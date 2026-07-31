"""데이터 존 공용 믹스인 — 필터 선언·행 선택 표면의 컨트롤러 몫(블록 3·4, 슬라이스 6 PR-2b).

웹 쪽 ``frontend/js/datazone.js`` 팩토리(PR-2a)의 Python 짝이다: 「작업」 화면(블록 4)이 착지한
필터·선택 디스패치와 스냅샷 합성을 txt 일괄 큐(블록 3)가 재사용한다 — 컨트롤러마다 복붙하면
JS 에서 막은 #94(링2 400줄 중복)와 동형의 드리프트가 Python 에서 재발한다. 판정은 전부 링1
(:class:`~hwpxfiller.gui.filter_state.FilterModel`·:class:`~hwpxfiller.gui.selection_state.
SelectionModel`)이 소유하고, 여기는 디스패치 위임과 스냅샷 성형만 든다(#87 경계 유지).

## 소비 컨트롤러가 대는 표면

- ``self.selection``(:class:`SelectionModel`) · ``self.filter``(:class:`FilterModel` | None —
  데이터 미겨눔이면 None) · ``self._last_filter``/``self._data_key``(결정 28 직전 필터 슬롯·
  소스 일치 키 — 데이터 겨눔 경로가 :meth:`_stash_filter` 후 :meth:`_file_key`/:meth:`_pool_key`
  로 갱신) · ``self.pool_registry``/``self.data_pool_key``(풀 키 정체 해소 — §5.3 재편으로
  라벨이 아니라 슬롯 키가 정체다).
- :meth:`_records` — 현 데이터소스의 원본 레코드(미겨눔이면 빈 리스트).

## 스냅샷 계약(웹 datazone.js 와 쌍)

:meth:`_zone_sections` 이 ``filter``/``table`` 스냅샷을 합성한다 — 선두 열 소재(작업=파일명·
식별 요약, txt=큐 표지)는 컨트롤러가 ``rows_by_index`` 로 주입하고, 셀은 하이라이트 세그먼트
(Python 이 잘라 조각으로 — 매치 인덱스를 웹에 건네지 않는다, jamo 계약)로 실린다. 평가는
FilterView 1회(캐시 계약) — 반환된 view 를 컨트롤러가 재진술·가드 판정에 재사용해 이중
평가를 피한다(작업 화면 리뷰 #7).
"""
from __future__ import annotations

import json

from pathlib import Path
from typing import Callable

from ..core.dataset_pool import DatasetPoolRegistry
from ..gui.filter_state import (
    FilterModel,
    FilterView,
    RangeClause,
    RangeCondition,
    cell_text,
    sniff_column_kinds,
)
from ..gui.selection_state import SelectionModel

# 데이터 미겨눔 상태의 필터/테이블 빈 골격 — 표면이 분기 없이 그린다.
EMPTY_FILTER = {
    "active": False, "reapply_available": False, "reapply_hint": "", "search": "",
    "chips": [], "definition": "", "branches": [], "columns": [],
}
EMPTY_TABLE = {
    "columns": [], "rows": [], "visible_count": 0, "hidden_selected": [],
    "hidden_columns": [],
}


class DataZoneMixin:
    """필터·선택 디스패치(``_do_*``)와 존 스냅샷 합성 — 컨트롤러 공유 표면(모듈 독스트링 참조)."""

    #: 현 세션 필터 정의줄의 **살아있는 데이터 기준** 문안(:meth:`_zone_sections` 가 갱신).
    #: 슬롯 스태시가 이걸 복사해 간다 — 스태시 시점엔 레코드가 이미 교체됐을 수 있어서
    #: 그때 새로 지으면 남의 데이터로 죽은 세션을 묘사하게 된다(리뷰 F1). 미겨눔·무정의는 "".
    _filter_desc: str = ""

    #: 사용자 열 선별(U2 §2.19, #341) — **표시 축뿐**이다: 숨긴 열도 필터·검색·매핑·생성에
    #: 그대로 참여한다(숨김 ≠ 제외). 수명은 세션 소유(필터와 같은 계층)라 소비 컨트롤러가
    #: 데이터 교체 seam 에서 비운다 — durable 저장은 어디에도 없다.
    hidden_columns: "frozenset[str] | set[str]" = frozenset()  # 클래스 기본만 불변(인스턴스는 set)

    selection: SelectionModel
    filter: "FilterModel | None"
    _last_filter: "dict | None"   # {"source_key": str, "state": dict} — 결정 28 슬롯
    _data_key: str                # 현 데이터 소스 정체(file:경로 | pool:참조) — 소스 일치 판정
    pool_registry: DatasetPoolRegistry
    data_label: str
    data_source: str              # ''(미겨눔) | 'file' | 'pool'
    data_pool_key: str            # 겨눈 풀 슬롯 키(§5.3 — 라벨은 개명 자유라 정체가 못 된다)
    #: 현 마운트 대상의 참조 정체(겨눔 시점 캐시) — 데이터 선택 다이얼로그 「현재 데이터」와
    #: 「이 데이터 고정」 프리필의 소재(재작성 F1). 라벨(파일명)만으론 고정할 참조를 지을 수
    #: 없어서 경로·확정 시트를 함께 남긴다(에디터 ``data_path``/``data_sheet`` 선례).
    data_path: str = ""
    data_sheet: str = ""
    #: 헤더 행(엑셀 참조 옵션) — 0 = 미지정(어댑터 기본 1행). ``data_path``/``data_sheet`` 와
    #: **같은 시점에 같은 이유로** 포획한다(#349 리뷰 2R): 참조는 슬롯에 살고 슬롯은 변한다
    #: (「다시 연결」은 정상 수명 사건, #347). 마운트가 성사된 그 순간의 참조가 곧 지금 화면에
    #: 보이는 레코드를 만든 참조이므로, 승계는 슬롯을 다시 읽지 않고 이 포획분만 읽는다.
    data_header_row: int = 0

    def _records(self) -> list:
        raise NotImplementedError  # 컨트롤러가 현 데이터소스 레코드를 댄다

    # ------------------------------------- 존이 편집·렌더하는 대상(재작성 F3 판정 A·D)
    # 13액션과 존 렌더는 **여기를 통해서만** 선택·필터에 닿는다. 기본은 커밋된 세션 상태이고,
    # 범위 초안이 열린 화면은 이 셋을 덮어 초안을 가리킨다 — 액션을 두 벌로 늘리지 않고
    # (같은 동사가 대상만 바꾼다) **경계가 코드에 한 번만** 적힌다. 반대로 실행 입력·게이트·
    # 거울·세션 가드는 이 훅을 쓰지 않는다(불변식 §18.11-21: 적용 전 메인 범위 불변).
    def _zone_sel(self) -> SelectionModel:
        return self.selection

    def _zone_flt(self) -> "FilterModel | None":
        return self.filter

    def _zone_set_flt(self, model: FilterModel) -> None:
        """필터 **원자 교체**의 착지처(직전 필터 재적용) — 소유자를 한 곳에서 답한다."""
        self.filter = model

    def _zone_visible(self, view: FilterView) -> "list[int]":
        """존 표에 실제로 그릴 행(필터 판정 전) — 기본은 필터 가시 집합 그대로.

        「선택된 항목만 보기」처럼 **가시성만** 갈아끼우는 보기 상태가 여기로 들어온다.
        필터 정의 자체는 살아 있고(칩 줄이 계속 말한다) 판정(재진술·가드)은 필터의 가시
        집합을 쓴다 — 보기와 판정을 같은 값으로 뭉개면 "선택만 보는 중"이 곧 "정의-유래
        선택"으로 오독된다.
        """
        return view.visible_indices()

    def _data_target(self) -> dict:
        """마운트 대상 재진술 ``{path, sheet, origin}`` — 스냅샷 동봉(신설 상태 아님, 파생).

        「이 데이터 고정」은 ``origin == 'file'`` 에서만 뜬다: 등록 데이터 출처는 **이미
        고정된 참조**라 다시 고정하면 같은 파일의 참조가 둘로 갈린다(v6 ``pinCurrentData``
        hidden 동형). 값은 겨눔 시점 캐시라 로드된 레코드와 같은 신선도 의미다.
        """
        return {
            "path": self.data_path,
            "sheet": self.data_sheet,
            "origin": self.data_source,
        }

    def new_work_handoff(self) -> "tuple[dict, str]":
        """「이 데이터로 새 작업」이 들고 갈 **데이터 참조**와 거절 사유 — 단일 판정.

        반환은 ``({"path", "sheet", "header_row"}, "")`` 또는 ``({}, 사유)`` 다. 버튼의
        가부(스냅샷)와 진입의 fail-closed(브리지)가 **같은 한 판정**을 읽는다 — 표면이
        `data_path` 유무로 스스로 유추하면 화면은 「누를 수 있다」고 말하고 백엔드는 거절하는
        어긋남이 난다(#349 리뷰 1R 이 지목한 자리).

        **슬롯을 다시 읽지 않는다**(#349 리뷰 2R). 등록 데이터의 참조는 가변이다 — 「다시
        연결」은 참조만 갈아 끼우고 수명을 보존하는 **정상 수명 사건**이고(#347), 그것이
        일어나도 이 화면은 재마운트 전까지 **옛 참조로 읽은 레코드**를 그대로 보여 준다.
        그때 승계가 슬롯을 다시 해석하면 「표시는 A · 시작은 B」가 된다. 그래서 참조는
        마운트가 성사되는 자리에서 통째로 포획해 두고(``data_path``·``data_sheet``·
        ``data_header_row`` — 세 값이 같은 시점의 한 벌이다) 여기서는 그 포획분만 읽는다.
        같은 계열의 규율이 마운트 descriptor 반환(U2 §2.7)과 소스 일치 키(``_data_key``)다:
        **나중에 다시 읽어 판정하지 않는다.**

        참조를 경로 하나로 줄이지도 않는다: 엑셀 참조가 든 ``header_row`` 를 떨어뜨리면
        마법사가 사용자가 고른 것과 **다른 헤더**에 앵커를 건다.

        파일로 다시 열 수 없는 마운트(조립 파이프라인 등)는 **시끄럽게 막는다**: 마법사의
        데이터 관문은 파일 참조를 여는 표면이고, 여기서 조용히 빈 초안으로 보내면
        「이 데이터로」라는 문안 자체가 거짓이 된다. 술어는 포획된 ``data_path`` 하나다 —
        그 필드의 뜻이 이미 「이 마운트를 파일로 가리킬 수 있는가」이기 때문이다
        (:meth:`~hwpxfiller.webapp.screens.PoolTargetingMixin._do_load_pool` 이 엑셀 참조에만
        채운다).
        """
        if not self.data_source:
            return {}, "데이터를 먼저 고르세요."
        if not self.data_path:
            return {}, (
                f"'{self.data_label}' 은 파일 참조가 아니어서 새 작업의 데이터로 열 수 "
                "없습니다. 엑셀·CSV 데이터를 고른 뒤 시작하세요."
            )
        return {
            "path": self.data_path,
            "sheet": self.data_sheet,
            "header_row": self.data_header_row,
        }, ""

    def _display_indices(self, indices: "list[int]") -> "list[int]":
        """표시 순서 투영 훅 — 기본 항등(원본 오름차순). 데이터-우선 「작업」 화면이
        sourceDesc(§18.10)로 재정의한다. 표·실행 입력이 같은 훅을 소비해 보이는 순서와
        생성 순서가 갈라지지 않는다(WYSIWYG)."""
        return indices

    # -------------------------------------------- 사용자 열 선별(U2 §2.19, #341)
    def _zone_hidden(self) -> "set[str]":
        """이번 렌더에 **적용되는** 숨김 집합 훅 — 기본은 세션 숨김 그대로.

        「작업」 화면이 재정의한다: ⤢ 시트(범위 초안)는 전 열·원본 순서(#271 "시트 = 전체
        진실" 유지)라 초안이 열려 있으면 빈 집합을 답한다 — 선별은 인라인 표 한정이다.
        판정이 Python 한 곳이라 인라인·시트·칩이 각자 답을 갖지 않는다.
        """
        return set(self.hidden_columns)

    def _hide_allowed(self) -> bool:
        """지금 열을 숨길 수 있는 표면인가 — 「작업」 화면이 시트(초안) 열림에서 닫는다."""
        return True

    def _do_hide_column(self, p: dict) -> None:
        """「이 열 숨기기」(열 패널) — **보기에서만** 숨긴다. 필터·검색·매핑·생성 불변.

        선두 식별 열(파일명·식별 요약)은 데이터 열이 아니라 이 집합에 아예 들어올 수 없고
        (열 이름 검증이 데이터 열 지형으로 닫는다), 시트에서는 항목이 서지 않지만 상태가
        DOM 이 아니라 여기를 지키므로 오배선 호출도 시끄럽게 거절한다.
        """
        fm = self._filter_or_raise()
        col = p["column"]
        if col not in fm.columns:  # 선두 식별 열·죽은 열 이름 — 조용한 무시 금지
            raise ValueError(f"숨길 수 없는 열입니다: {col!r}")
        if not self._hide_allowed():
            raise ValueError("펼친 화면은 전체 열을 보여줍니다 — 열 숨기기는 인라인 표에서 하세요.")
        self.hidden_columns = set(self.hidden_columns) | {col}

    def _do_unhide_columns(self, p: dict) -> None:
        """「열 N개 숨김 ×」(칩 줄) — 숨김 전체 해제. 개별 해제 어포던스는 짓지 않는다
        (#341: 되돌리기는 필터 칩 줄 관용구 하나)."""
        self.hidden_columns = set()

    # ------------------------------------------------------------- 행 선택 액션
    def _do_toggle_record(self, p: dict) -> None:
        self._zone_sel().toggle(int(p["index"]), bool(p["value"]))

    def _do_select_range(self, p: dict) -> None:
        """Shift 범위 — 앵커 행의 상태를 범위에 전파(결정 2). 표면이 가시 순서 범위를 준다."""
        value = bool(p["value"])
        sel = self._zone_sel()
        for i in p["indices"]:
            sel.toggle(int(i), value)

    def _do_set_all(self, p: dict) -> dict:
        """「전체 선택」 — 필터 활성 시 **매치 전체를 가산**한다(결정 4·26 "전체 선택 가산적").

        필터 밖 기존 선택은 유지된다(선택은 필터를 관통, 결정 3) — '매치'의 담보는 버튼
        이름이 아니라 게이트 정의줄 재진술이 진다. 반환 ``added`` = 새로 선택된 행 수 —
        전멸 필터에서의 무동작(0)을 표면이 정직하게 알린다(confirm-or-alarm, 리뷰 #9:
        아무 반응 없는 버튼은 결함으로 읽힌다).
        """
        sel, fm = self._zone_sel(), self._zone_flt()
        before = sel.selected_count()
        if fm is not None and fm.is_active():
            for i in fm.visible_indices(self._records()):
                sel.toggle(i, True)
        else:
            sel.set_all()
        return {"added": sel.selected_count() - before}

    def _do_set_none(self, p: dict) -> None:
        """「전체 해제」 — 명시 동사라 가드 불요(T4), 필터와 무관하게 전부 해제."""
        self._zone_sel().set_none()

    # ------------------------------------------------- 필터 액션(블록 4, 결정 23~25)
    def _filter_or_raise(self) -> FilterModel:
        fm = self._zone_flt()
        if fm is None:  # 표면 오배선 검출 — 데이터 없이 필터 액션은 프로그램 결함
            raise ValueError("데이터를 먼저 선택하세요.")
        return fm

    def _do_filter_search(self, p: dict) -> None:
        """전열 검색 = 재현 OR 그룹 재정의(교체) — 검색창이 그룹 편집기다."""
        self._filter_or_raise().set_search(p.get("text", ""))

    def _do_filter_col_text(self, p: dict) -> None:
        self._filter_or_raise().set_text(p["column"], p.get("text", ""))

    def _do_filter_col_values(self, p: dict) -> None:
        """값 체크리스트 — ``values=None`` 은 (전체)=무조건. 순서=패널 표시 순서."""
        values = p.get("values")
        self._filter_or_raise().set_values(
            p["column"], None if values is None else [str(v) for v in values]
        )

    def _do_filter_col_range(self, p: dict) -> dict:
        """범위 조건 — 피연산자 검증 실패는 시끄럽되 uncaught 아님(패널 인라인 재진술).

        빈 첫 절 = 조건 해제. 반환 dict 의 ``error`` 를 표면이 패널 안에서 재진술한다
        (confirm-or-alarm: 조용한 강등 대신 보이는 거절).
        """
        fm = self._filter_or_raise()
        first = p.get("first")
        try:
            if not first or not str(first.get("operand", "")).strip():
                fm.set_range(p["column"], None)
                return {"ok": True}
            second = p.get("second")
            cond = RangeCondition(
                first=RangeClause(first["op"], str(first["operand"]).strip()),
                second=(
                    RangeClause(second["op"], str(second["operand"]).strip())
                    if second and str(second.get("operand", "")).strip() else None
                ),
                joiner=p.get("joiner", "and"),
            )
            fm.set_range(p["column"], cond)
            return {"ok": True}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def _do_filter_prune(self, p: dict) -> None:
        """가지 쳐내기 — 마지막 가지면 그룹 해산(시안 동형, filter_state 소관)."""
        self._filter_or_raise().prune_branch(p["column"], self._records())

    def _do_filter_clear(self, p: dict) -> None:
        self._filter_or_raise().clear()

    def _do_filter_clear_col(self, p: dict) -> None:
        self._filter_or_raise().clear_column(p["column"])

    def _do_filter_panel(self, p: dict) -> dict:
        """열 패널 열기 질의 — 현 조건 + 값 목록(다른 조건 통과 행 기준, 엑셀 동형).

        스냅샷에 전 열 값 목록을 상시 싣지 않는다(53열 코퍼스 낭비) — 패널이 열릴 때만
        당긴다. 반환 값 목록의 ``""`` 은 (빈값) 일급 값이다.
        """
        fm = self._filter_or_raise()
        col = p["column"]
        state = fm.column_state(col)
        return {
            "column": col,
            "kind": fm.kind(col),
            "text": state["text"],
            "checked": state["values"],    # None=(전체)
            "options": fm.view(self._records()).column_values(col),
            "range": state["range"],
            # 「이 열 숨기기」 항목의 유무(#341) — 판정은 Python(시트로 이사한 패널에는
            # 항목이 서지 않는다). 표면은 이 값을 그리기만 한다.
            "can_hide": self._hide_allowed(),
        }

    _do_filter_panel.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # ------------------------------------------- 직전 필터 재적용(건 연속성, 결정 28)
    def _stash_filter(self) -> None:
        """죽는 세션의 활성 필터 정의를 직전 슬롯에 덮어쓴다(결정 28 — 1칸, 직전성).

        **정의 가진 세션이 죽을 때만** 덮어쓴다 — 정의 없는 세션의 죽음은 슬롯을 보존한다
        (직전 "정의"의 연속성이지 직전 "세션"의 연속성이 아니다). 저장이 아니라 전달
        (결정 8 예외) — 컨트롤러 수명(앱 수명)뿐, 디스크에 남지 않는다.
        """
        if self.filter is not None and self.filter.is_active() and self._data_key:
            self._last_filter = {
                "source_key": self._data_key,
                "state": self.filter.export_state(),
                # 정의줄은 **직전 스냅샷이 지어 둔 것**을 쓴다(리뷰 F1). 여기서 새로 지으면
                # 안 된다: 데이터 겨눔 경로는 `vm.load_data()` 로 레코드를 **먼저 갈아치운
                # 뒤** 이 함수를 부르므로(옛 소스 키를 쓰기 위한 순서), 지금 view 를 지으면
                # 죽는 세션의 정의를 **새 데이터**에 대고 묘사하게 된다 — 「매치 없음」이나
                # 남의 데이터 가지 이름이 슬롯에 박혀, 원 소스로 돌아왔을 때 버튼이 거짓을
                # 업고 뜬다. 캐시는 그 스냅샷이 이미 계산한 값이라 추가 비용도 없다.
                "summary": self._filter_desc,
            }

    def _current_filter_empty(self) -> bool:
        """현 존 필터가 백지인가 — 재적용 게이트의 셋째 연언(#127)."""
        fm = self._zone_flt()
        return fm is None or not fm.is_active()

    def _reapply_available(self) -> bool:
        """재적용 제공 판정 — **3연언**: 슬롯 존재 ∧ 현 필터 빈 상태 ∧ 소스 일치.

        소스 일치는 결정 28 이 **추가**한 조항이고(소스별 맵은 필터 영속 뒷문이라 기각 —
        교차 재사용은 재타이핑 몇 초), '현 필터 빈 상태'는 시안 v1.2 확정 지형 ㉣ 의 원
        게이트다. 둘째 연언을 빠뜨리면(#127) 조건을 쌓아 둔 필터 위에도 버튼이 떠서, 한 번
        누르면 현 정의가 **확인 없이 통째로 교체**된다(:meth:`_do_filter_reapply` 는 원자
        교체다). 결정 27 이 필터 정의를 세션 가드 술어에서 뺀 근거가 "재적용이 복원해 준다"
        였으므로, 그 재적용 자신이 파괴자가 되면 근거째 무너진다 — 복원 전용 어포던스로
        묶어 두는 것이 정본이자 이 화면의 유일한 필터 안전망이다.
        """
        return (
            self._last_filter is not None
            and bool(self._data_key)
            and self._last_filter["source_key"] == self._data_key
            and self._current_filter_empty()
        )

    def _do_filter_reapply(self, p: dict) -> dict:
        """직전 필터 재적용(결정 28) — 정의(보기)만 복원, 선택은 불변(2클릭 분리).

        열 결손 백스톱: 초안 모델에 설치해 보고 **전탈락이면 현 정의를 건드리지 않고
        거부**(이유 반환), 아니면 초안을 그대로 현 모델로 **원자 교체**한다(리뷰 #5 —
        clear 후 재적용의 이중 작업·오염 창 제거). 프루닝 포함 복원(결정 27 소실 창의
        복원) — 단 **가지 소실로 살아있는 가지가 전부 프루닝분이 된 경우엔 프루닝 복원을
        포기**한다(리뷰 #2): 그대로 두면 매치가 있는데 전부 쳐낸 "거짓 「매치 없음」 빈
        화면"이 된다 — 마지막 가지 프루닝=해산 불변식의 재적용판(사용자 의사가 아닌 열
        소실 유래이므로 검색을 살리고 프루닝만 내려놓는다, 고지 동반).
        """
        fm = self._filter_or_raise()
        slot = self._last_filter
        # 아래 두 거부는 표면 오배선에서만 닿는다(정상 경로는 버튼 미노출). 사유를 가르는
        # 이유(#127): "슬롯 없음"으로 뭉뚱그리면 현 정의를 지킨 거부가 없는 슬롯처럼 읽힌다.
        if not self._current_filter_empty():
            raise ValueError("필터를 지운 뒤에 재적용할 수 있습니다.")
        if slot is None or not self._reapply_available():
            raise ValueError("재적용할 직전 필터가 없습니다.")
        state = slot["state"]
        kinds = {c: fm.kind(c) for c in fm.columns}
        probe = FilterModel(fm.columns, kinds)
        installed, dropped = probe.apply_state(state)
        if not probe.is_active():
            return {
                "ok": False,
                "error": "직전 필터의 조건이 현재 데이터 열에 하나도 남지 않아 재적용하지 "
                         "못했습니다: " + ", ".join(dropped),
            }
        records = self._records()
        if probe.search_text and not probe.view(records).branches:
            unpruned = FilterModel(fm.columns, kinds)
            unpruned.apply_state(dict(state, pruned=[]))
            if unpruned.view(records).branches:  # 프루닝만 걷으면 가지가 산다 = 소실 유래
                probe = unpruned
                dropped = dropped + ["(검색 일부 조건은 열이 사라져 복원하지 못했습니다)"]
        self._zone_set_flt(probe)  # 원자 교체 — 검증된 초안이 그대로 정의가 된다
        return {"ok": True, "installed": installed, "dropped": dropped}

    # ------------------------------------------------------- 데이터 소스 정체(결정 28)
    @staticmethod
    def _file_key(path: str, sheet: "str | None") -> str:
        """파일 소스 키 — 정규화 경로(resolve+casefold) + 시트 병기(리뷰 #0·#8).

        시트가 다르면 다른 소스다(같은 워크북의 1월/2월 시트에 같은 정의 재적용은 결정
        28이 막는 바로 그 교차 재사용). 경로는 대소문자·표기 변형(Windows)에 같은 실파일이
        어긋나 어포던스가 조용히 안 뜨는 강등을 막기 위해 정규화한다.
        """
        norm = str(Path(path).resolve()).casefold()
        return f"file:{norm}" + (f"::{sheet}" if sheet else "")

    def _pool_key(self) -> str:
        """풀 소스 키 — 슬롯 키 + **참조 정체**(kind+opts) 병기(리뷰 #6 · §5.3 재편).

        라벨은 개명 자유라 키에 들지 않는다(들면 이름만 바꿔도 결정 28 게이트가 조용히
        닫힌다). 참조 정체를 병기하는 이유는 다시 연결이다: 같은 슬롯이 다른 파일을
        가리키게 되면 다른 소스다. 참조 해소 실패 시(경합 삭제 등)는 빈 정체로 강등 —
        게이트가 닫히는 안전 방향.
        """
        # 지연 임포트 — screens.py 가 이 믹스인을 소비하므로 모듈 상단 상호 임포트는 순환.
        from .screens import load_pool_item_checked

        try:
            item = load_pool_item_checked(self.pool_registry, self.data_pool_key)
            ident = f"{item.kind}:{json.dumps(item.opts, sort_keys=True, ensure_ascii=False)}"
        except Exception:  # noqa: BLE001 — 정체 불명 = 게이트 닫힘(안전 강등)
            ident = ""
        return f"pool:{self.data_pool_key}:{ident}"

    # ------------------------------------------------------------- 필터 설치·스냅샷
    def _install_filter(self, records: list, hints: "dict[str, str]") -> None:
        """데이터 겨눔 시 필터 신설(결정 24) — 열 유형은 힌트 우선 + 값 스니핑.

        힌트는 컨트롤러 소관(작업=매핑 확정 유형, txt=없음). 데이터 교체 = 필터 재생성
        (열 지형이 바뀐다) — 정의 인계는 결정 28 재적용이 담당한다.
        """
        columns = list(records[0].keys()) if records else []
        self.filter = FilterModel(columns, sniff_column_kinds(records, hints))

    # ------------------------------------------------- 세션 가드 술어(블록 4, 결정 26·27)
    def _selection_guard(
        self,
        *,
        settled: "set[int] | None" = None,
        vis_set: "set[int] | None" = None,
    ) -> dict:
        """"재현 불가능한 수작업 선택"이 있는가 — 세션 가드 술어의 **선택 성분**(결정 27).

        무장 조건: 선택이 비어 있지 않고 ∧ ``settled``(그 화면의 완료 이벤트가 설명하는
        집합 — 작업=마지막 생성분, txt=완주한 큐)와 다르고 ∧ **정의-유래**(현 필터 매치
        전체)가 아니고 ∧ **전체 선택**(1클릭 재현)도 아니다. 필터 정의 자체는 술어 불포함 —
        재타이핑 몇 초 + 직전 필터 재적용(결정 28)이 복원을 담보한다(프루닝 동일).

        두 소비 화면(작업 T1·txt T3)이 같은 판정을 쓰도록 믹스인이 소유한다 — 컨트롤러마다
        복붙하면 한쪽만 고쳐지는 드리프트가 곧 "조용히 통과하는 파괴 전이"가 된다(#94 동형).
        화면 고유 성분(txt 큐 부분 진행)은 소비처가 이 dict 위에 얹는다.

        ``vis_set`` 은 렌더 경로가 이미 산출한 가시 집합 — 스냅샷에서 필터를 이중 평가하지
        않기 위한 전달이다(FilterView 캐시 계약). 단발 판정은 생략하고 직접 평가한다.

        수치는 modal.js 재진술 본문 소재(결정 27 "종류별 수치 재진술") — 표면이 합성한다.
        """
        records = self._records()
        sel = set(self.selection.selected_indices())
        f_active = self.filter is not None and self.filter.is_active()
        filter_parts = 0
        if self.filter is not None and f_active:
            filter_parts = sum(
                1 for c in self.filter.columns if self.filter.has_condition(c)
            ) + (1 if self.filter.search_text else 0)
        in_def = extra = 0
        armed = False
        if sel and sel != (settled or set()) and len(sel) != len(records):
            if f_active:
                assert self.filter is not None
                vis = (
                    vis_set if vis_set is not None
                    else set(self.filter.visible_indices(records))
                )
                armed = sel != vis  # 정의-유래(매치 전체)는 정의줄이 재현을 담보
                in_def, extra = len(sel & vis), len(sel - vis)
            else:
                armed = True  # 필터 없는 부분 선택 = 순수 수작업 열거
        return {
            "armed": armed,
            "sel_count": len(sel),
            "in_def": in_def,
            "extra": extra,
            "filter_active": f_active,
            "filter_parts": filter_parts,
        }

    def _zone_sections(
        self, indices: "list[int]", lead_for: "Callable[[int], dict]"
    ) -> "tuple[dict, dict, FilterView | None, list[int]]":
        """필터·테이블 스냅샷 합성 — ``(filter, table, view|None, visible)`` 반환.

        평가는 FilterView 1회(캐시 계약) — 컨트롤러가 반환 view/visible 로 재진술·가드를
        추가 합성한다(이중 평가 금지, 작업 화면 리뷰 #7).

        ``lead_for(i)`` = 그 행의 선두 열 소재 dict(화면 주입: 작업=이름·요약, txt=큐 표지).
        **실리는 행에만** 부른다 — 가시 행 + 필터 밖 선택 스트립(결정 3)이 소비하는 행뿐이라,
        전 레코드 dict 를 미리 지어 대부분 버리는 낭비가 없다(PR-2b 리뷰). 두 소비처가
        같은 함수를 통과하므로 소재는 여전히 단일 출처다. 미겨눔(filter None)은 빈 골격.
        """
        fm = self._zone_flt()
        if fm is None:
            self._filter_desc = ""
            return EMPTY_FILTER, EMPTY_TABLE, None, []
        records = self._records()
        view = fm.view(records)  # 가지 1회 산출 — 렌더 경로 캐시 계약(filter_state)
        # 슬롯 스태시가 복사해 갈 정의줄 — **지금 살아있는 데이터 기준**으로 여기서만 짓는다
        # (리뷰 F1: 스태시 시점엔 레코드가 이미 교체됐다). 아래 "definition" 과 같은 값이다.
        # **커밋된 필터를 그릴 때만** 갱신한다(F3): 초안의 정의를 여기 남기면 데이터 전환이
        # 적용된 적 없는 정의를 직전 슬롯에 박아, 원 소스로 돌아왔을 때 버튼이 거짓을 업는다.
        if fm is self.filter:
            self._filter_desc = view.describe() if fm.is_active() else ""
        visible = self._display_indices(self._zone_visible(view))  # 표 순서 = 표시순 투영
        vis_set = set(visible)
        columns = fm.columns
        table_rows = [
            {
                **lead_for(i),
                # 셀 텍스트 = 필터와 같은 읽기(cell_text 단일 출처) — `or ""` 류는 0·False 를
                # 빈칸으로 붕괴시켜 "필터는 남겼는데 표면은 빈 셀"이 된다(리뷰 #8).
                "cells": [view.segments(c, cell_text(records[i], c)) for c in columns],
            }
            for i in visible
        ]
        filter_snap = {
            "active": fm.is_active(),
            # 직전 필터 재적용 어포던스(결정 28) — 3연언(슬롯 ∧ 현 필터 빈 상태 ∧ 소스 일치).
            "reapply_available": self._reapply_available(),
            # 그 버튼이 설치할 정의(#127) — 어포던스가 살아있을 때만 싣는다.
            "reapply_hint": (
                self._last_filter.get("summary", "")
                if self._reapply_available() and self._last_filter else ""
            ),
            "search": fm.search_text,
            "chips": view.describe_parts(),   # 칩 줄 문안(정의줄 단일 출처, 결정 4)
            "definition": view.describe(),
            "branches": view.branches,        # 가지 칩(× 프루닝)
            "columns": [
                {"name": c, "kind": fm.kind(c), "active": fm.has_condition(c)}
                for c in columns
            ],
        }
        # 사용자 열 선별(U2 §2.19, #341) — **표시 여부를 여기서 판정**해 얹는다. 숨김은
        # 표시 축뿐이라 위 필터 평가·셀 합성(검색 하이라이트 포함)은 숨긴 열도 그대로
        # 지난다(전체 열 검색이 숨긴 열을 계속 매치하는 것이 숨김 ≠ 제외의 증거).
        hidden = self._zone_hidden() & set(columns)
        table_snap = {
            # 표 렌더러도 필터 모델이 이미 판정한 열 유형을 그대로 소비한다. 별도 판정기를
            # 두지 않는다 — 패널과 표 조판이 같은 ``FilterModel.kind`` 진실을 공유한다.
            # ``visible`` 은 표시 축 판정(#341) — 표면은 이 플래그로 그릴지만 정하고,
            # ``cells`` 는 전 열을 실어 열 index 정렬(ci)을 지킨다.
            "columns": [
                {"name": c, "kind": fm.kind(c), "visible": c not in hidden}
                for c in columns
            ],
            # 숨김 표지 칩의 소재 — 0개가 아니면 칩이 선다(상시, confirm-or-alarm).
            "hidden_columns": [c for c in columns if c in hidden],
            "rows": table_rows,
            "visible_count": len(visible),
            # 필터 밖 선택 — 스트립이 상시 진술(결정 3). 순서는 **호출자가 준 ``indices``
            # 순서** 그대로다: 작업 화면은 이미 표시순 투영을 통과한 실행 입력을 넘기므로
            # 스트립 표본이 표와 같은 축을 말한다(F3 판정 H — 두 목록이 다른 순서를 말하면
            # "보이는 것 = 실행되는 것"이 스트립에서만 깨진다). 기안 화면은 원본 순서를
            # 넘기고 표도 같은 순서라 역시 일치한다.
            "hidden_selected": [lead_for(i) for i in indices if i not in vis_set],
        }
        return filter_snap, table_snap, view, visible
