"""101 학습 세트 정합 가드(#262) — 자산·문서·앱 계약이 어긋나면 여기서 잡힌다.

학습 세트의 핵심 계약: **템플릿 필드명 = CSV 한글 헤더 정확 일치**(직접 매칭으로
자동 제안이 뜨는 101 경험의 전제), **정상 경로 경고 0**(의도하지 않은 경고 없음),
**오류 학습 자산은 정상 자산과 파일 수준 분리**(의도적 미치환 토큰). 자산은
바이너리라 조용히 썩는다 — 커밋된 실물을 앱과 같은 코어 API 로 되읽어 비준한다.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import re
from pathlib import Path

from _web_source import REPO_ROOT, SOURCE_ROOT

from hwpxfiller.core.fields import read_fields
from hwpxfiller.core.lint import lint_template
from hwpxfiller.core.text_render import template_fields

Q101 = REPO_ROOT / "examples" / "quickstart-101"

FIELDS = ["공고번호", "수요기관", "공고명", "추정가격", "납품기한", "담당자"]
PURCHASE_SUBSET = {"수요기관", "공고명", "추정가격", "담당자"}

#: 101·102 문안이 화면을 지목하는 두 문서. 하나만 보면 서로 어긋난 채 각자 초록이다.
GUIDE_DOCS = ("README.md", "PATTERNS.md")

#: 판정으로 죽은 표면·결속을 가리키는 어휘. 실물에 없다는 것은 코드가 증명할 수 없다
#: (죽은 이름은 주석·이력에 남으므로 substring 탐색으로는 생사가 안 갈린다) — 그래서
#: 이 목록만은 손으로 적힌 판정이고, 지키는 것은 **재유입 차단** 하나다.
RETIRED_VOCABULARY = {
    "왼쪽 목록": "좌 master 작업 목록은 F2 PR-B 에서 사망 — 후보 카드·문서 탐색 면이 승계",
    "기본 데이터": "작업↔데이터 결속(default_dataset_ref)은 #347 에서 폐기",
    "기안 화면": "별도 기안 화면은 없다 — TXT 작업 저장 → 검토·복사 작업대",
    "데이터 함께 등록": "작업 저장은 데이터를 등록하지도 묶지도 않는다",
    "템플릿 관리": "scr-tpl 은 F8 에서 사망 — 승계처는 편집기 「템플릿」 자리",
}


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
    # 목록의 단일 출처는 "앱이 HWPXFILLER_HOME 밑에 쓰는 것 전수"(home_dir() 소비처 sweep):
    # jobs/·datasets/·templates/(자산이라 불가침)·text_templates/(자산)·webview/·settings.json·
    # ui_settings.ini·mapping_bases/·webapp-alerts.log(settings.alert 내구 채널 — Codex P2).
    for state in ("jobs", "datasets", "mapping_bases", "webview", "out",
                  "ui_settings.ini", "settings.json", "webapp-alerts.log"):
        assert state in ignored, f".gitignore 에 {state} 누락"
        assert state in reset, f"reset-101.cmd 가 {state} 를 안 지운다"
    # Results/ 는 .gitignore 상 임의 깊이 생성물 — 실습에서 나오는 두 위치(루트·templates 밑)를
    # 삭제 루프가 정확히 다룬다(substring 포함만으론 templates\Results 가 루트 몫을 가린다 — Codex P2).
    assert "in (jobs datasets mapping_bases webview out Results)" in reset, "루트 Results 미삭제"
    assert r'rd /s /q "templates\Results"' in reset
    for asset in ("templates", "text_templates", "data", "make_template.py", "start-101.cmd"):
        assert f'rd /s /q "{asset}"' not in reset, f"reset 이 예제 자산 {asset} 을 지운다"


def test_readme_screenshots_exist_one_to_one() -> None:
    """README 가 참조하는 스크린샷 = img/ 실물 (양방향 1:1) — 죽은 링크도 고아 컷도 없다.

    스크린샷은 capture_101_screenshots.py 전량 재생성이라, 참조·실물이 어긋나면
    캡처 대본과 문서 중 하나가 뒤처진 것이다(둘 다 같은 커밋에서 갱신돼야 한다).
    """
    import re

    readme = (Q101 / "README.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"img/(\d{2}-[a-z-]+\.png)", readme))
    files = {p.name for p in (Q101 / "img").glob("*.png")}
    assert refs, "README 에 스크린샷 참조가 없다"
    assert refs == files, (
        f"참조-실물 어긋남 — README에만: {sorted(refs - files)}, img/에만: {sorted(files - refs)}"
    )


def _app_label_haystack() -> str:
    """라벨이 실제로 사는 곳 전부 — 웹 표면(정적·동적)과 링1·링2 문안 소유자.

    source tree 의 물리 이름은 ``_web_source`` 가 단독 소유한다(``test_web_source_role``):
    여기서 다시 조립하면 중앙 컷오버 뒤에도 이 게이트만 옛 사본을 읽고 초록일 수 있다.
    """
    sources = [
        *sorted(SOURCE_ROOT.rglob("*.js")),
        *sorted(SOURCE_ROOT.rglob("*.ts")),
        *sorted(SOURCE_ROOT.rglob("*.html")),
        *sorted((REPO_ROOT / "src" / "hwpxfiller" / "gui").rglob("*.py")),
        *sorted((REPO_ROOT / "src" / "hwpxfiller" / "webapp").rglob("*.py")),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in sources)


def _doc_button_tokens(text: str) -> "set[str]":
    """문서가 **[…]** 로 지목한 버튼 이름. 글리프와 라이브 수치는 벗긴다.

    문서는 라벨을 화면에 뜬 그대로 인용한다 — 수치가 붙는 라벨(「검토·복사 시작 · 3건」)
    이나 자리표시자를 낀 라벨(「비우고 진행 확인 (N개 토큰)」)은 그 접미까지 함께 온다.
    벗기는 것은 **합성분뿐**이고 이름 본체는 손대지 않는다.
    """
    tokens: set[str] = set()
    for raw in re.findall(r"\*\*\[([^\]\n]+)\]\*\*", text):
        name = raw
        for glyph in ("…", "▶", "◀", "⤢", "←", "＋"):
            name = name.replace(glyph, "")
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name)   # (N개 토큰)
        name = re.sub(r"\s*·[^·]*$", "", name) if " · " in name else name  # · 3건
        name = name.strip()
        if name:
            tokens.add(name)
    return tokens


def test_guide_docs_quote_button_names_that_exist_in_the_app() -> None:
    """문서가 지목하는 버튼 이름이 앱 소스에 실제로 있다 — 지어낸 라벨·개명 드리프트 차단.

    **이 단언은 하한이고, 그 하한이 실제로 새는 것을 봤다**(#434 리뷰 4R). 두 겹이다:
    ① 주석·이력에만 남은 죽은 이름이 통과한다 ② **부분문자열**이라 다른 라벨 안에 든
    이름도 통과한다 — 렌더되지 않는 `[작업 만들기]` 가 `job.js` 의 「이 데이터로 새 작업
    만들기」에 얹혀 초록이었다. 건초더미를 렌더 표면으로 좁혀도 ②는 안 닫힌다(실측).
    제대로 닫으려면 라벨 **전체 일치**로 바꿔야 하는데, 그건 프론트 결합을 끊을 때 손댈
    자리다. 그때까지 이 게이트가 지키는 것은 **지어낸 이름**이고, 사망 표면은
    RETIRED_VOCABULARY 가 진다. allowlist 가 0이라 개명은 예외 없이 걸린다.
    """
    haystack = _app_label_haystack()
    offenders: list[str] = []
    for name in GUIDE_DOCS:
        text = (Q101 / name).read_text(encoding="utf-8")
        tokens = _doc_button_tokens(text)
        assert tokens, f"{name}: 버튼 인용이 하나도 없다 — 추출기가 죽었을 수 있다"
        offenders.extend(f"{name}: [{t}]" for t in sorted(tokens) if t not in haystack)

    assert not offenders, (
        "문서가 앱에 없는 버튼 이름을 지목합니다(개명했거나 지어냈습니다):\n"
        + "\n".join(offenders)
    )


def test_guide_docs_do_not_resurrect_retired_surfaces() -> None:
    """사망 판정이 난 표면·결속의 어휘가 문서로 되돌아오지 않는다."""
    offenders: list[str] = []
    for name in GUIDE_DOCS:
        text = (Q101 / name).read_text(encoding="utf-8")
        offenders.extend(
            f"{name}: 「{term}」 — {why}"
            for term, why in RETIRED_VOCABULARY.items()
            if term in text
        )

    assert not offenders, "문서가 죽은 표면을 현재형으로 서술합니다:\n" + "\n".join(offenders)


def test_guide_docs_field_enumerations_match_a_real_template() -> None:
    """문서가 세는 「N필드(a·b·c)」가 커밋된 템플릿의 실제 필드 집합과 일치한다.

    102 가 부분집합 템플릿을 「4필드(…품명…)」로 적어 둔 적이 있다 — 실물엔 없는 열이라
    독자가 CSV 에서 그 이름을 찾다 못 찾는다. 개수와 이름을 **둘 다** 실물에서 재읽어 센다.
    """
    known = {
        frozenset(read_fields(str(Q101 / "templates" / "발주요청서.hwpx"))),
        frozenset(read_fields(str(Q101 / "templates" / "구매요청서.hwpx"))),
    }
    seen = 0
    offenders: list[str] = []
    for name in GUIDE_DOCS:
        text = (Q101 / name).read_text(encoding="utf-8")
        for match in re.finditer(r"(\d+)\s*필드\s*\(([^)]*)\)", text):
            listed = [p.strip() for p in re.split(r"[·,]", match.group(2)) if p.strip()]
            seen += 1
            if len(listed) != int(match.group(1)) or frozenset(listed) not in known:
                offenders.append(f"{name}: {match.group(0)}")

    assert seen, "문서에 필드 열거가 없다 — 추출기가 죽었을 수 있다"
    assert not offenders, (
        "문서의 필드 열거가 커밋된 템플릿과 다릅니다:\n" + "\n".join(offenders)
    )


def test_make_template_source_of_truth_matches_committed_csv() -> None:
    """진실원(RECORDS/RECORDS_2)에서 CSV 를 재생성해 커밋 실물과 바이트 대조.

    substring 표본 검사는 판별력이 없다(값 하나 바꿔도 통과 — Codex 3라운드) —
    make_template.write_csv 와 같은 직렬화로 두 파일 전행·전열을 재현해 비교한다.
    줄끝만 정규화(체크아웃 CRLF 속성 비의존).
    """
    spec = importlib.util.spec_from_file_location("q101_make_template", Q101 / "make_template.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.FIELDS == FIELDS, "진실원 FIELDS 드리프트"
    for name, records in (("발주목록.csv", mod.RECORDS), ("발주목록_2.csv", mod.RECORDS_2)):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=mod.FIELDS, lineterminator="\n")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
        expected = buf.getvalue().encode("utf-8-sig")
        committed = (Q101 / "data" / name).read_bytes().replace(b"\r\n", b"\n")
        assert committed == expected, f"{name} 가 진실원과 다르다 — make_template.py 재실행 필요"
