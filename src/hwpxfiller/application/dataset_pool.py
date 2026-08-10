"""데이터셋 풀 워크숍 Application 상태 — UI·저장 구현 비의존.

웹 컨트롤러(:class:`~hwpxfiller.webapp.screen_pool.PoolController`)가 이 뷰모델을 들고
``rows()``·``register_excel``/``register_nara``·``archive``/``activate``/``delete`` 로
**렌더·오케스트레이션만** 한다(액션 키→핸들러 라우팅과 stale 항목 봉합은 컨트롤러 몫).
참조 등록·상태 전이·행 성형은 전부 여기 산다 — PySide6 임포트 없이 헤드리스로
테스트된다(template_manager_state 분리를 미러링). *(구 Qt ``DatasetPoolPanel`` 은
PySide6 철거로 제거됨 — 이제 소비자는 웹 컨트롤러다.)*

레지스트리는 :class:`DatasetPoolPort`로 주입한다. 참조 값·수명·정체성은
:mod:`hwpxfiller.domain.dataset_reference`가 소유하고 JSON·잠금·atomic write는
External Adapter가 소유한다. 등록은 **참조만** 저장한다(레코드·ServiceKey 없음).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..domain.dataset_reference import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    DatasetReference,
    reference_identity,
)
from .nara_acquire import validate_range


class DatasetPoolPort(Protocol):
    """Application이 요구하는 데이터셋 레지스트리 효과의 최소 port."""

    def list_entries(
        self,
        status: "str | None" = None,
        *,
        corrupted: "list[tuple[Path, str]] | None" = None,
    ) -> Any: ...

    def find_identity(
        self, path: "str | Path", sheet: "str | None" = ""
    ) -> Any: ...

    def add(self, item: DatasetReference) -> str: ...

    def mutate(self, key: str, change: Any) -> Any: ...

    def write_lock(self) -> Any: ...

    def delete(self, key: str) -> None: ...

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
_KIND_LABELS = {"excel": "엑셀/CSV", "nara": "나라장터", "pipeline": "파이프라인"}


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


def reference_summary(item: DatasetReference) -> str:
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


def kind_transition_clause(item: DatasetReference) -> str:
    """동명 **비-excel** 항목에 엑셀 재등록을 확정할 때 확인 문구에 병기할 전이 재진술.

    확정 경로(:meth:`DatasetPoolViewModel.update_excel_reference` · 에디터 ``_do_save``)는
    kind 를 excel 로 정규화하고 기존 opts(나라 기간·파이프라인 스텝)를 대체한다 — 확인
    문구가 이 전이를 함께 재진술하지 않으면 사용자가 승인한 내용과 디스크 착지 상태가
    어긋난다(confirm-or-alarm: 확인 문구=실제 전이). excel 항목이면 전이가 없으므로
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
    # 로케이트 대상 파일 경로(추적성 #53-B) — 엑셀 참조만. nara/파이프라인은 파일이 아니라 "".
    locate_path: str = ""
    # 확정 시트(#67 다시 연결 프리필) — 엑셀 참조만. 미지정/비엑셀은 "".
    sheet: str = ""

    def actions(self) -> "list[PoolAction]":
        return available_actions(self.status)

    @classmethod
    def from_item(cls, key: str, item: DatasetReference) -> "DatasetPoolRow":
        raw = item.opts.get("path") if isinstance(item.opts, dict) else None
        locate_path = raw if (item.kind == "excel" and isinstance(raw, str)) else ""
        raw_sheet = item.opts.get("sheet") if isinstance(item.opts, dict) else None
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

    ``registry``는 외부 composition root가 주입한다. Application은 구체 저장 구현을 모른다.
    """

    def __init__(self, registry: DatasetPoolPort):
        self.registry = registry
        self._rows: "list[DatasetPoolRow]" = []
        # 손상 파일 격리 목록(RC-05) — refresh 가 채우고 표현 계층이 시끄럽게 표면화한다.
        self._corrupted: "list[tuple[Path, str]]" = []
        # 같은 정체성 슬롯 그룹(§5.3 병합 대상) — refresh 가 채운다.
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
        corrupted: "list[tuple[Path, str]]" = []
        entries = self.registry.list_entries(corrupted=corrupted)
        self._rows = [DatasetPoolRow.from_item(key, it) for key, it in entries]
        self._corrupted = corrupted
        # 같은 정체성 슬롯 2+개(구판 마이그레이션의 병합 대상, §5.3) — 목록과 같은 스캔에서
        # 파생한다(별도 재스캔 금지). 표면이 loud 재진술하고 사용자 확정으로만 정리한다.
        by_ident: "dict[str, list[DatasetPoolRow]]" = {}
        for (_key, it), row in zip(entries, self._rows, strict=True):
            ident = reference_identity(it)
            if ident is not None:
                by_ident.setdefault(ident, []).append(row)
        self._duplicates = [g for g in by_ident.values() if len(g) > 1]
        self._notify()

    def rows(self) -> "list[DatasetPoolRow]":
        return list(self._rows)

    def corrupted(self) -> "list[tuple[Path, str]]":
        """격리된 손상 파일 목록 ``(경로, 오류)`` — 표현 계층이 '손상됨' 항목으로 재진술한다."""
        return list(self._corrupted)

    def duplicates(self) -> "list[list[DatasetPoolRow]]":
        """같은 데이터(경로+시트)를 가리키는 등록 2+건의 그룹 — 병합 확정 대상(§5.3).

        구판(이름=키)이 남긴 상태라 새 등록으로는 만들어지지 않는다(등록 게이트가 정체성
        중복을 갱신으로 접는다). 표면은 이 그룹을 숨기지 말고 loud 재진술한 뒤, 남길
        1건을 사용자가 고르게 한다 — 무손실 병합이 아니므로 조용한 자동 정리는 금지다.
        """
        return [list(g) for g in self._duplicates]

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

    def relabel(self, key: str, name: str, *, note: str = "") -> DatasetReference:
        """같은 데이터 재고정의 확정 착지 — **라벨·메모만** 갱신(수명·참조 보존).

        이름은 정체성이 아니므로(§5.3 C) 이 갱신은 다른 소비자를 흔들 수 없다 — 참조를
        드는 외래 소비자 자체가 없다(`default_dataset_ref` 폐기, 판정 D). 메모는 입력이
        있을 때만 교체한다(빈 입력 = 진술 없음, 조용한 소거 금지).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("데이터셋 이름을 입력하세요.")

        def update(current: DatasetReference) -> None:
            current.name = name
            if note:
                current.note = note

        item = self.registry.mutate(key, update)
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

        새 항목으로 통째 교체하면 보관 상태가 조용히 active 로 복귀해 실행 후보에
        재등장하고 note·created_at 이 소실된다 — 확인 문구는 '참조가 새 파일로 바뀐다'만
        재진술하므로 상태·생성시각은 건드리지 않는 것이 문구와 일치한다. 내용물 교체가
        이 개체의 **정상 수명 사건**이라(월별 파일 갈아끼우기) 정체성이 바뀌어도 슬롯은
        산다 — §5.3 이 id 축을 기각한 바로 그 근거다. 단 새 참조가 **다른 슬롯의
        정체성**과 겹치면 같은 데이터가 2건이 되므로 loud 거절한다. 메모는 입력이 있을
        때만 교체한다(빈 입력 = 진술 없음, 조용한 소거 금지).

        **kind 정규화(r4)**: opts 만 갈아끼우고 kind 를 방치하면 nara/pipeline 항목이
        ``kind="nara" + opts={"path": …}`` 하이브리드로 손상된다 — 겨눔 시 나라 동결
        문구로 거절되고, reference_summary 는 "기간 ?~?" 를 찍는다. 엑셀 참조 확정은
        kind 도 excel 로 착지한다(cross-kind 전이는 :func:`kind_transition_clause` 재진술).

        **정체성 검사는 변이와 한 잠금 안이다**(코덱스 1R P2): pywebview 는 호출마다 다른
        스레드로 들어오므로, 잠금 밖 선검사는 서로 다른 슬롯 둘을 같은 경로+시트로 동시
        재연결할 때 둘 다 통과시키고 mutate 만 직렬화돼 **같은 정체성의 슬롯 2개**가 남는다
        — 레지스트리 불변식(같은 데이터 = 슬롯 1개)이 조용히 깨진다. 공유 쓰기 잠금
        (:meth:`~hwpxfiller.core.dataset_pool.DatasetPoolRegistry.write_lock`, 재진입 RLock)
        안에서 검사하고 그대로 mutate 까지 간다 — ``add`` 가 자기 잠금 안에서 검사하는 것과
        같은 규율이다.
        """
        if not path:
            raise ValueError("파일 경로가 비어 있습니다.")
        opts: "dict[str, object]" = {"path": path}
        if sheet:
            opts["sheet"] = sheet

        def update(current: DatasetReference) -> None:
            # 호출자가 본 행은 확인 모달 전 스냅샷일 수 있다. 현재 디스크 항목을 잠금 안에서
            # 다시 읽어 참조 필드만 바꿔야 동시 보관 상태·메모를 되돌리거나 삭제를 부활시키지 않는다.
            current.kind = "excel"  # kind/opts 정합 — 하이브리드 손상 항목 금지(r4)
            current.opts = opts
            if note:
                current.note = note
            if name:  # 라벨은 정체성이 아니라(§5.3 C) 같은 확정에 함께 갱신해도 안전하다
                current.name = name

        with self.registry.write_lock():
            taken = self.registry.find_identity(path, sheet or "")
            if taken is not None and taken[0] != key:
                raise ValueError(
                    f"그 파일·시트는 이미 '{taken[1].name}' 으로 고정돼 있습니다. "
                    "그 항목을 쓰거나 먼저 정리하세요."
                )
            item = self.registry.mutate(key, update)
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
            self.registry.mutate(key, lambda item: item.archive())
        elif action == "activate":
            self.registry.mutate(key, lambda item: item.activate())
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


__all__ = [
    "DatasetPoolPort",
    "PoolAction",
    "DatasetPoolRow",
    "DatasetPoolViewModel",
    "available_actions",
    "kind_transition_clause",
    "reference_summary",
]
