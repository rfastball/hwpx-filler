"""pytest 루트 설정 — dev 스크립트(scripts/)를 import 경로에 얹는다.

``scripts/`` 는 배포 패키지에 들어가지 않는 dev/CI 도구다(pyproject wheel packages 밖).
토큰 동기화 가드 테스트(tests/test_design_tokens.py)가 ``import gen_design_tokens`` 로
생성기 함수를 직접 부를 수 있도록 여기서 sys.path 에 추가한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent / "scripts"
if _SCRIPTS.is_dir() and str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
