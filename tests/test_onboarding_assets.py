"""온보딩 예제 자산 계약 — `docs/ONBOARDING_TUTORIAL.md` §2 의 검사 가능한 얼굴.

지키는 것은 다섯이다.

1. **재생성 결정론** — `examples/onboarding/make_assets.py` 를 임시 폴더에 다시 돌리면
   커밋된 자산과 **bytes 가 같다**. 손편집이 끼면 여기서 갈라진다.
2. **CSV 스키마** — 헤더 8열이 §2.3 표와 정확히 일치하고(헤더 = 필드명 일치가 자동
   제안의 조건), 행 수와 **의도 결측의 자리**(계약목록_2 둘째 행의 `납품기한` 만 빈
   값)가 선언대로다.
3. **누름틀 필드 집합** — 컴파일된 두 템플릿의 필드가 스펙과 정확 일치(7/5).
4. **미컴파일 연습본** — `공고서_연습` 은 필드 토큰과 구간 표기를 **둘 다** 들고 있고,
   두 축 컴파일(필드 먼저·구간 다음)이 차단 사유 없이 성립한다. 이것이 고급·심화
   티어(T15·T17)의 재료가 실제로 서 있다는 증거다.
5. **허구화 규칙(§2.1)** — 원형 실문서의 식별 가능한 값이 자산 어디에도 없다.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from hwpxfiller.domain.authoring import scan_structure
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
from hwpxfiller.external.template_inspection import (
    compile_structure_file,
    compile_template_file,
    inspect_hwpx_template,
    scan_template_tokens,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "examples" / "onboarding"
SCRIPT = ASSETS / "make_assets.py"

#: §2.3 의 CSV 열 8개 — 순서까지 계약이다.
HEADER = [
    "공고번호",
    "수요기관",
    "품명",
    "사업명",
    "계약방법",
    "계약상대자",
    "계약금액",
    "납품기한",
]

#: 자산 census — 생성 스크립트가 낳는 파일 전부(결정론 비교의 대상 집합).
GENERATED = (
    "templates/계약체결안내.hwpx",
    "templates/구매추진안내.hwpx",
    "templates/공고서_연습.hwpx",
    "text_templates/계약안내_기안.txt",
    "text_templates/오류연습_보증금.txt",
    "data/계약목록.csv",
    "data/계약목록_2.csv",
)

CONTRACT_FIELDS = {
    "공고번호",
    "수요기관",
    "품명",
    "사업명",
    "계약상대자",
    "계약금액",
    "납품기한",
}
PURCHASE_FIELDS = {"공고번호", "수요기관", "품명", "계약방법", "납품기한"}
NOTICE_TOKENS = {"공고번호", "수요기관", "품명", "계약방법", "납품기한"}

#: §2.1 금지 목록의 대표 문자열 — 실기관·실업체·실인명·실번호·실연락처.
FORBIDDEN = (
    "조달청",
    "대전지방조달청",
    "나라장터",
    "루나이엔씨",
    "루나이앤씨",
    "육군군수사령부",
    "경제인문사회연구회",
    "방위사업청",
    "안준명",
    "황민오",
    "이순주",
    "조다래",
    "김성우",
    "korea.kr",
    "R26BK01666828",
    "25224100200",
)


def _load_script():
    """`make_assets.py` 를 경로로 적재한다(examples/ 는 패키지가 아니다)."""
    spec = importlib.util.spec_from_file_location("onboarding_make_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_csv(path: Path) -> "tuple[list[str], list[list[str]]]":
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def _asset_texts() -> "dict[str, str]":
    """자산의 사람이 읽는 내용 전부 — hwpx 는 ZIP 엔트리를 전부 펼쳐 본다."""
    texts: dict[str, str] = {}
    for name in GENERATED:
        path = ASSETS / name
        if path.suffix == ".hwpx":
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    blob = archive.read(entry)
                    texts[f"{name}!{entry}"] = blob.decode("utf-8", "ignore")
        else:
            texts[name] = path.read_text(encoding="utf-8-sig")
    texts["make_assets.py"] = SCRIPT.read_text(encoding="utf-8")
    return texts


# ------------------------------------------------------------------ 1. 결정론
def test_regeneration_reproduces_committed_bytes(tmp_path: Path) -> None:
    """임시 폴더 재생성 = 커밋 자산 bytes 동일 — 손편집이 끼면 여기서 갈라진다."""
    _load_script().main(tmp_path)

    regenerated = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()
    )
    assert regenerated == sorted(GENERATED)

    for name in GENERATED:
        committed = (ASSETS / name).read_bytes()
        fresh = (tmp_path / name).read_bytes()
        assert hashlib.sha256(fresh).hexdigest() == hashlib.sha256(committed).hexdigest(), (
            f"{name}: 재생성 산출이 커밋 자산과 다르다 — 손편집이거나 스크립트가 비결정적이다"
        )


# ------------------------------------------------------------------ 2. CSV 스키마
@pytest.mark.parametrize(("name", "rows_n"), [("계약목록.csv", 3), ("계약목록_2.csv", 2)])
def test_csv_header_matches_field_names(name: str, rows_n: int) -> None:
    """헤더 8열 정확 일치(순서 포함) + 행 수 — 자동 제안이 서는 조건."""
    header, rows = _read_csv(ASSETS / "data" / name)
    assert header == HEADER
    assert len(rows) == rows_n
    assert all(len(row) == len(HEADER) for row in rows)


def test_only_the_declared_cell_is_missing() -> None:
    """결측은 한 자리뿐 — 계약목록_2 둘째 행의 `납품기한`(§2.2 데이터측 결핍)."""
    _, primary = _read_csv(ASSETS / "data" / "계약목록.csv")
    assert all(cell.strip() for row in primary for cell in row), "계약목록.csv 에는 결측이 없다"

    _, second = _read_csv(ASSETS / "data" / "계약목록_2.csv")
    blanks = {
        (index, HEADER[column])
        for index, row in enumerate(second)
        for column, cell in enumerate(row)
        if not cell.strip()
    }
    assert blanks == {(1, "납품기한")}


# ------------------------------------------------------------------ 3. 누름틀 필드
@pytest.mark.parametrize(
    ("name", "fields"),
    [("계약체결안내.hwpx", CONTRACT_FIELDS), ("구매추진안내.hwpx", PURCHASE_FIELDS)],
)
def test_compiled_templates_carry_the_declared_fields(name: str, fields: "set[str]") -> None:
    """컴파일된 두 템플릿의 필드 집합이 스펙과 정확 일치하고 CSV 열의 부분집합이다."""
    inspection = inspect_hwpx_template(str(ASSETS / "templates" / name))
    assert set(inspection.fields) == fields
    assert fields <= set(HEADER)
    assert inspection.status.stray_n == 0
    assert inspection.status.structure_marker_n == 0


# ------------------------------------------------- 4. 미컴파일 연습본(고급·심화 재료)
def test_practice_notice_reports_tokens_and_regions() -> None:
    """스캔이 미해결 필드 토큰과 구간 표기를 **둘 다** 보고한다(항목 1 · 그 안의 갈래 2).

    갈래를 둘 둔 것은 선택 정책이 Slot 당 `EXACTLY_ONE` 이기 때문이다 — 갈래 없는
    항목은 「고를 수 있는 것이 없는 항목」이라 넣고 빼는 연습이 서지 않는다.
    """
    path = ASSETS / "templates" / "공고서_연습.hwpx"

    assert {site.name for site in scan_template_tokens(str(path))} == NOTICE_TOKENS

    scan = scan_structure(read_hwpx_package(path))
    assert scan.diagnostics == ()
    assert (scan.summary.slots, scan.summary.options, scan.summary.fields) == (1, 2, 5)

    (slot,) = scan.slots
    assert slot.id == "현장설명회"
    assert [option.id for option in slot.options] == ["실시", "생략"]


def test_practice_notice_compiles_on_both_axes(tmp_path: Path) -> None:
    """필드 먼저 · 구간 다음의 두 축이 차단 사유 없이 성립한다(T15 의 재료)."""
    work = tmp_path / "공고서_연습.hwpx"
    shutil.copy(ASSETS / "templates" / "공고서_연습.hwpx", work)

    field_report = compile_template_file(str(work))
    assert field_report.modified is True
    assert field_report.skipped == []
    assert set(field_report.compiled) == NOTICE_TOKENS

    structure_report = compile_structure_file(str(work))
    assert structure_report.refusal is None
    assert structure_report.modified is True
    assert structure_report.options == 2

    assert scan_structure(read_hwpx_package(work)).summary.markers == 0


# ------------------------------------------------------------------ 5. 허구화 규칙
@pytest.mark.parametrize("needle", FORBIDDEN)
def test_no_real_world_identifier_survives_in_the_assets(needle: str) -> None:
    """원형 실문서의 식별 가능한 값이 자산 어디에도 없다(§2.1, 예외 없음)."""
    hits = [where for where, text in _asset_texts().items() if needle in text]
    assert hits == [], f"금지 문자열 「{needle}」 이 남아 있다: {hits}"
