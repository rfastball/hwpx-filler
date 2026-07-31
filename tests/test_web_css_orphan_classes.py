"""고아 class 게이트 — 셸이 내는 class 중 **규칙이 한 줄도 없는 것**을 시끄럽게 만든다.

이 게이트가 없어서 통과한 사고가 있다. `67894b0`(F6 PR-B, 「기안」 화면 사망)이
`.draft-duo` 계열을 지우면서 **곁달린 공유 규칙까지 함께** 지웠다::

    .job-zones{...}                       ← job 세션 표면의 단일 카드
    .zone{padding:var(--sp-16) ...}       ← 존 패딩
    .zone + .zone{border-top:...}         ← 인접 존 구분선
    .zone-cap{display:block;...}          ← 존 캡션의 블록화

`.draft-duo` 는 화면과 함께 죽는 게 맞았지만 위 넷은 **살아 있는 「문서 만들기」가 쓰던
것**이다. 결과는 조용했다 — DOM 은 그대로 `class="zone"` 을 내고, 브라우저는 규칙 없는
class 에 대해 아무 말도 하지 않는다. 존 패딩 0 · 구분선 소멸 · 캡션이 인라인 흐름에 섞임이
실사용 피드백 3건으로 돌아오기까지 두 슬라이스가 지났다.

더 나쁜 것은 **주석이 같은 커밋에서 고쳐졌다**는 점이다:

    - ... zone-cap 은 인라인 섹션 헤더. job·draft 공통(둘 다 .zone). */
    + ... zone-cap 은 인라인 섹션 헤더. job 소유(.zone). */

규칙을 지운 손이 "이제 job 이 `.zone` 을 소유한다"고 적어 뒀다. 흔적으로도 못 잡는다.

**기존 게이트가 왜 못 잡는가.** `test_web_css_manifest.py` 는 *파일* 단위다(링크 순서·전수
등재·주석 균형). 파일이 통째로 검사 밖으로 새는 것은 막지만, **등재된 파일 안에서 규칙이
편집돼 사라지는 것**은 못 본다 — 세 테스트 모두 `.zone` 이 없는 상태에서 초록이었다.

**이 그물은 한 방향이다.** DOM → CSS(내는데 규칙이 없다)만 잡고, 반대 방향(CSS 에만 있고
생산자가 없는 죽은 선택자 — 지금 `.job-master`·`.master-splitter`·`.job-row`·`.job-item`)은
잡지 않는다. 초기 오탐 정리가 별건 규모라 세우지 않았고, 그 사실을 여기 적어 둔다(조용한
축소 금지). 죽은 CSS 정리는 이슈 #325(CSS 소유권 재정렬) 소관이다.

**이름이 변수를 거쳐 가도 본다**(리뷰 R1). 첫 판은 `class="..."` 와 따옴표가 **붙어 있는**
대입만 읽어서, `job.js` 의 `mark.className = MARK`(`const MARK = "openingMark"`)나 `app.js` 의
`classList.toggle(im.cls, ...)`(`{ cls: "editor-open" }`)가 내는 class 를 한 줄도 못 봤다 —
그 규칙을 지워도 이 게이트가 초록이면 **그물이 있다는 착각만 남는다**(이 파일이 막으려던
바로 그 사고). 그래서 sink(`className=` · `classList.add/remove/toggle`)의 **식**을 읽고 세
경로로 이름을 회수한다: ⑴ 문자열 리터럴 ⑵ 같은 파일의 `const/let/var` 리터럴 결속 ⑶ 같은
파일의 객체 속성 리터럴 결속(`cls: "editor-open"`). 이름을 **하나도** 못 얻은 sink 는
조용히 넘기지 않고 시끄럽게 실패한다 — 못 읽는 sink 가 늘면 그물이 다시 구멍 난다.

**보간도 읽는다**(리뷰 R2). `class="job-cand-card${active ? " active" : ""}"` 처럼 보간 안에
따옴표가 있으면 `class="([^"]*)"` 가 속성 끝이 아니라 그 따옴표에서 멈춰 **앞의 온전한
이름까지** 통째로 못 봤다. 그래서 속성을 읽기 **전에** `${...}` 를 짝 맞춰 펼친다. 펼친
결과가 온전한 class 목록인지(모든 갈래가 공백으로 시작 — `" active"`) 아니면 이름의
반쪽인지(`col-${kind}`)는 **갈래의 앞 공백**이 가른다.

**붙어 있는 이웃이 있을 때만 앞 공백을 따진다**(리뷰 R4). 속성 전체가 보간이면
(`class="${cls}"`) 갈래 자체가 온전한 이름이라 앞 공백을 요구할 이유가 없다 — 그 규칙을
무조건 걸어 `segview.js` 의 `const cls = ... "seg-fill"` 를 통째로 놓쳤다. 다만 결속을 읽을 때
**호출·대기가 있는 초기화식은 이름의 출처가 아니다**: `const r = await Bridge.call(screen,
"load_pool", …)` 의 리터럴은 액션 이름인데 `r` 은 흔한 이름이라 다른 자리의 `${r.badge_level}`
로 새어 `.load_pool` 을 요구하는 오탐이 됐다.

**보간의 안은 지우지 않는다**(리뷰 R3). 반쪽인 경우를 통째로 구멍으로 바꿨더니 보간 안에
들어앉은 마크업(`${v ? esc(v) : "<em class='muted'>(빈 값)</em>"}`)이 검사 밖으로 사라졌다 —
구멍은 **경계 표시**여야지 내용을 없애는 도구가 아니다. 경계만 표시하고 안은 같은 규칙으로
다시 펼쳐 남긴다. 속성은 **두 따옴표 다** 받는다(같은 리뷰): 형태를 세어서 규칙을 고르면
다음 사람이 다른 쪽으로 적는 날 눈을 감는다.

**조각은 버리지 않고 이어 붙인다**(리뷰 R2). `"wc-render f-" + (font || "gulimche")` 의 앞뒤를
둘 다 버리면 코드에 그대로 적혀 있는 `f-gulimche` 를 못 본다 — 그 규칙을 지워도 게이트가
초록이고, 작업대는 조용히 폴백 글꼴로 그려진다. 뒤가 리터럴이면 합성하고(`f-` + `gulimche`),
런타임 값이면 그때만 버린다. **비교 피연산자**(`level === "danger"`)는 값이지 class 가
아니므로 이것만 걷어낸다 — 안 걷으면 `.danger` 를 요구하는 오탐이 된다.

남는 구멍 하나는 적어 둔다: **값이 Python 에서 오는 tail**(`"note " + (s.notice.level || ...)`,
`f-` + `target_font` 의 나머지 두 글꼴)은 리터럴이 코드에 없어 못 본다. 그 자리는 링1 이
내는 문자열이라 이 그물이 아니라 스냅샷 계약과 이름을 가진 가드가 지킨다 — 글꼴 3종은
`tests/test_workcard_contract.py::test_workbench_card_wears_the_render_and_font_classes` 가
`.wc-render.f-*` 규칙의 존재를 직접 단언한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from _web_source import REPO_ROOT, SOURCE_CSS_DIR, SOURCE_INDEX, SOURCE_JS_DIR

ROOT = REPO_ROOT
#: 검사 대상 — 배포되는 셸과 화면 JS 전수(이름 회수·미해독 판정이 같은 목록을 본다).
_SOURCES = [SOURCE_INDEX, *sorted(SOURCE_JS_DIR.glob("**/*.js"))]

#: 규칙이 없어도 정당한 class — **사유 없이는 등재하지 않는다**.
#:
#: 두 부류뿐이다: ⑴ JS 가 동작으로만 소비하는 훅(`classList.contains`·`closest`·
#: `querySelector`) ⑵ 스타일 없이 의미만 표시하는 구조 표지. 「나중에 스타일 붙일 것」은
#: 사유가 아니다 — 그건 지금 없는 것이고, 붙일 때 등재를 지우면 된다.
STYLELESS_BY_DESIGN: dict[str, str] = {
    # ⑴ 동작 훅 — 이벤트 위임의 판별자로만 쓰인다.
    "ck": "작업대 매핑 체크박스 판별자(workbench.js 위임)",
    "mapfmt": "표시형 select 판별자(workbench.js:388 classList.contains)",
    "maptype": "타입 select 판별자(workbench.js:386 classList.contains)",
    "maprev": "자동 복귀 버튼 판별자(workbench.js:399 closest)",
    "ign-fold": "미사용 헤더 접힘 상태 되읽기(editor.js:79 querySelector)",
    "tok-fold": "파일명 토큰 참조 접힘 상태 되읽기(editor.js:81 querySelector)",
    # ⑵ 구조 표지 — 스타일은 부모·형제가 지고, 이름은 자리를 말한다.
    "cand-run": "후보 카드의 마지막 실행 줄 표지(스타일은 .job-cand-card 가 진다)",
    "cp-loading": "열 필터 패널 로딩 상태 표지(스타일은 .cp-sec 가 진다)",
    "mapfmt-cell": "작업대 매핑 표시형 칸 표지(폭 규칙은 형제 .maptype-cell 만 갖는다)",
    "mapval-cell": "작업대 매핑 값 칸 표지(폭 규칙은 형제 .maptype-cell 만 갖는다)",
    "job-data-zone": "세션 좌열 「현재 데이터」 존의 자리 표지(스타일은 .zone)",
    "job-mirror-zone": "세션 좌열 「본문 확인」 존의 자리 표지(스타일은 .zone)",
    "job-result-zone": "세션 좌열 「생성 결과」 존의 자리 표지(스타일은 .zone)",
    "job-cands-row": "세션 우열 후보 구획의 자리 표지(스타일은 .zone)",
    # (job-active-zone 은 「선택한 작업」 존 사망 — U2 §4 · #342 — 과 함께 걷혔다.
    #  등재가 실물을 앞지르면 아래 대조 테스트가 잡는다.)
    "tb": "표 골격 판별자 — 스타일은 결합 이름(.jobtb·.lib-bindings)이 진다"
          "(구 .tb.mir 사망 — U2 §2.13)",
    "preview-sheet-body": "확인 면 본문 자리 표지(스타일은 .sheet-body 가 진다 — U2 §2.13)",
}

#: 템플릿 보간 자리 표식 — `class="col-${i}"` 의 `col-` 같은 **조각**은 class 이름이 아니다.
_HOLE = "\x00"

#: class 속성 — **두 따옴표 다**(리뷰 R3). 셸이 쓰는 형태를 세어서 고르지 않고 문법을 받는다:
#: 홑따옴표는 지금 2곳뿐이지만(`job.js` 의 `class='muted'`), 「지금 적은 쪽만」 읽는 규칙은
#: 다음 사람이 다른 쪽으로 적는 날 조용히 눈을 감는다. 못 읽는 형태는 아래 테스트가 시끄럽다.
_CLASS_ATTR = re.compile(r"""class\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_CLASS_NAME_ASSIGN = re.compile(r"\.className\s*=\s*([^;]+);")
_CLASS_LIST = re.compile(r"classList\.(add|remove|toggle)\s*\(")
_STRING_LIT = re.compile(r"\"([^\"]*)\"|'([^']*)'|`([^`]*)`")
_IDENT = re.compile(r"[A-Za-z_][\w-]*\Z")

#: 비교 피연산자 — `level === "danger"` 의 `"danger"` 는 값이지 class 가 아니다.
_COMPARED_LIT = re.compile(r"(?:===|!==|==|!=)\s*(?:\"[^\"]*\"|'[^']*')")
#: 변수 결속 — `const MARK = "openingMark"` 처럼 **리터럴만** 받는 이름.
_LITERAL_BINDING = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)"
)
#: 이름 값이 **아닌** 초기화식 — 호출·대기가 있으면 그 결속의 리터럴은 인자일 뿐이다(리뷰 R4).
#: `const r = await Bridge.call(screen, "load_pool", {...})` 의 `"load_pool"` 은 액션 이름이지
#: class 가 아닌데, `r` 은 흔한 이름이라 다른 자리의 `${r.badge_level}` 로 그대로 새어 들어왔다.
_NOT_A_NAME_SOURCE = re.compile(r"\(|\bawait\b|\bnew\b")
#: 객체 속성 결속 — `{ cls: "editor-open" }`. sink 가 `im.cls` 로 읽는 자리의 유일한 출처.
_PROP_BINDING = re.compile(r"\b([A-Za-z_$][\w$]*)\s*:\s*(\"[^\"]*\"|'[^']*')")
_BARE_IDENT = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)")
_MEMBER_PROP = re.compile(r"\.([A-Za-z_$][\w$]*)")


def _raw_literals(expr: str) -> "list[str]":
    """식 안의 문자열 리터럴을 **원문 그대로**(앞뒤 공백 포함) 순서대로.

    이름 회수는 공백을 지우지만, 보간이 온전한 class 를 더하는지(`" active"`)와 앞 조각의
    꼬리인지(`"gulimche"`)를 가르는 것이 **바로 그 앞 공백**이라 여기선 보존한다.
    """
    return [
        double or single or backtick
        for double, single, backtick in _STRING_LIT.findall(_COMPARED_LIT.sub(" ", expr))
    ]


def _raw_bindings(text: str) -> "dict[str, list[str]]":
    """`const dirty = s.dirty ? " dirty" : ""` 처럼 **보간이 읽는** 이름 → 원문 리터럴들."""
    out: "dict[str, list[str]]" = {}
    for name, init in _LITERAL_BINDING.findall(text):
        if _NOT_A_NAME_SOURCE.search(init):
            continue
        got = _raw_literals(init)
        if got:
            out.setdefault(name, []).extend(got)
    return out


def _interpolation_end(text: str, start: int) -> int:
    """`${` 의 `{` 위치에서 짝 맞는 `}` 의 위치 — 문자열 안의 중괄호·따옴표는 세지 않는다."""
    depth = 0
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def _expand_interpolations(text: str, bindings: "dict[str, list[str]]") -> str:
    """`${...}` 를 **그 자리가 낼 수 있는 것**으로 바꾼다 — 이름이면 펼치고, 조각이면 구멍.

    두 가지를 동시에 푼다(리뷰 R2). ⑴ `class="job-cand-card${active ? " active" : ""}"` 처럼
    보간 **안에 따옴표**가 있으면 `class="([^"]*)"` 는 속성 끝이 아니라 그 따옴표에서 멈춰,
    앞의 온전한 이름(`job-cand-card`)까지 통째로 못 봤다. ⑵ 보간이 내는 것이 **온전한
    class 목록**인지(모든 갈래가 공백으로 시작) 아니면 **이름의 반쪽**(`col-${kind}`)인지는
    갈래의 앞 공백이 가른다 — 앞엣것은 펼치고 뒤엣것만 구멍으로 남긴다.
    """
    out: "list[str]" = []
    i = 0
    while True:
        at = text.find("${", i)
        if at < 0:
            out.append(text[i:])
            return "".join(out)
        end = _interpolation_end(text, at + 1)
        inner = text[at + 2:end]
        alternatives = _raw_literals(inner)
        for ident in _BARE_IDENT.findall(_STRING_LIT.sub(" ", inner)):
            alternatives.extend(bindings.get(ident, []))
        # 이 보간이 **이름 하나로 통째로 서는가** — 붙어 있는 이웃이 있는지로 가른다(리뷰 R4).
        # 앞뒤가 공백이거나 따옴표 경계면(`class="${cls}"`) 갈래 자체가 온전한 이름이므로 앞
        # 공백을 요구할 이유가 없다. 붙어 있을 때만(`job-cand-card${...}`) 앞 공백이 「이름을
        # 더하는가 vs 반쪽인가」를 가른다. 첫 판은 이 구분 없이 늘 앞 공백을 요구해
        # `segview.js` 의 `const cls = ... "seg-fill"` → `class="${cls}"` 를 통째로 놓쳤다.
        glued = bool(text[at - 1:at].strip()) and text[at - 1:at] not in "\"'`"
        tail = text[end + 1:end + 2]
        glued = glued or (bool(tail.strip()) and tail not in "\"'`")
        whole = bool(alternatives) and (
            not glued or all(not alt or alt[:1].isspace() for alt in alternatives)
        )
        out.append(text[i:at])
        if whole:
            out.append(" " + " ".join(alternatives) + " ")
        else:
            # **안을 지우지 않는다**(리뷰 R3 근본): 보간 안에는 중첩 템플릿이 통째로 들어앉기도
            # 한다(`${v ? esc(v) : "<em class='muted'>(빈 값)</em>"}`). 통째로 구멍으로 바꾸면
            # 그 안의 속성·sink 가 검사 밖으로 사라져, 그 자리에만 있는 class 는 규칙을 잃어도
            # 게이트가 조용하다. 경계만 구멍으로 표시하고(바깥 이름과 붙어 한 토큰이 되지 않게)
            # 안은 **같은 규칙으로 다시** 펼쳐 그대로 검사에 남긴다.
            out.append(_HOLE + _expand_interpolations(inner, bindings) + _HOLE)
        i = end + 1


def _tokens(raw: str) -> set[str]:
    """공백으로 가른 뒤 **온전한 이름만** 남긴다(보간 조각·비식별자는 버린다).

    조각은 두 모양으로 온다: 템플릿 보간(`class="col-${i}"`)은 구멍 표식이 남고, 문자열
    이어붙이기(`className = "wc-render f-" + font`)는 **끝이 하이픈**으로 끊긴다. 뒤엣것은
    정규식이 볼 수 없는 경계라 하이픈으로 판별한다 — 실제 class 이름은 하이픈으로 끝나지
    않으므로(웹 자산 전수 확인) 이 규칙이 진짜 이름을 삼키지 않는다.
    """
    return {
        t for t in raw.split()
        if _HOLE not in t and not t.endswith("-") and _IDENT.match(t)
    }


def _literal_names(expr: str) -> set[str]:
    """식 안의 **문자열 리터럴**에서 온전한 class 이름을 거둔다 — 조각은 이어 붙여서.

    조각 이어붙이기(`"wc-render f-" + (font || "gulimche")`)는 정규식이 볼 수 없는 경계라
    **끝이 하이픈**인 토큰으로 판별한다(실제 class 이름은 하이픈으로 끝나지 않는다 — 웹 자산
    전수 확인). 종전엔 앞뒤를 **둘 다 버려서** 코드에 그대로 적혀 있는 `f-gulimche` 를 못 봤고,
    그 규칙을 지워도 게이트가 초록이었다(리뷰 R2). 이제 **합성한다**: 뒤 리터럴이 리터럴이면
    `f-` + `gulimche` 로 이어 붙이고, 구멍(런타임 값)이면 그때만 버린다.
    """
    names: set[str] = set()
    pending = ""  # 하이픈으로 끊긴 앞 조각 — 다음 리터럴의 첫 토큰과 합성 대기
    for raw in _raw_literals(expr):
        parts = raw.split()
        if pending:
            if parts and _HOLE not in parts[0]:
                composed = pending + parts[0]
                if _IDENT.match(composed):
                    names.add(composed)
                parts = parts[1:]
            pending = ""
        # 마지막 토큰이 공백으로 끝나지 않고 하이픈으로 끊겼으면 다음 리터럴이 그 꼬리다.
        if parts and parts[-1].endswith("-") and not raw[-1:].isspace():
            pending = parts[-1]
            parts = parts[:-1]
        names |= {p for p in parts if _HOLE not in p and not p.endswith("-") and _IDENT.match(p)}
    return names


def _sink_names(expr: str, bindings: dict[str, set[str]], props: dict[str, set[str]]) -> set[str]:
    """class sink 한 자리의 식 → 그 자리가 낼 수 있는 이름들(리터럴 + 결속 회수)."""
    expr = _COMPARED_LIT.sub(" ", expr)
    names = _literal_names(expr)
    # 리터럴을 걷어낸 뒤에야 식별자를 본다 — 문자열 **안**의 단어가 변수 이름으로 읽히지
    # 않게(`"note warnbox"` 의 `note` 는 식별자가 아니다).
    bare = _STRING_LIT.sub(" ", expr)
    for ident in _BARE_IDENT.findall(bare):
        names |= bindings.get(ident, set())
    for prop in _MEMBER_PROP.findall(bare):
        names |= props.get(prop, set())
    return names


def _bindings(text: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """같은 파일의 리터럴 결속 — 변수(`const MARK = "openingMark"`)와 속성(`cls: "..."`)."""
    variables: dict[str, set[str]] = {}
    for name, init in _LITERAL_BINDING.findall(text):
        if _NOT_A_NAME_SOURCE.search(init):
            continue
        got = _literal_names(_COMPARED_LIT.sub(" ", init))
        if got:
            variables.setdefault(name, set()).update(got)
    properties: dict[str, set[str]] = {}
    for name, literal in _PROP_BINDING.findall(text):
        got = _literal_names(literal)
        if got:
            properties.setdefault(name, set()).update(got)
    return variables, properties


def _arg_body(text: str, open_paren: int) -> str:
    """`(` 위치에서 짝 맞는 `)` 까지의 인자 본문."""
    depth = 0
    for i in range(open_paren, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
    return text[open_paren + 1:]


def _first_arg(args: str) -> str:
    """최상위 첫 인자 — `toggle(cls, force)` 의 둘째 인자는 조건식이지 이름이 아니다."""
    depth = 0
    for i, ch in enumerate(args):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return args[:i]
    return args


def _class_sinks(text: str) -> list[str]:
    """이 파일이 class 를 내는 자리들의 **식** — 이름 회수와 미해독 판정이 같은 목록을 쓴다."""
    sinks = [m.group(1) for m in _CLASS_NAME_ASSIGN.finditer(text)]
    for match in _CLASS_LIST.finditer(text):
        args = _arg_body(text, match.end() - 1)
        # add/remove 는 인자가 전부 이름이고, toggle 은 첫 인자만 이름이다.
        sinks.append(_first_arg(args) if match.group(1) == "toggle" else args)
    return sinks


def _readable(path: Path) -> str:
    """검사용 본문 — 템플릿 보간을 **먼저** 펼친 뒤에야 속성·sink 를 읽는다.

    순서가 계약이다: 보간을 펼치기 전에 `class="..."` 를 찾으면 보간 안의 따옴표가 속성을
    끊어 앞의 온전한 이름까지 잃는다(리뷰 R2).
    """
    text = path.read_text(encoding="utf-8")
    return _expand_interpolations(text, _raw_bindings(text))


def _emitted_classes() -> dict[str, set[str]]:
    """셸과 화면 JS 가 실제로 DOM 에 내는 class → 그 자리들."""
    found: dict[str, set[str]] = {}
    for path in _SOURCES:
        text = _readable(path)
        names: set[str] = set()
        for match in _CLASS_ATTR.finditer(text):
            names |= _tokens(match.group(1) if match.group(1) is not None else match.group(2))
        variables, properties = _bindings(text)
        for expr in _class_sinks(text):
            names |= _sink_names(expr, variables, properties)
        where = path.relative_to(ROOT).as_posix()
        for name in names:
            found.setdefault(name, set()).add(where)
    return found


def _styled_classes() -> set[str]:
    """`frontend/css/*.css` 전수의 선택자에 등장하는 class 이름."""
    names: set[str] = set()
    for path in sorted(SOURCE_CSS_DIR.glob("*.css")):
        text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"), flags=re.S)
        selectors = re.sub(r"\{[^{}]*\}", " ", text)  # 선언 블록을 걷어 선택자만 남긴다
        names.update(re.findall(r"\.(-?[A-Za-z_][\w-]*)", selectors))
    return names


def test_every_class_the_shell_emits_has_a_rule() -> None:
    """DOM 이 내는 class 는 CSS 어딘가에 규칙이 있거나, 사유와 함께 등재돼 있다."""
    emitted = _emitted_classes()
    styled = _styled_classes()
    orphans = {
        name: sites
        for name, sites in emitted.items()
        if name not in styled and name not in STYLELESS_BY_DESIGN
    }
    assert not orphans, (
        "규칙이 한 줄도 없는 class 를 DOM 이 내고 있습니다:\n"
        + "\n".join(f"  .{n} — {' · '.join(sorted(s))}" for n, s in sorted(orphans.items()))
        + "\n스타일을 잃은 것이면 frontend/css 에 규칙을 되살리고, 스타일이 원래 없는 것이면 "
        "STYLELESS_BY_DESIGN 에 **사유와 함께** 등재하세요."
    )


def test_stylesless_allowlist_has_no_stale_entries() -> None:
    """허용 목록이 실물을 앞지르지 않는다 — 규칙이 생겼거나 class 가 사라지면 등재를 지운다.

    허용 목록은 「지금 스타일이 없다」는 선언이지 영구 면제가 아니다. 등재해 둔 class 에
    규칙이 생기면 그 등재는 거짓말이 되고, class 자체가 사라지면 다음 사람이 사유를 읽고
    있지도 않은 것을 지키게 된다.
    """
    emitted = _emitted_classes()
    styled = _styled_classes()
    now_styled = sorted(n for n in STYLELESS_BY_DESIGN if n in styled)
    gone = sorted(n for n in STYLELESS_BY_DESIGN if n not in emitted)
    assert not now_styled, (
        f"규칙이 생겼는데 허용 목록에 남아 있습니다: {', '.join(now_styled)} — 등재를 지우세요."
    )
    assert not gone, (
        f"DOM 이 더는 내지 않는 class 가 허용 목록에 남아 있습니다: {', '.join(gone)} — 등재를 지우세요."
    )


def test_every_class_attribute_form_is_readable() -> None:
    """`class=` 를 적는 **모든 형태**를 읽는다 — 못 읽는 형태가 있으면 시끄럽다(리뷰 R3).

    첫 판은 큰따옴표만 읽었다. 셸에 홑따옴표가 2곳뿐이라 테스트는 통과했지만(그 둘의 class 가
    마침 다른 데서도 나왔다), **그 형태로만 나오는 class 는 규칙을 잃어도 게이트가 조용했다**.
    형태를 세어서 규칙을 고르면 다음 사람이 다른 쪽으로 적는 날 눈을 감는 것과 같다.

    그래서 세는 대신 **문법을 받고**, 받지 못하는 형태는 여기서 실패시킨다 — 새 형태
    (백틱 속성·무따옴표)가 들어오면 회수 규칙을 넓히든 형태를 통일하든 선택하게 된다.
    """
    unreadable: list[str] = []
    for path in _SOURCES:
        text = _readable(path)
        where = path.relative_to(ROOT).as_posix()
        for match in re.finditer(r"class\s*=\s*(.)", text):
            if match.group(1) in "\"'":
                continue
            around = " ".join(text[match.start():match.start() + 60].split())
            unreadable.append(f"  {where} — {around}")
    assert not unreadable, (
        "읽지 못하는 class 속성 형태가 있습니다(고아 검사가 그 자리를 통째로 건너뜁니다):\n"
        + "\n".join(unreadable)
        + "\n따옴표로 적거나, 회수 규칙을 그 형태까지 넓히세요."
    )


def test_every_class_sink_yields_a_readable_name() -> None:
    """이름을 **하나도** 못 얻은 class sink 가 없다 — 그물의 구멍은 조용히 넓어진다.

    앞의 두 테스트는 「읽어 낸 이름」만 검사하므로, 읽지 못한 sink 는 검사 대상이 0개가 돼
    **초록으로 보인다**. 이 파일이 기록한 사고가 바로 그 모양이었다(규칙이 사라져도 아무도
    말하지 않음). 그래서 해독 실패 자체를 실패로 만든다: 새 sink 가 계산식으로 이름을 만들면
    여기서 걸리고, 상수로 바꾸거나 회수 규칙을 넓히거나 둘 중 하나를 하게 된다.
    """
    unreadable: list[str] = []
    for path in _SOURCES:
        text = _readable(path)
        variables, properties = _bindings(text)
        where = path.relative_to(ROOT).as_posix()
        for expr in _class_sinks(text):
            if not _sink_names(expr, variables, properties):
                unreadable.append(f"  {where} — {' '.join(expr.split())[:80]}")
    assert not unreadable, (
        "class 이름을 읽어 낼 수 없는 자리가 있습니다(고아 검사가 이 자리를 통째로 건너뜁니다):\n"
        + "\n".join(unreadable)
        + "\n이름을 리터럴이나 같은 파일의 상수 결속으로 두거나, 회수 규칙을 넓히세요."
    )


def test_interpolated_and_composed_class_names_are_seen() -> None:
    """보간 안에 따옴표가 있어도, 이름이 조각으로 이어 붙어도 본다(리뷰 R2).

    실물 두 자리를 든다. `job.js` 의 후보 카드는
    `class="job-cand-card${active ? " active" : ""}${...}"` 인데, 보간 안의 따옴표가 속성을
    끊어 **앞의 온전한 이름까지** 못 봤다 — `.job-cand-card` 를 지워도 게이트가 초록이었다.
    `workbench.js` 의 카드 글꼴은 `"wc-render f-" + (font || "gulimche")` 로 **코드에 그대로
    적힌** `f-gulimche` 인데, 조각 규칙이 앞뒤를 둘 다 버려 못 봤다.
    """
    emitted = _emitted_classes()
    for name, site in (
        ("job-cand-card", "frontend/js/screens/job.js"),   # 보간 앞의 온전한 이름
        ("active", "frontend/js/screens/job.js"),          # 보간이 더하는 상태 class
        ("suggested", "frontend/js/screens/job.js"),
        ("f-gulimche", "frontend/js/screens/workbench.js"),  # 조각 합성
        # 보간 **안**에 통째로 들어앉은 마크업(리뷰 R3 근본): `${v ? esc(v) :
        # "<em class='muted'>(빈 값)</em>"}` — 안을 지우면 이 자리의 class 가 검사 밖이 된다.
        ("muted", "frontend/js/screens/job.js"),
        # 속성 **전체**가 변수인 자리(리뷰 R4): `const cls = ... "seg-fill"` → `class="${cls}"`.
        # 붙어 있는 이웃이 없으므로 갈래 자체가 온전한 이름이다(앞 공백을 요구하면 못 본다).
        ("seg-fill", "frontend/js/segview.js"),
    ):
        assert site in emitted.get(name, set()), (
            f".{name} 이 {site} 의 산출 목록에 없습니다 — 보간·합성 회수가 깨졌습니다."
        )


def test_fragment_tails_do_not_become_names() -> None:
    """합성은 **리터럴 꼬리**에만 적용된다 — 런타임 값 자리는 여전히 이름이 아니다.

    `class="col-${c.kind}"`·`class="r-${r.row_state}"` 의 접두는 반쪽이라 이름으로 세면
    `.col-`·`.r-` 를 요구하는 오탐이 된다. 합성이 이 경계를 넘지 않았는지 본다.
    """
    emitted = _emitted_classes()
    bad = sorted(n for n in emitted if n.endswith("-"))
    assert not bad, f"조각이 이름으로 샜습니다: {', '.join(bad)}"
    # 꼬리는 **합성된 이름으로만** 산다 — 반쪽이 홀로 이름이 되면 `.gulimche` 를 요구한다.
    assert "gulimche" not in emitted, (
        "조각의 뒤 리터럴이 홀로 이름이 됐습니다 — 합성 대신 그냥 세고 있습니다."
    )


def test_variable_backed_class_names_are_seen() -> None:
    """변수·속성을 거쳐 나가는 이름도 회수된다 — 회수 경로 자체의 회귀 방지(리뷰 R1).

    실물 두 자리를 그대로 든다: `job.js` 의 `const MARK = "openingMark"` → `mark.className`,
    `app.js` 의 `{ cls: "editor-open" }` → `classList.toggle(im.cls, ...)`. 이 둘이 목록에서
    빠지면 그 CSS 를 지워도 게이트가 초록이던 상태로 되돌아간 것이다.
    """
    emitted = _emitted_classes()
    for name, site in (
        ("openingMark", "frontend/js/screens/job.js"),
        ("editor-open", "frontend/js/app.js"),
        ("workbench-open", "frontend/js/app.js"),
    ):
        assert site in emitted.get(name, set()), (
            f".{name} 이 {site} 의 산출 목록에 없습니다 — 변수·속성 결속 회수가 깨졌습니다."
        )


def test_allowlist_entries_carry_a_reason() -> None:
    """빈 사유는 등재가 아니다 — 「왜 스타일이 없어도 되는가」가 등재의 값이다."""
    empty = sorted(n for n, why in STYLELESS_BY_DESIGN.items() if not why.strip())
    assert not empty, f"사유 없는 등재: {', '.join(empty)}"
