"""레코드 범위 상태와 전문 편집기 초안 — 계약 §18.10 ``recordRange``/``RecordRangeDraft``.

재작성 F3(봉합 지도 §10.11)의 링1 신설분. 세션이 들고 있던 세 값(선택 집합·필터 정의·전체
표시순서)을 **한 그릇**으로 부르고, 전문 편집기가 그 그릇을 복제해 편집한다.

## 왜 그릇이 필요한가

계약은 초안이 "적용 전 메인 범위·validation·approval·결과를 바꾸지 않는다"고 요구한다
(불변식 §18.11-21). 세 값이 컨트롤러 속성으로 흩어져 있으면 복제·적용·취소가 **세 번씩**
일어나고, 한 값만 빠뜨린 복제가 곧 "취소했는데 필터만 바뀌어 있다" 같은 결함이 된다.

## 선택 정체성 — index 를 그대로 쓰는 근거

계약은 ``snapshotRecordId``·``snapshotOrdinal`` 을 말하지만, 이 앱의 레코드 목록은 마운트
단위로 **통째 교체**되고 새 스냅샷의 최초 선택은 0건이다(§18.2). 즉 index 는 이미
snapshot-local 이고 ordinal 과 같은 값이라, 계약이 막으려는 것("원본 행 번호를 영구 ID 로
쓰기")을 구조적으로 하지 않는다(지도 §10.11 판정 G — 실측 축소). 되깎기 조건: 스냅샷을
갈지 않고 레코드를 부분 갱신하는 경로가 생기면 그때 id 를 신설한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .filter_state import FilterModel
from .selection_state import SelectionModel


@dataclass
class RecordRange:
    """한 스냅샷 위의 범위 상태 — 선택 집합 · 필터 정의 · 전체 표시순서."""

    selection: SelectionModel
    filter: "FilterModel | None"
    view_order: str

    def copy(self) -> "RecordRange":
        """깊은 복제 — 초안 진입(§18.10 "진입 때 RecordRangeState를 draft로 깊은 복제").

        필터는 ``deepcopy`` 가 아니라 **모델 자신의 직렬화**(export/apply)로 복제한다:
        같은 열 지형이라 무손실이고, 렌더 경로가 들고 있을 수 있는 라이브 캐시를 같이
        복사해 오지 않는다(직전 필터 재적용의 초안 설치와 같은 기법).
        """
        sel = SelectionModel(len(self.selection), all_selected=False)
        for i in self.selection.selected_indices():
            sel.toggle(i, True)
        flt = None
        if self.filter is not None:
            flt = FilterModel(
                self.filter.columns, {c: self.filter.kind(c) for c in self.filter.columns}
            )
            flt.apply_state(self.filter.export_state())
        return RecordRange(selection=sel, filter=flt, view_order=self.view_order)

    def fingerprint(self) -> str:
        """이 범위의 정체 — 초안이 실제로 무언가를 바꿨는지(dirty) 판정하는 값.

        선택 집합 + 필터 정의 + 표시순서 전부가 든다. **표시순서가 지문에 드는 이유**는
        그것이 생성 순서이고 파일 이름 순번의 함수이기 때문이다(§2 충돌 B) — 순서만 바꾼
        적용도 실행 증거의 강등 대상이다.
        """
        return json.dumps(
            {
                "selected": self.selection.selected_indices(),
                "filter": self.filter.export_state() if self.filter is not None else None,
                "order": self.view_order,
            },
            sort_keys=True,
            ensure_ascii=False,
        )


@dataclass
class RecordRangeDraft:
    """전문 범위 편집기가 편집하는 초안 — 적용 전에는 메인 범위에 닿지 않는다.

    ``snapshot_gen`` 은 초안이 어느 스냅샷 위에서 열렸는지다. 적용 시점에 세대가 다르면
    초안의 index 는 **남의 행**을 가리키므로 조용히 커밋하지 않고 거절한다.
    ``selected_only`` 는 초안 안에서만 사는 **보기** 상태라 적용 대상이 아니다(지도 §10.11
    판정 B) — 메인 화면에는 그 토글이 없다.

    ``base_fingerprint`` 는 **여는 시점의 지문**이다: dirty 판정은 "연 뒤 내가 바꿨는가"이지
    "지금 커밋과 다른가"가 아니다. 판정의 주체를 값이 아니라 **사건**(내 편집)으로 두면,
    커밋 쪽이 나중에 움직이는 경로가 생겨도 이탈 가드가 거짓말하지 않는다.
    """

    range: RecordRange
    snapshot_gen: int
    base_fingerprint: str
    selected_only: bool = False

    def is_dirty(self) -> bool:
        return self.range.fingerprint() != self.base_fingerprint
