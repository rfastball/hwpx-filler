"""TXT 검토·복사 작업대 — v6 표면 S7(계약 §11). 재작성 F6 PR-A.

「문서 만들기」에서 TXT 작업을 고르고 실행하면 여기 온다. 데이터·범위 선택은 **저쪽이**
끝내고, 이 화면은 그 결과를 **고정 사본**으로 받아 레코드 하나씩 검토·복사한다.

**왜 별도 화면인가**(지도 §10.15 판정 E, F7 편집기 승격과 같은 근거): 좌 pane 의 필드 연결
편집은 저장 전까지 미저장 변경이고, 그 이탈 처분이 성립하려면 **나가는 경로가 셀 수 있어야**
한다. 「문서 만들기」 안에 살면 상단 탭·다른 컨트롤이 처분 미확정 이탈구가 되고 가드의
완전성이 표면 수에 비례한다.

**세션은 진입 시 고정 사본이다**(§13-13·§18.11-25). 표시순 투영을 통과한 OrderedSelection 의
복사본을 뜨고, 이후 「문서 만들기」의 검색·필터·정렬·선택 변화가 현재 작업점 순서를 바꾸지
않는다. 그래서 여기엔 데이터 존이 없다 — 데이터를 바꾸려면 나갔다 다시 들어온다.

**좌 pane 은 override 가 아니다**(판정 H). 편집은 저장 전까지 미저장 변경일 뿐이고 착지점은
「기본 규칙으로 저장…」 하나다. 거래 모델은 편집기와 **같은** :class:`EditSession`
(section=`binding`)을 쓴다 — patch 를 두 벌 지으면 같은 상태에 어휘가 둘이 된다.

**경계**: 실제 클립보드 쓰기는 브리지(:meth:`HwpxFillerApi.copy_clipboard`)가 한다. 이
컨트롤러는 시안의 mock 완료 사건이 아니라 **실제 복사**의 앞뒤(게이트·큐 전진·완료 노트)를
소유한다 — v6 §19.4 의 「복사는 mock」 경계 문안은 이 제품에 해당하지 않는다.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..core.format_engine import presets as format_presets
from ..core.job import Job, JobRegistry, content_fingerprint, work_mode
from ..core.mapping import TYPES, MappingProfile
from ..core.text_render import template_fields
from ..gui.edit_session import SECTION_BINDING, EditContext, EditSession
from ..gui.filter_state import sniff_column_kinds
from ..gui.mapping_state import MappingModel
from ..gui.selection_state import SelectionModel
from ..gui.txt_card import card_text, gate_empty_fields, render_card
from ..gui.txt_queue import TxtQueueModel
from ..gui.work_mode import WORK_MODE_TEXT, work_mode_label
from .mapping_verbs import MappingVerbsMixin
from .screens import PushSink
from .settings import is_proportional_font

#: 표시형 프리셋·유형 선택지 — 「기안」·편집기와 **같은 표**(format_engine)에서 뽑는다.
#: 세 표면이 표시형을 달리 부르면 저장 왕복에서 어휘가 갈린다.
_FMT_OPTIONS = {
    t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES
}
_TYPE_LABEL = {"text": "텍스트", "date": "날짜", "amount": "금액"}
_TYPE_OPTIONS = [{"code": t, "label": _TYPE_LABEL[t]} for t in ("text", "date", "amount")]

#: 레코드 검토 상태(§11 마지막 줄) — 복사했더라도 규칙이 바뀌면 **다시 확인 필요**다.
REVIEW_TODO = "todo"
REVIEW_COPIED = "copied"
REVIEW_RECHECK = "recheck"

_VIEWS = ("filled", "raw")


def _row_own(row) -> str:
    """맞추기 행의 소유권 — ``man`` 상수 / ``auto`` 결속 열 / ``""`` 무결속(「기안」과 같은 어휘)."""
    if row.type == "const":
        return "man"
    return "auto" if row.source else ""


class WorkbenchController(MappingVerbsMixin):
    """검토·복사 작업대의 세션 소유자 — 화면 하나에 세션 하나(동시 다중 없음)."""

    name = "workbench"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        target_font,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        # 대상 글꼴은 앱 전역 선언이라 「기안」과 **같은 인스턴스**를 공유한다 — 두 벌이면
        # 같은 사용자 선언에 두 값이 생긴다(PR-B 에서 「기안」이 죽으면 소비자는 하나가 된다).
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
        self.records: "list[dict]" = []
        self.source_rows: "list[int]" = []
        self.mapping: "MappingModel | None" = None
        self.selection = SelectionModel(0)
        self.queue = TxtQueueModel(self.selection)
        self.session: "EditSession | None" = None
        self.view = "filled"
        self._advance_after = False
        self._fullwidth = False
        self._last_copy: "dict | None" = None
        self._copied_total = 0
        # 최근 사용 스탬프는 **세션당 1회**다(§19.4: "한 레코드라도 복사 완료"). 매 복사마다
        # 찍으면 durable 쓰기가 복사 수만큼 늘고, 기록되는 사실은 첫 건과 똑같다.
        self._stamped = False
        # 복사 시점의 **규칙 지문**(행 index → 지문). 검토 상태는 이 값과 지금 지문의 **차이**로
        # 파생한다(2R P2). 종전에는 저장 **사건**이 `_review` 집합을 채웠는데, 그러면 사건
        # 밖의 변화(그냥 매핑을 고친 것)를 못 본다 — 카드는 이미 다른 문장을 보여 주는데
        # 배지는 「복사 완료」라고 말하는 창이 열린다. 사건을 세지 말고 **조건을 재라**.
        self._copied_rules: "dict[int, str]" = {}
        self.notice_text = ""
        self.notice_level = "muted"

    def open(self, job: Job, rows: "list[tuple[int, dict]]") -> None:
        """세션 개시 — 고정 사본을 뜬다. ``rows`` = (원본 행 index, 레코드) 표시순.

        **실패 원자성**: 실패할 수 있는 템플릿 읽기를 **먼저** 끝낸 뒤에 상태를 교체한다.
        템플릿이 사라졌으면 :class:`OSError` 가 올라가고 이전 상태(보통 「세션 없음」)는
        그대로다 — 반쪽 세션으로 화면이 서지 않는다(「기안」 `_restore_from_job` 과 같은 규율).
        파일 읽기는 잠금 **밖**이다: 실패해도 바꾸는 것이 없고, 느린 I/O 로 진행 중인 복사
        거래를 잡아 둘 이유도 없다. 잠그는 것은 교체 자체다.
        """
        text = Path(job.template_path).read_text(encoding="utf-8")
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
            self.records = records
            self.source_rows = [i + 1 for i, _ in rows]  # 1-based 원본 행 번호(정체 병기용)
            self.mapping = mapping
            # 고정 사본 **전체**가 이 세션의 대상이다(선택은 「문서 만들기」에서 이미 끝났다) —
            # 여기서 다시 고르는 축을 만들면 같은 결정을 두 표면이 내리게 된다.
            self.selection = SelectionModel(len(records))
            self.queue = TxtQueueModel(self.selection)
            self.session = EditSession(
                context=EditContext(work=job.name), base=job, section=SECTION_BINDING,
            )
            self._push()

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

    def _set_notice(self, text: str, level: str = "ok") -> None:
        self.notice_text, self.notice_level = text, level

    # ------------------------------------------------------------- 파생
    def _queue_pos(self) -> int:
        """작업점의 **큐 순서** 자리(없으면 -1) — 순회 경계 판정 전용.

        표시 서수와 갈리는 이유: 큐는 복사한 카드를 후미로 보내므로(결정 16) 같은 카드의
        고정 자리는 그대로여도 순회상의 앞뒤는 바뀐다. 두 축을 한 값으로 뭉치지 않는다.
        """
        cur = self.queue.current
        order = self.queue.display_order()
        return order.index(cur) if cur is not None and cur in order else -1

    def _current_record(self) -> dict:
        cur = self.queue.current
        if cur is None or not (0 <= cur < len(self.records)):
            return {}
        return self.records[cur]

    def _profile_over(self, base: Job) -> "MappingProfile":
        """모델이 낸 프로파일 + **이 템플릿에 없는 필드의 기존 매핑**을 그대로 승계한다.

        맞추기 표의 행은 **지금 템플릿의 토큰**에서만 나므로(`template_fields`), 저장된
        프로파일에 그 뒤 사라진·이름이 바뀐 토큰의 매핑이 남아 있으면 모델은 그 행을 아예
        모른다. 그대로 `to_profile()` 을 쓰면 그 매핑들이 **없어지는 것**이 되어, 아무것도
        건드리지 않은 채 들어온 화면이 「저장하지 않은 변경 1건」을 띄우고 이탈 가드가 무장한다
        — 사용자가 한 적 없는 편집이다. 「저장하고 나가기」를 고르면 그 편집이 진짜로 일어나
        매핑이 영구히 지워진다.

        **이 화면은 자기가 편집하지 않는 것을 지우지 않는다**(`_do_save_rules` 가 그룹·태그·
        완주 스탬프를 디스크 최신값으로 승계하는 것과 같은 규율). 사라진 토큰의 정리는
        템플릿 축의 일이고 그 축을 가진 표면(편집기)이 진다.
        """
        assert self.mapping is not None
        profile = self.mapping.to_profile(base.name)
        known = {r.template_field for r in self.mapping.rows}
        carried = [m for m in base.mapping.mappings if m.template_field not in known]
        if not carried:
            return profile
        return replace(profile, mappings=list(profile.mappings) + carried)

    def _draft_job(self) -> "Job | None":
        """지금 화면이 그리는 규칙의 Job 형상 — 판본 대조·저장 대상의 단일 성형.

        매핑만 갈아 끼운다: 작업대는 템플릿도 파일 이름도 건드리지 않으므로(§3.2 — TXT 엔
        파일 이름 규칙 자체가 없다) 그 축을 성형에 넣으면 없는 변경을 만들어 낸다.
        """
        if self.base_job is None or self.mapping is None:
            return None
        return replace(self.base_job, mapping=self._profile_over(self.base_job))

    def _changed_fields(self) -> "list[dict]":
        """저장하면 달라지는 필드 목록 — 「기본 규칙으로 저장」 확인이 **전부 나열**한다(§11)."""
        draft = self._draft_job()
        if draft is None or self.session is None:
            return []
        changes = self.session.changes(draft).get(SECTION_BINDING, {})
        return [{"name": name, **axes} for name, axes in changes.items()]

    def _pending_binding(self) -> bool:
        """확정하지 않은 매핑 편집이 있는가 — 저장되진 않지만 **버려지면 사라진다**."""
        if self.mapping is None:
            return False
        return any(r.touched and not r.confirmed for r in self.mapping.rows)

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
            (r.template_field, r.source, r.type, r.const, r.fmt, r.confirmed)
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
            if self._copied_rules[index] == self._rules_signature()
            else REVIEW_RECHECK
        )

    # ------------------------------------------------------------- 스냅샷
    def snapshot(self) -> dict:
        base = {
            "open": self.is_open,
            "job_name": self.job_name,
            "mode_label": work_mode_label(WORK_MODE_TEXT),
            "view": self.view,
            "target_font": self._font.value,
            "notice": {"text": self.notice_text, "level": self.notice_level},
        }
        if not self.is_open or self.mapping is None:
            # 세션 없음 = 빈 골격. 표면은 이 상태에서 화면을 세우지 않는다(라우팅 가드).
            base.update({
                "card": None, "rows": [], "source_fields": [], "dirty": {"count": 0, "fields": []},
                "can_save": False, "save_block": "", "guard": {"armed": False, "lines": []},
                "revision": {"template": 0, "binding": 0}, "total": 0, "copied_count": 0,
            })
            return base

        record = self._current_record()
        rendered = render_card(
            self.template_text, self.mapping, record, fullwidth=self._fullwidth
        )
        report = rendered.report
        cur = self.queue.current
        missing_set, empty_set = set(report.missing_fields), set(report.empty_fields)
        suggestions = self.mapping.suggestions()
        rows = [
            {
                "name": r.template_field,
                "state": ("missing" if r.template_field in missing_set
                          else ("blank" if r.template_field in empty_set else "fill")),
                "source": r.source,
                "own": _row_own(r),
                "manual": r.type == "const",
                "value": self.mapping.live_profile().apply(record).get(r.template_field, ""),
                "fmt_kind": r.type,
                "fmt_code": r.fmt,
                "suggest": suggestions.get(r.template_field, ""),
                "can_revert": r.type == "const" and bool(r.source),
                "confirmed": r.confirmed,
                "blank_declared": r.is_empty_confirmed(),
            }
            for r in self.mapping.rows
        ]
        changed = self._changed_fields()
        total = len(self.records)
        # 큐 퇴화(승계 — 「기안」 결정 8): 1건이면 순회할 곳이 없어 큐 장치 3종을 숨긴다.
        card = {
            "index": cur,
            "has_current": cur is not None,
            "queue_degenerate": total <= 1,
            # 작업점 자리 = **고정 사본의 서수**(0-기반)다. `TxtQueueModel.position_of` 는
            # *미처리 큐* 안의 1-기반 순번이라 여기 쓸 수 없다: ①1-기반이라 표면이 +1 하면
            # 진입부터 어긋나고 ②복사할 때마다 번호가 **다시 매겨지며** 복사한 카드는 아예
            # None 이 된다. 이 화면의 부제는 「선택 당시 표시순서로 고정된 항목」이라고
            # 말하므로, 사람이 읽는 숫자도 그 고정 순서를 따라야 참이다(§13-13).
            "position": cur,
            # 이동 가능 여부는 **큐 순서**의 질문이다(2R P1). 표시 서수(`position`)는 고정
            # 사본의 자리라 순회 경계를 답할 수 없다: 복사하면 그 카드가 후미로 가므로 자리는
            # 그대로인데 다음/이전은 달라진다. 하나의 값으로 두 질문에 답하면 그중 하나는
            # 반드시 틀린다 — 실제로 복사 직후 「다음」이 눌리지만 아무 일도 안 하고 「이전」은
            # 비활성이라 그 카드에 갇혔다. 그래서 경계도 Python 이 낸다.
            "can_prev": self._queue_pos() > 0,
            "can_next": 0 <= self._queue_pos() < len(self.queue.display_order()) - 1,
            "source_row": self.source_rows[cur] if cur is not None else None,
            "review_state": self._review_state(cur),
            # 큐 색인(직접 이동) — 「기안」 점 표시와 같은 형상. 순서는 큐 표시순이고 자리
            # 라벨은 **원본 행 번호**다(고정 사본의 정체를 사람이 아는 이름으로 말한다).
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
            "segments": (
                [{"text": s.text, "kind": s.kind, "name": s.name} for s in rendered.segments]
                if self.view == "filled" else self._raw_segments()
            ),
            "missing_fields": report.missing_fields,
            # 게이트·완료 노트가 소비하는 결손 — **확정-비움은 뺀다**(결정 12). 렌더는
            # 그대로 〈빈 값〉으로 그린다: 보이는 것은 같고 「확인해야 하는가」만 다르다.
            "empty_fields": gate_empty_fields(report, self.mapping),
            "lint": {
                "proportional": is_proportional_font(self._font.value),
                "space_run": rendered.space_run,
                "applied": self._fullwidth,
                "active": self._fullwidth
                or (is_proportional_font(self._font.value) and rendered.space_run),
            },
            "last_copy": self._last_copy,
            "copied_total": self._copied_total,
            # 복사 차단 사유 — 버튼의 활성 여부와 그 이유를 **같은 값**에서 낸다(표면이
            # `has_current` 만 보고 열어 두면 원문 보기에서 채운 문장이 나간다).
            "copy_block": self._copy_block(),
        }
        base.update({
            "card": card,
            "rows": rows,
            "source_fields": list(self.records[0].keys()) if self.records else [],
            "fmt_options": _FMT_OPTIONS,
            "type_options": _TYPE_OPTIONS,
            "total": total,
            "copied_count": self.queue.copied_count(),
            "is_complete": self.queue.is_complete(),
            "fullwidth": self._fullwidth,
            # 저장하지 않은 변경 — v6 배지 「이번 작업에만 적용 중」은 사망했다(판정 H):
            # override 가 없으므로 그 배지가 말할 상태가 없다.
            "dirty": {"count": len(changed), "fields": changed,
                      "pending": self._pending_binding()},
            "can_save": bool(changed) and not self._save_block(),
            "save_block": self._save_block(),
            "revision": {
                "template": self.base_job.template_revision if self.base_job else 0,
                "binding": self.base_job.binding_revision if self.base_job else 0,
            },
            "guard": self.leave_guard(),
        })
        return base

    def _raw_segments(self) -> "list[dict]":
        """원문 보기 — 토큰을 채우지 않고 ``{{이름}}`` 그대로 보여준다(§11 원문/채운 모습)."""
        from ..core.text_render import render_segments

        segments, _ = render_segments(self.template_text, {})
        return [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments]

    def _save_block(self) -> str:
        """저장 차단 사유(없으면 ``""``) — 확정하지 않은 편집이 있으면 먼저 확정한다."""
        if self._pending_binding():
            return "확정하지 않은 편집이 있습니다. 각 행의 확정 열을 켠 뒤 저장하세요."
        return ""

    def _copy_block(self) -> str:
        """복사 차단 사유(없으면 ``""``) — 「보이는 것 = 복사되는 것」의 술어(결정 17).

        원문 보기는 토큰을 **채우지 않은** 템플릿을 그린다(`_raw_segments`). 복사 경로는
        보기와 무관하게 언제나 채운 카드를 쓰므로, 그 상태로 복사하면 화면엔 ``{{수신}}`` 이
        보이는데 클립보드엔 값이 채워진 문장이 들어간다 — 원문을 복사한 줄 알고 붙여넣은
        사람은 잘못된 문서를 만든다. 이 화면의 복사는 **채운 모습 하나**이므로, 원문 보기에선
        조용히 다른 것을 주지 않고 **복사하지 않고 사유를 말한다**(confirm-or-alarm).
        """
        if self.view != "filled":
            return "원문 보기에서는 복사하지 않습니다. 「채운 모습」으로 바꾼 뒤 복사하세요."
        return ""

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 액션
    def dispatch(self, action: str, payload: dict):
        """액션 1건 — **핸들러가 선언한 표식을 읽는다**(「기안」·「문서 만들기」와 같은 규약).

        표식을 안 읽으면 그것을 붙인 자리가 조용히 죽는다: `is_query` 는 무변이 질의라
        재렌더할 것이 없고(복사 사전확인이 모달 직전에 표 전체를 다시 짓는다), `is_no_push`
        는 **포커스된 입력을 서버 푸시가 재구성하지 못하게** 붙인 표식인데 무조건 push 가
        바로 그 재구성을 일으킨다(IME 조합·캐럿이 왕복마다 끊긴다).

        변이 동작은 **직전 왕복의 재진술 둘을 무효화한다**(「기안」 dispatch 승계):
        ①복사 완료 노트 — 작업점이 옮겨지면 그 문장은 **다른 카드**의 사실이 된다(지금 카드가
        이미 복사된 것으로 읽혀 붙여넣기를 건너뛴다). ②저장 성공 배너 — 저장 시점의 상태를
        서술하는데, 그 뒤 편집이 오면 옆의 「저장하지 않은 변경 N건」과 동시에 서서 화면이 두
        말을 한다. 둘 다 **핸들러 앞에서** 지운다: `_do_save_rules` 는 자기 성공 문안을 바로
        그 자리에 남기므로, 뒤에서 지우면 저장이 아무 말도 못 하게 된다.

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
            self.notice_text, self.notice_level = "", "muted"
            result = handler(payload)
            if getattr(handler, "is_no_push", False):
                return result   # 반환 스냅샷으로 JS 가 겨냥 패치(맞추기 표 재구성 금지)
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

    # ---- 필드 연결(좌 pane) — 동사 6종은 :class:`MappingVerbsMixin` 소유(F6 3R).
    # 손으로 다시 짜다 규약이 갈렸던 자리다(표시형이 이름 API 에 index 를 넘겨 **전부**
    # 터졌고, 되돌리기는 스니핑 유형을 잃었고, 결속은 직접 입력 값을 무확인 덮었다).
    # 여기 남는 것은 그 동사들이 쓰는 **훅** 둘뿐이다.
    def _map_source_fields(self) -> "list[str]":
        """결속 후보 열 — 고정 사본의 열 집합(세션 동안 불변)."""
        return list(self.records[0].keys()) if self.records else []

    def _map_kind_of(self, source: str) -> str:
        """결속 대상 열의 스니핑 유형(없으면 ``""``) — 되돌리기·결속이 함께 쓴다."""
        if not source:
            return ""
        return sniff_column_kinds(self.records).get(source, "")

    # ---- 복사 게이트(브리지가 클립보드를 쓰기 전에 묻는다)
    def _do_copy_precheck(self, p: dict) -> dict:
        """복사 직전 판정 — 미치환·빈 값이 있으면 표면이 확인을 한 번 받는다."""
        self._require_open()
        assert self.mapping is not None
        rendered = render_card(
            self.template_text, self.mapping, self._current_record(),
            fullwidth=self._fullwidth,
        )
        cur = self.queue.current
        return {
            # 사전확인이 **어느 카드의 것인지**를 함께 돌려준다 — 웹이 이 토큰을 그대로
            # 복사 호출에 실어 「확인 대상 = 복사 대상」을 만든다.
            "token": self.copy_token(),
            "row": self.source_rows[cur] if cur is not None else None,
            "missing_fields": list(rendered.report.missing_fields),
            "empty_fields": gate_empty_fields(rendered.report, self.mapping),
        }

    _do_copy_precheck.is_query = True  # type: ignore[attr-defined]

    def copy_token(self) -> str:
        """지금 복사될 카드의 **정체** — 사전확인과 실제 쓰기를 묶는 값(3R P1).

        작업점과 지금 규칙을 함께 담는다: 둘 중 무엇이 바뀌어도 사용자가 확인한 카드가
        아니게 되기 때문이다. 브리지가 이 값을 대조해 어긋나면 쓰지 않는다 — 복사를 빠르게
        두 번 누르거나 그사이 이동하면 **확인하지 않은 카드**가 클립보드로 나가던 창을 닫는다.
        """
        cur = self.queue.current
        return "" if cur is None else f"{cur}|{self._rules_signature()}"

    # ---- 기본 규칙으로 저장(§11) — 착지점은 이것 하나(override 없음, 판정 H)
    def _save_confirm_text(self, current: Job, changed: "list[dict]") -> str:
        """확인 문안을 **잠금 안에서 지금** 성형한다 — 이 문자열이 곧 확인의 정체다.

        무엇이 문안에 들어가야 하는지의 기준은 하나다: **그 값이 달라지면 사용자가 다시
        확인해야 하는가.** 그래서 dirty 필드 전부(§11 "영구 저장 확인에는 모든 dirty 필드를
        나열한다")와, 외부 변경이 있으면 그 **버전**까지 못박는다. 이름만 든 문안은 버전
        불가지라 모달이 열린 사이 또 다른 외부 버전으로 바뀌어도 대조를 통과한다(#273).
        """
        names = ", ".join(c["name"] for c in changed)
        base = (
            f"다음 항목의 연결·표시가 이 작업의 기본 규칙이 됩니다: {names}\n"
            "이미 복사한 항목은 다시 확인이 필요해집니다."
        )
        if self.base_job is None:
            return base
        if content_fingerprint(current) == content_fingerprint(self.base_job):
            return base
        digest = hashlib.sha256(
            content_fingerprint(current).encode("utf-8")
        ).hexdigest()[:8]
        return (
            f"열어 둔 사이 작업 '{current.name}' 이(가) 다른 곳에서 바뀌었습니다"
            f" (현재 내용 #{digest}).\n지금 저장하면 그 변경 위에 아래 연결을 덮어씁니다.\n\n"
            + base
        )

    def _do_save_rules(self, p: dict) -> dict:
        """확인한 patch 만 Binding 판본에 저장하고 **같은 작업점**으로 돌아온다(§11).

        확인 왕복을 거치는 이유는 이 저장이 **다음 실행부터의 기본 규칙**을 바꾸기 때문이다 —
        이 세션에만 듣는 조정이 아니다(override 는 짓지 않았다). 그래서 확인 문안이 dirty
        필드를 **전부** 나열한다: 무엇이 영구히 달라지는지 세지 않고 누르게 하지 않는다.

        **읽기-수정-쓰기 전 구간이 잠금 안이다**(에디터·「기안」 저장과 같은 규율). 작업대
        세션은 오래 열려 있어 진입 시점에 읽은 Job 이 특히 낡기 쉽다 — 잠금 밖에서 저장하면
        그사이 다른 표면이 바꾼 그룹·태그·완주 스탬프를 되돌린다(lost update). 그래서 잠금
        안에서 **지금 디스크를 다시 읽고** 그 위에 매핑만 얹는다.

        **확인은 `confirmed_text` 왕복이다**(1R P1·P2 근본 조치 — 「기안으로 저장」·에디터
        덮어쓰기 게이트와 **같은 관용구**). 문안을 **잠금 안에서 지금** 성형해 사용자가 확인한
        문안과 대조하고, 다르면 새 문안으로 다시 묻는다. 불리언 2개(`confirm`+`confirm_drift`)로
        짰던 첫 판은 두 가지를 동시에 틀렸다: ①새 어휘라 dispatch 스키마 등록을 빠뜨려 실
        브리지에서 저장이 **한 번도 성사되지 않았고** ②불리언은 「사용자가 **이** 상황을
        확인했다」와 「**어떤** 상황을 확인했다」를 구별하지 못해 클라이언트가 드리프트를
        미리 승인해 버렸다. 문안 대조는 그 구별을 **구조로** 만든다 — 상황이 바뀌면 문안이
        바뀌고, 바뀐 문안은 대조에서 걸린다(리뷰 5c 6R P1 / 273 이 세운 규율의 승계).
        """
        self._require_open()
        block = self._save_block()
        if block:
            return {"ok": False, "error": block}
        changed = self._changed_fields()
        if not changed:
            return {"ok": False, "error": "저장할 변경이 없습니다."}
        assert self.base_job is not None and self.mapping is not None
        with self.registry.write_lock():
            try:
                current = self.registry.load(self.base_job.name)
            except (FileNotFoundError, ValueError):
                return {"ok": False, "error": (
                    f"작업 '{self.base_job.name}' 을(를) 더는 읽을 수 없습니다"
                    " — 다른 곳에서 지웠거나 파일이 손상됐습니다.")}
            gate_text = self._save_confirm_text(current, changed)
            if not p.get("confirm") or p.get("confirmed_text", "") != gate_text:
                return {"ok": False, "needs_confirm": True, "confirm_text": gate_text}
            # 지금 읽은 것 위에 **매핑만** 얹는다 — 그룹·태그·완주 스탬프 같은 이 화면이
            # 편집하지 않는 필드는 디스크의 최신값을 그대로 승계한다.
            draft = replace(current, mapping=self._profile_over(current))
            self.registry.save(draft, allow_overwrite=True)
            saved = self.registry.load(draft.name)  # 판본은 저장이 정산(advance_revisions)
        self.base_job = saved
        self.session = EditSession(
            context=EditContext(work=saved.name), base=saved, section=SECTION_BINDING,
        )
        # 「이미 복사한 레코드는 다시 확인 필요」(§11 마지막 줄)를 여기서 **세우지 않는다** —
        # 그 판정은 복사 시점 지문과의 차이에서 파생된다(2R P2). 저장은 규칙을 바꾸지 않고
        # (바뀐 건 이미 편집 때다) 영속시킬 뿐이라, 여기서 집합을 다시 칠하면 같은 상태에
        # 판정 주체가 둘이 된다. 큐 진행(복사 이력)도 그대로 둔다: 무엇을 이미 붙여넣었는지는
        # 여전히 사실이고, 갈린 것은 「확인했는가」다.
        recheck = sum(
            1 for i in self._copied_rules if self._review_state(i) == REVIEW_RECHECK
        )
        self._set_notice(
            f"기본 규칙을 저장했습니다 · 연결 r{saved.binding_revision}"
            + (f" · 복사한 {recheck}건은 다시 확인이 필요합니다" if recheck else ""),
        )
        return {"ok": True, "binding_revision": saved.binding_revision}

    # ---- 이탈 가드(T3 승계) — 복사 진행·미저장 변경을 열거한다
    def leave_guard(self) -> dict:
        """이탈 시 잃는 것의 **열거**. 문안은 웹이 짓되 집합은 여기가 낸다.

        가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고 = 거짓말). 그래서 복사
        진행과 미저장 변경을 **따로** 센다 — 둘은 다른 사실이고 처방도 다르다.
        """
        if not self.is_open:
            return {"armed": False, "lines": []}
        lines: "list[str]" = []
        copied, total = self.queue.copied_count(), len(self.records)
        if 0 < copied < total:
            lines.append(f"복사 진행 {copied}/{total}건 — 나가면 이 진행은 사라집니다.")
        # **다시 확인 대기도 미완이다**(5R P2). 전건을 복사한 뒤 규칙을 고쳐 저장하면 복사
        # 진행(=total)도 미저장 변경도 없지만, 그 문서들은 **지금 규칙의 산출물이 아니다** —
        # 다시 복사해야 한다는 사실이 세션과 함께 사라지면 사용자는 낡은 문서를 붙여넣은 채
        # 끝난다. 가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고도, 과소경고도 아니게).
        recheck = sum(
            1 for i in self._copied_rules if self._review_state(i) == REVIEW_RECHECK
        )
        if recheck:
            lines.append(
                f"규칙이 바뀌어 다시 확인해야 하는 항목 {recheck}건 — 나가면 그 표시가 사라집니다."
            )
        changed = self._changed_fields()
        if changed:
            names = ", ".join(c["name"] for c in changed)
            lines.append(f"저장하지 않은 필드 연결 변경 {len(changed)}건: {names}")
        if self._pending_binding():
            lines.append("확정하지 않은 편집이 있습니다.")
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
                "검토·복사 작업대의 미저장 연결 변경 또는 복사 진행"
                if self.leave_guard()["armed"] else ""
            )

    def _do_leave_guard(self, p: dict) -> dict:
        return self.leave_guard()

    _do_leave_guard.is_query = True  # type: ignore[attr-defined]

    def _do_close(self, p: dict) -> dict:
        """세션 파기 — 웹이 가드 처분을 마친 뒤 부른다."""
        self._clear()
        return {"ok": True}

    # ------------------------------------------------ 클립보드 브리지 계약
    # app.copy_clipboard(screen) 이 render → can_copy → note_copied 순으로 부른다.
    # 「기안」과 **같은 3메서드 계약**이라 브리지가 화면을 몰라도 된다.
    def render(self) -> "tuple[str, object]":
        """작업점 카드의 (클립보드 텍스트, 리포트) — 카드와 **같은 통로**(링1 공유)."""
        assert self.mapping is not None
        rendered = render_card(
            self.template_text, self.mapping, self._current_record(),
            fullwidth=self._fullwidth,
        )
        return card_text(rendered.segments), rendered.report

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
        배제한다. 복사만 잠그면 「다음」·매핑 편집·이탈은 그대로 임계구역 **안으로** 들어와,
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
                text, report = self.render()
                return {"copied": False, "missing_fields": list(report.missing_fields),
                        "empty_fields": list(report.empty_fields)}
            text, report = self.render()
            write(text)                       # OS 쓰기도 임계구역 안 — 성사 뒤에만 전진한다
            self.note_copied(report)
            return {"copied": True, "missing_fields": list(report.missing_fields),
                    "empty_fields": gate_empty_fields(report, self.mapping)}

    def note_copied(self, report) -> None:
        """복사 성사 뒤 상태 전진 — 클립보드 쓰기가 **성공한 뒤에만** 불린다.

        작업점은 복사해도 그 카드에 머문다(조용한 이동 금지) — 전진은 사용자가 켰을 때만.

        **세션 잠금 안에서 불린다**(:meth:`copy_to` 가 유일한 실호출자). 여기서 다시 읽는
        작업점·지문은 방금 렌더한 카드의 것이어야 하므로, 잠금 밖에서 부르면 그 사이의
        이동이 **다른 카드**를 복사 완료로 찍는다. 잠금은 재진입 가능(`RLock`)이라 이
        메서드를 잠금 안에서 부르는 것이 안전하다.
        """
        assert self.mapping is not None
        cur = self.queue.current
        if cur is None:
            return
        stamp_error = self._stamp_first_copy()
        self._last_copy = {
            "row": self.source_rows[cur],
            "missing_fields": list(report.missing_fields),
            "empty_fields": gate_empty_fields(report, self.mapping),
            # 스탬프 실패는 삼키지 않는다 — 복사는 이미 일어났으므로 예외로 완료 노트를
            # 날리는 건 더 큰 손실이고, 조용히 넘기면 이력이 아무 말 없이 이 사건을 잃는다.
            "stamp_error": stamp_error,
        }
        self._copied_total += 1
        # 지금 규칙으로 복사했다 — 그 지문을 못박는다. 다시 복사하면 덮어써 재확인이 해소되고,
        # 규칙이 갈리면 같은 값에서 파생이 「다시 확인 필요」로 넘어간다(별도 무효화 코드 없음).
        self._copied_rules[cur] = self._rules_signature()
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
        행동의 시간 순위」이기 때문이고(§19.2), 그 사실을 표면 문안이
        :func:`~hwpxfiller.gui.work_mode.last_use_label` 로 정직하게 갈라 말한다.

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
            job = self.registry.stamp_last_run(
                self.job_name, datetime.now().isoformat(timespec="seconds"),
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
