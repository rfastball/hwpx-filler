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

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..core.format_engine import presets as format_presets
from ..core.job import Job, JobRegistry, content_fingerprint, work_mode
from ..core.mapping import TYPES
from ..core.text_render import template_fields
from ..gui.edit_session import SECTION_BINDING, EditContext, EditSession
from ..gui.filter_state import sniff_column_kinds
from ..gui.mapping_state import MappingModel
from ..gui.selection_state import SelectionModel
from ..gui.txt_card import card_text, gate_empty_fields, render_card
from ..gui.txt_queue import TxtQueueModel
from ..gui.work_mode import WORK_MODE_TEXT, work_mode_label
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


class WorkbenchController:
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
        self._review: "set[int]" = set()
        self.notice_text = ""
        self.notice_level = "muted"

    def open(self, job: Job, rows: "list[tuple[int, dict]]") -> None:
        """세션 개시 — 고정 사본을 뜬다. ``rows`` = (원본 행 index, 레코드) 표시순.

        **실패 원자성**: 실패할 수 있는 템플릿 읽기를 **먼저** 끝낸 뒤에 상태를 교체한다.
        템플릿이 사라졌으면 :class:`OSError` 가 올라가고 이전 상태(보통 「세션 없음」)는
        그대로다 — 반쪽 세션으로 화면이 서지 않는다(「기안」 `_restore_from_job` 과 같은 규율).
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
        # 커밋(이 아래로는 실패 없음).
        self._clear()
        self.job_name = job.name
        self.base_job = job
        self.template_text = text
        self.records = records
        self.source_rows = [i + 1 for i, _ in rows]     # 1-based 원본 행 번호(정체 병기용)
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
    def _current_record(self) -> dict:
        cur = self.queue.current
        if cur is None or not (0 <= cur < len(self.records)):
            return {}
        return self.records[cur]

    def _draft_job(self) -> "Job | None":
        """지금 화면이 그리는 규칙의 Job 형상 — 판본 대조·저장 대상의 단일 성형.

        매핑만 갈아 끼운다: 작업대는 템플릿도 파일 이름도 건드리지 않으므로(§3.2 — TXT 엔
        파일 이름 규칙 자체가 없다) 그 축을 성형에 넣으면 없는 변경을 만들어 낸다.
        """
        if self.base_job is None or self.mapping is None:
            return None
        return replace(self.base_job, mapping=self.mapping.to_profile(self.base_job.name))

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

    def _review_state(self, index: "int | None") -> str:
        if index is None:
            return REVIEW_TODO
        if index in self._review:
            return REVIEW_RECHECK
        return REVIEW_COPIED if self.queue.is_copied(index) else REVIEW_TODO

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
            "source_row": self.source_rows[cur] if cur is not None else None,
            "review_state": self._review_state(cur),
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

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 workbench 액션: {action!r}")
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

    # ---- 필드 연결(좌 pane) — 「기안」 맞추기 표와 같은 동사·같은 판정
    def _row_index(self, p: dict) -> int:
        self._require_open()
        return int(p["index"])

    def _do_set_source(self, p: dict) -> None:
        assert self.mapping is not None
        i, source = self._row_index(p), p.get("source", "")
        if source:
            kind = sniff_column_kinds(self.records).get(source, "")
            self.mapping.bind_column(i, source, kind=kind)
        else:
            self.mapping.unbind(i)

    def _do_set_map_value(self, p: dict) -> None:
        assert self.mapping is not None
        self.mapping.set_manual(self._row_index(p), p.get("value", ""))

    def _do_set_map_fmt(self, p: dict) -> None:
        assert self.mapping is not None
        self.mapping.set_fmt_for(self._row_index(p), p.get("code", ""))

    def _do_set_map_type(self, p: dict) -> None:
        assert self.mapping is not None
        self.mapping.set_type(self._row_index(p), p.get("code", ""))

    def _do_set_confirmed(self, p: dict) -> None:
        assert self.mapping is not None
        self.mapping.set_confirmed(self._row_index(p), bool(p["value"]))

    def _do_revert_map(self, p: dict) -> None:
        assert self.mapping is not None
        self.mapping.revert_binding(self._row_index(p))

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
            "row": self.source_rows[cur] if cur is not None else None,
            "missing_fields": list(rendered.report.missing_fields),
            "empty_fields": gate_empty_fields(rendered.report, self.mapping),
        }

    _do_copy_precheck.is_query = True  # type: ignore[attr-defined]

    # ---- 기본 규칙으로 저장(§11) — 착지점은 이것 하나(override 없음, 판정 H)
    def _do_save_rules(self, p: dict) -> dict:
        """확인한 patch 만 Binding 판본에 저장하고 **같은 작업점**으로 돌아온다(§11).

        확인 왕복을 거치는 이유는 이 저장이 **다음 실행부터의 기본 규칙**을 바꾸기 때문이다 —
        이 세션에만 듣는 조정이 아니다(override 는 짓지 않았다). 그래서 확인 문안이 dirty
        필드를 **전부** 나열한다: 무엇이 영구히 달라지는지 세지 않고 누르게 하지 않는다.

        **읽기-수정-쓰기 전 구간이 잠금 안이다**(에디터·「기안」 저장과 같은 규율). 작업대
        세션은 오래 열려 있어 진입 시점에 읽은 Job 이 특히 낡기 쉽다 — 잠금 밖에서 저장하면
        그사이 다른 표면이 바꾼 그룹·태그·완주 스탬프를 되돌린다(lost update). 그래서 잠금
        안에서 **지금 디스크를 다시 읽고** 그 위에 매핑만 얹는다. 매핑 자체가 외부에서
        갈렸으면(내용 지문 불일치) 조용히 덮지 않고 확인을 다시 받는다.
        """
        self._require_open()
        block = self._save_block()
        if block:
            return {"ok": False, "error": block}
        changed = self._changed_fields()
        if not changed:
            return {"ok": False, "error": "저장할 변경이 없습니다."}
        if not p.get("confirm"):
            return {"ok": True, "needs_confirm": True,
                    "fields": [c["name"] for c in changed]}
        assert self.base_job is not None and self.mapping is not None
        with self.registry.write_lock():
            try:
                current = self.registry.load(self.base_job.name)
            except (FileNotFoundError, ValueError):
                return {"ok": False, "error": (
                    f"작업 '{self.base_job.name}' 을(를) 더는 읽을 수 없습니다"
                    " — 다른 곳에서 지웠거나 파일이 손상됐습니다.")}
            drifted = content_fingerprint(current) != content_fingerprint(self.base_job)
            if drifted and not p.get("confirm_drift"):
                return {"ok": True, "needs_confirm": True, "drift": True,
                        "fields": [c["name"] for c in changed]}
            # 지금 읽은 것 위에 **매핑만** 얹는다 — 그룹·태그·완주 스탬프 같은 이 화면이
            # 편집하지 않는 필드는 디스크의 최신값을 그대로 승계한다.
            draft = replace(current, mapping=self.mapping.to_profile(current.name))
            self.registry.save(draft, allow_overwrite=True)
            saved = self.registry.load(draft.name)  # 판본은 저장이 정산(advance_revisions)
        self.base_job = saved
        self.session = EditSession(
            context=EditContext(work=saved.name), base=saved, section=SECTION_BINDING,
        )
        # 이미 복사한 레코드는 **다시 확인 필요**가 된다(§11 마지막 줄) — 규칙이 갈렸으므로
        # 그 문서들은 지금 규칙의 산출물이 아니다. 큐 진행(복사 이력)은 지우지 않는다:
        # 무엇을 이미 붙여넣었는지는 여전히 사실이고, 갈린 것은 「확인했는가」다.
        self._review = {i for i in range(len(self.records)) if self.queue.is_copied(i)}
        self._set_notice(
            f"기본 규칙을 저장했습니다 · 연결 r{saved.binding_revision}"
            + (f" · 복사한 {len(self._review)}건은 다시 확인이 필요합니다"
               if self._review else ""),
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
        changed = self._changed_fields()
        if changed:
            names = ", ".join(c["name"] for c in changed)
            lines.append(f"저장하지 않은 필드 연결 변경 {len(changed)}건: {names}")
        if self._pending_binding():
            lines.append("확정하지 않은 편집이 있습니다.")
        return {"armed": bool(lines), "lines": lines}

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
        """복사 가능 = 세션이 있고 작업점이 실재한다.

        「기안」의 가상 카드(무데이터 직접 입력)는 여기 없다 — 작업대는 언제나 고정 사본
        위에 서므로 레코드 없는 복사가 성립하지 않는다(그 경로는 휘발 세션의 것이고 PR-B
        에서 함께 죽는다).
        """
        return self.is_open and self.queue.current is not None

    def note_copied(self, report) -> None:
        """복사 성사 뒤 상태 전진 — 클립보드 쓰기가 **성공한 뒤에만** 불린다.

        작업점은 복사해도 그 카드에 머문다(조용한 이동 금지) — 전진은 사용자가 켰을 때만.
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
        self._review.discard(cur)   # 지금 규칙으로 다시 복사했다 = 재확인 해소
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
