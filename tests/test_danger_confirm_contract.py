"""#219 — 파괴 확인의 danger 시각 언어·구체 동사 영구 가드."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "web" / "js"


def _confirm_calls(text: str) -> list[str]:
    """JS의 ``Modal.confirm(...)`` 호출을 문자열/주석을 건너 균형 괄호로 추출한다."""
    calls: list[str] = []
    marker = "Modal.confirm("
    pos = 0
    while (start := text.find(marker, pos)) != -1:
        i = start + len(marker)
        depth = 1
        quote = ""
        while i < len(text) and depth:
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = ""
                i += 1
                continue
            if ch in ("'", '"', "`"):
                quote = ch
                i += 1
                continue
            if ch == "/" and nxt == "/":
                end = text.find("\n", i + 2)
                i = len(text) if end == -1 else end + 1
                continue
            if ch == "/" and nxt == "*":
                end = text.find("*/", i + 2)
                i = len(text) if end == -1 else end + 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        assert depth == 0, "닫히지 않은 Modal.confirm 호출"
        calls.append(text[start:i])
        pos = i
    return calls


def _calls(relative: str) -> list[str]:
    return _confirm_calls((WEB_JS / relative).read_text(encoding="utf-8"))


def _call_containing(relative: str, needle: str) -> str:
    matches = [call for call in _calls(relative) if needle in call]
    assert len(matches) == 1, f"{relative}: {needle!r} confirm 호출이 {len(matches)}개"
    return matches[0]


def test_every_confirm_has_a_concrete_action_label() -> None:
    offenders: list[str] = []
    for path in WEB_JS.rglob("*.js"):
        for call in _confirm_calls(path.read_text(encoding="utf-8")):
            if "confirmLabel" not in call:
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "기본 '확인'으로 남은 Modal.confirm 호출:\n" + "\n".join(offenders)


def test_durable_destructive_confirms_are_danger() -> None:
    # unlink·덮어쓰기·제자리 변환 도달 경로 전수. needle은 호출마다 유일한 사용자 문안/판정값.
    inventory = (
        ("app.js", 'confirmLabel: "종료"'),
        ("screens/editor.js", "res.overwrite_text"),
        ("screens/editor.js", "res.dataset_text"),
        ("screens/draft.js", "body: confirmedText"),
        ("screens/draft.js", 'title: "덮어쓰기 확인", body: r.confirm_text'),
        ("screens/draft.js", 'title: "기안 작업 삭제 확인"'),
        ("screens/job.js", "body: overwriteBody(res)"),
        ("screens/job.js", 'title: "작업 삭제 확인"'),
        ("screens/home.js", "body: res.confirm_text"),
        ("screens/home.js", "작업 화면에서 이 작업을 열어 둔 실행 세션"),
        ("screens/template.js", 'r.confirm_text + "\\n\\n삭제할까요?"'),
        ("screens/template.js", 'res.confirm_text + "\\n\\n지금 변환할까요?"'),
        ("screens/pool.js", 'res.confirm_text + "\\n\\n삭제할까요?"'),
        ("screens/pool.js", 'res.confirm_text + "\\n\\n계속할까요?"'),
    )
    for relative, needle in inventory:
        call = _call_containing(relative, needle)
        assert "danger: true" in call, f"{relative}: {needle!r}에 danger 누락"
        assert "confirmLabel" in call and 'confirmLabel: "확인"' not in call


def test_transient_or_organizational_confirms_stay_neutral() -> None:
    inventory = (
        ("draftsession.js", 'title: "데이터 변경 확인"'),
        ("screens/editor.js", "미확정으로 되돌리기"),
        ("screens/job.js", 'title: "그룹 병합 확인"'),
        ("screens/template.js", "그룹을 해산하면"),
    )
    for relative, needle in inventory:
        assert "danger: true" not in _call_containing(relative, needle)


def test_danger_button_has_light_dark_and_forced_color_contract() -> None:
    modal = (WEB_JS / "modal.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
    tokens = (ROOT / "web" / "css" / "tokens.css").read_text(encoding="utf-8")
    assert 'classList.toggle("danger", !!opts.danger)' in modal
    assert 'classList.toggle("primary", !opts.danger)' in modal
    assert ".btn.danger{" in css and "background:var(--a-danger)" in css
    assert ".btn.danger:not(:disabled){background:Mark;color:MarkText" in css
    assert tokens.count("--a-danger:") >= 3  # light + OS dark + explicit dark
