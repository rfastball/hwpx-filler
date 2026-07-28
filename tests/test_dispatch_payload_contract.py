"""프런트가 실제로 보내는 **페이로드 키**가 등록 스키마와 맞는가 — F6 1R P1 근본 조치.

기존 배선 가드(:mod:`tests.test_dispatch_wiring`)는 화면/액션 **이름**까지만 봤다. 그래서
액션은 등록돼 있는데 페이로드 키가 미등록인 조합이 정적으로 통과했고,
:func:`~hwpxfiller.webapp.action_registry.validate_dispatch` 가 실 브리지에서 거절하는 것을
**실앱을 띄워야만** 알 수 있었다 — 작업대 「기본 규칙으로 저장」이 실제로 그렇게 한 번도
성사되지 않았다(미등록 키 ``confirm_drift``).

헤드리스 컨트롤러 테스트는 `ctrl.dispatch()` 를 직접 불러 이 관문 **아래**로 들어가므로 이
결함류를 영영 못 본다. 그 사각을 정적 가드가 맡는다.

**읽을 수 있는 것만 센다**: 변수·spread·계산 키가 섞인 페이로드는 건너뛴다. 거짓 실패로
가드를 무디게 만드는 것보다, 읽히는 호출을 확실히 세는 편이 오래 산다(대신 최소 판독 수를
못박아 추출기가 조용히 stale 해지는 것을 막는다).
"""
from __future__ import annotations

import re
from pathlib import Path

from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "web" / "js"

#: `Bridge.call(SCREEN|'screen', "action", {…})` — 화면 상수 또는 리터럴 화면 이름.
_CALL = re.compile(
    r"Bridge\.call\(\s*(?:SCREEN|['\"](?P<screen>[a-z]+)['\"])\s*,\s*"
    r"['\"](?P<action>[a-z0-9_]+)['\"]\s*,\s*"
)

#: 최상위 키 1개의 형태 — `key:` · `"key":` · ES6 축약 `key`(콜론 없음).
_KEY = re.compile(r"^(?:\"(?P<q>[A-Za-z_][\w]*)\"|(?P<b>[A-Za-z_][\w]*))\s*(?::|$)")

#: 화면 상수(`SCREEN`)의 소유 화면 — 공용 모듈은 화면을 인자로 받으므로 여기 두지 않는다.
SCREEN_OF_FILE = {
    "screens/library.js": "library",
    "screens/editor.js": "editor",
    "screens/job.js": "job",
    "screens/draft.js": "draft",
    "screens/template.js": "tpl",
    "screens/workbench.js": "workbench",
    "data_picker.js": "pool",
}


def _top_level_parts(body: str) -> "list[str] | None":
    """객체 리터럴 본문을 **최상위 쉼표**로 가른다 — 문자열·중첩 괄호 안의 쉼표는 무시.

    따옴표를 세는 이유는 `{ text: "a, b" }` 같은 페이로드가 실제로 있기 때문이다. 정규식
    한 방으로 자르면 그런 값이 키로 둔갑해 **거짓 실패**가 나고, 거짓 실패는 가드를 무디게
    만든다(다음 사람이 그냥 skip 목록에 넣는다).
    """
    parts, buf, depth, quote = [], [], 0, ""
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                buf.append(ch)
                i += 1
                if i < len(body):
                    buf.append(body[i])
                i += 1
                continue
            if ch == quote:
                quote = ""
            buf.append(ch)
        elif ch in "\"'`":
            quote = ch
            buf.append(ch)
        elif ch in "{[(":
            depth += 1
            buf.append(ch)
        elif ch in "}])":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quote or depth:
        return None                      # 잘린 리터럴 — 정적 판독 포기
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _object_literal(text: str, at: int) -> "str | None":
    """`at` 위치에서 시작하는 객체 리터럴 본문(중괄호 안). 리터럴이 아니면 None."""
    rest = text[at:]
    if not rest.startswith("{"):
        return None                      # 변수·표현식 페이로드 — 정적 판독 대상 아님
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return rest[1:i]
    return None


def test_literal_frontend_payloads_match_the_registered_schema() -> None:
    offenders: list[str] = []
    checked = 0
    for relative, owner in SCREEN_OF_FILE.items():
        path = WEB_JS / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _CALL.finditer(text):
            screen = match.group("screen") or owner
            action = match.group("action")
            schema = ACTION_REGISTRY.get(screen, {}).get(action)
            if schema is None:
                continue                  # 이름 계약은 test_dispatch_wiring 이 본다
            body = _object_literal(text, match.end())
            if body is None or "..." in body:
                continue
            parts = _top_level_parts(body)
            if parts is None:
                continue
            keys, readable = set(), True
            for part in parts:
                m = _KEY.match(part)
                if m is None:            # 계산 키 `[x]:` 등 — 정적으로 못 읽는다
                    readable = False
                    break
                keys.add(m.group("q") or m.group("b"))
            if not readable:
                continue
            checked += 1
            unexpected = keys - schema.allowed
            missing = schema.required - keys
            if unexpected or missing:
                offenders.append(
                    f"{relative}: {screen}/{action} "
                    f"미등록 키={sorted(unexpected)} 필수 누락={sorted(missing)}"
                )
    assert checked >= 40, f"리터럴 페이로드를 너무 적게 읽었습니다({checked}) — 추출기 stale?"
    assert not offenders, (
        "프런트 페이로드가 등록 스키마와 어긋납니다 — 실 브리지가 거절합니다:\n"
        + "\n".join(offenders)
    )


#: 이 가드가 **적용되는 화면** — 자기 화면 파일 하나가 자기 액션을 전부 부르는 곳.
#: 나머지 화면은 공용 팩토리(`datazone.js`·`draftsession.js`·`intent.js`·`guard.js`)가
#: 화면을 **변수**로 받아 발신하므로 정적 귀속이 성립하지 않는다 — 거기까지 억지로 세면
#: 거짓 실패가 쏟아지고, 거짓 실패는 가드를 무디게 만든다(다음 사람이 목록에 넣고 잊는다).
#: 범위를 좁히는 대신 **그 안에서는 예외를 두지 않는다**.
SELF_CONTAINED_SCREENS = {"workbench"}

#: 위 화면에서 프런트 소비자가 **없어도 되는** 액션 — 사유를 여기 적는다. 조용한 무시와
#: 선언된 배제는 다르다(F5 판정 O·F7 판정 K 선례). 지금은 비어 있다: 작업대의 모든 액션은
#: 자기 화면이 부른다.
NO_FRONTEND_CONSUMER: "set[tuple[str, str]]" = set()


def test_every_registered_action_has_a_frontend_consumer() -> None:
    """등록만 되고 **아무도 부르지 않는** 액션이 남지 않는가(F6 4R P2).

    작업대가 `set_target_font`·`set_current` 를 등록하고 스냅샷까지 실었지만 그것을 부르는
    DOM 이 하나도 없었다 — 사용자는 대상 글꼴을 고칠 수도(정렬 린트가 그 선언으로 판정하는데),
    아는 행으로 바로 갈 수도 없었다. F7 판정 K 가 같은 말을 해 뒀다: "열거값을 만들어 두고
    아무도 안 쓰면, 나중에 그 자리에 배선을 빠뜨려도 아무 테스트도 울지 않는다."

    이 가드는 앞 테스트의 **반대 방향**이다(앞 = 소비자가 있는데 규약이 틀림 / 여기 =
    규약이 있는데 소비자가 없음). 둘이 짝을 이뤄야 「표면과 백엔드가 한 벌로 옮겨졌는가」를
    센다 — 3R·4R 이 각각 그 한쪽이었다.
    """
    called: "set[tuple[str, str]]" = set()
    for relative, owner in SCREEN_OF_FILE.items():
        path = WEB_JS / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _CALL.finditer(text):
            called.add((match.group("screen") or owner, match.group("action")))
    orphans = sorted(
        f"{screen}/{action}"
        for screen in SELF_CONTAINED_SCREENS
        for action in ACTION_REGISTRY.get(screen, {})
        if (screen, action) not in called and (screen, action) not in NO_FRONTEND_CONSUMER
    )
    assert not orphans, (
        "등록됐지만 프런트가 부르지 않는 액션입니다 — 배선하거나 "
        "NO_FRONTEND_CONSUMER 에 사유와 함께 적으세요:\n" + "\n".join(orphans)
    )
