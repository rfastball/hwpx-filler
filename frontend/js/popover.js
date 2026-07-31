/* 팝오버 공용 계약 — 등록/해제, dismissal, 위치와 전체 닫기를 한 곳에서 소유한다.
   소비자는 자기 열린 상태·inside 판정·close 동작만 등록한다. document 리스너는 표면마다
   늘리지 않고 한 벌만 두므로 메뉴와 열 패널의 focusout/scroll/Escape 동작이 갈라지지 않는다.

   바깥 pointerdown의 click 소비는 같은 primary 제스처가 실제 click으로 이어질 때만 한다.
   우클릭은 후보가 아니고, 스크롤바 drag처럼 click 없이 끝난 제스처는 pointerup 다음 task에서
   후보를 걷는다. 따라서 그 뒤 첫 정상 클릭을 잘못 삼키지 않는다. */
(function () {
  const entries = new Set();
  let suppressNextClick = null;  // { target, pointerId } — 현재 primary 제스처 하나만

  function isOpen(entry) {
    try { return !!entry.isOpen(); }
    catch (_) { return false; }
  }

  function contains(entry, target) {
    if (!(target instanceof Element)) return false;
    try { return !!entry.contains(target); }
    catch (_) { return false; }
  }

  function close(entry) {
    if (isOpen(entry)) entry.close();
  }

  /** cfg: { isOpen(), contains(target), close() } -> unregister(). */
  function register(cfg) {
    if (!cfg || typeof cfg.isOpen !== "function" || typeof cfg.contains !== "function" ||
        typeof cfg.close !== "function") {
      throw new TypeError("Popover.register requires isOpen, contains and close functions");
    }
    entries.add(cfg);
    let registered = true;
    return function unregister() {
      if (!registered) return;
      registered = false;
      entries.delete(cfg);
    };
  }

  // 기존 소비자의 이름은 유지하되 이제 공용 registry 등록자로 동작한다.
  function wireDismiss(cfg) {
    return register(cfg);
  }

  /** H-16 모달이 의존하는 안정 API. 열린 팝오버를 snapshot 순서로 모두 닫는다. */
  function closeAll() {
    Array.from(entries).forEach(close);
    suppressNextClick = null;
  }

  function sameTarget(a, b) {
    return a === b || (a instanceof Node && b instanceof Node &&
      (a.contains(b) || b.contains(a)));
  }

  document.addEventListener("click", (e) => {
    const pending = suppressNextClick;
    suppressNextClick = null;
    if (!pending || !sameTarget(pending.target, e.target)) return;
    e.stopPropagation();
    e.preventDefault();
  }, true);

  document.addEventListener("pointerdown", (e) => {
    // 이전 제스처의 후보는 새 pointerdown 경계에서 반드시 만료된다.
    suppressNextClick = null;
    let closed = false;
    Array.from(entries).forEach((entry) => {
      if (!isOpen(entry) || contains(entry, e.target)) return;
      entry.close();
      closed = true;
    });
    // right/middle click 및 보조 touch pointer는 click 소비 후보가 아니다.
    if (closed && e.button === 0 && e.isPrimary !== false) {
      suppressNextClick = { target: e.target, pointerId: e.pointerId };
    }
  }, true);

  document.addEventListener("pointerup", (e) => {
    const pending = suppressNextClick;
    if (!pending || pending.pointerId !== e.pointerId) return;
    // 호환 click은 pointerup 직후 같은 task에 발행된다. 없으면 다음 task 전에 후보를 걷는다.
    setTimeout(() => { if (suppressNextClick === pending) suppressNextClick = null; }, 0);
  }, true);
  document.addEventListener("pointercancel", () => { suppressNextClick = null; }, true);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeAll();
  }, true);

  document.addEventListener("focusout", (e) => {
    Array.from(entries).forEach((entry) => {
      if (!isOpen(entry) || !contains(entry, e.target) || contains(entry, e.relatedTarget)) return;
      entry.close();
    });
  }, true);

  // scroll은 bubble하지 않으므로 capture로 듣는다. 패널 내부 목록 스크롤은 유지하고,
  // 트리거의 조상 스크롤포트·문서 스크롤처럼 표면 바깥 scroll만 닫는다.
  document.addEventListener("scroll", (e) => {
    Array.from(entries).forEach((entry) => {
      if (isOpen(entry) && !contains(entry, e.target)) entry.close();
    });
  }, true);
  window.addEventListener("resize", closeAll);

  function clamp(value, low, high) {
    return Math.max(low, Math.min(value, Math.max(low, high)));
  }

  /**
   * 렌더되어 측정 가능한 el을 anchor 아래/위에 배치한다.
   * opts.offsetParent가 없으면 fixed 좌표, 있으면 그 요소 기준 absolute 좌표를 쓴다.
   * 실제 getBoundingClientRect 폭·높이로 viewport clamp/flip하고 transform-origin을 트리거로 맞춘다.
   */
  function place(el, anchor, opts) {
    opts = opts || {};
    const gap = opts.gap == null ? 4 : opts.gap;
    const margin = opts.margin == null ? 4 : opts.margin;
    const ar = typeof anchor.getBoundingClientRect === "function"
      ? anchor.getBoundingClientRect() : anchor;
    const measured = el.getBoundingClientRect();
    const width = measured.width;
    const height = measured.height;
    const belowSpace = window.innerHeight - margin - (ar.bottom + gap);
    const aboveSpace = ar.top - gap - margin;
    const below = height <= belowSpace || belowSpace >= aboveSpace;
    const wantedTop = below ? ar.bottom + gap : ar.top - gap - height;
    const top = clamp(wantedTop, margin, window.innerHeight - margin - height);
    const left = clamp(ar.left, margin, window.innerWidth - margin - width);
    const basis = opts.offsetParent && opts.offsetParent.getBoundingClientRect
      ? opts.offsetParent.getBoundingClientRect() : { left: 0, top: 0 };

    el.style.left = `${left - basis.left}px`;
    el.style.top = `${top - basis.top}px`;
    const originX = clamp(ar.left + ar.width / 2 - left, 8, width - 8);
    el.style.transformOrigin = `${originX}px ${below ? "top" : "bottom"}`;
    el.dataset.placement = below ? "bottom" : "top";
    return { left, top, placement: el.dataset.placement };
  }

  window.Popover = { register, wireDismiss, closeAll, place };
})();
