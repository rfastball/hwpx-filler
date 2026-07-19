"""웹 컨트롤러 디스패치 액션 ↔ 프론트 호출자 완결성 가드 — 백엔드/프론트 배선 누락 재발 방지.

2026-07-16 high 코드리뷰(#26 웹 패리티 2차)에서 ``_do_profile_delete``(screen_editor.py)가
완전히 구현·테스트까지 됐는데 ``web/js/screens/editor.js`` 어디서도 호출되지 않는 결함이
확정됐다. 이 테스트를 만들며 저장소 전체를 훑자 같은 패턴이 3건 더 나왔다
(``_do_refresh`` — home/pool/template, UI 트리거 전무) — 전부 이번 라운드에 배선하고 이
가드로 재발을 막는다.

**검사 방식**: 각 ``screen_*.py`` 컨트롤러의 ``def _do_<action>(`` 메서드마다, 그 액션
문자열이 저장소 전체( ``src/hwpxfiller/`` + ``web/`` )의 다른 어딘가에 리터럴로 등장하는지
찾는다. 화면별 JS 파일 하나만 보면 오탐이 컸다 — ``pool_sources``/``load_pool`` 은 공유
모듈(``pool_picker.js``)이 호출하고, ``archive``/``activate`` 는 서버가 내려주는
동적 액션 키(``gui/dataset_pool_state.py`` 의 ``PoolAction``)로 렌더된다. 저장소 전체를
haystack 으로 삼으면 이 두 정당한 패턴은 통과하고, 진짜 미배선(호출자 0)만 남는다.

허용목록은 두지 않는다 — 이 테스트의 존재 이유가 "의도적으로 미배선인 액션"을 조용히
넘기지 않는 것이므로, 새 액션을 추가하되 당장 UI 를 만들지 않을 거라면 이 테스트가
빨갛게 알리는 게 맞다(confirm-or-alarm). 실제로 그런 경우가 생기면 액션을 추가하지 않고
다음 배선까지 미루거나, 최소 자리표시 호출(예: 숨은 디버그 메뉴)을 만들어라.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hwpxfiller"
WEB = ROOT / "web"

# 컨트롤러 파일 → 소유 화면의 1차 JS(공유 헬퍼는 haystack 전체 검색이 커버).
CONTROLLER_FILES = [
    "screen_editor.py",
    "screen_home.py",
    "screen_job.py",  # 「작업」 세션 패널(R-flow) — run 사망(슬라이스 3) 후 유일 생성 표면
    "screen_pool.py",
    "screen_template.py",
    "screens.py",  # TxtController
]

_ACTION_DEF = re.compile(r"def _do_([a-zA-Z0-9_]+)\(")


def _repo_haystack() -> str:
    parts = [p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")]
    parts += [p.read_text(encoding="utf-8") for p in WEB.rglob("*.js")]
    return "\n".join(parts)


def test_every_dispatch_action_has_a_caller() -> None:
    haystack = _repo_haystack()
    offenders: list[str] = []
    for filename in CONTROLLER_FILES:
        text = (SRC / "webapp" / filename).read_text(encoding="utf-8")
        for action in _ACTION_DEF.findall(text):
            if f'"{action}"' not in haystack and f"'{action}'" not in haystack:
                offenders.append(f"{filename}: _do_{action}")
    assert not offenders, (
        "백엔드 디스패치 액션인데 저장소 어디에서도 호출되지 않는다(프론트 미배선) — "
        "UI 를 배선하거나, 정말 불필요하면 액션 자체를 지워라:\n" + "\n".join(offenders)
    )
