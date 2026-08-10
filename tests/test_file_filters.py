"""파일 다이얼로그 필터 단일 출처(RC-34) — 파생 검증 + 하드코딩 재유입 grep 게이트.

지원 확장자의 단일 출처는 domain/data_source.py(``SUPPORTED_DATA_FILE_EXTENSIONS``)다.
factory와 gui/file_filters.py가 함께 파생하고, 그 지점 밖의 필터 리터럴 하드코딩은
확장자 정책 변경 시 화면별 드리프트로 이어진다(재유입 금지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _filter_literal_pattern() -> "re.Pattern[str]":
    """Domain 정본 확장자와 hwpx의 필터 리터럴 시그니처.

    "이름 (*.ext …)" 의 "(*.ext" 부분만 겨눈다 — 단일 출처가 없는 일회성 필터
    (txt 저장·매핑 json 등)는 RC-34 스코프 밖이라 게이트하지 않는다.
    Domain 정본에서 파생하므로 확장자가 늘어나면 게이트도 자동으로 따라온다.
    """
    from hwpxfiller.domain.data_source import SUPPORTED_DATA_FILE_EXTENSIONS

    exts = [ext.lstrip(".") for ext in SUPPORTED_DATA_FILE_EXTENSIONS] + ["hwpx"]
    return re.compile(r"\(\*\.(?:" + "|".join(map(re.escape, exts)) + r")\b")


def test_factory_alias_is_domain_canonical_tuple():
    import hwpxfiller.data as data_package
    import hwpxfiller.domain.data_source as domain_data_source
    from hwpxfiller.data.factory import EXCEL_EXTS
    from hwpxfiller.gui.file_filters import EXCEL_EXTS as FILTER_EXTS

    public_api = ("Record", "SUPPORTED_DATA_FILE_EXTENSIONS", "DataSource")
    assert tuple(domain_data_source.__all__) == public_api
    assert domain_data_source.DataSource.field_labels(object()) == {}

    assert data_package.Record is domain_data_source.Record
    assert data_package.DataSource is domain_data_source.DataSource
    assert EXCEL_EXTS is domain_data_source.SUPPORTED_DATA_FILE_EXTENSIONS
    assert FILTER_EXTS is domain_data_source.SUPPORTED_DATA_FILE_EXTENSIONS


def test_excel_filter_derives_from_domain_exts():
    from hwpxfiller.domain.data_source import SUPPORTED_DATA_FILE_EXTENSIONS
    from hwpxfiller.gui.file_filters import (
        EXCEL_FILTER,
        EXCEL_FILTER_PATTERN,
        HWPX_FILTER,
    )

    exts = SUPPORTED_DATA_FILE_EXTENSIONS
    assert exts, "지원 확장자 단일 출처가 비어 있다"
    assert EXCEL_FILTER == "엑셀/CSV (" + " ".join(f"*{ext}" for ext in exts) + ")"
    assert EXCEL_FILTER_PATTERN == ";".join(f"*{ext}" for ext in exts)
    assert HWPX_FILTER == "HWPX (*.hwpx)"


def test_factory_accepts_exactly_the_public_exts(tmp_path):
    """source_for_path 의 판정도 같은 공개 튜플을 쓴다 — 필터와 실제 수용이 일치."""
    from hwpxfiller.domain.data_source import SUPPORTED_DATA_FILE_EXTENSIONS
    from hwpxfiller.data.factory import source_for_path

    for ext in SUPPORTED_DATA_FILE_EXTENSIONS:
        source_for_path(tmp_path / f"data{ext}")
    with pytest.raises(ValueError):
        source_for_path(tmp_path / "doc.hwp")  # 목록 밖 확장자는 시끄럽게 거부


def test_no_hardcoded_file_dialog_filter_literals():
    """재유입 grep 게이트 — 필터 리터럴은 단일 출처 한 지점에서만 정의된다."""
    pattern = _filter_literal_pattern()
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not pattern.search(line):
                continue
            if rel == "hwpxfiller/gui/file_filters.py":
                continue  # 단일 출처(파생 정의)
            offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "파일 다이얼로그 필터 리터럴 하드코딩 재유입(RC-34) — "
        "gui/file_filters.py 의 상수를 참조하라:\n" + "\n".join(offenders)
    )
