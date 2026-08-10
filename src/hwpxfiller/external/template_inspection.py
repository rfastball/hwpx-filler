"""HWPX 템플릿 판독 효과의 외부 어댑터."""

from __future__ import annotations

from hwpxcore.package import HwpxPackage

from ..core.fields import fill_precheck
from ..core.template_status import compile_status
from ..gui.template_manager_state import TemplateInspection


def inspect_hwpx_template(path: str) -> TemplateInspection:
    """경로를 한 번 열고 같은 패키지 스냅샷에서 상태와 사전고지를 계산한다."""
    package = HwpxPackage.open(path)
    return TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
    )
