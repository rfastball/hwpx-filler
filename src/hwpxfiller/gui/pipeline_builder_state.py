"""파이프라인 빌더 ViewModel — Qt 비의존(링1). 조립 파이프라인 저작·미리보기면.

위젯(:class:`~hwpxfiller.gui.pipeline_builder.PipelineBuilderDialog`)은 이 뷰모델을 들고
소스 추가·스텝 편집·미리보기·저장을 **렌더·오케스트레이션만** 한다(dataset_pool_state 분리
미러). PySide6 임포트 없이 헤드리스로 테스트된다.

**divergence 0 (UnivContractor #3).** 미리보기는 별도 경로를 만들지 않는다 — 저장될 드래프트
항목(``{kind:"pipeline", opts:{sources, steps}}``)을 **실행과 동일한**
:func:`~hwpxfiller.data.factory.source_from_pool_item` 으로 복원해 ``records()`` 를 렌더한다.
미리보기가 보여준 파이프라인 = 저장 후 실행이 복원하는 그 파이프라인(문자 그대로 같은 함수).

**merge 제안 = 제안 전용·사람 확정(ADR D).** 공유 컬럼 감지는 후보 키 목록을 *반환*할 뿐
스텝을 만들지 않는다 — 사용자가 키를 골라 명시적으로 추가한다(추측 조인 자동실행 금지).
merge 키 후보 = **실제 공유 컬럼**(구조축 schema, UnivContractor #2) — preset 이름 휴리스틱 없음.

**참조만 저장.** 드래프트 opts 는 서브소스 참조(kind+opts)와 스텝 레시피뿐 — 레코드·키 없음
(KA 라운드트립 불변식 계승). v1 스텝 = merge+append 뿐(falsifiable 가드 — 팽창 시 정지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from ..core.dataset_pool import STATUS_ACTIVE, DatasetPoolItem, DatasetPoolRegistry
from ..data.factory import source_from_pool_item

# v1 스텝 op 집합 — 이 둘을 넘어 자라면 슬롯 발명 신호(ADR K falsifiable 가드).
_V1_OPS = ("merge", "append")
_MERGE_HOWS = ("inner", "left")


@dataclass(frozen=True)
class SourceSlot:
    """선택된 서브소스 1개 — 풀 항목의 **참조 사본**(kind+opts) + 표시 이름."""

    name: str
    kind: str
    opts: "dict[str, object]"


@dataclass(frozen=True)
class PreviewResult:
    """미리보기 결과 — 성공(fields·rows) 또는 시끄러운 실패(error 문구).

    조립 실패는 조용히 빈 표로 두지 않는다 — ``error`` 가 차 있으면 위젯이 경고로
    표면화한다(confirm-or-alarm; KA AssemblyError 의 GUI 착지).
    """

    fields: "list[str]" = field(default_factory=list)
    rows: "list[dict[str, str]]" = field(default_factory=list)
    total: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class PipelineBuilderViewModel:
    """조립 파이프라인 드래프트 상태 + 저작 오케스트레이션(Qt 비의존).

    ``registry`` 주입 가능(테스트는 ``DatasetPoolRegistry(tmp_path)``).
    ``secret_store``/``fetcher`` 는 나라 서브소스 복원에 전파된다(N1 키 주입 경로 상속;
    테스트는 주입으로 네트워크 무접촉).
    """

    def __init__(
        self,
        registry: DatasetPoolRegistry,
        *,
        secret_store=None,
        fetcher=None,
    ):
        self.registry = registry
        self._secret_store = secret_store
        self._fetcher = fetcher
        self.sources: "list[SourceSlot]" = []
        self.steps: "list[dict]" = []

    # ------------------------------------------------------------- 후보 소스
    def available_source_names(self) -> "list[str]":
        """서브소스 후보 = 풀의 **active** 항목(파이프라인 제외).

        파이프라인-속-파이프라인은 v1 밖 — KA 재귀 복원이 기술적으로 지원하나, 최소
        표면 원칙 + 자기참조 순환(무한 재귀) 위험 차단을 위해 후보에서 뺀다.
        """
        return [
            it.name
            for it in self.registry.list_items(status=STATUS_ACTIVE)
            if it.kind != "pipeline"
        ]

    # ------------------------------------------------------------- 소스 편집
    def add_source(self, pool_name: str) -> SourceSlot:
        """풀 항목 이름으로 서브소스 추가 — 참조(kind+opts)만 사본으로 담는다."""
        item = self.registry.load(pool_name)
        if item.kind == "pipeline":
            raise ValueError(
                "파이프라인을 파이프라인의 소스로 넣을 수 없습니다(v1 중첩 미지원)."
            )
        slot = SourceSlot(name=item.name, kind=item.kind, opts=dict(item.opts))
        self.sources.append(slot)
        return slot

    def remove_source(self, index: int) -> None:
        """서브소스 제거 — 그 소스를 참조하는 스텝이 있으면 **시끄럽게 거부**.

        조용한 스텝 자동삭제(추측)는 금지; 사용자가 스텝을 먼저 제거해야 한다.
        **씨앗(index 0) 제거도 스텝이 있는 한 거부** — 씨앗은 스텝이 명시 참조하지
        않아도 파이프라인 의미가 암묵 참조하는 기준 테이블이라, 제거 시 다음 소스가
        조용히 승격되며 기존 스텝이 전혀 다른 조립(자기조인 포함)이 된다.
        더 높은 인덱스를 참조하는 스텝은 의미 보존 재번호(순수 시프트, 추측 아님).
        """
        if not (0 <= index < len(self.sources)):
            raise ValueError(f"소스 인덱스가 범위를 벗어났습니다: {index}")
        if index == 0 and self.steps:
            raise ValueError(
                "기준(첫) 소스는 스텝이 있는 동안 제거할 수 없습니다 — 스텝을 먼저 "
                "제거하세요(제거 시 다음 소스가 기준으로 승격되어 조립 의미가 바뀝니다)."
            )
        for n, st in enumerate(self.steps):
            if st.get("source") == index:
                raise ValueError(
                    f"스텝 {n + 1}({st.get('op')})이 이 소스를 사용합니다 — 스텝을 먼저 제거하세요."
                )
        del self.sources[index]
        for st in self.steps:
            if isinstance(st.get("source"), int) and st["source"] > index:
                st["source"] -= 1

    # ------------------------------------------------------------- 스텝 편집
    def add_step(
        self,
        op: str,
        source_index: int,
        *,
        on: "str | None" = None,
        how: str = "inner",
    ) -> dict:
        """스텝 추가(v1 = merge|append). 인자 검증은 여기서 시끄럽게 — 실행 전에 잡는다."""
        if op not in _V1_OPS:
            raise ValueError(f"알 수 없는 스텝 종류입니다: {op!r} (v1 = merge|append)")
        if not (0 <= source_index < len(self.sources)):
            raise ValueError(f"스텝 대상 소스가 없습니다: {source_index}")
        if op == "merge":
            if not on:
                raise ValueError("merge 스텝에는 조인 키(on)가 필요합니다.")
            if how not in _MERGE_HOWS:
                raise ValueError(f"merge how 는 'inner'|'left' 여야 합니다: {how!r}")
            step = {"op": "merge", "source": source_index, "on": on, "how": how}
        else:
            step = {"op": "append", "source": source_index}
        self.steps.append(step)
        return step

    def remove_step(self, index: int) -> None:
        if not (0 <= index < len(self.steps)):
            raise ValueError(f"스텝 인덱스가 범위를 벗어났습니다: {index}")
        del self.steps[index]

    # ------------------------------------------------------------- 드래프트/복원
    def draft_opts(self) -> "dict[str, object]":
        """저장될 opts — 서브소스 **참조**(kind+opts)와 스텝 레시피만(데이터·키 없음)."""
        return {
            "sources": [{"kind": s.kind, "opts": dict(s.opts)} for s in self.sources],
            "steps": [dict(st) for st in self.steps],
        }

    def build_source(self):
        """드래프트를 실행 경로로 복원 — 미리보기·저장 후 실행이 **공유하는 단일 경로**.

        :func:`source_from_pool_item` 그대로 — 나라 서브소스 키 주입(N1)·재귀 복원(KA)을
        전부 상속한다. 별도 조립 경로를 두지 않는 것이 divergence 0 의 구조적 보장.
        """
        draft = SimpleNamespace(kind="pipeline", opts=self.draft_opts())
        return source_from_pool_item(
            draft, secret_store=self._secret_store, fetcher=self._fetcher
        )

    # ------------------------------------------------------------- 미리보기
    def preview(self, limit: int = 20) -> PreviewResult:
        """WYSIWYG 미리보기 — 실행 동일 경로로 조립해 상위 ``limit`` 행을 성형.

        실패(빈 소스·키 부재·조립 오류)는 삼키지 않고 ``error`` 로 표면화한다.
        """
        if not self.sources:
            return PreviewResult(error="소스를 먼저 추가하세요.")
        try:
            src = self.build_source()
            records = src.records()
            fields = src.fields()
        except Exception as exc:  # noqa: BLE001 — 모든 조립 실패를 경고로 표면화
            return PreviewResult(error=str(exc))
        return PreviewResult(fields=fields, rows=records[:limit], total=len(records))

    # ------------------------------------------------------------- merge 제안
    def suggest_merge_keys(self, source_index: int) -> "list[str]":
        """공유 컬럼 감지 — 현재 드래프트 결과와 대상 소스의 **실제 공유 컬럼**(구조축).

        **제안 전용**: 후보 키 목록만 반환하고 스텝을 만들지 않는다(사람이 골라
        :meth:`add_step` 으로 명시 확정 — ADR D 게이트). 감지 실패는 시끄럽게(ValueError).

        현재 결과가 **0행이면 "감지 불가"로 시끄럽게** 실패한다 — 파이프라인 필드는
        레코드 유도(:meth:`PipelineSource.fields`)라 0행에선 스키마상 공유 컬럼이
        실재해도 보이지 않는다. 불확실("판단 근거 없음")을 오답("공유 컬럼 없음")으로
        단정하지 않는다(confirm-or-alarm).
        """
        if not (0 <= source_index < len(self.sources)):
            raise ValueError(f"소스 인덱스가 범위를 벗어났습니다: {source_index}")
        current = self.preview(limit=1)
        if not current.ok:
            raise ValueError(f"현재 조립 결과를 읽을 수 없습니다: {current.error}")
        if current.total == 0:
            raise ValueError(
                "현재 조립 결과가 0행이라 공유 컬럼을 감지할 수 없습니다 — "
                "키를 직접 입력하세요."
            )
        slot = self.sources[source_index]
        target = source_from_pool_item(
            SimpleNamespace(kind=slot.kind, opts=dict(slot.opts)),
            secret_store=self._secret_store,
            fetcher=self._fetcher,
        )
        target_fields = set(target.fields())
        return [f for f in current.fields if f in target_fields]  # 등장순 유지

    # ------------------------------------------------------------- 저장(참조만)
    def save(
        self, name: str, *, note: str = "", overwrite: bool = False
    ) -> DatasetPoolItem:
        """드래프트를 풀 항목으로 저장 — **참조·레시피만**(KA 라운드트립 불변식).

        동명 항목이 이미 있으면 **조용히 덮지 않고** 거부한다 — 빌더는 기존 항목명이
        소스 콤보에 그대로 노출되는 표면이라 충돌 확률이 구조적으로 높고, 덮어쓰기는
        기존 durable 참조(엑셀 경로·나라 쿼리)를 무경고 소실시킨다. 덮어쓰기는
        호출측이 사용자 확정을 받은 뒤 ``overwrite=True`` 로만(confirm-or-alarm).
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("파이프라인 이름을 입력하세요.")
        if not self.sources:
            raise ValueError("소스가 없습니다 — 서브소스를 하나 이상 추가하세요.")
        if not overwrite and self.registry.exists(name):
            raise ValueError(
                f"같은 이름의 데이터셋이 이미 있습니다: {name!r} — 다른 이름을 쓰거나 "
                "덮어쓰기를 확정하세요."
            )
        # 조립 유효성 게이트(UD-01) — save 가 build_source 를 호출하지 않아 깨진 조립(부재 키·
        # 빈 취득)도 그대로 저장되고 실행 시점에야 실패하던 결함을 닫는다. 저장은 실행과 **같은**
        # 복원 경로(preview→build_source)로 조립이 성립함을 확인한 뒤에만 커밋한다 — 실패는
        # 실행이 아니라 저장 시점에 시끄럽게(confirm-or-alarm; divergence 0 단일 경로 재사용).
        assembly = self.preview(limit=1)
        if not assembly.ok:
            raise ValueError(f"조립이 유효하지 않아 저장할 수 없습니다: {assembly.error}")
        item = DatasetPoolItem(
            name=name, kind="pipeline", opts=self.draft_opts(), note=note
        )
        # 위 exists 게이트가 이미 동명/slug 충돌을 걸러 확정(overwrite=True) 아니면 여기 못 온다.
        # 확정 경로는 core slug 가드에 allow_overwrite 로 opt-in 한다(#34; 이중 차단 회피).
        self.registry.save(item, allow_overwrite=overwrite)
        return item
