"""DataSource 팩토리 — 소스 종류 선택 단일화(Qt 불필요, 헤드리스).

파일 확장자 분기와 미지원 형식의 시끄러운 실패(ValueError)를 못박는다 —
UI/VM 은 이 포트만 알면 되고, 미래 소스 종류는 팩토리에만 추가된다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.data import (
    DataSource,
    ExcelDataSource,
    InlineDataSource,
    make_source,
    sheet_overview,
    source_for_path,
    source_from_pool_item,
)

FIXTURES = Path(__file__).parent / "fixtures"
MULTI_SHEET = FIXTURES / "multi_sheet.xlsx"


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


def test_make_source_inline_kind_wraps_records():
    """수기 1건 경로(UD-25) — 파일 없이 메모리 레코드를 동일 포트로 겨눈다."""
    rec = {"공고명": "전산장비", "추정가격": "1000"}
    src = make_source("inline", records=[rec])
    assert isinstance(src, InlineDataSource)
    assert isinstance(src, DataSource)  # 파일 소스와 동일 포트(다운스트림 무구별)
    assert src.records() == [rec]
    assert src.fields() == ["공고명", "추정가격"]
    assert src.field_labels() == {}
    # 방어 복사 — 반환 dict 변형이 소스 내부를 오염시키지 않는다.
    src.records()[0]["공고명"] = "변조"
    assert src.records() == [rec]


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


# ---------------------------------------------------------------- 시트 열거
# sheet_overview = 소비자(시트 선택 다이얼로그)의 생략 판정 단일 출처:
# 빈 목록(CSV)·길이 1(단일 시트)이면 묻지 않고, 2개 이상이면 묻는다.


def test_sheet_overview_lists_all_sheets_in_workbook_order():
    """다중 시트 픽스처 — 통합문서 순서 그대로, 시트별 행×열(근사) 동반."""
    overview = sheet_overview(MULTI_SHEET)
    assert [name for name, _, _ in overview] == ["공고목록", "낙찰현황"]
    # 헤더 포함 행수·열수 — 픽스처는 시트별로 규모가 다르다(2×2열 vs 3×3열 데이터).
    assert overview[0][1:] == (3, 2)  # 공고목록: 헤더 1 + 데이터 2, 열 2
    assert overview[1][1:] == (4, 3)  # 낙찰현황: 헤더 1 + 데이터 3, 열 3


def test_sheet_overview_csv_returns_empty_without_raising(tmp_path):
    """CSV 는 시트 개념이 없다 — 빈 목록(다이얼로그 생략 판정값), 예외 금지."""
    csv = tmp_path / "rec.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    assert sheet_overview(csv) == []


def test_sheet_overview_single_sheet_returns_length_one(tmp_path):
    from openpyxl import Workbook

    xlsx = tmp_path / "one.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "유일시트"
    ws.append(["공고명"])
    ws.append(["전산장비"])
    wb.save(xlsx)
    overview = sheet_overview(xlsx)
    assert len(overview) == 1
    assert overview[0][0] == "유일시트"


def test_source_for_path_passes_sheet_through():
    """sheet= 관통 고정 — 지정 시트의 레코드가 첫 시트와 다른 내용으로 온다."""
    src = source_for_path(MULTI_SHEET, sheet="낙찰현황")
    assert src.fields() == ["업체명", "낙찰금액", "계약일"]
    assert len(src.records()) == 3
    assert src.records()[0]["업체명"] == "가나상사"
    # 대조군: 기본(첫 시트)은 다른 헤더·행수다.
    first = source_for_path(MULTI_SHEET)
    assert first.fields() == ["공고명", "추정가격"]
    assert len(first.records()) == 2


def test_source_from_pool_item_restores_excel_sheet_opt():
    """kind='excel' 풀 항목 opts 의 sheet 가 복원 소스까지 관통함을 고정."""
    item = SimpleNamespace(
        kind="excel", opts={"path": str(MULTI_SHEET), "sheet": "낙찰현황"}
    )
    src = source_from_pool_item(item)
    assert isinstance(src, ExcelDataSource)
    assert src.fields() == ["업체명", "낙찰금액", "계약일"]
    assert len(src.records()) == 3
