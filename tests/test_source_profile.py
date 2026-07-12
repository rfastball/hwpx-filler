"""소스 프로파일링 — 샘플 관측 + 잠정 타입 라벨(주장 아닌 제안, 모르면 degrade)."""

from hwpxfiller.core.source_profile import profile_fields, tentative_type


def test_samples_dedupe_and_cap():
    records = [{"a": "x"}, {"a": "x"}, {"a": "y"}, {"a": "z"}, {"a": "w"}]
    (p,) = profile_fields(records, ["a"])
    assert p.samples == ("x", "y", "z")  # 중복 제거 + 기본 3건 캡


def test_labels_come_from_source_vocabulary():
    (p,) = profile_fields(
        [{"bidNtceNo": "R26BK01561738"}], ["bidNtceNo"],
        labels={"bidNtceNo": "입찰공고번호"},
    )
    assert p.label == "입찰공고번호"


def test_tentative_type_is_suggestion_with_degrade():
    assert tentative_type(["20260601", "20260702"]) == "날짜(YYYYMMDD 추정)"
    assert tentative_type(["202606011230"]) == "일시(YYYYMMDDHHMM 추정)"
    assert tentative_type(["1,000", "12,345,678"]) == "금액(천단위 콤마 추정)"
    assert tentative_type(["12000000"]) == "정수(추정)"
    # 혼재·불명은 주장하지 않는다 — 빈 라벨(샘플만 남는다).
    assert tentative_type(["20260601", "abc"]) == ""
    assert tentative_type([]) == ""


def test_unknown_key_degrades_to_empty_profile():
    (p,) = profile_fields([{"a": "1"}], ["없는키"])
    assert p.samples == () and p.tentative_type == ""


def test_default_keys_follow_record_order():
    profiles = profile_fields([{"b": "1"}, {"a": "2", "b": ""}])
    assert [p.key for p in profiles] == ["b", "a"]
