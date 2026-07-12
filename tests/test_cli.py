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
    """NaraStdDataSource._fetch 를 실 응답 픽스처로 대체(네트워크 차단).

    실 OS 자격증명 저장소 무접촉을 위해 ``DATA_GO_KR_KEY`` 환경변수도 비운다(키 해석이
    저장소로 폴백하지 않도록). 호출부는 빈 :class:`MemorySecretStore` 를 주입한다.
    """
    fixture = (FIXTURES / "nara_std_response.json").read_bytes()
    from hwpxfiller.data.nara import NaraStdDataSource
    monkeypatch.setattr(NaraStdDataSource, "_fetch", lambda self: fixture)
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)


def test_nara_missing_service_key_errors(monkeypatch):
    from hwpxfiller.data.secret_store import MemorySecretStore
    _patch_nara(monkeypatch)
    # 인라인 키·파일·환경변수·저장소 모두 비어 있으면 시끄럽게 종료.
    with pytest.raises(SystemExit):
        main(["--template", TEMPLATE, "--source", "nara",
              "--bgn", "202606010000", "--end", "202606302359"],
             secret_store=MemorySecretStore())


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


# ------------------------------------------------- 키 소스 우선순위(스펙 고정)
def _key_args(**over):
    import argparse
    ns = argparse.Namespace(service_key_file=None, service_key=None)
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


def test_service_key_precedence(tmp_path, monkeypatch):
    """우선순위: --service-key-file > DATA_GO_KR_KEY > --service-key(비권장) > 저장소.

    핵심: 1급 입력(파일·환경변수)이 비권장 인라인 플래그보다 위. 비권장 인라인은 수동
    저장된 키보다는 위(명시적 override).
    """
    import argparse

    from hwpxfiller.cli import _resolve_service_key
    from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore

    ap = argparse.ArgumentParser()
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "STORED"})
    kf = tmp_path / "key.txt"
    kf.write_text("  FILEKEY\n", encoding="utf-8")

    # 파일이 최우선(환경변수·인라인·저장소 모두 있어도).
    monkeypatch.setenv("DATA_GO_KR_KEY", "ENVKEY")
    args = _key_args(service_key_file=str(kf), service_key="INLINE")
    assert _resolve_service_key(ap, args, store) == "FILEKEY"

    # 파일 없으면 환경변수가 인라인보다 우선(스펙 핵심 수정).
    args = _key_args(service_key="INLINE")
    assert _resolve_service_key(ap, args, store) == "ENVKEY"

    # 환경변수 없으면 비권장 인라인이 저장소보다 우선.
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    args = _key_args(service_key="INLINE")
    assert _resolve_service_key(ap, args, store) == "INLINE"

    # 아무 입력 없으면 저장소 폴백.
    args = _key_args()
    assert _resolve_service_key(ap, args, store) == "STORED"

    # 저장소도 비었으면 None.
    args = _key_args()
    assert _resolve_service_key(ap, args, MemorySecretStore()) is None
