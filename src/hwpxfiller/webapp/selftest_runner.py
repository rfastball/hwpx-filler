"""Selftest mode selection, browser evidence, and live-run driver."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..host.native.debug import log
from . import selftest_api

if TYPE_CHECKING:
    from . import live_run


_GLOBAL_DELTA_FN = r"""function () {
  var RETIRED = ['AppCloseGuard','Bridge','Copy','DataPicker','DataZone','EditorEntry',
    'EditorScreen','GroupList','Guard','Intent','JobScreen','LibraryScreen','Modal','Nav',
    'PathTrack','Personalization','Popover','Preserve','Relink','SegView','SheetPicker',
    'SurfaceSheet','Theme','UndoToast','WorkbenchScreen','__push','escHtml'];
  var names = Object.getOwnPropertyNames(window).sort();
  var digest = function (list) {
    var h = 0x811c9dc5;
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      for (var j = 0; j < t.length; j++) {
        h ^= t.charCodeAt(j);
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
      }
      h ^= 10;
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  };
  var hwpx = [], retired = [], withoutTest = [];
  for (var i = 0; i < names.length; i++) {
    if (names[i].indexOf('__hwpx') === 0) { hwpx.push(names[i]); }
    if (RETIRED.indexOf(names[i]) !== -1) { retired.push(names[i]); }
    if (names[i] !== '__hwpxTest') { withoutTest.push(names[i]); }
  }
  return {
    total_own: names.length,
    hwpx_namespace: hwpx,
    retired_present: retired,
    digest: digest(names),
    digest_without_test: digest(withoutTest),
    has_document: names.indexOf('document') !== -1,
    has_location: names.indexOf('location') !== -1
  };
}"""

_GLOBAL_DELTA_JS = "(" + _GLOBAL_DELTA_FN + ")()"
_NON_EXPOSURE_JS = r"""
(function () {
  var own = function () {
    return Object.prototype.hasOwnProperty.call(window, '__hwpxTest');
  };
  var out = {
    selftest_own: own(),
    selftest_typeof: typeof window.__hwpxTest,
    product_typeof: typeof window.__hwpx,
    host_claim_typeof: typeof (window.pywebview
      && window.pywebview.api && window.pywebview.api.selftest_claim)
  };
  out.global_delta = (GLOBAL_DELTA_FN)();
  try {
    window.history.replaceState(null, '',
      window.location.pathname + '?selftest=1&hwpxTest=on#selftest');
    out.url_after = window.location.href;
    out.selftest_own_after_query_hash = own();
    out.selftest_typeof_after_query_hash = typeof window.__hwpxTest;
  } catch (e) {
    out.query_hash_error = String(e && e.message ? e.message : e);
  }
  return out;
})()
""".replace("GLOBAL_DELTA_FN", _GLOBAL_DELTA_FN)

_MODE_GLOBAL_DELTA = "global_delta"
_MODE_NO_CAPABILITY = "no_capability"
_SELFTEST_ECHO_KEYS = {"theme_write": "theme_write", "font_scale_write": "font_scale_write"}

#: Selftest engine budget (seconds).  app.py keeps the public monkeypatch seam.
SELFTEST_BUDGET_S = 80.0


def _selftest_mode(environ: Mapping[str, str]) -> tuple[str, str]:
    """Environment to ``(mode, input)``; preserve the legacy priority."""
    if environ.get("HWPX_SELFTEST_NO_CAPABILITY"):
        return _MODE_NO_CAPABILITY, ""
    if environ.get("HWPX_SELFTEST_GLOBAL_DELTA"):
        return _MODE_GLOBAL_DELTA, ""
    if environ.get("HWPX_SELFTEST_GEOMETRY_ONLY"):
        return "geometry_only", ""
    if font_scale := environ.get("HWPX_SELFTEST_SET_FONT_SCALE"):
        return "font_scale_write", font_scale
    if theme := environ.get("HWPX_SELFTEST_SET_THEME"):
        return "theme_write", theme
    return "full", ""


def _selftest_non_exposure_evidence(window: object) -> dict:
    """Measure the no-capability control without exposing a product hook."""
    evidence: dict = {"mode": _MODE_NO_CAPABILITY}
    sentinel = os.environ.get("HWPX_SELFTEST_LEAK_SENTINEL")
    if sentinel:
        evidence["leak_sentinel"] = sentinel
        try:
            window.evaluate_js(  # type: ignore[attr-defined]
                f"(function () {{ window[{json.dumps(sentinel)}] = 1; return true; }})()"
            )
        except Exception as exc:  # noqa: BLE001
            evidence["error"] = f"누수 파수꾼 설치 실패: {exc!r}"
            return evidence

    try:
        probed = window.evaluate_js(_NON_EXPOSURE_JS)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        evidence["error"] = f"비노출 음성 대조 평가 실패: {exc!r}"
        return evidence
    if not isinstance(probed, Mapping):
        evidence["error"] = f"비노출 음성 대조 반환이 객체가 아니다: {probed!r}"
        return evidence
    probed = dict(probed)
    evidence["global_delta"] = dict(probed.pop("global_delta", {}))
    evidence["non_exposure"] = probed
    return evidence


def _selftest_global_delta(window: object) -> dict:
    """Measure the window's own globals without treating observation failure as success."""
    try:
        probed = window.evaluate_js(_GLOBAL_DELTA_JS)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return {"added_globals_error": f"전역 델타 평가 실패: {exc!r}"}
    if not isinstance(probed, Mapping):
        return {"added_globals_error": f"전역 델타 반환이 객체가 아니다: {probed!r}"}
    return dict(probed)


def drive(ctx: live_run.LiveContext) -> None:
    """Run the selected selftest mode and finish through the supplied context."""
    window = ctx.window
    mode, echo_value = _selftest_mode(os.environ)

    if mode == _MODE_NO_CAPABILITY:
        ctx.finish(_selftest_non_exposure_evidence(window))
        return

    if mode == _MODE_GLOBAL_DELTA:
        probe_client = selftest_api.SelftestClient.for_window(
            window, budget_s=SELFTEST_BUDGET_S, log=log
        )
        delta_evidence: dict = {"mode": _MODE_GLOBAL_DELTA}
        try:
            probe_client.await_readiness(probe_client.new_deadline())
        except Exception as exc:  # noqa: BLE001
            delta_evidence["error"] = f"시험 능력 준비 실패: {exc!r}"
        else:
            delta_evidence["global_delta"] = _selftest_global_delta(window)
        ctx.finish(delta_evidence)
        return

    client = selftest_api.SelftestClient.for_window(
        window, budget_s=SELFTEST_BUDGET_S, log=log
    )
    outcome = client.drive(
        mode,
        probe_input=echo_value or None,
        flags={"offlineProbe": bool(os.environ.get("HWPX_SELFTEST_OFFLINE_PROBE"))},
    )

    evidence: dict = {}
    if echo_key := _SELFTEST_ECHO_KEYS.get(mode):
        evidence[echo_key] = echo_value
    if outcome.has_evidence:
        evidence.update(outcome.evidence or {})
    if not outcome.ok and "error" not in evidence:
        evidence["error"] = outcome.alarm_text
    ctx.finish(evidence)
