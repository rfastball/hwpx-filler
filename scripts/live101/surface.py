"""101 시나리오가 화면을 만지는 **유일한 표면** — 대기·클릭·스크롤·값 설정(N-11A · #423).

시나리오는 사용자 행동의 순서와 결과 판정만 말한다. "어떻게 기다리는가"(폴링 간격·시한·
진단)는 여기가 진다. 그래야 시나리오를 읽는 사람이 대본과 기계를 섞어 읽지 않는다.

## 왜 부재와 미성립을 가르는가

종전 하니스의 실패는 전부 한 문장이었다: ``대기 시한 초과: <무엇> — <표현식>``. 그런데 그
한 문장 뒤에는 성질이 다른 두 사건이 있다.

- **부재** — 겨눈 요소가 아예 없다. 화면이 개편됐거나 id 가 바뀌었다. 대본을 고쳐야 한다.
- **미성립** — 요소는 있는데 조건이 참이 되지 않았다. 앱이 느리거나 실제로 동작이 깨졌다.

둘을 같은 문장으로 내면 "20초 기다렸다"만 남고 **무엇을 고쳐야 하는지**는 안 남는다. 그래서
시한이 지난 뒤 :class:`Surface` 가 필수 selector 를 되짚어, 없으면 그 이름을 대며
:class:`MissingSurface` 로 죽는다. 진단을 실패 시점에만 하므로 정상 경로의 왕복은 늘지 않는다.

## 왜 전체 시한이 따로 있는가

종전에는 걸음마다의 시한(기본 20s)만 있었다. 40여 걸음이 각자 20초씩 매달릴 수 있으니 실행
하나의 상한이 사실상 없었고, 그래서 "언제 포기하는가"를 아무도 몰랐다. :class:`Deadline` 이
실행 전체의 예산을 들고, 걸음의 시한은 **남은 예산과의 최솟값**으로 잘린다.

## 왜 실창 경보를 포획하는가

``window.alert`` 는 WebView2 의 native modal 이라 사람이 닫기 전까지 JavaScript 실행을 막는다.
그 상태에서는 폴링의 ``evaluate_js`` 자체가 돌아오지 않아 걸음 시한을 다시 볼 수 없다. 101
실행에서만 경보를 문자열 queue 로 바꾸고, 같은 폴링 평가가 그 queue 를 함께 읽어 경보 문안을
즉시 실패로 남긴다. 정상 제품 실행의 경보 채널은 바꾸지 않는다.
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field


def js_literal(value: "str | None") -> str:
    """파이썬 값을 **자바스크립트 리터럴**로 적는다.

    ``repr`` 을 쓰면 안 된다: ``None`` 이 ``None`` 으로 적혀 ``ReferenceError`` 가 되고
    (문서 전역 스코프에 그런 이름이 없다), 따옴표·역슬래시가 든 문안은 표현식을 깨뜨린다.
    두 언어의 리터럴이 우연히 겹치는 구간에 기대면 겹치지 않는 값에서 조용히 무너진다.
    """
    return json.dumps(value, ensure_ascii=False)

#: 시나리오가 쓰는 DOM 헬퍼. 텍스트로 버튼을 겨누는 것은 사용자가 실제로 보는 것이 문안이기
#: 때문이다 — id 로만 겨누면 문안이 바뀌어도 대본이 초록으로 남는다.
JS_HELPERS = """
window.__cap = {
  alerts: [],
  takeAlert() {
    return this.alerts.length ? this.alerts.shift() : null;
  },
  poll(check) {
    const before = this.takeAlert();
    if (before !== null) return { ready: false, alert: before };
    const ready = Boolean(check());
    const after = this.takeAlert();
    return { ready: after === null && ready, alert: after };
  },
  btn(scopeSel, text) {
    const scope = scopeSel ? document.querySelector(scopeSel) : document;
    if (!scope) return null;
    return [...scope.querySelectorAll('button')].find(
      (b) => b.textContent.trim() === text && !b.disabled) || null;
  },
  clickBtn(scopeSel, text) {
    const b = this.btn(scopeSel, text);
    if (!b) return false;
    b.click();
    return true;
  },
  /* 입력과 이탈은 host 왕복을 사이에 둔 2상이다.
     R4-02 뒤 편집 입력은 React 제어 컴포넌트라 `el.value = …` 만으로는 아무 일도 없다:
     React 가 자기가 쓴 값을 기억하고 있어 변경으로 안 보고 `onChange` 를 안 띄운다.
     네이티브 setter 로 써야 그 추적기가 「바뀌었다」를 보고, 발신은 다음 host 왕복의
     blur 에서 난다. 같은 JS 스택에 input·blur를 붙이면 concurrent React 커밋 전의
     낡은 노드를 떠나거나 focusout 이 서지 않을 수 있다. */
  setValue(sel, value) {
    const el = document.querySelector(sel);
    if (!el) return false;
    let setter = null;
    for (let proto = Object.getPrototypeOf(el); proto; proto = Object.getPrototypeOf(proto)) {
      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
      if (descriptor && typeof descriptor.set === 'function') { setter = descriptor.set; break; }
    }
    el.focus();
    if (setter) setter.call(el, value); else el.value = value;
    const view = el.ownerDocument.defaultView || window;
    el.dispatchEvent(new view.Event('input', { bubbles: true }));
    return true;
  },
  commitValue(sel) {
    const el = document.querySelector(sel);
    if (!el) return false;
    /* host 왕복 사이 concurrent commit 이 초점을 옮겼더라도, 최신 노드에서 실제
       focus→blur 전이를 다시 만든다. 비활성 WebView2 창은 programmatic focus 를 얻지
       못해 native focusout 을 내지 않을 수 있으므로, 실제 발생을 관찰한 뒤 없을 때만
       한 번 합성한다(둘 다 내면 같은 편집을 두 번 발신한다). */
    let left = false;
    const markLeft = () => { left = true; };
    el.addEventListener('focusout', markLeft);
    el.focus();
    /* set_value 의 소비자 중 편집기 소스 선택기는 select 다(#jobOrderSel 은 U4 7번에서
       스위치가 되어 이 헬퍼를 떠났다). React 의 select onChange 는 native change 를
       소유하므로 이탈 상에서만 실제 이벤트를 재현한다. */
    const view = el.ownerDocument.defaultView || window;
    if (el.tagName === 'SELECT') el.dispatchEvent(new view.Event('change', { bubbles: true }));
    el.blur();
    el.removeEventListener('focusout', markLeft);
    if (!left && el.tagName !== 'SELECT') {
      el.dispatchEvent(new view.FocusEvent('focusout', { bubbles: true }));
    }
    return true;
  },
  asyncResults: {},
  startAsync(key, task) {
    this.asyncResults[key] = { done: false };
    Promise.resolve().then(task).then(
      (value) => { this.asyncResults[key] = { done: true, ok: true, value }; },
      (error) => {
        this.asyncResults[key] = {
          done: true,
          ok: false,
          error: String(error && (error.message || error)),
        };
      },
    );
    return true;
  },
  asyncDone(key) {
    return Boolean(this.asyncResults[key] && this.asyncResults[key].done);
  },
  takeAsync(key) {
    const result = this.asyncResults[key];
    delete this.asyncResults[key];
    return result;
  },
  dispatchTrace: [],
  dispatchGate: null,
  installDispatchProbe() {
    if (this.dispatchInstalled) return true;
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.dispatch !== 'function') return false;
    const original = api.dispatch.bind(api);
    api.dispatch = async (screen, action, payload) => {
      const trace = { screen, action, payload };
      this.dispatchTrace.push(trace);
      const gate = this.dispatchGate;
      if (gate && gate.action === action && gate.mode === 'before') {
        gate.reached = true;
        await gate.promise;
      }
      try {
        const response = await original(screen, action, payload);
        trace.response = response;
        if (gate && gate.action === action && gate.mode === 'after') {
          gate.reached = true;
          await gate.promise;
        }
        return response;
      } catch (error) {
        trace.error = String(error && (error.message || error));
        throw error;
      }
    };
    this.dispatchInstalled = true;
    return true;
  },
  gateDispatch(action, mode) {
    if (this.dispatchGate !== null || !['before', 'after'].includes(mode)) return false;
    let release;
    const promise = new Promise((resolve) => { release = resolve; });
    this.dispatchGate = { action, mode, reached: false, promise, release };
    return true;
  },
  dispatchGateReached() {
    return Boolean(this.dispatchGate && this.dispatchGate.reached);
  },
  releaseDispatch() {
    const gate = this.dispatchGate;
    if (!gate) return false;
    this.dispatchGate = null;
    gate.release();
    return true;
  },
  takeDispatchTrace() {
    return this.dispatchTrace.splice(0);
  },
};
/* 실창 하니스에서만 native modal 을 만들지 않는다. 문안은 poll 한 번의 JSON-safe 결과로
   Python 에 건너가므로 경보가 timeout이나 bridge hang으로 둔갑하지 않는다. */
window.alert = (message) => { window.__cap.alerts.push(String(message)); };
true;
"""


class ScenarioFailure(RuntimeError):
    """101 완주가 깨졌다 — 아래 둘 중 하나로만 구체화된다."""


class MissingSurface(ScenarioFailure):
    """겨눈 요소가 화면에 **없다**. 대본이 낡았거나 화면이 개편됐다."""

    def __init__(self, selector: str, what: str) -> None:
        super().__init__(f"화면에 없는 요소를 겨눴습니다: {selector!r} ({what})")
        self.selector = selector
        self.what = what


class StepTimeout(ScenarioFailure):
    """요소는 있는데 조건이 참이 되지 않았다. 앱이 느리거나 동작이 깨졌다."""

    def __init__(self, what: str, expression: str, waited_s: float) -> None:
        super().__init__(
            f"조건이 성립하지 않았습니다({waited_s:.1f}s): {what} — {expression}"
        )
        self.what = what
        self.expression = expression


class RunDeadlineExceeded(ScenarioFailure):
    """실행 **전체**의 예산이 끝났다 — 어느 걸음에서 끝났는지를 이름으로 남긴다."""


class UnexpectedNativeAlert(ScenarioFailure):
    """실창의 native 경보가 열릴 자리였다 — 문안을 잃지 않고 즉시 실패한다."""

    def __init__(self, message: str, what: str) -> None:
        super().__init__(f"실창 경보가 대기를 중단했습니다: {message!r} (기다리던 것: {what})")
        self.message = message
        self.what = what


@dataclass
class Deadline:
    """실행 하나의 전체 예산. 걸음의 시한은 남은 예산과의 최솟값으로 잘린다."""

    total_s: float
    started_at: float = field(default_factory=time.monotonic)

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_s(self) -> float:
        return self.total_s - self.elapsed_s()

    def expired(self) -> bool:
        return self.remaining_s() <= 0


class Surface:
    """실 DOM 위의 대기·클릭. 평가기 하나(``window.evaluate_js``)만 알고 그 밖은 모른다."""

    #: 폴링 간격. 값이 아니라 성질이 계약이다 — 사람의 눈보다 촘촘하고 CPU 를 태우지 않는다.
    POLL_S = 0.15
    #: 걸음 하나의 기본 상한.
    STEP_TIMEOUT_S = 20.0

    def __init__(self, window: object, deadline: Deadline) -> None:
        self._window = window
        self._deadline = deadline
        self._async_serial = 0

    # ------------------------------------------------------------------ 원자

    def js(self, expression: str):
        return self._window.evaluate_js(expression)  # type: ignore[attr-defined]

    def install_helpers(self) -> None:
        self.js(JS_HELPERS)

    def bridge_outcome(self, expression: str, what: str) -> dict:
        """Await one real pywebview Promise without adding a second timeout clock."""
        self._async_serial += 1
        key = f"p{self._async_serial}"
        if not self.js(
            f"window.__cap.startAsync({js_literal(key)}, () => ({expression}))"
        ):
            raise ScenarioFailure(f"브리지 호출을 시작하지 못했습니다: {what}")
        self.wait(
            f"window.__cap.asyncDone({js_literal(key)})",
            what,
        )
        result = self.js(f"window.__cap.takeAsync({js_literal(key)})")
        if not isinstance(result, dict):
            raise ScenarioFailure(f"브리지 호출 결과가 객체가 아닙니다: {what}")
        return result

    def bridge(self, expression: str, what: str) -> object:
        result = self.bridge_outcome(expression, what)
        if result.get("ok") is not True:
            detail = result.get("error") if isinstance(result, dict) else result
            raise ScenarioFailure(f"브리지 호출 실패: {what} — {detail}")
        return result.get("value")

    def install_dispatch_probe(self) -> None:
        if not self.js("window.__cap.installDispatchProbe()"):
            raise ScenarioFailure("Product dispatch probe를 설치하지 못했습니다")

    def gate_dispatch(self, action: str, *, mode: str) -> None:
        if not self.js(
            f"window.__cap.gateDispatch({js_literal(action)}, {js_literal(mode)})"
        ):
            raise ScenarioFailure(f"dispatch gate를 무장하지 못했습니다: {action}/{mode}")

    def wait_dispatch_gate(self, what: str) -> None:
        self.wait("window.__cap.dispatchGateReached()", what)

    def release_dispatch(self) -> None:
        if not self.js("window.__cap.releaseDispatch()"):
            raise ScenarioFailure("dispatch gate가 무장되지 않았습니다")

    def take_dispatch_trace(self) -> list[dict]:
        value = self.js("window.__cap.takeDispatchTrace()")
        if not isinstance(value, list):
            raise ScenarioFailure("Product dispatch trace가 배열이 아닙니다")
        return value

    def exists(self, selector: str) -> bool:
        return bool(self.js(f"document.querySelector({js_literal(selector)}) !== null"))

    # ------------------------------------------------------------------ 대기

    def wait(
        self,
        expression: str,
        what: str,
        *,
        timeout: "float | None" = None,
        requires: "Sequence[str]" = (),
    ) -> None:
        """``expression`` 이 참이 될 때까지 기다린다.

        ``requires`` 는 이 걸음이 **있다고 전제하는** selector 들이다. 시한이 지나면 그것들을
        되짚어 없는 것이 있으면 :class:`MissingSurface` 로, 전부 있으면 :class:`StepTimeout`
        으로 죽는다 — 같은 침묵을 두 사건으로 가르는 자리가 여기다.

        셋째 사건이 하나 더 있다: **실행 전체 예산이 끝난 것**. 걸음의 시한은 남은 예산과의
        최솟값으로 잘리므로, 예산이 바닥나는 **정상적인 방식**은 "짧게 잘린 걸음이 시간을
        넘기는 것"이다. 그때 :class:`StepTimeout` 을 내면 전체 예산 소진이 특정 걸음의 결함으로
        둔갑한다 — 도입한 구분이 정작 가장 흔한 경우에서 무력해진다(#426 리뷰 라운드 4).
        그래서 만료 뒤 **먼저** 전체 시한을 묻는다.

        실창 경보는 네 번째 사건이다. native ``alert`` 를 그대로 열면 이 폴링 왕복이 반환하지
        않아 위 셋을 판정할 기회가 사라진다. helper 가 포획한 문안을 **같은 평가 결과**에서
        먼저 읽어, 사람의 확인이나 전체 하드 스톱을 기다리지 않고 실패시킨다.
        """
        budget = self.STEP_TIMEOUT_S if timeout is None else timeout
        budget = min(budget, max(self._deadline.remaining_s(), 0.0))
        if budget <= 0:
            raise RunDeadlineExceeded(
                f"실행 예산 {self._deadline.total_s:.0f}s 소진 — 기다리려던 것: {what}"
            )
        started = time.monotonic()
        while time.monotonic() - started < budget:
            polled = self.js(f"window.__cap.poll(() => Boolean({expression}))")
            alert = polled.get("alert")
            if alert is not None:
                raise UnexpectedNativeAlert(str(alert), what)
            if polled.get("ready"):
                return
            time.sleep(self.POLL_S)
        if self._deadline.expired():
            raise RunDeadlineExceeded(
                f"실행 예산 {self._deadline.total_s:.0f}s 소진 — 기다리던 것: {what}"
                f" (이 걸음에 남았던 시간 {budget:.1f}s)"
            )
        self._diagnose(requires, what)
        raise StepTimeout(what, expression, time.monotonic() - started)

    def _diagnose(self, requires: "Sequence[str]", what: str) -> None:
        """시한이 지난 뒤에만 부른다 — 정상 경로에 왕복을 더하지 않는다."""
        for selector in requires:
            if not self.exists(selector):
                raise MissingSurface(selector, what)

    # ------------------------------------------------------------------ 조작

    def click_sel(self, selector: str, *, what: str = "클릭 대상") -> None:
        clicked = self.js(
            f"(function(){{const el=document.querySelector({js_literal(selector)});"
            "if(!el)return false; el.click(); return true;})()"
        )
        if not clicked:
            raise MissingSurface(selector, what)

    def click_text(self, scope_selector: "str | None", text: str) -> None:
        """문안으로 버튼을 겨눈다 — 비활성 버튼은 ``__cap.btn`` 이 애초에 고르지 않는다.

        ``scope_selector`` 가 ``None`` 이면 문서 전체가 범위다(모달처럼 화면 밖에 뜨는 것).
        """
        clicked = self.js(
            f"window.__cap.clickBtn({js_literal(scope_selector)}, {js_literal(text)})"
        )
        if not clicked:
            raise MissingSurface(
                f"{scope_selector or 'document'} 안 버튼 {text!r}", "문안으로 겨눈 버튼"
            )

    def set_value(self, selector: str, value: str) -> None:
        if not self.js(
            f"window.__cap.setValue({js_literal(selector)}, {js_literal(value)})"
        ):
            raise MissingSurface(selector, f"값 {value!r} 을 넣을 입력")
        if not self.js(f"window.__cap.commitValue({js_literal(selector)})"):
            raise MissingSurface(selector, f"값 {value!r} 을 커밋할 입력")

    def scroll_to(self, selector: str) -> None:
        """대상을 뷰포트 중앙으로 — 폴드 아래 상태가 컷에서 잘리지 않게(즉시, 무모션)."""
        moved = self.js(
            f"(function(){{const el=document.querySelector({js_literal(selector)});"
            "if(!el)return false; el.scrollIntoView({block:'center',behavior:'instant'});"
            "return true;})()"
        )
        if not moved:
            raise MissingSurface(selector, "스크롤 대상")
