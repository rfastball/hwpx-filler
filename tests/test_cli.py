"""CLI 테스트 — 기본 채우기 흐름 + 데이터 소스 선택(엑셀/나라장터) + 프로파일 매핑.

나라장터는 네트워크 없이: ``NaraStdDataSource._fetch`` 를 픽스처 바이트로 몽키패치.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from hwpxfiller.cli import main
from hwpxfiller.core.mapping import FieldMapping, MappingProfile

CORPUS = Path(__file__).parent / "corpus" / "real"
FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = str(CORPUS / "bid_notice_limited_under100m.hwpx")
FIELDS = ["입찰공고번호", "공고명", "계약방법", "추정가격", "개찰일시"]


def _xlsx(path: Path, rows: "list[list[str]]") -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(FIELDS)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def _outputs(d: Path) -> "list[str]":
    return sorted(p.name for p in d.glob("*.hwpx"))


# --------------------------------------------------------------------- --fields
def test_fields_lists_required_fields(capsys):
    rc = main(["--template", TEMPLATE, "--fields"])
    assert rc == 0
    out = capsys.readouterr().out
    for f in FIELDS:
        assert f in out


# ---------------------------------------------------------------- 엑셀 채우기
def test_excel_fill_generates_documents(tmp_path):
    data = _xlsx(tmp_path / "d.xlsx",
                 [["R26BK00000001", "관급자재 구매", "일반경쟁", "12000000", "2026-08-01 10:00"]])
    out = tmp_path / "out"
    rc = main(["--template", TEMPLATE, "--data", data, "--out", str(out),
               "--pattern", "공고-{{입찰공고번호}}"])
    assert rc == 0
    assert _outputs(out) == ["공고-R26BK00000001.hwpx"]
    with zipfile.ZipFile(out / "공고-R26BK00000001.hwpx") as zf:
        assert zf.infolist()[0].filename == "mimetype"


def test_excel_missing_data_errors():
    # --data 없이 --source excel(기본) → argparse error → SystemExit.
    with pytest.raises(SystemExit):
        main(["--template", TEMPLATE])


# ------------------------------------------------------- 프로파일 매핑(엑셀 소스)
def test_profile_maps_source_keys_to_template_fields(tmp_path):
    # 소스 헤더가 영문이라도 프로파일이 한글 필드로 잇는다.
    wb = Workbook()
    ws = wb.active
    ws.append(["bidNtceNo", "presmptPrce"])
    ws.append(["R26BK00000009", "5000000"])
    data = tmp_path / "eng.xlsx"
    wb.save(data)

    profile = MappingProfile(name="p", mappings=[
        FieldMapping("입찰공고번호", ["bidNtceNo"]),
        FieldMapping("추정가격", ["presmptPrce"], transform="amount"),
    ])
    pf = tmp_path / "map.json"
    profile.save(pf)

    out = tmp_path / "out"
    rc = main(["--template", TEMPLATE, "--data", str(data), "--profile", str(pf),
               "--out", str(out), "--pattern", "p-{{입찰공고번호}}"])
    assert rc == 0
    gen = out / "p-R26BK00000009.hwpx"
    assert gen.exists()
    import zipfile as _z
    with _z.ZipFile(gen) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xml")).decode("utf-8")
    assert "5,000,000원" in blob


# --------------------------------------------------------------- 나라장터 소스
def _patch_nara(monkeypatch):
    """NaraStdDataSource._fetch 를 실 응답 픽스처로 대체(네트워크 차단)."""
    fixture = (FIXTURES / "nara_std_response.json").read_bytes()
    from hwpxfiller.data.nara import NaraStdDataSource
    monkeypatch.setattr(NaraStdDataSource, "_fetch", lambda self: fixture)


def test_nara_missing_service_key_errors(monkeypatch):
    _patch_nara(monkeypatch)
    with pytest.raises(SystemExit):
        main(["--template", TEMPLATE, "--source", "nara",
              "--bgn", "202606010000", "--end", "202606302359"])


def test_nara_source_with_profile_fills_template(tmp_path, monkeypatch, capsys):
    _patch_nara(monkeypatch)
    profile = MappingProfile(name="나라", mappings=[
        FieldMapping("입찰공고번호", ["bidNtceNo"]),
        FieldMapping("공고명", ["bidNtceNm"]),
        FieldMapping("추정가격", ["presmptPrce"], transform="amount"),
        FieldMapping("개찰일시", ["opengDate", "opengTm"], transform="datetime"),
    ])
    pf = tmp_path / "nara.json"
    profile.save(pf)
    out = tmp_path / "out"

    rc = main(["--template", TEMPLATE, "--source", "nara",
               "--service-key", "DUMMY", "--bgn", "202606010000", "--end", "202606302359",
               "--profile", str(pf), "--out", str(out), "--pattern", "n-{{입찰공고번호}}"])
    assert rc == 0
    # 픽스처는 2레코드 → 2파일.
    assert len(_outputs(out)) == 2
    gen = out / "n-R26BK01561738.hwpx"
    assert gen.exists()
    with zipfile.ZipFile(gen) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xml")).decode("utf-8")
    assert "65,454,545원" in blob
    assert "2026년 6월 15일 18:00" in blob
    # 취득 로그가 stderr 로 나온다.
    assert "[나라장터]" in capsys.readouterr().err


def test_nara_without_profile_warns(tmp_path, monkeypatch, capsys):
    _patch_nara(monkeypatch)
    out = tmp_path / "out"
    rc = main(["--template", TEMPLATE, "--source", "nara",
               "--service-key", "DUMMY", "--bgn", "202606010000", "--end", "202606302359",
               "--out", str(out), "--pattern", "x-{{bidNtceNo}}"])
    # 프로파일 없이도 실행은 되지만(영문키라 대부분 빈칸) 경고를 낸다.
    assert rc == 0
    assert "--profile 없이는" in capsys.readouterr().err
