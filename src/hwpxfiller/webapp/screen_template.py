"""템플릿 라이브러리(tpl) 채널 컨트롤러 — HWPX·TXT 라이브러리 관리(webview 비의존).

**화면은 죽고 채널은 산다(F8 §10.17.2 판정 B — F1 pool 선례)**: 「템플릿 관리」 화면
(scr-tpl·template.js)은 사망했고, 이 컨트롤러의 12액션·잠금 규율·경로 검증·휴지통은
편집기 「템플릿」 탭(editor.js)이 리터럴 `Bridge.call("tpl", …)` 로 그대로 소비한다.
push 스냅샷의 생존 소비자 = 편집기 결과 줄(result) + 재당김 신호.

링1 VM 을 **그대로 임포트**해 구동한다: HWPX 라이브러리 상태·상태별 게이트 액션·2단계
fieldize(스캔→적용)·lint 는
:class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`(Qt-free)가 소유한다.
TXT 관리는 코어 :class:`~hwpxfiller.core.text_registry.TextTemplateRegistry`(Qt-free)를 그대로
쓴다. 표현 계층(행 렌더·확인 라운드트립)은 편집기 「템플릿」 탭(editor.js)이 소유한다.

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
제자리 fieldize 적용은 확인 라운드트립으로 지키고, 삭제는 30일 휴지통+최근 1건 복원으로 완화한다.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from hwpxcore.atomic import write_text_atomic

from ..core.template_status import TRASH_DIR_NAME, default_templates_dir
from ..core.text_registry import TextTemplateRegistry
from ..gui.template_manager_state import TemplateManagerViewModel
from .screens import PushSink
from .template_groups import TemplateGroupModel, rel_key, validate_template_name

# HWPX 미리보기 액션은 작업 위저드와 중복이라 링2에서 노출하지 않는다(#13 10F2FF98-B).
_HIDDEN_ACTIONS = frozenset({"preview"})


class TemplateController:
    """템플릿 라이브러리 채널 — HWPX 라이브러리 VM + TXT 레지스트리 + 매체별 그룹 모델(webview 비의존)."""

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
        # 가져오기 직렬화 잠금(#137 리뷰 F9) — pywebview 네이티브 호출은 별도 스레드라 같은
        # basename 동시 가져오기가 이름 선점~복사 사이 무경계로 겹쳐 두 호출이 같은 목적지를
        # 골라 내용 하나만 남는다. 후보 선택~복사를 이 잠금으로 직렬화한다(JobRegistry.clone 동형).
        self._import_lock = threading.Lock()
        # 폴더 배치 가져오기의 동시 실행 거절 잠금(PR #355 2R) — _import_lock 은 개별 복사만
        # 직렬화해 두 배치가 교차하면 같은 목록이 번호 접미로 재반입된다. 배치 중복의 판정은
        # 여기 **한 곳**(비차단 획득 실패 = loud 거절)이고, JS 는 어포던스만 잠근다.
        self._folder_import_lock = threading.Lock()
        # 마지막 결과 문구(컴파일·검토·가져오기·TXT 변경) — 성과별 심각도 채널(UD-07).
        self.result_text = ""
        self.result_level = "muted"
        # 최근 삭제 1건 복원 슬롯 — (media, 원경로, 휴지통경로, 삭제 시점 그룹). 그룹을 슬롯에
        # 보존해야 한다(#269 리뷰): 삭제 직후 스냅샷 푸시의 reconcile 이 사라진 키의 그룹 지정을
        # 영구 제거하므로, 복원 시 파일만 돌아오면 조용히 「그룹 없음」이 된다.
        self._deleted_template_slot: "tuple[str, Path, Path, str] | None" = None

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
        raise ValueError(f"알 수 없는 형식: {media!r}")

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
                # 채움 완화 사전 고지(#154) — 문안은 링1(describe_precheck_note) 확정.
                "fill_warns": list(r.fill_warns),
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
        txt["dir"] = str(self.text_registry.directory)
        # (고지②(휘발 「기안」 폐지 재진술)와 empty_hint 는 tpl 화면과 함께 사망(F8 §10.17) —
        # 빈 밴드 안내는 편집기 「템플릿」 탭이 자기 문안으로 소유한다. 고지①(job txt_note)은
        # 존치. 이 스냅샷의 생존 소비자 = 편집기 결과 줄(result)·재당김 신호.)
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

        복사 몸통(잠금·라우팅·접미·무잔재)은 :meth:`_copy_into_library` — 배치와 공유."""
        src = Path(path)
        dest = self._copy_into_library(src)
        if src.suffix.lower() == ".hwpx":
            self.vm.refresh()  # TXT 는 snapshot 의 list_templates 가 매번 재스캔
        renamed = f" (이름 충돌로 '{dest.name}')" if dest.name != src.name else ""
        self._set_result(
            _ok(f"'{src.name}' 을 라이브러리로 가져왔습니다{renamed}. '그룹 없음'에서 시작합니다.")
        )
        self._push()
        # 전체 경로 반환(F8 판정 C) — 편집기 채택 판정(adopt_imported_template)이 사본의
        # 정확한 목적지를 알아야 한다(충돌 접미로 이름이 바뀔 수 있다). 프런트 소비자는
        # "ERROR:" 접두 검사뿐이라 이름→경로 확장은 무해.
        return str(dest)

    # ---------------------------- 폴더 일괄 가져오기(#339 · U2 §2.16 narrow) — 스캔/실행 2박자
    def _folder_candidates(self, folder: Path) -> "tuple[list[Path], int]":
        """폴더 **직속**(1단계) 파일에서 가져올 후보(.hwpx/.txt)와 제외 파일 수.

        하위 폴더는 훑지 않는다(§2.16 narrow) — 재귀는 트리→그룹 유도·중복 병합 정책을
        먼저 정해야 하는 별건이다. 이름순 정렬 = 재진술과 실행이 같은 결정적 순서."""
        files = sorted(
            (p for p in folder.iterdir() if p.is_file()),
            key=lambda p: p.name.casefold(),
        )
        candidates = [p for p in files if p.suffix.lower() in (".hwpx", ".txt")]
        return candidates, len(files) - len(candidates)

    def scan_import_folder(self, folder: str) -> dict:
        """가져오기 재진술 스캔(읽기 전용) — **확정 전에는 홈에 아무것도 쓰지 않는다**.

        수치(매체별 건수·제외 수·이름 충돌 수)와 완성 재진술 문안을 함께 돌려준다 — 표면이
        수치로 문안을 재조립하면 두 답이 생긴다(판정·문안은 Python, 확인 UI 는 웹). 후보 0
        은 확인이 아니라 loud 거절이다(가져올 것 없는 확정을 시키지 않는다). 브리지가 부른다.

        ``files`` = 확정 대상 후보 목록(이름) — 실행(:meth:`import_folder`)은 재스캔이 아니라
        **이 목록에 결속**된다(PR #355 리뷰): 스캔~확정 사이 폴더가 바뀌어도 확인 안 된
        파일이 따라 들어오지 않는다(재진술이 참이 되게)."""
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"폴더를 찾을 수 없습니다: {folder}")
        candidates, skipped = self._folder_candidates(root)
        if not candidates:
            note = (
                " 하위 폴더는 살펴보지 않습니다."
                if any(p.is_dir() for p in root.iterdir()) else ""
            )
            return {
                "ok": False,
                "error": f"'{root.name}' 폴더 바로 아래에 가져올 .hwpx/.txt 파일이 없습니다.{note}",
            }
        hwpx = sum(1 for p in candidates if p.suffix.lower() == ".hwpx")
        txt = len(candidates) - hwpx
        collisions = sum(1 for p in candidates if self._import_dest_taken(p))
        lines = [f"'{root.name}' 폴더에서 라이브러리로 가져옵니다:"]
        counts = [f"HWPX 서식 {hwpx}건"] if hwpx else []
        if txt:
            counts.append(f"TXT 기안 {txt}건")
        lines.append("- " + " · ".join(counts))
        if skipped:
            lines.append(f"- 나머지 파일 {skipped}개는 가져오지 않습니다(.hwpx/.txt 아님)")
        lines.append("- 하위 폴더는 살펴보지 않습니다")
        if collisions:
            # 「(2)」라 단정하지 않는다(PR #355 리뷰) — 이미 (2)까지 있으면 (3)이 붙는다.
            # 정확한 접미는 복사 시점 잠금 안에서 정해지므로 정책(번호 접미)만 재진술한다.
            lines.append(f"- 이름 충돌 {collisions}건은 이름 뒤 번호 접미로 가져옵니다")
        return {
            "needs_confirm": True, "folder": str(root),
            "hwpx": hwpx, "txt": txt, "skipped": skipped, "collisions": collisions,
            "files": [p.name for p in candidates],
            "confirm_text": "\n".join(lines),
        }

    def _import_dest_taken(self, src: Path) -> bool:
        """가져오기 목적지(매체 루트/원래 이름)가 이미 있는가 — 충돌 수 재진술용(무변이)."""
        root = self.vm.library_dir if src.suffix.lower() == ".hwpx" else self.text_registry.directory
        return root is not None and (Path(root) / src.name).exists()

    def _copy_into_library(self, src: Path) -> Path:
        """복사 권위 **몸통** — 매체 라우팅·잠금·충돌 번호 접미·무잔재. refresh/결과/push 없음.

        단건(:meth:`import_into_library`)과 배치(:meth:`import_folder`)가 같은 몸통을 쓴다 —
        배치는 항목별 전체 리프레시·push 를 유예하고 완료 후 1회만 민다(PR #355 리뷰: N건
        가져오기가 N번의 라이브러리 재스캔+전체 재렌더가 되는 준-제곱 정지 방지).

        **직렬화**(F9): 후보 선택~복사를 인스턴스 잠금으로 묶어 동시 동명 가져오기가 같은
        목적지를 골라 내용 하나만 남는 경합을 막는다. **무잔재**(F6): 복사 중 실패하면(디스크
        풀·원본 판독 불가) 부분 파일을 걷어내고 재던진다 — 다음 새로고침이 잘린 TXT/손상 HWPX
        를 목록에 노출하고 충돌 접미가 재시도를 막는 것을 방지(에디터 import_template 동형).

        **TXT 는 공유 writer 축에 함께 선다**(PR #355 P1): ``_import_lock`` 은 가져오기끼리만
        아는 잠금이라, 배치가 도는 동안 사용자가 「새 TXT」·내용 편집·복원을 하면 두 writer 가
        서로를 모른 채 같은 이름을 겨눈다 — 목적지가 「비었다」고 고른 뒤 그 사이 채워지면
        ``copy2`` 가 방금 쓴 내용을 덮고(반대 방향도 같다), 충돌 접미가 지켜야 할 사용자
        내용이 조용히 사라진다. 그래서 TXT 항목은 목적지 선택~복사를 다른 TXT writer 와
        **같은 잠금**(:meth:`~hwpxfiller.core.text_registry.TextTemplateRegistry.write_lock`)
        안에서 한다. 획득은 **항목 단위**라 배치가 도는 내내 TXT 조작이 통째로 막히지 않는다.

        **잠금 획득 순서 규약**: ``_folder_import_lock``(배치) → ``_import_lock``(가져오기)
        → ``text_registry.write_lock()``(TXT writer). 항상 안쪽으로만 잡는다. 역순 획득
        경로는 없다 — TXT writer 를 먼저 잡는 쪽(``_do_txt_new``·``_do_txt_edit``·
        ``_do_undo_delete``)은 어느 것도 가져오기 잠금을 잡지 않으므로 순환 대기가 성립하지
        않는다. 새 writer 를 더할 때도 이 순서를 지킨다."""
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
        # HWPX 는 공유 writer 가 없는 단일 표면이라 가져오기 잠금 하나면 족하다(_do_undo_delete
        # 의 매체 분기와 같은 비대칭 — 없는 축을 흉내내지 않는다).
        txt_writer = (
            self.text_registry.write_lock() if suffix == ".txt" else nullcontext()
        )
        with self._import_lock, txt_writer:
            dest = root / src.name
            n = 2
            while dest.exists():
                dest = root / f"{src.stem} ({n}){src.suffix}"
                n += 1
            try:
                shutil.copy2(src, dest)
            except Exception:
                dest.unlink(missing_ok=True)  # 반가져오기 잔재 제거
                raise
        return dest

    def import_folder(self, folder: str, files: "list[str]") -> dict:
        """확정 후 실행 — **확정 시점 후보 목록**(``files``)을 복사 몸통으로 반복한다.

        재스캔하지 않는다(PR #355 리뷰): 스캔~확정 사이 폴더에 새 파일이 와도 재진술에
        없던 것은 들어오지 않고, 확정된 파일이 사라졌으면 그 건만 부분 실패로 사유 병기.
        각 건이 단건과 같은 잠금·매체 라우팅·충돌 번호 접미·무잔재를 상속하고, 항목별
        전체 리프레시·push 는 유예해 완료 후 1회만 민다. 결과 줄은 배치 요약으로 재진술:
        「N건 중 M건 등록 · K건 실패(사유)」. 채택은 없다 — 편집 세션은 이 메서드가 모르는
        남의 상태다(세션 무변경).

        ``files`` 검증은 여기(권위 소유자)가 진다: 비어 있지 않은 문자열 **basename** 목록
        (경로 구분자·상위 탈출 불가)에 허용 확장자만 — 임의 경로 반입 승격을 막는다.

        **동시 배치 거절**(PR #355 2R): 배치 진행 중 재실행은 비차단 잠금 실패 = loud
        거절 — 두 배치가 교차하면 같은 목록이 번호 접미로 재반입되고 완료 푸시 2회가
        오해를 낳는다. JS 의 in-flight 플래그는 어포던스 잠금이고 판정 정본은 이 잠금
        하나다(같은 상태를 두 곳이 판정하지 않는다)."""
        if not self._folder_import_lock.acquire(blocking=False):
            raise ValueError("폴더 가져오기가 이미 진행 중입니다. 끝난 뒤 다시 시도하세요.")
        try:
            root = Path(folder)
            if not root.is_dir():
                raise ValueError(f"폴더를 찾을 수 없습니다: {folder}")
            if not files or not isinstance(files, list):
                raise ValueError("확정된 가져오기 목록이 비어 있습니다.")
            for name in files:
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or Path(name).name != name      # 구분자·'..' 등 basename 밖 형태 차단
                    or Path(name).suffix.lower() not in (".hwpx", ".txt")
                ):
                    raise ValueError(f"가져오기 목록에 올 수 없는 항목입니다: {name!r}")
            imported = 0
            imported_hwpx = 0
            failed: "list[tuple[str, str]]" = []
            for name in sorted(files, key=str.casefold):     # 재진술과 같은 결정적 순서
                src = root / name
                if not src.is_file():
                    failed.append((name, "확정 뒤 폴더에서 사라졌습니다"))
                    continue
                try:
                    self._copy_into_library(src)
                    imported += 1
                    if src.suffix.lower() == ".hwpx":
                        imported_hwpx += 1
                except Exception as exc:  # noqa: BLE001 — 한 건의 실패가 나머지를 막지 않는다(사유 병기)
                    failed.append((name, str(exc)))
            if imported_hwpx:
                self.vm.refresh()  # 배치 완료 후 1회 — TXT 는 snapshot 이 매번 재스캔
            total = len(files)
            if failed:
                from ..gui.template_manager_state import ResultLine  # _ok 동형(경량 성형)

                reasons = " · ".join(f"{name}: {err}" for name, err in failed)
                self._set_result(ResultLine(
                    f"{total}건 중 {imported}건 등록 · {len(failed)}건 실패({reasons})", "warn",
                ))
            else:
                self._set_result(_ok(
                    f"'{root.name}' 폴더에서 {total}건을 가져왔습니다. '그룹 없음'에서 시작합니다."
                ))
            self._push()
            return {
                "ok": not failed, "imported": imported, "total": total,
                "failed": [{"name": name, "error": err} for name, err in failed],
            }
        finally:
            self._folder_import_lock.release()

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

    @staticmethod
    def _norm(path: "str | Path") -> str:
        """경로 정규화(대소문자·구분자·심볼릭 해소) — 라이브 집합 대조용 단일 형식."""
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(Path(path))

    def _live_paths(self, media: str) -> "set[str]":
        """이 매체 라이브러리의 현재 목록에 실재하는 파일 경로 집합(정규화) — 삭제 대상 검증용."""
        if media == "hwpx":
            return {self._norm(r.path) for r in self.vm.rows()}
        return {self._norm(t.path) for t in self.text_registry.list_templates()}

    # ---- 삭제(HWPX·TXT 공통 · 30일 휴지통 + 최근 1건 복원)
    def _do_delete(self, p: dict) -> dict:
        """템플릿을 매체 루트의 .trash로 옮긴다. 그룹은 슬롯에 보존(복원 시 재지정), 스토어의
        지정 자체는 reconcile 이 정리.

        **경로 검증**(#137 리뷰 F10): 렌더러 페이로드의 ``media``·``path`` 를 그대로 unlink 하면
        라이브러리 밖 임의 파일도 지워진다. 매체를 열거 검증하고(``_model``), 경로가 그 매체
        라이브러리의 **현재 목록**에 속하는지 정규화 후 대조해 임의 파일 삭제 권한 승격을 막는다."""
        media = p["media"]
        model = self._model(media)  # 매체 열거 검증(오타·미지 매체 loud)
        path = Path(p["path"])
        if self._norm(path) not in self._live_paths(media):
            raise ValueError("현재 라이브러리 목록에 없는 경로는 삭제할 수 없습니다.")
        root = self.vm.library_dir if media == "hwpx" else self.text_registry.directory
        # 그룹은 이동 전에 떠 둔다 — 이동 직후 reconcile 이 이 키의 지정을 영구 제거한다.
        group = model.group_of(rel_key(path, Path(root)))
        trash = Path(root) / TRASH_DIR_NAME
        trash.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 30 * 24 * 60 * 60
        for old in trash.iterdir():
            try:
                if old.is_file() and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                continue
        trashed = trash / f"{int(time.time())}-{uuid.uuid4().hex}-{path.name}"
        path.replace(trashed)
        self._deleted_template_slot = (media, path, trashed, group)
        if media == "hwpx":
            self.vm.refresh()
        # 삭제 확인은 **UndoToast 하나**다(U2 §2.12 자리 3, #345 — PR #353 1R): 결과줄에도
        # 실으면 같은 말을 두 번 하고, 되돌리기 어포던스를 든 토스트가 이긴다. 문안 자체도
        # 「휴지통」이라 말하지 않는다 — .trash 30일 보존은 실재하지만 도달 표면이 아직 없다
        # (별건 #350). 보존 기제(위 컷오프 정리·이동)는 삭제가 상속하는 의무라 지우지 않는다.
        #
        # 다만 **말하지 않는 것과 남의 말을 남기는 것은 다르다**(2R): 직전 행동(TXT 생성·편집·
        # 검토·가져오기)이 채워 둔 결과줄을 안 건드리면 dispatch 의 push 가 그 문장을 다시
        # 실어, 지운 직후 화면에 삭제와 무관한 문장이 삭제의 결과인 것처럼 선다. 그래서
        # 이 자리는 비운다(_do_refresh 와 같은 초기화 — 삭제 경로에만 적용).
        self.result_text = ""
        self.result_level = "muted"
        return {"ok": True, "undo": True, "name": path.stem}

    def _do_undo_delete(self, p: dict) -> dict:
        """휴지통 최근 1건 복원 — TXT 는 **복원 전 구간**이 writer 락 임계구역(#268/#280 리뷰).

        TXT 는 존재 검사와 ``replace`` 사이에 다른 pywebview 호출(새 템플릿·템플릿으로 저장)이
        같은 이름을 새로 쓸 수 있다 — 무락이면 복원이 그 새 파일을 조용히 덮거나, 동시 writer 가
        복원본을 즉시 덮는다. :meth:`~hwpxfiller.core.text_registry.TextTemplateRegistry.write_lock`
        을 존재 검사~교체~그룹 복원~실패 롤백까지 한 임계구역으로 잡는다(부분만 덮으면 롤백
        ``replace`` 가 락 밖에서 동시 편집을 쓸어 넣는다 — 3R). HWPX 는 공유 writer 락이 없는
        단일 표면이라 무락 동일 몸통. 복원 후 삭제 시점 그룹을 재지정한다(#269 리뷰) —
        삭제 직후 reconcile 이 지정을 지웠으므로 슬롯의 그룹이 유일한 생존 기록이다."""
        if self._deleted_template_slot is None:
            return {"ok": False, "error": "복원할 최근 템플릿이 없습니다."}
        media, path, trashed, group = self._deleted_template_slot

        def restore_and_regroup() -> "dict | None":
            """복원의 **모든 durable 변이**(존재 검사~이동~그룹 복원~실패 롤백) 한 몸통.

            TXT 는 이 전체가 writer 락 임계구역 안이어야 한다(#280 리뷰 3R) — 이동만 락으로
            덮고 그룹 복원·롤백을 밖에 두면, 락 해제 후 동시 writer 가 같은 이름을 새로 쓴
            뒤 설정 쓰기가 실패했을 때 롤백 ``replace`` 가 그 새 내용을 무락으로 휴지통에
            쓸어 넣는다(재시도 Undo = 엉뚱한 내용 복원 + 동시 편집 소실).
            """
            if not trashed.exists():
                # 「휴지통」 없이 말한다(#345) — 사용자에게 그 장소는 도달 불가라 이름만 있는
                # 공간이다. 실패 사실(파일 부재)만 재진술한다.
                return {"ok": False, "error": "되돌릴 템플릿 파일을 찾을 수 없습니다."}
            if path.exists():
                return {"ok": False, "error": "같은 이름의 템플릿이 이미 있어 복원할 수 없습니다."}
            path.parent.mkdir(parents=True, exist_ok=True)
            trashed.replace(path)
            if group:
                # 그룹 복원까지 성공해야 슬롯을 비운다(#280 리뷰) — 슬롯이 삭제 시점 그룹의
                # 유일한 생존 기록이라, 설정 쓰기 실패 후 슬롯을 이미 비웠다면 재시도가
                # "복원할 템플릿이 없습니다"로 막히고 템플릿은 조용히 「그룹 없음」이 된다.
                # 실패 시 파일 이동을 되돌려(슬롯↔실상태 정합) 재시도를 가능하게 남긴다.
                try:
                    root = (
                        self.vm.library_dir if media == "hwpx"
                        else self.text_registry.directory
                    )
                    self._model(media).set_group(rel_key(path, Path(root)), group)
                except Exception:
                    path.replace(trashed)  # 이동 롤백 — 슬롯은 그대로, Undo 재시도 가능
                    raise
            return None

        if media == "txt":
            with self.text_registry.write_lock():
                error = restore_and_regroup()
        else:
            error = restore_and_regroup()
        if error is not None:
            return error
        self._deleted_template_slot = None
        if media == "hwpx":
            self.vm.refresh()
        self._set_result(_ok(f"템플릿을 복원했습니다: {path.stem}"))
        return {"ok": True, "name": path.stem}

    # ---- TXT 저작(HWPX와 동등 · 10F2FF98-C)
    def _do_txt_new(self, p: dict) -> dict:
        """새 TXT 템플릿 생성 — 이름 검증·중복 차단 후 원자 쓰기.

        존재 검사~쓰기는 공유 :meth:`~hwpxfiller.core.text_registry.TextTemplateRegistry.write_lock`
        임계구역 안에서 한다(리뷰 F5) — 「템플릿으로 저장」의 덮어쓰기 재검증과 같은 락을 잡아,
        두 writer 가 같은 대상을 두고 check/write 를 교차하지 못하게 한다.
        """
        name = validate_template_name(p.get("name", ""))
        content = p.get("content", "")
        path = self.text_registry.directory / f"{name}.txt"
        with self.text_registry.write_lock():
            if path.exists():  # confirm-or-alarm: 조용한 덮어쓰기 금지 — 시끄럽게 거부.
                raise ValueError(f"이미 같은 이름의 템플릿이 있습니다: {name}")
            self.text_registry.directory.mkdir(parents=True, exist_ok=True)
            write_text_atomic(str(path), content)
        self._set_result(_ok(f"TXT 템플릿을 만들었습니다: {name}"))
        return {"ok": True, "name": name}

    def _do_txt_edit(self, p: dict) -> dict:
        """기존 TXT 템플릿 내용 저장 — 원자 쓰기(공유 write_lock, 리뷰 F5)."""
        path = Path(p["path"])
        with self.text_registry.write_lock():
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
