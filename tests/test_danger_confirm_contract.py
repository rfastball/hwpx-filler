"""#219 — 파괴 확인의 danger 시각 언어·구체 동사 영구 가드."""
from __future__ import annotations

from _web_source import REPO_ROOT, SOURCE_CSS_DIR, SOURCE_JS_DIR, SOURCE_ROOT, app_css


WEB_JS = SOURCE_JS_DIR


def _confirm_calls(text: str) -> list[str]:
    """JS의 ``Modal.confirm(...)`` 호출을 문자열/주석을 건너 균형 괄호로 추출한다."""
    calls: list[str] = []
    markers = ("Modal.confirm(", "deps.modal.confirm(", "modal.confirm(")
    pos = 0
    while True:
        found = [(text.find(marker, pos), marker) for marker in markers]
        found = [(start, marker) for start, marker in found if start != -1]
        if not found:
            break
        start, marker = min(found)
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
    return _confirm_calls((SOURCE_ROOT / relative).read_text(encoding="utf-8"))


def _call_containing(relative: str, needle: str) -> str:
    matches = [call for call in _calls(relative) if needle in call]
    assert len(matches) == 1, f"{relative}: {needle!r} confirm 호출이 {len(matches)}개"
    return matches[0]


def test_every_confirm_has_a_concrete_action_label() -> None:
    offenders: list[str] = []
    paths = [*WEB_JS.rglob("*.js"), *(SOURCE_ROOT / "src").rglob("*.ts")]
    for path in paths:
        for call in _confirm_calls(path.read_text(encoding="utf-8")):
            if "confirmLabel" not in call:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, "기본 '확인'으로 남은 Modal.confirm 호출:\n" + "\n".join(offenders)


def test_durable_destructive_confirms_are_danger() -> None:
    # unlink·덮어쓰기·제자리 변환 도달 경로 전수. needle은 호출마다 유일한 사용자 문안/판정값.
    inventory = (
        ("js/app.js", 'confirmLabel: "종료"'),
        ("js/screens/editor.js", "res.overwrite_text"),
        # (editor 의 자동등록 확인(res.dataset_text)은 #347 에서 게이트째 사망 — U2 §5.3 D.)
        # (screens/draft.js 두 행 삭제 — 「기안」 화면 사망, F6 PR-B. 덮어쓰기 확인의
        #  생존 표면은 editor·job 행이 계속 진다.)
        ("js/screens/job.js", "body: overwriteBody(res)"),
        ("src/screens/library.ts", 'body: result.confirm_text, confirmLabel: "삭제"'),
        # 누름틀 제자리 변환 확인 — 거처가 편집기 「템플릿」 탭 ⋮ 로 이주(F8, tpl 화면 사망).
        ("js/screens/editor.js", 'res.confirm_text + "\\n\\n지금 변환할까요?"'),
        # 등록 데이터 삭제·같은 데이터 라벨 갱신·다시 연결 — 거처는 데이터 선택 다이얼로그(F1).
        ("src/screens/data_picker.ts", 'first.confirm_text}\\n\\n삭제할까요?'),
        ("src/screens/data_picker.ts", "body: result.confirm_text"),
        # 구판 중복 등록 병합(#347 §5.3) — 이름·메모가 다른 등록을 지우는 파괴 확정.
        ("src/screens/data_picker.ts", 'first.confirm_text}\\n\\n정리할까요?'),
    )
    for relative, needle in inventory:
        call = _call_containing(relative, needle)
        assert "danger: true" in call, f"{relative}: {needle!r}에 danger 누락"
        assert "confirmLabel" in call and 'confirmLabel: "확인"' not in call


def test_transient_or_organizational_confirms_stay_neutral() -> None:
    inventory = (
        # (draftsession.js 「데이터 변경 확인」·screens/draft.js 「기안 작업 삭제 확인」 행
        #  삭제 — 「기안」 화면 사망, F6 PR-B.)
        ("js/screens/editor.js", "미확정으로 되돌리기"),
        # 좌 목록 사망(F2 PR-B)으로 두 문안의 거처가 라이브러리로 옮겼다 — 표면이 옮겨도
        # 「되돌릴 수 있는 조직 행위는 danger 로 물들이지 않는다」는 계약은 따라간다.
        ("src/screens/library.ts", 'title: "그룹 병합 확인"'),
        ("src/screens/library.ts", 'title: "작업 삭제 확인"'),
        # 그룹 해산 — 거처가 편집기 「템플릿」 탭 그룹 ⋮ 로 이주(F8, 문안 계약 불변).
        ("js/screens/editor.js", "그룹을 해산하면"),
    )
    for relative, needle in inventory:
        assert "danger: true" not in _call_containing(relative, needle)


def test_danger_button_has_light_dark_and_forced_color_contract() -> None:
    # R3-01(#410): danger 판정(불리언)은 파사드가 spec 으로 싣고, 같은 안정 버튼의 **양방향
    # 토글 집행**은 React host 컨트롤러가 진다 — 두 거처를 각각 겨눈다(단방향만 남으면
    # danger 뒤 중립 confirm 이 빨갛게 남는 상태 누수가 재발한다).
    modal = (WEB_JS / "modal.js").read_text(encoding="utf-8")
    host = (WEB_JS.parent / "src" / "overlay" / "host.ts").read_text(encoding="utf-8")
    # `.btn.danger{`(base.css)와 forced-colors 의 `Mark` 강등(forced-colors.css)이 서로 다른
    # 조각에 살지만, 이어붙인 문자열에서는 한 단언이 둘 다 본다.
    css = app_css()
    tokens = (SOURCE_CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    assert "danger: !!opts.danger" in modal
    assert 'classList.toggle("danger", spec.danger)' in host
    assert 'classList.toggle("primary", !spec.danger)' in host
    assert ".btn.danger{" in css and "background:var(--a-danger)" in css
    assert ".btn.danger:not(:disabled){background:Mark;color:MarkText" in css
    assert tokens.count("--a-danger:") >= 3  # light + OS dark + explicit dark
