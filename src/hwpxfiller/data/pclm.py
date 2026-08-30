"""pclm(계약 목록) 데이터 소스 — 조달 계약 DB 의 계약면 뷰를 레코드로 낸다.

pclm 은 나라장터에서 내려받은 입찰공고서·계약서 PDF 를 읽어 SQLite 에 쌓는 별개의
프로그램이다. 이 저장소가 그쪽에 의존하는 것은 **뷰 네 개**뿐이다 — 테이블은 예고 없이
바뀐다고 저쪽이 못박아 두었다(그쪽 ``docs/dataset-contract.md``).

**값을 손질하지 않는다.** 계약면의 모든 컬럼은 이미 *문서에 그대로 찍힐 문자열*이다 —
금액 ``170,309,180``, 날짜 ``2026/10/24``, 비율 ``84.245``. 빈 값은 NULL 이 아니라 빈
문자열로 오는데, 이것이 중요하다: 여기서 None 을 만들어 넣으면 「생성 값 미리보기」의
**빈 값 경고가 죽고** 빈칸이 그대로 문서에 남는다. 그래서 읽어서 그대로 넘긴다.

**읽기 전용으로 연다.** 그 DB 를 쓰는 주체는 pclm 하나뿐이므로, 이쪽이 실수로도 쓰지
못하게 ``mode=ro`` URI 로 붙는다. 저널이 WAL 이라 pclm 이 쓰는 중에도 읽기가 막히지 않는다.

**어휘를 선언하지 않는다**(``field_labels`` 가 빈 dict). 컬럼 이름이 이미 한글이라
엑셀 헤더와 똑같이 동작한다 — 이름 대응표를 들고 있을 필요가 없다.

한 줄이 뜻하는 것이 뷰마다 다르다. 계약 단위 문서에는 ``v_통합_v1``(계약 + 이어진 공고)
이나 ``v_계약_v1`` 을, 품목 명세에는 ``v_품목_v1`` 을 쓴다 — 섞으면 안 된다.
"""
from __future__ import annotations

import os
import sqlite3
import urllib.request
from pathlib import Path

__all__ = [
    "DEFAULT_PCLM_VIEW",
    "PCLM_VIEWS",
    "PclmDataSource",
    "default_pclm_db",
]

# 계약면. pclm 이 약속한 것은 이 넷뿐이라 그 밖의 이름은 받지 않는다.
# 뷰 이름은 SELECT 문에 그대로 박히므로 이 허용목록이 주입 방어를 겸한다 —
# 사용자가 고른 문자열이 SQL 로 흘러드는 유일한 자리가 여기다.
PCLM_VIEWS: "tuple[str, ...]" = ("v_통합_v1", "v_공고_v1", "v_계약_v1", "v_품목_v1")

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


class PclmDataSource:
    """pclm 계약면 뷰 하나를 :class:`~hwpxfiller.domain.data_source.DataSource` 로 낸다.

    :param db: pclm SQLite 파일. ``None`` 이면 :func:`default_pclm_db`.
    :param view: :data:`PCLM_VIEWS` 중 하나. 그 밖의 이름은 ``ValueError``.
    """

    def __init__(
        self,
        db: "str | Path | None" = None,
        view: str = DEFAULT_PCLM_VIEW,
    ) -> None:
        if view not in PCLM_VIEWS:
            raise ValueError(
                f"pclm 이 약속한 뷰가 아닙니다: {view!r}. "
                f"쓸 수 있는 뷰: {', '.join(PCLM_VIEWS)}"
            )
        self.db = Path(db) if db is not None else default_pclm_db()
        self.view = view
        self._fields: "list[str]" = []
        self._records: "list[dict[str, str]]" = []
        self._loaded = False

    # 한 번 읽고 그 인스턴스 동안 붙들고 있는다. 다시 읽는 것(싱크)은 풀 항목을 복원해
    # **새 인스턴스를 만드는 것**이다 — Excel 소스와 같은 규칙이라 다운스트림이 구별하지 않는다.
    def _load(self) -> None:
        if self._loaded:
            return

        if not self.db.exists():
            raise FileNotFoundError(
                f"pclm 자료를 찾지 못했습니다: {self.db}\n"
                "계약 목록 앱을 한 번 실행했는지 확인하세요. "
                "다른 자료를 읽으려면 db= 로 그 경로를 짚습니다."
            )

        # 드라이브 문자·공백·한글이 섞인 경로를 URI 로 옮긴다. 문자열을 이어 붙이면
        # 경로 안의 ? 나 # 이 URI 의 문법으로 읽혀 엉뚱한 파일을 열거나 실패한다.
        uri = f"file:{urllib.request.pathname2url(str(self.db))}?mode=ro"

        try:
            connection = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise RuntimeError(f"pclm 자료를 열지 못했습니다: {self.db} ({exc})") from exc

        try:
            cursor = connection.execute(f'SELECT * FROM "{self.view}"')
            self._fields = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError(
                f"pclm 뷰를 읽지 못했습니다: {self.view} ({exc}). "
                "계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다."
            ) from exc
        finally:
            connection.close()

        # 계약면은 빈 값을 빈 문자열로 내기로 되어 있지만, None 이 와도 빈 문자열로 받는다 —
        # 레코드는 dict[str, str] 라는 포트 약속이 이쪽 책임이다.
        self._records = [
            {
                name: "" if value is None else str(value)
                for name, value in zip(self._fields, row, strict=True)
            }
            for row in rows
        ]
        self._loaded = True

    # ---------------------------------------------------------- DataSource
    def records(self) -> "list[dict[str, str]]":
        self._load()
        # 방어 복사 — 받은 쪽이 dict 를 고쳐도 소스 내부가 오염되지 않는다.
        return [dict(record) for record in self._records]

    def fields(self) -> "list[str]":
        self._load()
        return list(self._fields)

    def field_labels(self) -> "dict[str, str]":
        """컬럼 이름이 이미 한글 라벨이라 어휘가 없다(빈 dict) — 엑셀 헤더와 같다."""
        return {}

    def source_pointer(self) -> str:
        """원장에 남길 표기 — 가리키는 곳만. 쿼리도 값도 박제하지 않는다."""
        return f"sqlite:{self.db}#{self.view}"
