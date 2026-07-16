"""데이터셋 풀 워크숍 ViewModel — Qt 비의존(링1). durable 데이터 참조 관리면.

위젯(:class:`~hwpxfiller.gui.dataset_pool_panel.DatasetPoolPanel`)은 이 뷰모델을 들고
``rows()``·``register_excel``/``register_nara``·``archive``/``retire``/``delete`` 로
**렌더·오케스트레이션만** 한다. 참조 등록·상태 전이·행 성형은 전부 여기 산다 —
PySide6 임포트 없이 헤드리스로 테스트된다(template_manager_state 분리를 미러링).

**새 코어 없음.** 레지스트리·항목은 :mod:`~hwpxfiller.core.dataset_pool` 재사용.
등록은 **참조만** 저장한다(레코드·ServiceKey 없음) — 나라 키는 실행 복원 때 OS 저장소에서.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.dataset_pool import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_RETIRED,
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from .nara_state import NaraAcquireViewModel  # 기간 검증 단일 출처(링1→링1)

# 상태 → 사람이 읽는 배지 라벨/레벨(style.py QLabel[level=...] 팔레트와 통일).
# 경보 위계는 활성>지난(RC-26): '활성'(지금 실행에 쓰는 것)만 prominent(ok)로 세우고,
# 보관·은퇴는 둘 다 '지난 것'이라 muted 로 둔다. 은퇴=warn(보관=muted보다 강한 경보)는
# 위계 역전이었다 — 은퇴가 활성보다 시끄러울 이유가 없다.
_BADGE_LABELS = {
    STATUS_ACTIVE: "활성",
    STATUS_ARCHIVED: "보관",
    STATUS_RETIRED: "은퇴",
}
_BADGE_LEVELS = {
    STATUS_ACTIVE: "ok",
    STATUS_ARCHIVED: "muted",
    STATUS_RETIRED: "muted",
}
_KIND_LABELS = {"excel": "엑셀/CSV", "nara": "나라장터", "pipeline": "파이프라인"}


@dataclass(frozen=True)
class PoolAction:
    """상태 게이트가 허용하는 액션 하나 — ``key`` 안정 식별자, ``label`` 버튼 문구."""

    key: str
    label: str


# 상태 → 허용 액션(순수 단일 출처).
#   active   → [보관][은퇴][삭제]
#   archived → [활성화][은퇴][삭제]
#   retired  → [활성화][삭제]
_STATE_ACTIONS = {
    STATUS_ACTIVE: (
        PoolAction("archive", "보관"),
        PoolAction("retire", "은퇴"),
        PoolAction("delete", "삭제"),
    ),
    STATUS_ARCHIVED: (
        PoolAction("activate", "활성화"),
        PoolAction("retire", "은퇴"),
        PoolAction("delete", "삭제"),
    ),
    STATUS_RETIRED: (
        PoolAction("activate", "활성화"),
        PoolAction("delete", "삭제"),
    ),
}


def available_actions(status: str) -> "list[PoolAction]":
    return list(_STATE_ACTIONS.get(status, ()))


def reference_summary(item: DatasetPoolItem) -> str:
    """항목이 가리키는 참조의 사람이 읽는 요약(경로/쿼리 — 데이터·키 없음)."""
    opts = item.opts
    if item.kind == "excel":
        path = str(opts.get("path", ""))
        name = Path(path).name if path else "(경로 없음)"
        sheet = opts.get("sheet")
        return f"파일: {name}" + (f" · 시트 {sheet}" if sheet else "")
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


@dataclass
class DatasetPoolRow:
    """풀 1항목이 렌더할 성형 데이터 — 위젯은 이 필드만 읽는다."""

    name: str
    kind: str
    kind_label: str
    status: str
    badge_label: str
    badge_level: str
    reference: str
    note: str = ""

    def actions(self) -> "list[PoolAction]":
        return available_actions(self.status)

    @classmethod
    def from_item(cls, item: DatasetPoolItem) -> "DatasetPoolRow":
        return cls(
            name=item.name,
            kind=item.kind,
            kind_label=_KIND_LABELS.get(item.kind, item.kind),
            status=item.status,
            badge_label=_BADGE_LABELS.get(item.status, item.status),
            badge_level=_BADGE_LEVELS.get(item.status, "muted"),
            reference=reference_summary(item),
            note=item.note,
        )


class DatasetPoolViewModel:
    """데이터셋 풀 상태 + 오케스트레이션. 위젯은 구독해 렌더한다(Qt 비의존).

    ``registry`` 주입 가능(테스트는 ``DatasetPoolRegistry(tmp_path)``); 기본은 홈 레지스트리.
    """

    def __init__(self, registry: "DatasetPoolRegistry | None" = None):
        self.registry = (
            registry if registry is not None
            else DatasetPoolRegistry(default_dataset_pool_dir())
        )
        self._rows: "list[DatasetPoolRow]" = []
        # 손상 파일 격리 목록(RC-05) — refresh 가 채우고 표현 계층이 시끄럽게 표면화한다.
        self._corrupted: "list[tuple[Path, str]]" = []
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
        corrupted: "list[tuple[Path, str]]" = []
        items = self.registry.list_items(corrupted=corrupted)
        self._rows = [DatasetPoolRow.from_item(it) for it in items]
        self._corrupted = corrupted
        self._notify()

    def rows(self) -> "list[DatasetPoolRow]":
        return list(self._rows)

    def corrupted(self) -> "list[tuple[Path, str]]":
        """격리된 손상 파일 목록 ``(경로, 오류)`` — 표현 계층이 '손상됨' 항목으로 재진술한다."""
        return list(self._corrupted)

    def is_empty(self) -> bool:
        return not self._rows

    def count_label(self) -> str:
        return f"{len(self._rows)}건" if self._rows else ""

    # ---------------------------------------------------------- 등록(참조만)
    def register_excel(
        self, name: str, path: str, *, sheet: "str | None" = None, note: str = ""
    ) -> DatasetPoolItem:
        """엑셀/CSV 참조 등록 — **경로만** 저장(스냅샷 아님, 실행 때 재읽기)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        if not path:
            raise ValueError("파일 경로가 비어 있습니다.")
        opts: "dict[str, object]" = {"path": path}
        if sheet:
            opts["sheet"] = sheet
        item = DatasetPoolItem(name=name, kind="excel", opts=opts, note=note)
        self.registry.save(item)
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
    ) -> DatasetPoolItem:
        """나라장터 쿼리 참조 등록 — 기간·건수만 저장(**ServiceKey 없음**·데이터 없음).

        기간은 등록 시점에 검증한다(형식·1개월 제한) — 취득 경로만 믿고 우회 저장하면
        실행 때마다 실패하는 죽은 참조가 조용히 생긴다(RC-13).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")
        if not bgn_dt or not end_dt:
            raise ValueError("조회 기간(시작·종료)을 입력하세요.")
        rng_err = NaraAcquireViewModel.validate_range(bgn_dt, end_dt)
        if rng_err:
            raise ValueError(rng_err)
        opts: "dict[str, object]" = {"bgn_dt": bgn_dt, "end_dt": end_dt}
        if num_rows:
            opts["num_rows"] = num_rows
        if page_no:
            opts["page_no"] = page_no
        item = DatasetPoolItem(name=name, kind="nara", opts=opts, note=note)
        self.registry.save(item)
        self.refresh()
        return item

    # ---------------------------------------------------------- 상태/삭제
    def _transition(self, name: str, action: str) -> None:
        item = self.registry.load(name)
        getattr(item, action)()  # archive/retire/activate — 순수 전이
        self.registry.save(item)
        self.refresh()

    def archive(self, name: str) -> None:
        self._transition(name, "archive")

    def retire(self, name: str) -> None:
        self._transition(name, "retire")

    def activate(self, name: str) -> None:
        self._transition(name, "activate")

    def delete(self, name: str) -> None:
        self.registry.delete(name)
        self.refresh()

    def dispatch(self, key: str, name: str) -> None:
        """상태 액션 키를 전이/삭제로 라우팅(위젯 디스패처의 순수 몫)."""
        if key in ("archive", "retire", "activate"):
            self._transition(name, key)
        elif key == "delete":
            self.delete(name)
