"""데이터-우선 후보 판정(링1) — v6 계약 §18.4·§19.1 이식의 경계 테스트.

정본: docs/DATA_FIRST_INTEGRATION_MAP.md (봉합 지도) · lab 태그 prototype-v6-freeze 의
docs/core-workflow.md. 판정의 단일 출처 = compatibility_for, 후보 열거 = candidate_rows.
"""

from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.work_candidates import (
    KIND_AVAILABLE,
    KIND_EXCLUDED,
    KIND_NEEDS_ACTION,
    candidate_rows,
    compatibility_for,
)


def _hwpx_job(name: str = "입찰공고서", *mappings: FieldMapping) -> Job:
    return Job(
        name=name,
        template_path="/tmp/t.hwpx",
        mapping=MappingProfile(mappings=list(mappings)),
    )


# ------------------------------------------------------------ 판정 단일 출처
def test_available_when_all_source_keys_present():
    job = _hwpx_job(
        "공고서",
        FieldMapping("공고명", source="bidNtceNm"),
        FieldMapping("추정가격", source="presmptPrce"),
    )
    compat = compatibility_for(job, ["bidNtceNm", "presmptPrce", "여분열"])
    assert compat.kind == KIND_AVAILABLE
    assert compat.missing == ()


def test_needs_action_lists_missing_keys_in_document_order():
    job = _hwpx_job(
        "공고서",
        FieldMapping("공고명", source="bidNtceNm"),
        FieldMapping("추정가격", source="presmptPrce"),
        FieldMapping("담당자", source="ofclNm"),
    )
    compat = compatibility_for(job, ["ofclNm"])
    assert compat.kind == KIND_NEEDS_ACTION
    # 문서순(매핑 선언 순서) 보존 — 표시가 판정과 같은 순서를 쓰게 한다.
    assert compat.missing == ("bidNtceNm", "presmptPrce")


def test_blank_declaration_does_not_break_compatibility():
    """§18.4: blank 선언 필드는 소스 요구가 아니다 — malformed 잔존 source 도 무시."""
    job = _hwpx_job(
        "공고서",
        FieldMapping("공고명", source="bidNtceNm"),
        FieldMapping("비고", source="잔존소스", type="blank"),
    )
    compat = compatibility_for(job, ["bidNtceNm"])
    assert compat.kind == KIND_AVAILABLE


def test_const_mapping_without_source_requires_no_data_column():
    """상수 입력은 데이터 열을 요구하지 않는다 — 상수 공백은 RunViewModel 빈값 게이트 소관."""
    job = _hwpx_job(
        "공고서",
        FieldMapping("기관명", source="", type="const", const="조달청"),
        FieldMapping("공고명", source="bidNtceNm"),
    )
    compat = compatibility_for(job, ["bidNtceNm"])
    assert compat.kind == KIND_AVAILABLE


def test_const_mapping_with_leftover_source_follows_source_keys():
    """const 잔존 source 는 요구로 계산된다 — 판정이 source_keys 를 그대로 소비해
    사전검증(preflight)과 같은 걸음을 걷는다(#154 사전=사후 패리티). const 가 source 를
    실제로 읽지 않는다는 과요구 여부는 source_keys 소유 문제라 여기서 갈라서지 않는다."""
    job = _hwpx_job(
        "공고서",
        FieldMapping("기관명", source="잔존열", type="const", const="조달청"),
    )
    compat = compatibility_for(job, ["다른열"])
    assert compat.kind == KIND_NEEDS_ACTION
    assert compat.missing == ("잔존열",)


def test_new_data_columns_are_harmless():
    """§18.4: 작업이 사용하지 않는 새 데이터 열은 호환을 깨지 않는다."""
    job = _hwpx_job("공고서", FieldMapping("공고명", source="bidNtceNm"))
    compat = compatibility_for(job, ["bidNtceNm", "신규열A", "신규열B"])
    assert compat.kind == KIND_AVAILABLE


def test_empty_mapping_job_is_trivially_available():
    """빈 매핑 작업 = 요구 소스 0 → 자명 available(퇴화 허용, 권위 판정은 RunViewModel)."""
    compat = compatibility_for(_hwpx_job("빈작업"), ["아무열"])
    assert compat.kind == KIND_AVAILABLE


# ------------------------------------------------------------ 매체 국경 (§19.1)
def test_txt_job_is_excluded_with_media_reason():
    job = Job(name="기안", template_path="/tmp/t.txt")
    compat = compatibility_for(job, ["아무열"])
    assert compat.kind == KIND_EXCLUDED
    assert compat.reason == "media"


def test_unknown_suffix_is_fail_closed_excluded():
    """모르는 확장자를 hwpx 로 추측하지 않는다(§19.1 — v5 fallback 제거 계승)."""
    for path in ("/tmp/t.hwp", "/tmp/t", ""):
        compat = compatibility_for(Job(name="미상", template_path=path), ["아무열"])
        assert compat.kind == KIND_EXCLUDED, path
        assert compat.reason == "unsupported", path


# ------------------------------------------------------------ 후보 열거
def test_candidate_rows_drops_excluded_and_preserves_input_order():
    ok = _hwpx_job("가능", FieldMapping("공고명", source="bidNtceNm"))
    needs = _hwpx_job("확인필요", FieldMapping("담당자", source="없는열"))
    txt = Job(name="기안", template_path="/tmp/t.txt")
    rows = candidate_rows([needs, txt, ok], ["bidNtceNm"])
    assert [(j.name, c.kind) for j, c in rows] == [
        ("확인필요", KIND_NEEDS_ACTION),
        ("가능", KIND_AVAILABLE),
    ]


def test_candidate_rows_empty_jobs_yield_empty_list():
    assert candidate_rows([], ["아무열"]) == []
