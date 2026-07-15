"""파일 다이얼로그 필터 단일 출처(RC-34) — 파생 검증 + 하드코딩 재유입 grep 게이트.

지원 확장자의 실질 단일 출처는 data/factory.py(``EXCEL_EXTS``)다. hwpxfiller 의
필터는 gui/file_filters.py 가 거기서 파생하고, hwpxdiff 웹앱은 제품 간 임포트 금지
규칙 때문에 자체 필터(``HWPX_FILTERS`` 튜플)를 소유한다 — 그 두 지점 밖의 필터 리터럴
하드코딩은 확장자 정책 변경 시 화면별 드리프트로 이어진다(재유입 금지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _filter_literal_pattern() -> "re.Pattern[str]":
    """단일 출처가 존재하는 확장자(EXCEL_EXTS + hwpx)의 필터 리터럴 시그니처.

    "이름 (*.ext …)" 의 "(*.ext" 부분만 겨눈다 — 단일 출처가 없는 일회성 필터
    (txt 저장·매핑 json 등)는 RC-34 스코프 밖이라 게이트하지 않는다.
    EXCEL_EXTS 에서 파생하므로 확장자가 늘어나면 게이트도 자동으로 따라온다.
    """
    from hwpxfiller.data.factory import EXCEL_EXTS

    exts = [ext.lstrip(".") for ext in EXCEL_EXTS] + ["hwpx"]
    return re.compile(r"\(\*\.(?:" + "|".join(map(re.escape, exts)) + r")\b")


def test_excel_filter_derives_from_factory_exts():
    from hwpxfiller.data.factory import EXCEL_EXTS
    from hwpxfiller.gui.file_filters import EXCEL_FILTER, HWPX_FILTER

    assert EXCEL_EXTS, "지원 확장자 단일 출처가 비어 있다"
    for ext in EXCEL_EXTS:
        assert f"*{ext}" in EXCEL_FILTER  # 확장자 추가가 필터에 자동 반영
    assert EXCEL_FILTER.count("*.") == len(EXCEL_EXTS)  # 파생 외 잔여 리터럴 없음
    assert HWPX_FILTER == "HWPX (*.hwpx)"


def test_factory_accepts_exactly_the_public_exts(tmp_path):
    """source_for_path 의 판정도 같은 공개 튜플을 쓴다 — 필터와 실제 수용이 일치."""
    from hwpxfiller.data.factory import EXCEL_EXTS, source_for_path

    with pytest.raises(ValueError):
        source_for_path(tmp_path / "doc.hwp")  # 목록 밖 확장자는 시끄럽게 거부
    assert ".xlsx" in EXCEL_EXTS and ".csv" in EXCEL_EXTS


def test_hwpxdiff_owns_equivalent_hwpx_filter():
    """hwpxdiff 웹앱 자체 필터(제품 간 임포트 금지)가 hwpxfiller hwpx 필터와 확장자에서 일치.

    표현형은 다르다 — filler 는 Qt-free 상수 ``HWPX_FILTER`` ("HWPX (*.hwpx)"), diff 웹앱은
    comdlg32 용 (레이블, 패턴) 튜플 목록 — 그러나 같은 ``*.hwpx`` 확장자를 공유해야 한다.
    """
    from hwpxdiff.webapp.app import HWPX_FILTERS
    from hwpxfiller.gui.file_filters import HWPX_FILTER

    assert ("HWPX", "*.hwpx") in HWPX_FILTERS
    assert "*.hwpx" in HWPX_FILTER


def test_no_hardcoded_file_dialog_filter_literals():
    """재유입 grep 게이트 — 필터 리터럴은 단일 출처 두 지점에서만 정의된다."""
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
        "gui/file_filters.py(hwpxfiller) 또는 HWPX_FILTER(hwpxdiff) 상수를 참조하라:\n"
        + "\n".join(offenders)
    )
