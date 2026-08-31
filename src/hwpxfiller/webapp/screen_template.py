"""템플릿 라이브러리(tpl) 채널 컨트롤러 — HWPX·TXT 라이브러리 관리(webview 비의존).

**화면은 죽고 채널은 산다(F8 §10.17.2 판정 B — F1 pool 선례)**: 「템플릿 관리」 화면
(scr-tpl·template.js)은 사망했고, 이 컨트롤러의 12액션·잠금 규율·경로 검증·휴지통은
편집기 「템플릿」 탭(editor.js)이 리터럴 `Bridge.call("tpl", …)` 로 그대로 소비한다.
push 스냅샷의 생존 소비자 = 편집기 결과 줄(result) + 재당김 신호.

링1 VM 을 **그대로 임포트**해 구동한다: HWPX 라이브러리 상태·상태별 게이트 액션·2단계
fieldize(스캔→적용)·lint 는
:class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`(Qt-free)가 소유한다.
TXT 관리는 코어 :class:`~hwpxfiller.external.text_registry.TextTemplateRegistry`(Qt-free)를 그대로
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

import threading
from pathlib import Path

from ..domain.text_structure import scan_text_structure, scan_text_token_spans
from ..host.locations import default_example_data_dir, default_templates_dir
from ..external import example_pack
from ..external.template_files import TemplateFileStore, TextEditDrift
from ..external.text_registry import TextTemplateRegistry
from ..external.template_inspection import HWPX_TEMPLATE_OPS, inspect_hwpx_template
from ..gui.template_manager_state import SlotView, TemplateManagerViewModel
from ..gui.tutorial_state import Milestone
from .screens import (
    MUTATION_KINDS,
    CompileSink,
    MutationSink,
    PushSink,
    TutorialSink,
    unwired_tutorial,
)
from .template_groups import (
    TemplateGroupModel,
    norm_library_path,
    rel_key,
    validate_template_name,
)

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
        file_store: TemplateFileStore,
        pool_registry,
        library_dir=None,
        hwpx_groups: "TemplateGroupModel | None" = None,
        txt_groups: "TemplateGroupModel | None" = None,
        example_data_dir=None,
        tutorial: TutorialSink = unwired_tutorial,
    ) -> None:
        self._push_sink = push
        # 튜토리얼 마일스톤 통지(#894) — 이 채널이 소유하는 전이 둘: 예제 설치 성립(T0 =
        # 명시 시작)과 누름틀 변환 성립(T15). 판정을 다시 하지 않고 **이미 성립한 사실**만
        # 넘긴다(통지 지점은 아래 두 곳 뿐).
        self._tutorial = tutorial
        self.text_registry = text_registry
        self._files = file_store
        # 예제 세트 설치(#891)의 데이터 고정 대상 — **필수 주입**이다(LibraryController 의
        # pool_registry 전례): 이 화면이 자기 것을 세우면 풀 상태의 제2 정본이 된다.
        # 설치 몸통은 ``external/example_pack`` 이 지고 여기는 확인 왕복과 재진술만 한다.
        self._pool_registry = pool_registry
        self._example_data_dir = (
            Path(example_data_dir) if example_data_dir is not None
            else default_example_data_dir()
        )
        # 라이브러리 폴더 미지정이면 표준 라이브러리(~/.hwpxfiller/templates)를 겨눈다(고정 루트).
        self.vm = TemplateManagerViewModel(
            library_dir if library_dir is not None else default_templates_dir(),
            inspect_template=inspect_hwpx_template,
            file_ops=HWPX_TEMPLATE_OPS,
        )
        # 매체별 그룹+접힘 모델(결정 2·3) — 설정 영속의 단일 소유자. 주입은 테스트 편의.
        self.hwpx_groups = hwpx_groups if hwpx_groups is not None else TemplateGroupModel("hwpx")
        self.txt_groups = txt_groups if txt_groups is not None else TemplateGroupModel("txt")
        # 가져오기 직렬화 잠금(#137 리뷰 F9) — pywebview 네이티브 호출은 별도 스레드라 같은
        # basename 동시 가져오기가 이름 선점~복사 사이 무경계로 겹쳐 두 호출이 같은 목적지를
        # 골라 내용 하나만 남는다. 후보 선택~복사를 이 잠금으로 직렬화한다(JobRegistry.clone 동형).
        self._import_lock = file_store.import_lock
        # 폴더 배치 가져오기의 동시 실행 거절 잠금(PR #355 2R) — _import_lock 은 개별 복사만
        # 직렬화해 두 배치가 교차하면 같은 목록이 번호 접미로 재반입된다. 배치 중복의 판정은
        # 여기 **한 곳**(비차단 획득 실패 = loud 거절)이고, JS 는 어포던스만 잠근다.
        self._folder_import_lock = threading.Lock()
        # HWPX 라이브러리 writer 잠금(PR #355 P1 후속) — TXT 의 ``text_registry.write_lock()``
        # 대응물. 「HWPX 는 공유 writer 가 없는 단일 표면」이라는 종전 전제는 **틀렸다**:
        # 삭제 복원(:meth:`_do_undo_delete` 의 hwpx 갈래)이 바로 그 공유 writer 다. 둘 다
        # 「이 basename 이 비었는가」를 보고 파일을 놓으므로, 잠금을 공유하지 않으면 복원이
        # 원본을 되돌린 직후 배치의 ``copy2`` 가 그 위를 덮어 **복원은 성공을 보고하는데
        # 지운 문서는 사라진다**. TXT 와 같은 축·같은 항목 단위 범위로 세운다. RLock.
        self._hwpx_write_lock = file_store.hwpx_write_lock
        # 마지막 결과 문구(컴파일·검토·가져오기·TXT 변경) — 성과별 심각도 채널(UD-07).
        self.result_text = ""
        self.result_level = "muted"
        # 마지막으로 검토한 템플릿의 Slot 목록(S8-03) — 결과 줄과 같은 수명의 관측 채널이다.
        # 「어느 템플릿의 목록인가」를 뷰가 추측하지 않게 경로·이름을 함께 싣는다.
        self._slot_view: "SlotView | None" = None
        # 최근 삭제 1건 복원 슬롯 — (media, 원경로, 휴지통경로, 삭제 시점 그룹). 그룹을 슬롯에
        # 보존해야 한다(#269 리뷰): 삭제 직후 스냅샷 푸시의 reconcile 이 사라진 키의 그룹 지정을
        # 영구 제거하므로, 복원 시 파일만 돌아오면 조용히 「그룹 없음」이 된다.
        self._deleted_template_slot: "tuple[str, Path, Path, str] | None" = None
        # 템플릿 bytes 변이 통지 sink(S8G-00 #320) — 이 채널이 파일을 실제로 바꾼 **직후**,
        # 같은 파일을 든 다른 표면(편집 세션)이 스스로 재정산할 수 있게 알린다. 서명은
        # ``(kind, path)`` 이고 kind 는 :data:`MUTATION_KINDS` 셋 중 하나다. 배선은 앱
        # 조립부 한 줄(app.py)이고 이 컨트롤러는 상대의 형체를 모른다(handoff callable).
        self.mutation_sinks: "list[MutationSink]" = []
        # 누름틀 변환 **성립** 통지 sink(#894) — `mutation_sinks` 와 나눠 두는 이유는 동사가
        # 다르기 때문이다(:data:`CompileSink` 주석). 「문서 만들기」가 이것을 받아, 생성된
        # 문서의 템플릿이 이 세션에서 변환된 것인지(T16)를 자기 사실로 안다.
        self.compile_sinks: "list[CompileSink]" = []

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _notify_mutation(self, kind: str, path: "str | Path") -> None:
        """durable 변이 성공 직후 통지 — **예외를 삼키지 않는다**(confirm-or-alarm).

        재정산이 실패했는데 변이가 성공을 보고하면, 편집 세션은 사라졌거나 바뀐 파일을
        든 채 조용히 살아남는다. 던지면 dispatch 가 그대로 표면화한다.
        """
        if kind not in MUTATION_KINDS:  # 오타는 시끄럽게(미지 kind 는 상대가 무시한다)
            raise ValueError(f"알 수 없는 템플릿 변이 종류: {kind!r}")
        for sink in self.mutation_sinks:
            sink(kind, str(path))

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
                "name": t.name,
                "path": str(t.path),
                "field_count": field_count,
                "error": error,
            })
        return rows

    def _media_snapshot(self, media: str, rows: "list[dict]", model: TemplateGroupModel) -> dict:
        """한 매체 구획의 스냅샷 — U4 §2-30 이후 **언제나 평면**이다.

        구획을 만들던 축은 템플릿 그룹 하나였고 그 표면이 걷혔다. 모델은 동결이라 유령 지정
        정리(``reconcile``)는 계속 돌린다 — 저장된 지정이 스캔과 어긋난 채 굳는 것이 되살릴
        때의 부채다. 다만 **구획으로 묻지 않는다**(``grouped_view=False``).
        """
        model.reconcile([r["key"] for r in rows])
        sections, flat = model.build_sections(
            rows, key_of=lambda r: r["key"], grouped_view=False
        )
        return {
            "sections": sections,
            "flat": flat,
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
            "slots": self.slot_snapshot(),
            # 동봉 예제 진입점(#891 · §4.1) — 라벨·설치 여부는 **Python 이 낸다**. 링2 가
            # 「이미 설치됨」을 다시 판정하면 같은 사실을 두 곳이 말하게 된다. 판정 몸통은
            # ``example_pack.entry_point_state`` 하나이고 라이브러리 빈 상태도 그것을 읽는다.
            "examples": example_pack.entry_point_state(),
        }

    def slot_snapshot(self) -> "dict | None":
        """검토한 템플릿의 Slot 목록 투영(없으면 ``None``) — 편집기 밴드도 이 값을 읽는다.

        목록이 가리키는 파일이 라이브러리에서 사라졌으면 스스로 걷는다: 죽은 경로를 겨눈
        동사 버튼을 남기면 누를 때야 실패한다.
        """
        view = self._slot_view
        if view is None:
            return None
        if self._norm(view.path) not in self._live_paths("hwpx"):
            self._slot_view = None
            return None
        return view.to_dict()  # 성형은 링1 소유(U4-E2 #939) — 편집기 요약과 같은 모양이다

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
        _root, candidates, skipped, _has_subdirs = self._files.folder_candidates(folder)
        return candidates, skipped

    def scan_import_folder(self, folder: str) -> dict:
        """가져오기 재진술 스캔(읽기 전용) — **확정 전에는 홈에 아무것도 쓰지 않는다**.

        수치(매체별 건수·제외 수·이름 충돌 수)와 완성 재진술 문안을 함께 돌려준다 — 표면이
        수치로 문안을 재조립하면 두 답이 생긴다(판정·문안은 Python, 확인 UI 는 웹). 후보 0
        은 확인이 아니라 loud 거절이다(가져올 것 없는 확정을 시키지 않는다). 브리지가 부른다.

        ``files`` = 확정 대상 후보 목록(이름) — 실행(:meth:`import_folder`)은 재스캔이 아니라
        **이 목록에 결속**된다(PR #355 리뷰): 스캔~확정 사이 폴더가 바뀌어도 확인 안 된
        파일이 따라 들어오지 않는다(재진술이 참이 되게)."""
        root, candidates, skipped, has_subdirs = self._files.folder_candidates(folder)
        if not candidates:
            note = (
                " 하위 폴더는 살펴보지 않습니다."
                if has_subdirs else ""
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
        return self._files.import_dest_taken(src)

    def _copy_into_library(self, src: Path) -> Path:
        """복사 권위 **몸통** — 매체 라우팅·잠금·충돌 번호 접미·무잔재. refresh/결과/push 없음.

        단건(:meth:`import_into_library`)과 배치(:meth:`import_folder`)가 같은 몸통을 쓴다 —
        배치는 항목별 전체 리프레시·push 를 유예하고 완료 후 1회만 민다(PR #355 리뷰: N건
        가져오기가 N번의 라이브러리 재스캔+전체 재렌더가 되는 준-제곱 정지 방지).

        **직렬화**(F9): 후보 선택~복사를 인스턴스 잠금으로 묶어 동시 동명 가져오기가 같은
        목적지를 골라 내용 하나만 남는 경합을 막는다. **무잔재**(F6): 복사 중 실패하면(디스크
        풀·원본 판독 불가) 부분 파일을 걷어내고 재던진다 — 다음 새로고침이 잘린 TXT/손상 HWPX
        를 목록에 노출하고 충돌 접미가 재시도를 막는 것을 방지(에디터 import_template 동형).

        **두 매체 모두 공유 writer 축에 함께 선다**(PR #355 P1·P1 후속): ``_import_lock`` 은
        가져오기끼리만 아는 잠금이라, 배치가 도는 동안 사용자가 「새 TXT」·내용 편집·삭제
        복원을 하면 두 writer 가 서로를 모른 채 같은 이름을 겨눈다 — 목적지가 「비었다」고
        고른 뒤 그 사이 채워지면 ``copy2`` 가 방금 놓인 파일을 덮고(반대 방향도 같다),
        충돌 접미가 지켜야 할 사용자 내용이 조용히 사라진다. **HWPX 도 예외가 아니다**:
        「공유 writer 가 없는 단일 표면」이라는 전제는 틀렸고, :meth:`_do_undo_delete` 의
        hwpx 갈래가 그 공유 writer 다(복원이 원본을 되돌린 직후 배치가 덮으면 복원은 성공을
        보고하는데 지운 문서는 사라진다). 그래서 목적지 선택~복사를 **매체별 writer 잠금**
        (TXT=:meth:`~hwpxfiller.external.text_registry.TextTemplateRegistry.write_lock`,
        HWPX=``_hwpx_write_lock``) 안에서 한다. 획득은 **항목 단위**라 배치가 도는 내내
        그 매체 조작이 통째로 막히지 않는다.

        **잠금 획득 순서 규약**: ``_folder_import_lock``(배치) → ``_import_lock``(가져오기)
        → 매체 writer(``text_registry.write_lock()`` / ``_hwpx_write_lock``). 항상 안쪽으로만
        잡는다. 역순 획득 경로는 없다 — 매체 writer 를 먼저 잡는 쪽(``_do_txt_new``·
        ``_do_txt_edit``·``_do_undo_delete``)은 어느 것도 가져오기 잠금을 잡지 않으므로 순환
        대기가 성립하지 않는다. 두 매체 writer 는 서로 중첩되지 않는다(매체가 배타적 분기).
        새 writer 를 더할 때도 이 순서를 지킨다.

        (``_do_delete`` 는 이 축에 세우지 않는다: 삭제는 **있는** 파일을 치우는 이동이라
        가져오기와 같은 이름을 두고 다투지 않는다 — 최악이 「방금 비워진 이름 대신 접미가
        붙는다」이고 그건 내용 소실이 아니라 예고 정확도 축이다(별건 #365).)"""
        return self._files.copy_into_library(src)

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
            root = self._files.require_folder(folder)
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
                if not self._files.source_file_exists(src):
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

    # ---- 동봉 예제 설치(#891 · ONBOARDING_TUTORIAL.md §4.1~4.2)
    def _hwpx_root(self) -> Path:
        root = self.vm.library_dir
        if root is None:  # 고정 루트라 실제로는 오지 않는다 — 오면 조용히 추측하지 않는다.
            raise ValueError("HWPX 라이브러리 루트가 정해져 있지 않습니다.")
        return Path(root)

    def _do_install_examples(self, p: dict) -> dict:
        """동봉 예제 세트 설치 — **1차는 재진술, 2차(`confirm`)가 실행**이다.

        D1(빈 상태 제안 + 명시 버튼)의 백엔드 착지다: 최초 부팅 자동 설치가 사용자 홈 무단
        쓰기라 기각됐으므로, 확정을 지나지 않은 호출은 **홈에 아무것도 쓰지 않고** 무엇을
        몇 건 어디에 쓰는지만 돌려준다(문안·수치는 Python, 확인 UI 는 웹 ``Modal.confirm``).

        재설치는 되돌리기다(§1 D4 — 벌크 undo 슬롯을 새로 만들지 않는다): 지난 manifest
        기재분을 덮어쓰고 manifest 를 새로 쓴다. 남의 동명 파일은 접미로 비켜 가고 그 사실은
        결과 줄이 재진술한다. 설치 몸통(복사·그룹 지정·데이터 고정·manifest)은
        :func:`~hwpxfiller.external.example_pack.install` 이 지고 여기는 조립과 문구만 맡는다.
        """
        hwpx_root = self._hwpx_root()
        txt_root = Path(self.text_registry.directory)
        if not p.get("confirm"):
            return {
                "needs_confirm": True,
                "confirm_text": example_pack.confirm_text(
                    hwpx_root=hwpx_root, txt_root=txt_root, data_dir=self._example_data_dir
                ),
            }
        try:
            done = example_pack.install(
                file_store=self._files,
                hwpx_groups=self.hwpx_groups,
                txt_groups=self.txt_groups,
                hwpx_root=hwpx_root,
                txt_root=txt_root,
                pool_registry=self._pool_registry,
                group_key=rel_key,
                data_dir=self._example_data_dir,
            )
        except (OSError, ValueError) as exc:  # 자산 부재·복사 실패 — 사유를 그대로 재진술
            self._set_result(_danger(f"예제를 설치하지 못했습니다: {exc}"))
            return {"ok": False, "error": str(exc)}
        self.vm.refresh()  # TXT 는 snapshot 의 list_templates 가 매번 재스캔
        line = (
            f"예제 템플릿 {len(done['templates'])}건을 '{example_pack.EXAMPLE_GROUP}' 그룹에 넣고 "
            f"데이터 {len(done['pool_keys'])}건을 고정했습니다."
        )
        if done["renamed"]:
            # 조용히 덮지 않았다는 사실은 결과가 말한다 — 같은 이름의 남의 파일이 있었다.
            line += " 같은 이름의 파일이 있어 " + ", ".join(done["renamed"]) + " 로 넣었습니다."
        self._set_result(_ok(line))
        # T0 예제 설치(#894) — **명시 시작**이다(§1 D3): 이 통지 전까지 튜토리얼 표면은 서지
        # 않는다. 1차(재진술)는 홈에 아무것도 쓰지 않으므로 여기까지 온 것만이 설치 성립이다.
        self._tutorial(Milestone.INSTALL_EXAMPLES)
        return {"ok": True, "installed": len(done["templates"]) + len(done["data_files"])}

    def _do_remove_examples(self, p: dict) -> dict:
        """설치한 예제 일괄 제거(#892 · §1 D4) — **1차는 재진술, 2차(`confirm`)가 실행**이다.

        걷는 것은 **설치 manifest 기재분뿐**이다: 그룹은 실체가 아니라 소속이라 「그룹 삭제
        한 번으로 통째 제거」가 성립하지 않고, 기재 밖 파일(사용자가 예제를 고쳐 다른 이름으로
        저장한 것)은 남아야 한다. 몸통·경로 화이트리스트 검증은
        :func:`~hwpxfiller.external.example_pack.remove` 가 지고 여기는 조립과 문구만 맡는다.

        **벌크 undo 슬롯을 만들지 않는다**: ``_deleted_template_slot`` 은 최근 1건 전용이고
        확장하면 「되돌리기가 되는 것과 안 되는 것」이 갈린다. 되돌리기는 재설치이고, 그
        사실은 확인 문안이 말한다. 그래서 이 자리는 삭제(``_do_delete``)와 달리 결과 줄을
        비우지 않는다 — 되돌리기 어포던스를 든 토스트가 없으므로 결과 줄이 유일한 증거다.
        """
        try:
            plan = example_pack.removal_plan(
                hwpx_root=self._hwpx_root(),
                txt_root=Path(self.text_registry.directory),
                data_dir=self._example_data_dir,
            )
        except (OSError, ValueError) as exc:  # 경로 탈출·기재 손상·설정 읽기 실패
            # ``OSError`` 도 여기다: 기재 판독은 설정 파일 I/O 라 디스크 쪽 실패가 실재하고,
            # 그것이 dispatch 밖으로 새면 사용자는 사유 없는 실패를 본다(confirm-or-alarm).
            self._set_result(_danger(f"예제를 제거하지 못했습니다: {exc}"))
            return {"ok": False, "error": str(exc)}
        if plan is None:
            self._set_result(_danger("설치된 예제가 없습니다."))
            return {"ok": False, "error": "설치된 예제가 없습니다."}
        if not p.get("confirm"):
            return {
                "needs_confirm": True,
                "confirm_text": example_pack.remove_confirm_text(plan),
            }
        try:
            done = example_pack.remove(
                file_store=self._files,
                hwpx_groups=self.hwpx_groups,
                txt_groups=self.txt_groups,
                hwpx_root=self._hwpx_root(),
                txt_root=Path(self.text_registry.directory),
                pool_registry=self._pool_registry,
                data_dir=self._example_data_dir,
            )
        except (OSError, ValueError) as exc:
            self._set_result(_danger(f"예제를 제거하지 못했습니다: {exc}"))
            return {"ok": False, "error": str(exc)}
        self.vm.refresh()  # TXT 는 snapshot 의 list_templates 가 매번 재스캔
        # 세션이 든 템플릿이 사라졌다 — 편집기가 스스로 시끄러워진다(#320). ``_do_delete`` 와
        # 같은 계약으로 **건별** 발신한다: 벌크 통지를 새로 짓지 않는다.
        for entry in done["trashed"]:
            self._notify_mutation("deleted", entry["path"])
        line = (
            f"예제 템플릿 {len(done['trashed'])}건과 데이터 {done['data_removed']}건을 걷고 "
            f"고정 {done['unpinned']}건을 해제했습니다. 되돌리려면 다시 설치하세요."
        )
        if done["missing"]:
            line += " 이미 없던 항목: " + ", ".join(done["missing"]) + "."
        if done["kept_pins"]:
            # 다른 데이터로 다시 연결된 슬롯은 남의 것이다 — 조용히 지우지도, 숨기지도 않는다.
            line += " 다른 데이터로 다시 연결된 고정은 남겼습니다: " + ", ".join(
                done["kept_pins"]
            ) + "."
        self._set_result(_ok(line))
        return {
            "ok": True,
            "removed": len(done["trashed"]) + done["data_removed"],
        }

    # ---- HWPX 상태 게이트 액션
    def _do_compile(self, p: dict) -> dict:
        """「누름틀·구간 변환」 2단계 — 미리보기(dry-run) → 확인 라운드트립 → 적용·저장.

        1차 호출(``confirm`` 없음): 스캔만. 표기 진단이 있으면 **확인을 묻지 않고** 차단
        사유를 인라인으로 재진술한다(변환 불가는 확정할 것이 아니다). 바꿀 것이 없으면
        역시 인라인 통지로 끝(파괴 아님). 있으면 ``needs_confirm`` 으로 두 축(누름틀·구간)을
        함께 재진술한다. 2차 호출(``confirm``): 실제 변환·저장.

        판정·수치·문안은 전부 링1(:class:`TemplateManagerViewModel`) 소유다 — 여기서
        다시 조립하지 않는다.
        """
        path = p["path"]
        if p.get("confirm"):
            result = self.vm.apply_convert(path)
            self._set_result(self.vm.format_convert_result(path, result))
            # 제자리 변환 = bytes 변이. 같은 파일을 든 편집 세션은 스키마가 방금 달라졌다.
            # 통지는 **실제 변이 여부**에만 결속한다(#853 F-3·F-4): 무변이 거절에서 통지가
            # 서면 거짓 경보이고, 필드만 저장된 뒤 구간이 실패한 갈래에서 통지가 빠지면
            # 세션이 낡은 스키마로 남는다. 판정 축은 링1 의 ``mutated`` 하나다.
            if result.mutated:
                self._notify_mutation("mutated", path)
                # T15 누름틀 변환(#894) — 통지 축은 위와 **같은 ``mutated``** 하나다: 무변이
                # 거절에서 체크가 서면 하지 않은 일을 했다고 말하는 것이고, 필드만 저장되고
                # 구간이 실패한 갈래는 실제로 파일이 바뀌었으므로 체크가 선다.
                self._tutorial(Milestone.COMPILE_TEMPLATE)
                for sink in self.compile_sinks:
                    sink(str(path))
            return {
                "ok": True, "applied": True,
                "refused": result.refused, "mutated": result.mutated,
            }
        preview = self.vm.convert_preview(path)
        if preview.blocked:
            self._set_result(self.vm.format_convert_blocked_result(path, preview))
            return {"ok": True, "applied": False, "blocked": True}
        if not preview.has_convertible:
            # UD-24: '바꿀 것 없음'은 차단 모달이 아니라 인라인 결과로(파괴 아님).
            self._set_result(self.vm.format_convert_empty_result(path, preview))
            return {"ok": True, "applied": False}
        lines = [preview.summary(), ""]
        lines.extend(f"+ {s.name}" for s in preview.tokens.compilable)
        lines.extend(f"! {s.name}: {s.reason}" for s in preview.tokens.skipped)
        lines.append(f"\n지금 변환하면 파일이 제자리에서 바뀝니다: {Path(path).name}")
        return {"ok": True, "needs_confirm": True, "confirm_text": "\n".join(lines), "path": path}

    def _do_review(self, p: dict) -> dict:
        """lint 점검(읽기 전용) → 결과 문구 + **Slot 목록 투영**(S8-03).

        검토는 「이 템플릿이 지금 어떤가」를 묻는 자리라 컴파일된 구간 항목 목록도 같은
        왕복에서 선다. 목록·진단은 링1 투영 그대로다(판정 재조립 금지).
        """
        path = p["path"]
        report = self.vm.lint(path)
        self._set_result(self.vm.format_lint_result(path, report))
        self._slot_view = self.vm.slot_view(path)
        return {"ok": True}

    # ---- 컴파일된 Slot 관리 동사(S8-03 #834)
    def _slot_target(self, p: dict) -> "tuple[str, str]":
        """(path, slot_id) 검증 — 라이브러리 밖 임의 파일 변이 권한 승격을 막는다.

        ``_do_delete`` 와 같은 술어다: 경로가 이 매체 라이브러리의 **현재 목록**에 실재해야
        한다. slot id 는 비어 있을 수 없다(빈 값이 「첫 항목」으로 접히지 않게).
        """
        path = str(p["path"])
        if self._norm(path) not in self._live_paths("hwpx"):
            raise ValueError("현재 라이브러리 목록에 없는 경로는 바꿀 수 없습니다.")
        slot_id = str(p.get("slot_id", "")).strip()
        if not slot_id:
            raise ValueError("대상 항목 id 가 비어 있습니다.")
        return path, slot_id

    def _after_slot_mutation(self, path: str, view, text: str) -> dict:
        """Slot 동사 성공 뒤 공통 후처리 — 목록 재투영·결과 줄·재정산 통지."""
        self._slot_view = view
        self._set_result(self.vm.format_slot_result(path, text))
        # bytes 변이 = 같은 파일을 든 편집 세션의 스키마가 방금 달라졌다(S8G-00 seam).
        self._notify_mutation("mutated", path)
        return {"ok": True, "slot_count": len(view.rows)}

    def _do_slot_rename(self, p: dict) -> dict:
        """항목 이름(label) 변경 — 구조 무변형이라 확인 왕복이 없다(파괴 아님).

        빈 값은 label 을 뗀다(이름 없는 항목). 입력 프롬프트는 웹이 소유한다.
        """
        path, slot_id = self._slot_target(p)
        label = str(p.get("label", "") or "").strip()
        view = self.vm.rename_slot(path, slot_id, label or None)
        told = f"항목 이름을 바꿨습니다 '{slot_id}'" if label else f"항목 이름을 지웠습니다 '{slot_id}'"
        return self._after_slot_mutation(path, view, told)

    def _do_slot_decompile(self, p: dict) -> dict:
        """항목을 구간 표기로 되돌리기 — 2왕복. 확인 본문이 **전이 결과**를 재진술한다."""
        path, slot_id = self._slot_target(p)
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "kind": "slot_decompile",
                "path": path, "slot_id": slot_id,
                "confirm_text": self.vm.confirm_decompile_text(path, slot_id),
            }
        view = self.vm.decompile_slot(path, slot_id)
        return self._after_slot_mutation(path, view, f"항목을 표기로 되돌렸습니다 '{slot_id}'")

    def _do_slot_remove(self, p: dict) -> dict:
        """항목을 **내용째** 삭제 — 2왕복 파괴 확정(손실 목록 재진술)."""
        path, slot_id = self._slot_target(p)
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "kind": "slot_remove",
                "path": path, "slot_id": slot_id,
                "confirm_text": self.vm.confirm_remove_slot_text(path, slot_id),
            }
        view = self.vm.remove_slot(path, slot_id)
        return self._after_slot_mutation(path, view, f"항목을 지웠습니다 '{slot_id}'")

    # 그룹 관리 동사 4종(지정·접힘·개명·해산)은 U4 §2-30 에서 표면과 함께 걷혔다.
    # 판정·영속은 `template_groups.TemplateGroupModel` 에 **동결**로 남는다.

    def _live_keys(self, media: str) -> "list[str]":
        """현 스캔의 살아있는 식별키 — 그룹 소속 수 판정용(캐시된 행 소비, 재파싱 없음)."""
        if media == "hwpx":
            root = self.vm.library_dir
            return [rel_key(r.path, root) for r in self.vm.rows()]
        root = self.text_registry.directory
        return [rel_key(t.path, root) for t in self.text_registry.list_templates()]

    @staticmethod
    def _norm(path: "str | Path") -> str:
        """경로 정규화 — 라이브 집합 대조용 단일 형식(:func:`norm_library_path` 위임).

        편집 세션 재정산(#320)이 같은 술어를 써야 해서 몸통은 공용 모듈이 소유한다.
        """
        return norm_library_path(path)

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
        trashed = self._files.trash(media, path)
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
        # 세션이 든 템플릿이 사라졌다 — 편집기가 스스로 시끄러워진다(#320). 통지는 이동이
        # **끝난 뒤**다: 실패한 삭제로 남의 세션을 놀라게 하지 않는다.
        self._notify_mutation("deleted", path)
        return {"ok": True, "undo": True, "name": path.stem}

    def _do_undo_delete(self, p: dict) -> dict:
        """휴지통 최근 1건 복원 — TXT 는 **복원 전 구간**이 writer 락 임계구역(#268/#280 리뷰).

        TXT 는 존재 검사와 ``replace`` 사이에 다른 pywebview 호출(새 템플릿·템플릿으로 저장)이
        같은 이름을 새로 쓸 수 있다 — 무락이면 복원이 그 새 파일을 조용히 덮거나, 동시 writer 가
        복원본을 즉시 덮는다. :meth:`~hwpxfiller.external.text_registry.TextTemplateRegistry.write_lock`
        을 존재 검사~교체~그룹 복원~실패 롤백까지 한 임계구역으로 잡는다(부분만 덮으면 롤백
        ``replace`` 가 락 밖에서 동시 편집을 쓸어 넣는다 — 3R).

        **HWPX 도 같은 규율이다**(PR #355 P1 후속): 「공유 writer 락이 없는 단일 표면」이라
        무락으로 두었던 것이 결함이었다 — 폴더 배치 가져오기가 같은 basename 을 겨누고
        있으면 둘 다 그 이름을 「비었다」고 읽고, 복원이 원본을 되돌린 뒤 배치의 ``copy2``
        가 그 위를 덮어 **복원은 성공을 보고하는데 지운 문서는 사라진다**. 그래서 hwpx 는
        ``_hwpx_write_lock``(가져오기 몸통과 공유)을 같은 범위로 잡는다.

        복원 후 삭제 시점 그룹을 재지정한다(#269 리뷰) — 삭제 직후 reconcile 이 지정을
        지웠으므로 슬롯의 그룹이 유일한 생존 기록이다."""
        if self._deleted_template_slot is None:
            return {"ok": False, "error": "복원할 최근 템플릿이 없습니다."}
        media, path, trashed, group = self._deleted_template_slot

        def regroup() -> None:
            """복원의 **모든 durable 변이**(존재 검사~이동~그룹 복원~실패 롤백) 한 몸통.

            TXT 는 이 전체가 writer 락 임계구역 안이어야 한다(#280 리뷰 3R) — 이동만 락으로
            덮고 그룹 복원·롤백을 밖에 두면, 락 해제 후 동시 writer 가 같은 이름을 새로 쓴
            뒤 설정 쓰기가 실패했을 때 롤백 ``replace`` 가 그 새 내용을 무락으로 휴지통에
            쓸어 넣는다(재시도 Undo = 엉뚱한 내용 복원 + 동시 편집 소실).
            """
            if group:
                # 그룹 복원까지 성공해야 슬롯을 비운다(#280 리뷰) — 슬롯이 삭제 시점 그룹의
                # 유일한 생존 기록이라, 설정 쓰기 실패 후 슬롯을 이미 비웠다면 재시도가
                # "복원할 템플릿이 없습니다"로 막히고 템플릿은 조용히 「그룹 없음」이 된다.
                # 실패 시 파일 이동을 되돌려(슬롯↔실상태 정합) 재시도를 가능하게 남긴다.
                root = self.vm.library_dir if media == "hwpx" else self.text_registry.directory
                self._model(media).set_group(rel_key(path, Path(root)), group)

        # 매체 writer 잠금 — 가져오기 복사 몸통(_copy_into_library)과 **같은 축**이라
        # 배치가 겨눈 이름과 복원이 겨눈 이름이 겹쳐도 한쪽이 먼저 끝난 뒤에 다른 쪽이 본다.
        error = self._files.restore(media, path, trashed, regroup)
        if error is not None:
            return {"ok": False, "error": error}
        self._deleted_template_slot = None
        if media == "hwpx":
            self.vm.refresh()
        self._set_result(_ok(f"템플릿을 복원했습니다: {path.stem}"))
        # 같은 경로로 돌아왔다 — 삭제 통지로 danger 를 띄운 편집 세션이 여기서 되살아난다.
        self._notify_mutation("restored", path)
        return {"ok": True, "name": path.stem}

    # ---- TXT 저작(HWPX와 동등 · 10F2FF98-C)
    def _do_txt_new(self, p: dict) -> dict:
        """새 TXT 템플릿 생성 — 이름 검증·중복 차단 후 원자 쓰기.

        존재 검사~쓰기는 공유 :meth:`~hwpxfiller.external.text_registry.TextTemplateRegistry.write_lock`
        임계구역 안에서 한다(리뷰 F5) — 「템플릿으로 저장」의 덮어쓰기 재검증과 같은 락을 잡아,
        두 writer 가 같은 대상을 두고 check/write 를 교차하지 못하게 한다.
        """
        name = validate_template_name(p.get("name", ""))
        content = p.get("content", "")
        self._files.create_text(name, content)
        self._set_result(_ok(f"TXT 템플릿을 만들었습니다: {name}"))
        return {"ok": True, "name": name}

    def _do_txt_edit(self, p: dict) -> dict:
        """기존 TXT 템플릿 내용 저장 — 원자 쓰기(공유 write_lock, 리뷰 F5) + 드리프트 확인 왕복.

        ``baseline`` 은 편집 창이 열릴 때 읽은 원문이다(필수 키 — 없으면 시끄럽게 실패).
        디스크가 그것과 다르면 창이 열린 사이 밖에서 바뀐 것이라 무확인 덮어쓰기가 파괴가
        된다(#216 이월 2): 쓰지 않고 재진술 문안과 **현재 지문**을 돌려주고, 웹이 확인을
        받아 그 지문을 ``confirm_fingerprint`` 로 되실어 다시 부른다. 판정은
        :meth:`~hwpxfiller.external.template_files.TemplateFileStore.edit_text` 가 쓰기와
        같은 임계구역 안에서 내린다 — 여기서 미리 읽어 재판정하지 않는다.
        """
        result = self._files.edit_text(
            p["path"],
            p.get("content", ""),
            baseline=p["baseline"],
            confirm_fingerprint=str(p.get("confirm_fingerprint", "") or ""),
        )
        if isinstance(result, TextEditDrift):
            name = Path(p["path"]).stem
            return {
                "needs_confirm": True,
                "kind": "txt_drift",
                "fingerprint": result.fingerprint,
                "text": (
                    f"편집 중 외부 변경: TXT 템플릿 '{name}' 이 이 편집 창을 여는 사이 "
                    "다른 곳에서 바뀌었습니다.\n지금 저장하면 그 변경 내용을 이 편집 창의 "
                    "내용으로 덮어씁니다."
                ),
            }
        path = result
        self._set_result(_ok(f"TXT 템플릿을 저장했습니다: {path.stem}"))
        # 내용이 바뀌면 토큰 집합이 바뀐다 — 편집 세션의 스키마가 방금 낡았다(#320).
        self._notify_mutation("mutated", path)
        return {"ok": True}

    def _do_txt_content(self, p: dict) -> dict:
        """편집 모달용 현재 내용 반환(읽기 전용). 읽기 실패는 loud raise."""
        return {"content": self._files.read_text(p["path"])}

    def _do_txt_lint(self, p: dict) -> dict:
        """저작 중인 **미저장 본문**의 구간 표기 판정 + 토큰 좌표(읽기 전용·무변형).

        린트메모장(S10-05 #862)의 판정 원천이다. 파일이 아니라 **창이 들고 있는 문자열**을
        받는다 — 저장 전에 표기가 깨졌는지 말해 주는 것이 이 왕복의 존재 이유라, 디스크를
        읽으면 늘 한 저장 늦게 대답한다. 그래서 경로 인자가 없고 쓰기도 없다(새 TXT 저작
        창에는 아직 경로 자체가 없다).

        진단은 링0 스캐너(:func:`~hwpxfiller.domain.text_structure.scan_text_structure`)가
        낸 것을 **그대로** 싣는다. 표면은 ``message`` 를 재진술만 하고 ``kind`` 로 문안을
        다시 짓지 않는다. 강조 좌표도 마찬가지로
        :func:`~hwpxfiller.domain.text_structure.scan_text_token_spans` 가 낸 문자
        오프셋이다 — 웹이 토큰 정규식을 다시 쓰면 sigil 선행 분류가 두 곳에서 갈린다.
        """
        content = p.get("content", "")
        scan = scan_text_structure(content)
        return {
            **scan.to_dict(),
            "spans": [span.to_dict() for span in scan_text_token_spans(content)],
        }


def _ok(text: str):
    """성공 결과 라인(ok 레벨) — ResultLine 재사용을 피해 경량 성형."""
    from ..gui.template_manager_state import ResultLine

    return ResultLine(text, "ok")


def _danger(text: str):
    """거절 결과 라인(danger 레벨) — :func:`_ok` 동형. 실패를 muted 로 접지 않는다."""
    from ..gui.template_manager_state import ResultLine

    return ResultLine(text, "danger")
