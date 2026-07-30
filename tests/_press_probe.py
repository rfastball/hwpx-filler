"""눌림 기하 측정 창구 — 실 배포 CSS 를 링크한 최소 문서에서 `:active` 를 유지하고 잰다.

이 모듈이 존재하는 이유는 **사본을 재지 않기** 위해서다. CSS 는 `web/css/` 실파일을
`web/index.html` 의 `<link>` 순서로 그대로 링크한다(`_web_css.APP_CSS_FILES` 가 그 순서의 단일
출처이고 `test_web_css_manifest` 가 index 와의 일치를 게이트한다). 골격 HTML 만 호출자가 준다 —
재는 것은 값이 아니라 **상자**이므로 내용은 필요 없다.

`prefers-reduced-motion` 은 호출자가 **명시**한다. 개발 기기가 Windows 「애니메이션 표시」를
꺼 두면 모션 층이 통째로 강등되므로(U2 §2.11) 강제 없이 잰 숫자는 무엇의 증거인지 말할 수 없다.
"""

from __future__ import annotations

import pathlib
import tempfile

from _web_css import APP_CSS_FILES, WEB_CSS_DIR

_TOKENS = "tokens.css"

_DOC = """<!doctype html>
<html lang="ko" data-theme="light"><head><meta charset="utf-8">
{links}
<style>
  /* 골격을 재려는 폭에 못 박는다 — 파손 크기가 폭에 비례하므로 폭이 측정의 입력이다. */
  #probe-host{{width:{width}px}}
</style>
</head><body><div id="probe-host">{scaffold}</div></body></html>
"""


def _document(scaffold: str, width: int) -> str:
    links = "\n".join(
        f'<link rel="stylesheet" href="{(WEB_CSS_DIR / name).as_uri()}">'
        for name in (_TOKENS, *APP_CSS_FILES)
    )
    return _DOC.format(links=links, width=width, scaffold=scaffold)


_MEASURE = """() => {
  const el = document.getElementById("probe");
  const r = el.getBoundingClientRect();
  return {left: r.left, width: r.width, height: r.height,
          transform: getComputedStyle(el).transform, active: el.matches(":active")};
}"""


def measure_press(scaffold: str, width: int, motion: str) -> dict:
    """`#probe` 요소를 누른 **채로** 기하를 잰다.

    :param scaffold: `#probe` 를 포함하는 최소 골격 HTML(실 산출자의 구조만 남긴 것).
    :param width: 골격 호스트의 폭 — 전수조사가 잰 실폭을 넣는다.
    :param motion: ``"no-preference"`` 또는 ``"reduce"``. 자동 감지하지 않는다.
    :returns: ``d_left``·``d_width``·``d_height``(누른 뒤 − 누르기 전) + ``transform``·``active``.
    """
    from playwright.sync_api import sync_playwright

    html = _document(scaffold, width)
    with tempfile.TemporaryDirectory() as tmp:
        page_path = pathlib.Path(tmp) / "press_probe.html"
        page_path.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            try:
                ctx = browser.new_context(viewport={"width": max(width + 200, 800), "height": 600},
                                          reduced_motion=motion)
                page = ctx.new_page()
                page.goto(page_path.as_uri())
                page.wait_for_timeout(120)
                before = page.evaluate(_MEASURE)
                box = page.locator("#probe").bounding_box()
                assert box is not None, "골격의 #probe 가 렌더되지 않았습니다."
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.wait_for_timeout(320)   # --dur-press 완주 대기(전이 중간값을 재지 않는다)
                held = page.evaluate(_MEASURE)
                page.mouse.up()
            finally:
                browser.close()

    return {
        "d_left": round(held["left"] - before["left"], 2),
        "d_width": round(held["width"] - before["width"], 2),
        "d_height": round(held["height"] - before["height"], 2),
        "width": round(before["width"], 2),
        "transform": held["transform"],
        "active": bool(held["active"]),
    }
