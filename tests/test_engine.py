from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.batch import generate_batch
from hwpxfiller.core.engine import HwpxEngine

FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


def _required(engine):
    return engine.required_fields(str(FIXTURE))


def test_generate_injects_and_output_is_valid_hwpx(tmp_path):
    engine = HwpxEngine()
    fields = _required(engine)
    assert fields, "템플릿에 요구 필드가 있어야 함"

    data = {f: f"VAL_{i}" for i, f in enumerate(fields)}
    out = tmp_path / "gen.hwpx"
    res = engine.generate(str(FIXTURE), data, str(out))

    assert res.ok, res.error
    assert res.applied  # 최소 하나는 주입됨
    assert out.exists()

    # 결과가 유효한 HWPX(zip) 이고 mimetype 규칙 유지
    with zipfile.ZipFile(out) as zf:
        assert zf.infolist()[0].filename == "mimetype"
        # 주입값이 어느 XML엔가 존재
        blob = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xml"))
    assert b"VAL_0" in blob


def test_batch_generates_multiple_files(tmp_path):
    engine = HwpxEngine()
    fields = _required(engine)
    key = fields[0]
    records = [
        {key: "가나다", "ID": "A1"},
        {key: "라마바", "ID": "A2"},
    ]
    batch = generate_batch(str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine)
    assert batch.total == 2
    assert batch.succeeded == 2
    assert (tmp_path / "doc-A1.hwpx").exists()
    assert (tmp_path / "doc-A2.hwpx").exists()


def test_batch_collision_suffixes_dedupe(tmp_path):
    # 두 레코드가 같은 파일명을 만들면 덮어쓰지 않고 _1 접미사로 유일화.
    engine = HwpxEngine()
    key = _required(engine)[0]
    records = [{key: "가", "ID": "A1"}, {key: "나", "ID": "A1"}]
    batch = generate_batch(str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine)
    assert batch.succeeded == 2
    assert (tmp_path / "doc-A1.hwpx").exists()
    assert (tmp_path / "doc-A1_1.hwpx").exists()


def test_batch_seq_and_date_tokens(tmp_path):
    engine = HwpxEngine()
    key = _required(engine)[0]
    records = [{key: "가"}, {key: "나"}]
    now = datetime(2026, 7, 9, 0, 0, 0)
    batch = generate_batch(
        str(FIXTURE), records, str(tmp_path), "{{date:YYYYMMDD}}-{{seq:001}}", engine, now=now
    )
    assert batch.succeeded == 2
    assert (tmp_path / "20260709-001.hwpx").exists()
    assert (tmp_path / "20260709-002.hwpx").exists()


def test_batch_blocks_existing_outputs_without_overwrite(tmp_path):
    """RC-02 — 대상 파일이 디스크에 이미 있으면 생성을 시작하기 전에 원자 차단.

    같은 폴더 재실행(기본 동선)이 사용자 수기 보정본을 무경고 교체하던 결함의 회귀 방어:
    하나라도 충돌이면 전건 차단(부분 생성 없음), 기존 파일 바이트는 그대로다.
    """
    engine = HwpxEngine()
    key = _required(engine)[0]
    records = [{key: "가", "ID": "A1"}, {key: "나", "ID": "A2"}]
    generate_batch(str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine)

    # 사용자 수기 보정본 모사 — 재실행이 이걸 조용히 덮으면 안 된다.
    sentinel = tmp_path / "doc-A1.hwpx"
    sentinel.write_bytes(b"user-edited")
    other_bytes = (tmp_path / "doc-A2.hwpx").read_bytes()

    with pytest.raises(FileExistsError, match="덮어쓰"):
        generate_batch(str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine)
    assert sentinel.read_bytes() == b"user-edited"                 # 보정본 무손상
    assert (tmp_path / "doc-A2.hwpx").read_bytes() == other_bytes  # 전건 차단


def test_batch_overwrite_optin_replaces_existing(tmp_path):
    """--overwrite 계약 — 명시 옵트인 시에만 기존 파일을 교체한다."""
    engine = HwpxEngine()
    key = _required(engine)[0]
    records = [{key: "가", "ID": "A1"}]
    generate_batch(str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine)
    (tmp_path / "doc-A1.hwpx").write_bytes(b"user-edited")

    batch = generate_batch(
        str(FIXTURE), records, str(tmp_path), "doc-{{ID}}", engine, overwrite=True
    )
    assert batch.succeeded == 1
    assert (tmp_path / "doc-A1.hwpx").read_bytes()[:2] == b"PK"  # 재생성본으로 교체됨


def test_batch_progress_callback(tmp_path):
    engine = HwpxEngine()
    key = _required(engine)[0]
    records = [{key: "가"}, {key: "나"}, {key: "다"}]
    seen: list[tuple[int, int]] = []
    generate_batch(
        str(FIXTURE), records, str(tmp_path), "doc-{{seq}}", engine,
        progress=lambda d, t: seen.append((d, t)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]
