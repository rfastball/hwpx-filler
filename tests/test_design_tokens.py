"""디자인 토큰 단일 출처 동기화 가드 — Qt/QApplication 불필요(순수 stdlib).

색 hex 를 웹 CSS·목업 여러 곳에 손으로 중복하던 드리프트를 봉쇄하는 계약 테스트:
``design_tokens.json`` 이 생성하는 영역과 디스크 내용이 어긋나면 실패. Qt style.py 생성
타깃은 PySide6 제거(#23)로 폐기됐다 — 팔레트는 이제 웹 CSS 변수로만 소비된다.
어긋났을 때 복구는 ``python scripts/gen_design_tokens.py``.
"""
from __future__ import annotations

import gen_design_tokens as gen


def test_tokens_in_sync():
    problems = gen.check()
    assert not problems, (
        "토큰 드리프트: " + "; ".join(problems)
        + " — `python scripts/gen_design_tokens.py` 로 재생성하세요."
    )


def test_web_region_renders_expected_palette_and_tints():
    """웹 CSS 변수 영역이 핵심 팔레트·배지/중성 틴트를 design_tokens.json 에서 생성한다."""
    region = gen.render_web_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region            # 선택 하이라이트
    assert "--a-unconf:#fff3bf;" in region         # 미확정 배경
    # 배지·중성 틴트(V14/UD-33 환원)가 웹 변수로 실린다.
    assert "--fb-missing-bg:#fbe6e3;" in region
    assert "--n-ink-control:#2b3038;" in region
    assert "--n-track:#eef0f3;" in region


def test_mockup_region_maps_app_palette():
    region = gen.render_mockup_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region


# ---- 다크모드(prefers-color-scheme + [data-theme] override) 가드 ----

# 라이트 top-level 과 병렬이어야 하는 다크 팔레트 그룹(_note 등 메타 키는 제외).
_PALETTE_GROUPS = ("color", "state", "badge", "neutral", "log")


def test_dark_palette_has_full_light_parity():
    """``dark`` 섹션이 라이트 팔레트의 모든 group/key 를 빠짐없이 가진다(누락=다크에서 토큰 미정의).

    한 토큰이라도 다크에 빠지면 그 변수는 다크 블록에서 라이트 값을 물려받아(또는 미정의로)
    다크 표면에서 대비가 깨진다 — 병렬 완전성을 정적으로 강제한다.
    """
    t = gen.load_tokens()
    assert "dark" in t, "design_tokens.json 에 다크 팔레트(dark) 섹션이 없습니다."
    dark = t["dark"]
    for group in _PALETTE_GROUPS:
        light_keys = {k for k in t[group] if not k.startswith("_")}
        dark_keys = {k for k in dark.get(group, {}) if not k.startswith("_")}
        missing = light_keys - dark_keys
        assert not missing, f"다크 {group} 에 빠진 토큰: {sorted(missing)}"


def test_web_region_emits_three_theme_blocks():
    """웹 CSS 영역이 :root(라이트) + @media(prefers-color-scheme:dark) + [data-theme=dark] 3블록을
    color-scheme 선언과 함께 방출한다(OS 자동 + 앱 토글 양방향 override 패턴).
    """
    region = gen.render_web_region(gen.load_tokens())
    assert "@media (prefers-color-scheme:dark){" in region
    assert ':root:not([data-theme="light"]){' in region  # OS 다크를 앱 라이트 토글이 이김
    assert ':root[data-theme="dark"]{' in region          # OS 라이트를 앱 다크 토글이 이김
    assert "color-scheme:light;" in region and "color-scheme:dark;" in region
    # 다크 값이 실제로 실린다(라이트와 구분되는 대표 토큰).
    assert "--a-card:#1c2127;" in region
    assert "--a-on-accent:#0f1418;" in region


def test_web_region_dark_declares_every_light_variable():
    """다크 블록이 라이트가 선언한 모든 CSS 변수 이름을 재선언한다(개수·이름 패리티).

    tokens.css 는 CSS 변수 include 가 없어 다크가 이름을 하나라도 빠뜨리면 그 변수만 라이트
    값으로 남아 다크에서 색이 새는 조용한 회귀가 된다 — 렌더 문자열 수준에서 이름 집합을 맞춘다.
    """
    import re

    region = gen.render_web_region(gen.load_tokens())
    names = [name for name, _ in gen._WEB_MAP]
    light_block = region.split("@media", 1)[0]
    dark_block = region.split(':root[data-theme="dark"]{', 1)[1]
    for name in names:
        assert re.search(rf"{re.escape(name)}\s*:", light_block), f"라이트 블록에 {name} 누락"
        assert re.search(rf"{re.escape(name)}\s*:", dark_block), f"다크 블록에 {name} 누락"


# ---- 스케일 토큰(space/radius/type — 테마 불변) 가드 ----

_APP_CSS = (
    gen.ROOT / "web" / "css" / "app.css",
    gen.ROOT / "web-diff" / "css" / "app.css",
)


def test_web_region_emits_scale_tokens():
    """웹 CSS 영역이 여백·모서리·폰트크기 스케일 변수를 px 부착으로 방출한다(대표값 검증)."""
    region = gen.render_web_region(gen.load_tokens())
    assert "--sp-12:12px;" in region       # 여백 그리드
    assert "--sp-8:8px;" in region
    assert "--rad-md:6px;" in region        # 모서리
    assert "--rad-pill:999px;" in region    # 완전 둥근 pill
    assert "--fs-body:13px;" in region      # 본문 폰트
    assert "--fs-kpi:23px;" in region


def test_scale_tokens_theme_invariant():
    """스케일 변수는 라이트 :root 에만 실리고 다크 두 블록(@media·[data-theme=dark])엔 없다.

    스케일은 테마 불변이라 다크에서 재선언할 이유가 없다 — 색 3블록 패턴과 달리 :root 한 곳뿐임을
    정적으로 강제해, 훗날 다크 블록에 스케일이 새어들어 중복·불일치가 생기는 회귀를 막는다.
    """
    region = gen.render_web_region(gen.load_tokens())
    light_block = region.split("@media", 1)[0]
    dark_region = region.split("@media", 1)[1]  # @media + [data-theme=dark] 두 다크 블록 전부
    for prefix in ("--sp-", "--rad-", "--fs-"):
        assert prefix in light_block, f"라이트 :root 에 {prefix} 스케일 누락"
        assert prefix not in dark_region, f"다크 블록에 {prefix} 스케일이 새어듦(테마 불변 위반)"


def test_app_css_free_of_metric_literals():
    """채택 완료 축(font-size·border-radius)은 app.css 에 px 리터럴이 남지 않는다(색 리터럴 가드의 스케일판).

    허용 예외: ``font-size:0``(로고 접기)·``border-radius:50%``(원형)·``border-radius:0``은 스케일 값이
    아니라 리터럴 유지. 여백(padding/margin/gap)은 구조 치수가 리터럴로 남아 가드 대상에서 제외.
    """
    import re

    for path in _APP_CSS:
        css = path.read_text(encoding="utf-8")
        fs = re.search(r"font-size:\s*[\d.]+px", css)
        assert fs is None, f"{path.name}: font-size px 리터럴 잔존 → var(--fs-*) 로 (`{fs.group(0)}`)"
        rad = re.search(r"border-radius:[^;{}]*\d+px", css)
        assert rad is None, f"{path.name}: border-radius px 리터럴 잔존 → var(--rad-*) 로 (`{rad.group(0)}`)"
