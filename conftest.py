"""pytest 루트 설정 — dev 스크립트(scripts/)를 import 경로에 얹고, 임시 베이스를 안전한 곳으로 옮긴다.

``scripts/`` 는 배포 패키지에 들어가지 않는 dev/CI 도구다(pyproject wheel packages 밖).
토큰 동기화 가드 테스트(tests/test_design_tokens.py)가 ``import gen_design_tokens`` 로
생성기 함수를 직접 부를 수 있도록 여기서 sys.path 에 추가한다.

또한 게이트(test.ps1)가 넘기는 ``--basetemp=.pytest-tmp`` 는 저장소 안(= OneDrive 동기화·
Windows 검색 인덱서가 감시하는 Desktop 하위)에 만들어진다. 그 서비스들이 tmp 파일에
순간 핸들을 걸면 pytest 가 베이스를 지울 때 디렉터리 루트가 Windows 의 *삭제 보류
(delete-pending)* 상태로 빠져 이후 접근이 전부 ``WinError 5`` 로 거부된다 — ``tmp_path`` 를
쓰는 수백 개 테스트가 setup 에서 무더기 ERROR 로 무너지는 원인(gate-env-gotchas 원장 참조).

근본 원인은 *감시 대상 트리 안에서의 삭제* 이므로, 저장소 안을 가리키는 베이스를
감시받지 않는 시스템 임시 폴더(``%LOCALAPPDATA%\\Temp``)의 매 실행 고유 디렉터리로
돌린다 — 세션 시작 시 지울 선행 디렉터리 자체가 없어 삭제 보류 함정을 아예 회피한다.
사용자가 저장소 밖 경로를 명시로 넘긴 경우는 그대로 존중한다(조용한 우회 금지).
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.resolve()
_SCRIPTS = _ROOT / "scripts"
if _SCRIPTS.is_dir() and str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _unwatched_temp_root() -> Path:
    """OneDrive 동기화·검색 인덱서가 감시하지 않는 시스템 임시 루트.

    ``tempfile.gettempdir()`` 는 일부 환경에서 서드파티가 ``%TEMP%`` 를 Public 하위로
    가로채므로(예: Public\\Documents), 먼저 ``%LOCALAPPDATA%\\Temp`` 를 시도한다 —
    사용자 프로파일의 로컬 앱데이터는 OneDrive 에 동기화되지 않고 기본 인덱싱 대상도 아니다.
    """
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = Path(local) / "Temp"
        if cand.is_dir():
            return cand
    return Path(tempfile.gettempdir())


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """저장소 안을 가리키는 ``--basetemp`` 를 감시받지 않는 고유 임시 폴더로 돌린다.

    tmpdir 내장 플러그인이 ``config.option.basetemp`` 를 읽어 :class:`TempPathFactory`
    를 만들기 *전에* 값을 바꿔야 하므로 ``tryfirst`` 로 먼저 돈다(conftest 는 내장
    플러그인보다 늦게 등록돼 tryfirst 훅에서 앞서 호출된다).
    """
    given = getattr(config.option, "basetemp", None)
    if not given:
        return  # 기본 동작 존중(명시 베이스 없음)
    given_path = Path(given).resolve()
    # 저장소 밖을 명시로 겨눈 베이스는 사용자 의도이므로 건드리지 않는다.
    if not _is_inside(given_path, _ROOT):
        return
    # 매 실행 고유 디렉터리 → 세션 시작 시 지울 선행 디렉터리가 없어 삭제 보류 회피.
    fresh = _unwatched_temp_root() / f"hwpx-pytest-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    config.option.basetemp = str(fresh)
