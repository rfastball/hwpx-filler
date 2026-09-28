"""저작 작업대 배치의 **실렌더 기하** 게이트 — UX-08(#1027).

## 왜 실렌더인가

열 폭이 rem·clamp·컨테이너 질의로 바뀌었다. 정적 검사는 규칙이 **있다**는 것만 말하고,
150% 배율에서 구조 열이 몇 글자를 담는지·좁은 폭에서 속성 시트가 편집면 스크롤 막대를
덮는지·분할선이 이웃과 겹치는지는 말하지 못한다. 그래서 sealed CSS 를 실제 Chrome 에 싣고
작업대 골격을 창 폭 2 × 글자 배율 3 으로 그려 상자를 잰다(`_press_probe` 와 같은 loopback
·artifact 동일성 규칙).

## 판정

- 넓은 폭: 구조·분할선·가운데·분할선·속성이 겹치지 않고 한 줄로 서며, 편집면 오른쪽 끝(스크롤
  막대 자리)을 무엇도 덮지 않는다.
- 좁은 폭(작업대 ≤ 64rem — 뿌리 글자 기준): 속성은 몸통 전체 높이의 시트, 그 뒤에 가림막,
  구조는 레일로 접히고 분할선은 쉰다.
- 어느 배율에서도 구조 행이 낱말 안에서 줄을 바꾸지 않고, 도구 막대는 한 줄이다.
- 강제 색상에서 린트 강조 두 종은 그림자가 아니라 실보더로 갈린다.

데스크톱 Chrome 이 없는 러너는 ``HWPX_SKIP_MOTION_TESTS=1`` 로 **명시** 옵트아웃한다(눌림 기하
게이트와 같은 매체·같은 스위치).
"""

from __future__ import annotations

import os

import pytest

_GATE = bool(os.environ.get("HWPX_SKIP_MOTION_TESTS"))
_REASON = "저작 배치 실렌더 게이트 — Playwright + 설치 Chrome 필요(HWPX_SKIP_MOTION_TESTS=1 로 명시 옵트아웃)"

_OUTLINE_ROWS = (
    "항목 안내 유형",
    "선택 일반 공고",
    "사업명 · 2",
    "공고 기관 담당자 연락처 · 1",
    "1. 제출 서류 목록과 기한 확인",
)

_SCAFFOLD = """<!doctype html>
<html lang="ko" data-theme="light" data-font-scale="{scale}"><head><meta charset="utf-8">
<link rel="stylesheet" href="./{css_path}">
</head><body class="authoring-open">
<div class="app" style="{app_style}"><header class="topbar"></header><main class="stage"><div id="reactScreenStage">
<section id="scr-authoring" class="scr on"><div class="authoring-shell">
  <div class="authoring-toolbar" role="toolbar">
    <div class="authoring-toolbar-group"><button class="btn sm">문서 실행 취소</button><button class="btn sm">문서 다시 실행</button></div>
    <div class="authoring-toolbar-group"><div class="authoring-mode"><button aria-pressed="true">원문</button><button>구조</button><button>문서</button></div></div>
    <div class="authoring-toolbar-group"><button class="btn sm">필드 만들기</button><button class="btn sm">항목 만들기</button><button class="btn sm">선택 만들기</button></div>
    <div class="authoring-toolbar-group"><button class="btn sm">명령</button><button class="btn sm">더보기</button></div>
    <div class="authoring-toolbar-group authoring-toolbar-end"><button class="btn sm">결과 시험</button><select class="field"><option>100%</option></select></div>
  </div>
  <div class="authoring-body with-properties">
    <button type="button" class="authoring-rail-toggle" aria-expanded="false">구조 패널 보기</button>
    <aside class="authoring-outline"><h2>템플릿 구조</h2>{rows}</aside>
    <div class="authoring-splitter authoring-splitter-outline" role="separator" tabindex="0"></div>
    <div class="authoring-center">
      <div class="authoring-selection"><span class="authoring-selection-label">현재 위치의 의미</span></div>
      <main class="authoring-canvas"><div class="authoring-document" id="document"><div style="height:3000px">본문</div></div></main>
    </div>
    <div class="authoring-splitter authoring-splitter-properties" role="separator" tabindex="0"></div>
    <form class="authoring-properties"><div class="authoring-properties-head"><h2>속성</h2><button type="button" class="btn sm">닫기</button></div>
      <label class="authoring-field">이름<input class="field"></label></form>
    <div class="authoring-scrim" aria-hidden="true"></div>
  </div>
</div></section></div></main></div></body></html>
"""

_MEASURE = """() => {
  const q = (s) => document.querySelector(s);
  const box = (s) => { const r = q(s).getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height}; };
  const shown = (s) => getComputedStyle(q(s)).display !== "none";
  const root = parseFloat(getComputedStyle(document.documentElement).fontSize);
  const doc = q("#document").getBoundingClientRect();
  const hit = document.elementFromPoint(doc.right - 3, (doc.top + doc.bottom) / 2);
  const brokenWords = [];
  for (const button of document.querySelectorAll(".authoring-outline .btn")) {
    const node = button.firstChild;
    const text = node.textContent;
    let at = 0;
    for (const word of text.split(" ")) {
      const range = document.createRange();
      range.setStart(node, at); range.setEnd(node, at + word.length);
      const lines = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
      if (lines.size > 1) brokenWords.push(word);
      at += word.length + 1;
    }
  }
  const toolbar = q(".authoring-toolbar");
  // 한 줄 = 모든 무리의 세로 구간이 서로 겹친다(높이가 다른 무리는 가운데 정렬이라 윗변이 조금씩 다르다).
  const groups = [...document.querySelectorAll(".authoring-toolbar-group")].map((g) => g.getBoundingClientRect());
  const oneRow = Math.max(...groups.map((r) => r.top)) < Math.min(...groups.map((r) => r.bottom));
  return {
    root, container: q("#scr-authoring").getBoundingClientRect().width,
    body: box(".authoring-body"), outline: box(".authoring-outline"), center: box(".authoring-center"),
    properties: box(".authoring-properties"), splitterOutline: box(".authoring-splitter-outline"),
    splitterProperties: box(".authoring-splitter-properties"), scrim: box(".authoring-scrim"),
    outlineShown: shown(".authoring-outline"), splitterShown: shown(".authoring-splitter-outline"),
    railShown: shown(".authoring-rail-toggle"), scrimShown: shown(".authoring-scrim"),
    propertiesPosition: getComputedStyle(q(".authoring-properties")).position,
    documentEdgeHit: hit === null ? "" : (hit.id || hit.className || hit.tagName),
    documentEdgeFree: hit !== null && q("#document").contains(hit),
    brokenWords, toolbarRows: oneRow ? 1 : 2,
    toolbarOverflowY: toolbar.scrollHeight - toolbar.clientHeight,
  };
}"""


def _render(width: int, height: int, scale: str, app_style: str = "") -> dict:
    from playwright.sync_api import sync_playwright

    from _press_probe import _built_css_path, _loopback_document

    css_path, artifact_id = _built_css_path()
    rows = "".join(f'<button class="btn sm">{label}</button>' for label in _OUTLINE_ROWS)
    html = _SCAFFOLD.format(css_path=css_path, scale=scale, rows=rows, app_style=app_style)
    with _loopback_document(html) as (url, served_artifact_id):
        assert served_artifact_id == artifact_id
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            try:
                page = browser.new_context(viewport={"width": width, "height": height}).new_page()
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(120)
                return page.evaluate(_MEASURE)
            finally:
                browser.close()


_CASES = [(width, height, scale) for width, height in ((1440, 900), (1000, 700))
          for scale in ("normal", "large", "larger")]


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
@pytest.mark.parametrize(("width", "height", "scale"), _CASES)
def test_authoring_columns_scale_and_narrow_sheet(width: int, height: int, scale: str) -> None:
    m = _render(width, height, scale)
    narrow = m["container"] <= 64 * m["root"] + 0.5
    where = f"{width}x{height}@{scale} (root {m['root']}px, 작업대 {m['container']:.0f}px)"

    assert not m["brokenWords"], f"{where}: 구조 행이 낱말 안에서 줄을 바꿨습니다: {m['brokenWords']}"
    assert m["toolbarRows"] == 1 and m["toolbarOverflowY"] <= 1, (
        f"{where}: 도구 막대가 한 줄이 아닙니다(행 {m['toolbarRows']}, 세로 넘침 {m['toolbarOverflowY']})"
    )

    if not narrow:
        assert m["outlineShown"] and m["splitterShown"] and not m["railShown"] and not m["scrimShown"], where
        assert m["propertiesPosition"] == "static", where
        # 한 줄로 서고 겹치지 않는다: 구조 | 분할선 | 가운데 | 분할선 | 속성.
        order = [m["outline"], m["splitterOutline"], m["center"], m["splitterProperties"], m["properties"]]
        for left, right in zip(order, order[1:], strict=False):
            assert left["right"] <= right["left"] + 0.5, f"{where}: 열이 겹칩니다 {left} / {right}"
        assert m["documentEdgeFree"], f"{where}: 편집면 오른쪽 끝을 {m['documentEdgeHit']!r} 가 덮습니다"
        # 기본 열 폭은 rem(16·20) 이라 배율을 따라 함께 자란다 — 문서면 몫의 상한(30%·35%)에 눌리지 않는 한.
        body = m["body"]["width"]
        assert m["outline"]["width"] == pytest.approx(min(16 * m["root"], 0.30 * body), abs=0.5), (where, m["outline"])
        assert m["properties"]["width"] == pytest.approx(min(20 * m["root"], 0.35 * body), abs=0.5), (
            where, m["properties"])
    else:
        assert m["railShown"] and not m["outlineShown"] and not m["splitterShown"], where
        assert m["propertiesPosition"] == "absolute" and m["scrimShown"], where
        body, sheet = m["body"], m["properties"]
        assert abs(sheet["top"] - body["top"]) <= 1 and abs(sheet["bottom"] - body["bottom"]) <= 1, (
            f"{where}: 속성 시트가 몸통 전체 높이가 아닙니다 {sheet} / {body}"
        )
        assert abs(sheet["right"] - body["right"]) <= 1, where
        assert abs(m["scrim"]["width"] - body["width"]) <= 1, f"{where}: 가림막이 몸통을 덮지 않습니다"
        # 편집면 오른쪽 끝을 덮는 것은 시트(가림막 위)뿐이다.
        assert "authoring-properties" in str(m["documentEdgeHit"]) or m["documentEdgeHit"] in {
            "LABEL", "INPUT", "H2", "DIV", "BUTTON", "FORM"
        }, f"{where}: {m['documentEdgeHit']!r}"


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
def test_saved_width_is_rem_and_follows_font_scale() -> None:
    """분할선으로 맞춘 폭(기준 px 256 = 16rem)은 배율을 따라 자란다 — 125% 에서 320px."""
    normal = _render(1440, 900, "normal", "--authoring-outline-w:16rem;--authoring-properties-w:20rem")
    large = _render(1440, 900, "large", "--authoring-outline-w:16rem;--authoring-properties-w:20rem")
    assert normal["outline"]["width"] == pytest.approx(256, abs=0.5)
    assert large["outline"]["width"] == pytest.approx(320, abs=0.5)
    assert normal["properties"]["width"] == pytest.approx(320, abs=0.5)
    assert large["properties"]["width"] == pytest.approx(400, abs=0.5)


_FORCED = """<!doctype html>
<html lang="ko" data-theme="light"><head><meta charset="utf-8">
<link rel="stylesheet" href="./{css_path}"></head><body>
<p><span id="field" class="cm-txtField">{{{{공고명}}}}</span> <span id="marker" class="cm-txtMarker">{{{{#항목 a 안내}}}}</span></p>
</body></html>
"""

_MEASURE_FORCED = """() => Object.fromEntries(["field", "marker"].map((id) => {
  const s = getComputedStyle(document.getElementById(id));
  return [id, {shadow: s.boxShadow, bottom: `${s.borderBottomWidth} ${s.borderBottomStyle}`,
               left: `${s.borderLeftWidth} ${s.borderLeftStyle}`}];
}))"""


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
def test_lintpad_spans_stay_distinct_in_forced_colors() -> None:
    from playwright.sync_api import sync_playwright

    from _press_probe import _built_css_path, _loopback_document

    css_path, _artifact = _built_css_path()
    measured = {}
    with _loopback_document(_FORCED.format(css_path=css_path)) as (url, _served):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            try:
                for mode in ("active", "none"):
                    context = browser.new_context(viewport={"width": 800, "height": 400}, forced_colors=mode)
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle")
                    measured[mode] = page.evaluate(_MEASURE_FORCED)
                    context.close()
            finally:
                browser.close()
    active, plain = measured["active"], measured["none"]
    # 전제: 강제 색상은 그림자를 지운다 — 그래서 실보더가 필요하다.
    assert active["field"]["shadow"] == "none" and active["marker"]["shadow"] == "none", active
    assert active["field"]["bottom"] == "2px solid", active
    assert active["marker"]["bottom"] == "1px dashed" and active["marker"]["left"] == "1px dashed", active
    # 평시에는 새 테두리가 새지 않는다(그림자 밑줄이 그대로).
    assert plain["field"]["bottom"].startswith("0px") and plain["field"]["shadow"] != "none", plain
