"""세션 행 키의 **두 리터럴이 갈리지 않는다** — Python ↔ TS 정적 대조(고르기 열 공용 ⑤ 리뷰).

## 이 파일이 겨누는 결함류

키 ``session`` 은 층을 가로지르는 **약속된 글자**다. Python 이 그 키로 세션 행을 짓고
(:data:`hwpxfiller.webapp.pool_column.SESSION_DATA_KEY`), 웹이 같은 글자로 그 행을 셋으로
가른다: ⋯ 메뉴에서 「자세히…」를 빼고(풀에 없는 항목이라 검토할 것이 없다), 클릭을 무동작으로
돌리고(이미 쓰고 있다), 고름 표지를 세운다. **두 자리에 리터럴이 하나씩 산다** — 한쪽만 고치면
그날부터 세션 행은 「고를 수 없는 지금 데이터」가 아니라 「없는 슬롯을 가리키는 행」이 된다.

그 어긋남은 **아무 게이트도 빨강으로 만들지 않는다**: 렌더는 그대로 서고, ⋯ 는 열리고, 클릭은
발신된다 — 다만 답이 없다. 조용히 틀리는 자리라 여기서 글자로 못박는다.

## 이 대조의 정직한 한계

정적 문자열 대조다. 「그 키가 실제로 그 행에 실려 왔는가」는 헤드리스 계약
(``tests/test_webapp_pool_column.py``)과 컴포넌트 단위(``tests/js/pool_column.test.js``)가
각각 진다. 여기서 잡는 것은 **두 저자가 다른 글자를 쓰기 시작한** 순간 하나다.
"""

from __future__ import annotations

import re
from pathlib import Path

from hwpxfiller.webapp.pool_column import SESSION_DATA_KEY

ROOT = Path(__file__).resolve().parents[2]
#: TS 쪽 정본. 이 파일이 든 이유는 **행 계약이 여기 살기 때문**이다(소비자 셋이 여기서 받는다).
POOL_COLUMN_TS = ROOT / "frontend" / "src" / "screens" / "pool_column.ts"

_TS_LITERAL = re.compile(
    r"""^export\s+const\s+SESSION_DATA_KEY\s*=\s*["']([^"']+)["']\s*;""",
    re.MULTILINE,
)


def test_the_session_row_key_is_the_same_letter_on_both_sides() -> None:
    source = POOL_COLUMN_TS.read_text(encoding="utf-8")
    found = _TS_LITERAL.findall(source)
    # 선언 부재·중복 선언도 시끄럽다 — 정규식이 빗나간 채 「대조 통과」로 읽히면 이 계약은
    # 존재만 하고 결과를 못 본다(이 저장소가 이름 붙인 hollow measurement).
    assert len(found) == 1, (
        f"{POOL_COLUMN_TS.name} 의 SESSION_DATA_KEY 선언이 1개가 아닙니다: {found}"
    )
    assert found[0] == SESSION_DATA_KEY, (
        f"세션 행 키가 갈렸습니다 — TS {found[0]!r} ≠ Python {SESSION_DATA_KEY!r}. "
        "한쪽만 고치면 세션 행이 「없는 슬롯」을 가리키고, 눌러도 답이 없습니다."
    )


def test_no_other_frontend_source_reinvents_the_literal() -> None:
    """다른 화면 파일이 그 글자를 **다시 적지 않는다** — 정본은 `pool_column.ts` 하나다.

    편집기 우 열의 고름 표지가 실제로 그렇게 새 나갔던 자리다(``sessionRow ? "session" : ""``):
    import 는 서 있는데 리터럴을 옆에 한 번 더 적으면, 정본을 고쳐도 그 자리만 옛 글자로 남는다.
    """
    literal = f'"{SESSION_DATA_KEY}"'
    offenders: "list[str]" = []
    for path in sorted((ROOT / "frontend" / "src").rglob("*.ts")):
        if path == POOL_COLUMN_TS:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if literal in line:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    assert not offenders, (
        "세션 행 키를 리터럴로 다시 적은 자리가 있습니다 — `pool_column.ts` 의 "
        "SESSION_DATA_KEY 를 import 하십시오:\n" + "\n".join(offenders)
    )
