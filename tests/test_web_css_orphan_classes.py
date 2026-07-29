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
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

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
    "job-active-zone": "세션 우열 「선택한 작업」 존의 자리 표지(스타일은 .zone)",
}

#: 템플릿 보간 자리 표식 — `class="col-${i}"` 의 `col-` 같은 **조각**은 class 이름이 아니다.
_HOLE = "\x00"

_CLASS_ATTR = re.compile(r'class="([^"]*)"')
_CLASS_NAME_ASSIGN = re.compile(r'className\s*=\s*"([^"]*)"')
_CLASS_LIST = re.compile(r"classList\.(?:add|remove|toggle)\(([^)]*)\)")
_STRING_LIT = re.compile(r"\"([^\"]*)\"|'([^']*)'")
_IDENT = re.compile(r"[A-Za-z_][\w-]*\Z")


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


def _emitted_classes() -> dict[str, set[str]]:
    """셸과 화면 JS 가 실제로 DOM 에 내는 class → 그 자리들."""
    found: dict[str, set[str]] = {}
    sources = [WEB / "index.html", *sorted(WEB.glob("js/**/*.js"))]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        names: set[str] = set()
        for match in _CLASS_ATTR.finditer(text):
            # `${...}` 를 구멍 표식으로 바꾼다 — 붙어 있던 조각이 이름으로 새지 않게.
            names |= _tokens(re.sub(r"\$\{[^}]*\}", _HOLE, match.group(1)))
        for match in _CLASS_NAME_ASSIGN.finditer(text):
            names |= _tokens(re.sub(r"\$\{[^}]*\}", _HOLE, match.group(1)))
        for match in _CLASS_LIST.finditer(text):
            for double, single in _STRING_LIT.findall(match.group(1)):
                names |= _tokens(double or single)
        where = path.relative_to(ROOT).as_posix()
        for name in names:
            found.setdefault(name, set()).add(where)
    return found


def _styled_classes() -> set[str]:
    """`web/css/*.css` 전수의 선택자에 등장하는 class 이름."""
    names: set[str] = set()
    for path in sorted((WEB / "css").glob("*.css")):
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
        + "\n스타일을 잃은 것이면 web/css 에 규칙을 되살리고, 스타일이 원래 없는 것이면 "
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


def test_allowlist_entries_carry_a_reason() -> None:
    """빈 사유는 등재가 아니다 — 「왜 스타일이 없어도 되는가」가 등재의 값이다."""
    empty = sorted(n for n, why in STYLELESS_BY_DESIGN.items() if not why.strip())
    assert not empty, f"사유 없는 등재: {', '.join(empty)}"
