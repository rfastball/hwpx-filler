"""템플릿-구조 드리프트의 순수 파생 — 매핑 전건 커버와 현재 템플릿 누름틀의 대칭차.

별도 스냅샷을 저장하지 않는다. 사람이 확정한 매핑 커버가 기준선이고, 현재 템플릿
누름틀과의 대칭차가 곧 템플릿-구조 드리프트다(CLI 하드게이트·재연결 재진술·홈 건강 보기).

종전 이 모듈이 함께 소유하던 legacy 생성 원장(``FillLedger``·``LedgerRow``·``OutputLedger`` —
``GenerateResult`` 순서열에서 파생한 매핑 행·되읽기 증거)은 legacy 생성기와 함께 #1081 PR3 에서
퇴역했다. 생성 원장은 managed 배달 원장(:func:`hwpxfiller.external.ledger_export
.write_managed_delivery_ledger`)이 진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .engine import HwpxEngine
from .mapping import MappingProfile


@dataclass(frozen=True)
class TemplateStructureDrift:
    """현재 템플릿 누름틀과 매핑 커버의 양방향 대칭차.

    ``readable`` 는 **구조를 실제로 읽었는가**이고 기본값이 거짓이다(U6-F #980). 대칭차만
    보면 「읽고 나서 아무 차이도 없었다」와 「읽지 못해 아무것도 모른다」가 같은 모양(전부
    빈 튜플)이라, 그 위에 수치를 세우는 표면이 「연결 n / n · 확인 필요 0」을 지어낸다.
    빈 인스턴스(원장 기본값)는 아직 아무것도 읽지 않은 상태이므로 거짓이 옳은 기본이다 —
    참으로 만들려면 :func:`template_structure_drift` 를 실제로 지나야 한다.

    ``template_fields`` 는 그때 읽은 누름틀 이름의 **문서순**이다. 같은 재계산에서 이미
    손에 있던 값이라, 이것을 버리면 「그 템플릿에 무슨 필드가 있나」를 묻는 표면이 파일을
    한 번 더 연다.
    """

    template_only: "tuple[str, ...]" = ()
    mapping_only: "tuple[str, ...]" = ()
    conflicting: "tuple[str, ...]" = ()
    read_error: str = ""
    readable: bool = False
    template_fields: "tuple[str, ...]" = ()

    @property
    def has_drift(self) -> bool:
        return bool(self.template_only or self.mapping_only or self.conflicting or self.read_error)

    @property
    def introduced(self) -> "tuple[str, ...]":
        """템플릿에 새로 유입됐으나 매핑이 커버하지 않는 필드."""
        return self.template_only

    @property
    def removed(self) -> "tuple[str, ...]":
        """매핑 계약에는 있으나 현재 템플릿에서 소멸한 필드."""
        return self.mapping_only

    @property
    def symmetric_difference(self) -> "set[str]":
        return set(self.template_only) | set(self.mapping_only)

    @property
    def template_uncovered(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``T - C``."""
        return self.template_only

    @property
    def mapping_orphaned(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``C - T``."""
        return self.mapping_only

    def describe(self, sep: str = "\n") -> str:
        """차단 사유 상세 문구의 **단일 출처**(RC-03) — GUI·CLI·생성 경계가 같은 문장을 쓴다.

        표면별로 문구를 재조립하면 이미 갈라졌던 전례(run_state/run_view/cli/batch 4곳)가
        있어, 조립을 여기로 하강한다. 드리프트가 없으면 빈 문자열.
        """
        parts: "list[str]" = []
        if self.read_error:
            parts.append("템플릿 구조를 읽을 수 없음: " + self.read_error)
        if self.template_only:
            parts.append("새로 유입된 미매핑 필드: " + ", ".join(self.template_only))
        if self.mapping_only:
            parts.append("템플릿에서 소멸한 매핑 필드: " + ", ".join(self.mapping_only))
        if self.conflicting:
            parts.append("값 매핑과 비움 확정이 충돌하는 필드: " + ", ".join(self.conflicting))
        return sep.join(parts)


def template_structure_drift(
    template_fields: "Iterable[str]", mapping: MappingProfile
) -> TemplateStructureDrift:
    """``현재 템플릿 Δ effective mapping 커버``를 순서 안정적으로 계산한다."""
    template_order = list(dict.fromkeys(template_fields))
    cover_order = mapping.cover_fields()
    template_set = set(template_order)
    cover_set = set(cover_order)
    return TemplateStructureDrift(
        template_only=tuple(f for f in template_order if f not in cover_set),
        mapping_only=tuple(f for f in cover_order if f not in template_set),
        conflicting=tuple(mapping.coverage_conflicts()),
        # 여기까지 왔다는 것이 곧 「구조를 읽었다」다 — 실패 갈래는 위에서 read_error 로 돈다.
        readable=True,
        template_fields=tuple(template_order),
    )


# 간결한 호출명도 제공한다. L2가 원장 행을 확장할 때 같은 seam을 그대로 소비한다.
mapping_drift = template_structure_drift


def template_path_drift(
    path: "str", mapping: MappingProfile, *, engine: HwpxEngine
) -> TemplateStructureDrift:
    """HWPX 경로를 매 호출 다시 읽어 구조 드리프트를 fail-closed로 계산한다.

    GUI 실행·CLI가 공유하는 경계다. 파일 부재/손상/파싱 실패를 정상
    빈 템플릿으로 오인하지 않고 ``read_error`` 로 반환한다. 재읽기의 zip IO 는
    호출자가 결속해 준 ``engine``(package read/write 포트 뒤)이 진다(P3-03, #591).
    """
    if not path:
        return TemplateStructureDrift(read_error="템플릿 경로가 비어 있습니다.")
    try:
        fields = engine.required_fields(path)
    except Exception as exc:  # noqa: BLE001 - 구조를 증명 못 하면 fail-closed
        return TemplateStructureDrift(read_error=str(exc))
    return template_structure_drift(fields, mapping)
