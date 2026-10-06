"""계약 목록(pclm) 데이터 소스 — SQLite DB 를 엑셀 통합문서처럼 연다(Qt 불필요, 헤드리스).

붙들어 두는 것은 다섯이다.

1. **하드코딩이 없다** — 시트는 그 DB 의 ``sqlite_master`` 가 가진 뷰와 표다(뷰 먼저, 다음
   표, ``sqlite_*`` 내부 표 제외). 고정 허용목록은 사용자 결정(2026-09-30)으로 걷혔다.
2. **그 DB 에 없는 이름은 SELECT 전에 거절한다** — 사용자가 고른 문자열이 SQL 로 흘러드는
   유일한 자리라, 목록 대조와 식별자 인용(``"`` 이중화)이 주입 방어를 겸한다.
3. **읽기 전용으로 연다** — 그 DB 를 쓰는 주체는 pclm 하나뿐이다.
4. **빈 값이 빈 문자열로 온다** — None 을 만들어 넣으면 저쪽의 빈 값 경고가 죽는다.
5. **WAL 이어도 읽힌다** — pclm 이 창을 열어 둔 채여도 읽기가 막히면 안 된다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.data import DataSource
from hwpxfiller.data.factory import make_source, source_from_pool_item
from hwpxfiller.data.pclm import (
    PclmDataSource,
    list_sqlite_sheets,
)

COLUMNS = ("계약번호", "계약건명", "계약금액", "진행상태")
ROWS = [
    ("R26TA0215950700", "2026년 육군 잔류항생제분석기 조달", "170,309,180", "계약"),
    ("R26TA0216463900", "26년 육군 질량분석기 구매", "324,727,920", ""),
]
VIEW = "v_통합_v2"


def _build(db: Path, *, view: str = VIEW, rows=ROWS, keep_open=False):
    """pclm 이 내는 모양을 흉내 낸 DB — 표 하나 위에 뷰 하나를 얹는다."""
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL;")
    columns = ", ".join(f'"{name}" TEXT' for name in COLUMNS)
    connection.execute(f"CREATE TABLE 계약 ({columns});")
    placeholders = ", ".join("?" for _ in COLUMNS)
    connection.executemany(f"INSERT INTO 계약 VALUES ({placeholders});", rows)
    quoted = '"' + view.replace('"', '""') + '"'
    connection.execute(f"CREATE VIEW {quoted} AS SELECT * FROM 계약;")
    connection.commit()
    if keep_open:
        return connection  # -wal 을 남긴 채로 둔다(pclm 이 열려 있는 상태)
    connection.close()
    return None


def _build_mixed(db: Path) -> None:
    """표·뷰가 섞여 생긴 DB — 생성 순서를 일부러 엇갈리게 둔다(표→뷰→표→뷰)."""
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE 공고 (번호 TEXT PRIMARY KEY, 건명 TEXT);
        CREATE VIEW v_공고_v1 AS SELECT * FROM 공고;
        CREATE TABLE 계약 (번호 INTEGER PRIMARY KEY AUTOINCREMENT, 금액 INTEGER);
        CREATE VIEW v_계약_v1 AS SELECT * FROM 계약;
        CREATE INDEX idx_공고 ON 공고(건명);
        INSERT INTO 계약 (금액) VALUES (100);
        """
    )
    connection.commit()
    connection.close()


# ------------------------------------------------------------------ 시트 나열


def test_lists_views_first_then_tables_in_schema_order(tmp_path):
    """뷰 먼저, 다음 표 — 각 무리 안은 sqlite_master 순서. 색인·sqlite_* 는 시트가 아니다.

    ``AUTOINCREMENT`` 는 ``sqlite_sequence`` 를, TEXT ``PRIMARY KEY`` 는 자동 색인을 만든다 —
    둘 다 내부 것이라 나열에 서지 않는다.
    """
    db = tmp_path / "mixed.db"
    _build_mixed(db)
    assert list_sqlite_sheets(db) == ["v_공고_v1", "v_계약_v1", "공고", "계약"]


def test_every_listed_sheet_opens_as_a_source(tmp_path):
    """나열된 시트는 전부 읽힌다 — 뷰든 표든 같은 모양. 숫자 칼럼도 문자열로 온다."""
    db = tmp_path / "mixed.db"
    _build_mixed(db)
    for sheet in list_sqlite_sheets(db):
        src = PclmDataSource(db=db, view=sheet)
        assert src.fields()
        assert all(isinstance(v, str) for r in src.records() for v in r.values())
    assert PclmDataSource(db=db, view="계약").records() == [{"번호": "1", "금액": "100"}]


def test_listing_missing_database_fails_loudly(tmp_path):
    """나열도 조용히 빈 목록을 내지 않는다 — 부재는 소스와 같은 문장."""
    with pytest.raises(FileNotFoundError) as caught:
        list_sqlite_sheets(tmp_path / "없다.db")
    assert "찾지 못했습니다" in str(caught.value)


def test_listing_a_file_that_is_not_sqlite_is_a_runtime_error(tmp_path):
    """SQLite 가 아닌 파일은 열기 실패 문장 — 원시 sqlite3 예외가 새지 않는다."""
    bogus = tmp_path / "가짜.db"
    bogus.write_bytes(b"this is not a database at all" * 10)
    with pytest.raises(RuntimeError) as caught:
        list_sqlite_sheets(bogus)
    assert "열지 못했습니다" in str(caught.value)


def test_listing_opens_read_only(tmp_path, monkeypatch):
    """나열도 mode=ro URI 로만 붙는다."""
    db = tmp_path / "pclm.db"
    _build(db)
    seen: "list[str]" = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        seen.append(str(target))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    assert list_sqlite_sheets(db) == [VIEW, "계약"]
    assert len(seen) == 1
    assert seen[0].startswith("file:")
    assert seen[0].endswith("?mode=ro")


# ------------------------------------------------------- 그 DB 에 없는 시트


@pytest.mark.parametrize(
    "name",
    [
        "없는시트",
        "sqlite_master",
        'v_통합_v2"; DROP TABLE 계약; --',
        "",
    ],
)
def test_unknown_sheet_is_rejected_before_any_select(tmp_path, monkeypatch, name):
    """그 DB 에 없는 이름은 SELECT 가 **돌기 전에** 거절하고 쓸 수 있는 시트를 재진술한다.

    ``sqlite_master`` 는 실제로 존재하지만 내부 표라 시트가 아니다 — 거절된다. 주입 문자열이
    SELECT 에 닿지 않았다는 것은 실행된 문장 기록과, 표가 그대로 남은 것으로 함께 확인한다.
    """
    db = tmp_path / "pclm.db"
    _build(db)
    statements: "list[str]" = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        connection = real(target, *args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(ValueError) as caught:
        PclmDataSource(db=db, view=name).records()
    message = str(caught.value)
    assert "약속한 뷰가 아닙니다" in message
    assert VIEW in message
    assert "계약" in message  # 쓸 수 있는 시트를 재진술
    assert statements  # 목록 조회는 돌았다
    assert not any(s.lstrip().upper().startswith("SELECT *") for s in statements)
    monkeypatch.setattr(sqlite3, "connect", real)
    assert len(PclmDataSource(db=db, view="계약").records()) == 2


def test_sheet_name_with_a_double_quote_is_escaped(tmp_path):
    """이름에 ``"`` 가 든 시트도 목록에 있으면 열린다 — 인용은 ``"`` 를 두 번 적는다."""
    db = tmp_path / "pclm.db"
    odd = 'v_"따옴표"_면'
    _build(db, view=odd)
    assert odd in list_sqlite_sheets(db)
    assert PclmDataSource(db=db, view=odd).fields() == list(COLUMNS)


def test_view_is_required_no_default_sheet():
    """기본 시트가 없다 — 조용히 한 면을 추측하지 않는다(키워드 필수)."""
    with pytest.raises(TypeError):
        PclmDataSource(db="아무거나.db")  # type: ignore[call-arg]


# ------------------------------------------------------------------- 포트 준수


def test_reads_records_and_fields_as_a_datasource(tmp_path):
    db = tmp_path / "pclm.db"
    _build(db)
    src = PclmDataSource(db=db, view=VIEW)

    assert isinstance(src, DataSource)  # 포트 준수(runtime_checkable Protocol)
    assert src.fields() == list(COLUMNS)
    assert src.records()[0] == {
        "계약번호": "R26TA0215950700",
        "계약건명": "2026년 육군 잔류항생제분석기 조달",
        "계약금액": "170,309,180",
        "진행상태": "계약",
    }
    assert len(src.records()) == 2


def test_loads_once_per_instance(tmp_path, monkeypatch):
    """한 번 읽고 그 인스턴스 동안 붙든다 — 다시 읽는 것은 새 인스턴스(싱크)다."""
    db = tmp_path / "pclm.db"
    _build(db)
    calls: "list[str]" = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        calls.append(str(target))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    src = PclmDataSource(db=db, view=VIEW)
    src.records()
    src.fields()
    src.records()
    assert len(calls) == 1


def test_field_labels_is_empty_because_columns_are_the_header(tmp_path):
    """컬럼 이름이 곧 헤더라 어휘 선언이 없다 — 엑셀 헤더와 같은 취급."""
    db = tmp_path / "pclm.db"
    _build(db)
    assert PclmDataSource(db=db, view=VIEW).field_labels() == {}


def test_records_are_defensively_copied(tmp_path):
    """받은 dict 를 고쳐도 소스 내부가 오염되지 않는다(Excel·Inline 과 같은 규칙)."""
    db = tmp_path / "pclm.db"
    _build(db)
    src = PclmDataSource(db=db, view=VIEW)

    src.records()[0]["계약건명"] = "변조"
    assert src.records()[0]["계약건명"] == "2026년 육군 잔류항생제분석기 조달"
    src.fields().append("변조")
    assert src.fields() == list(COLUMNS)


def test_source_pointer_points_only(tmp_path):
    """원장 표기는 가리키는 곳만 — 쿼리도 값도 박제하지 않는다."""
    db = tmp_path / "pclm.db"
    _build(db)
    pointer = PclmDataSource(db=db, view=VIEW).source_pointer()

    assert pointer == f"sqlite:{db}#{VIEW}"
    assert "SELECT" not in pointer
    assert "R26TA0215950700" not in pointer


# --------------------------------------------------------------------- 빈 값


def test_null_becomes_empty_string_not_none(tmp_path):
    """빈 값이 None 으로 새면 「생성 값 미리보기」의 빈 값 경고가 죽는다."""
    db = tmp_path / "pclm.db"
    _build(db, rows=[("R26TA0215950700", "계약건명", None, None)])
    record = PclmDataSource(db=db, view=VIEW).records()[0]

    assert record["계약금액"] == ""
    assert record["진행상태"] == ""
    assert all(isinstance(value, str) for value in record.values())


# ---------------------------------------------------------------- 읽기 전용


def test_opens_read_only(tmp_path, monkeypatch):
    """mode=ro URI 로만 붙는다 — 이쪽이 실수로도 그 DB 에 쓰지 못하게."""
    db = tmp_path / "pclm.db"
    _build(db)
    seen: "list[tuple[str, bool]]" = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        seen.append((str(target), bool(kwargs.get("uri"))))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    PclmDataSource(db=db, view=VIEW).records()

    assert len(seen) == 1
    uri, as_uri = seen[0]
    assert as_uri is True
    assert uri.startswith("file:")
    assert uri.endswith("?mode=ro")


def test_reads_while_the_writer_holds_the_database_open(tmp_path):
    """WAL 이라 pclm 이 쓰는 중에도 읽기가 막히지 않는다(-wal 이 남아 있는 상태)."""
    db = tmp_path / "pclm.db"
    writer = _build(db, keep_open=True)
    try:
        assert Path(f"{db}-wal").exists()
        assert len(PclmDataSource(db=db, view=VIEW).records()) == 2
    finally:
        writer.close()


#: 계약 목록 앱이 자기 파일에 찍는 SQLite application_id(``"PCLM"``) — 저쪽 계약의 값 그대로.
PCLM_APPLICATION_ID = 0x50434C4D


def _build_pclm_file(path: Path) -> sqlite3.Connection:
    """계약 목록 앱이 내는 ``.pclm`` 그대로 — application_id·WAL, 체크포인트 전(-wal 에만 행).

    쓰는 쪽 연결을 열어 둔 채 돌려준다(저쪽 창이 열린 상태). 자동 체크포인트를 끄므로
    행은 본 파일이 아니라 ``-wal`` 에만 있다 — 읽기 전용 소비자가 WAL 을 함께 읽어야 보인다.
    """
    writer = sqlite3.connect(path)
    writer.execute(f"PRAGMA application_id = {PCLM_APPLICATION_ID};")
    writer.execute("PRAGMA journal_mode=WAL;")
    writer.execute("PRAGMA wal_autocheckpoint=0;")
    columns = ", ".join(f'"{name}" TEXT' for name in COLUMNS)
    writer.execute(f"CREATE TABLE 계약 ({columns});")
    writer.execute(f'CREATE VIEW "{VIEW}" AS SELECT * FROM 계약;')
    writer.commit()
    placeholders = ", ".join("?" for _ in COLUMNS)
    writer.executemany(f"INSERT INTO 계약 VALUES ({placeholders});", ROWS)
    writer.commit()
    return writer


def test_pclm_file_in_wal_with_application_id_lists_and_loads(tmp_path):
    """``.pclm`` 은 확장자만 다른 같은 SQLite 다 — 읽기 전용으로 열어 시트를 나열하고 읽는다.

    확장자·application_id 를 따지지 않는다(형식 판정은 SQLite 가 연다/못 연다 하나). 저쪽
    창이 열린 채 체크포인트 전이어도 WAL 의 행까지 보인다.
    """
    db = tmp_path / "계약목록.pclm"
    writer = _build_pclm_file(db)
    try:
        assert Path(f"{db}-wal").exists()
        probe = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            assert probe.execute("PRAGMA application_id;").fetchone()[0] == PCLM_APPLICATION_ID
            assert probe.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
        finally:
            probe.close()
        assert list_sqlite_sheets(db) == [VIEW, "계약"]
        source = PclmDataSource(db=db, view=VIEW)
        assert source.records() == [dict(zip(COLUMNS, row, strict=True)) for row in ROWS]
        assert source.source_pointer() == f"sqlite:{db}#{VIEW}"
    finally:
        writer.close()


# ------------------------------------------------------------------ 없는 자료


def test_missing_database_fails_loudly(tmp_path):
    """조용히 빈 목록을 내지 않는다 — 없으면 없다고 말한다."""
    src = PclmDataSource(db=tmp_path / "없다.db", view=VIEW)
    with pytest.raises(FileNotFoundError) as caught:
        src.records()
    assert "찾지 못했습니다" in str(caught.value)


def test_unreadable_sheet_is_a_runtime_error(tmp_path):
    """목록에는 있지만 SELECT 가 실패하는 시트(깨진 뷰) — 원시 예외 대신 읽기 실패 문장."""
    db = tmp_path / "pclm.db"
    _build(db)
    connection = sqlite3.connect(db)
    connection.execute("CREATE VIEW 깨진면 AS SELECT * FROM 사라진표;")
    connection.commit()
    connection.close()
    assert "깨진면" in list_sqlite_sheets(db)
    with pytest.raises(RuntimeError) as caught:
        PclmDataSource(db=db, view="깨진면").records()
    assert "읽지 못했습니다" in str(caught.value)


@pytest.mark.parametrize(
    "item",
    [
        pytest.param(SimpleNamespace(kind="pclm", opts={"db": "", "view": VIEW}), id="empty-db"),
        pytest.param(SimpleNamespace(kind="pclm", opts={"view": VIEW}), id="no-db-key"),
    ],
)
def test_empty_place_is_refused_not_guessed(item):
    """자리가 빈 참조는 다른 프로그램의 설치 자리로 추측하지 않고 거절한다.

    ``Path("")`` 는 현재 폴더라 그대로 두면 엉뚱한 자리를 열려 든다 — 어댑터 입구에서
    결속 복원과 같은 문장으로 끊는다. 시트 나열도 같은 입구를 지난다.
    """
    with pytest.raises(ValueError, match="데이터 참조에 경로가 없습니다"):
        source_from_pool_item(item)
    with pytest.raises(ValueError, match="데이터 참조에 경로가 없습니다"):
        list_sqlite_sheets("")


# -------------------------------------------------------------------- 팩토리


def test_factory_makes_pclm_by_kind(tmp_path):
    db = tmp_path / "pclm.db"
    _build(db, view="v_품목_v1")
    src = make_source("pclm", db=str(db), view="v_품목_v1")

    assert isinstance(src, PclmDataSource)
    assert isinstance(src, DataSource)
    assert src.fields() == list(COLUMNS)


def test_pool_item_restores_pclm_source(tmp_path):
    """풀 항목은 참조만 담는다 — 복원이 실행 시점의 재읽기(싱크)다."""
    db = tmp_path / "pclm.db"
    _build(db)
    item = SimpleNamespace(kind="pclm", opts={"db": str(db), "view": VIEW})
    src = source_from_pool_item(item)

    assert isinstance(src, PclmDataSource)
    assert len(src.records()) == 2


def test_pool_item_restores_a_plain_table_too(tmp_path):
    """저장된 참조 형상(kind=pclm, opts={db, view})은 그대로 — 표 이름을 가리켜도 열린다."""
    db = tmp_path / "pclm.db"
    _build(db)
    item = SimpleNamespace(kind="pclm", opts={"db": str(db), "view": "계약"})
    src = source_from_pool_item(item)

    assert src.fields() == list(COLUMNS)
    assert src.source_pointer() == f"sqlite:{db}#계약"
