"""R-css 라운드(101 순회 로드맵 6) 정적 가드 — 버튼/열 레이아웃 전수조사 착지의 회귀 차단.

원장: docs/UX_FINDINGS_101_WALKTHROUGH.md (F2·F5·F23·F28·F29 + 흡수 F6·F14·F24·F30·F32).
동적 거동(실창 렌더)은 selftest 게이트가, 색·스케일 토큰은 test_design_tokens 가 본다 —
여기선 이 라운드가 고친 구조(고정 열폭·조건부 복구 동선·quiet 재진술·기본 어포던스 축소·
타입 스케일의 마크업 사각)만 정적으로 가드한다. F6(새로고침 제거)·N1 이관은 test_r3_home.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_CSS = WEB / "css" / "app.css"
RUN_JS = WEB / "js" / "screens" / "run.js"
EDITOR_JS = WEB / "js" / "screens" / "editor.js"
PATHTRACK_JS = WEB / "js" / "pathtrack.js"


def _css() -> str:
    """주석 제거 + 공백 제거 — 포맷 불가지 검사(기존 관례: test_web_dom_contract)."""
    text = re.sub(r"/\*.*?\*/", "", APP_CSS.read_text(encoding="utf-8"), flags=re.S)
    return "".join(text.split())


def _fn_body(src: str, name: str, next_name: str) -> str:
    """최상위 함수 본문 조각 — 다음 함수 정의 전까지(정적 검사 범위 한정)."""
    return src[src.index(f"function {name}"): src.index(f"function {next_name}")]


# ------------------------------------------------------------------ F23·F24: 매핑표

def test_map_table_fixed_layout_prevents_column_jumps():
    """매핑표는 table-layout:fixed 여야 한다(F23) — auto 로 돌아가면 값 길이에 따라
    열폭이 변해 이전/다음 행 스텝마다 레이아웃이 튄다."""
    css = _css()
    m = re.search(r"table\.map\{([^}]*)\}", css)
    assert m and "table-layout:fixed" in m.group(1), (
        "table.map 이 table-layout:fixed 를 잃었습니다 — 행 스텝 시 열폭 튐 재발(F23)."
    )
    # 고정 레이아웃의 전제: 열폭 지정(th)과 셀 내 말줄임 — 지정이 사라지면 브라우저가
    # 첫 행 내용으로 임의 분배해 사실상 auto 와 같은 튐이 재발한다.
    assert re.search(r"table\.mapth:nth-child\(\d\)\{width:", css), (
        "table.map 열폭 지정(th:nth-child width)이 사라졌습니다(F23)."
    )


def test_confirmed_row_shows_green_tint():
    """확정 행은 녹색 틴트(완료 신호)여야 한다(F24) — 스키마온리(중립)와 갈라져야 한다."""
    css = _css()
    assert "tr.r-confirmedtd{background:var(--fb-fill-bg)}" in css, (
        "확정 행 녹색 틴트가 사라졌습니다 — 확정이 민무늬로 돌아가면 완료 신호 부재(F24)."
    )
    assert "tr.r-schemaonlytd{background:var(--a-card)}" in css, (
        "스키마온리 행이 중립(card)이 아닙니다 — 데이터 미연결은 '완료'가 아닙니다(F24)."
    )


# ------------------------------------------------------------------ F29: 로케이트 기본 세트

def test_pathtrack_default_affordances_are_open_and_reveal():
    """PathTrack 기본 어포던스는 열기·폴더보기 2개(F29) — 「경로 복사」는 경로 텍스트가
    실제로 필요한 곳(저장 폴더 등)만 opts.only 로 명시해 살린다."""
    src = PATHTRACK_JS.read_text(encoding="utf-8")
    m = re.search(r"opts\.only\)\s*\|\|\s*\[([^\]]*)\]", src)
    assert m, "PathTrack.affordances 의 기본 액션 배열이 없습니다(F29)."
    defaults = [p.strip().strip('"') for p in m.group(1).split(",")]
    assert defaults == ["open", "reveal"], (
        f"PathTrack 기본 어포던스가 {defaults} — 열기·폴더보기 2개여야 합니다(F29: "
        "경로 복사는 폴더보기와 중복이라 기본에서 제외)."
    )


# ------------------------------------------------------------------ F30: 복구 동선 조건부

def test_run_relink_button_gated_by_template_missing():
    """실행 화면 「템플릿 다시 연결」은 template_missing 일 때만 렌더(F30) — 상시 노출은
    정상 상태 노이즈이자 홈 카드(조건부)와의 비대칭."""
    src = RUN_JS.read_text(encoding="utf-8")
    body = _fn_body(src, "renderJobMeta", "renderData")
    assert "relink-template" in body, "실행 화면 템플릿 재연결 동선이 사라졌습니다(#67)."
    assert re.search(r"s\.template_missing\s*\?", body), (
        "재연결 버튼이 template_missing 조건 없이 상시 렌더됩니다(F30)."
    )
    gate = body.index("s.template_missing")
    assert gate < body.index("relink-template"), (
        "template_missing 분기가 재연결 버튼보다 뒤에 있습니다 — 조건부 렌더가 아닙니다(F30)."
    )


# ------------------------------------------------------------------ F32: 정상은 조용히

def test_normal_state_restatements_are_quiet_not_green_boxes():
    """정상 상태(ok) 재진술은 quiet(muted 한 줄)여야 한다(F32) — 초록 okbox 상시 배너 금지.

    run(자동 연결·사전검증)과 editor(세션 통지)의 상태 재진술이 대상. 사용자 행위의 직접
    결과(저장 완료 등)는 대상이 아니다 — 이 가드는 run.js 전체 무-okbox 와 editor 통지의
    quiet 분기만 본다.
    """
    run_src = RUN_JS.read_text(encoding="utf-8")
    assert "okbox" not in run_src, (
        "run.js 에 okbox 가 재도입됐습니다 — 정상 상태 초록 배너는 노이즈입니다(F32)."
    )
    for fn, nxt in (("renderData", "renderPreflight"), ("renderPreflight", "renderBadges")):
        body = _fn_body(run_src, fn, nxt)
        if '"ok"' in body:
            assert '"quiet"' in body, f"run.js {fn} 의 ok 레벨이 quiet 로 렌더되지 않습니다(F32)."
    ed_src = EDITOR_JS.read_text(encoding="utf-8")
    assert re.search(r'notice\.level === "ok" \? "quiet"', ed_src), (
        "editor.js 세션 통지의 ok 레벨이 quiet 가 아닙니다(F32)."
    )
    css = _css()
    assert ".note.quiet{" in css, "quiet 재진술 스타일(.note.quiet)이 app.css 에 없습니다(F32)."


# ------------------------------------------------------------------ 타입 스케일 마크업 사각

def test_web_markup_free_of_inline_font_size_literals():
    """인라인 font-size px 리터럴 금지 — app.css 가드(test_design_tokens)의 마크업/JS 확장.

    이 라운드가 걷어낸 인라인 12px(5역할 타입 스케일 밖 값)가 index.html·JS 템플릿 문자열로
    되돌아오는 회귀를 막는다. 크기는 var(--fs-*) 또는 클래스(capnote 등)로만.
    """
    targets = [WEB / "index.html", *sorted((WEB / "js").rglob("*.js"))]
    offenders = []
    for path in targets:
        for m in re.finditer(r"font-size:\s*[\d.]+px", path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, (
        "인라인 font-size px 리터럴 잔존 → var(--fs-*)/클래스로: " + "; ".join(offenders)
    )
