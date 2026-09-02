"""템플릿 라이브러리(tpl) 채널 컨트롤러 — HWPX·TXT 라이브러리 관리(webview 비의존).

**화면은 죽고 채널은 산다(F8 §10.17.2 판정 B — F1 pool 선례)**: 「템플릿 관리」 화면
(scr-tpl·template.js)은 사망했고, 이 컨트롤러의 액션·잠금 규율·경로 검증은
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
- **가져오기 = 루트로 복사**: 「파일 가져오기…」 단건 하나. 「그룹 없음」에서 시작.

**U6-A(#975) 재편**: 루트가 **사용자가 고르는 단일 폴더**가 됐다(설정 모달의 「서식 폴더」
행). hwpx·txt 가 같은 루트를 재귀로 읽고, 재지정 동사는 :meth:`TemplateController.set_templates_root`
하나다. 함께 **퇴역**한 것: 폴더 일괄 가져오기(``scan_import_folder``·``import_folder``)와
삭제·휴지통(``delete``·``undo_delete``) — 앱은 사용자 폴더에 ``.trash`` 를 만들지 않고
읽기와 제자리 변환만 한다(U6 §2.3). 「폴더에서 보기」가 삭제 동사를 대신한다.

**결정 반영(#13 승계)**:
- 미리보기(필드명·토큰) 액션 **제외**(10F2FF98-B) — 링1 seam 은 보존하되 노출 안 함.
- 판본 드리프트 비교는 **숨김/강등**(10F2FF98-D) — diff 는 앱 A(hwpxdiff) 책임.
제자리 fieldize 적용은 확인 라운드트립으로 지킨다.
"""
from __future__ import annotations

from pathlib import Path

from ..domain.text_structure import scan_text_structure, scan_text_token_spans
from ..host.locations import default_example_data_dir
from ..external import example_pack
from ..external.template_files import TemplateFileStore, TextEditDrift
from ..external.template_root import TemplateRoot
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
        template_root: "TemplateRoot | None" = None,
        migration_notice: str = "",
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
        # 서식 폴더 권위(U6-A #975) — hwpx 목록·txt 목록·가져오기 복사가 **같은 홀더**를
        # 지난다. VM 에는 Path 가 아니라 콜러블을 준다: 재지정은 설정 하나를 바꾸는 일이고
        # 그 다음 스냅샷이 곧 새 루트여야 한다(사본을 굳혀 들면 선언≠실제가 된다).
        self._template_root = template_root if template_root is not None else TemplateRoot()
        # 부팅 1회 레거시 TXT 이관의 재진술(U6-A §4). 경보 로그만으로는 **화면에 닿지 않아**
        # 사용자가 자기 파일이 옮겨진 사실을 모른다 — 그래서 이 프로세스가 사는 동안 서식
        # 폴더 존의 사유에 병기한다. 값은 조립부가 계산해 넘긴 문자열 그대로다(재판정 없음).
        self._migration_notice = str(migration_notice or "")
        self.vm = TemplateManagerViewModel(
            self._template_root.path,
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
        # HWPX 라이브러리 writer 잠금 — TXT 의 ``text_registry.write_lock()`` 대응물.
        # 두 매체가 **같은 루트**를 쓰게 된 U6-A 이후에도 축은 그대로다: 가져오기 복사가
        # 「이 이름이 비었는가」를 보고 파일을 놓으므로 그 구간은 직렬화돼야 한다. RLock.
        self._hwpx_write_lock = file_store.hwpx_write_lock
        # 마지막 결과 문구(컴파일·검토·가져오기·TXT 변경) — 성과별 심각도 채널(UD-07).
        self.result_text = ""
        self.result_level = "muted"
        # 마지막으로 검토한 템플릿의 Slot 목록(S8-03) — 결과 줄과 같은 수명의 관측 채널이다.
        # 「어느 템플릿의 목록인가」를 뷰가 추측하지 않게 경로·이름을 함께 싣는다.
        self._slot_view: "SlotView | None" = None
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
            except Exception as exc:  # noqa: BLE001 — 손상 파일도 사유를 단 행으로 loud 노출
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
        resolution = self._template_root.resolution()
        hwpx["dir"] = resolution.directory
        txt["dir"] = resolution.directory
        # 빈 목록 안내는 U6-A 에서 **링1 하나가 정본**이 됐다(`empty_hint`) — 루트가 하나라
        # 원인도 하나이고, 두 밴드가 각자 문안을 지으면 같은 사실을 두 곳이 판정한다.
        hint = self.vm.empty_hint()
        hwpx["empty_hint"] = hint
        txt["empty_hint"] = hint
        return {
            "hwpx": hwpx,
            "txt": txt,
            # 서식 폴더 존(U6-A #975) — 저장 폴더의 최상위 `output_folder` 존과 **동형**이다.
            # 「어느 폴더를 읽고 있는가」는 목록이 비어도, 작업이 없어도 답할 수 있는 사실이라
            # 밴드 안이 아니라 최상위가 진다. 판정·라벨·사유는 전부 링0 도출 그대로다.
            "templates_root": {
                "directory": resolution.directory,
                "source": resolution.source,
                "source_label": resolution.source_label,
                # 도출 사유(폴더 부재)와 이관 재진술은 **둘 다** 설 수 있고 서로를 지우지
                # 않는다 — 줄바꿈으로 병기한다(하나가 다른 하나를 덮으면 조용한 소실이다).
                "notice": "\n".join(
                    text for text in (resolution.notice, self._migration_notice) if text
                ),
            },
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
    def set_templates_root(self, path: str) -> dict:
        """서식 폴더 재지정(U6-A #975) — 영속 뒤 **한 번의 푸시**로 전 소비자가 새 루트를 본다.

        재지정 동사가 홀더 하나인 이유는 소비자가 전부 그 홀더를 지나기 때문이다: hwpx 목록·
        txt 목록·가져오기 복사·Job 링크 해석 어디에도 「루트를 갈아 끼우는」 두 번째 자리가
        없다. 그래서 여기가 하는 일은 설정 쓰기와 재스캔뿐이다.

        payload 검증은 **이 메서드 몸통이 진다**(action registry 밖 직접 브리지): 빈 값과
        파일 경로는 조용히 무시하지 않고 loud 거절한다 — 빈 값을 통과시키면 「지정한 적
        없음」과 구분되지 않고, 파일을 통과시키면 다음 스캔이 이유 없이 0건이 된다.
        """
        if not isinstance(path, str) or not path.strip():
            raise ValueError("서식 폴더 경로가 비어 있습니다.")
        target = Path(path.strip())
        if target.is_file():
            raise ValueError(f"폴더가 아니라 파일입니다: {target}")
        resolution = self._template_root.set(str(target))
        # 편집 세션에는 **변이 통지를 보내지 않는다**. `mutation_sinks` 는 「이 경로의 파일이
        # 바뀌었다」는 seam 이고(:meth:`reconcile_template_mutation` 이 경로 일치에서만 산다),
        # 루트 재지정은 파일을 하나도 건드리지 않는다 — 세션이 든 절대경로도 스키마도 그대로다.
        # 폴더 경로를 그 seam 에 실으면 어느 세션과도 일치하지 않아 **조용한 무효 통지**가 되고,
        # 일치시키려 규칙을 넓히면 「남의 템플릿 변이가 내 세션에 경고를 남기는」 그 결함을
        # 되살린다. 목록 갱신은 이 채널의 푸시 + 호출자의 화면 재당김이 진다.
        self.vm.refresh()
        self._set_result(_ok(f"서식 폴더를 바꿨습니다: {resolution.directory}"))
        self._push()
        return {"ok": True, "directory": resolution.directory}

    def import_into_library(self, path: str) -> str:
        """가져오기 = 루트로 **복사**(결정 4) — 확장자로 매체 라우팅. 「그룹 없음」에서 시작.

        원본의 후속 이동·수정은 라이브러리 사본에 불파급. 이름 충돌은 조용히 덮지 않고
        ``이름 (2).ext`` 접미로 회피 + 결과 재진술. 관리 화면은 RAW(누름틀 0)도 받는다(그
        자리에서 변환하는 게 요점 — 에디터 가져오기의 RAW 거부와 다르다). 브리지가 부른다.

        복사 몸통(잠금·충돌 번호 접미·무잔재)은 store 가 진다. 폴더 일괄 가져오기는
        U6-A 에서 퇴역했으므로 이 몸통을 나누던 배치 소비자도 없다(소비자 1)."""
        src = Path(path)
        dest = self._files.copy_into_library(src)
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
        # 세션이 든 템플릿이 사라졌다 — 편집기가 스스로 시끄러워진다(#320). **건별** 발신한다:
        # 벌크 통지를 새로 짓지 않는다.
        for entry in done["removed"]:
            self._notify_mutation("deleted", entry["path"])
        line = (
            f"예제 템플릿 {len(done['removed'])}건과 데이터 {done['data_removed']}건을 걷고 "
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
            "removed": len(done["removed"]) + done["data_removed"],
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
    def _slot_path(self, p: dict) -> str:
        """대상 경로 검증 — 라이브러리 밖 임의 파일 변이 권한 승격을 막는다.

        ``_do_delete`` 와 같은 술어다: 경로가 이 매체 라이브러리의 **현재 목록**에 실재해야
        한다. 항목을 겨누지 않는 문서 단위 동사(전체판 풀기)도 같은 관문을 지난다.
        """
        path = str(p["path"])
        if self._norm(path) not in self._live_paths("hwpx"):
            raise ValueError("현재 라이브러리 목록에 없는 경로는 바꿀 수 없습니다.")
        return path

    def _slot_target(self, p: dict) -> "tuple[str, str]":
        """(path, slot_id) 검증 — 경로 관문에 더해 slot id 는 비어 있을 수 없다.

        (빈 값이 「첫 항목」으로 조용히 접히지 않게 한다.)
        """
        path = self._slot_path(p)
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

    def _do_slot_decompile_all(self, p: dict) -> dict:
        """이 템플릿의 항목을 **전부** 표기로 되돌리기 — 2왕복(U4-E3 #939).

        단건(:meth:`_do_slot_decompile`)과 같은 왕복이고 payload 에 ``slot_id`` 가 없다:
        대상이 항목이 아니라 파일이다. 확인 본문·개수는 링1 이 싣는다(여기서 세지 않는다).
        """
        path = self._slot_path(p)
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "kind": "slot_decompile_all",
                "path": path,
                "confirm_text": self.vm.confirm_decompile_all_text(path),
            }
        view = self.vm.decompile_all_slots(path)
        return self._after_slot_mutation(path, view, "전 항목을 표기로 되돌렸습니다")

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
