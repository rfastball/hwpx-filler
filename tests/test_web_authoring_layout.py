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
- 어느 배율에서도 구조 행이 낱말 안에서 줄을 바꾸지 않고(UX-09: 28px 한 줄 말줄임), 구조 패널이 가로로
  넘치지 않으며, 머리 띠(돌아가기·제목·파일·문서 탭·저장)와 도구 막대는 각각 한 줄이고 그림 단추는 32px 정사각이다.
  항목의 자식 구간은 실선, 선택은 점선 안내선이다.
- 강제 색상에서 린트 강조 두 종은 그림자가 아니라 실보더로 갈린다.

데스크톱 Chrome 이 없는 러너는 ``HWPX_SKIP_MOTION_TESTS=1`` 로 **명시** 옵트아웃한다(눌림 기하
게이트와 같은 매체·같은 스위치).
"""

from __future__ import annotations

import os

import pytest

_GATE = bool(os.environ.get("HWPX_SKIP_MOTION_TESTS"))
_REASON = "저작 배치 실렌더 게이트 — Playwright + 설치 Chrome 필요(HWPX_SKIP_MOTION_TESTS=1 로 명시 옵트아웃)"

_ICON = '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9"></path></svg>'


def _row(kind: str, tag: str, name: str, meta: str, children: str = "", dot: bool = False) -> str:
    """문서 척추 한 줄(UX-09) — 제품(authoring.ts)이 그리는 줄 구조와 같은 모양."""
    group = f'<ul role="group">{children}</ul>' if children else ""
    toggle = '<span class="authoring-tree-toggle" aria-hidden="true"></span>' if children else (
        '<span class="authoring-tree-toggle" aria-hidden="true" data-leaf=""></span>')
    dot_html = f'<span class="authoring-coverage-dot">{_ICON}</span>' if dot else ""
    return (f'<li role="treeitem" data-kind="{kind}" aria-expanded="{"true" if children else "false"}">'
            f'<span class="authoring-tree-row">{toggle}<span class="authoring-tree-glyph">{_ICON}</span>'
            f'<span class="authoring-kind">{tag}</span>{dot_html}<span class="authoring-tree-name">{name}</span>'
            f'<span class="authoring-tree-meta">{meta}</span></span>{group}</li>')


_OUTLINE_ROWS = (
    _row("use", "필드", "공고 기관 담당자 연락처", "사용 위치 1곳")
    + _row("slot", "항목", "안내 유형과 제출 서류 목록", "문단 3–17 · 문제 1", children=(
        _row("option", "선택", "일반 공고", "문단 3–9", dot=True, children=(
            _row("use", "필드", "제출 서류 목록과 기한 확인", "같은 필드, 1/2")))
        + _row("option", "선택", "긴급 공고(재공고 포함)", "문단 10–17", dot=True, children=(
            _row("use", "필드", "제출 서류 목록과 기한 확인", "같은 필드, 2/2")))))
    + _row("use", "필드", "사업명", "사용 위치 1곳")
)

_SCAFFOLD = """<!doctype html>
<html lang="ko" data-theme="light" data-font-scale="{scale}"><head><meta charset="utf-8">
<link rel="stylesheet" href="./{css_path}">
</head><body class="authoring-open">
<div class="app" style="{app_style}"><header class="topbar"></header><main class="stage"><div id="reactScreenStage">
<section id="scr-authoring" class="scr on"><div class="authoring-shell">
  <header class="authoring-head"><button type="button" class="btn icon" aria-label="돌아가기">{icon}</button><h1>템플릿 저작</h1>
    <button type="button" class="btn quiet" aria-haspopup="menu">파일</button>
    <div class="authoring-tabs" role="tablist"><div class="authoring-tab" role="tab" aria-selected="true"><span class="authoring-tab-name">2026년 공고문 초안.hwpx</span><button type="button" class="btn icon" aria-label="닫기">{icon}</button></div><div class="authoring-tab" role="tab" aria-selected="false"><span class="authoring-tab-name">안내문.txt</span><button type="button" class="btn icon" aria-label="닫기">{icon}</button></div></div>
    <button type="button" class="btn primary">저장</button></header>
  <div class="authoring-toolbar" role="toolbar">
    <div class="authoring-toolbar-group"><button class="btn icon" aria-label="문서 실행 취소">{icon}</button><button class="btn icon" aria-label="문서 다시 실행">{icon}</button></div>
    <div class="authoring-toolbar-group"><div class="authoring-mode"><button aria-pressed="true">원문</button><button>이름표</button><button>문서</button></div></div>
    <div class="authoring-toolbar-group"><button class="btn quiet">필드로 만들기</button><button class="btn quiet">항목으로 만들기</button><button class="btn quiet">선택으로 만들기</button></div>
    <div class="authoring-toolbar-group"><button class="btn icon" aria-label="더보기">{icon}</button></div>
    <div class="authoring-toolbar-group authoring-toolbar-end"><button class="btn">결과 시험</button></div>
  </div>
  <div class="authoring-body with-properties">
    <button type="button" class="authoring-rail-toggle" aria-expanded="false" aria-label="구조 패널 보기">{icon}</button>
    <aside class="authoring-outline"><div class="authoring-outline-head"><h2 class="authoring-section-label">템플릿 구조</h2>
      <div class="authoring-outline-tabs" role="tablist"><button type="button" role="tab" class="authoring-outline-tab" aria-selected="true">구조</button><button type="button" role="tab" class="authoring-outline-tab" aria-selected="false">필드 <span class="authoring-tab-count">4</span></button></div>
      <label class="authoring-filter">{icon}<input class="field" type="search" aria-label="구조 필터"></label></div>
      <div class="authoring-outline-panel" role="tabpanel"><ul class="authoring-tree" role="tree">{rows}</ul></div></aside>
    <div class="authoring-splitter authoring-splitter-outline" role="separator" tabindex="0"></div>
    <div class="authoring-center">
      <div class="authoring-selection" role="navigation"><span class="authoring-crumb root">2026년 공고문 초안.hwpx</span><span class="authoring-crumb-sep">{icon}</span><button type="button" class="authoring-crumb" aria-current="location">항목 · 견적 조건</button><span class="authoring-selection-note" title="고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요.">고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요.</span></div>
      <main class="authoring-canvas"><div class="authoring-document" id="document"><div style="height:3000px">본문</div></div></main>
    </div>
    <div class="authoring-splitter authoring-splitter-properties" role="separator" tabindex="0"></div>
    <form class="authoring-properties"><div class="authoring-properties-head"><h2 class="authoring-section-label">속성</h2><button type="button" class="btn icon" aria-label="닫기">{icon}</button></div>
      <label class="authoring-field">이름<input class="field"></label></form>
    <div class="authoring-scrim" aria-hidden="true"></div>
  </div>
  <footer class="authoring-status"><div class="authoring-status-group"><span>저장됨 · 초안</span><button type="button" class="authoring-status-link">사용 전에 구조 오류 1개를 확인하세요.</button></div>
    <div class="authoring-status-group authoring-status-end"><button type="button" class="authoring-status-link" data-trial="current">현재 구성 통과</button><select class="field authoring-zoom" aria-label="확대"><option>100%</option></select></div></footer>
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
  for (const name of document.querySelectorAll(".authoring-outline .authoring-tree-name")) {
    const node = name.firstChild;
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
  // UX-09: 줄은 28px 한 줄(이름은 말줄임)이고 구조 패널은 가로로 넘치지 않는다. 그림 단추는 32px 정사각.
  const rowHeights = [...document.querySelectorAll(".authoring-tree-row")].map((row) => Math.round(row.getBoundingClientRect().height * 10) / 10);
  const outlineEl = q(".authoring-outline");
  const outlineOverflowX = outlineEl.scrollWidth - outlineEl.clientWidth;
  const rowsInside = [...document.querySelectorAll(".authoring-tree-row")].every((row) => row.getBoundingClientRect().right <= outlineEl.getBoundingClientRect().right + 0.5);
  const iconSizes = [...document.querySelectorAll(".authoring-toolbar .btn.icon")].map((b) => { const r = b.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; });
  const guide = (s) => getComputedStyle(q(s)).borderLeftStyle;
  const guides = { slot: guide('[data-kind="slot"]>[role="group"]'), option: guide('[role="group"]>[data-kind="option"]') };
  const toolbar = q(".authoring-toolbar");
  // 한 줄 = 모든 무리의 세로 구간이 서로 겹친다(높이가 다른 무리는 가운데 정렬이라 윗변이 조금씩 다르다).
  const groups = [...document.querySelectorAll(".authoring-toolbar-group")].map((g) => g.getBoundingClientRect());
  const oneRow = Math.max(...groups.map((r) => r.top)) < Math.min(...groups.map((r) => r.bottom));
  // 머리 띠도 한 줄이다: 자식(돌아가기·제목·파일·탭 줄·저장)의 세로 구간이 서로 겹치고, 저장은 띠 안(오른쪽 끝)에 선다.
  const head = q(".authoring-head");
  const headKids = [...head.children].map((el) => el.getBoundingClientRect());
  const headOneRow = Math.max(...headKids.map((r) => r.top)) < Math.min(...headKids.map((r) => r.bottom));
  const headBox = head.getBoundingClientRect();
  const save = q(".authoring-head>.btn:last-child").getBoundingClientRect();
  const headSaveInside = save.right <= headBox.right + 0.5 && save.left >= headBox.left;
  // IDE-01: 위치 줄 메모는 줄 안의 한 줄(말줄임)이고, 상태 막대 입구는 밑줄 없는 글이다(hover·focus 에만 밑줄).
  const selectionEl = q(".authoring-selection");
  const selectionBox = selectionEl.getBoundingClientRect();
  const noteBox = q(".authoring-selection-note").getBoundingClientRect();
  const noteInside = noteBox.right <= selectionBox.right + 0.5 && noteBox.top >= selectionBox.top - 0.5
    && noteBox.bottom <= selectionBox.bottom + 0.5 && noteBox.width > 0;
  const noteStyle = getComputedStyle(q(".authoring-selection-note"));
  const statusLinks = [...document.querySelectorAll(".authoring-status-link")].map((el) => {
    const style = getComputedStyle(el);
    return { decoration: style.textDecorationLine, border: style.borderTopStyle, background: style.backgroundColor };
  });
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
    brokenWords, toolbarRows: oneRow ? 1 : 2, rowHeights, outlineOverflowX, rowsInside, iconSizes, guides,
    toolbarOverflowY: toolbar.scrollHeight - toolbar.clientHeight,
    headRows: headOneRow ? 1 : 2, headSaveInside, headOverflowX: head.scrollWidth - head.clientWidth,
    noteInside, noteEllipsis: noteStyle.textOverflow === "ellipsis" && noteStyle.whiteSpace === "nowrap",
    selectionOverflowY: selectionEl.scrollHeight - selectionEl.clientHeight, statusLinks,
  };
}"""


def _render(width: int, height: int, scale: str, app_style: str = "") -> dict:
    from playwright.sync_api import sync_playwright

    from _press_probe import _built_css_path, _loopback_document

    css_path, artifact_id = _built_css_path()
    rows = _OUTLINE_ROWS
    html = _SCAFFOLD.format(css_path=css_path, scale=scale, rows=rows, app_style=app_style, icon=_ICON)
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


#: 1028×740 은 CI live-webview2 창의 클라이언트 폭이다(1024 급 화면) — 구조가 기본으로 서야 하는 폭.
#: 744×560 은 selftest 최소 창(760×600)의 클라이언트 폭이다.
_CASES = [(width, height, scale) for width, height in ((1440, 900), (1028, 740), (1000, 700), (744, 560))
          for scale in ("normal", "large", "larger")]


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
@pytest.mark.parametrize(("width", "height", "scale"), _CASES)
def test_authoring_columns_scale_and_narrow_sheet(width: int, height: int, scale: str) -> None:
    m = _render(width, height, scale)
    narrow = m["container"] <= 64 * m["root"] + 0.5   # 속성 시트
    rail = m["container"] <= 52 * m["root"] + 0.5     # 구조 레일(핵심 패널이라 더 좁을 때만)
    where = f"{width}x{height}@{scale} (root {m['root']}px, 작업대 {m['container']:.0f}px)"

    assert not m["brokenWords"], f"{where}: 구조 행이 낱말 안에서 줄을 바꿨습니다: {m['brokenWords']}"
    if m["outlineShown"]:
        assert set(m["rowHeights"]) == {28}, f"{where}: 구조 줄 높이가 28px 한 줄이 아닙니다: {m['rowHeights']}"
        assert m["outlineOverflowX"] <= 0 and m["rowsInside"], f"{where}: 구조 패널이 가로로 넘칩니다({m['outlineOverflowX']}px)"
        assert m["guides"] == {"slot": "solid", "option": "dashed"}, f"{where}: 안내선 종류가 다릅니다 {m['guides']}"
    assert all(size == [32, 32] for size in m["iconSizes"]), f"{where}: 그림 단추가 32px 정사각이 아닙니다 {m['iconSizes']}"
    assert m["toolbarRows"] == 1 and m["toolbarOverflowY"] <= 1, (
        f"{where}: 도구 막대가 한 줄이 아닙니다(행 {m['toolbarRows']}, 세로 넘침 {m['toolbarOverflowY']})"
    )
    assert m["headRows"] == 1 and m["headSaveInside"] and m["headOverflowX"] <= 0, (
        f"{where}: 머리 띠가 한 줄로 서지 않습니다(행 {m['headRows']}, 저장 안쪽 {m['headSaveInside']}, "
        f"가로 넘침 {m['headOverflowX']})"
    )
    # IDE-01: 위치 줄 메모는 줄 안에 한 줄로 서고(넘치면 말줄임), 줄을 세로로 밀지 않는다.
    assert m["noteInside"] and m["noteEllipsis"] and m["selectionOverflowY"] <= 0, (
        f"{where}: 위치 줄 메모가 줄 안의 한 줄이 아닙니다(안쪽 {m['noteInside']}, 말줄임 {m['noteEllipsis']}, "
        f"세로 넘침 {m['selectionOverflowY']})"
    )
    # 상태 막대 입구는 단추 모양이 아니라 글 링크 모양이다 — 테두리·면·평시 밑줄 없음.
    assert m["statusLinks"] and all(link == {"decoration": "none", "border": "none", "background": "rgba(0, 0, 0, 0)"}
                                    for link in m["statusLinks"]), f"{where}: {m['statusLinks']}"

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
        assert not m["splitterShown"], where
        if rail:
            assert m["railShown"] and not m["outlineShown"], f"{where}: 구조 레일로 접혀야 합니다"
        else:
            assert m["outlineShown"] and not m["railShown"], f"{where}: 구조가 기본으로 서야 합니다"
            assert m["outline"]["right"] <= m["center"]["left"] + 0.5, f"{where}: 구조가 문서면과 겹칩니다"
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
<p><button type="button" id="link" class="authoring-status-link">구조 오류 1개</button> <a id="ref" href="#ref">참조</a></p>
</body></html>
"""

_MEASURE_FORCED = """() => ({...Object.fromEntries(["field", "marker"].map((id) => {
  const s = getComputedStyle(document.getElementById(id));
  return [id, {shadow: s.boxShadow, bottom: `${s.borderBottomWidth} ${s.borderBottomStyle}`,
               left: `${s.borderLeftWidth} ${s.borderLeftStyle}`}];
})), link: getComputedStyle(document.getElementById("link")).color, ref: getComputedStyle(document.getElementById("ref")).color})"""


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
    # IDE-01: 상태 막대 입구는 강제 색상에서 링크 색(LinkText)이다 — 단추 글자색(ButtonText)으로 뭉개지지 않는다.
    assert active["link"] == active["ref"], active


# ---------------------------------------------------------------- IDE-04 결과 시험 첫 결과
#: 결과 시험 독(펼침) 고정물 — 제품(authoring.ts `Trial`)의 열 차례와 같다: 입력 열(입력 → 자동 갱신 → 시험 시작 →
#: 접힌 보관 케이스), 출력 열(상태 줄 → 결과 칸 → 통과 범위 문장 → 접힌 이유). 결과 칸은 HWPX(iframe) 또는 TXT(pre).
_TRIAL_DOCK = """  <section class="authoring-dock open trial" role="region" aria-label="보조 패널">
    <div class="authoring-dock-bar"><div class="authoring-dock-tabs" role="tablist"><button type="button" role="tab" class="authoring-dock-tab" aria-selected="false">문제</button><button type="button" role="tab" class="authoring-dock-tab" aria-selected="true">결과 시험</button></div>
      <div class="authoring-dock-actions"><button class="btn icon" aria-label="최대화">{icon}</button><button class="btn icon" aria-label="닫기">{icon}</button></div></div>
    <div class="authoring-dock-panel" id="authoring-dock-panel" role="tabpanel"><section class="authoring-trial" aria-label="결과 시험">
      <header><h2>결과 시험</h2><p>시험 자료는 템플릿 파일에 포함되지 않습니다.</p></header>
      <div class="authoring-trial-input"><div class="authoring-trial-group"><div class="authoring-actions start"><button class="btn">필드 이름 사용</button></div>
        <label class="authoring-field">수요기관<input class="field" value="시험값1"></label><label class="authoring-field">공고명<input class="field" value="시험값2"></label>
        <label class="authoring-field">추정가격<input class="field"></label><label class="authoring-field">담당자<input class="field"></label></div>
        <label class="authoring-check"><input type="checkbox" checked> 자동 갱신</label>
        <div class="authoring-actions start"><button class="btn primary">시험 시작</button></div>
        <details class="authoring-fold" id="cases"><summary class="authoring-section-label">보관한 시험 케이스</summary>
          <div class="authoring-actions start"><button class="btn" id="save-case">시험 케이스 저장</button></div>
          <div class="authoring-actions start quiet-row" id="transfer"><button class="btn quiet">시험 자료 가져오기</button><button class="btn quiet">시험 자료 내보내기</button></div></details></div>
      <div class="authoring-trial-output" id="output"><div class="authoring-trial-state" id="state"><span class="authoring-badge" data-trial="current">현재 구성 통과</span><p>현재 시험 구성 통과</p><button class="btn quiet">시험 결과 내보내기</button></div>
        {result}
        <p class="authoring-reason" id="reason">통과 표시는 현재 값과 선택 구성에만 해당합니다.</p>
        <details class="authoring-fold" id="reasons"><summary class="authoring-section-label">출력·제외 이유</summary><ul class="authoring-rows"><li>수요기관</li></ul></details></div>
    </section></div></section>
"""
_TRIAL_RESULTS = {
    "hwpx": '<div class="authoring-trial-result" id="result"><iframe title="시험 결과"></iframe></div>',
    "txt": '<pre class="authoring-trial-result" id="result" tabindex="0" role="group" aria-label="읽기 전용 시험 결과">'
           + "".join(f"{i:03d}행 본문 문장입니다.\n" for i in range(1, 121)) + "</pre>",
}

_MEASURE_TRIAL = """() => {
  const q = (s) => document.querySelector(s);
  const box = (s) => { const r = q(s).getBoundingClientRect(); return {top: r.top, bottom: r.bottom, height: r.height}; };
  const result = q("#result"), output = q("#output");
  const frame = q("#result iframe");
  const folded = [...document.querySelectorAll("details.authoring-fold")].map((d) => d.open);
  // 펼친 케이스 구획: 물러선 가져오기·내보내기 줄이 「시험 케이스 저장」과 겹치지 않는다.
  q("#cases").open = true;
  const caseGap = q("#transfer").getBoundingClientRect().top - q("#save-case").getBoundingClientRect().bottom;
  q("#cases").open = false;
  return { folded, caseGap,
    body: box(".authoring-body"), dock: box(".authoring-dock"), viewport: innerHeight,
    panel: box("#authoring-dock-panel"), output: box("#output"), state: box("#state"), result: box("#result"), reason: box("#reason"),
    frame: frame ? box("#result iframe") : null,
    resultScrolls: result.scrollHeight > result.clientHeight + 1 && getComputedStyle(result).overflowY === "auto",
    outputOverflow: output.scrollHeight - output.clientHeight, root: parseFloat(getComputedStyle(document.documentElement).fontSize),
    summaryShown: [...document.querySelectorAll("details.authoring-fold>summary")].every((s) => s.getBoundingClientRect().height > 0),
  };
}"""


def _render_trial(width: int, height: int, scale: str, media: str, dock: str = "open", trial_open: bool = True) -> dict:
    from playwright.sync_api import sync_playwright

    from _press_probe import _built_css_path, _loopback_document

    css_path, artifact_id = _built_css_path()
    # 결과 칸 HTML 에는 중괄호가 없다 — 이어서 뼈대 전체를 한 번 format 한다({icon} 등).
    dock_html = _TRIAL_DOCK.replace("{result}", _TRIAL_RESULTS[media])
    scaffold = _SCAFFOLD.replace('  <footer class="authoring-status">', dock_html + '  <footer class="authoring-status">')
    shell = "authoring-shell" + (" dock-max" if dock == "max" else "") + (" trial-open" if trial_open else "")
    scaffold = scaffold.replace('<div class="authoring-shell">', f'<div class="{shell}">')
    html = scaffold.format(css_path=css_path, scale=scale, rows=_OUTLINE_ROWS, app_style="", icon=_ICON)
    with _loopback_document(html) as (url, served_artifact_id):
        assert served_artifact_id == artifact_id
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            try:
                page = browser.new_context(viewport={"width": width, "height": height}).new_page()
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(120)
                return page.evaluate(_MEASURE_TRIAL)
            finally:
                browser.close()


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1366, 768), (1028, 740)])
@pytest.mark.parametrize("scale", ["normal", "large"])
@pytest.mark.parametrize("media", ["hwpx", "txt"])
def test_trial_result_fills_the_dock(width: int, height: int, scale: str, media: str) -> None:
    """IDE-04(P-02): 결과 칸은 고정 20rem 이 아니라 독 패널의 남은 높이를 채운다 — 1440×900(물리 2518×1574)과
    1028×740 에서 독 패널 높이의 절반 이상이고, 상태 줄 바로 아래(스크롤 없이 윗변이 보인다)에 선다. 통과 범위 문장과
    접힌 구획은 결과 아래다. HWPX 결과 iframe 은 칸을 가득 채우고, TXT 결과는 칸 자체가 스크롤 상자다."""
    m = _render_trial(width, height, scale, media)
    where = f"{media} {width}x{height}@{scale}"
    panel, output, result = m["panel"], m["output"], m["result"]
    # 몸통 하한: 결과 시험 중인 낮은 창(≤820px)은 32vh, 그 밖은 40vh 그대로.
    floor = 0.32 if height <= 820 else 0.4
    assert m["body"]["height"] >= floor * m["viewport"] - 0.5, f"{where}: 결과 시험 독이 몸통의 {floor:.0%} 하한을 눌렀습니다 {m['body']}"
    assert result["height"] >= 0.5 * panel["height"], f"{where}: 결과 칸 {result['height']}px < 독 패널 {panel['height']}px 의 50%"
    assert m["state"]["bottom"] <= result["top"] <= m["reason"]["top"], f"{where}: 열 차례가 상태 → 결과 → 통과 범위가 아닙니다 {m}"
    assert output["top"] <= result["top"] < output["bottom"], f"{where}: 결과 칸 윗변이 출력 열 안에 보이지 않습니다 {m}"
    assert m["folded"] == [False, False] and m["summaryShown"], f"{where}: 케이스·이유 구획은 접힌 채 요약만 보여야 합니다 {m['folded']}"
    assert m["caseGap"] >= 0, f"{where}: 펼친 케이스 구획에서 가져오기·내보내기 줄이 저장 단추와 겹칩니다({m['caseGap']}px)"
    # 결과 칸은 12rem 하한을 넘는 한 보이는 출력 열을 끝까지 쓴다(아래 여백 = 열 안쪽 여백 12px 뿐).
    if result["height"] > 12 * m["root"] + 0.5:
        assert abs(min(result["bottom"], output["bottom"]) - output["bottom"]) <= 12.5, f"{where}: 결과 칸이 보이는 열을 다 쓰지 않습니다 {m}"
    if (width, height, scale) == (1440, 900, "normal"):
        # 독 몫(48vh)은 몸통 40vh 하한에 막혀 347px 이다 — 결과 칸은 그 안의 최대(상태 줄 아래 전부)다.
        assert result["height"] >= 215, f"{where}: 결과 칸 {result['height']}px"
    if media == "hwpx":
        assert m["frame"] and abs(m["frame"]["height"] - result["height"]) <= 1, f"{where}: 결과 iframe 이 칸을 채우지 않습니다 {m}"
    else:
        assert m["resultScrolls"], f"{where}: 긴 TXT 결과는 칸 안에서 스크롤해야 합니다(닻은 이 칸의 scrollTop 만 옮긴다)"
    # 스크롤 없이 보이는 결과 칸(출력 열 안쪽)도 독 패널의 절반 이상이다 — 통과 범위 문장·접힌 구획은 그 아래로 밀려도 된다
    # (출력 열 스크롤로 닿는다, P-02 위험 항목).
    visible = min(result["bottom"], output["bottom"]) - result["top"]
    assert visible >= 0.5 * panel["height"], f"{where}: 스크롤 없이 보이는 결과 칸 {visible}px < 독 패널 {panel['height']}px 의 50%"


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
@pytest.mark.parametrize("media", ["hwpx", "txt"])
def test_trial_result_grows_with_a_maximized_dock(media: str) -> None:
    """IDE-04: 결과 칸은 고정 높이(옛 20rem)가 아니다 — 독을 최대화하면 보이는 출력 열을 끝까지 채우고, 통과 범위 문장과
    접힌 구획은 그 바로 아래(열 스크롤 한 번)에 선다."""
    m = _render_trial(1440, 900, "normal", media, dock="max")
    assert m["result"]["height"] > 20 * m["root"], f"{media}: 최대화한 독에서 결과 칸이 자라지 않습니다 {m['result']}"
    assert abs(m["result"]["bottom"] - m["output"]["bottom"]) <= 12.5, f"{media}: 결과 칸이 보이는 열을 다 쓰지 않습니다 {m}"
    assert 0 < m["outputOverflow"] <= 8 * m["root"], f"{media}: 결과 아래 구획의 넘침이 예상 밖입니다({m['outputOverflow']}px)"
    assert m["state"]["bottom"] <= m["result"]["top"] <= m["reason"]["top"], m


@pytest.mark.browser
@pytest.mark.skipif(_GATE, reason=_REASON)
@pytest.mark.parametrize(("width", "height", "trial_open", "floor"), [
    (1028, 740, True, 0.32), (1366, 768, True, 0.32), (1028, 740, False, 0.4), (1440, 900, True, 0.4)])
def test_body_floor_drops_only_during_a_trial_in_short_windows(width: int, height: int, trial_open: bool, floor: float) -> None:
    """IDE-04: 결과 시험 독이 몸통을 누르면 몸통은 하한에서 멈춘다 — 결과 시험 중(셸 trial-open)이고 창 높이가 820px 이하일
    때만 32vh, 셸 표지가 없거나 높은 창이면 40vh 그대로다."""
    m = _render_trial(width, height, "normal", "hwpx", trial_open=trial_open)
    assert abs(m["body"]["height"] - floor * m["viewport"]) <= 1, (width, height, trial_open, m["body"], m["viewport"])
