"""템플릿 관리(tpl) 화면 컨트롤러 — HWPX·TXT 라이브러리 관리(webview 비의존).

목업 scr-tpl 의 웹 이관(에픽 #20, 화면 #13). 링1 VM 을 **그대로 임포트**해 구동한다:
HWPX 라이브러리 상태·상태별 게이트 액션·2단계 fieldize(스캔→적용)·lint 는
:class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`(Qt-free)가 소유한다.
TXT 관리는 코어 :class:`~hwpxfiller.core.text_registry.TextTemplateRegistry`(Qt-free)를 그대로
쓴다. 표현 계층(카드 렌더·확인 라운드트립)만 웹(js/screens/template.js)으로 이식한다 —
VM 로직 재구현이 아니다.

**[B] 렌더 버그 해소(61C7ADF8)**: Qt QListWidget 카드 선택 하이라이트가 반투명이라 숨긴
아이템 텍스트가 비쳐 겹쳐 보이던 렌더 버그를, 웹 카드는 불투명 배경 div 라 **구성상 소멸**
시킨다(숨긴 텍스트 레이어 자체가 없음) — 이관이 곧 수정.

**결정 반영(#13)**:
- 미리보기(필드명·토큰) 액션 **제외**(10F2FF98-B, 작업 위저드와 중복) — ``preview`` 액션은
  링1 seam 은 보존하되 화면에 노출하지 않는다(Qt TemplateCard 와 동형).
- TXT 템플릿 **HWPX와 동등 관리**(10F2FF98-C) — 열기·편집·생성·삭제.
- 판본 드리프트 비교는 **숨김/강등**(10F2FF98-D) — diff 는 앱 A(hwpxdiff) 책임. 링1
  ``drift()`` seam 은 보존하되 UI 미노출.

**이번 이관의 스코프 경계(조용히 빠뜨리지 않고 명시)** — 아래는 미구현이며 후속 이관 대상이다
(confirm-or-alarm: 없는 기능을 있는 척하지 않는다):
- 템플릿 구조화·순서 조정(10F2FF98-E, 보류) · 어휘(vocabulary) 주입 lint · FILLED 값 미리보기.
파괴 확정(fieldize 적용·TXT 삭제)은 조용히 넘기지 않고 **확인 라운드트립**으로 재진술한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

from ..core.template_status import default_templates_dir
from ..core.text_registry import TextTemplateRegistry
from ..gui.template_manager_state import TemplateManagerViewModel
from .screens import PushSink

# TXT 이름 검증 — Qt TemplateManagerPanel._validated_txt_name 미러(확장자·경로문자 배제).
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')

# HWPX 미리보기 액션은 작업 위저드와 중복이라 링2에서 노출하지 않는다(#13 10F2FF98-B).
_HIDDEN_ACTIONS = frozenset({"preview"})


class TemplateController:
    """템플릿 관리 화면 — HWPX 라이브러리 VM + TXT 레지스트리 위임(webview 비의존)."""

    name = "tpl"

    def __init__(
        self,
        text_registry: TextTemplateRegistry,
        push: PushSink,
        *,
        library_dir=None,
    ) -> None:
        self._push_sink = push
        self.text_registry = text_registry
        # 라이브러리 폴더 미지정이면 표준 라이브러리(~/.hwpxfiller/templates)를 겨눈다(Qt 미러).
        self.vm = TemplateManagerViewModel(
            library_dir if library_dir is not None else default_templates_dir()
        )
        # 마지막 결과 문구(컴파일·검토·TXT 변경) — 성과별 심각도 채널(UD-07).
        self.result_text = ""
        self.result_level = "muted"

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _set_result(self, line) -> None:
        """ResultLine(str 하위형, ``.level`` 보유) 또는 (text, level) 을 결과로 성형."""
        self.result_text = str(line)
        self.result_level = getattr(line, "level", "muted")

    # ------------------------------------------------------------- 스냅샷
    def _hwpx_rows(self) -> "list[dict]":
        rows: "list[dict]" = []
        for r in self.vm.rows():
            rows.append({
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
        rows: "list[dict]" = []
        for t in self.text_registry.list_templates():
            error = ""
            field_count = 0
            try:
                field_count = len(t.fields())
            except Exception as exc:  # noqa: BLE001 — 손상 파일도 삭제 가능한 행으로 loud 노출
                error = str(exc)
            rows.append({
                "name": t.name,
                "path": str(t.path),
                "field_count": field_count,
                "error": error,
            })
        return rows

    def snapshot(self) -> dict:
        return {
            "hwpx_rows": self._hwpx_rows(),
            "hwpx_count": self.vm.count_label(),
            "hwpx_empty": self.vm.is_empty(),
            "empty_hint": self.vm.empty_hint(),
            "library_dir": str(self.vm.library_dir) if self.vm.library_dir is not None else "",
            "txt_rows": self._txt_rows(),
            "txt_dir": str(self.text_registry.directory),
            "result": {"text": self.result_text, "level": self.result_level},
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def set_library_dir(self, path: str) -> None:
        """라이브러리 폴더 재지정(네이티브 폴더 피커) — 재스캔하고 스테일 결과는 초기화."""
        self.result_text = ""
        self.result_level = "muted"
        self.vm.set_library_dir(path)
        self._push()

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
        """lint 위생 점검(읽기 전용) → 결과 문구(심각도 채널)."""
        path = p["path"]
        report = self.vm.lint(path)
        self._set_result(self.vm.format_lint_result(path, report))
        return {"ok": True}

    # ---- TXT 관리(HWPX와 동등 · 10F2FF98-C)
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

    def _do_txt_delete(self, p: dict) -> dict:
        """TXT 템플릿 삭제 — 파괴이므로 확인 라운드트립(1차=재진술, 2차=삭제)."""
        path = Path(p["path"])
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "path": str(path),
                "confirm_text": f"삭제하면 즉시 기안 목록에서도 사라집니다:\n{path}",
            }
        path.unlink()
        self._set_result(_ok(f"TXT 템플릿을 삭제했습니다: {path.stem}"))
        return {"ok": True}


def _ok(text: str):
    """성공 결과 라인(ok 레벨) — ResultLine 재사용을 피해 경량 성형."""
    from ..gui.template_manager_state import ResultLine

    return ResultLine(text, "ok")
