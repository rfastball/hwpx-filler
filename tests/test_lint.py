"""템플릿 lint + 필드 드리프트 테스트."""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.lint import diff_schema, lint_template
from hwpxfiller.core.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
CORPUS = Path(__file__).parent / "corpus" / "real"


def _field_p(name: str) -> str:
    return (
        f'<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run></hp:p>'
    )


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _fields_pkg(*names: str) -> HwpxPackage:
    return _pkg("".join(_field_p(n) for n in names))


def _kinds(report) -> "list[str]":
    return [f.kind for f in report.findings]


# ------------------------------------------------------------- near-duplicate
def test_whitespace_variant_flagged():
    """공백만 다른 필드명은 near_duplicate 로 신고된다."""
    report = lint_template(_fields_pkg("계약명", "계약 명"))
    dups = [f for f in report.findings if f.kind == "near_duplicate"]
    assert len(dups) == 1
    assert set(dups[0].fields) == {"계약명", "계약 명"}
    assert report.has_issues


def test_substring_fields_not_flagged():
    """부분 문자열 관계(품명 vs 품명번호)는 별개 필드 — 오탐하지 않는다."""
    report = lint_template(_fields_pkg("세부품명", "세부품명번호"))
    assert "near_duplicate" not in _kinds(report)


# ----------------------------------------------------------------- 미치환 토큰
def test_stray_token_flagged():
    """평문 미치환 토큰은 stray_token(fieldize 권장)으로 신고된다."""
    inner = '<hp:p><hp:run><hp:t>{{미치환}}</hp:t></hp:run></hp:p>'
    report = lint_template(_pkg(inner))
    strays = [f for f in report.findings if f.kind == "stray_token"]
    assert len(strays) == 1 and strays[0].fields == ["미치환"]


def test_split_token_flagged():
    """파편에 걸친 토큰은 split_token 으로 신고된다."""
    inner = (
        "<hp:p>"
        "<hp:run><hp:t>{{계약</hp:t></hp:run>"
        "<hp:run><hp:t>명}}</hp:t></hp:run>"
        "</hp:p>"
    )
    report = lint_template(_pkg(inner))
    assert "split_token" in _kinds(report)


# --------------------------------------------------------------------- no_fields
def test_empty_template_flagged():
    inner = '<hp:p><hp:run><hp:t>필드 없는 문단</hp:t></hp:run></hp:p>'
    report = lint_template(_pkg(inner))
    assert "no_fields" in _kinds(report)


# ----------------------------------------------------------------- 어휘 준수
def test_off_vocabulary_with_nearest_hint():
    """어휘 사전을 주면 벗어난 필드명 + 가장 가까운 표준을 제안한다."""
    report = lint_template(
        _fields_pkg("계약명세"), vocabulary=["계약명", "사업예산"]
    )
    offv = [f for f in report.findings if f.kind == "off_vocabulary"]
    assert len(offv) == 1
    assert "계약명" in offv[0].message  # 가까운 표준 제안


def test_in_vocabulary_not_flagged():
    report = lint_template(_fields_pkg("계약명"), vocabulary=["계약명", "사업예산"])
    assert "off_vocabulary" not in _kinds(report)


# ------------------------------------------------------------------- 읽기 전용
def test_lint_is_readonly():
    pkg = _fields_pkg("계약명", "계약 명")
    before = pkg.entries["Contents/section0.xml"]
    lint_template(pkg)
    assert pkg.entries["Contents/section0.xml"] == before


# ------------------------------------------------------------- 실제 코퍼스 clean
def test_corpus_lints_clean():
    """실제 입찰공고 템플릿은 lint 이슈가 없다(오탐 없음 확인)."""
    report = lint_template(str(CORPUS / "bid_notice_limited_under100m.hwpx"))
    assert report.findings == []


# --------------------------------------------------------------- 필드 드리프트
def test_drift_added_and_removed():
    old = _fields_pkg("계약명", "사업예산")
    new = _fields_pkg("계약명", "공고명")
    drift = diff_schema(old, new)
    assert drift.added == ["공고명"]
    assert drift.removed == ["사업예산"]
    assert drift.renamed == []
    assert drift.has_changes


def test_drift_detects_rename():
    """공백만 바뀐 필드는 삭제+추가가 아니라 개명으로 추정된다."""
    old = _fields_pkg("공고명")
    new = _fields_pkg("공고 명")
    drift = diff_schema(old, new)
    assert drift.added == [] and drift.removed == []
    assert len(drift.renamed) == 1
    assert drift.renamed[0]["old"] == "공고명" and drift.renamed[0]["new"] == "공고 명"


def test_drift_no_changes():
    pkg = _fields_pkg("계약명", "사업예산")
    drift = diff_schema(pkg, _fields_pkg("계약명", "사업예산"))
    assert not drift.has_changes
