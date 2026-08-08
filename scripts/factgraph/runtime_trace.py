"""runtime trace seam — 테스트 전용 최소 실행 계측(``sys.monitoring``, PEP 669).

정적 그래프가 미해결로 남긴 edge(문자열 디스패치·주입 콜백)를 **실행 증거**로 확인하는
자리다. 제품 코드는 이 모듈을 모른다 — 계측은 테스트가 문맥관리자로 켠다.

``sys.settrace`` 를 쓰지 않는 이유: coverage 트레이서와 같은 자리를 두고 다퉈 측정을
조용히 죽일 수 있다. ``sys.monitoring`` 은 도구 슬롯이 분리돼 공존한다(#512 설계 패킷).

계측 범위의 정직한 경계: 관측 대상 지도(``code_map``)에 든 파일 **안**에서 시작하는
호출만 기록한다. 관측 밖 코드가 낀 edge 는 「없다」가 아니라 「이 seam 이 안 본 것」이다
— 정적 부재를 runtime 부재로 간주하지 않는 불변식과 같은 방향이다.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator, Mapping

from .schema import Evidence, Fact, FactGraphError, Provenance

COLLECTOR = "factgraph.runtime_trace"
_TOOL_NAME = "factgraph"


@contextmanager
def record_calls(
    code_map: Mapping[str, str],
    symbol_index: Mapping[tuple[str, str], str],
) -> Iterator[list[Fact]]:
    """관측 지도 안에서 일어나는 호출을 ``RUNTIME_CONFIRMED`` calls 사실로 기록한다.

    - ``code_map``: ``co_filename`` **원문 그대로**의 키 → 모듈 이름. 정규화하지 않는다 —
      콜백 안에서 경로 함수를 부르면 그 호출이 다시 이벤트를 낳는다.
    - ``symbol_index``: (모듈, qualname) → symbol ID. 정적 심볼 패스의 산출을 그대로 받아
      실행 증거가 정적 심볼과 같은 좌표에 앉게 한다. 좌표 밖 코드(람다 등)는 버리지 않고
      ``?:runtime:`` 미해결로 남긴다.
    """
    mon = sys.monitoring
    tool_id = _claim_tool_id(mon)
    recorded: set[tuple[str, str, str, int]] = set()
    facts: list[Fact] = []
    busy = False

    def _symbol_of(code) -> "tuple[str, str] | None":  # (symbol_or_ref, module)
        module = code_map.get(code.co_filename)
        if module is None:
            return None
        sid = symbol_index.get((module, code.co_qualname))
        return (sid if sid is not None else f"?:runtime:{module}.{code.co_qualname}", module)

    def _on_start(code, _offset):  # noqa: ANN001 — sys.monitoring 콜백 시그니처
        nonlocal busy
        if busy:
            return None
        busy = True
        try:
            callee = _symbol_of(code)
            if callee is None:
                return mon.DISABLE  # 관측 밖 코드 — 이후 이벤트도 끈다
            frame = sys._getframe(1)
            while frame is not None and frame.f_code is not code:
                frame = frame.f_back
            caller_frame = frame.f_back if frame is not None else None
            if caller_frame is None:
                return None
            caller = _symbol_of(caller_frame.f_code)
            if caller is None or caller[0].startswith("?:"):
                return None  # 관측 밖에서 들어온 진입 호출은 이 seam 의 몫이 아니다
            key = (caller[0], callee[0], code.co_filename, code.co_firstlineno)
            if key in recorded:
                return None
            recorded.add(key)
            facts.append(
                Fact(
                    src=caller[0],
                    rel="calls",
                    dst=callee[0],
                    grade="RUNTIME_CONFIRMED",
                    evidence=Evidence(
                        file=callee[1], line=code.co_firstlineno, anchor=code.co_qualname
                    ),
                    provenance=Provenance(COLLECTOR, "py_start"),
                )
            )
            return None
        finally:
            busy = False

    mon.register_callback(tool_id, mon.events.PY_START, _on_start)
    mon.set_events(tool_id, mon.events.PY_START)
    try:
        yield facts
    finally:
        mon.set_events(tool_id, 0)
        mon.register_callback(tool_id, mon.events.PY_START, None)
        mon.free_tool_id(tool_id)
        facts.sort(key=Fact.sort_key)


def _claim_tool_id(mon) -> int:  # noqa: ANN001 — sys.monitoring 모듈
    for tool_id in range(6):
        if mon.get_tool(tool_id) is None:
            mon.use_tool_id(tool_id, _TOOL_NAME)
            return tool_id
    raise FactGraphError("sys.monitoring 도구 슬롯이 모두 점유돼 runtime trace 를 켤 수 없다")
