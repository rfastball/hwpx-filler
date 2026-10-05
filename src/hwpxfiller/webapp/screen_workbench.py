"""TXT 검토·복사 작업대 — v6 표면 S7(계약 §11). 재작성 F6 PR-A.

「문서 만들기」에서 TXT 작업을 고르고 실행하면 여기 온다. 데이터·범위 선택은 **저쪽이**
끝내고, 이 화면은 그 결과를 **고정 사본**으로 받아 레코드 하나씩 검토·복사한다.

**왜 별도 화면인가**: 복사 진행은 세션과 함께 사라지는 상태이고, 그 이탈 처분이 성립하려면
**나가는 경로가 셀 수 있어야** 한다. 「문서 만들기」 안에 살면 상단 탭·다른 컨트롤이 처분
미확정 이탈구가 되고 가드의 완전성이 표면 수에 비례한다.

**세션은 진입 시 고정 사본이다**(§13-13·§18.11-25). 표시순 투영을 통과한 OrderedSelection 의
복사본을 뜨고, 이후 「문서 만들기」의 검색·필터·정렬·선택 변화가 현재 작업점 순서를 바꾸지
않는다. 그래서 여기엔 데이터 존이 없다 — 데이터를 바꾸려면 나갔다 다시 들어온다.

**연결은 읽기만 한다**(#1148 —지도 §10.15 판정 E 의 뒤집기). 이 화면은 필드 연결 표를 들지
않는다: 복사할 본문이 화면의 중심이고, 연결 문제는 「연결 편집」(편집기 연결 표)과 「템플릿
편집」(저작 작업대)으로 나가 저장해 푼다. 그래서 이 세션에는 저장할 규칙 변경이 생기지 않고,
이탈 가드가 세는 것은 복사 진행·다시 확인할 항목·임시로 고친 본문이다.

**본문은 그 행 복사본의 임시 편집기다**(#1148 PR B). 사용자가 고친 글자는 행별로 이 세션에만
남고(템플릿·데이터·연결은 그대로), 복사는 편집본 그대로 나간다. 판정(표식 자리·빈 값 채움·
린트)은 :mod:`~hwpxfiller.viewmodel.txt_card_edit` 가 하고, 봉인 물질화 대조는 편집 **전** 원문에만
건다 — 편집은 그 위에 얹힌다.

**경계**: 실제 클립보드 쓰기는 브리지(:meth:`HwpxFillerApi.copy_clipboard`)가 한다. 이
컨트롤러는 시안의 mock 완료 사건이 아니라 **실제 복사**의 앞뒤(게이트·큐 전진·완료 노트)를
소유한다 — v6 §19.4 의 「복사는 mock」 경계 문안은 이 제품에 해당하지 않는다.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..application.jobs import stamp_run_completion
from ..domain.job import Job, work_mode
from ..external.job_store import JobRegistry
from ..domain.text_render import template_fields
from ..domain.text_structure import project_selected_text, scan_text_structure
from ..viewmodel.filter_state import sniff_column_kinds
from ..viewmodel.mapping_state import MappingModel
from ..viewmodel.selection_state import SelectionModel
from ..viewmodel.txt_card import gate_empty_fields, render_card
from ..viewmodel.txt_card_edit import CardEdits, CardView, card_view, raw_card, utf16_marks
from ..viewmodel.tutorial_state import Milestone
from ..viewmodel.txt_queue import TxtQueueModel
from ..viewmodel.work_mode import WORK_MODE_TEXT, work_mode_label
from .screens import PushSink, TutorialSink, unwired_tutorial
from ..external.settings import is_proportional_font, load_draft_target_font, save_draft_target_font

#: 레코드 검토 상태(§11 마지막 줄) — 복사했더라도 규칙이 바뀌면 **다시 확인 필요**다.
REVIEW_TODO = "todo"
REVIEW_COPIED = "copied"
REVIEW_RECHECK = "recheck"

_VIEWS = ("filled", "raw")

#: 물질화 표면이 결선되지 않은 채 slot-bearing TXT 를 연 세션의 복사 차단 사유(S10-04 #861).
#: S10-03 의 상시 차단(``COPY_BLOCK_STRUCTURE_NOTATION``)은 걷혔다 — 이제 복사는 Sealed Plan 이
#: 물질화한 bytes 를 내보낸다. 남은 것은 **미주입**이라는 오배선의 정직한 얼굴이다: 포트가
#: 없으면 이 화면은 고르지 않은 선택지와 마커가 실린 텍스트를 내보내는 대신 사유를 말한다.
COPY_BLOCK_MATERIALIZATION_UNAVAILABLE = (
    "구간 표기가 있는 템플릿의 복사 준비가 이 창에 연결되지 않았습니다. "
    "'문서 만들기'에서 다시 시작하세요."
)

#: 화면이 보여 준 문장과 봉인된 실행 결과가 갈렸을 때의 차단 사유(S10-04 #861).
#: **보이는 것 = 복사되는 것**(결정 17)이 이 화면의 계약이라, 두 문장이 다르면 조용히 한쪽을
#: 내보내지 않고 복사하지 않는다. 이 화면이 연결을 편집하지 않게 된 뒤(#1148) 남는 원인은
#: 전각 정렬(표시 전용 치환이라 봉인된 실행에 없다) 하나다. 저장된 연결 밖의 카드 연결(저장
#: 프로파일에 없는 필드의 자동 확정)은 여기까지 오지 않는다 — 봉인이 먼저 그 필드를
#: ``ACTIVE_FIELD_UNBOUND`` 로 거절하고, 그 사유가 그대로 복사 결과에 실린다.
COPY_BLOCK_MATERIALIZATION_DIVERGED = (
    "화면에 보이는 문장과 실제로 만들어진 문서가 다릅니다. "
    "전각 정렬을 끈 뒤 다시 복사하세요."
)

#: 선택을 조회하지 못했을 때의 상시 재진술. 조용히 원문으로 접지 않는다(복사는 어차피 차단).
SELECTION_UNAVAILABLE_NOTE = (
    "포함할 내용을 불러오지 못해 템플릿 원문 그대로 보여 줍니다. "
    "'문서 만들기'에서 템플릿을 다시 확인하세요."
)


class TargetFontSetting:
    """대상 글꼴 선언(결정 17)의 **단일 실체** — 앱 전역 영속 값의 인메모리 캐시.

    거처 이동(F6 PR-B, §10.15.15 판정 E): 「기안」 화면 사망으로 유일 생존 소비자인
    작업대가 소유한다. 영속 키(``draft_target_font``)는 그대로다 — 개명은 마이그레이션
    비용만 사고 얻는 게 없다. 컨트롤러마다 사본을 캐시하면 한쪽에서 바꾼 선언이 다른
    쪽에 재부팅까지 도달하지 않는 「선언≠실제」 결함류라 공유 실체 하나로 닫는다(코덱스
    리뷰 P2 — 소비자가 하나가 된 지금도 앱 조립이 한 인스턴스를 주입하는 규율은 유지).
    스냅샷마다 설정 파일을 다시 읽는 대안은 매 타건 I/O 라 기각.
    """

    def __init__(self) -> None:
        self._value = load_draft_target_font()

    @property
    def value(self) -> str:
        return self._value

    def set(self, font: str) -> None:
        """선언 변경 — **저장이 먼저**(영속 실패 시 상태 불변 + 브리지 경보)."""
        save_draft_target_font(font)  # 검증도 여기 단일 출처(열거형·문안 사본 금지)
        self._value = font


class WorkbenchController:
    """검토·복사 작업대의 세션 소유자 — 화면 하나에 세션 하나(동시 다중 없음)."""

    name = "workbench"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        clock: Callable[[], datetime],
        target_font,
        content_selection: "Callable[[str], dict[str, frozenset[str]]] | None" = None,
        txt_materialization: (
            "Callable[[str, dict, str, datetime], tuple[str | None, str]] | None"
        ) = None,
        tutorial: TutorialSink = unwired_tutorial,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self._clock = clock
        # 튜토리얼 마일스톤 통지(#894) — 이 채널이 소유하는 전이 하나: 복사 성사(T11).
        self._tutorial = tutorial
        # slot-bearing TXT 의 **물질화 포트**(S10-04 #861). 앱 조립이 봉인→VDR→start gate 를
        # 거쳐 검증된 bytes 를 내는 서비스에 결선한다. 이 컨트롤러는 그 안을 모른다 — 받는
        # 것은 「검증된 텍스트」 아니면 「사유」뿐이고, 사유는 그대로 복사 차단으로 재진술된다.
        # 미주입이면 slot-bearing 복사가 서지 않고 그 사실이 사유로 남는다(조용한 투영 유출 0).
        self._txt_materialization = txt_materialization
        # 「포함할 내용」(S4 Slot Option 선택) **조회 포트**(S10-03 #860). 앱 조립이 Slot
        # Configuration Product 의 read-only projection 에 결선한다 — 이 컨트롤러는 선택을
        # 판정하지도, 저장하지도, 그 형체를 알지도 않는다(투영 ≠ 실행 권위, S-9). 미주입이면
        # slot-bearing 템플릿의 투영이 서지 않고 그 사실이 사유로 남는다(조용한 원문 폴백 0).
        self._content_selection = content_selection
        # 대상 글꼴은 앱 전역 영속 선언(TargetFontSetting — 「기안」 사망으로 이 화면이
        # 유일 소비자, §10.15.15 판정 E). 앱 조립이 단일 인스턴스를 주입한다.
        self._font = target_font
        # **세션 상태 전이의 임계구역**(6R P1 근본 조치). pywebview 는 브리지 호출마다 별도
        # 스레드라 이 컨트롤러의 진입점들이 실제로 겹친다.
        #
        # 같은 결함이 세 번 왔고(3R=확인 대상과 복사 대상을 토큰으로 결속 · 5R=복사 거래를
        # 컨트롤러가 원자로 소유 · 6R=그 잠금에 **변이 쪽이 참여하지 않음**), 그때마다 복사
        # 경로만 넓혔다. 잠금은 잠금을 잡는 쪽끼리만 배제하므로, `copy_to` 혼자 잠가서는
        # 「다음」·매핑 편집·이탈이 렌더와 `note_copied` 사이로 그대로 들어온다 — 옛 카드로
        # 만든 문자열을 쓰고 **새** 작업점을 복사 완료로 찍거나, `_do_close` 가 비운
        # `mapping` 위에서 이미 성공한 복사가 터진다.
        #
        # 그래서 정의를 넓혀 한 자리로 닫는다: 잠그는 것은 「복사」가 아니라 **이 세션의
        # 상태를 바꾸는 모든 것**이다(dispatch 변이 · 세션 개시/파기 · 복사 거래). 무변이
        # 질의도 같은 잠금 아래에서 읽어 전이 중간을 보지 않는다.
        #
        # 잠금 순서는 언제나 `_state_lock` → `registry.write_lock()` 이다(저장·최근 사용
        # 스탬프가 그렇게 중첩한다). 역순으로 잡는 경로는 없다 — 레지스트리 잠금을 든 채
        # 이 컨트롤러를 부르는 자리를 만들지 않는다.
        self._state_lock = threading.RLock()
        self._clear()

    # ------------------------------------------------------------- 세션 수명
    def _clear(self) -> None:
        """세션 없음 — 부팅 기본값이자 이탈 뒤 상태.

        **화면이 열려 있다는 사실은 라우팅이 아니라 이 상태다**(F7 선례): 세션 없이 라우팅만으로
        열면 부팅·새로고침에 문맥 없는 작업대가 선다(진입 사유도, 복귀처도, 레코드도 없다).
        """
        self.job_name = ""
        self.base_job: "Job | None" = None
        self.template_text = ""
        # 구간 표기 스캔은 **진입 시 1회**다(S10-03 #860). 세션 텍스트가 고정 사본이므로 매
        # 스냅샷마다 다시 훑을 것이 없고, 복사 admission 과 투영이 **같은 스캔 하나**를 봐야
        # 「버튼이 닫힌 이유」와 「카드가 그런 이유」가 갈리지 않는다.
        self._marker_count = 0
        # 선택을 반영한 카드용 텍스트. slotless(마커 0)이면 원문과 같은 값이라 그 경로는
        # 이 슬라이스로 **한 줄도 달라지지 않는다**.
        self._card_text = ""
        # 투영이 서지 못한 사유(없으면 ``""``) — 스냅샷이 상시 재진술한다.
        self._selection_note = ""
        self.records: "list[dict]" = []
        self.source_rows: "list[int]" = []
        self.mapping: "MappingModel | None" = None
        self.selection = SelectionModel(0)
        self.queue = TxtQueueModel(self.selection)
        self.view = "filled"
        self._advance_after = False
        self._fullwidth = False
        self._last_copy: "dict | None" = None
        self._copied_total = 0
        # 최근 사용 스탬프는 **세션당 1회**다(§19.4: "한 레코드라도 복사 완료"). 매 복사마다
        # 찍으면 durable 쓰기가 복사 수만큼 늘고, 기록되는 사실은 첫 건과 똑같다.
        self._stamped = False
        # 복사 시점의 **규칙 지문**(행 index → 지문). 검토 상태는 이 값과 지금 지문의 **차이**로
        # 파생한다(2R P2). 사건을 세면 사건 밖의 변화(전각 정렬을 켠 것)를 못 본다 — 카드는
        # 이미 다른 문장을 보여 주는데 배지는 「복사 완료」라고 말하는 창이 열린다. 사건을
        # 세지 말고 **조건을 재라**.
        self._copied_rules: "dict[int, str]" = {}
        # 행별 임시 편집 — 세션 안에서만 산다. 나가면 가드가 알리고 버린다.
        self._edits = CardEdits()

    def open(self, job: Job, rows: "list[tuple[int, dict]]") -> None:
        """세션 개시 — 고정 사본을 뜬다. ``rows`` = (원본 행 index, 레코드) 표시순.

        **실패 원자성**: 실패할 수 있는 템플릿 읽기를 **먼저** 끝낸 뒤에 상태를 교체한다.
        템플릿이 사라졌으면 :class:`OSError` 가 올라가고 이전 상태(보통 「세션 없음」)는
        그대로다 — 반쪽 세션으로 화면이 서지 않는다(「기안」 `_restore_from_job` 과 같은 규율).
        파일 읽기는 잠금 **밖**이다: 실패해도 바꾸는 것이 없고, 느린 I/O 로 진행 중인 복사
        거래를 잡아 둘 이유도 없다. 잠그는 것은 교체 자체다.

        구간 표기 스캔과 「포함할 내용」 투영도 여기서 **한 번** 끝난다(S10-03 #860) — 세션은
        고정 사본이므로 이후 스냅샷마다 다시 훑거나 다시 조회할 근거가 없다. 선택 조회 실패는
        예외로 올리지 않는다: 원문을 그대로 들고 사유를 남기면 화면은 서고 복사는 어차피
        차단된다(반쪽 세션보다 정직한 세션이 낫다).
        """
        # ``newline=""`` — 줄 끝 문자를 **원문 그대로** 든다(S10-04 #861). 기본 universal
        # newline 은 CRLF 템플릿을 LF 로 접어 읽는데, 물질화는 Candidate bytes 를 그대로 다루므로
        # 그때 화면(LF)과 문서(CRLF)가 갈려 「보이는 것 = 복사되는 것」이 거짓이 된다. 사용자가
        # 고칠 수 없는 사유로 복사가 막히느니 읽기를 원문에 맞춘다.
        text = Path(job.template_path).read_text(encoding="utf-8", newline="")
        card_text_source, selection_note, marker_count = self._project_selection(job, text)
        records = [dict(rec) for _, rec in rows]        # 고정 사본(§13-13) — 바깥과 공유 금지
        source_fields = list(records[0].keys()) if records else []
        mapping = MappingModel.from_field_names(
            template_fields(text), source_fields,
            col_kinds=sniff_column_kinds(records) if records else {},
        )
        # 저장 프로파일은 **과거 사람 확정**의 산출물이라 확정본으로 복원한다(결정 12) —
        # 라이브 재제안이 그 위를 덮으면 사람이 고른 결속이 조용히 바뀐다.
        mapping.apply_profile(job.mapping, confirm=True)
        # 커밋(이 아래로는 실패 없음) — 세션 교체는 상태 전이라 잠금 안이다.
        with self._state_lock:
            self._clear()
            self.job_name = job.name
            self.base_job = job
            self.template_text = text
            self._card_text = card_text_source
            self._selection_note = selection_note
            self._marker_count = marker_count
            self.records = records
            self.source_rows = [i + 1 for i, _ in rows]  # 1-based 원본 행 번호(정체 병기용)
            self.mapping = mapping
            # 고정 사본 **전체**가 이 세션의 대상이다(선택은 「문서 만들기」에서 이미 끝났다) —
            # 여기서 다시 고르는 축을 만들면 같은 결정을 두 표면이 내리게 된다.
            self.selection = SelectionModel(len(records))
            self.queue = TxtQueueModel(self.selection)
            self._push()

    def _project_selection(self, job: Job, text: str) -> "tuple[str, str, int]":
        """(카드용 텍스트, 투영 실패 사유, 마커 총수) — 잠금 밖 순수 조립(S10-03 #860).

        **slotless 는 아무 일도 일어나지 않는다**: 마커가 0 건이면 선택을 조회하지도, 투영을
        시도하지도 않고 원문 그대로다. 그 경로가 이 슬라이스의 회귀 축이다.

        slot-bearing 이면 「포함할 내용」을 조회해 고른 선택만 남긴 텍스트를 만든다. 판정은
        전부 저쪽(S4 Product)의 것이고 여기는 **읽어서 접기만** 한다 — 이 컨트롤러가 선택을
        다시 판정하면 같은 상태를 두 곳이 결정하게 된다. 조회·투영이 실패하면 원문을 들되
        사유를 함께 낸다(조용한 폴백 0).
        """
        scan = scan_text_structure(text)
        if not scan.summary.markers:
            return text, "", 0
        if self._content_selection is None:
            return text, SELECTION_UNAVAILABLE_NOTE, scan.summary.markers
        try:
            selected = self._content_selection(job.name)
            return (
                project_selected_text(text, scan, selected),
                "",
                scan.summary.markers,
            )
        except (ValueError, OSError):
            # 표기 오류(`TextStructureProjectionError` 는 ValueError 다)와 조회 실패(포트가
            # 낸 ValueError·홈 손상)를 같은 처분으로 닫는다: 둘 다 「지금 화면이 고른 내용을
            # 말할 수 없다」이고, 사용자가 할 일도 같다(템플릿을 다시 확인).
            return text, SELECTION_UNAVAILABLE_NOTE, scan.summary.markers

    def close(self) -> None:
        """세션 파기 — 이탈이 성사된 뒤 호출한다(가드는 웹→`leave_guard` 가 먼저 본다)."""
        with self._state_lock:
            self._clear()
            self._push()

    @property
    def is_open(self) -> bool:
        return self.base_job is not None

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 파생
    def _display_pos(self) -> int:
        """작업점의 표시 서수(0-기반, 없으면 -1) — 자리·순회 경계가 **같은 값**을 쓴다.

        표시 순서는 고정 사본 순서다(U2 §2.15, #338 — ``TxtQueueModel.display_order`` 가
        복사에 재배열되지 않는다). 그래서 사람이 읽는 자리(`position`)와 이동 경계
        (`can_prev`/`can_next`)의 갈림 자체가 소멸했다 — 순서가 하나면 답도 하나다.
        """
        cur = self.queue.current
        order = self.queue.display_order()
        return order.index(cur) if cur is not None and cur in order else -1

    def _current_record(self) -> dict:
        cur = self.queue.current
        if cur is None or not (0 <= cur < len(self.records)):
            return {}
        return self.records[cur]

    def _rules_signature(self) -> str:
        """지금 카드를 만드는 규칙의 지문 — **보이는 문장을 바꾸는 것 전부**를 담는다.

        결속·유형·상수·표시형은 물론 **전각 치환 여부**까지 센다: 그것도 복사되는 문자열을
        바꾸므로, 빼면 「복사한 뒤 전각을 켰다」가 조용히 지나간다. 확정 열은 담지 않는다 —
        확정-비움은 게이트의 축이지 렌더되는 값의 축이 아니다(확정을 켜도 문장은 그대로다).
        """
        if self.mapping is None:
            return ""
        # `confirmed` 도 담는다(5R P2). 무결속·미확정 행은 `live_profile` 에서 **빠져** 토큰이
        # `{{이름}}` 그대로 복사되고, 확정하면 확정-비움이 되어 빈 문자열로 바뀐다 — 즉 확정은
        # 게이트의 축만이 아니라 **복사되는 문자열의 축**이기도 하다. 2R 에서 "확정을 켜도
        # 문장은 그대로"라고 단정한 것이 틀렸다(`live_profile` 의 계약이 반대로 적고 있다).
        rows = tuple(
            (r.template_field, r.source, r.type, r.const, r.fmt, r.slice, r.confirmed)
            for r in self.mapping.rows
        )
        return repr((rows, self._fullwidth))

    def _review_state(self, index: "int | None") -> str:
        """복사 상태는 **파생**이다 — 복사 시점 지문과 지금 지문의 차이(2R P2).

        저장 사건에 결속하면 「복사 → 편집(카드가 즉시 바뀜) → 아직 저장 안 함」 구간에서
        배지가 「복사 완료」로 남아, 사용자가 다시 복사해야 할 행을 건너뛴다. §11 이 요구하는
        「이미 복사한 레코드는 다시 확인 필요」도 이 파생이 자연히 만족한다(저장이 아니라
        규칙이 갈린 것이 원인이므로).
        """
        if index is None or index not in self._copied_rules:
            return REVIEW_TODO
        return (
            REVIEW_COPIED
            if self._copied_rules[index] == self._edits.signature(index, self._rules_signature())
            else REVIEW_RECHECK
        )

    def _card_view(self, index: "int | None", now: "datetime | None" = None) -> CardView:
        """행 하나의 본문 판정 — 렌더(원문) 위에 그 행의 편집본을 얹는다(판정은 링1)."""
        assert self.mapping is not None
        record = self.records[index] if index is not None and 0 <= index < len(self.records) else {}
        rendered = render_card(
            self._card_text, self.mapping, record,
            fullwidth=self._fullwidth, now=now if now is not None else self._clock(),
        )
        return card_view(
            rendered, frozenset(self.mapping.declared_empty_fields()),
            gate_empty_fields(rendered.report, self.mapping), self._edits.get(index),
            fullwidth=self._fullwidth,
        )

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        base = {
            "open": self.is_open,
            "job_name": self.job_name,
            "mode_label": work_mode_label(WORK_MODE_TEXT),
            "view": self.view,
            "target_font": self._font.value,
            # 상시 사실(투영 실패 사유)만 싣는다 — 사건 노트를 내던 유일한 발신자(「기본 규칙으로
            # 저장」 성공 배너)는 연결 편집과 함께 이 화면을 떠났다(#1148).
            "notice": {"text": self._selection_note, "level": "warn" if self._selection_note else "muted"},
        }
        if not self.is_open or self.mapping is None:
            # 세션 없음 = 빈 골격. 표면은 이 상태에서 화면을 세우지 않는다(라우팅 가드).
            base.update({
                "card": None, "template_path": "", "guard": {"armed": False, "lines": []},
                "revision": {"template": 0, "binding": 0}, "total": 0, "copied_count": 0,
            })
            return base

        cur = self.queue.current
        view = self._card_view(cur)
        shown, shown_marks = (
            (view.text, view.marks) if self.view == "filled" else raw_card(self.template_text)
        )
        total = len(self.records)
        # 큐 퇴화(승계 — 「기안」 결정 8): 1건이면 순회할 곳이 없어 큐 장치 3종을 숨긴다.
        card = {
            "index": cur,
            "has_current": cur is not None,
            "queue_degenerate": total <= 1,
            # 자리도 경계도 **같은 표시 서수**에서 나온다(U2 §2.15, #338): 표시 순서가 고정
            # 사본 순서 하나뿐이라(복사는 색만 바꾼다) 「자리는 고정인데 순회는 큐 순서」라는
            # 두-순서 화해가 필요 없어졌다. 부제 「선택 당시 표시순서로 고정된 항목」이
            # 숫자·점 띠·이동 경계 모두에서 참이다(§13-13).
            "position": self._display_pos(),
            "can_prev": self._display_pos() > 0,
            "can_next": 0 <= self._display_pos() < len(self.queue.display_order()) - 1,
            "source_row": self.source_rows[cur] if cur is not None else None,
            "review_state": self._review_state(cur),
            # 큐 색인(직접 이동) — 「기안」 점 표시와 같은 형상. 순서는 **고정 사본 순서**
            # (#338: 복사해도 점의 자리는 그대로, 상태 색만 바뀐다)이고 자리 라벨은
            # **원본 행 번호**다(고정 사본의 정체를 사람이 아는 이름으로 말한다).
            "index_map": [
                {
                    "index": i,
                    "row": self.source_rows[i] if 0 <= i < len(self.source_rows) else None,
                    "state": ("current" if i == cur
                              else ("copied" if self.queue.is_copied(i) else "uncopied")),
                    "recheck": self._review_state(i) == REVIEW_RECHECK,
                }
                for i in self.queue.display_order()
            ],
            "uncopied_count": len(self.queue.uncopied()),
            "advance_after": self._advance_after,
            # 본문 = 편집기 문서(#1148 PR B). 표식 좌표는 UTF-16(웹 문자열 단위)이고, 종류는
            # 값(fill)·빈 값(blank)·비워 둠(declared)·미치환(missing)이다. 표면은 받은 좌표에
            # 장식만 얹는다 — 빈 자리가 채워졌는지도 여기서 판정해 범위로 낸다.
            "text": shown,
            "marks": utf16_marks(shown, shown_marks),
            "edited": cur in self._edits,
            # 표면이 문서를 **갈아 끼울** 때만 바뀐다(행·보기·전각·되돌리기). 편집 왕복의
            # 메아리는 같은 키라 표면이 들고 있는 문서·캐럿을 건드리지 않는다.
            "text_key": f"{cur}|{self.view}|{int(self._fullwidth)}|{self._edits.epoch}",
            "missing_fields": view.missing_fields,
            # 게이트·완료 노트가 소비하는 결손 — **확정-비움은 뺀다**(결정 12). 편집본에서
            # 채운 빈 자리도 뺀다. 표식은 그대로 남아 어디가 빈 값이었는지 보인다.
            "empty_fields": view.empty_fields,
            "lint": {
                "proportional": is_proportional_font(self._font.value),
                "space_run": view.space_run,
                "applied": self._fullwidth,
                "active": self._fullwidth
                or (is_proportional_font(self._font.value) and view.space_run),
            },
            "last_copy": self._last_copy,
            "copied_total": self._copied_total,
            # 복사 차단 사유 — 버튼의 활성 여부와 그 이유를 **같은 값**에서 낸다(표면이
            # `has_current` 만 보고 열어 두면 원문 보기에서 채운 문장이 나간다).
            "copy_block": self._copy_block(),
        }
        base.update({
            "card": card,
            "total": total,
            "copied_count": self.queue.copied_count(),
            "is_complete": self.queue.is_complete(),
            "fullwidth": self._fullwidth,
            # 「템플릿 편집」이 여는 파일 — 진입 때 읽은 그 템플릿이다(#1148). 연결 편집은
            # 작업 이름(`job_name`)으로 연다. 이 화면은 연결을 편집하지 않으므로 둘 다 나가는 문이다.
            "template_path": self.base_job.template_path if self.base_job else "",
            "revision": {
                "template": self.base_job.template_revision if self.base_job else 0,
                "binding": self.base_job.binding_revision if self.base_job else 0,
            },
            "guard": self.leave_guard(),
        })
        return base

    def _copy_block(self) -> str:
        """복사 차단 사유(없으면 ``""``) — 「보이는 것 = 복사되는 것」의 술어(결정 17).

        원문 보기는 토큰을 **채우지 않은** 템플릿을 그린다(`_raw_segments`). 복사 경로는
        보기와 무관하게 언제나 채운 카드를 쓰므로, 그 상태로 복사하면 화면엔 ``{{수신}}`` 이
        보이는데 클립보드엔 값이 채워진 문장이 들어간다 — 원문을 복사한 줄 알고 붙여넣은
        사람은 잘못된 문서를 만든다. 이 화면의 복사는 **채운 모습 하나**이므로, 원문 보기에선
        조용히 다른 것을 주지 않고 **복사하지 않고 사유를 말한다**(confirm-or-alarm).

        **구간 표기가 있으면 물질화 포트가 있어야 한다**(S10-04 #861). S10-03 은 이 자리를
        상시 차단으로 닫아 두었다 — 화면의 접기는 **투영**이고 투영은 실행 권위가 아니어서,
        그대로 내보내면 고르지 않은 선택지와 마커 텍스트가 붙여넣어졌기 때문이다. 이제 복사는
        Sealed Plan 이 물질화한 bytes 를 내보내므로 그 차단이 사라졌고, 남은 것은 포트 미주입
        (오배선)뿐이다. 판정 원천은 진입 시 스캔 하나다(재스캔 0 — 세션 텍스트는 고정 사본이라
        다시 세면 같은 값이고, 두 번 세면 값이 갈릴 자리만 생긴다).
        """
        if self._marker_count and self._txt_materialization is None:
            return COPY_BLOCK_MATERIALIZATION_UNAVAILABLE
        if self.view != "filled":
            return "원문 보기에서는 복사하지 않습니다. 「채운 모습」으로 바꾼 뒤 복사하세요."
        return ""

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 액션
    def dispatch(self, action: str, payload: dict):
        """액션 1건 — **핸들러가 선언한 표식을 읽는다**(「기안」·「문서 만들기」와 같은 규약).

        표식을 안 읽으면 그것을 붙인 자리가 조용히 죽는다: `is_query` 는 무변이 질의라
        재렌더할 것이 없다(복사 사전확인이 모달 직전에 화면 전체를 다시 짓지 않게).

        변이 동작은 **직전 왕복의 복사 완료 노트를 무효화한다**(「기안」 dispatch 승계):
        작업점이 옮겨지면 그 문장은 **다른 카드**의 사실이 된다(지금 카드가 이미 복사된
        것으로 읽혀 붙여넣기를 건너뛴다).

        **모든 액션이 세션 잠금 안이다**(6R P1). 변이는 진행 중인 복사 거래의 렌더와
        `note_copied` 사이로 끼어들 수 없어야 하고(끼어들면 옛 카드의 문자열을 새 작업점의
        복사 완료로 찍는다), 질의도 전이 중간을 읽지 않아야 한다 — 복사 사전확인이 내는
        토큰이 반쪽 상태의 정체이면 3R 이 세운 결속이 그 자리에서 무너진다.
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 workbench 액션: {action!r}")
        with self._state_lock:
            if getattr(handler, "is_query", False):
                return handler(payload)
            self._last_copy = None
            result = handler(payload)
            self._push()
            return result

    def _require_open(self) -> None:
        if not self.is_open:
            raise ValueError("작업대 세션이 없습니다. 「문서 만들기」에서 다시 시작하세요.")

    # ---- 작업점 이동·보기
    def _do_step(self, p: dict) -> None:
        self._require_open()
        self.queue.step(int(p.get("delta", 0)))

    def _do_set_current(self, p: dict) -> None:
        self._require_open()
        self.queue.set_current(int(p["index"]))

    def _do_toggle_advance(self, p: dict) -> None:
        self._advance_after = bool(p["value"])

    def _do_set_view(self, p: dict) -> None:
        view = p.get("view", "")
        if view not in _VIEWS:  # fail-closed — 표면 오타로 빈 카드를 그리지 않는다
            raise ValueError(f"알 수 없는 보기: {view!r}")
        self.view = view

    def _do_set_target_font(self, p: dict) -> None:
        self._font.set(p.get("font", ""))

    def _do_set_fullwidth(self, p: dict) -> None:
        self._fullwidth = bool(p["value"])

    # ---- 복사 게이트(브리지가 클립보드를 쓰기 전에 묻는다)
    def _do_copy_precheck(self, p: dict) -> dict:
        """복사 직전 판정 — 미치환·빈 값이 있으면 표면이 확인을 한 번 받는다."""
        self._require_open()
        cur = self.queue.current
        view = self._card_view(cur)
        return {
            # 사전확인이 **어느 카드의 것인지**를 함께 돌려준다 — 웹이 이 토큰을 그대로
            # 복사 호출에 실어 「확인 대상 = 복사 대상」을 만든다.
            "token": self.copy_token(),
            "row": self.source_rows[cur] if cur is not None else None,
            "missing_fields": view.missing_fields,
            "empty_fields": view.empty_fields,
        }

    _do_copy_precheck.is_query = True  # type: ignore[attr-defined]

    def copy_token(self) -> str:
        """지금 복사될 카드의 **정체** — 사전확인과 실제 쓰기를 묶는 값(3R P1).

        작업점과 지금 규칙을 함께 담는다: 둘 중 무엇이 바뀌어도 사용자가 확인한 카드가
        아니게 되기 때문이다. 브리지가 이 값을 대조해 어긋나면 쓰지 않는다 — 복사를 빠르게
        두 번 누르거나 그사이 이동하면 **확인하지 않은 카드**가 클립보드로 나가던 창을 닫는다.
        """
        cur = self.queue.current
        return "" if cur is None else f"{cur}|{self._edits.signature(cur, self._rules_signature())}"

    # ---- 본문 임시 편집(#1148 PR B) — 그 행 복사본만, 이 세션에만
    def _do_set_card_text(self, p: dict) -> None:
        """행 하나의 편집본을 받는다. 원문과 같아지면 편집이 없는 것으로 접는다.

        정체는 payload 의 ``index`` 다(작업점이 아니다): 친 글자가 늦게 도착하는 사이 「다음」이
        먼저 착지해도 편집이 남의 행에 붙지 않는다.
        """
        self._require_open()
        if self.view != "filled":  # 원문 보기는 읽기 전용이다 — 채운 모습만 복사된다
            raise ValueError("원문 보기에서는 본문을 고치지 않습니다.")
        index = int(p["index"])
        if not 0 <= index < len(self.records):
            raise ValueError(f"없는 항목입니다: {index}")
        self._edits.put(index, str(p["text"]), self._card_view(index).base)

    def _do_revert_card(self, p: dict) -> None:
        """「원래대로」 — 그 행의 편집본을 버리고 원문으로 되돌린다."""
        self._require_open()
        self._edits.revert(int(p["index"]))

    # ---- 이탈 가드(T3 승계) — 복사 진행·다시 확인 대기를 열거한다
    def leave_guard(self) -> dict:
        """이탈 시 잃는 것의 **열거**. 문안은 웹이 짓되 집합은 여기가 낸다.

        가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고 = 거짓말). 이 화면은 연결을
        편집하지 않으므로(#1148) 잃는 것은 세션의 진행 사실 둘 — 복사 진행과 다시 확인 대기 —
        뿐이고, 둘은 다른 사실이라 **따로** 센다.
        """
        if not self.is_open:
            return {"armed": False, "lines": []}
        lines: "list[str]" = []
        copied, total = self.queue.copied_count(), len(self.records)
        if 0 < copied < total:
            lines.append(f"복사 진행 {copied}/{total}건 — 나가면 이 진행은 사라집니다.")
        # **다시 확인 대기도 미완이다**(5R P2). 전건을 복사한 뒤 전각 정렬을 바꾸면 복사
        # 진행(=total)은 끝났지만, 그 문서들은 **지금 규칙의 산출물이 아니다** —
        # 다시 복사해야 한다는 사실이 세션과 함께 사라지면 사용자는 낡은 문서를 붙여넣은 채
        # 끝난다. 가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고도, 과소경고도 아니게).
        recheck = sum(
            1 for i in self._copied_rules if self._review_state(i) == REVIEW_RECHECK
        )
        if recheck:
            lines.append(
                f"규칙이 바뀌어 다시 확인해야 하는 항목 {recheck}건 — 나가면 그 표시가 사라집니다."
            )
        if self._edits:
            lines.append(f"임시로 고친 항목 {len(self._edits)}건 — 나가면 고친 내용은 사라집니다.")
        return {"armed": bool(lines), "lines": lines}

    def close_guard_reason(self) -> str:
        """창 종료 가드 참여(F6 1R P2) — 이탈 가드와 **같은 술어**를 쓴다.

        back 으로 나가면 묻고 창을 닫으면 안 묻는 것은 같은 소실에 두 답을 주는 것이다.
        그래서 문안만 창 종료 문맥으로 바꾸고 판정은 :meth:`leave_guard` 하나에 둔다.

        **다른 스레드에서 온다**(창 종료 훅) — 그래서 판정을 세션 잠금 아래에서 읽는다.
        진행 중인 복사 거래의 중간을 보면 「잃을 것 없음」과 「있음」이 왕복마다 갈린다.
        """
        with self._state_lock:
            return (
                "검토·복사 작업대의 복사 진행 또는 임시로 고친 본문"
                if self.leave_guard()["armed"] else ""
            )

    def _do_leave_guard(self, p: dict) -> dict:
        return self.leave_guard()

    _do_leave_guard.is_query = True  # type: ignore[attr-defined]

    def _do_close(self, p: dict) -> dict:
        """세션 파기 — 웹이 가드 처분을 마친 뒤 부른다."""
        self._clear()
        return {"ok": True}

    # ------------------------------------------------ 클립보드 복사 거래
    # app.copy_clipboard(screen, token) 이 :meth:`copy_to` 하나를 부른다(대조·렌더·쓰기·전진).
    def can_copy(self) -> bool:
        """복사 가능 = 세션이 있고 작업점이 실재하며 **채운 모습을 보고 있다**.

        「기안」의 가상 카드(무데이터 직접 입력)는 여기 없다 — 작업대는 언제나 고정 사본
        위에 서므로 레코드 없는 복사가 성립하지 않는다(그 경로는 휘발 세션의 것이고 PR-B
        에서 함께 죽는다). 보기 축은 :meth:`_copy_block` 이 진다.
        """
        return self.is_open and self.queue.current is not None and not self._copy_block()

    def copy_to(self, token: str, write) -> dict:
        """복사 한 건을 **원자로** 처리한다 — 대조·렌더·쓰기·전진이 한 임계구역 안이다.

        **왜 토큰만으로 부족했나**(5R P1 — 3R 픽스가 연 창): 3R 은 확인 대상과 복사 대상을
        토큰으로 **묶었지만**, 대조와 쓰기 사이를 잠그지 않았다. 브리지가 「대조 → 렌더 →
        쓰기 → 전진」을 네 걸음으로 밟는 동안 두 호출이 겹치면 **둘 다 같은 토큰으로 통과**
        하고, 앞선 호출이 자동 전진으로 작업점을 옮긴 뒤 뒤선 호출이 *새* 카드를 렌더해
        복사한다. 정체를 묶어도 **시간**을 안 묶으면 같은 창이 남는다(F3 4R 이 존 세대에서
        배운 것과 같은 축: 공간·이름을 닫아도 시간 축은 따로 닫아야 한다).

        그래서 거래의 **소유권을 옮겼다**: 브리지는 OS 클립보드 쓰기 함수만 건네고, 순서와
        원자성은 이 컨트롤러가 진다. 겹친 두 번째 호출은 잠금에서 기다렸다가 **바뀐 작업점**
        때문에 토큰 대조에서 걸린다 — 조용한 오복사 대신 stale 재진술이 나간다.

        **왜 복사끼리 잠그는 것으로도 부족했나**(6R P1): 잠금은 잠금을 잡는 쪽끼리만
        배제한다. 복사만 잠그면 「다음」·보기 전환·이탈은 그대로 임계구역 **안으로** 들어와,
        렌더와 :meth:`note_copied` 사이에서 작업점을 옮기거나(옛 카드의 문자열이 새 작업점의
        복사 완료로 찍힌다) 세션을 비운다(이미 성공한 복사가 `mapping is None` 에서 터진다).
        그래서 잠금의 정의를 「복사 거래」에서 **「세션 상태 전이」**로 넓혔다 —
        :meth:`dispatch`·:meth:`open`·:meth:`close` 가 같은 잠금에 참여한다.
        """
        with self._state_lock:
            if not self.is_open:
                return {"copied": False, "missing_fields": [], "empty_fields": [],
                        "error": "작업대 세션이 없습니다."}
            block = self._copy_block()
            if block:
                # 버튼이 이미 닫혀 있지만 잠금은 DOM 이 아니라 상태가 진다 — 그사이 보기가
                # 바뀐 왕복도 여기서 걸린다(사유는 화면 안에서 말한다).
                return {"copied": False, "missing_fields": [], "empty_fields": [],
                        "error": block}
            if token != self.copy_token():
                return {"copied": False, "stale": True,
                        "missing_fields": [], "empty_fields": []}
            if not self.can_copy():
                return {"copied": False, "missing_fields": [], "empty_fields": []}
            # 「오늘 날짜」의 기준 시각은 이 거래에서 **한 번**만 읽는다(RC-02 · #950): 카드 렌더와
            # 봉인 물질화가 각자 시계를 읽으면 분 단위 서식에서 두 글자가 갈려 조용히 복사가 막힌다.
            now = self._clock()
            view = self._card_view(self.queue.current, now)
            if self._marker_count:
                # slot-bearing 은 화면이 그린 투영이 아니라 **봉인된 실행 산출**을 대조한다 —
                # 대조 대상은 편집 **전** 원문이다. 원문이 봉인 산출과 같을 때만 그 위에 얹은
                # 편집본(없으면 원문)을 내보낸다(#1148 PR B).
                materialized, reason = self._materialize_current(now)
                if materialized is None:
                    return {"copied": False, "missing_fields": [], "empty_fields": [],
                            "error": reason}
                if materialized != view.base:
                    return {"copied": False, "missing_fields": [], "empty_fields": [],
                            "error": COPY_BLOCK_MATERIALIZATION_DIVERGED}
            write(view.text)                  # OS 쓰기도 임계구역 안 — 성사 뒤에만 전진한다
            self.note_copied(view)
            return {"copied": True, "missing_fields": list(view.missing_fields),
                    "empty_fields": list(view.empty_fields)}

    def _materialize_current(self, now: datetime) -> "tuple[str | None, str]":
        """작업점 레코드의 물질화 결과 — (검증된 텍스트, 사유). 정확히 한쪽만 산다.

        판정은 전부 저쪽(봉인·record 검증·start gate·postcondition)의 것이고 이 컨트롤러는
        결과를 나르기만 한다 — 여기서 사유를 다시 조립하면 같은 상태를 두 곳이 말하게 된다.
        그래서 포트가 내는 것도 값 두 개뿐이다: 봉인·VDR·start gate 의 타입을 이 화면이
        알면 「형체를 모른다」는 계약이 이름만 남는다. 포트가 예외를 던지면 그것도 사유로
        접어 복사만 막는다(세션은 살아 있다).
        """
        assert self._txt_materialization is not None
        try:
            return self._txt_materialization(
                self.job_name, self._current_record(), self.copy_token(), now
            )
        except Exception as exc:  # noqa: BLE001 — 복사 차단 사유로 접는다(조용한 성공 0)
            return None, f"문서를 만들지 못했습니다: {exc}"

    def note_copied(self, view: CardView) -> None:
        """복사 성사 뒤 상태 전진 — 클립보드 쓰기가 **성공한 뒤에만** 불린다.

        작업점은 복사해도 그 카드에 머문다(조용한 이동 금지) — 전진은 사용자가 켰을 때만.

        **세션 잠금 안에서 불린다**(:meth:`copy_to` 가 유일한 실호출자). 여기서 다시 읽는
        작업점·지문은 방금 렌더한 카드의 것이어야 하므로, 잠금 밖에서 부르면 그 사이의
        이동이 **다른 카드**를 복사 완료로 찍는다. 잠금은 재진입 가능(`RLock`)이라 이
        메서드를 잠금 안에서 부르는 것이 안전하다.
        """
        cur = self.queue.current
        if cur is None:
            return
        stamp_error = self._stamp_first_copy()
        self._last_copy = {
            "row": self.source_rows[cur],
            "missing_fields": list(view.missing_fields),
            "empty_fields": list(view.empty_fields),
            # 스탬프 실패는 삼키지 않는다 — 복사는 이미 일어났으므로 예외로 완료 노트를
            # 날리는 건 더 큰 손실이고, 조용히 넘기면 이력이 아무 말 없이 이 사건을 잃는다.
            "stamp_error": stamp_error,
        }
        self._copied_total += 1
        # T11 검토·복사(#894) — 카운터가 실제로 오른 자리다(작업대 복사 카운터 ≥1). 클립보드
        # 쓰기가 성공한 뒤에만 여기 오므로 「복사가 곧 완료 표시」와 같은 사건에 결속된다.
        self._tutorial(Milestone.COPY_DRAFT)
        # 지금 규칙으로 복사했다 — 그 지문을 못박는다. 다시 복사하면 덮어써 재확인이 해소되고,
        # 규칙이 갈리면 같은 값에서 파생이 「다시 확인 필요」로 넘어간다(별도 무효화 코드 없음).
        self._copied_rules[cur] = self._edits.signature(cur, self._rules_signature())
        self.queue.copy(cur)
        if self._advance_after:
            self.queue.advance_to_next_uncopied()
        self.queue.reconcile()
        self._push()

    def _stamp_first_copy(self) -> str:
        """세션 첫 복사에서 **최근 사용**을 영속한다(§19.4) — 성공 시 ``""``, 실패 시 사유.

        **두 매체는 다른 술어를 쓰고 같은 필드를 쓴다.** HWPX 는 완주(전건 성공)에서,
        TXT 는 레코드 **복사 완료 1건**에서 찍는다 — 계약 §19.4 의 표 그대로다. 저장처가
        같은 `Job.last_run_at` 인 것은 어휘의 혼선이 아니라 이 축의 정의가 「의미 있는 결과
        행동의 시간 순위」이기 때문이다(§19.2). 그 시각을 **문구로** 갈라 말하던 표면
        (`last_use_label` + 라이브러리 목록·상세)은 걷혔고, 남은 소비자는 「최근 사용」 보기의
        정렬이다 — 순위 축이므로 매체별 술어 차이가 표시로 새지 않는다.

        쓰기는 레지스트리의 **잠긴 경로**를 탄다(`stamp_last_run`) — 작업대 세션이 열려
        있는 동안 편집기·라이브러리가 같은 작업을 만질 수 있고, 잠금 없는 통째 저장은 늦게
        착지한 쪽이 상대 변경을 되돌린다.

        **검토 기준선(`rules`)은 넘기지 않는다**(지도 §10.15 판정 I·J의 따름정리): TXT 는
        검토 요구 축을 지지 않으므로, 그 기준선을 여기서 찍으면 짓지 않은 축에 「검토했다」를
        기록하는 것이 된다. 하지 않은 검토를 기록하는 쪽이 조용한 누락보다 나쁘다.
        """
        if self._stamped or not self.job_name:
            return ""
        try:
            # rules=None 명시 = 검토 기준선 불변(위 docstring) — use case 가 기본값을 두지
            # 않아 이 선택이 호출부에 보인다(P2-21 #569).
            job = stamp_run_completion(
                self.registry, self.job_name,
                self._clock().isoformat(timespec="seconds"), rules=None,
            )
        except (OSError, ValueError) as exc:
            return str(exc) or exc.__class__.__name__
        self._stamped = True
        if self.base_job is not None:  # 인메모리 사본도 같은 사실을 들게(디스크와 갈리지 않게)
            self.base_job = replace(self.base_job, last_run_at=job.last_run_at)
        return ""

    # ------------------------------------------------------------- 진입 자격
    @staticmethod
    def accepts(job: Job) -> bool:
        """이 작업이 작업대의 것인가 — 방식 파생(§19.1). 표면이 확장자를 다시 읽지 않게."""
        return work_mode(job.template_path) == WORK_MODE_TEXT
