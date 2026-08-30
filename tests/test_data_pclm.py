"""pclm(계약 목록) 데이터 소스 — 계약면 뷰를 레코드로 낸다(Qt 불필요, 헤드리스).

붙들어 두는 것은 넷이다.

1. **계약면만 읽는다** — 뷰 넷 밖의 이름은 파일을 열기도 전에 거절한다. 뷰 이름이
   SELECT 에 그대로 박히므로 이 거절이 주입 방어를 겸한다.
2. **읽기 전용으로 연다** — 그 DB 를 쓰는 주체는 pclm 하나뿐이다.
3. **빈 값이 빈 문자열로 온다** — None 을 만들어 넣으면 저쪽의 빈 값 경고가 죽는다.
4. **WAL 이어도 읽힌다** — pclm 이 창을 열어 둔 채여도 읽기가 막히면 안 된다.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.data import DataSource
from hwpxfiller.data.factory import make_source, source_from_pool_item
from hwpxfiller.data.pclm import (
    DEFAULT_PCLM_VIEW,
    PCLM_VIEW_LABELS,
    PCLM_VIEWS,
    PclmDataSource,
    default_pclm_db,
)

COLUMNS = ("계약번호", "계약건명", "계약금액", "진행상태")
ROWS = [
    ("R26TA0215950700", "2026년 육군 잔류항생제분석기 조달", "170,309,180", "계약"),
    ("R26TA0216463900", "26년 육군 질량분석기 구매", "324,727,920", ""),
]


def _build(db: Path, *, view: str = DEFAULT_PCLM_VIEW, rows=ROWS, keep_open=False):
    """pclm 이 내는 모양을 흉내 낸 DB — 표 하나 위에 계약면 뷰를 얹는다."""
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL;")
    columns = ", ".join(f'"{name}" TEXT' for name in COLUMNS)
    connection.execute(f"CREATE TABLE 계약 ({columns});")
    placeholders = ", ".join("?" for _ in COLUMNS)
    connection.executemany(f"INSERT INTO 계약 VALUES ({placeholders});", rows)
    connection.execute(f'CREATE VIEW "{view}" AS SELECT * FROM 계약;')
    connection.commit()
    if keep_open:
        return connection  # -wal 을 남긴 채로 둔다(pclm 이 열려 있는 상태)
    connection.close()
    return None


# ------------------------------------------------------------------ 계약면만


def test_rejects_view_outside_the_contract_before_touching_disk():
    """뷰 넷 밖의 이름은 ValueError — 파일이 없어도(=열기 전에) 거절한다."""
    for name in ("계약", "sqlite_master", 'v_통합_v1"; DROP TABLE 계약; --'):
        with pytest.raises(ValueError) as caught:
            PclmDataSource(db="없는파일.db", view=name)
        assert "약속한 뷰가 아닙니다" in str(caught.value)


def test_every_contract_view_is_accepted(tmp_path):
    """뷰 넷은 모두 받는다 — 목록이 곧 계약면이다."""
    for view in PCLM_VIEWS:
        db = tmp_path / f"{view}.db"
        _build(db, view=view)
        assert PclmDataSource(db=db, view=view).fields() == list(COLUMNS)


def test_every_view_carries_a_line_that_says_what_one_row_is():
    """설명 없는 뷰를 허용목록에 늘리지 않는다 — 고르는 기준이 '한 줄이 무엇인가'다."""
    assert set(PCLM_VIEW_LABELS) == set(PCLM_VIEWS)
    assert all(PCLM_VIEW_LABELS[view].strip() for view in PCLM_VIEWS)


def test_default_view_is_the_joined_one():
    """기본은 계약 + 이어진 공고. 한 줄이 계약 하나다."""
    assert DEFAULT_PCLM_VIEW == "v_통합_v1"
    assert DEFAULT_PCLM_VIEW in PCLM_VIEWS


# ------------------------------------------------------------------- 포트 준수


def test_reads_records_and_fields_as_a_datasource(tmp_path):
    db = tmp_path / "pclm.db"
    _build(db)
    src = PclmDataSource(db=db)

    assert isinstance(src, DataSource)  # 포트 준수(runtime_checkable Protocol)
    assert src.fields() == list(COLUMNS)
    assert src.records()[0] == {
        "계약번호": "R26TA0215950700",
        "계약건명": "2026년 육군 잔류항생제분석기 조달",
        "계약금액": "170,309,180",
        "진행상태": "계약",
    }
    assert len(src.records()) == 2


def test_field_labels_is_empty_because_columns_are_already_korean(tmp_path):
    """컬럼이 이미 한글 라벨이라 어휘 선언이 없다 — 엑셀 헤더와 같은 취급."""
    db = tmp_path / "pclm.db"
    _build(db)
    assert PclmDataSource(db=db).field_labels() == {}


def test_records_are_defensively_copied(tmp_path):
    """받은 dict 를 고쳐도 소스 내부가 오염되지 않는다(Excel·Inline 과 같은 규칙)."""
    db = tmp_path / "pclm.db"
    _build(db)
    src = PclmDataSource(db=db)

    src.records()[0]["계약건명"] = "변조"
    assert src.records()[0]["계약건명"] == "2026년 육군 잔류항생제분석기 조달"


def test_source_pointer_points_only(tmp_path):
    """원장 표기는 가리키는 곳만 — 쿼리도 값도 박제하지 않는다."""
    db = tmp_path / "pclm.db"
    _build(db)
    pointer = PclmDataSource(db=db).source_pointer()

    assert pointer == f"sqlite:{db}#v_통합_v1"
    assert "SELECT" not in pointer
    assert "R26TA0215950700" not in pointer


# --------------------------------------------------------------------- 빈 값


def test_null_becomes_empty_string_not_none(tmp_path):
    """빈 값이 None 으로 새면 「생성 값 미리보기」의 빈 값 경고가 죽는다."""
    db = tmp_path / "pclm.db"
    _build(db, rows=[("R26TA0215950700", "계약건명", None, None)])
    record = PclmDataSource(db=db).records()[0]

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
    PclmDataSource(db=db).records()

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
        assert len(PclmDataSource(db=db).records()) == 2
    finally:
        writer.close()


# ------------------------------------------------------------------ 없는 자료


def test_missing_database_fails_loudly(tmp_path):
    """조용히 빈 목록을 내지 않는다 — 없으면 없다고 말한다."""
    src = PclmDataSource(db=tmp_path / "없다.db")
    with pytest.raises(FileNotFoundError) as caught:
        src.records()
    assert "찾지 못했습니다" in str(caught.value)


def _isolate_pclm_places(monkeypatch, tmp_path):
    """개발 기기의 실제 pclm 쪽지·자료가 새어들지 않게 두 자리를 임시 폴더로 — 헬퍼.

    ``default_pclm_db`` 는 이제 ``%APPDATA%`` 의 쪽지도 읽으므로, LOCALAPPDATA 만 갈아끼운
    테스트는 이 기계에 진짜 ``config.json`` 이 있는 순간 다른 답을 낸다.
    """
    roaming = tmp_path / "Roaming"
    local = tmp_path / "Local"
    roaming.mkdir(exist_ok=True)
    local.mkdir(exist_ok=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return roaming, local


def _write_config(roaming: Path, text: str) -> Path:
    cfg_dir = roaming / "Pclm"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.json"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_default_db_points_at_the_place_pclm_writes(monkeypatch, tmp_path):
    """쪽지가 없으면 저쪽 Database.DefaultPath 와 같은 자리 — 종전 고정 자리 그대로."""
    _, local = _isolate_pclm_places(monkeypatch, tmp_path)
    assert default_pclm_db() == local / "Pclm" / "pclm.db"


def test_default_db_follows_the_configured_data_dir(monkeypatch, tmp_path):
    """사용자가 옮긴 자료 폴더(config.json 의 dataDir)를 따라간다 — 자리는 여전히 하나."""
    roaming, _ = _isolate_pclm_places(monkeypatch, tmp_path)
    moved = tmp_path / "계약목록_자료"
    _write_config(roaming, f'{{"dataDir": {json.dumps(str(moved))}, "pendingMoveFrom": null}}')
    assert default_pclm_db() == moved / "pclm.db"


def test_default_db_ignores_pending_move_marker(monkeypatch, tmp_path):
    """pendingMoveFrom 은 저쪽 창의 혼잣말 — 값이 있어도 dataDir 만 본다."""
    roaming, _ = _isolate_pclm_places(monkeypatch, tmp_path)
    moved = tmp_path / "옮긴자리"
    _write_config(
        roaming,
        f'{{"dataDir": {json.dumps(str(moved))}, "pendingMoveFrom": "C:\\\\old"}}',
    )
    assert default_pclm_db() == moved / "pclm.db"


@pytest.mark.parametrize(
    "config_text",
    [
        pytest.param(None, id="no-config"),
        pytest.param("{이건 JSON 이 아니다", id="broken-json"),
        pytest.param('{"dataDir": null}', id="null-datadir"),
        pytest.param('{"dataDir": ""}', id="empty-datadir"),
        pytest.param('{"dataDir": 7}', id="non-string-datadir"),
        pytest.param('["dataDir"]', id="non-object-root"),
    ],
)
def test_default_db_falls_back_quietly_when_the_note_is_unusable(
    monkeypatch, tmp_path, config_text
):
    """쪽지 하나 때문에 멈추지 않는다 — 어떤 실패 경로도 예외 없이 기본 자리로."""
    roaming, local = _isolate_pclm_places(monkeypatch, tmp_path)
    if config_text is not None:
        _write_config(roaming, config_text)
    assert default_pclm_db() == local / "Pclm" / "pclm.db"


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
    item = SimpleNamespace(kind="pclm", opts={"db": str(db), "view": "v_통합_v1"})
    src = source_from_pool_item(item)

    assert isinstance(src, PclmDataSource)
    assert len(src.records()) == 2
