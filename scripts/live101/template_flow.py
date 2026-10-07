"""SX-05 applied-template authoring and explicit Work application journey."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .surface import Surface

if TYPE_CHECKING:
    from .scenario import ScenarioContext


def _select_work(surface: Surface, name: str) -> None:
    selector = f'#jobCandidates button[data-cand={json.dumps(name, ensure_ascii=False)}]'
    surface.wait(
        f"!!document.querySelector({json.dumps(selector)})"
        f" && !document.querySelector({json.dumps(selector)}).disabled",
        f"{name} 후보 선택 가능",
        requires=["#jobCandidates"],
    )
    surface.click_sel(selector, what=f"{name} 명시 선택")
    surface.wait(
        f"document.getElementById('jobActionName').textContent.trim() === {json.dumps(name, ensure_ascii=False)}",
        f"{name} active Work",
        requires=["#jobActionName"],
    )


def _apply_staged_template(ctx: ScenarioContext, kind: str, *, confirm: bool) -> None:
    s = ctx.surface
    ctx.stage_template(kind)
    s.click_sel('.navbtn[data-scr="library"]', what=f"{kind} 적용본 저작 진입")
    s.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청서\"]')",
        f"{kind} Work 라이브러리 행",
        timeout=30.0,
        requires=["#scr-library", "#libraryList"],
    )
    s.click_sel('#libraryList [data-work="발주요청서"]', what=f"{kind} Work 상세")
    s.wait("!!document.querySelector('#libraryDetail [data-use=\"발주요청서\"]')"
           " && !!document.getElementById('libraryTemplateEdit')", f"{kind} 적용본 템플릿 편집 가능",
           timeout=30.0, requires=["#libraryDetail"])
    s.click_sel("#libraryTemplateEdit", what=f"{kind} 적용본 템플릿 편집")
    s.wait("!!document.getElementById('authoring-dock-tab-impact')", f"{kind} 저작 변경 영향 탭",
           timeout=30.0, requires=["#scr-authoring"])
    s.click_sel("#authoring-dock-tab-impact", what=f"{kind} 변경 영향 열기")
    s.wait("!!document.querySelector('[data-guide=\"apply-check\"]')", f"{kind} 적용 영향 확인",
           timeout=30.0)
    s.click_sel('[data-guide="apply-check"]', what=f"{kind} 적용 영향 확인")
    s.wait("!!document.querySelector('[data-guide=\"apply-confirm\"]:not(:disabled)')", f"{kind} 적용 준비",
           timeout=30.0)
    if confirm:
        s.click_sel('[data-guide="apply-confirm"]', what=f"{kind} 기존 Work에 적용")
        s.wait("!document.querySelector('[data-guide=\"apply-confirm\"]')", f"{kind} 적용 착지",
               timeout=30.0)
    # Closing the tab is necessary: opening the same path reuses an existing authoring session.
    s.click_sel('#scr-authoring .authoring-tab [aria-label$="닫기"]', what=f"{kind} 저작 문서 닫기")
    s.wait("!document.querySelector('#scr-authoring .authoring-tab')", f"{kind} 저작 문서 닫힘",
           requires=["#scr-authoring"])
    s.click_sel('#scr-authoring [aria-label="돌아가기"]', what=f"{kind} 저작 나가기")
    s.wait("document.querySelector('#scr-library.on') !== null", f"{kind} 라이브러리 복귀",
           requires=["#scr-library"])
    s.click_sel('.navbtn[data-scr="job"]', what=f"{kind} 문서 만들기 복귀")
    s.wait("document.querySelector('#scr-job.on') !== null", f"{kind} job 복귀", requires=["#scr-job"])
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청서'"
        " || !!document.querySelector('#jobCandidates button[data-cand=\"발주요청서\"]')",
        f"{kind} Work 연속성",
        requires=["#jobActionName", "#jobCandidates"],
    )
    if not s.js("document.getElementById('jobActionName').textContent.trim() === '발주요청서'"):
        _select_work(s, "발주요청서")
