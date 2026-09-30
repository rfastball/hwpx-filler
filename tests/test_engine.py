"""템플릿 엔진 — 요구 필드 판독(사전검증·CLI ``--fields``·실행뷰의 원천).

legacy 생성(``HwpxEngine.generate``·``hwpxfiller.batch.generate_batch``)은 #1081 PR3 에서
퇴역했다. 채움 사실(줄배치 캐시 제거·완화 노트)의 회귀는 managed 경로로 옮겨
``test_headless_generation`` 이 잰다. 여기 남는 것은 엔진의 유일한 표면인 필드 판독이다.
"""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.domain.fields import read_fields
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import read_hwpx_package

FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


def test_required_fields_are_the_template_field_names_in_document_order():
    fields = make_hwpx_engine().required_fields(str(FIXTURE))
    assert fields  # 픽스처에 누름틀 실재
    assert len(fields) == len(set(fields))  # 이름 단위 dedupe
    assert set(fields) == set(read_fields(read_hwpx_package(FIXTURE)))
