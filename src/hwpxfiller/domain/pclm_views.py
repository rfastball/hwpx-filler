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

import json
import os
from pathlib import Path

__all__ = [
    "DEFAULT_PCLM_VIEW",
    "PCLM_DOC_VIEWS",
    "PCLM_VIEWS",
    "PCLM_VIEW_DESCS",
    "PCLM_VIEW_LABELS",
    "PCLM_VIEW_TITLES",
    "default_pclm_db",
    "sheet_title",
]

# 뷰 하나가 지는 정보 한 벌 — (제목, 설명, 한 줄의 뜻).
#
# **제목이 따로 있는 이유**: `v_통합_v1` 은 저쪽이 약속한 **내부 이름**이라 옵션·카드·요약에
# 그대로 내보내면 사용자가 읽을 것이 없다. 표면은 제목으로 말하고 값·SELECT 는 실이름으로
# 간다 — 같은 것의 두 층이지 두 개의 진실이 아니다.
#
# 「한 줄이 무엇 하나인지」를 뜻으로 따로 든 것은 그것이 **고르는 기준**이기 때문이다 —
# 계약면을 섞으면 문서 건수가 조용히 어긋난다. CLI 는 그 둘을 이어 붙인 한 줄을 쓴다.
_PCLM_VIEW_INFO: "dict[str, tuple[str, str, str]]" = {
    "v_통합_v1": ("통합", "공고와 계약을 이어 붙인 표", "한 줄이 계약 1건(기본 문서 대상)"),
    "v_공고_v1": ("공고", "공고 정보", "한 줄이 공고 1건"),
    "v_계약_v1": ("계약", "계약 정보", "한 줄이 계약 1건"),
    "v_품목_v1": ("품목", "품목 명세", "한 줄이 품목 1줄(계약 1건에 여러 줄)"),
}

# 계약면. pclm 이 약속한 것은 이 넷뿐이라 그 밖의 이름은 받지 않는다.
# 뷰 이름은 SELECT 문에 그대로 박히므로 이 허용목록이 주입 방어를 겸한다 —
# 사용자가 고른 문자열이 SQL 로 흘러드는 유일한 자리가 여기다.
PCLM_VIEWS: "tuple[str, ...]" = tuple(_PCLM_VIEW_INFO)

# 표면이 부를 이름 / 그 면이 무엇인지 한 마디. 셋 다 정보표 하나에서 파생하므로
# 허용목록에 이름만 늘고 문안이 빠지는 자리가 없다(키 집합 동일성은 테스트가 지킨다).
PCLM_VIEW_TITLES: "dict[str, str]" = {k: v[0] for k, v in _PCLM_VIEW_INFO.items()}
PCLM_VIEW_DESCS: "dict[str, str]" = {k: v[1] for k, v in _PCLM_VIEW_INFO.items()}

# 「설명. 뜻」 한 줄 — 목록을 한 줄씩 늘어놓는 소비자(CLI 나열·거절 재진술)의 것이다.
PCLM_VIEW_LABELS: "dict[str, str]" = {
    k: f"{v[1]}. {v[2]}" for k, v in _PCLM_VIEW_INFO.items()
}

# 웹 등록이 **고르게 하는** 뷰. 허용목록(PCLM_VIEWS)의 부분집합이고, 빠진 것은
# `v_품목_v1` 하나다 — 그 뷰만 한 계약이 여러 줄로 오는데 한 문서 안에 N 줄을 반복 표로
# 펴는 기능이 아직 없어서, 지금 그것을 웹에서 고르면 품목 1줄이 문서 1건이 된다. 허용목록·
# CLI·겨눔 백스톱은 넷 그대로다(이미 등록된 것을 조용히 못 읽게 만들지 않는다) — 좁히는
# 것은 **새로 고르게 하는 자리** 하나다.
PCLM_DOC_VIEWS: "tuple[str, ...]" = ("v_통합_v1", "v_공고_v1", "v_계약_v1")

# 가장 자주 쓰는 시트: 계약 1건 + 이어진 공고. 한 줄이 계약 하나다.
DEFAULT_PCLM_VIEW = "v_통합_v1"


def sheet_title(kind: str, sheet: str) -> str:
    """표면이 부를 **면 하나**의 이름 — 계약 목록의 뷰만 제목으로 옮긴다.

    소비자가 둘이라 여기 하나가 진다(고르기 열 공용 ④): 지금 쓰고 있는 데이터의 열 행
    (:func:`~hwpxfiller.webapp.pool_column.session_data_row`)과 등록 항목의 상세 투영
    (:class:`~hwpxfiller.application.dataset_pool.DatasetDetail`)이 같은 사실을 말한다.
    각자 적으면 한쪽만 내부 이름(``v_품목_v1``)을 새 나가게 하는 날이 온다.

    **미지 이름은 원문 그대로**다: 표에 없는 뷰(구판·손편집)를 지우면 그 항목이 무엇을
    가리키는지 화면이 말하지 못한다. 엑셀 시트 이름은 애초에 사람이 지은 것이라 옮길
    표가 없다(``kind`` 가 그 갈래를 진다).
    """
    return PCLM_VIEW_TITLES.get(sheet, sheet) if kind == "pclm" else sheet


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
