"""pclm(계약 목록)이 **밖에 약속한 것** — 자료가 사는 자리 하나.

종전에는 여기에 계약면 뷰 허용목록(``PCLM_VIEWS`` 등)과 그 제목·설명표가 살았다. pclm 의
스키마가 뷰 15종·내부 표 수십 개로 자라면서 허용목록은 새 면을 전부 거절하는 박제가 됐고,
사용자 결정(2026-09-30)으로 걷혔다: 이제 DB 는 **엑셀 통합문서처럼** 열린다 — 그 안의 뷰와
표가 곧 시트이고, 시트 이름은 DB 가 가진 이름 그대로다(어댑터
:func:`~hwpxfiller.data.pclm.list_sqlite_sheets` 가 실제 DB 에서 나열한다).

남은 것은 **자리의 해석**(:func:`default_pclm_db`)뿐이다. 이 해석은 실제로 SQLite 를 여는
어댑터(:class:`~hwpxfiller.data.pclm.PclmDataSource`, EXTERNAL_ADAPTER)와 참조를 등록하는
Application(:meth:`~hwpxfiller.application.dataset_pool.DatasetPoolViewModel.register_pclm`)이
**같은 값**을 봐야 하고, Application 은 바깥 링을 import 할 수 없다
(``tests/repo_contract/test_application_boundary.py``). 어휘는 안쪽에, 접속은 바깥쪽에 둔다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = [
    "default_pclm_db",
]


def _configured_data_dir() -> "Path | None":
    """pclm 이 DB 밖 쪽지에 적어 둔 자료 폴더 — 못 읽으면 어떤 사유든 ``None``.

    쪽지가 DB 밖(``%APPDATA%\\Pclm\\config.json``)에 사는 까닭은 부트스트랩이다: 그 값을
    DB 에 적으면 읽으려고 여는 DB 가 바로 그 값이 가리키는 것이라 순환이 된다(저쪽
    ADR-018). ``pendingMoveFrom`` 은 저쪽 창이 「다음 실행에 이사한다」고 스스로에게 남기는
    표시라 소비자가 읽을 값이 아니다 — 여기서 무시한다.

    **쪽지 하나 때문에 이쪽이 멈추면 안 된다**: 파일 부재·깨진 JSON·형 불일치·읽기 예외는
    전부 조용히 기본 자리로 물러난다. 이것은 조용한-추측 금지의 예외가 아니라 그 적용이다
    — 자리는 여전히 하나이고, 쪽지가 없다는 것의 뜻이 곧 「기본 자리」다. DB 자체가
    없을 때의 시끄러운 안내는 :meth:`~hwpxfiller.data.pclm.PclmDataSource` 의 로드가 진다.
    """
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    try:
        raw = json.loads((Path(roaming) / "Pclm" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # 부재·권한·깨진 JSON·인코딩 — 사유 불문 기본 자리로
        return None
    if not isinstance(raw, dict):
        return None
    data_dir = raw.get("dataDir")
    if not isinstance(data_dir, str) or not data_dir:
        return None
    return Path(data_dir)


def default_pclm_db() -> Path:
    """pclm 이 자료를 쌓는 자리 — 그쪽 창과 명령줄이 함께 보는 곳.

    저쪽 ``Database.DefaultPath`` 와 같은 값이다. 사용자가 설정 창에서 자료 폴더를 옮겼으면
    그 자리(:func:`_configured_data_dir`)를, 아니면 종전 고정 자리를 가리킨다 — **자리는
    여전히 하나**다(여러 DB 를 고르는 축이 아니라, 하나뿐인 그 자리가 어디인지의 해석).

    쪽지를 읽는 일이 이 모듈의 「접속은 바깥쪽에」 경계에 걸리는 듯 보이지만, 이 함수의
    일은 데이터 접속이 아니라 **자리의 해석**이고(환경변수를 읽던 것과 같은 성격), 이
    해석은 등록 게이트(Application ``resolve_pclm_db``)도 써야 해서 바깥 링으로 옮길 수
    없다 — 어댑터로 내리면 등록이 옮기기 전 자리를 박제한다.
    """
    configured = _configured_data_dir()
    if configured is not None:
        return configured / "pclm.db"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Pclm" / "pclm.db"
