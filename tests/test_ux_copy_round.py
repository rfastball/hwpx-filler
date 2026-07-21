"""R-copy 라운드(101 순회 로드맵 5) 금지어 가드 — 개발 어휘의 UI 재유입을 CI 에서 차단.

원장: docs/UX_FINDINGS_101_WALKTHROUGH.md (F1·F3·F4·F15·F17·F25·F31·F35).
전면 카피 레이어는 기각(마크업 간접화 비용 > 이득) — 대신 ①두 곳 이상 쓰이는 문자열만
web/js/copy.js 로 승격하고 ②이 모듈이 **주석을 걷어낸 사용자 표면**(index.html 텍스트,
JS 템플릿/문자열)에서 개발 어휘·이슈번호를 탐지한다. 어휘 결정의 정본은 원장 F4/F15.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
WEB_INDEX = WEB / "index.html"
JS_FILES = sorted((WEB / "js").rglob("*.js"))
WEBAPP = ROOT / "src" / "hwpxfiller" / "webapp"
GUI = ROOT / "src" / "hwpxfiller" / "gui"

# 웹 화면이 소비하는 Python 사용자 메시지 공급원(PR #85 리뷰) — webapp 컨트롤러 + 링1 VM.
# 제외: nara_state(동결·웹 미노출)·pipeline_builder_state(파킹, F40) — 동결 표면의 문구
# 수선은 동결 해제에 묶는다(nara-freeze 결정).
_PY_EXCLUDE = {"nara_state.py", "pipeline_builder_state.py"}
PY_MESSAGE_SOURCES = sorted(WEBAPP.glob("*.py")) + sorted(
    p for p in GUI.glob("*.py") if p.name not in _PY_EXCLUDE
)

# 금지어(개발 어휘) → 사용자 어휘 정본. 코드 식별자와 충돌하지 않는 한국어/누출 형태만 담는다
# (예: 영어 "records" 는 스냅샷 키라 금지 불가 — 한국어 "레코드" 만 금지).
BANNED = {
    "투트랙": "삭제(F1) — 개발결정 용어(ADR I)",
    "두 트랙": "삭제(F1) — 개발결정 용어(ADR I)",
    "정식 문서 생성": "「HWPX 문서 만들기」(F4 확정)",
    "즉시 기안": "「기안문 채우기」(F4 확정)",
    "겨눠": "「골라/선택해」(F15)",
    "겨눔": "「선택」(F15)",
    "스키마온리": "「데이터 없음(템플릿 필드만)」(F15)",
    "레코드": "「행」(R-copy 결정 — 엑셀 사용자 어휘)",
    "view가": "「미리보기가」(F35)",
    "(commit": "삭제(F35) — 복사 버튼/안내문",
    "commit —": "「복사하면 완료 —」(F35)",
}


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    """블록 주석 전부 + 공백이 선행하는 줄끝 // 주석 제거 — 남는 본문은 코드·문자열.

    문자열 안의 ``//`` 오탐 위험은 '공백+//' 요구로 낮춘다(현 코드베이스의 인라인 주석은
    전부 ``  // `` 형태, URL 은 주석에만 등장). 주석은 개발자 대상이라 금지 대상이 아니다.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", text)


def _surfaces() -> "list[tuple[str, str]]":
    out = [("web/index.html", _strip_html_comments(WEB_INDEX.read_text(encoding="utf-8")))]
    for p in JS_FILES:
        out.append((str(p.relative_to(ROOT)), _strip_js_comments(p.read_text(encoding="utf-8"))))
    return out


def test_web_surfaces_free_of_banned_dev_vocabulary():
    """주석 제거 후 웹 표면에 금지어(개발 어휘)가 없어야 한다 — 어휘 드리프트 CI 차단."""
    offenders = []
    for name, body in _surfaces():
        for term, fix in BANNED.items():
            if term in body:
                offenders.append(f"{name}: '{term}' → {fix}")
    assert not offenders, "개발 어휘가 UI 표면에 재유입됐습니다:\n" + "\n".join(offenders)


def test_web_surfaces_free_of_issue_numbers():
    """UI 문자열에 이슈번호('(#53-A)' 류)가 노출되면 안 된다 — F25 최악 표본의 재발 차단.

    주석 제거 후 남는 ``(#숫자`` 는 문자열 리터럴뿐이다(코드 구문상 등장 불가).
    """
    offenders = []
    for name, body in _surfaces():
        for m in re.finditer(r"\(#\d+[^)]*\)?", body):
            offenders.append(f"{name}: {m.group(0)}")
    assert not offenders, "이슈번호가 UI 표면에 노출됩니다(F25):\n" + "\n".join(offenders)


def test_txt_note_single_source_in_copy_js():
    """txt 기본 안내문은 copy.js 단일 출처여야 한다 — index.html/txt.js 두 벌 중복(실측된
    드리프트 위험)의 재발 차단. 정적 #txtNote 는 비워 두고 txt.js 가 Copy.TXT_NOTE 로 채운다."""
    index = WEB_INDEX.read_text(encoding="utf-8")
    m = re.search(r'<p class="note" id="txtNote">([^<]*)</p>', index)
    assert m is not None, "txtNote 요소가 사라졌습니다."
    assert m.group(1).strip() == "", (
        "index.html #txtNote 에 정적 문구가 다시 들어왔습니다 — copy.js(Copy.TXT_NOTE) 단일 출처 위반."
    )
    assert 'src="js/copy.js"' in index, "copy.js 가 index.html 에 로드되지 않았습니다."
    copy_js = (WEB / "js" / "copy.js").read_text(encoding="utf-8")
    assert "TXT_NOTE" in copy_js, "copy.js 에 TXT_NOTE 가 없습니다."
    # 안내문을 채우는 주체는 공용 기안 세션 팩토리(#148 슬라이스 3a) — 두 화면 한 출처.
    sess_js = (WEB / "js" / "draftsession.js").read_text(encoding="utf-8")
    assert "Copy.TXT_NOTE" in sess_js, (
        "draftsession.js 가 Copy.TXT_NOTE 를 쓰지 않습니다(중복 재도입 위험)."
    )


# Python 문자열용 금지어 — 한국어 사용자 어휘만(영문 형태는 코드 식별자와 충돌 위험).
_PY_BANNED = [t for t in BANNED if not t.startswith("(") and "commit" not in t]


def _user_string_literals(path: Path) -> "list[tuple[int, str]]":
    """모듈의 문자열 상수 중 독스트링을 뺀 것 — 주석은 AST 에 없어 자동 제외.

    독스트링(모듈/클래스/함수 본문 첫 문장)은 개발자 대상이라 금지 대상이 아니다.
    f-string 조각(JoinedStr 내부 Constant)도 걷힌다 — 사용자 메시지의 실제 표면.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_pos = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_pos.add((body[0].value.lineno, body[0].value.col_offset))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (node.lineno, node.col_offset) in doc_pos:
                continue
            out.append((node.lineno, node.value))
    return out


def test_backend_user_strings_free_of_banned_vocabulary():
    """웹이 소비하는 Python 사용자 문자열(webapp + 링1 VM)에 금지어가 없어야 한다.

    PR #85 리뷰: 종전 가드는 webapp 의 두 정확 문구만 봐서, 실행 화면 gate.text 로
    그대로 흐르는 gui/run_state 메시지('레코드 1건만…')와 template.js confirm 으로
    흐르는 '즉시 기안' 잔재를 놓쳤다 — 공급원 전체를 AST 문자열 수준으로 스캔한다.
    """
    offenders = []
    for p in PY_MESSAGE_SOURCES:
        for lineno, s in _user_string_literals(p):
            for term in _PY_BANNED:
                if term in s:
                    offenders.append(f"{p.name}:{lineno}: '{term}' in {s!r} → {BANNED[term]}")
    assert not offenders, "Python 사용자 문자열에 금지어 잔존:\n" + "\n".join(offenders)


def test_backend_user_strings_free_of_log_vocabulary():
    """웹앱 컨트롤러 사용자 문구의 로그 어휘 잔재 — F17('편집 모드로 열었습니다 — 매핑 N행
    복원')·'레코드 0건' 형태가 문자열로 되살아나면 실패한다(빈 데이터 문구는 NO_ROWS_TEXT
    단일 출처)."""
    for p in sorted(WEBAPP.glob("*.py")):
        src = p.read_text(encoding="utf-8")
        # 독스트링·주석은 개발자 대상이라 대상 밖 — 사용자 문구 리터럴 형태만 잡는다.
        assert "레코드 0건 —" not in src, f"{p.name}: '레코드 0건 —' — screens.NO_ROWS_TEXT 를 쓰세요."
        assert "편집 모드로 열었습니다" not in src, f"{p.name}: F17 로그 어휘 문구 재유입."
