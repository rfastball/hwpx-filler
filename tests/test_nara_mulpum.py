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

from functools import partial

from hwpxfiller.batch import OutputCollisionError, generate_batch as _generate_batch
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths

generate_batch = partial(
    _generate_batch,
    existing_outputs=existing_output_paths,
    ensure_output_dir=ensure_output_directory,
)
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.domain.fields import read_fields
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.mapping_store import load_mapping_profile

SCENARIO = Path(__file__).parent / "corpus" / "scenario"
BID_NOTICE = str(SCENARIO / "templates" / "입찰공고서.hwpx")  # 25필드(담당부서·입찰개시일자 등 포함)
PROFILE = load_mapping_profile(SCENARIO / "data" / "나라장터_매핑.json")

MULPUM = Path(__file__).parent / "corpus" / "nara_mulpum" / "mulpum.json"

# 목적별로 박제된 앵커 레코드(README 매니페스트와 일치).
EMPTY_DATE_NO = "R26BK01621756"      # 입찰개시/마감 일자·시각 전부 ""(F1)
DUP_NAME_NOS = ("R26BK01621756", "R26BK01610529")  # 기관 다른 동명 Adobe 2건(F3)


def _by_no() -> "dict[str, dict[str, str]]":
    recs = NaraStdDataSource.parse(MULPUM.read_bytes())
    return {r["bidNtceNo"]: r for r in recs}


def test_empty_date_record_fills_without_crash_and_writes_the_field_empty(tmp_path):
    """F1: 입찰일자 통째 결측 레코드 — 크래시 없이 빈 값이 그대로 주입된다.

    U6 §2.10 에서 엔진의 「빈 값 스킵」이 죽었다: 주어진 키는 전부 주입한다. 값이 없어
    비는 자리를 시끄럽게 만드는 것은 이제 스킵이 아니라 표식(`MISSING_MARKER`)이고, 그
    표식은 이 함수보다 **위**(`mapped_records`·CLI `--ack-empty`)에서 붙는다.
    """
    rec = _by_no()[EMPTY_DATE_NO]
    mapped = PROFILE.apply(rec)
    # 빈 소스 날짜는 표시형 변환에서 '' 로 degrade(크래시 아님).
    assert mapped["입찰개시일자"] == ""
    assert mapped["입찰개시시각"] == ""

    batch = generate_batch(BID_NOTICE, [mapped], str(tmp_path), "f1-{{입찰공고번호}}", engine=make_hwpx_engine())
    res = batch.results[0]
    assert res.ok and res.error == ""          # 생성 자체가 성공(무크래시)
    # 빈 날짜도 주입된다 — 누름틀 안내 문구가 산출물에 실려 나가지 않는다.
    assert {"입찰개시일자", "입찰개시시각", "개찰일자"} <= res.applied
    values = read_fields(read_hwpx_package(res.output_path))
    assert values["입찰개시일자"] == "" and values["입찰개시시각"] == ""


def test_duplicate_notice_names_yield_distinct_files_no_loss(tmp_path):
    """F3: 동명 공고 2건을 공고명 파일명으로 일괄 생성 — 덮어쓰기 없이 유일화(무손실)."""
    by_no = _by_no()
    recs = [PROFILE.apply(by_no[n]) for n in DUP_NAME_NOS]
    assert recs[0]["공고명"] == recs[1]["공고명"]  # 전제: 동명

    batch = generate_batch(BID_NOTICE, recs, str(tmp_path), "공고서-{{공고명}}", engine=make_hwpx_engine())
    assert batch.succeeded == 2
    files = sorted(p.name for p in tmp_path.glob("*.hwpx"))
    assert len(files) == 2                       # 2건 → 2파일(손실 0)
    assert any(f.endswith("_1.hwpx") for f in files)  # 동명 충돌은 _1 로 유일화

    # 같은 폴더 재실행 → 기존 파일 덮어쓰기 확정 없이는 착수 전 차단(RC-02).
    with pytest.raises(OutputCollisionError):
        generate_batch(BID_NOTICE, recs, str(tmp_path), "공고서-{{공고명}}", engine=make_hwpx_engine())
