from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

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
