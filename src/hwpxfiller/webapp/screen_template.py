"""템플릿 관리(tpl) 화면 컨트롤러 — HWPX·TXT 라이브러리 관리(webview 비의존).

목업 scr-tpl 의 웹 이관(에픽 #20, 화면 #13) → **R-info 2부 개편(#108)**. 링1 VM 을 **그대로
임포트**해 구동한다: HWPX 라이브러리 상태·상태별 게이트 액션·2단계 fieldize(스캔→적용)·lint 는
:class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`(Qt-free)가 소유한다.
TXT 관리는 코어 :class:`~hwpxfiller.core.text_registry.TextTemplateRegistry`(Qt-free)를 그대로
쓴다. 표현 계층(카드 렌더·확인 라운드트립)만 웹(js/screens/template.js)으로 이식한다.

**R-info 2부 개편(정본 `docs/R_INFO_JOB_HOME.md` 2부)**:
- **매체 = 구조, 그룹 = 그 안**(결정 3): HWPX/TXT 는 소비 동사를 가르는 경성 축이라 구획으로,
  그 안에서 **작업과 같은 그룹+접힘 모델**(결정 2). 그룹 상태는 매체별
  :class:`~hwpxfiller.webapp.template_groups.TemplateGroupModel` 이 소유(설정 영속).
- **식별키 = 루트 상대경로**(결정 8): 그룹 지정·이동·삭제의 대상 키. Explorer 개명·이동 시
  고아→「그룹 없음」 복귀(build_sections 가 live 행만 묶음 + reconcile 정리).
- **가져오기 = 루트로 복사**(결정 4): 확장자로 매체 라우팅. 「그룹 없음」에서 시작.
- **고정 루트**(결정 4): 「폴더 선택…」(라이브러리 재지정) 폐기 — 앱 소유 고정 루트가 정본
  (파편화 차단·습관 고정). 재지정은 세션 한정·비영속이라 잃을 저장 선택 없음.

**결정 반영(#13 승계)**:
- 미리보기(필드명·토큰) 액션 **제외**(10F2FF98-B) — 링1 seam 은 보존하되 노출 안 함.
- 판본 드리프트 비교는 **숨김/강등**(10F2FF98-D) — diff 는 앱 A(hwpxdiff) 책임.
파괴 확정(fieldize 적용·삭제)은 조용히 넘기지 않고 **확인 라운드트립**으로 재진술한다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

from ..core.template_status import default_templates_dir
from ..core.text_registry import TextTemplateRegistry
from ..gui.template_manager_state import TemplateManagerViewModel
from .screens import PushSink
from .template_groups import TemplateGroupModel, rel_key

# TXT 이름 검증 — Qt TemplateManagerPanel._validated_txt_name 미러(확장자·경로문자 배제).
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')

# HWPX 미리보기 액션은 작업 위저드와 중복이라 링2에서 노출하지 않는다(#13 10F2FF98-B).
_HIDDEN_ACTIONS = frozenset({"preview"})


class TemplateController:
    """템플릿 관리 화면 — HWPX 라이브러리 VM + TXT 레지스트리 + 매체별 그룹 모델(webview 비의존)."""

    name = "tpl"

    def __init__(
        self,
        text_registry: TextTemplateRegistry,
        push: PushSink,
        *,
        library_dir=None,
        hwpx_groups: "TemplateGroupModel | None" = None,
        txt_groups: "TemplateGroupModel | None" = None,
    ) -> None:
        self._push_sink = push
        self.text_registry = text_registry
        # 라이브러리 폴더 미지정이면 표준 라이브러리(~/.hwpxfiller/templates)를 겨눈다(고정 루트).
        self.vm = TemplateManagerViewModel(
            library_dir if library_dir is not None else default_templates_dir()
        )
        # 매체별 그룹+접힘 모델(결정 2·3) — 설정 영속의 단일 소유자. 주입은 테스트 편의.
        self.hwpx_groups = hwpx_groups if hwpx_groups is not None else TemplateGroupModel("hwpx")
        self.txt_groups = txt_groups if txt_groups is not None else TemplateGroupModel("txt")
        # 마지막 결과 문구(컴파일·검토·가져오기·TXT 변경) — 성과별 심각도 채널(UD-07).
        self.result_text = ""
        self.result_level = "muted"

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _set_result(self, line) -> None:
        """ResultLine(str 하위형, ``.level`` 보유) 또는 (text, level) 을 결과로 성형."""
        self.result_text = str(line)
        self.result_level = getattr(line, "level", "muted")

    def _model(self, media: str) -> TemplateGroupModel:
        """매체 문자열 → 그룹 모델. 오타는 loud(confirm-or-alarm)."""
        if media == "hwpx":
            return self.hwpx_groups
        if media == "txt":
            return self.txt_groups
        raise ValueError(f"알 수 없는 매체: {media!r}")

    # ------------------------------------------------------------- 스캔·행
    def _hwpx_rows(self) -> "list[dict]":
        root = self.vm.library_dir
        rows: "list[dict]" = []
        for r in self.vm.rows():
            key = rel_key(r.path, root)
            rows.append({
                "key": key,
                "group": self.hwpx_groups.group_of(key),
                "name": r.name,
                "path": r.path,
                "state": r.state.value if r.state is not None else "",
                "badge_label": r.badge_label,
                "badge_level": r.badge_level,
                "detail": r.detail_line(),
                "is_error": r.is_error,
                # 미리보기 제외(10F2FF98-B) — 링1 seam 은 보존하되 노출 액션에서 뺀다.
                "actions": [
                    {"key": a.key, "label": a.label}
                    for a in r.actions() if a.key not in _HIDDEN_ACTIONS
                ],
            })
        return rows

    def _txt_rows(self) -> "list[dict]":
        root = self.text_registry.directory
        rows: "list[dict]" = []
        for t in self.text_registry.list_templates():
            error = ""
            field_count = 0
            try:
                field_count = len(t.fields())
            except Exception as exc:  # noqa: BLE001 — 손상 파일도 삭제 가능한 행으로 loud 노출
                error = str(exc)
            key = rel_key(t.path, root)
            rows.append({
                "key": key,
                "group": self.txt_groups.group_of(key),
                "name": t.name,
                "path": str(t.path),
                "field_count": field_count,
                "error": error,
            })
        return rows

    def _media_snapshot(self, media: str, rows: "list[dict]", model: TemplateGroupModel) -> dict:
        """한 매체 구획의 스냅샷 — 유령 지정 정리 후 그룹 구획 뷰로 성형(작업 목록 동형)."""
        model.reconcile([r["key"] for r in rows])
        sections, flat = model.build_sections(rows, key_of=lambda r: r["key"])
        return {
            "sections": sections,
            "flat": flat,
            "group_names": model.existing_groups([r["key"] for r in rows]),
            "count": len(rows),
        }

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        hwpx_rows = self._hwpx_rows()
        txt_rows = self._txt_rows()
        hwpx = self._media_snapshot("hwpx", hwpx_rows, self.hwpx_groups)
        txt = self._media_snapshot("txt", txt_rows, self.txt_groups)
        hwpx["dir"] = str(self.vm.library_dir) if self.vm.library_dir is not None else ""
        hwpx["empty_hint"] = self.vm.empty_hint()
        txt["dir"] = str(self.text_registry.directory)
        return {
            "hwpx": hwpx,
            "txt": txt,
            "result": {"text": self.result_text, "level": self.result_level},
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def import_into_library(self, path: str) -> str:
        """가져오기 = 루트로 **복사**(결정 4) — 확장자로 매체 라우팅. 「그룹 없음」에서 시작.

        원본의 후속 이동·수정은 라이브러리 사본에 불파급. 이름 충돌은 조용히 덮지 않고
        ``이름 (2).ext`` 접미로 회피 + 결과 재진술. 관리 화면은 RAW(누름틀 0)도 받는다(그
        자리에서 변환하는 게 요점 — 에디터 가져오기의 RAW 거부와 다르다). 브리지가 부른다.
        """
        src = Path(path)
        suffix = src.suffix.lower()
        if suffix == ".hwpx":
            root = self.vm.library_dir
        elif suffix == ".txt":
            root = self.text_registry.directory
        else:
            raise ValueError("가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.")
        if root is None:
            raise ValueError("라이브러리 폴더가 지정되지 않았습니다.")
        root.mkdir(parents=True, exist_ok=True)
        dest = root / src.name
        n = 2
        while dest.exists():
            dest = root / f"{src.stem} ({n}){src.suffix}"
            n += 1
        shutil.copy2(src, dest)
        if suffix == ".hwpx":
            self.vm.refresh()  # TXT 는 snapshot 의 list_templates 가 매번 재스캔
        renamed = f" (이름 충돌로 '{dest.name}')" if dest.name != src.name else ""
        self._set_result(
            _ok(f"'{src.name}' 을 라이브러리로 가져왔습니다{renamed} — 「그룹 없음」에서 시작합니다.")
        )
        self._push()
        return dest.name

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 tpl 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_refresh(self, p: dict) -> None:
        """라이브러리 재스캔(F5 짝) — compile_status 매번 재산출."""
        self.result_text = ""
        self.result_level = "muted"
        self.vm.refresh()

    # ---- HWPX 상태 게이트 액션
    def _do_compile(self, p: dict) -> dict:
        """CLI 2단계 미러 — 스캔 미리보기(dry-run) → 확인 라운드트립 → 적용·저장.

        1차 호출(``confirm`` 없음): 스캔만. 변환 가능 토큰이 없으면 인라인 결과로 통지하고
        끝(파괴 아님). 있으면 ``needs_confirm`` 으로 미리보기를 재진술 — 조용히 파일을 만지지
        않는다. 2차 호출(``confirm``): 실제 컴파일·저장.
        """
        path = p["path"]
        if p.get("confirm"):
            report = self.vm.apply_fieldize(path)
            self._set_result(self.vm.format_compile_result(path, report))
            return {"ok": True, "applied": True}
        preview = self.vm.scan_preview(path)
        if not preview.has_compilable:
            # UD-24: '변환 가능 토큰 없음'은 차단 모달이 아니라 인라인 결과로(파괴 아님).
            self._set_result(self.vm.format_scan_empty_result(path, preview))
            return {"ok": True, "applied": False}
        lines = [preview.summary(), ""]
        lines.extend(f"+ {s.name}" for s in preview.compilable)
        lines.extend(f"! {s.name} — {s.reason}" for s in preview.skipped)
        lines.append(f"\n지금 누름틀로 변환하면 파일이 제자리에서 변경됩니다: {Path(path).name}")
        return {"ok": True, "needs_confirm": True, "confirm_text": "\n".join(lines), "path": path}

    def _do_review(self, p: dict) -> dict:
        """lint 점검(읽기 전용) → 결과 문구(심각도 채널)."""
        path = p["path"]
        report = self.vm.lint(path)
        self._set_result(self.vm.format_lint_result(path, report))
        return {"ok": True}

    # ---- 그룹 관리(작업 목록과 단일 모델 · 결정 2)
    def _do_set_group(self, p: dict) -> None:
        """그룹 지정/해제(이동 다이얼로그·＋그룹지정 칩 확정) — ``group=""`` 는 「그룹 없음」.

        새 그룹 = 다이얼로그의 새 이름 입력이 이 액션으로 그대로 들어온다(소속=생성,
        빈 그룹 불가 불변식은 모델 구조가 담보)."""
        self._model(p["media"]).set_group(p["key"], p.get("group", ""))

    def _do_toggle_group(self, p: dict) -> None:
        """그룹 접힘/펼침 토글 — 마지막 상태를 매체별 설정에 영속(결정 6-①). ``""``=「그룹 없음」."""
        self._model(p["media"]).toggle_collapse(p["group"])

    def _do_rename_group(self, p: dict) -> dict:
        """그룹 이름 변경 — 새 이름이 **기존 그룹**이면 병합이므로 확인 승격(무확인 반환).

        모델이 remap·접힘 승계를 진다(순수 개명=이월, 병합=대상 접힘 존중). 화면은 병합 여부만
        판정해 재진술한다(screen_job._do_rename_group 동형)."""
        model = self._model(p["media"])
        old = p["group"]
        new = p.get("new", "").strip()
        if not new:
            return {"ok": False, "error": "그룹 이름이 비어 있습니다."}
        live = self._live_keys(p["media"])
        if new != old and not p.get("confirm"):
            target = sum(1 for k in live if model.group_of(k) == new)
            if target:
                count = sum(1 for k in live if model.group_of(k) == old)
                return {"needs_confirm": True, "kind": "merge_group",
                        "group": old, "new": new, "count": count, "target": target}
        count = model.rename_group(old, new)
        return {"ok": True, "count": count}

    def _do_disband_group(self, p: dict) -> dict:
        """그룹 해산(결정 43) — 무확인 호출은 소속 수 재진술로 멈춘다. 소속은 「그룹 없음」으로."""
        model = self._model(p["media"])
        name = p["group"]
        if not p.get("confirm"):
            count = sum(1 for k in self._live_keys(p["media"]) if model.group_of(k) == name)
            return {"needs_confirm": True, "kind": "disband_group", "group": name, "count": count}
        count = model.disband_group(name)
        return {"ok": True, "count": count}

    def _live_keys(self, media: str) -> "list[str]":
        """현 스캔의 살아있는 식별키 — 그룹 소속 수 판정용(캐시된 행 소비, 재파싱 없음)."""
        if media == "hwpx":
            root = self.vm.library_dir
            return [rel_key(r.path, root) for r in self.vm.rows()]
        root = self.text_registry.directory
        return [rel_key(t.path, root) for t in self.text_registry.list_templates()]

    # ---- 삭제(HWPX·TXT 공통 · 파괴이므로 확인 라운드트립)
    def _do_delete(self, p: dict) -> dict:
        """템플릿 삭제 — 1차=재진술(매체별 파급 명시), 2차=삭제. 그룹 지정은 reconcile 이 정리."""
        media = p["media"]
        path = Path(p["path"])
        if not p.get("confirm"):
            if media == "txt":
                body = f"삭제하면 기안문 채우기·빠른 기안 목록에서도 사라집니다:\n{path}"
            else:
                body = (
                    "이 서식으로 새 작업을 만들 수 없게 되고, 이 서식을 쓰는 작업은 템플릿을 "
                    f"다시 연결해야 합니다:\n{path}"
                )
            return {"ok": True, "needs_confirm": True, "media": media,
                    "path": str(path), "confirm_text": body}
        path.unlink()
        if media == "hwpx":
            self.vm.refresh()
        self._set_result(_ok(f"템플릿을 삭제했습니다: {path.stem}"))
        return {"ok": True}

    # ---- TXT 저작(HWPX와 동등 · 10F2FF98-C)
    def _validated_txt_name(self, raw_name: str) -> str:
        """확장자·경로문자를 배제한 순수 이름만 허용(Qt _validated_txt_name 미러). 실패는 loud raise."""
        name = raw_name.strip()
        if not name:
            raise ValueError("템플릿 이름을 입력해 주세요.")
        if name.lower().endswith(".txt") or _BAD_NAME.search(name) or name in (".", ".."):
            raise ValueError("확장자와 경로 문자를 제외한 이름만 입력해 주세요.")
        return name

    def _do_txt_new(self, p: dict) -> dict:
        """새 TXT 템플릿 생성 — 이름 검증·중복 차단 후 원자 쓰기."""
        name = self._validated_txt_name(p.get("name", ""))
        content = p.get("content", "")
        path = self.text_registry.directory / f"{name}.txt"
        if path.exists():  # confirm-or-alarm: 조용한 덮어쓰기 금지 — 시끄럽게 거부.
            raise ValueError(f"이미 같은 이름의 템플릿이 있습니다: {name}")
        self.text_registry.directory.mkdir(parents=True, exist_ok=True)
        write_text_atomic(str(path), content)
        self._set_result(_ok(f"TXT 템플릿을 만들었습니다: {name}"))
        return {"ok": True, "name": name}

    def _do_txt_edit(self, p: dict) -> dict:
        """기존 TXT 템플릿 내용 저장 — 원자 쓰기."""
        path = Path(p["path"])
        write_text_atomic(str(path), p.get("content", ""))
        self._set_result(_ok(f"TXT 템플릿을 저장했습니다: {path.stem}"))
        return {"ok": True}

    def _do_txt_content(self, p: dict) -> dict:
        """편집 모달용 현재 내용 반환(읽기 전용). 읽기 실패는 loud raise."""
        return {"content": Path(p["path"]).read_text(encoding="utf-8")}


def _ok(text: str):
    """성공 결과 라인(ok 레벨) — ResultLine 재사용을 피해 경량 성형."""
    from ..gui.template_manager_state import ResultLine

    return ResultLine(text, "ok")
