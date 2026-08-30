"""pclm(계약 목록)이 **밖에 약속한 것** — 계약면 뷰 이름·설명과 자료가 사는 자리.

값은 :mod:`hwpxfiller.data.pclm` 에서 왔다(그쪽이 계속 re-export 한다 — 기존 import 는
그대로 산다). 여기로 올린 이유는 **소비자가 두 링에 걸쳐 있기** 때문이다: 실제로 SQLite 를
여는 어댑터(:class:`~hwpxfiller.data.pclm.PclmDataSource`, EXTERNAL_ADAPTER)와, 참조를
등록하며 뷰를 검증하는 Application(:meth:`~hwpxfiller.application.dataset_pool.
DatasetPoolViewModel.register_pclm`)이 **같은 허용목록**을 봐야 한다. Application 은 바깥
링을 import 할 수 없으므로(``tests/repo_contract/test_application_boundary.py``), 허용목록이
어댑터에 남아 있으면 등록 게이트가 뷰 4종을 **재구현**하게 된다 — 그것이 조용한 표류의
표준 형태다. 어휘는 안쪽에, 접속은 바깥쪽에 둔다.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "DEFAULT_PCLM_VIEW",
    "PCLM_VIEWS",
    "PCLM_VIEW_LABELS",
    "default_pclm_db",
]

# 계약면. pclm 이 약속한 것은 이 넷뿐이라 그 밖의 이름은 받지 않는다.
# 뷰 이름은 SELECT 문에 그대로 박히므로 이 허용목록이 주입 방어를 겸한다 —
# 사용자가 고른 문자열이 SQL 로 흘러드는 유일한 자리가 여기다.
PCLM_VIEWS: "tuple[str, ...]" = ("v_통합_v1", "v_공고_v1", "v_계약_v1", "v_품목_v1")

# 뷰를 고르는 사람에게 보일 한 줄. **한 줄이 무엇 하나인지**가 고르는 기준이라
# 그것을 문장의 절반으로 쓴다 — 계약면을 섞으면 문서 건수가 조용히 어긋난다.
# 키 집합은 PCLM_VIEWS 와 같다(허용목록에 이름만 늘고 설명이 빠지는 것을 테스트가 막는다).
PCLM_VIEW_LABELS: "dict[str, str]" = {
    "v_통합_v1": "공고와 계약을 이어 붙인 계약면. 한 줄이 계약 1건(기본 문서 대상)",
    "v_공고_v1": "공고 정보. 한 줄이 공고 1건",
    "v_계약_v1": "계약 정보. 한 줄이 계약 1건",
    "v_품목_v1": "품목 명세. 한 줄이 품목 1줄(계약 1건에 여러 줄)",
}

# 가장 자주 쓰는 시트: 계약 1건 + 이어진 공고. 한 줄이 계약 하나다.
DEFAULT_PCLM_VIEW = "v_통합_v1"


def default_pclm_db() -> Path:
    """pclm 이 자료를 쌓는 자리 — 그쪽 창과 명령줄이 함께 보는 곳.

    저쪽 ``Database.DefaultPath`` 와 같은 값이다. 한동안 창과 명령줄이 서로 다른 자리를
    봐서 같은 컴퓨터에 DB 가 여럿 생겼는데, 밖에서 읽는 쪽에는 **가리킬 자리가 하나**
    여야 하므로 그쪽이 이리로 모았다.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Pclm" / "pclm.db"
