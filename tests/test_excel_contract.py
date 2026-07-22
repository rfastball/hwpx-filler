"""Excel/CSV 행 성형 계약(#183)."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from hwpxfiller.data.excel import ExcelDataSource


def _xlsx(path: Path, rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_custom_header_row_blank_and_ragged_rows_share_policy(
    tmp_path: Path, suffix: str
) -> None:
    path = tmp_path / f"rows{suffix}"
    if suffix == ".csv":
        path.write_text(
            "설명 줄\n공고명,금액,담당자\n전산장비,1000\n,,\n비품,2000,김담당\n",
            encoding="utf-8-sig",
        )
    else:
        _xlsx(
            path,
            [
                ["설명 줄"],
                ["공고명", "금액", "담당자"],
                ["전산장비", 1000],
                [None, None, None],
                ["비품", 2000, "김담당"],
            ],
        )

    source = ExcelDataSource(str(path), header_row=2)

    assert source.fields() == ["공고명", "금액", "담당자"]
    assert source.records() == [
        {"공고명": "전산장비", "금액": "1000", "담당자": ""},
        {"공고명": "비품", "금액": "2000", "담당자": "김담당"},
    ]


def test_csv_bom_and_unicode_headers_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "unicode.csv"
    path.write_text("공고명,예산￦,담당자𠮷\n장비,10,김\n", encoding="utf-8-sig")

    source = ExcelDataSource(str(path))

    assert source.fields() == ["공고명", "예산￦", "담당자𠮷"]
    assert source.records()[0]["담당자𠮷"] == "김"


@pytest.mark.parametrize(
    ("headers", "message"),
    [(["공고명", "", "담당자"], "빈 헤더"), (["공고명", "공고명"], "중복 헤더")],
)
@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_blank_and_duplicate_headers_fail_loudly(
    tmp_path: Path, suffix: str, headers: list[str], message: str
) -> None:
    path = tmp_path / f"bad{suffix}"
    if suffix == ".csv":
        path.write_text(",".join(headers) + "\n값,값,값\n", encoding="utf-8")
    else:
        _xlsx(path, [headers, ["값"] * len(headers)])

    with pytest.raises(ValueError, match=message):
        ExcelDataSource(str(path)).fields()


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_nonblank_cells_beyond_header_fail_loudly(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"wide{suffix}"
    if suffix == ".csv":
        path.write_text("공고명\n장비,숨은 값\n", encoding="utf-8")
    else:
        _xlsx(path, [["공고명"], ["장비", "숨은 값"]])

    # CSV는 ragged overflow로, XLSX는 worksheet max_column이 헤더까지 넓어져 빈 헤더로
    # 관측된다. 어느 쪽도 이름 없는 값을 조용히 버리지 않는다.
    with pytest.raises(ValueError, match="빈 헤더|헤더보다 값이 많은 행"):
        ExcelDataSource(str(path)).records()


def test_xlsx_scalar_conversion_is_deterministic(tmp_path: Path) -> None:
    path = _xlsx(
        tmp_path / "scalars.xlsx",
        [
            ["날짜", "시각", "정수", "실수", "참거짓"],
            [date(2026, 7, 22), datetime(2026, 7, 22, 9, 5, 6), 1000, 1.25, True],
        ],
    )

    assert ExcelDataSource(str(path)).records() == [
        {
            "날짜": "2026-07-22 00:00:00",
            "시각": "2026-07-22 09:05:06",
            "정수": "1000",
            "실수": "1.25",
            "참거짓": "TRUE",
        }
    ]


def test_xlsx_formula_without_cached_value_fails_loudly(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "formula.xlsx", [["합계"], ["=1+2"]])

    with pytest.raises(ValueError, match="수식 cache가 없습니다"):
        ExcelDataSource(str(path)).records()


def test_csv_and_xlsx_same_logical_data_have_parity(tmp_path: Path) -> None:
    csv_path = tmp_path / "same.csv"
    csv_path.write_text(
        "공고명,금액,완료\n전산장비,1000,TRUE\n비품,1.25,FALSE\n",
        encoding="utf-8-sig",
    )
    xlsx_path = _xlsx(
        tmp_path / "same.xlsx",
        [["공고명", "금액", "완료"], ["전산장비", 1000, True], ["비품", 1.25, False]],
    )

    csv_source = ExcelDataSource(str(csv_path))
    xlsx_source = ExcelDataSource(str(xlsx_path))

    assert csv_source.fields() == xlsx_source.fields()
    assert csv_source.records() == xlsx_source.records()


def test_minimal_xlsm_is_read_through_supported_adapter(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "minimal.xlsm", [["공고명", "금액"], ["전산장비", 1000]])

    source = ExcelDataSource(str(path))

    assert source.fields() == ["공고명", "금액"]
    assert source.records() == [{"공고명": "전산장비", "금액": "1000"}]


@pytest.mark.parametrize("header_row", [0, -1, True, 1.5])
def test_header_row_must_be_positive_integer(header_row: object) -> None:
    with pytest.raises(ValueError, match="1 이상의 정수"):
        ExcelDataSource("unused.csv", header_row=header_row)  # type: ignore[arg-type]
