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


def test_generate_reports_template_open_failure(tmp_path):
    """정직-실패 계약(engine.py:38) — 손상 템플릿(zip 아님)은 ok=True 로 위장하지 못하고
    ok=False + "템플릿 열기 실패" 로 강등한다. 실패를 산출물로 문서화하지 않는다."""
    engine = HwpxEngine()
    bad = tmp_path / "corrupt.hwpx"
    bad.write_bytes(b"not a real hwpx zip")
    out = tmp_path / "gen.hwpx"
    res = engine.generate(str(bad), {"입찰공고번호": "A1"}, str(out))
    assert not res.ok
    assert "템플릿 열기 실패" in res.error
    assert not out.exists()


def test_generate_reports_xml_processing_failure(tmp_path, monkeypatch):
    """정직-실패 계약(engine.py:55) — XML 처리 단계 예외는 삼키지 않고
    ok=False + "XML 처리 실패" 로 전파한다."""
    from hwpxfiller.core import engine as engine_mod

    class _Boom:  # FieldDocument 생성 시점에 폭발 — 처리 루프 진입 즉시 예외
        def __init__(self, *args, **kwargs):
            raise RuntimeError("XML 파싱 폭발 주입")

    monkeypatch.setattr(engine_mod, "FieldDocument", _Boom)
    engine = HwpxEngine()
    out = tmp_path / "gen.hwpx"
    res = engine.generate(str(FIXTURE), {"입찰공고번호": "A1"}, str(out))
    assert not res.ok
    assert "XML 처리 실패" in res.error
    assert not out.exists()


def test_generate_reports_save_failure(tmp_path, monkeypatch):
    """정직-실패 계약(engine.py:60) — 저장 단계 예외를 엔진이 ok=False + "저장 실패" 로
    변환·전파한다(원자/패키지 계층 실패를 엔진 결과로 정직하게 노출)."""
    from hwpxcore.package import HwpxPackage

    def _boom(self):  # save 가 페이로드를 선평가하는 to_bytes 에서 폭발
        raise RuntimeError("직렬화 실패 주입")

    engine = HwpxEngine()
    fields = _required(engine)
    data = {f: f"VAL_{i}" for i, f in enumerate(fields)}
    monkeypatch.setattr(HwpxPackage, "to_bytes", _boom)
    out = tmp_path / "gen.hwpx"
    res = engine.generate(str(FIXTURE), data, str(out))
    assert not res.ok
    assert "저장 실패" in res.error
    assert not out.exists()  # 저장 실패 시 산출물이 남지 않는다


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


# ------------------------------------------------------- stale 줄배치 캐시(#95)
CORPUS_NOTICE = Path(__file__).parent / "corpus" / "real" / "bid_notice_limited_under100m.hwpx"


def test_generate_strips_stale_lineseg_from_modified_sections(tmp_path):
    """#95 실코퍼스 회귀 — 캐시를 무겁게 지닌 실제 공고서 템플릿을 채우면
    변경된 XML 의 stale 줄배치 캐시가 전량 제거되고, 미변경 XML 은 바이트 그대로다."""
    from hwpxcore.package import HwpxPackage

    engine = HwpxEngine()
    fields = engine.required_fields(str(CORPUS_NOTICE))
    assert fields  # 템플릿에 누름틀 실재(양성 대조 1)

    out = tmp_path / "filled.hwpx"
    res = engine.generate(str(CORPUS_NOTICE), {f: "값" for f in fields}, str(out))
    assert res.ok

    src = HwpxPackage.open(str(CORPUS_NOTICE))
    dst = HwpxPackage.open(str(out))
    changed = [
        n for n in dst.content_xml_names() if dst.entries[n] != src.entries[n]
    ]
    assert changed  # 채움이 실제로 일어났다
    # 변경 전 XML 에 stale 후보 캐시가 실재했다(양성 대조 2 — 스트립 무의미 방지)
    assert sum(src.entries[n].count(b"linesegarray") for n in changed) > 0
    # 변경된 XML 은 캐시 0 — 미변경 XML 은 changed 판정상 바이트 동일 = 보존 자동 성립
    for name in changed:
        assert dst.entries[name].count(b"linesegarray") == 0


def test_regenerate_same_values_is_byte_stable(tmp_path):
    """동일 값 재생성(무변경 재실행) — 재작성도 캐시 상실도 없이 콘텐츠 XML 바이트 그대로(#95).

    엔진 쓰기 게이트가 매칭이 아닌 실변경(doc.modified)을 소비함을 핀한다:
    "재작성된 XML + 캐시 잔존" 조합은 불가능해야 한다(재작성 ⇔ modified ⇔ 스트립).
    """
    from hwpxcore.package import HwpxPackage

    engine = HwpxEngine()
    data = {f: "값" for f in engine.required_fields(str(CORPUS_NOTICE))}
    out1 = tmp_path / "a.hwpx"
    out2 = tmp_path / "b.hwpx"
    assert engine.generate(str(CORPUS_NOTICE), data, str(out1)).ok
    res2 = engine.generate(str(out1), data, str(out2))  # 같은 데이터로 재생성
    assert res2.ok
    assert res2.unmatched == set()  # 동일 값 재채움도 매칭 보고는 정직

    p1 = HwpxPackage.open(str(out1))
    p2 = HwpxPackage.open(str(out2))
    for name in p1.content_xml_names():
        assert p2.entries[name] == p1.entries[name]
