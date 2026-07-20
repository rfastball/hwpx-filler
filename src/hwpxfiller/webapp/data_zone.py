"""데이터 존 공용 믹스인 — 필터 선언·행 선택 표면의 컨트롤러 몫(블록 3·4, 슬라이스 6 PR-2b).

웹 쪽 ``web/js/datazone.js`` 팩토리(PR-2a)의 Python 짝이다: 「작업」 화면(블록 4)이 착지한
필터·선택 디스패치와 스냅샷 합성을 txt 일괄 큐(블록 3)가 재사용한다 — 컨트롤러마다 복붙하면
JS 에서 막은 #94(링2 400줄 중복)와 동형의 드리프트가 Python 에서 재발한다. 판정은 전부 링1
(:class:`~hwpxfiller.gui.filter_state.FilterModel`·:class:`~hwpxfiller.gui.selection_state.
SelectionModel`)이 소유하고, 여기는 디스패치 위임과 스냅샷 성형만 든다(#87 경계 유지).

## 소비 컨트롤러가 대는 표면

- ``self.selection``(:class:`SelectionModel`) · ``self.filter``(:class:`FilterModel` | None —
  데이터 미겨눔이면 None) · ``self._last_filter``/``self._data_key``(결정 28 직전 필터 슬롯·
  소스 일치 키 — 데이터 겨눔 경로가 :meth:`_stash_filter` 후 :meth:`_file_key`/:meth:`_pool_key`
  로 갱신) · ``self.pool_registry``/``self.data_label``(풀 키 정체 해소).
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
EMPTY_TABLE = {"columns": [], "rows": [], "visible_count": 0, "hidden_selected": []}


class DataZoneMixin:
    """필터·선택 디스패치(``_do_*``)와 존 스냅샷 합성 — 컨트롤러 공유 표면(모듈 독스트링 참조)."""

    selection: SelectionModel
    filter: "FilterModel | None"
    _last_filter: "dict | None"   # {"source_key": str, "state": dict} — 결정 28 슬롯
    _data_key: str                # 현 데이터 소스 정체(file:경로 | pool:참조) — 소스 일치 판정
    pool_registry: DatasetPoolRegistry
    data_label: str

    def _records(self) -> list:
        raise NotImplementedError  # 컨트롤러가 현 데이터소스 레코드를 댄다

    # ------------------------------------------------------------- 행 선택 액션
    def _do_toggle_record(self, p: dict) -> None:
        self.selection.toggle(int(p["index"]), bool(p["value"]))

    def _do_select_range(self, p: dict) -> None:
        """Shift 범위 — 앵커 행의 상태를 범위에 전파(결정 2). 표면이 가시 순서 범위를 준다."""
        value = bool(p["value"])
        for i in p["indices"]:
            self.selection.toggle(int(i), value)

    def _do_set_all(self, p: dict) -> dict:
        """「전체 선택」 — 필터 활성 시 **매치 전체를 가산**한다(결정 4·26 "전체 선택 가산적").

        필터 밖 기존 선택은 유지된다(선택은 필터를 관통, 결정 3) — '매치'의 담보는 버튼
        이름이 아니라 게이트 정의줄 재진술이 진다. 반환 ``added`` = 새로 선택된 행 수 —
        전멸 필터에서의 무동작(0)을 표면이 정직하게 알린다(confirm-or-alarm, 리뷰 #9:
        아무 반응 없는 버튼은 결함으로 읽힌다).
        """
        before = self.selection.selected_count()
        if self.filter is not None and self.filter.is_active():
            for i in self.filter.visible_indices(self._records()):
                self.selection.toggle(i, True)
        else:
            self.selection.set_all()
        return {"added": self.selection.selected_count() - before}

    def _do_set_none(self, p: dict) -> None:
        """「전체 해제」 — 명시 동사라 가드 불요(T4), 필터와 무관하게 전부 해제."""
        self.selection.set_none()

    # ------------------------------------------------- 필터 액션(블록 4, 결정 23~25)
    def _filter_or_raise(self) -> FilterModel:
        if self.filter is None:  # 표면 오배선 검출 — 데이터 없이 필터 액션은 프로그램 결함
            raise ValueError("데이터를 먼저 선택하세요.")
        return self.filter

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
            try:
                # 정의줄은 **죽는 시점의 레코드로** 짓는다 — 되살릴 때는 그 데이터가 없을 수도
                # 있다. 버튼이 무엇을 설치하는지 말하기 위한 문안(#127)이라, 못 지으면 빈
                # 문자열로 강등한다(어포던스 자체는 살린다 — 문안 부재가 복원을 막을 이유는 없다).
                summary = self.filter.view(self._records()).describe()
            except Exception:  # noqa: BLE001
                summary = ""
            self._last_filter = {
                "source_key": self._data_key,
                "state": self.filter.export_state(),
                "summary": summary,
            }

    def _current_filter_empty(self) -> bool:
        """현 세션 필터가 백지인가 — 재적용 게이트의 셋째 연언(#127)."""
        return self.filter is None or not self.filter.is_active()

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
            raise ValueError(
                "현재 필터가 설정돼 있어 직전 필터를 재적용하지 않았습니다 — "
                "재적용은 필터를 지운 뒤에만 할 수 있습니다."
            )
        if slot is None or not self._reapply_available():
            raise ValueError("재적용할 직전 필터가 없습니다.")
        state = slot["state"]
        kinds = {c: fm.kind(c) for c in fm.columns}
        probe = FilterModel(fm.columns, kinds)
        installed, dropped = probe.apply_state(state)
        if not probe.is_active():
            return {
                "ok": False,
                "error": "직전 필터의 조건이 현재 데이터 열에 하나도 남지 않아 적용하지 "
                         "않았습니다: " + ", ".join(dropped),
            }
        records = self._records()
        if probe.search_text and not probe.view(records).branches:
            unpruned = FilterModel(fm.columns, kinds)
            unpruned.apply_state(dict(state, pruned=[]))
            if unpruned.view(records).branches:  # 프루닝만 걷으면 가지가 산다 = 소실 유래
                probe = unpruned
                dropped = dropped + ["(프루닝 — 가지 소실로 복원하지 않음)"]
        self.filter = probe  # 원자 교체 — 검증된 초안이 그대로 정의가 된다
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
        """풀 소스 키 — 이름이 아니라 **참조 정체**(kind+opts)까지 병기(리뷰 #6).

        라벨은 가변이다: 같은 이름으로 다른 파일을 재등록하면 이름만으론 게이트가 뚫려
        이전 데이터의 정의가 "같은 소스"로 제공된다. 참조 해소 실패 시(경합 삭제 등)는
        빈 정체로 강등 — 게이트가 닫히는 안전 방향.
        """
        # 지연 임포트 — screens.py 가 이 믹스인을 소비하므로 모듈 상단 상호 임포트는 순환.
        from .screens import load_pool_item_checked

        try:
            item = load_pool_item_checked(self.pool_registry, self.data_label)
            ident = f"{item.kind}:{json.dumps(item.opts, sort_keys=True, ensure_ascii=False)}"
        except Exception:  # noqa: BLE001 — 정체 불명 = 게이트 닫힘(안전 강등)
            ident = ""
        return f"pool:{self.data_label}:{ident}"

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
        if self.filter is None:
            return EMPTY_FILTER, EMPTY_TABLE, None, []
        records = self._records()
        fm = self.filter
        view = fm.view(records)  # 가지 1회 산출 — 렌더 경로 캐시 계약(filter_state)
        visible = view.visible_indices()
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
        table_snap = {
            "columns": columns,
            "rows": table_rows,
            "visible_count": len(visible),
            # 필터 밖 선택 — 스트립이 상시 진술(결정 3). 원본 순서.
            "hidden_selected": [lead_for(i) for i in indices if i not in vis_set],
        }
        return filter_snap, table_snap, view, visible
