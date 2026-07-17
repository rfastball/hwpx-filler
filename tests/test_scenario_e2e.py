"""실사용 시나리오 end-to-end — 여러 템플릿(hwpx+txt) × 여러 자료 매칭.

Qt 불필요(헤드리스). ``tests/corpus/scenario/`` 번들 하나로 조달 담당자의 실제
워크플로를 재현한다: 한 벌의 입찰 데이터를 (1) 여러 형식의 소스에서 읽고, (2) 서로 다른
필드 집합의 템플릿들에 채우고, (3) 소스 어휘 차이를 매핑 프로파일로 흡수한다.

번들 구성(같은 조달 어휘 25필드 공유 — 입찰개시·입찰마감·개찰 모두 일자+시각으로 분해됨)::

    templates/입찰공고서.hwpx       25필드 전량(scenario 전용 저작 — real 재사용 아님)
    templates/구매요청서.hwpx       10필드 부분집합(fieldize 저작)
    text_templates/온나라기안.txt   내부 기안 — {{필드}} 평문(TextTemplateRegistry 루트)
    text_templates/게시요약.txt     공개 게시 요약 — {{필드}} 평문
    data/조달_한글.csv          한글 헤더 = 템플릿 필드(직접 매칭, 3건)
    data/조달_한글.xlsx         동일 데이터·다른 형식
    data/나라장터_응답.json      영문 코드 키(bidNtceNo…) — 매핑 필요(2건)
    data/나라장터_매핑.json      영문 키 → 한글 필드 + 금액/일시 서식 정규화

검증하는 실사용 불변식:
- **소스 형식 무관**: CSV·xlsx 가 같은 레코드를 낸다(DataSource 이음새).
- **직접 매칭 경로**: 한글 CSV → Job/RunRequest/generate_batch → 25필드 채워진 산출.
- **부분집합 템플릿**: 같은 데이터가 10필드 구매요청서를 채우고 여분 키는 조용히 무시.
- **매핑 경로**: 영문 나라장터 레코드가 프로파일로 한글 필드에 이어지고 금액/일시 서식.
- **얇은 소스 대비**: 나라장터엔 세부품명이 없어 그 누름틀은 미충족으로 남는다(CSV는 채움).
- **txt 트랙**: 같은 레코드가 두 기안 템플릿을 렌더, 누락 필드는 토큰 유지(시끄럽게).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from hwpxfiller.batch import generate_batch
from hwpxfiller.core.job import Job, RunRequest
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.core.text_render import render_record
from hwpxfiller.data import source_for_path
from hwpxfiller.data.nara import NaraStdDataSource

SCENARIO = Path(__file__).parent / "corpus" / "scenario"
TEMPLATES = SCENARIO / "templates"
TEXT_TEMPLATES = SCENARIO / "text_templates"
DATA = SCENARIO / "data"

BID_NOTICE = str(TEMPLATES / "입찰공고서.hwpx")   # 25필드(입찰개시·입찰마감·개찰 일자/시각 분리)
PURCHASE_REQ = str(TEMPLATES / "구매요청서.hwpx")  # 10필드 부분집합


# --------------------------------------------------------------------- 헬퍼
def _xml_blob(path: Path) -> str:
    """생성 HWPX 안의 모든 .xml 을 이어붙인 텍스트(주입값 검사용)."""
    with zipfile.ZipFile(path) as zf:
        return b"".join(
            zf.read(n) for n in zf.namelist() if n.endswith(".xml")
        ).decode("utf-8")


def _outputs(d: Path) -> "list[str]":
    return sorted(p.name for p in d.glob("*.hwpx"))


def _identity_profile(fields: "list[str]") -> MappingProfile:
    """한글 헤더 소스용 항등 매핑(필드 ← 동명 소스 키) — 직접 매칭 Job 의 프로파일."""
    return MappingProfile(
        name="직접매칭", mappings=[FieldMapping(f, f) for f in fields]
    )


def _nara_source():
    """네트워크 없이 나라장터 소스처럼 records() 를 내는 어댑터."""
    recs = NaraStdDataSource.parse((DATA / "나라장터_응답.json").read_bytes())

    class _Src:
        def records(self):
            return recs

        def fields(self):
            return list(recs[0]) if recs else []

    return _Src()


def _nara_profile() -> MappingProfile:
    return MappingProfile.load(DATA / "나라장터_매핑.json")


# ---------------------------------------------------- 소스 형식 무관(여러 자료)
def test_csv_and_xlsx_yield_identical_records():
    """같은 데이터의 CSV·xlsx 는 DataSource 이음새 뒤에서 동일 레코드를 낸다."""
    csv_recs = source_for_path(DATA / "조달_한글.csv").records()
    xlsx_recs = source_for_path(DATA / "조달_한글.xlsx").records()
    assert csv_recs == xlsx_recs
    assert len(csv_recs) == 3
    assert csv_recs[0]["공고명"] == "친환경 선박용 소화장비 구매"


# ------------------------------------------ 직접 매칭 경로(한글 CSV → 25필드)
def test_direct_match_batch_fills_bid_notice(tmp_path):
    """한글 CSV → Job/RunRequest(항등 매핑) → generate_batch → 건별 산출·값 주입."""
    src = source_for_path(DATA / "조달_한글.csv")
    job = Job(
        name="입찰공고 일괄",
        template_path=BID_NOTICE,
        mapping=_identity_profile(src.fields()),
        filename_pattern="입찰공고서-{{입찰공고번호}}",
    )
    req = RunRequest(job, src, selected_indices=[0, 1, 2])

    # 사전검증: 소스가 매핑이 읽는 키를 모두 제공(빠진 소스키 없음).
    assert req.source_report().missing_columns == []

    out = tmp_path / "out"
    batch = generate_batch(job.template_path, req.mapped_records(),
                           str(out), job.filename_pattern)
    assert batch.succeeded == 3
    assert _outputs(out) == [
        "입찰공고서-2026-001.hwpx",
        "입찰공고서-2026-002.hwpx",
        "입찰공고서-2026-003.hwpx",
    ]
    blob = _xml_blob(out / "입찰공고서-2026-001.hwpx")
    for v in ("해양수산부", "친환경 선박용 소화장비 구매", "선박용 소화기", "김담당"):
        assert v in blob


# ----------------------------------------- 부분집합 템플릿(같은 데이터 → 10필드)
def test_same_data_fills_subset_template_ignoring_extra_keys(tmp_path):
    """같은 CSV 레코드가 10필드 구매요청서를 채운다 — 여분 키(계약방법 등)는 조용히 무시."""
    src = source_for_path(DATA / "조달_한글.csv")
    out = tmp_path / "req"
    # 부분집합 템플릿은 직접 채우기(원본 한글 키). 템플릿에 없는 키는 unmatched 로.
    batch = generate_batch(PURCHASE_REQ, src.records(), str(out),
                           "구매요청서-{{입찰공고번호}}")
    assert batch.succeeded == 3
    res0 = batch.results[0]
    # 템플릿에 있는 필드만 주입되고, 나머지 소스 키(예: 계약방법)는 매칭 실패로 신고.
    assert "세부품명" in res0.applied
    assert "계약방법" in res0.unmatched  # 25필드 CSV엔 있으나 10필드 템플릿엔 없음
    blob = _xml_blob(out / "구매요청서-2026-001.hwpx")
    assert "선박용 소화기" in blob and "해양수산부" in blob
    assert "일반경쟁입찰" not in blob  # 계약방법은 이 템플릿이 담지 않음


# ------------------------------------------- 매핑 경로(영문 나라장터 → 한글 필드)
def test_nara_mapping_fills_bid_notice_with_formatting(tmp_path):
    """영문 코드 키 레코드가 매핑 프로파일로 한글 필드에 이어지고 금액/일시가 서식된다."""
    src = _nara_source()
    job = Job(
        name="나라장터 취득",
        template_path=BID_NOTICE,
        mapping=_nara_profile(),
        filename_pattern="공고서-{{입찰공고번호}}",
    )
    req = RunRequest(job, src, selected_indices=[0, 1])
    assert req.source_report().missing_columns == []  # 매핑이 읽는 영문 키 모두 존재

    out = tmp_path / "out"
    batch = generate_batch(job.template_path, req.mapped_records(),
                           str(out), job.filename_pattern)
    assert batch.succeeded == 2
    blob = _xml_blob(out / "공고서-R26BK00450011.hwpx")
    assert "친환경 선박용 소화장비 구매" in blob
    assert "45,000,000원" in blob                # amount 변환
    # 개찰일시가 두 누름틀(개찰일자/개찰시각)로 분해 — hwpx 에선 별도 런이라 각각 검사.
    assert "2026. 7. 22." in blob                # 개찰일자(date 기본 서식)
    assert "10:00" in blob                       # 개찰시각(date fmt=%H:%M)
    # 입찰개시·입찰마감도 일자+시각 두 누름틀로 분해 — 종전 시각 유실이 복원된다.
    assert "2026. 7. 15." in blob                # 입찰개시일자
    assert "09:00" in blob                       # 입찰개시시각(date fmt=%H:%M)
    assert "2026. 7. 21." in blob                # 입찰마감일자
    assert "17:00" in blob                       # 입찰마감시각(date fmt=%H:%M)
    assert "적격심사" in blob                     # 낙찰자결정방법


def test_thin_source_leaves_unmapped_fields_unfilled(tmp_path):
    """얇은 소스 대비: 나라장터엔 세부품명이 없어 그 누름틀은 미충족 — CSV는 채운다.

    실행 시 매핑 재확정 없음 원칙: 매핑이 방출하지 않는 필드는 output_report 가
    되살리지 않는다(잡음 재유입 방지). 얇음은 '산출 문서에 미충족 누름틀이 남음'으로
    드러난다 — 더 풍부한 CSV 소스를 선호할 실증 근거.
    """
    nara_job = Job(template_path=BID_NOTICE, mapping=_nara_profile())
    nara_req = RunRequest(nara_job, _nara_source(), [0])
    # 매핑이 방출하는 필드 집합에 세부품명은 없다(나라장터 소스에 원천 부재).
    assert "세부품명" not in nara_job.template_fields()
    assert "세부품명" not in nara_req.mapped_records()[0]

    out = tmp_path / "out"
    generate_batch(BID_NOTICE, nara_req.mapped_records(), str(out), "n-{{입찰공고번호}}")
    nara_blob = _xml_blob(next(out.glob("*.hwpx")))
    assert "선박용 소화기" not in nara_blob  # 세부품명 미충족(나라장터)

    # 반면 한글 CSV 는 세부품명을 채운다.
    csv_src = source_for_path(DATA / "조달_한글.csv")
    out2 = tmp_path / "out2"
    generate_batch(BID_NOTICE, csv_src.records(), str(out2), "c-{{입찰공고번호}}")
    csv_blob = _xml_blob(out2 / "c-2026-001.hwpx")
    assert "선박용 소화기" in csv_blob


# --------------------------------------------------- txt 트랙(같은 데이터 → 기안)
def test_text_registry_lists_scenario_drafts():
    """GUI txt 트랙이 나열하는 경로 그대로 — TextTemplateRegistry 로 두 기안이 뜬다.

    수동 QA: ``HWPXFILLER_HOME`` 을 이 시나리오 폴더로 두면 GUI txt 화면에 그대로 뜬다.
    """
    reg = TextTemplateRegistry(TEXT_TEMPLATES)
    assert reg.names() == sorted(["게시요약", "온나라기안"])
    assert "입찰방법" in reg.load("게시요약").fields()


def test_txt_templates_render_from_mapped_records():
    """매핑 적용된 나라장터 레코드로 두 txt 템플릿을 렌더 — 값 치환 + 서식 유지."""
    profile = _nara_profile()
    rec = profile.apply(_nara_source().records()[0])  # 표시형 이미 적용(WYSIWYG)

    draft = (TEXT_TEMPLATES / "온나라기안.txt").read_text(encoding="utf-8")
    text, report = render_record(draft, rec)
    assert "[입찰공고 게시 요청] 친환경 선박용 소화장비 구매" in text
    assert "나. 추정가격 : 45,000,000원" in text
    # 입찰마감이 인접 일자/시각 토큰으로 — 종전 유실된 시각(17:00)이 채워진다.
    assert "다. 입찰마감 : 2026. 7. 21. 17:00" in text
    assert "라. 개찰일시 : 2026. 7. 22. 10:00" in text
    assert report.missing_fields == []  # 매핑이 이 템플릿의 전 필드를 공급

    summary = (TEXT_TEMPLATES / "게시요약.txt").read_text(encoding="utf-8")
    stext, sreport = render_record(summary, rec)
    assert "[입찰공고] 친환경 선박용 소화장비 구매" in stext
    assert "일반경쟁 / 적격심사" in stext
    # 게시요약은 입찰방법을 참조하나 나라장터 매핑은 그 필드를 방출하지 않음 → 시끄럽게.
    assert "입찰방법" in sreport.missing_fields
    assert "{{입찰방법}}" in stext


def test_txt_template_from_korean_csv_record():
    """직접 매칭(한글 CSV) 레코드도 같은 txt 템플릿을 채운다 — 서식은 소스 원문 그대로."""
    rec = source_for_path(DATA / "조달_한글.csv").records()[2]  # 부산 CCTV 건
    summary = (TEXT_TEMPLATES / "게시요약.txt").read_text(encoding="utf-8")
    text, report = render_record(summary, rec)
    assert "항만 CCTV 통합관제 장비 구매" in text
    assert "전자입찰" in text                 # 입찰방법(CSV 직접 제공)
    assert report.missing_fields == []       # 한글 CSV 는 25필드 전량 제공
    assert "108000000" in text               # 직접 매칭 경로는 raw(서식 미적용)
