"""데이터셋 풀 워크숍 Application 상태 — UI·저장 구현 비의존.

웹 컨트롤러(:class:`~hwpxfiller.webapp.screen_pool.PoolController`)가 이 뷰모델을 들고
``rows()``·``register_excel``/``register_pclm``/``register_nara``·
``archive``/``activate``/``delete`` 로
**렌더·오케스트레이션만** 한다(액션 키→핸들러 라우팅과 stale 항목 봉합은 컨트롤러 몫).
참조 등록·상태 전이·행 성형은 전부 여기 산다 — PySide6 임포트 없이 헤드리스로
테스트된다(template_manager_state 분리를 미러링). *(구 Qt ``DatasetPoolPanel`` 은
PySide6 철거로 제거됨 — 이제 소비자는 웹 컨트롤러다.)*

레지스트리는 :class:`DatasetPoolPort` 로 주입한다. 참조 값·수명·정체성은
:mod:`hwpxfiller.domain.dataset_reference` 가 소유하고 JSON·잠금·atomic write 는
External Adapter(:mod:`hwpxfiller.external.dataset_store`)가 소유한다. 등록은
**참조만** 저장한다(레코드·ServiceKey 없음).

**P2-22(#570) port 규율**: 포트에 물리(raw ``write_lock``·콜백 ``mutate``·``Path``
out-parameter)를 올리지 않는다. 잠긴 읽기-수정-쓰기가 필요한 업무 전이는 전부 포트의
**semantic atomic op**(``relabel``·``relink_excel``·``archive``·``activate``·확정 결속판
``*_confirmed``·``resolve_duplicates``) 하나로 완결된다 — 물리 잠금은 어댑터 내부
구현이고 Application 은 잠금을 잡지 않는다.

**확정 결속(코덱스 2R·3R 근본 조치)**: 파괴·덮어쓰기 확정 왕복 넷(삭제 · 같은 데이터
재등록의 라벨 갱신 · 다시 연결 · 중복 병합)은 전부 **1차가 보여준 상태의 지문**
(:func:`confirm_basis`)에 결속된다. 1차 응답이 ``basis`` 를 발행하고 확정이 그대로
되실어 보내면, 어댑터가 쓰기 잠금 안에서 지금 상태의 지문을 다시 지어 대조한다 —
다르거나 미동봉이면 **삭제·덮어쓰기 0건 + :class:`StaleConfirmError`**(fail-closed,
문안 재진술은 컨트롤러 몫).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.dataset_reference import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    DatasetReference,
    pclm_identity,
    reference_identity,
)
from ..domain.pclm_views import (
    PCLM_VIEW_LABELS,
    PCLM_VIEW_TITLES,
    PCLM_VIEWS,
    default_pclm_db,
)
from .nara_acquire import validate_range


class StaleConfirmError(Exception):
    """확정이 실은 지문과 지금 상태의 지문이 다르다(또는 근거 미동봉) — 파괴·갱신 0건.

    승인의 대상은 「그때 읽은 값」이다. 근거 미동봉(구식 호출)도 같은 거절이다 —
    무엇을 승인했는지 모르는 확정으로는 지우거나 덮을 수 없다(fail-closed).
    """


@dataclass(frozen=True)
class CorruptDatasetEntry:
    """파싱 실패한 풀 파일 1건의 사실 — 저장소가 주는 값 객체(RC-05 표면화의 원료).

    ``file_name`` 은 표시용(종전 ``path.name`` 과 동일 문자열)이고, Application·표현
    계층은 파일 좌표(``Path``)를 만지지 않는다(#569 ``CorruptJobEntry`` 동형).
    """

    file_name: str
    error: str


#: 확정 왕복이 결속하는 항목 상태의 성분(:func:`bound_state` 의 열쇠).
#:
#: **표시 요약에서 파생하지 않는다**(코덱스 3R 근본 조치): ``reference_summary`` 는 사람이
#: 읽으라고 정보를 **버리는** 함수라(경로를 basename 으로 줄인다) 결속의 재료로 부적합하다 —
#: ``/a/report.xlsx`` → ``/b/report.xlsx`` 재연결이 요약에서 같아 보이는 자리가 그 증거다.
#: 결속은 정체를 정하는 **전체 값**(정규화 정체성 + opts 원본)에서 짓고, 표시 문안만 요약을
#: 쓴다. 방향은 늘 「지문 ⊇ 표시」다: 표시에 드러나는 변화는 반드시 지문에도 드러난다.
BOUND_FIELDS = ("key", "name", "kind", "identity", "reference", "note", "status")


def bound_state(key: str, item: DatasetReference) -> "dict[str, str]":
    """확정이 결속할 항목 상태 한 벌 — **디스크 항목 하나**가 유일 소재다.

    소재를 항목으로 통일한 이유(3R): 종전엔 병합이 VM 행(표시 성형)을, 다시 연결이
    디스크 항목을 재료로 써서 같은 지문이 두 경로에서 다른 정보량을 담았다. 행에는
    ``opts`` 가 없어 표시 요약이 최선이었고, 그 손실이 곧 P2-1 이다.
    """
    opts = item.opts if isinstance(item.opts, dict) else {}
    values = (
        str(key),
        item.name,
        item.kind,
        # 정규화 정체성(경로+시트) — 표기 변형을 흡수한 「같은 데이터인가」의 축.
        reference_identity(item) or "",
        # 참조 **원본 전체** — 정체성 밖 opts(헤더 행·나라 쿼리·파이프라인 레시피)까지
        # 든다. 정체성만 들면 같은 파일의 다른 읽기 규칙 교체가 지문을 통과한다.
        json.dumps(opts, ensure_ascii=False, sort_keys=True, default=str),
        item.note,
        item.status,
    )
    return dict(zip(BOUND_FIELDS, values, strict=True))


def confirm_basis(states: "list[dict[str, str]]") -> str:
    """1차가 보여준 상태의 지문 — 확정이 되실어 대조하는 **단일 결속 기제**.

    키 순 정렬 + 정렬된 JSON 이라 같은 상태면 같은 값이 나온다(발신 순서·사전 순서
    무관). 값 하나라도 갈리면 지문이 갈리므로, 「무엇이 바뀌었는지」를 열거로 관리하지
    않는다 — 열거로 푼 문제는 다음 라운드에서 다시 샌다(1R→2R→3R 이 그 증거다).
    """
    payload = json.dumps(
        sorted(states, key=lambda s: s["key"]), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


class DatasetPoolPort(Protocol):
    """Application 이 요구하는 데이터셋 레지스트리 효과의 semantic port(#570).

    구조적(덕타이핑) 계약이다: concrete 는
    :class:`hwpxfiller.external.dataset_store.DatasetPoolRegistry`, 테스트는 in-memory
    구현이 선다. 모든 쓰기 연산은 저장 매체 안에서 **원자적으로** 완결된다 — 호출자가
    잠금을 알 필요도, 잡을 방법도 없다. ``expected_basis`` 를 받는 연산은 지금 상태의
    지문(:func:`confirm_basis` × :func:`bound_state`)과 대조해 다르거나 미동봉이면
    :class:`StaleConfirmError` 로 fail-closed 한다.
    """

    def load(self, key: str) -> DatasetReference: ...

    def list_references(
        self, status: "str | None" = None
    ) -> "tuple[list[tuple[str, DatasetReference]], list[CorruptDatasetEntry]]": ...

    def find_identity_raw(
        self, ident: str
    ) -> "tuple[str, DatasetReference] | None": ...

    def find_identity(
        self, path: "str | Path", sheet: "str | None" = ""
    ) -> "tuple[str, DatasetReference] | None": ...

    def add(self, item: DatasetReference) -> str: ...

    def delete(self, key: str) -> None: ...

    def archive(self, key: str) -> DatasetReference: ...

    def activate(self, key: str) -> DatasetReference: ...

    def relabel(self, key: str, name: str, *, note: str = "") -> DatasetReference: ...

    def relink_excel(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
    ) -> DatasetReference: ...

    def relabel_confirmed_raw(
        self, ident: str, name: str, *,
        note: str = "", expected_basis: "str | None",
    ) -> "tuple[str, DatasetReference]": ...

    def relabel_confirmed(
        self, path: str, sheet: "str | None", name: str, *,
        note: str = "", expected_basis: "str | None",
    ) -> "tuple[str, DatasetReference]": ...

    def relink_confirmed(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
        expected_basis: "str | None",
    ) -> DatasetReference: ...

    def delete_confirmed(
        self, key: str, *, expected_basis: "str | None"
    ) -> DatasetReference: ...

    def resolve_duplicates(
        self, keep: str, *, expected_basis: "str | None"
    ) -> "tuple[str, int]": ...

# 상태 → 사람이 읽는 배지 라벨/레벨(style.py QLabel[level=...] 팔레트와 통일).
# 2상태(#5): '활성'(지금 실행에 쓰는 것)만 prominent(ok), '보관'(지난 것)은 muted.
_BADGE_LABELS = {
    STATUS_ACTIVE: "활성",
    STATUS_ARCHIVED: "보관",
}
_BADGE_LEVELS = {
    STATUS_ACTIVE: "ok",
    STATUS_ARCHIVED: "muted",
}
_KIND_LABELS = {
    "excel": "엑셀/CSV",
    "nara": "나라장터",
    "pclm": "계약 목록",
    "pipeline": "파이프라인",
}

#: 종류 → 그 참조가 **가리키는 파일**이 사는 opts 키. 없는 종류(나라·조립)는 파일 참조가
#: 아니라 로케이트·끊김 배지의 대상이 아니다(빈 문자열 = 판정 밖).
_LOCATE_KEYS = {"excel": "path", "pclm": "db"}


@dataclass(frozen=True)
class PoolAction:
    """상태 게이트가 허용하는 액션 하나 — ``key`` 안정 식별자, ``label`` 버튼 문구."""

    key: str
    label: str


# 상태 → 허용 액션(순수 단일 출처, 2상태·#5).
#   active   → [보관][삭제]
#   archived → [활성화][삭제]
# 각 상태 정확히 2액션·겹침 0 → 라벨↔버튼 1:1(desync 구조적 제거).
_STATE_ACTIONS = {
    STATUS_ACTIVE: (
        PoolAction("archive", "보관"),
        PoolAction("delete", "삭제"),
    ),
    STATUS_ARCHIVED: (
        PoolAction("activate", "활성화"),
        PoolAction("delete", "삭제"),
    ),
}


def available_actions(status: str) -> "list[PoolAction]":
    return list(_STATE_ACTIONS.get(status, ()))


def resolve_pclm_db(db: str) -> str:
    """계약 목록 DB 경로 해석 — 빈 값이면 **기본 자리**, 있으면 절대경로.

    등록(:meth:`DatasetPoolViewModel.register_pclm`)과 그 전 중복 조회가 **같은 자리**를
    봐야 한다. 두 곳이 각자 빈 값을 해석하면 조회는 기본 자리를, 등록은 빈 문자열을 보고
    같은 데이터가 2건이 된다. 존재 검사는 하지 않는다 — 참조 등록은 파일을 열지 않고,
    끊김은 배지(:func:`~hwpxfiller.webapp.screens.reference_missing`)와 실행 시점 재읽기가
    말한다(``register_excel`` 과 같은 규율).
    """
    return os.path.abspath(db) if db else str(default_pclm_db())


def reference_summary(item: DatasetReference) -> str:
    """항목이 가리키는 참조의 사람이 읽는 요약(경로/쿼리 — 데이터·키 없음)."""
    opts = item.opts
    if item.kind == "excel":
        path = str(opts.get("path", ""))
        name = Path(path).name if path else "(경로 없음)"
        sheet = opts.get("sheet")
        return f"파일: {name}" + (f" · 시트 {sheet}" if sheet else "")
    if item.kind == "pclm":
        # 엑셀 문형의 거울 — 가리키는 파일 하나 + 그 안의 면 하나. 표면 어휘는 「시트」로
        # 통일한다(내부 어휘 「뷰」는 사용자가 읽을 자리에 서지 않는다). 면 이름도 제목으로
        # 옮긴다 — 미지 이름(손편집·구판)은 감추지 않고 원문 그대로 남긴다.
        db = str(opts.get("db", ""))
        name = Path(db).name if db else "(경로 없음)"
        view = opts.get("view")
        title = PCLM_VIEW_TITLES.get(str(view), view)
        return f"DB: {name}" + (f" · 시트 {title}" if view else "")
    if item.kind == "nara":
        bgn = opts.get("bgn_dt", "?")
        end = opts.get("end_dt", "?")
        rows = opts.get("num_rows")
        s = f"기간 {bgn}~{end}"
        return s + (f" · {rows}건" if rows else "")
    if item.kind == "pipeline":
        srcs = opts.get("sources")
        steps = opts.get("steps")
        n_src = len(srcs) if isinstance(srcs, list) else 0
        ops = (
            "+".join(str(st.get("op", "?")) for st in steps)
            if isinstance(steps, list) and steps
            else "스텝 없음"
        )
        return f"조립: 소스 {n_src}개 · {ops}"
    return "(알 수 없는 소스)"


def kind_transition_clause(item: DatasetReference) -> str:
    """동명 **비-excel** 항목에 엑셀 재등록을 확정할 때 확인 문구에 병기할 전이 재진술.

    확정 경로(:meth:`DatasetPoolViewModel.update_excel_reference`)는 kind 를 excel 로
    정규화하고 기존 opts(나라 기간·파이프라인 스텝)를 대체한다 — 확인 문구가 이 전이를
    함께 재진술하지 않으면 사용자가 승인한 내용과 디스크 착지 상태가 어긋난다
    (confirm-or-alarm: 확인 문구=실제 전이). excel 항목이면 전이가 없으므로
    ``""`` (불필요한 소음 금지 — 활성 재등록의 상태 문구 생략과 같은 결).
    """
    if item.kind == "excel":
        return ""
    label = _KIND_LABELS.get(item.kind, item.kind)
    return (
        f"\n종류도 {label} → 엑셀/CSV 참조로 바뀝니다"
        f"(기존 {label} 참조 정보는 사라집니다)."
    )


@dataclass
class DatasetPoolRow:
    """풀 1항목이 렌더할 성형 데이터 — 표현 계층은 이 필드만 읽는다.

    ``key`` 는 레지스트리 슬롯 키(U2 §5.3 — 이름은 중복 허용 라벨이라 행동의 겨눔 대상이
    될 수 없다). 표면의 사용·보관·활성화·삭제·다시 연결은 전부 이 키를 실어 보낸다.
    """

    key: str
    name: str
    kind: str
    kind_label: str
    status: str
    badge_label: str
    badge_level: str
    reference: str
    note: str = ""
    # 로케이트 대상 파일 경로(추적성 #53-B) — 파일을 가리키는 참조만(엑셀=``path``,
    # 계약 목록=``db``). nara/파이프라인은 파일이 아니라 "".
    locate_path: str = ""
    # 확정 시트(#67 다시 연결 프리필) — 엑셀 참조만. 미지정/비엑셀은 "".
    sheet: str = ""

    def actions(self) -> "list[PoolAction]":
        return available_actions(self.status)

    @classmethod
    def from_item(cls, key: str, item: DatasetReference) -> "DatasetPoolRow":
        opts = item.opts if isinstance(item.opts, dict) else {}
        # 「끊김」 배지·로케이트가 보는 파일은 종류마다 키가 다르다(엑셀=path, 계약 목록=db).
        # 그 대응을 여기 한 번만 적어야 배지와 로케이트가 **같은 파일**을 본다.
        raw = opts.get(_LOCATE_KEYS.get(item.kind, ""))
        locate_path = raw if isinstance(raw, str) else ""
        raw_sheet = opts.get("sheet")
        sheet = raw_sheet if (item.kind == "excel" and isinstance(raw_sheet, str)) else ""
        return cls(
            key=key,
            name=item.name,
            kind=item.kind,
            kind_label=_KIND_LABELS.get(item.kind, item.kind),
            status=item.status,
            badge_label=_BADGE_LABELS.get(item.status, item.status),
            badge_level=_BADGE_LEVELS.get(item.status, "muted"),
            reference=reference_summary(item),
            note=item.note,
            locate_path=locate_path,
            sheet=sheet,
        )


class DatasetPoolViewModel:
    """데이터셋 풀 상태 + 오케스트레이션. 웹 컨트롤러는 결과를 읽어 렌더한다(Qt 비의존).

    ``registry`` 는 외부 composition root 가 주입한다. Application 은 구체 저장 구현을
    모르고, 잠금도 잡지 않는다 — 원자성이 필요한 전이는 포트의 semantic op 하나로
    완결된다(#570).
    """

    def __init__(self, registry: DatasetPoolPort):
        self.registry = registry
        self._rows: "list[DatasetPoolRow]" = []
        # 손상 파일 격리 목록(RC-05) — refresh 가 채우고 표현 계층이 시끄럽게 표면화한다.
        self._corrupted: "list[CorruptDatasetEntry]" = []
        # 같은 정체성 슬롯 그룹(§5.3 병합 대상) — refresh 가 채운다. `_ident_groups` 는
        # 항목 원본(확정 결속·재진술 소재), `_duplicates` 는 그 행 투영이다 — 같은 스캔
        # 하나에서 파생한다(별도 재스캔 금지).
        self._ident_groups: "list[list[tuple[str, DatasetReference]]]" = []
        self._duplicates: "list[list[DatasetPoolRow]]" = []
        self._subs: list = []
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        self._subs.append(cb)

    def _notify(self) -> None:
        for cb in self._subs:
            cb()

    # ---------------------------------------------------------- 데이터
    def refresh(self) -> None:
        entries, corrupted = self.registry.list_references()
        self._rows = [DatasetPoolRow.from_item(key, it) for key, it in entries]
        self._corrupted = corrupted
        # 같은 정체성 슬롯 2+개(구판 마이그레이션의 병합 대상, §5.3) — 목록과 같은 스캔에서
        # 파생한다(별도 재스캔 금지). 표면이 loud 재진술하고 사용자 확정으로만 정리한다.
        by_ident: "dict[str, list[tuple[str, DatasetReference]]]" = {}
        for key, it in entries:
            ident = reference_identity(it)
            if ident is not None:
                by_ident.setdefault(ident, []).append((key, it))
        self._ident_groups = [g for g in by_ident.values() if len(g) > 1]
        row_by_key = {r.key: r for r in self._rows}
        self._duplicates = [
            [row_by_key[key] for key, _it in g] for g in self._ident_groups
        ]
        self._notify()

    def rows(self) -> "list[DatasetPoolRow]":
        return list(self._rows)

    def corrupted(self) -> "list[CorruptDatasetEntry]":
        """격리된 손상 파일 값 객체 목록 — 표현 계층이 '손상됨' 항목으로 재진술한다."""
        return list(self._corrupted)

    def duplicates(self) -> "list[list[DatasetPoolRow]]":
        """같은 데이터(경로+시트)를 가리키는 등록 2+건의 그룹 — 병합 확정 대상(§5.3).

        구판(이름=키)이 남긴 상태라 새 등록으로는 만들어지지 않는다(등록 게이트가 정체성
        중복을 갱신으로 접는다). 표면은 이 그룹을 숨기지 말고 loud 재진술한 뒤, 남길
        1건을 사용자가 고르게 한다 — 무손실 병합이 아니므로 조용한 자동 정리는 금지다.
        """
        return [list(g) for g in self._duplicates]

    def duplicate_group(self, keep: str) -> "list[tuple[str, DatasetReference]] | None":
        """``keep`` 이 속한 중복 그룹의 (키, 항목) 원본 — 확정 재진술·결속의 소재.

        :meth:`refresh` 가 목록을 만든 **같은 스캔**의 항목이라 화면 행과 어긋나지 않는다.
        VM 행은 표시 성형이라 opts 를 잃으므로(3R P2-1 의 뿌리) 결속 재료가 될 수 없다.
        """
        for g in self._ident_groups:
            if any(key == keep for key, _it in g):
                return list(g)
        return None

    def is_empty(self) -> bool:
        return not self._rows

    def count_label(self) -> str:
        return f"{len(self._rows)}건" if self._rows else ""

    # ---------------------------------------------------------- 등록(참조만)
    def find_same_data(
        self, path: str, sheet: "str | None" = None
    ) -> "tuple[str, DatasetReference] | None":
        """이 경로+시트가 이미 고정돼 있는가 — 등록 게이트의 **정체성** 중복 판정(§5.3 C).

        이름은 라벨이라 판정에 들지 않는다: 같은 데이터의 재등록은 새 항목이 아니라
        기존 슬롯의 라벨·메모 갱신(:meth:`relabel`)이고, 그 확정은 호출측(컨트롤러)이
        기존 이름을 재진술한 뒤 받는다.
        """
        return self.registry.find_identity(path, sheet or "")

    def find_same_pclm(
        self, db: str, view: str
    ) -> "tuple[str, DatasetReference] | None":
        """이 DB+뷰가 이미 고정돼 있는가 — 계약 목록 판 :meth:`find_same_data`.

        정체성 계산은 Domain 이 소유하므로(:func:`~hwpxfiller.domain.dataset_reference.
        pclm_identity`) 조회는 어댑터의 정체성 질의에 그대로 얹는다 — 경로 정규화(대소문자·
        상대경로)는 그 계산이 흡수한다.
        """
        return self.registry.find_identity_raw(pclm_identity(db, view))

    def register_excel(
        self, name: str, path: str, *, sheet: "str | None" = None, note: str = ""
    ) -> DatasetReference:
        """엑셀/CSV 참조 등록 — **경로만** 저장(스냅샷 아님, 실행 때 재읽기).

        같은 정체성(경로+시트)이 이미 있으면 레지스트리가 loud 거절한다 — 중복 확인·
        갱신 분기는 호출측이 :meth:`find_same_data` 로 먼저 가른다(백스톱 이중선).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        if not path:
            raise ValueError("파일 경로가 비어 있습니다.")
        opts: "dict[str, object]" = {"path": path}
        if sheet:
            opts["sheet"] = sheet
        item = DatasetReference(name=name, kind="excel", opts=opts, note=note)
        self.registry.add(item)
        self.refresh()
        return item

    def register_pclm(
        self, name: str, db: str = "", *, view: str, note: str = ""
    ) -> DatasetReference:
        """계약 목록(pclm) 참조 등록 — **DB 경로 + 뷰만** 저장(스냅샷 아님, 실행 때 재읽기).

        ``opts`` 는 **항상 두 키를 채운다**: 빈 ``db`` 는 「기본 자리」라는 뜻이지 「자리
        미상」이 아니므로 등록 시점에 :func:`resolve_pclm_db` 로 해석해 박는다 — 미기재로
        두면 나중에 기본 자리가 바뀌었을 때 같은 항목이 조용히 다른 DB 를 가리키고,
        정체성(같은 데이터인가)도 지어지지 않아 중복 판정이 통째로 죽는다.

        뷰는 여기서 검증한다(등록 시점 확정): 뷰 이름은 SELECT 에 그대로 박히는
        허용목록이고(:data:`~hwpxfiller.domain.pclm_views.PCLM_VIEWS`), 잘못된 이름을
        저장하면 실행 때마다 실패하는 죽은 참조가 조용히 생긴다(``register_nara`` 의 기간
        검증과 같은 근거, RC-13). 거절은 쓸 수 있는 뷰를 설명과 함께 재진술한다.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        if view not in PCLM_VIEWS:
            raise ValueError(
                f"계약 목록이 약속한 뷰가 아닙니다: {view!r}\n"
                "쓸 수 있는 뷰:\n"
                + "\n".join(f"  {v} — {PCLM_VIEW_LABELS[v]}" for v in PCLM_VIEWS)
            )
        opts: "dict[str, object]" = {"db": resolve_pclm_db(db), "view": view}
        item = DatasetReference(name=name, kind="pclm", opts=opts, note=note)
        self.registry.add(item)
        self.refresh()
        return item

    def relabel(self, key: str, name: str, *, note: str = "") -> DatasetReference:
        """같은 데이터 재고정의 확정 착지 — **라벨·메모만** 갱신(수명·참조 보존).

        이름은 정체성이 아니므로(§5.3 C) 이 갱신은 다른 소비자를 흔들 수 없다 — 참조를
        드는 외래 소비자 자체가 없다(`default_dataset_ref` 폐기, 판정 D). 메모는 입력이
        있을 때만 교체한다(빈 입력 = 진술 없음, 조용한 소거 금지).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        item = self.registry.relabel(key, name, note=note)
        self.refresh()
        return item

    def relabel_confirmed(
        self, path: str, sheet: "str | None", name: str, *,
        note: str = "", basis: "str | None",
    ) -> DatasetReference:
        """라벨 갱신 확정(같은 데이터 재등록의 2차) — 결속 대조·갱신은 어댑터가 한 잠금 안에서.

        확인 모달이 열린 사이 같은 등록의 이름·비고가 바뀌면 :class:`StaleConfirmError`,
        삭제됐으면 ``FileNotFoundError`` (신규 등록 승인으로 부활 금지 — 코덱스 3R P2-2).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        _key, item = self.registry.relabel_confirmed(
            path, sheet or "", name, note=note, expected_basis=basis
        )
        self.refresh()
        return item

    def relabel_confirmed_raw(
        self, ident: str, name: str, *, note: str = "", basis: "str | None"
    ) -> DatasetReference:
        """정체성으로 겨눈 라벨 갱신 확정 — 종류를 묻지 않는 :meth:`relabel_confirmed` 의 몸통.

        엑셀 판은 경로+시트라는 **사람이 든 좌표**를 받지만, 계약 목록처럼 좌표가 다른
        종류가 늘 때마다 확정 경로를 복제하지 않으려면 결속 왕복은 정체성 하나로 서야
        한다(어댑터도 같은 규율 — :meth:`~hwpxfiller.external.dataset_store.
        DatasetPoolRegistry.relabel_confirmed_raw`). 정체성 계산은 Domain 소유다.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        _key, item = self.registry.relabel_confirmed_raw(
            ident, name, note=note, expected_basis=basis
        )
        self.refresh()
        return item

    def update_excel_reference(
        self,
        key: str,
        path: str,
        *,
        sheet: "str | None" = None,
        note: str = "",
        name: str = "",
    ) -> DatasetReference:
        """다시 연결 확정 — 기존 슬롯의 **참조(kind+opts)만** 갱신한다(수명 보존, C3).

        정체성 검사·kind 정규화·변이의 원자성은 어댑터 semantic op
        (:meth:`DatasetPoolPort.relink_excel`)가 진다 — 새 참조가 **다른 슬롯의
        정체성**과 겹치면 같은 데이터가 2건이 되므로 loud 거절된다. 메모는 입력이 있을
        때만 교체한다(빈 입력 = 진술 없음, 조용한 소거 금지).
        """
        if not path:
            raise ValueError("파일 경로가 비어 있습니다.")
        item = self.registry.relink_excel(key, path, sheet=sheet, note=note, name=name)
        self.refresh()
        return item

    def relink_confirmed(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
        basis: "str | None",
    ) -> DatasetReference:
        """다시 연결 확정(2차) — 1차가 보여준 슬롯 상태의 지문에 결속된 원자 갱신(2R P2)."""
        if not path:
            raise ValueError("파일 경로가 비어 있습니다.")
        item = self.registry.relink_confirmed(
            key, path, sheet=sheet, note=note, name=name, expected_basis=basis
        )
        self.refresh()
        return item

    def register_nara(
        self,
        name: str,
        bgn_dt: str,
        end_dt: str,
        *,
        num_rows: "int | None" = None,
        page_no: "int | None" = None,
        note: str = "",
    ) -> DatasetReference:
        """나라장터 쿼리 참조 등록 — 기간·건수만 저장(**ServiceKey 없음**·데이터 없음).

        기간은 등록 시점에 검증한다(형식·1개월 제한) — 취득 경로만 믿고 우회 저장하면
        실행 때마다 실패하는 죽은 참조가 조용히 생긴다(RC-13).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        if not bgn_dt or not end_dt:
            raise ValueError("조회 기간(시작·종료)을 입력하세요.")
        rng_err = validate_range(bgn_dt, end_dt)
        if rng_err:
            raise ValueError(rng_err)
        opts: "dict[str, object]" = {"bgn_dt": bgn_dt, "end_dt": end_dt}
        if num_rows:
            opts["num_rows"] = num_rows
        if page_no:
            opts["page_no"] = page_no
        item = DatasetReference(name=name, kind="nara", opts=opts, note=note)
        self.registry.add(item)
        self.refresh()
        return item

    # ---------------------------------------------------------- 상태/삭제(슬롯 키)
    def _transition(self, key: str, action: str) -> None:
        if action == "archive":
            self.registry.archive(key)
        elif action == "activate":
            self.registry.activate(key)
        else:
            raise ValueError(f"지원하지 않는 데이터셋 전이: {action!r}")
        self.refresh()

    def archive(self, key: str) -> None:
        self._transition(key, "archive")

    def activate(self, key: str) -> None:
        self._transition(key, "activate")

    def delete(self, key: str) -> None:
        self.registry.delete(key)
        self.refresh()

    # ---------------------------------------------------------- 확정 결속 use case(#570)
    def inspect(self, key: str) -> "tuple[DatasetReference, str]":
        """확정 1차의 소재 — (지금 디스크 항목, 그 상태의 지문). 문안은 컨트롤러가 짓는다."""
        item = self.registry.load(key)
        return item, confirm_basis([bound_state(key, item)])

    def delete_confirmed(self, key: str, *, basis: "str | None") -> DatasetReference:
        """결속 삭제(2차) — 지워진 항목을 돌려준다(결과 문구 소재). 어긋나면 삭제 0건."""
        item = self.registry.delete_confirmed(key, expected_basis=basis)
        self.refresh()
        return item

    def resolve_duplicates(self, keep: str, *, basis: "str | None") -> "tuple[str, int]":
        """중복 병합 확정(2차) — ``(남은 이름, 삭제 건수)``. 그룹 변동은 fail-closed."""
        kept, removed = self.registry.resolve_duplicates(keep, expected_basis=basis)
        self.refresh()
        return kept, removed


__all__ = [
    "BOUND_FIELDS",
    "CorruptDatasetEntry",
    "DatasetPoolPort",
    "PoolAction",
    "DatasetPoolRow",
    "DatasetPoolViewModel",
    "StaleConfirmError",
    "available_actions",
    "bound_state",
    "confirm_basis",
    "kind_transition_clause",
    "reference_summary",
    "resolve_pclm_db",
]
