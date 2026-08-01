"""수집 결과를 JSON 으로 뜨는 pytest 플러그인 — suite 분리 계약의 눈(N-11B · #424).

``pytest --collect-only -p _suite_probe --suite-probe-out <경로>`` 로 부른다. 판정하지 않고
**본 것만** 적는다 — 무엇이 어긋남인지는 :mod:`test_suite_partition` 이 정한다. 프로브가
판정까지 쥐면 프로브를 고쳐 초록을 만드는 길이 열린다.

수집된 노드마다 세 가지를 적는다.

- ``nodeid`` — pytest 가 부르는 이름 그대로(비 ASCII 파라미터 id 는 pytest 가 이미 escape 한다).
- ``markers`` — 그 노드에 **실제로 적용된** marker 이름 전부. 클래스·모듈 단위로 얹힌 것도
  포함한다(선언 위치가 아니라 결과를 본다).
- ``skip_reasons`` — ``skipif`` 의 사유 문자열. 어떤 자원이 없으면 못 도는지가 여기 적힌다.
"""
from __future__ import annotations

import json
from pathlib import Path


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--suite-probe-out",
        action="store",
        default=None,
        help="수집 결과 JSON 을 쓸 경로(suite 분리 계약 전용)",
    )


def pytest_collection_finish(session) -> None:
    target = session.config.getoption("--suite-probe-out")
    if not target:
        return

    rows = []
    for item in session.items:
        skip_reasons = [
            str(mark.kwargs["reason"])
            for mark in item.iter_markers(name="skipif")
            if "reason" in mark.kwargs
        ]
        rows.append(
            {
                # nodeid 를 손대지 않는다 — pytest 는 경로를 이미 `/` 로 쓰고, 비 ASCII
                # 파라미터 id 는 `\uXXXX` **역슬래시 escape** 라 치환하면 이름이 부서진다.
                "nodeid": item.nodeid,
                "markers": sorted({mark.name for mark in item.iter_markers()}),
                "skip_reasons": skip_reasons,
            }
        )

    Path(target).write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
