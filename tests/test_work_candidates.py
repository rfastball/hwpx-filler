"""데이터-우선 후보 판정(링1) — v6 계약 §18.4·§19.1 이식의 경계 테스트.

정본: docs/archive/DATA_FIRST_INTEGRATION_MAP.md (봉합 지도) · docs/core-workflow.md (계약).
판정의 단일 출처 = compatibility_for, 후보 열거 = candidate_rows.
"""

from hwpxfiller.core.job import (
    WORK_MODE_HWPX,
    WORK_MODE_TEXT,
    WORK_MODE_UNSUPPORTED,
    Job,
)
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.work_candidates import (
    KIND_AVAILABLE,
    KIND_EXCLUDED,
    KIND_NEEDS_ACTION,
    MAIN_TOP_N,
    TIER_FAVORITE,
    TIER_RECENT,
    TIER_UNUSED,
    TAB_AVAILABLE,
    TAB_NEEDS_ACTION,
    browse_candidates,
    candidate_rows,
    compatibility_for,
    rank_available,
    suggested_work,
)


def _hwpx_job(name: str = "입찰공고서", *mappings: FieldMapping) -> Job:
    return Job(
        name=name,
        template_path="/tmp/t.hwpx",
        mapping=MappingProfile(mappings=list(mappings)),
    )


def _txt_job(name: str = "발주요청_기안", *mappings: FieldMapping) -> Job:
    return Job(
        name=name,
        template_path="/tmp/t.txt",
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


# ------------------------------------------------------ 작업 방식 국경 (§19.1, F6 합류)
def test_txt_job_is_a_candidate_judged_by_the_same_predicate():
    """TXT 는 후보다(F6) — 그리고 hwpx 와 **같은 술어**로 판정된다.

    F6 이전에는 `reason="media"` 로 배제됐다(「기안」 화면 소유). 합류 뒤 방식이 가르는
    것은 후보 자격이 아니라 실행이 어느 표면으로 가는가뿐이다(지도 §10.15 판정 B).
    """
    ok = _txt_job("기안", FieldMapping("수신", source="dept"))
    compat = compatibility_for(ok, ["dept"])
    assert compat.kind == KIND_AVAILABLE
    assert compat.mode == WORK_MODE_TEXT

    needs = _txt_job("기안2", FieldMapping("수신", source="없는열"))
    assert compatibility_for(needs, ["dept"]).kind == KIND_NEEDS_ACTION


def test_unknown_suffix_is_fail_closed_excluded():
    """모르는 확장자를 hwpx 로 추측하지 않는다(§19.1 — v5 fallback 제거 계승).

    빈 경로(미연결)도 여기서는 ``unsupported`` 다 — 「아직 방식을 정하지 않았다」와
    「지원하지 않는다」를 후보 자격 관점에서 같게 다루는 것이 fail-closed 다(연결 상태는
    다른 축이 말한다 — 지도 §10.15 판정 A).
    """
    for path in ("/tmp/t.hwp", "/tmp/t", ""):
        compat = compatibility_for(Job(name="미상", template_path=path), ["아무열"])
        assert compat.kind == KIND_EXCLUDED, path
        assert compat.reason == "unsupported", path
        assert compat.mode == WORK_MODE_UNSUPPORTED, path


def test_media_exclusion_reason_is_dead():
    """배제 사유는 ``unsupported`` 하나뿐 — 아무도 만들지 않는 값을 남기지 않는다.

    남겨 두면 그 분기에 배선을 빠뜨려도 아무 테스트가 울지 않는다(선언된 배제 ≠ 조용한 무시).
    """
    jobs = [
        Job(name="기안", template_path="/tmp/t.txt"),
        _hwpx_job("문서"),
        Job(name="미상", template_path="/tmp/t.hwp"),
    ]
    reasons = {compatibility_for(j, ["아무열"]).reason for j in jobs}
    assert "media" not in reasons


# ------------------------------------------------------------ 후보 열거
def test_candidate_rows_drops_excluded_and_preserves_input_order():
    ok = _hwpx_job("가능", FieldMapping("공고명", source="bidNtceNm"))
    needs = _hwpx_job("확인필요", FieldMapping("담당자", source="없는열"))
    unsupported = Job(name="미상", template_path="/tmp/t.hwp")
    rows = candidate_rows([needs, unsupported, ok], ["bidNtceNm"])
    assert [(j.name, c.kind) for j, c in rows] == [
        ("확인필요", KIND_NEEDS_ACTION),
        ("가능", KIND_AVAILABLE),
    ]


def test_candidate_rows_empty_jobs_yield_empty_list():
    assert candidate_rows([], ["아무열"]) == []


# ------------------------------------------------- 메인 순위·추천 (§18.5·§19.3·§18.3 개정)
def _ranked_job(name: str, *, favorited_at: str = "", last_run_at: str = "") -> Job:
    job = _hwpx_job(name, FieldMapping("공고명", source="bidNtceNm"))
    job.favorited_at = favorited_at
    job.last_run_at = last_run_at
    return job


def test_rank_orders_favorites_then_recent_then_unused():
    """§19.3 3단 계층 — 즐겨찾기(최신순) → 최근 사용(최신순) → 미사용(이름순)."""
    jobs = [
        _ranked_job("미사용ㄴ"),
        _ranked_job("최근옛", last_run_at="2026-07-01T09:00:00"),
        _ranked_job("즐겨옛", favorited_at="2026-07-01T09:00:00"),
        _ranked_job("미사용ㄱ"),
        _ranked_job("최근새", last_run_at="2026-07-20T09:00:00"),
        _ranked_job("즐겨새", favorited_at="2026-07-20T09:00:00"),
    ]
    ranked = rank_available(jobs, ["bidNtceNm"])
    assert [r.name for r in ranked] == [
        "즐겨새", "즐겨옛", "최근새", "최근옛", "미사용ㄱ", "미사용ㄴ",
    ]
    assert [r.tier for r in ranked[:2]] == [TIER_FAVORITE, TIER_FAVORITE]
    assert ranked[2].tier == TIER_RECENT and ranked[-1].tier == TIER_UNUSED


def test_favorite_wins_over_recency():
    """즐겨찾기는 사용자 우선순위 — 더 최근에 실행된 작업보다 앞선다(§19.2)."""
    jobs = [
        _ranked_job("방금실행", last_run_at="2026-07-26T09:00:00"),
        _ranked_job("즐겨찾기", favorited_at="2026-01-01T09:00:00",
                    last_run_at="2026-01-01T09:00:00"),
    ]
    assert [r.name for r in rank_available(jobs, ["bidNtceNm"])] == ["즐겨찾기", "방금실행"]


def test_rank_ties_fall_back_to_name_order():
    """같은 계층·같은 시각이면 표시 이름순(결정적 순서 — 스캔 순서에 흔들리지 않는다)."""
    jobs = [
        _ranked_job("나작업", favorited_at="2026-07-20T09:00:00"),
        _ranked_job("가작업", favorited_at="2026-07-20T09:00:00"),
    ]
    assert [r.name for r in rank_available(jobs, ["bidNtceNm"])] == ["가작업", "나작업"]


def test_rank_excludes_needs_action_but_ranks_both_modes():
    """메인 순위는 available 만(§18.5) — 확인 필요·미상 방식은 들어오지 않는다.

    **두 작업 방식은 한 순위에서 겨룬다**(§19.3: 전체 후보 정렬 → Top 5 → 그 결과를
    구획). 방식별 최소 자리 보장이 없으므로 순위 계산에 방식이 끼어들지 않는다.
    """
    jobs = [
        _hwpx_job("확인필요", FieldMapping("담당자", source="없는열")),
        Job(name="미상", template_path="/tmp/t.hwp"),
        _txt_job("기안"),
        _ranked_job("가능"),
    ]
    ranked = rank_available(jobs, ["bidNtceNm"])
    assert [r.name for r in ranked] == ["가능", "기안"]        # 둘 다 미사용 → 이름순
    assert [r.mode for r in ranked] == [WORK_MODE_HWPX, WORK_MODE_TEXT]


def test_rank_returns_full_order_without_truncating():
    """자르지 않는다 — 상위 N 절단과 「외 N건」 고지는 표면 몫(조용한 절단 금지)."""
    jobs = [_ranked_job(f"작업{i}") for i in range(MAIN_TOP_N + 3)]
    assert len(rank_available(jobs, ["bidNtceNm"])) == MAIN_TOP_N + 3


def test_suggestion_only_when_exactly_one_available_and_no_active():
    """§18.3 개정 — 추천은 자동 선택이 서 있던 자리(유일 후보)에만, 표지일 뿐 전이가 아니다."""
    one = rank_available([_ranked_job("유일")], ["bidNtceNm"])
    assert suggested_work(one, active="") == "유일"
    # 활성 작업이 있으면 추천하지 않는다(사용자가 이미 골랐다).
    assert suggested_work(one, active="유일") == ""
    assert suggested_work(one, active="다른작업") == ""
    # 2개 이상이면 1위를 밀지 않는다 — 순위는 이력의 관측이지 이 데이터의 권위가 아니다.
    two = rank_available(
        [_ranked_job("갑", favorited_at="2026-07-20T09:00:00"), _ranked_job("을")],
        ["bidNtceNm"],
    )
    assert suggested_work(two, active="") == ""
    assert suggested_work([], active="") == ""


# ------------------------------------------------- 문서 탐색 (§18.6·§19.5, 슬라이스 3)
def _browse_jobs():
    return [
        _hwpx_job("공고서", FieldMapping("공고명", source="bidNtceNm")),
        _hwpx_job("계약서", FieldMapping("공고명", source="bidNtceNm")),
        _hwpx_job("견적요청서", FieldMapping("담당자", source="없는열")),
        _txt_job("기안문"),                                      # F6 합류 — 후보다
        Job(name="미상문서", template_path="/tmp/t.hwp"),        # 방식 국경(§19.1)
    ]


def test_browse_tabs_split_by_availability_with_stable_counts():
    """탭 = 현재 데이터 실행 가능성(primary), 건수는 **검색 전** 데이터에 대한 사실이다."""
    res = browse_candidates(_browse_jobs(), ["bidNtceNm"], tab=TAB_AVAILABLE)
    assert res.tab == TAB_AVAILABLE
    assert [r["name"] for r in res.rows] == ["계약서", "공고서", "기안문"]   # 이름순
    assert res.available_count == 3 and res.needs_count == 1      # 미상 방식만 빠진다
    # 행은 방식을 싣는다 — 탭 **안**의 구획 판단은 표면이 이 값으로 한다(§19.5).
    assert [r["mode"] for r in res.rows] == [
        WORK_MODE_HWPX, WORK_MODE_HWPX, WORK_MODE_TEXT,
    ]
    needs = browse_candidates(_browse_jobs(), ["bidNtceNm"], tab=TAB_NEEDS_ACTION)
    assert [r["name"] for r in needs.rows] == ["견적요청서"]
    assert needs.rows[0]["missing"] == ["없는열"]                   # 막힌 이유 병기
    assert needs.available_count == 3                              # 탭 건수는 양쪽 다 싣는다


def test_browse_search_matches_display_name_by_jamo_only():
    """검색 대상은 표시 이름만(§18.6) — 일치는 앱 전역과 같은 자모 부분일치(core.jamo)."""
    jobs = _browse_jobs()
    res = browse_candidates(jobs, ["bidNtceNm"], tab=TAB_AVAILABLE, query="계약")
    assert [r["name"] for r in res.rows] == ["계약서"]
    assert res.available_count == 3 and res.filtered_out == 2  # 탭 숫자는 안 흔들린다
    # 자모 조각도 같은 규칙으로 걸린다(전열 검색·열 조건과 동일 어휘).
    frag = browse_candidates(jobs, ["bidNtceNm"], tab=TAB_NEEDS_ACTION, query="ㄱㅇ")
    assert [r["name"] for r in frag.rows] == ["견적요청서"]
    # 소스 키·매체·그룹은 검색 대상이 아니다.
    assert browse_candidates(jobs, ["bidNtceNm"], tab=TAB_AVAILABLE,
                             query="bidNtceNm").rows == ()


def test_browse_unknown_tab_degenerates_to_available():
    """미지 탭 값은 사용 가능으로 퇴화 — 표면 오타가 빈 화면을 만들지 않는다."""
    res = browse_candidates(_browse_jobs(), ["bidNtceNm"], tab="엉뚱")
    assert res.tab == TAB_AVAILABLE and len(res.rows) == 3
