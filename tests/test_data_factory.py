"""DataSource 팩토리 — 소스 종류 선택 단일화(Qt 불필요, 헤드리스).

파일 확장자 분기와 미지원 형식의 시끄러운 실패(ValueError)를 못박는다 —
UI/VM 은 이 포트만 알면 되고, 미래 소스 종류는 팩토리에만 추가된다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.data import DataSource, ExcelDataSource, make_source, source_for_path


def test_source_for_path_picks_excel_by_extension(tmp_path):
    for ext in (".xlsx", ".xlsm", ".csv"):
        src = source_for_path(tmp_path / f"data{ext}")
        assert isinstance(src, ExcelDataSource)
        assert isinstance(src, DataSource)  # 포트 준수(runtime_checkable Protocol)


def test_source_for_path_rejects_unknown_extension_loudly():
    with pytest.raises(ValueError):
        source_for_path("data.pdf")


def test_make_source_by_kind(tmp_path):
    assert isinstance(make_source("excel", path=str(tmp_path / "d.xlsx")), ExcelDataSource)
    with pytest.raises(ValueError):
        make_source("does_not_exist")


def test_make_source_pipeline_kind(tmp_path):
    from hwpxfiller.data.pipeline import PipelineSource

    src = make_source(
        "pipeline", sources=[source_for_path(tmp_path / "d.csv")], steps=[]
    )
    assert isinstance(src, PipelineSource)
    assert isinstance(src, DataSource)  # 파이프라인도 동일 포트로 다운스트림에 보임


def test_csv_roundtrip_through_factory(tmp_path):
    csv = tmp_path / "rec.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    src = source_for_path(csv)
    assert src.fields() == ["공고명", "추정가격"]
    assert src.records() == [{"공고명": "전산장비", "추정가격": "1000"}]
