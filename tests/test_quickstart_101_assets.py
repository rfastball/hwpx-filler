"""101 학습 세트 정합 가드(#262) — 자산·문서·앱 계약이 어긋나면 여기서 잡힌다.

학습 세트의 핵심 계약: **템플릿 필드명 = CSV 한글 헤더 정확 일치**(직접 매칭으로
자동 제안이 뜨는 101 경험의 전제), **정상 경로 경고 0**(의도하지 않은 경고 없음),
**오류 학습 자산은 정상 자산과 파일 수준 분리**(의도적 미치환 토큰). 자산은
바이너리라 조용히 썩는다 — 커밋된 실물을 앱과 같은 코어 API 로 되읽어 비준한다.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from hwpxfiller.core.fields import read_fields
from hwpxfiller.core.lint import lint_template
from hwpxfiller.core.text_render import template_fields

Q101 = Path(__file__).resolve().parents[1] / "examples" / "quickstart-101"

FIELDS = ["공고번호", "수요기관", "공고명", "추정가격", "납품기한", "담당자"]
PURCHASE_SUBSET = {"수요기관", "공고명", "추정가격", "담당자"}


def _csv_rows(name: str) -> "tuple[list[str], list[dict[str, str]]]":
    raw = (Q101 / "data" / name).read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", f"{name}: utf-8-sig(BOM) 이어야 Excel 왕복이 안전하다"
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def test_csv_headers_match_template_fields_exactly() -> None:
    """두 CSV 모두 헤더 = 템플릿 필드명(순서 포함) — 직접 매칭 자동 제안의 전제."""
    for name in ("발주목록.csv", "발주목록_2.csv"):
        headers, _rows = _csv_rows(name)
        assert headers == FIELDS, f"{name} 헤더 드리프트: {headers}"


def test_csv_normal_path_has_no_blank_values() -> None:
    """정상 학습 경로에 빈값 없음 — 의도하지 않은 미입력 확인 게이트가 뜨면 안 된다."""
    for name in ("발주목록.csv", "발주목록_2.csv"):
        _headers, rows = _csv_rows(name)
        assert rows, f"{name}: 데이터 0건"
        for i, row in enumerate(rows):
            blanks = [k for k, v in row.items() if not (v or "").strip()]
            assert not blanks, f"{name} {i + 1}행 빈값: {blanks}"


def test_hwpx_templates_fields_and_lint() -> None:
    """커밋된 hwpx 실물 되읽기: 발주요청서=6필드 전량, 구매요청서=4필드 부분집합, lint 무경고."""
    bid = read_fields(str(Q101 / "templates" / "발주요청서.hwpx"))
    assert sorted(bid) == sorted(FIELDS), f"발주요청서 필드 드리프트: {sorted(bid)}"
    purchase = read_fields(str(Q101 / "templates" / "구매요청서.hwpx"))
    assert set(purchase) == PURCHASE_SUBSET, f"구매요청서 필드 드리프트: {sorted(purchase)}"
    for name in ("발주요청서.hwpx", "구매요청서.hwpx"):
        report = lint_template(str(Q101 / "templates" / name))
        assert not report.has_issues, f"{name} lint 경고: {[f.message for f in report.findings]}"


def test_normal_draft_tokens_all_resolvable() -> None:
    """정상 기안 초안의 토큰 전부가 CSV 헤더에 있다 — 트랙 B 정상 경로 미치환 0."""
    text = (Q101 / "text_templates" / "발주요청_기안.txt").read_text(encoding="utf-8")
    tokens = set(template_fields(text))
    assert tokens, "정상 초안에 토큰이 없다"
    assert tokens <= set(FIELDS), f"CSV 에 없는 토큰: {sorted(tokens - set(FIELDS))}"


def test_error_practice_draft_is_separate_and_intentional() -> None:
    """오류 학습 자산: 파일 수준 분리(이름으로 식별) + 의도적 미치환 토큰을 정확히 담는다."""
    path = Q101 / "text_templates" / "오류연습_미치환.txt"
    text = path.read_text(encoding="utf-8")
    tokens = set(template_fields(text))
    unresolved = tokens - set(FIELDS)
    assert unresolved == {"담당연락처"}, f"의도적 미치환 토큰 드리프트: {sorted(unresolved)}"
    # 본문이 스스로 목적을 설명한다(자족형 — 문서 없이 열어도 오해하지 않게).
    assert "연습" in text and "발주요청_기안" in text


def test_no_orphan_asset_dirs() -> None:
    """계약 밖 자산 디렉터리 재유입 차단 — text_data/ 는 고아 자산이라 삭제됐다(#262)."""
    assert not (Q101 / "text_data").exists(), "text_data/ 는 앱이 읽지 않는 고아 자산이다"


def test_launcher_and_reset_cover_generated_state() -> None:
    """reset 스크립트가 .gitignore 의 생성물 목록을 전부 다루고, 예제 자산은 건드리지 않는다."""
    reset = (Q101 / "reset-101.cmd").read_text(encoding="utf-8")
    ignored = (Q101 / ".gitignore").read_text(encoding="utf-8")
    for state in ("jobs", "datasets", "mapping_bases", "webview", "out", "ui_settings.ini", "settings.json"):
        assert state in ignored, f".gitignore 에 {state} 누락"
        assert state in reset, f"reset-101.cmd 가 {state} 를 안 지운다"
    for asset in ("templates", "text_templates", "data", "make_template.py", "start-101.cmd"):
        assert f'rd /s /q "{asset}"' not in reset, f"reset 이 예제 자산 {asset} 을 지운다"


def test_make_template_source_of_truth_matches_committed_csv() -> None:
    """make_template.py 의 FIELDS/RECORDS(진실원)와 커밋된 CSV 가 일치한다(같은 입력=같은 자산)."""
    src = (Q101 / "make_template.py").read_text(encoding="utf-8")
    for field_name in FIELDS:
        assert f'"{field_name}"' in src
    headers, rows = _csv_rows("발주목록.csv")
    for row in rows:
        assert row["공고번호"] in src, f"커밋 CSV 의 {row['공고번호']} 가 진실원에 없다"
