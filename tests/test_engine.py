from __future__ import annotations

import zipfile
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
