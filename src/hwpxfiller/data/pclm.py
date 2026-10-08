"""계약 목록(pclm) 데이터 소스 — SQLite DB 하나를 **엑셀 통합문서처럼** 연다.

pclm 은 나라장터에서 내려받은 입찰공고서·계약서 PDF 를 읽어 SQLite 에 쌓는 별개의
프로그램이다. 종전에는 이 저장소가 그쪽의 **뷰 네 개**만 허용목록으로 받았지만, 저쪽
스키마가 자라며(뷰 15종·내부 표 수십 개) 허용목록은 새 면을 전부 거절하는 박제가 됐다.
사용자 결정(2026-09-30)으로 하드코딩을 걷었다: 이 소스는 **pclm 의 스키마를 모른다**.
DB 를 받아 그 안의 뷰와 표를 시트로 나열하고(:func:`list_sqlite_sheets`), 고른 시트 하나를
레코드로 낸다 — 엑셀 통합문서에서 시트를 고르는 것과 같은 모양이다.

**시트 이름은 그 DB 가 가진 것만 SELECT 에 들어간다.** 고른 이름이 ``sqlite_master`` 에
실제로 있는지 먼저 확인한 뒤에야 인용해 SELECT 에 박는다(``"`` 는 두 번 적어 이스케이프).
허용목록이 겸하던 주입 방어를 이 대조가 잇는다 — 사용자가 고른 문자열이 SQL 로 흘러드는
유일한 자리가 여기다.

**값을 손질하지 않는다.** pclm 계약면의 컬럼은 이미 *문서에 그대로 찍힐 문자열*이다 —
금액 ``170,309,180``, 날짜 ``2026/10/24``. 빈 값은 빈 문자열로 오고, NULL 이 오면 빈
문자열로 받는다(None 을 만들어 넣으면 「생성 값 미리보기」의 **빈 값 경고가 죽는다**).
숫자 칼럼(내부 표)은 ``str()`` 한 그대로다.

**읽기 전용으로 연다.** 그 DB 를 쓰는 주체는 pclm 하나뿐이므로, 이쪽이 실수로도 쓰지
못하게 ``mode=ro`` URI 로 붙는다. 저널이 WAL 이라 pclm 이 쓰는 중에도 읽기가 막히지 않는다.

**어휘를 선언하지 않는다**(``field_labels`` 가 빈 dict). 컬럼 이름이 곧 헤더다 — 엑셀과 같다.

한 줄이 뜻하는 것은 시트마다 다르다(계약 1건 / 품목 1줄 …). 무엇을 고를지는 사람이 정한다 —
이 소스는 기본 시트를 두지 않는다(조용히 한 면을 추측하면 문서 건수가 어긋난다).
"""
from __future__ import annotations

import sqlite3
import urllib.request
from pathlib import Path

__all__ = [
    "PclmDataSource",
    "list_sqlite_sheets",
]


def _db_path(db: "str | Path | None") -> Path:
    """사용자가 고른 DB 자리 — 비었으면 거절한다(다른 프로그램의 설치 자리를 추측하지 않는다).

    ``Path("")`` 는 현재 폴더(``.``)라 그대로 두면 엉뚱한 자리를 열려 든다. 빈 자리는
    구판 참조의 손상이지 「기본 자리」가 아니다 — 결속 복원
    (:func:`~hwpxfiller.data.factory.source_for_binding`)과 같은 문장으로 거절한다.
    """
    if not db:  # None·"" — 경로 객체는 비지 않는다
        raise ValueError("데이터 참조에 경로가 없습니다.")
    return Path(db)


def _connect(db: Path) -> sqlite3.Connection:
    """``db`` 를 읽기 전용으로 연다 — 부재는 ``FileNotFoundError``, 열기 실패는 ``RuntimeError``."""
    if not db.exists():
        raise FileNotFoundError(f"pclm 자료를 찾지 못했습니다: {db}")
    # 드라이브 문자·공백·한글이 섞인 경로를 URI 로 옮긴다. 문자열을 이어 붙이면
    # 경로 안의 ? 나 # 이 URI 의 문법으로 읽혀 엉뚱한 파일을 열거나 실패한다.
    uri = f"file:{urllib.request.pathname2url(str(db))}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RuntimeError(f"pclm 자료를 열지 못했습니다: {db} ({exc})") from exc


def registered_workfile_sheets(path: str, dataset_id: str) -> list[str]:
    """자동 연결은 외부 config와 같은 신원의 업무 자료·기본 계약면만 받는다."""
    db = _db_path(path)
    conn = _connect(db)
    try:
        identity = conn.execute(
            "SELECT role, dataset_id FROM pclm_file WHERE singleton = 1"
        ).fetchone()
        sheets = _sheets_of(conn, db)
        selected = ["v_통합", "v_접수", "v_공고", "v_계약"]
        if identity != ("work", dataset_id) or any(name not in sheets for name in selected):
            raise ValueError(f"pclm 자료를 열지 못했습니다: {db}")
        return selected
    finally:
        conn.close()


def _sheets_of(connection: sqlite3.Connection, db: Path) -> "list[str]":
    """열린 DB 의 시트 — 뷰 먼저, 다음 표. 각 무리 안은 ``sqlite_master`` 순서 그대로.

    ``sqlite_`` 로 시작하는 이름(SQLite 내부 표)은 뺀다. 그 접두는 SQLite 가 대소문자를
    가리지 않고 예약하므로 거르기도 대소문자를 가리지 않는다. 뷰가 먼저인 이유는 뷰가
    그 DB 가 **밖에 내놓은** 면이기 때문이다(표는 뒤에 그대로 남긴다 — 숨기지 않는다).
    """
    try:
        rows = connection.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('view', 'table') ORDER BY rowid"
        ).fetchall()
    except sqlite3.Error as exc:  # 손상·SQLite 아닌 파일 — 열기 실패와 같은 문장
        raise RuntimeError(f"pclm 자료를 열지 못했습니다: {db} ({exc})") from exc
    visible = [
        (kind, str(name)) for kind, name in rows
        if not str(name).lower().startswith("sqlite_")
    ]
    return [n for k, n in visible if k == "view"] + [n for k, n in visible if k == "table"]


def list_sqlite_sheets(db: "str | Path") -> "list[str]":
    """SQLite DB 가 가진 시트(뷰 먼저, 다음 표) — 등록 폼과 등록 게이트가 고를 목록.

    :param db: SQLite 파일 — 사용자가 고른 자리.
    :raises ValueError: 자리가 비었다.
    :raises FileNotFoundError: 파일이 없다.
    :raises RuntimeError: 열 수 없거나 SQLite 가 아니다.
    """
    path = _db_path(db)
    connection = _connect(path)
    try:
        return _sheets_of(connection, path)
    finally:
        connection.close()


def _quote(name: str) -> str:
    """SQL 식별자 인용 — ``"`` 는 두 번 적는다(표준 SQL 이스케이프)."""
    return '"' + name.replace('"', '""') + '"'


class PclmDataSource:
    """SQLite DB 의 시트 하나(뷰 또는 표)를 :class:`~hwpxfiller.domain.data_source.DataSource` 로 낸다.

    :param db: SQLite 파일 — 사용자가 고른 자리. 비어 있으면(구판 참조의 빈 ``db``) 생성
        시점에 ``ValueError`` 다 — 다른 프로그램의 설치 자리를 추측하지 않는다.
    :param view: 시트 이름 — 그 DB 의 뷰 또는 표. 없는 이름은 로드 때 ``ValueError``
        (쓸 수 있는 시트를 재진술한다). 키 이름 ``view`` 는 저장된 참조(``opts={db, view}``)
        와의 호환을 위해 그대로 둔다.
    """

    def __init__(
        self,
        db: "str | Path",
        *,
        view: str,
    ) -> None:
        self.db = _db_path(db)
        self.view = view
        self._fields: "list[str]" = []
        self._records: "list[dict[str, str]]" = []
        self._loaded = False

    # 한 번 읽고 그 인스턴스 동안 붙들고 있는다. 다시 읽는 것(싱크)은 풀 항목을 복원해
    # **새 인스턴스를 만드는 것**이다 — Excel 소스와 같은 규칙이라 다운스트림이 구별하지 않는다.
    def _load(self) -> None:
        if self._loaded:
            return

        connection = _connect(self.db)
        try:
            # 고른 이름이 이 DB 에 실제로 있는지부터 — SELECT 에 박히는 것은 이 목록의 원소뿐이다.
            sheets = _sheets_of(connection, self.db)
            if not isinstance(self.view, str) or self.view not in sheets:
                raise ValueError(
                    f"pclm 이 약속한 뷰가 아닙니다: {self.view!r}. "
                    f"쓸 수 있는 뷰: {', '.join(sheets)}"
                )
            try:
                cursor = connection.execute(f"SELECT * FROM {_quote(self.view)}")
                self._fields = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
            except sqlite3.Error as exc:
                raise RuntimeError(
                    f"pclm 뷰를 읽지 못했습니다: {self.view} ({exc}). "
                    "계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다."
                ) from exc
        finally:
            connection.close()

        # 빈 값은 빈 문자열로 받는다 — 레코드는 dict[str, str] 라는 포트 약속이 이쪽 책임이다.
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
        """컬럼 이름이 곧 헤더라 어휘가 없다(빈 dict) — 엑셀 헤더와 같다."""
        return {}

    def source_pointer(self) -> str:
        """원장에 남길 표기 — 가리키는 곳만. 쿼리도 값도 박제하지 않는다."""
        return f"sqlite:{self.db}#{self.view}"
