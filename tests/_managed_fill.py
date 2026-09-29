"""테스트 공용 — 템플릿 하나를 GUI·CLI 와 같은 managed 경로로 채운다(#1081 PR3).

legacy 엔진(``HwpxEngine.generate``)이 퇴역한 뒤 「이 템플릿에 이 값을 넣으면 문서가 어떻게
나오는가」를 재던 테스트들이 공유하는 얇은 조립이다. managed 는 확정되지 않은 활성 필드로
실행 계획을 세우지 않으므로, 연결이 덮지 않는 필드는 명시적 비움으로 확정한다(``cover``).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.delivery_coordinator import DeliveredDocument, DeliveryCompleted
from hwpxfiller.external.headless_generation import (
    HeadlessExecuted,
    HeadlessGenerationResult,
    run_headless_generation,
)
from hwpxfiller.external.hwpx_engine import make_hwpx_engine


def covered(template: "str | Path", mapping: MappingProfile) -> MappingProfile:
    """연결이 덮지 않는 템플릿 필드를 명시적 비움으로 채운 연결."""
    mapped = {item.template_field for item in mapping.mappings}
    extra = [
        FieldMapping(field, type="const")
        for field in make_hwpx_engine().required_fields(str(template))
        if field not in mapped
    ]
    return MappingProfile(name=mapping.name, mappings=[*mapping.mappings, *extra])


def generate(
    tmp_path: Path,
    template: "str | Path",
    mapping: MappingProfile,
    records: "list[dict[str, str]]",
    *,
    pattern: str = "doc-{{seq:001}}",
    cover: bool = True,
) -> HeadlessGenerationResult:
    return run_headless_generation(
        workspace=tmp_path / "managed-ws",
        template_path=str(template),
        mapping=covered(template, mapping) if cover else mapping,
        filename_pattern=pattern,
        records=records,
        source_schema_keys=tuple(dict.fromkeys(k for r in records for k in r)),
        output_directory=str(tmp_path / "managed-out"),
        overwrite=False,
        clock=datetime.now,
    )


def only_document(result: HeadlessGenerationResult) -> DeliveredDocument:
    """완주한 한 건의 배달 사실 — 완주가 아니면 결과를 그대로 보이며 실패한다."""
    assert isinstance(result, HeadlessExecuted), result
    assert isinstance(result.outcome, DeliveryCompleted), result.outcome
    (document,) = result.outcome.delivered
    return document
