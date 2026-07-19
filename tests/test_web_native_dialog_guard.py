"""네이티브 다이얼로그 재유입 방지 가드(#86, R-flow 부록 B-2) — ``web/js`` 에서
``window.confirm``·``window.prompt`` 검출 금지.

네이티브 ``confirm`` 은 Enter-반사로 파괴 동작이 무의식 통과되는 결함 클래스(F7)라, 확인은
공유 ``Modal.confirm``/``Modal.prompt``(Promise 기반, 기본 포커스=취소·Escape=머무르기)로 전수
이관했다(#86). ``window.alert`` 은 통지 성격(Enter-반사 파괴 위험 없음)이라 범위 밖 — 허용한다.

주석은 개발자 대상이라 스캔에서 제외한다(``test_ux_copy_round`` 의 ``_strip_js_comments`` 관례
미러 — modal.js 는 헬퍼 설명에 ``window.confirm`` 을 언급하는데 그건 블록 주석이라 걷힌다).
양성대조로 스캐너가 실제로 검출하는지 함께 단언한다(measurement-litmus: 프로브 음성은 부재
판별력을 먼저 증명해야 신뢰한다).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_FILES = sorted((ROOT / "web" / "js").rglob("*.js"))

# window.alert 은 통지 성격이라 의도적으로 제외한다(별도 후속 검토).
BANNED = ("window.confirm", "window.prompt")


def _strip_js_comments(text: str) -> str:
    """블록 주석 전부 + 공백이 선행하는 줄끝 // 주석 제거 — 남는 본문은 코드·문자열.

    ``test_ux_copy_round._strip_js_comments`` 와 동일 규약. 헬퍼 설명(modal.js)이 금지어를
    언급해도 주석이라 걷혀 오탐하지 않는다.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", text)


def test_no_native_confirm_or_prompt_in_web_js():
    """web/js 코드(주석 제외)에 window.confirm·window.prompt 가 없어야 한다(#86)."""
    offenders = []
    for p in JS_FILES:
        body = _strip_js_comments(p.read_text(encoding="utf-8"))
        for term in BANNED:
            for m in re.finditer(re.escape(term), body):
                line = body.count("\n", 0, m.start()) + 1
                offenders.append(f"{p.relative_to(ROOT).as_posix()}:{line}: '{term}'")
    assert not offenders, (
        "네이티브 다이얼로그가 web/js 에 재유입됐습니다 — Modal.confirm/Modal.prompt 로 "
        "이관하세요(#86, Enter-반사 파괴 결함 F7):\n" + "\n".join(offenders)
    )


def test_window_alert_is_out_of_scope():
    """window.alert 은 통지 성격이라 가드 대상이 아님을 고정한다(범위 오확장 방지)."""
    assert not any(term in "window.alert('알림');" for term in BANNED)


def test_guard_detects_positive_control():
    """양성대조 — 스캐너가 실제로 두 금지어를 검출하는지(부재 판별력 선증명)."""
    sample = "if (window.confirm('x')) {}\nconst v = window.prompt('y');"
    hits = {t for t in BANNED if t in _strip_js_comments(sample)}
    assert hits == {"window.confirm", "window.prompt"}


def test_comment_mention_does_not_trip_guard():
    """양성대조 짝 — 블록 주석 안의 금지어는 스캔에서 걷혀야 한다(오탐 없음 확인)."""
    sample = "/* window.confirm 은 이제 Modal.confirm 이 대체한다 */\nModal.confirm({});"
    assert not any(term in _strip_js_comments(sample) for term in BANNED)
