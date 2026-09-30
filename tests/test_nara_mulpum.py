"""실 나라장터 물품 세트(`corpus/nara_mulpum/`) 대비 회귀 — 검증된 동작 잠금.

이 세트의 첫 취득 패스에서 나온 finding F1·F3을 실 코드에 태워 **반증**(앱이
confirm-or-alarm 준수)한 뒤, 그 정상 동작이 회귀하지 않도록 고정한다. 판정 서사는
``tests/corpus/nara_mulpum/README.md`` 참조. Qt 불필요(헤드리스).

- **F1** — 입찰일자가 통째 빈 실 레코드(재입찰·수의 흐름)를 채워도 크래시하지 않고,
  빈 날짜는 미입력 표식으로 산출문서에 남는다(loud).
- **F3** — 기관 다른 동명 공고 2건을 공고명 기반 파일명으로 일괄 생성해도 파일이
  덮어써지지 않는다(``_1`` 유일화 → 무손실). 디스크 기존 파일과 충돌하면 착수 전 차단.

legacy 일괄 생성기가 #1081 PR3 에서 퇴역해 두 사실을 managed 경로(CLI 가 쓰는 창 없는
조립 :func:`~hwpxfiller.external.headless_generation.run_headless_generation`)로 다시 잰다.
"""

from __future__ import annotations

from pathlib import Path


from datetime import datetime

from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.domain.fields import read_fields
from hwpxfiller.domain.fill_ledger import template_path_drift
from hwpxfiller.domain.job import MISSING_MARKER
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.delivery_coordinator import DeliveryCompleted
from hwpxfiller.external.headless_generation import (
    HeadlessExecuted,
    HeadlessNeedsOverwrite,
    run_headless_generation,
)
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
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


def _covered_profile() -> MappingProfile:
    """시나리오 프로파일 + 템플릿에만 있는 필드의 명시적 비움 — 전건 확정된 연결.

    managed 는 확정되지 않은 활성 필드로 실행 계획을 세우지 않는다(CLI 는 같은 사실을
    구조 드리프트 하드게이트로 먼저 말한다). 이 회귀가 재는 것은 빈 날짜·동명 공고라
    나머지 필드는 비움으로 확정한다.
    """
    drift = template_path_drift(BID_NOTICE, PROFILE, engine=make_hwpx_engine())
    return MappingProfile(
        mappings=[
            *PROFILE.mappings,
            *(FieldMapping(field, type="const") for field in drift.template_uncovered),
        ]
    )


def _generate(tmp_path, records, pattern, *, n=0):
    return run_headless_generation(
        workspace=tmp_path / f"ws{n}",
        template_path=BID_NOTICE,
        mapping=_covered_profile(),
        filename_pattern=pattern,
        records=records,
        source_schema_keys=tuple(dict.fromkeys(k for r in records for k in r)),
        output_directory=str(tmp_path / "out"),
        overwrite=False,
        clock=datetime.now,
    )


def test_empty_date_record_fills_without_crash_and_marks_the_field(tmp_path):
    """F1: 입찰일자 통째 결측 레코드 — 크래시 없이 만들고 빈 자리는 표식으로 시끄럽게 남는다.

    빈 값은 조용히 비지 않는다(#957): managed 레코드 검증이 GUI 와 같은 규칙으로 미입력 표식을
    넣는다. 누름틀 안내 문구도 산출물에 실려 나가지 않는다.
    """
    rec = _by_no()[EMPTY_DATE_NO]
    mapped = PROFILE.apply(rec)
    # 빈 소스 날짜는 표시형 변환에서 '' 로 degrade(크래시 아님).
    assert mapped["입찰개시일자"] == ""
    assert mapped["입찰개시시각"] == ""

    result = _generate(tmp_path, [rec], "f1-{{입찰공고번호}}")
    assert isinstance(result, HeadlessExecuted), result
    assert isinstance(result.outcome, DeliveryCompleted), result.outcome
    (doc,) = result.outcome.delivered
    values = read_fields(read_hwpx_package(doc.absolute_path))
    assert values["입찰개시일자"] == MISSING_MARKER.format(field="입찰개시일자")
    assert values["입찰개시시각"] == MISSING_MARKER.format(field="입찰개시시각")


def test_duplicate_notice_names_yield_distinct_files_no_loss(tmp_path):
    """F3: 동명 공고 2건을 공고명 파일명으로 일괄 생성 — 덮어쓰기 없이 유일화(무손실)."""
    by_no = _by_no()
    raws = [by_no[n] for n in DUP_NAME_NOS]
    recs = [PROFILE.apply(raw) for raw in raws]
    assert recs[0]["공고명"] == recs[1]["공고명"]  # 전제: 동명

    result = _generate(tmp_path, raws, "공고서-{{공고명}}")
    assert isinstance(result, HeadlessExecuted), result
    assert isinstance(result.outcome, DeliveryCompleted), result.outcome
    files = sorted(p.name for p in (tmp_path / "out").glob("*.hwpx"))
    assert len(files) == 2                       # 2건 → 2파일(손실 0)
    assert any(f.endswith("_1.hwpx") for f in files)  # 동명 충돌은 _1 로 유일화

    # 같은 폴더 재실행 → 덮어쓰기 확정 없이는 착수 전 차단(RC-02).
    again = _generate(tmp_path, raws, "공고서-{{공고명}}", n=1)
    assert isinstance(again, HeadlessNeedsOverwrite)
    assert sorted(again.conflict_names) == files
