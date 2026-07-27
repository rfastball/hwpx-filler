"""파일명 생성 테스트 — Qt 불필요(순수 로직).

``{{키}}`` 하위호환 + 날짜/연번 예약 토큰 + ``OutputNamer`` 의 충돌 접미사·배치 상태.
날짜·연번은 ``now``/``seq`` 를 주입해 결정적으로 검증한다.
"""

from __future__ import annotations

from datetime import datetime

from hwpxfiller.naming import (
    MAX_PATH_CHARS,
    OutputNamer,
    audit_output_names,
    clean_filename,
    existing_outputs,
    make_output_filename,
    pattern_field_tokens,
    pattern_uses_seq,
    plan_output_names,
)

_NOW = datetime(2026, 7, 9, 14, 5, 3)


# ------------------------------------------------------------- 하위호환/위생
def test_key_substitution_backward_compatible():
    assert make_output_filename("공고서-{{ID}}", {"ID": "A1"}) == "공고서-A1.hwpx"


def test_illegal_chars_sanitized_in_value():
    out = make_output_filename("{{name}}", {"name": "a/b:c*d"})
    assert out == "a_b_c_d.hwpx"


def test_hwpx_extension_enforced_case_insensitive():
    assert make_output_filename("x.HWPX", {}) == "x.HWPX"
    assert make_output_filename("x", {}) == "x.hwpx"


def test_missing_key_left_untouched():
    # 데이터에 없는 키 토큰은 그대로 남는다(기존 동작).
    assert make_output_filename("{{a}}-{{b}}", {"a": "1"}) == "1-{{b}}.hwpx"


def test_prefformatted_value_substituted_plainly():
    # 파일명은 서식하지 않는다 — 프로파일이 이미 서식한 값을 평문 치환.
    out = make_output_filename("공고-{{개찰일시}}", {"개찰일시": "2026년 6월 15일"})
    assert out == "공고-2026년 6월 15일.hwpx"


# ------------------------------------------------------------------- 날짜 토큰
def test_date_default_is_yyyymmdd():
    assert make_output_filename("{{date}}", {}, now=_NOW) == "20260709.hwpx"


def test_date_custom_format():
    assert make_output_filename("{{date:YYYY-MM-DD}}", {}, now=_NOW) == "2026-07-09.hwpx"


def test_date_month_vs_minute_case_sensitive():
    # MM=월(07), mm=분(05) — 대소문자 구분이 하중.
    assert make_output_filename("{{date:MM-mm}}", {}, now=_NOW) == "07-05.hwpx"


def test_date_time_components():
    assert make_output_filename("{{date:HHmmSS}}", {}, now=_NOW) == "140503.hwpx"


def test_date_slash_in_format_is_sanitized():
    assert make_output_filename("{{date:YYYY/MM}}", {}, now=_NOW) == "2026_07.hwpx"


def test_date_mixed_with_key():
    out = make_output_filename("{{date:YYYYMMDD}}-{{ID}}", {"ID": "7"}, now=_NOW)
    assert out == "20260709-7.hwpx"


# ------------------------------------------------------------------- 연번 토큰
def test_seq_unpadded():
    assert make_output_filename("{{seq}}", {}, seq=12) == "12.hwpx"


def test_seq_padded_width_from_literal():
    assert make_output_filename("{{seq:001}}", {}, seq=7) == "007.hwpx"


def test_seq_default_is_one_when_absent():
    assert make_output_filename("{{seq:00}}", {}) == "01.hwpx"


# ------------------------------------------------------------- OutputNamer 상태
def test_namer_seq_increments_per_next():
    namer = OutputNamer("doc-{{seq:001}}", now=_NOW)
    assert namer.next({}) == "doc-001.hwpx"
    assert namer.next({}) == "doc-002.hwpx"
    assert namer.next({}) == "doc-003.hwpx"


def test_namer_collision_appends_suffix():
    namer = OutputNamer("doc-{{ID}}", now=_NOW)
    assert namer.next({"ID": "A1"}) == "doc-A1.hwpx"
    assert namer.next({"ID": "A1"}) == "doc-A1_1.hwpx"
    assert namer.next({"ID": "A1"}) == "doc-A1_2.hwpx"


def test_namer_collision_does_not_clobber_explicit_suffix():
    # 명시적 _1 이 먼저 등장하면, 이후 base 충돌은 _2 로 건너뛴다.
    namer = OutputNamer("{{ID}}", now=_NOW)
    assert namer.next({"ID": "doc_1"}) == "doc_1.hwpx"
    assert namer.next({"ID": "doc"}) == "doc.hwpx"
    assert namer.next({"ID": "doc"}) == "doc_2.hwpx"


def test_namer_date_constant_across_batch():
    namer = OutputNamer("{{date:YYYYMMDD}}-{{seq}}", now=_NOW)
    a = namer.next({})
    b = namer.next({})
    assert a == "20260709-1.hwpx"
    assert b == "20260709-2.hwpx"


def test_namer_deterministic_given_order():
    recs = [{"ID": "A"}, {"ID": "A"}, {"ID": "B"}]
    n1 = OutputNamer("{{ID}}", now=_NOW)
    n2 = OutputNamer("{{ID}}", now=_NOW)
    assert [n1.next(r) for r in recs] == [n2.next(r) for r in recs]


def test_clean_filename_direct():
    assert clean_filename('a\\b/c:d') == "a_b_c_d"


# -------------------------------------------------- 디스크 충돌 검출(RC-02)
def test_plan_output_names_matches_namer_rules():
    """사전 계산이 실제 발급(OutputNamer)과 동일 규칙·순서 — 검출과 생성의 이름 일치."""
    recs = [{"ID": "A"}, {"ID": "A"}, {"ID": "B"}]
    namer = OutputNamer("{{date:YYYYMMDD}}-{{ID}}", now=_NOW)
    assert plan_output_names("{{date:YYYYMMDD}}-{{ID}}", recs, now=_NOW) == [
        namer.next(r) for r in recs
    ]


def test_existing_outputs_reports_only_disk_hits(tmp_path):
    """배치 내 유일성(_seen)과 별개로 **디스크**의 기존 파일만 보고한다."""
    (tmp_path / "doc-A.hwpx").write_text("수기 보정본", encoding="utf-8")
    names = ["doc-A.hwpx", "doc-B.hwpx"]
    assert existing_outputs(tmp_path, names) == [str(tmp_path / "doc-A.hwpx")]
    assert existing_outputs(tmp_path / "없는폴더", names) == []


# --------------------------------------------- 패턴 요구 토큰 조회(RC-20)
def test_pattern_field_tokens_excludes_reserved_and_dedupes():
    toks = pattern_field_tokens("{{공고명}}-{{date:YYYYMMDD}}-{{seq:001}}-{{공고명}}-{{ID}}")
    assert toks == ["공고명", "ID"]


def test_pattern_field_tokens_empty_for_literal_and_reserved_only():
    assert pattern_field_tokens("고정이름-{{date}}-{{seq}}") == []
    assert pattern_field_tokens("고정이름") == []


def test_pattern_uses_seq_marks_the_order_filename_link():
    """표시순서(F3)와 파일 이름의 연동 판정 — 문안이 이 값 위에 선다(거짓 경보 방지)."""
    assert pattern_uses_seq("{{공고명}}-{{seq}}") is True
    assert pattern_uses_seq("{{공고명}}-{{seq:001}}") is True
    assert pattern_uses_seq("{{공고명}}-{{date:YYYYMMDD}}") is False
    assert pattern_uses_seq("고정이름") is False


# ------------------------------------- 집합 단위 감사(보고서 C-01, 재작성 F5 판정 K)
def test_audit_names_match_the_plan_exactly():
    """감사가 계획과 한 글자라도 다르면 미리보기가 실행과 다른 이름을 말한다."""
    recs = [{"이름": "가"}, {"이름": "가"}, {"이름": "나"}]
    audit = audit_output_names("{{이름}}", recs)
    assert list(audit.names) == plan_output_names("{{이름}}", recs)


def test_audit_counts_records_that_converged_on_one_name():
    """꼬리표는 올바른 처분이지만 **몇 건이 수렴했는지**는 아무도 세지 않았다."""
    recs = [{"이름": "가"}, {"이름": "가"}, {"이름": "나"}, {"이름": "가"}]
    audit = audit_output_names("{{이름}}", recs)
    assert audit.converged == (1, 3)
    assert audit.names[1] == "가_1.hwpx" and audit.names[3] == "가_2.hwpx"


def test_empty_token_values_collapse_and_are_counted():
    """값이 빈 토큰은 이름을 무너뜨리고, 무너진 이름끼리 겹친다 — 수렴 집계가 함께 잡는다."""
    audit = audit_output_names("{{이름}}", [{"이름": ""}, {"이름": ""}])
    assert audit.converged == (1,)


def test_seq_token_keeps_names_distinct_so_nothing_converges():
    recs = [{"이름": "가"}, {"이름": "가"}]
    assert audit_output_names("{{seq:001}}-{{이름}}", recs).converged == ()


def test_audit_flags_paths_over_the_length_limit():
    """실행하면 확실히 실패하는 것을 실행해서 알게 하지 않는다.

    감사는 문자열 길이만 재므로 실제 폴더가 없어도 된다 — 임시 경로 길이에 결과가 흔들리지
    않게 고정 폴더로 잰다(환경 의존 플레이크 차단).
    """
    out = "C:/out"
    long_name = "가" * (MAX_PATH_CHARS - len(out) - len("/.hwpx"))
    audit = audit_output_names(
        "{{이름}}", [{"이름": "짧"}, {"이름": long_name}], out,
        max_path=MAX_PATH_CHARS,   # 플랫폼 무관 결정성 — 한계 자체가 이 테스트의 대상이다
    )
    assert audit.too_long == (1,) and audit.has_warning


def test_length_audit_is_silent_without_a_folder():
    """폴더를 모르면 잴 경로가 없다 — 없는 근거로 경고하지 않는다."""
    assert audit_output_names(
        "{{이름}}", [{"이름": "가" * 300}], max_path=MAX_PATH_CHARS,
    ).too_long == ()


def test_length_limit_applies_only_where_it_exists(monkeypatch):
    """휴리스틱은 그것이 참인 환경에서만 말한다(2R P2) — POSIX 에 260 한계는 없다."""
    from hwpxfiller import naming

    recs = [{"이름": "가" * 300}]
    monkeypatch.setattr(naming.os, "name", "posix")
    assert naming.default_max_path() == 0
    assert audit_output_names("{{이름}}", recs, "/out").too_long == ()
    monkeypatch.setattr(naming.os, "name", "nt")
    assert naming.default_max_path() == MAX_PATH_CHARS
    assert audit_output_names("{{이름}}", recs, "C:/out").too_long == (0,)


def test_convergence_alone_is_not_a_warning():
    """표 「문서」 열이 실이름을 이미 보여준다 — 보이는 변화 앞의 경고는 과경고다."""
    audit = audit_output_names("{{이름}}", [{"이름": "가"}, {"이름": "가"}])
    assert audit.converged and not audit.has_warning
