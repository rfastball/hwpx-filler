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
JOB_JS = WEB / "js" / "screens" / "job.js"  # run.js 사망(슬라이스 3) → 「작업」 패널이 생성 표면
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

# 유연 열(2열 '템플릿 필드 · 추정')이 최소 폭에서 보장받아야 하는 실용 하한(px).
# 이 밑으로 내려가면 좁은 창에서 핵심 식별자 열이 짜부라져 매핑 검토가 불가능하다(PR #84 리뷰).
_FLEX_COL_FLOOR = 180


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


def test_map_table_flex_column_survives_min_width():
    """min-width 에서 유연 열(폭 미지정 2열)에 남는 공간이 실용 하한 이상이어야 한다.

    고정 열 합이 min-width 를 거의 다 먹으면(fixed 레이아웃에서 잔여=유연 열 폭)
    좁은 창에서 '템플릿 필드 · 추정' 열이 수 px 로 짜부라진다 — 고정폭·min-width 중
    어느 쪽을 조정하든 이 배분 불변식이 성립해야 한다(PR #84 리뷰 회귀 가드).
    """
    css = _css()
    table = re.search(r"table\.map\{([^}]*)\}", css).group(1)
    min_width = int(re.search(r"min-width:(\d+)px", table).group(1))
    fixed = [int(w) for w in re.findall(r"table\.mapth:nth-child\(\d\)\{width:(\d+)px", css)]
    assert fixed, "고정 열폭 선언이 없습니다(F23 전제)."
    remaining = min_width - sum(fixed)
    assert remaining >= _FLEX_COL_FLOOR, (
        f"min-width({min_width}) - 고정 열 합({sum(fixed)}) = {remaining}px — 유연 열이 "
        f"{_FLEX_COL_FLOOR}px 미만으로 짜부라집니다. min-width 를 올리거나 고정폭을 줄이세요."
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


def test_pathtrack_secondary_actions_are_accessible_icon_buttons():
    """H-12: 열기·폴더보기·경로복사는 같은 아이콘 급이며 접근 이름·툴팁을 보존한다."""
    src = PATHTRACK_JS.read_text(encoding="utf-8")
    for action, label in (("open", "열기"), ("reveal", "폴더에서 보기"), ("copy", "경로 복사")):
        assert f"{action}: '<svg" in src
        assert f'label: "{label}", icon: ICONS.{action}' in src
    assert 'class="btn sm icon track-btn"' in src
    assert 'title="${spec.label}" aria-label="${spec.label}"' in src
    assert '${spec.icon}</button>' in src


def test_pathtrack_icon_style_is_visually_secondary_and_focusable():
    css = _css()
    assert ".track-affords{" in css and ".track-btn{" in css and ".track-btnsvg{" in css
    assert ".track-btn{width:28px;height:28px;padding:0;color:var(--a-muted)" in css
    assert ".btn:focus-visible{outline:2pxsolidvar(--a-primary)" in css


def test_pathtrack_keeps_text_primary_folder_picker():
    """보조 아이콘화가 찾아보기/지정 주동사를 삼키지 않는다."""
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="jobBtnPickFolder"[^>]*>찾아보기…</button>', index)


# ------------------------------------------------------------------ F30: 복구 동선 조건부

def test_job_relink_button_gated_by_template_missing():
    """「작업」 패널 「템플릿 다시 연결」은 template_missing 일 때만 렌더(F30) — 상시 노출은
    정상 상태 노이즈이자 홈 카드(조건부)와의 비대칭. (run.js 사망 후 job.js renderHeader 이 소관.)"""
    src = JOB_JS.read_text(encoding="utf-8")
    body = _fn_body(src, "renderHeader", "renderData")
    assert "relink-template" in body, "「작업」 패널 템플릿 재연결 동선이 사라졌습니다(#67)."
    assert "s.template_missing" in body, (
        "재연결 버튼이 template_missing 조건 없이 상시 렌더됩니다(F30)."
    )
    gate = body.index("s.template_missing")
    assert gate < body.index("relink-template"), (
        "template_missing 분기가 재연결 버튼보다 뒤에 있습니다 — 조건부 렌더가 아닙니다(F30)."
    )


# ------------------------------------------------------------------ F32: 정상은 조용히

def test_normal_state_restatements_are_quiet_not_green_boxes():
    """정상 상태(ok) 재진술은 quiet(muted 한 줄)여야 한다(F32) — 초록 okbox 상시 배너 금지.

    작업 패널(자동 연결·사전검증)과 editor(세션 통지)의 상태 재진술이 대상. 사용자 행위의 직접
    결과(저장 완료 등)는 대상이 아니다 — 이 가드는 job.js 전체 무-okbox 와 editor 통지의
    quiet 분기만 본다. (run.js 사망(슬라이스 3) 후 job.js 가 생성 표면.)
    """
    job_src = JOB_JS.read_text(encoding="utf-8")
    assert "okbox" not in job_src, (
        "job.js 에 okbox 가 재도입됐습니다 — 정상 상태 초록 배너는 노이즈입니다(F32)."
    )
    for fn, nxt in (("renderData", "renderPreflight"), ("renderPreflight", "renderMirror")):
        body = _fn_body(job_src, fn, nxt)
        if '"ok"' in body:
            assert '"quiet"' in body, f"job.js {fn} 의 ok 레벨이 quiet 로 렌더되지 않습니다(F32)."
    ed_src = EDITOR_JS.read_text(encoding="utf-8")
    assert re.search(r'notice\.level === "ok" \? "quiet"', ed_src), (
        "editor.js 세션 통지의 ok 레벨이 quiet 가 아닙니다(F32)."
    )
    css = _css()
    assert ".note.quiet{" in css, "quiet 재진술 스타일(.note.quiet)이 app.css 에 없습니다(F32)."


# ------------------------------------------------------------------ 타입 스케일 마크업 사각

# ------------------------------------------------------------------ #179: 조작 피드백 모션 규율

def test_motion_discipline_press_feedback_and_no_transition_all():
    """#179 슬라이스 4 — 조작 피드백 모션 규율(emil-design-eng)의 정적 가드.

    완료 조건 4항: press/overlay 모션은 모두 <300ms 이며 `transition: all` 을 쓰지 않는다.
    또 pressable 눌림(:active scale)과 reduced-motion 이동 제거가 실재해야 회귀를 잡는다.
    (구체 지속시간 값·테마 불변은 test_design_tokens 가, 실 개폐는 selftest 게이트가 본다.)
    """
    raw = APP_CSS.read_text(encoding="utf-8")
    nocomment = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)  # 주석 제거(공백 유지 — 단위 경계 보존)
    css = _css()  # 주석·공백 제거본
    # `transition: all` 금지 — 정확한 속성만 지정(불필요 리페인트·의도치 않은 전이 차단).
    assert "transition:all" not in css, (
        "app.css 에 `transition: all` 이 있습니다 — 정확한 속성만 지정하세요(#179 완료 조건)."
    )
    # 눌림 피드백 — :active 에 transform:scale 이 있고 :disabled 는 제외한다.
    assert ":active:not(:disabled){transform:scale(" in css, (
        "pressable :active 눌림(transform:scale, :disabled 제외)이 사라졌습니다(#179)."
    )
    # 이동은 reduced-motion 에서 제거(멀미 유발 위치·크기 애니메이션 차단).
    assert "@media(prefers-reduced-motion:reduce)" in css, (
        "prefers-reduced-motion 블록이 없습니다 — 이동 제거 계약 누락(#179)."
    )
    # 지속시간은 리터럴이 아니라 모션 토큰(var(--dur-*))으로만 — 드리프트 차단.
    assert "var(--dur-press)" in css and "var(--ease-out)" in css, (
        "모션 지속/이징이 토큰(var(--dur-*)/var(--ease-*))을 참조하지 않습니다(#179)."
    )
    # 주석 제거본에서 300ms 이상 하드코딩 지속시간이 없는지(진행바 .25s 같은 선행-점 소수 포함).
    for val, unit in re.findall(r"transition[^;{}]*?(\d*\.?\d+)\s*(ms|s)\b", nocomment):
        ms = float(val) * (1000 if unit == "s" else 1)
        assert ms < 300, f"app.css transition 에 {val}{unit}(={ms}ms) — 300ms 이상 모션 금지(#179)."


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
