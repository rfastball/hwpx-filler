"""실 나라장터 물품 세트(`corpus/nara_mulpum/`) 대비 회귀 — 검증된 동작 잠금.

이 세트의 첫 취득 패스에서 나온 finding F1·F3을 실 코드에 태워 **반증**(앱이
confirm-or-alarm 준수)한 뒤, 그 정상 동작이 회귀하지 않도록 고정한다. 판정 서사는
``tests/corpus/nara_mulpum/README.md`` 참조. Qt 불필요(헤드리스).

- **F1** — 입찰일자가 통째 빈 실 레코드(재입찰·수의 흐름)를 채워도 크래시하지 않고,
  빈 날짜는 엔진이 스킵해 누름틀이 산출문서에 잔존(loud)한다.
- **F3** — 기관 다른 동명 공고 2건을 공고명 기반 파일명으로 일괄 생성해도 파일이
  덮어써지지 않는다(``_1`` 유일화 → 무손실). 디스크 기존 파일과 충돌하면 착수 전 차단.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.batch import OutputCollisionError, generate_batch
from hwpxfiller.core.mapping import MappingProfile
from hwpxfiller.data.nara import NaraStdDataSource

SCENARIO = Path(__file__).parent / "corpus" / "scenario"
BID_NOTICE = str(SCENARIO / "templates" / "입찰공고서.hwpx")  # 25필드(담당부서·입찰개시일자 등 포함)
PROFILE = MappingProfile.load(SCENARIO / "data" / "나라장터_매핑.json")

MULPUM = Path(__file__).parent / "corpus" / "nara_mulpum" / "mulpum.json"

# 목적별로 박제된 앵커 레코드(README 매니페스트와 일치).
EMPTY_DATE_NO = "R26BK01621756"      # 입찰개시/마감 일자·시각 전부 ""(F1)
DUP_NAME_NOS = ("R26BK01621756", "R26BK01610529")  # 기관 다른 동명 Adobe 2건(F3)


def _by_no() -> "dict[str, dict[str, str]]":
    recs = NaraStdDataSource.parse(MULPUM.read_bytes())
    return {r["bidNtceNo"]: r for r in recs}


def test_empty_date_record_fills_without_crash_and_keeps_placeholder(tmp_path):
    """F1: 입찰일자 통째 결측 레코드 — 크래시 없이 빈 날짜는 스킵(누름틀 잔존)."""
    rec = _by_no()[EMPTY_DATE_NO]
    mapped = PROFILE.apply(rec)
    # 빈 소스 날짜는 표시형 변환에서 '' 로 degrade(크래시 아님).
    assert mapped["입찰개시일자"] == ""
    assert mapped["입찰개시시각"] == ""

    batch = generate_batch(BID_NOTICE, [mapped], str(tmp_path), "f1-{{입찰공고번호}}")
    res = batch.results[0]
    assert res.ok and res.error == ""          # 생성 자체가 성공(무크래시)
    # 빈 날짜는 엔진 active 에서 제외 → 누름틀 잔존(applied 에 없음).
    assert "입찰개시일자" not in res.applied
    assert "입찰개시시각" not in res.applied
    # 값이 있는 날짜(개찰일자)는 정상 주입 — 빈값만 골라 스킵함을 대조.
    assert "개찰일자" in res.applied


def test_duplicate_notice_names_yield_distinct_files_no_loss(tmp_path):
    """F3: 동명 공고 2건을 공고명 파일명으로 일괄 생성 — 덮어쓰기 없이 유일화(무손실)."""
    by_no = _by_no()
    recs = [PROFILE.apply(by_no[n]) for n in DUP_NAME_NOS]
    assert recs[0]["공고명"] == recs[1]["공고명"]  # 전제: 동명

    batch = generate_batch(BID_NOTICE, recs, str(tmp_path), "공고서-{{공고명}}")
    assert batch.succeeded == 2
    files = sorted(p.name for p in tmp_path.glob("*.hwpx"))
    assert len(files) == 2                       # 2건 → 2파일(손실 0)
    assert any(f.endswith("_1.hwpx") for f in files)  # 동명 충돌은 _1 로 유일화

    # 같은 폴더 재실행 → 기존 파일 덮어쓰기 확정 없이는 착수 전 차단(RC-02).
    with pytest.raises(OutputCollisionError):
        generate_batch(BID_NOTICE, recs, str(tmp_path), "공고서-{{공고명}}")
