"""앱 홈 경로의 단일 출처 — ``HWPXFILLER_HOME`` 해석기(#76).

레지스트리 4종(작업·데이터셋·템플릿·txt)과 웹앱 설정은 모두 같은 홈 밑에 산다. 그 홈을
해석하는 관용구(``os.environ.get("HWPXFILLER_HOME") or ~/.hwpxfiller``)가 모듈마다 복사돼
있으면 홈 규약이 바뀔 때 전부를 lockstep 으로 고쳐야 하고, **한 곳이라도 놓치면 레지스트리
상태와 settings.json 이 서로 다른 디렉터리로 조용히 갈라진다** — 사용자에겐 "작업이 사라진"
것으로 보이는 조용한 소실이다. 해석을 여기로 회수해 그 갈라짐을 구조적으로 불가능하게 한다.

각 모듈의 ``default_*_dir()`` 공개 API 는 그대로다(내부 홈 해석만 이 함수에 위임) — 호출자
계약은 불변이고, 레지스트리 *클래스* 들은 여전히 위치-불가지다(생성자가 디렉터리를 받는다).

core 에 두는 이유: 소비자가 core 레지스트리 4종과 webapp 설정에 걸쳐 있고, core 는 webapp 을
import 할 수 없다(역의존). 반대 방향(webapp→core)은 이미 관례다.
"""

from __future__ import annotations

import os
from pathlib import Path

#: 홈 재지정 환경변수 이름 — 테스트 격리(``tests/conftest.py`` autouse 임시 홈)·CI·다중 프로필.
HOME_ENV_VAR = "HWPXFILLER_HOME"

#: 재지정이 없을 때의 기본 홈 폴더 이름(사용자 홈 아래).
DEFAULT_HOME_NAME = ".hwpxfiller"


def home_dir() -> Path:
    """앱 홈 — ``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``.

    빈 문자열 재지정은 미설정과 같이 취급한다(``or``) — 빈 값이 현재 작업 디렉터리로
    해석돼 홈이 repo 체크아웃 안으로 들어오는 사고를 막는다.
    """
    root = os.environ.get(HOME_ENV_VAR) or (Path.home() / DEFAULT_HOME_NAME)
    return Path(root)
