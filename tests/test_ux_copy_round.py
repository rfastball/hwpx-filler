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

from _web_source import REPO_ROOT, SOURCE_INDEX, SOURCE_JS_DIR

ROOT = REPO_ROOT
WEB_INDEX = SOURCE_INDEX
JS_FILES = sorted(SOURCE_JS_DIR.rglob("*.js"))
WEBAPP = REPO_ROOT / "src" / "hwpxfiller" / "webapp"
GUI = REPO_ROOT / "src" / "hwpxfiller" / "gui"

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
    # 죽은 표면을 가리키는 안내(F1 리뷰 P2) — 화면 사망은 **문안 빚**을 남긴다. 조치처가
    # 사라졌는데 문구만 남으면 사용자는 이행 불가능한 지시를 받는다(막다른길). 다음 화면
    # 사망(F2 home·F6 draft·F8 tpl)도 이 표에 한 줄 더해 같은 결함류를 CI 가 막게 한다.
    "데이터 관리": "「데이터 선택」의 「고정한 데이터」(F1 — 화면 사망, 없는 곳 지시 금지)",
    "템플릿 관리": "편집기 「템플릿」 탭(F8 — 화면 사망, 없는 곳 지시 금지)",
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


# (test_txt_note_single_source_in_copy_js 삭제 — 대상(#draftNote·draftsession.js)이
#  「기안」 화면과 함께 사망, F6 PR-B. copy.js 자체는 다른 공용 문안으로 생존 —
#  단일 출처 계약은 살아 있는 소비자가 생기면 그 표면의 테스트가 다시 진다.)
def test_copy_js_still_loaded():
    """공용 문안 모듈(copy.js)의 로드 배선은 「기안」 사망과 무관하게 산다."""
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert 'src="js/copy.js"' in index, "copy.js 가 index.html 에 로드되지 않았습니다."


def test_status_pill_calls_the_rule_axis_approval():
    """상단 상태 표지가 규칙축을 「승인」으로 부른다(U2 §2.10 · 리뷰 R1).

    어휘 분리(규칙축=「승인」, 필드축=「확인」)는 표지 `#jobReviewFlag` 와 게이트 문안만
    바꿨는데, **같은 화면의 상단 표지**는 막힌 이유와 무관하게 「확인 필요」였다. 첫 실행
    화면에서는 규칙축 승인이 유일한 미충족 게이트라 두 표지가 같은 행동을 두 이름으로 부르고,
    분리가 그 자리에서 무효가 된다 — 소명을 요구하지 않으려고 가른 어휘가 다시 소명을
    요구한다.

    판정은 링1 이 낸 `gate.reason` 하나로 한다(서열 재유도 금지) — 그래서 이 가드는 표지
    문안과 그 근거가 **같은 자리**에 있는지를 본다.
    """
    body = _strip_js_comments(
        (SOURCE_JS_DIR / "screens" / "job.js").read_text(encoding="utf-8")
    )
    status = re.search(r"function renderStatus\(s\) \{.*?\n  \}", body, re.S)
    assert status, "renderStatus 를 찾지 못했습니다 — 가드가 겨눌 자리가 사라졌습니다."
    src = status.group(0)
    assert "승인 필요" in src, "규칙축이 막고 있을 때 표지가 「승인」을 안 씁니다."
    assert "review_required" in src, (
        "표지가 게이트 사유를 안 읽습니다 — 문안이 게이트 서열을 재유도하거나 한 이름으로 "
        "두 축을 다시 누르고 있습니다."
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
