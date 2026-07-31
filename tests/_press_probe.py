"""눌림 기하 측정 창구 — sealed Vite CSS를 loopback HTTP로 제공해 실 상자를 잰다.

이 모듈은 source CSS나 ``file:`` 문서를 읽지 않는다. 제품과 같은 resolver로 fresh
``build/web/``을 검증하고, Vite manifest가 가리키는 단일 CSS chunk를 임시 loopback
페이지에 연결한다. 그러므로 기하 게이트와 제품/selftest가 같은 sealed artifact ID를 본다.

``prefers-reduced-motion``은 호출자가 명시한다. 개발 기기의 Windows 모션 설정이 게이트
의미를 바꾸지 않게 ``no-preference``와 ``reduce``를 각각 강제한다.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from _web_source import REPO_ROOT
from hwpxfiller.web_artifact import VITE_MANIFEST_PATH, resolve_web_artifact

_PROBE_PATH = "/__n03_press_probe__.html"

_DOC = """<!doctype html>
<html lang="ko" data-theme="light"><head><meta charset="utf-8">
<link rel="stylesheet" href="./{css_path}">
<style>
  /* 골격을 재려는 폭에 못 박는다 — 파손 크기가 폭에 비례하므로 폭이 측정의 입력이다. */
  #probe-host{{width:{width}px}}
</style>
</head><body><div id="probe-host">{scaffold}</div></body></html>
"""


def _built_css_path() -> tuple[str, str]:
    artifact = resolve_web_artifact(repo_root=REPO_ROOT)
    manifest = json.loads(
        (artifact.root / VITE_MANIFEST_PATH).read_text(encoding="utf-8")
    )
    entries = [
        value
        for value in manifest.values()
        if isinstance(value, dict) and value.get("isEntry") is True
    ]
    assert len(entries) == 1, f"Vite product entry가 하나가 아닙니다: {entries!r}"
    css_paths = [
        value.get("file")
        for value in manifest.values()
        if isinstance(value, dict)
        and isinstance(value.get("file"), str)
        and value["file"].endswith(".css")
    ]
    assert len(css_paths) == 1, (
        f"Vite product CSS chunk가 하나가 아닙니다: {css_paths!r}"
    )
    css_path = css_paths[0]
    assert isinstance(css_path, str) and (artifact.root / css_path).is_file()
    return css_path, artifact.artifact_id


@contextmanager
def _loopback_document(document: str):
    artifact = resolve_web_artifact(repo_root=REPO_ROOT)
    payload = document.encode("utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(artifact.root), **kwargs)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler protocol
            if urlsplit(self.path).path == _PROBE_PATH:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

        def log_message(self, _format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}{_PROBE_PATH}", artifact.artifact_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_MEASURE = """() => {
  const el = document.getElementById("probe");
  const r = el.getBoundingClientRect();
  return {left: r.left, width: r.width, height: r.height,
          transform: getComputedStyle(el).transform, active: el.matches(":active")};
}"""


def measure_press(scaffold: str, width: int, motion: str) -> dict:
    """``#probe`` 요소를 누른 채 기하와 loopback artifact identity를 잰다."""
    from playwright.sync_api import sync_playwright

    css_path, artifact_id = _built_css_path()
    html = _DOC.format(css_path=css_path, width=width, scaffold=scaffold)
    with _loopback_document(html) as (url, served_artifact_id):
        assert served_artifact_id == artifact_id
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            try:
                context = browser.new_context(
                    viewport={"width": max(width + 200, 800), "height": 600},
                    reduced_motion=motion,
                )
                page = context.new_page()
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(120)
                before = page.evaluate(_MEASURE)
                box = page.locator("#probe").bounding_box()
                assert box is not None, "골격의 #probe 가 렌더되지 않았습니다."
                page.mouse.move(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
                page.mouse.down()
                page.wait_for_timeout(320)  # --dur-press 완주 대기
                held = page.evaluate(_MEASURE)
                resources = page.evaluate(
                    "() => performance.getEntriesByType('resource').map((entry) => entry.name)"
                )
                page.mouse.up()
                current_url = page.url
            finally:
                browser.close()

    origin = f"{urlsplit(current_url).scheme}://{urlsplit(current_url).netloc}"
    forbidden = [
        resource
        for resource in resources
        if f"{urlsplit(resource).scheme}://{urlsplit(resource).netloc}" != origin
        or urlsplit(resource).scheme == "file"
        or "@vite/client" in resource
    ]
    assert current_url == url and current_url.startswith("http://127.0.0.1:")
    assert resources, "sealed CSS resource가 loopback 페이지에서 로드되지 않았습니다."
    assert not forbidden, f"press probe가 loopback 외 resource를 로드했습니다: {forbidden}"

    return {
        "d_left": round(held["left"] - before["left"], 2),
        "d_width": round(held["width"] - before["width"], 2),
        "d_height": round(held["height"] - before["height"], 2),
        "width": round(before["width"], 2),
        "transform": held["transform"],
        "active": bool(held["active"]),
        "url": current_url,
        "origin": origin,
        "resource_urls": resources,
        "resources_same_origin": True,
        "artifact_id": artifact_id,
    }
