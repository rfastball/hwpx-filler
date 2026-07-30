"""검토 요구와 승인 — 재작성 F5(지도 §10.12) 링0·링1 계약. Qt 불필요(헤드리스).

여기서 못박는 것은 셋이다: ①대상별 지문이 **무엇이** 바뀌었는지 답한다(F-06 이 P0 로
지목한 결함의 봉합) ②승인은 지문에 결속돼 **자동으로** 무효가 된다(폐기 코드 없음)
③기준선은 완주가 찍고 영속하며 승인은 세션이라 재시작이 요구를 되살린다.
"""
from __future__ import annotations

import json
import shutil

from hwpxfiller.core.job import (
    Job,
    JobRegistry,
    content_fingerprint,
    rules_fingerprints,
)
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.review_state import (
    ReviewState,
    review_gate_text,
    review_requirement,
    rules_key,
)


def _job(**over) -> Job:
    mapping = over.pop("mapping", None) or MappingProfile(
        mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="금액", source="presmptPrce", type="amount"),
        ]
    )
    job = Job(
        name=over.pop("name", "공고"),
        template_path=over.pop("template_path", "T.hwpx"),
        filename_pattern=over.pop("filename_pattern", "{{공고명}}.hwpx"),
        mapping=mapping,
    )
    for k, v in over.items():
        setattr(job, k, v)
    return job


def _reviewed(job: Job) -> Job:
    """완주한 뒤와 같은 상태 — 기준선이 현재 규칙과 일치."""
    job.reviewed_rules = rules_fingerprints(job)
    return job


# ------------------------------------------------------------------ 지문 축


def test_fingerprint_splits_axes_so_change_is_nameable():
    """blob 하나가 아니라 축별 지문 — '무엇이' 바뀌었는지 답할 수 있어야 한다."""
    job = _job()
    fp = rules_fingerprints(job)
    assert fp["template"] == "T.hwpx"
    assert fp["filename"] == "{{공고명}}.hwpx"
    assert "field:공고명:source" in fp and "field:공고명:format" in fp


def test_source_and_format_axes_are_independent():
    """표시형만 바꾸면 source 축은 그대로다(둘이 한 지문이면 위험 분류가 붕괴한다)."""
    base = rules_fingerprints(_job())
    job = _job()
    job.mapping.mappings[1].fmt = "천단위"
    now = rules_fingerprints(job)
    assert now["field:금액:source"] == base["field:금액:source"]
    assert now["field:금액:format"] != base["field:금액:format"]


def test_source_axis_separator_does_not_collapse_distinct_rules():
    """구분자가 값에 못 들어가는 문자라 'a'+'|b' 와 'a|b' 가 같은 지문이 되지 않는다."""
    a, b = _job(), _job()
    a.mapping.mappings[0].source = "가"
    a.mapping.mappings[0].const = "나"
    b.mapping.mappings[0].source = "가\x1f나"  # 실제로는 못 만드는 값이지만 계약을 못박는다
    b.mapping.mappings[0].const = ""
    assert (
        rules_fingerprints(a)["field:공고명:source"]
        != rules_fingerprints(b)["field:공고명:source"]
    )


def test_reviewed_rules_is_excluded_from_content_fingerprint():
    """완주 스탬프가 열어 둔 편집 세션에 거짓 파괴 확인을 띄우지 않는다(판정 B)."""
    job = _job()
    before = content_fingerprint(job)
    job.reviewed_rules = rules_fingerprints(job)
    assert content_fingerprint(job) == before


def test_reviewed_rules_round_trips_through_durable_json():
    job = _reviewed(_job())
    assert Job.from_dict(job.to_dict()).reviewed_rules == job.reviewed_rules


# ------------------------------------------------------------------ 요구 판정


def test_never_run_job_requires_review_with_heaviest_evidence():
    """§13-3 새 문서 작업 — 기준선이 없으면 전 축을 바뀐 것으로 본다(판정: 새 작업에
    표시형 증거만 보여주면 확인의 의미가 빈다)."""
    req = review_requirement(_job())
    assert req.required and req.first_run
    assert req.risk_class == "filename_set"  # 서열 1위(파일명 축도 처음이라 바뀐 것)


def test_completed_job_with_unchanged_rules_requires_nothing():
    """§13-2 정상 반복 실행에서 미리보기는 선택이다."""
    assert not review_requirement(_reviewed(_job())).required


def test_format_change_is_presentation_risk():
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    assert req.risk_class == "presentation"
    assert req.evidence_policy == "formatted_value"
    assert req.changed_targets == ("금액(표시형)",)
    assert not req.selection_bound  # 표시형 증거는 레코드 집합과 무관(C-02 차등화)


def test_source_change_is_semantic_risk_and_selection_bound():
    job = _reviewed(_job())
    job.mapping.mappings[1].source = "다른열"
    req = review_requirement(job)
    assert req.risk_class == "semantic_binding"
    assert req.evidence_policy == "value_scope_summary"
    assert req.selection_bound


def test_field_removal_is_a_change():
    """키의 소멸도 변경이다 — F-06 증거 표의 '의도적 미사용' 행."""
    job = _reviewed(_job())
    del job.mapping.mappings[1]
    req = review_requirement(job)
    assert req.risk_class == "semantic_binding"
    assert "금액(연결)" in req.changed_targets


def test_filename_change_outranks_semantic():
    job = _reviewed(_job())
    job.filename_pattern = "{{금액}}.hwpx"
    job.mapping.mappings[0].source = "다른열"
    req = review_requirement(job)
    assert req.risk_class == "filename_set"


def test_template_only_change_needs_no_approval():
    """판정 E — 구조 위험은 드리프트 게이트가 fail-closed 로 진다. 승인 표면을 더하면
    게이트를 우회하는 두 번째 권위가 생긴다."""
    job = _reviewed(_job())
    job.template_path = "다른.hwpx"
    req = review_requirement(job)
    assert not req.required
    assert req.structure_changed


def test_template_change_does_not_exempt_a_semantic_change():
    """서열이 면제의 근거가 되면 그건 서열이 아니라 구멍이다(구현 중 되깎기 1건).

    템플릿과 source 가 같이 바뀐 경우, 서열 1위를 template_structure 로 두고 면제하면
    의미 변경이 검토를 통과해 버린다.
    """
    job = _reviewed(_job())
    job.template_path = "다른.hwpx"
    job.mapping.mappings[1].source = "다른열"
    req = review_requirement(job)
    assert req.required and req.risk_class == "semantic_binding"
    assert req.structure_changed  # 병기는 하되 면제는 안 한다


def test_changed_targets_follow_document_order_not_alphabet():
    """사용자가 편집기에서 본 순서 그대로 — 정렬하면 지목이 낯설어진다."""
    job = _reviewed(_job())
    job.mapping.mappings[0].fmt = "x"
    job.mapping.mappings[1].fmt = "y"
    assert review_requirement(job).changed_targets == ("공고명(표시형)", "금액(표시형)")


def test_ordering_meta_does_not_trigger_review():
    """즐겨찾기·그룹·태그는 출력에 무영향 — 불변식 §13-8·§19.10-13."""
    job = _reviewed(_job())
    job.favorited_at = "2026-07-27T00:00:00"
    job.group = "가"
    job.tags = {"축": "값"}
    assert not review_requirement(job).required


# ------------------------------------------------------------------ 승인 결속


def test_approval_clears_the_requirement():
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    st = ReviewState()
    assert not st.is_approved(req, "0,1")
    assert st.approve(req, "0,1")
    assert st.is_approved(req, "0,1")


def test_approval_is_refused_when_nothing_is_required():
    """조용히 승인 상태를 세우지 않는다(확인-또는-경보)."""
    st = ReviewState()
    assert not st.approve(review_requirement(_reviewed(_job())), "0,1")
    assert not st.approved


def test_rule_change_invalidates_approval_without_any_disposal_code():
    """불변식 §13-6 — 규칙이 바뀌면 관련 approval 이 폐기된다. 폐기 코드 없이 성립한다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    st = ReviewState()
    st.approve(review_requirement(job), "0,1")
    job.mapping.mappings[1].fmt = "다른표시형"
    assert not st.is_approved(review_requirement(job), "0,1")


def test_presentation_approval_survives_a_selection_change():
    """C-02 차등화 — 선택을 넓혔다고 표시형을 다시 확인시키면 과경고다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    st = ReviewState()
    st.approve(req, "0,1")
    assert st.is_approved(req, "0,1,2")


def test_semantic_approval_dies_with_the_selection():
    """증거가 '선택분 중 몇 건이 달라지나'라 선택·순서가 바뀌면 증거 자체가 무효다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].source = "다른열"
    req = review_requirement(job)
    st = ReviewState()
    st.approve(req, "0,1")
    assert not st.is_approved(req, "1,0")  # 순서만 바뀌어도 파일 이름이 달라진다


def test_evidence_says_why_confirmation_is_asked():
    """눈검증이 잡은 자리 — 드로어 안에서는 게이트 문안이 안 보인다. 첫 실행인데 "이름이
    모두 서로 다릅니다"만 뜨면 묻지 않은 질문에 답한 꼴이다. 게이트와 **같은 문장**을
    공유해 두 표면이 같은 상태를 다르게 부르지 않게 한다."""
    from hwpxfiller.gui.review_state import build_evidence, review_reason_text

    req = review_requirement(_job())          # 새 작업
    ev = build_evidence(req, mapped=[{"공고명": "가"}], names=("가.hwpx",),
                        converged=0, too_long=0, pos=0)
    assert ev["reason"] == review_reason_text(req)
    assert "한 번도 문서를 만들지 않은" in ev["reason"]
    # 파일 이름은 footer 소유 — 증거 행에 다시 싣지 않는다(한 면에 같은 문자열 두 번 금지).
    assert ev["rows"] == []
    # 수렴 0건·경로 초과 0건이면 note 는 **빈다**(U2 §2.3). 종전엔 "이름이 모두 서로
    # 다릅니다"가 떴는데, 위 docstring 이 이미 그 문장을 "묻지 않은 질문에 답한 꼴"이라고
    # 적어 뒀다 — 이유 문장을 곁들이는 것으로 완화했던 것을 이제 자리째 비운다.
    assert ev["note"] == ""


def test_gate_text_names_what_changed():
    job = _reviewed(_job())
    job.mapping.mappings[1].source = "다른열"
    text = review_gate_text(review_requirement(job))
    assert "금액(연결)" in text and "미리보기" in text
    assert "—" not in text  # 표기 규칙 1(em dash 금지)


def test_gate_text_for_a_new_job_does_not_claim_rules_changed():
    text = review_gate_text(review_requirement(_job()))
    assert "규칙이 바뀌" not in text


def test_rule_axis_says_approve_not_confirm():
    """규칙축은 「승인」, 필드축은 「확인」 — 두 축이 한 동사를 나눠 쓰지 않는다(U2 §2.10).

    제보는 *"두 확인 트리거의 차이를 소명하라"* 였고, 두 축이 다르다는 소명은 선다.
    **소명을 요구했다는 사실이 결함**이라 어휘를 가른다: 거울은 "눌러서 **확인**해야
    생성할 수 있습니다"(필드축 ack), 드로어는 "결과 **확인** 완료"(규칙축 승인)로 같은
    동사가 두 축에 겹쳐 있었다.

    새 어휘를 짓는 것이 아니라 링1 이름을 표면으로 올리는 것이다 — 코드는 이미 `approve`·
    `PreviewApproved`(§13-4)로 그렇게 부르고 표면만 한 단어로 눌렀다.

    「검토」·「확정」이 아닌 이유는 **점유 대조**다: 「검토」는 `work_mode` 의 「온나라 기안
    검토·복사」가, 「확정」은 매핑 축이 이미 갖고 있다. 어휘는 점유를 안 세고 고르면 충돌을
    옮길 뿐이다.
    """
    text = review_gate_text(review_requirement(_job()))
    assert "승인" in text, "규칙축 게이트가 「승인」을 안 씁니다."
    assert "확인" not in text, (
        "규칙축 게이트가 필드축(거울 ack)의 동사 「확인」을 다시 씁니다 — 같은 동사가 두 축에 "
        f"겹치면 사용자가 차이를 소명받아야 합니다: {text!r}"
    )
    # 지목까지 준다(C3): 이 축이 보는 것은 거울이 못 보여 주는 **이름**이다.
    assert "이름" in text
    # 점유 대조 — 다른 축이 쓰는 동사를 빌려오지 않는다.
    assert "검토" not in text and "확정" not in text


def test_rules_key_is_stable_across_processes():
    """hash() 가 아니라 안정 해시 — 같은 규칙이면 언제나 같은 키다."""
    assert rules_key(rules_fingerprints(_job())) == rules_key(rules_fingerprints(_job()))


def test_approval_is_not_persisted_so_restart_reinstates_the_requirement():
    """판정 B — 승인만 하고 실행하지 않은 채 재시작하면 열린 게이트로 시작하지 않는다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    st = ReviewState()
    st.approve(req, "0,1")
    reloaded = Job.from_dict(job.to_dict())  # durable 왕복 = 재시작
    assert review_requirement(reloaded).required
    assert not ReviewState().is_approved(review_requirement(reloaded), "0,1")


# ------------------------------------------------------- 기준선의 durable 수명


def test_completion_stamp_writes_the_review_baseline(tmp_path):
    """완주 이벤트가 둘로 갈라지지 않는다 — 시각과 기준선이 같은 잠긴 왕복에서 찍힌다."""
    reg = JobRegistry(tmp_path / "jobs")
    job = _job()
    reg.save(job)
    assert review_requirement(reg.load("공고")).required  # 완주 전
    reg.stamp_last_run("공고", "2026-07-27T09:00:00", rules=rules_fingerprints(job))
    after = reg.load("공고")
    assert after.last_run_at == "2026-07-27T09:00:00"
    assert not review_requirement(after).required


def test_completion_stamp_records_the_rules_the_run_actually_used(tmp_path):
    """1R P1 — **디스크의 지금 규칙으로 찍으면 안 된다**.

    같은 프로세스의 에디터가 배치가 도는 사이 이 작업을 저장하면, 디스크 규칙을 찍는 순간
    한 번도 실행·확인된 적 없는 새 규칙이 검토받은 것으로 기록된다(조용한 승인 — 되돌릴 수
    없는 방향). 런의 규칙을 찍으면 요구가 **그대로 서서** 사용자가 다시 확인한다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    ran = _job()                      # 이 런이 쓴 규칙
    reg.save(ran)
    edited = _job()
    edited.filename_pattern = "{{금액}}.hwpx"
    reg.save(edited, allow_overwrite=True)   # 배치 중 착지한 에디터 저장
    reg.stamp_last_run("공고", "2026-07-27T09:00:00", rules=rules_fingerprints(ran))
    after = reg.load("공고")
    assert after.reviewed_rules["filename"] == "{{공고명}}.hwpx"   # 런이 쓴 것
    assert review_requirement(after).required, (
        "디스크의 새 규칙이 검토 없이 통과했습니다 — 조용한 승인입니다."
    )


def test_completion_stamp_without_run_context_leaves_the_baseline_alone(tmp_path):
    """무엇을 실행했는지 모르면 기준선을 세우지 않는다 — 디스크 규칙 폴백을 두면 그
    폴백이 곧 위 결함의 통로다(안전한 기본값이 없는 인자는 필수로 두는 것이 낫다)."""
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(_job())
    reg.stamp_last_run("공고", "2026-07-27T09:00:00")
    after = reg.load("공고")
    assert after.last_run_at == "2026-07-27T09:00:00"
    assert after.reviewed_rules == {} and review_requirement(after).required


def test_clone_does_not_inherit_the_review_baseline(tmp_path):
    """복사본은 아직 아무 문서도 만들지 않았다 — 한 번도 확인받지 않은 규칙이 열린
    게이트로 시작하면 안 된다(last_run_at·favorited_at 과 같은 줄)."""
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(_reviewed(_job()))
    clone = reg.load(reg.clone("공고"))
    assert clone.reviewed_rules == {}
    assert review_requirement(clone).required and review_requirement(clone).first_run


# ---------------- 리뷰 4R 조치의 영구 가드 ----------------
def test_a_field_the_filename_consumes_is_a_filename_risk():
    """4R P2 — 패턴 문자열이 그대로여도 그 패턴이 **소비하는 필드**가 바뀌면 이름 집합이
    바뀐다. 위험은 "무엇을 편집했는가"가 아니라 **무엇이 달라지는가**로 정한다.
    """
    job = _reviewed(_job(filename_pattern="{{금액}}.hwpx"))
    job.mapping.mappings[1].source = "다른열"          # 이름이 소비하는 필드의 연결 변경
    req = review_requirement(job)
    assert req.risk_class == "filename_set" and req.selection_bound


def test_a_presentation_change_on_a_filename_field_does_not_escape_selection_binding():
    """표시형 승인은 선택 결속이 아니라(판정 I) 선택을 넓혀도 살아남는다 — 그 필드가
    파일 이름을 만든다면 **새로 고른 레코드의 이름 충돌이 검토를 통과**한다."""
    job = _reviewed(_job(filename_pattern="{{금액}}.hwpx"))
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    assert req.risk_class == "filename_set"
    st = ReviewState()
    st.approve(req, "0,1")
    assert not st.is_approved(req, "0,1,2"), "선택이 넓어졌는데 승인이 살아남았습니다."


def test_a_field_the_filename_ignores_keeps_its_own_risk():
    """반대 방향 — 이름이 안 쓰는 필드까지 파일명 위험으로 올리면 증거가 엉뚱해진다."""
    job = _reviewed(_job(filename_pattern="{{공고명}}.hwpx"))
    job.mapping.mappings[1].fmt = "천단위"             # 금액은 이름에 안 쓰인다
    assert review_requirement(job).risk_class == "presentation"


# ----------------------------------- 직전 판본 before/after (재작성 F7 판정 H — F5 되깎기)
def test_before_values_render_the_same_record_with_the_previous_rules():
    """before 는 **저장해 둔 값이 아니라 이전 규칙으로 지금 행을 다시 렌더한 값**이다.

    저장된 값을 되읽으면 다른 시점의 다른 데이터가 before 로 붙는다 — 그건 증거가 아니라
    지어낸 값이다(§10.3 계열). 같은 행에 두 규칙을 적용해야 사용자가 보는 두 값이 비교
    가능해진다.
    """
    from hwpxfiller.core.job import rules_values
    from hwpxfiller.gui.review_state import previous_values

    job = _reviewed(_job())
    before_snapshot = rules_values(job)          # 판본 r1 의 규칙
    job.mapping.mappings[0].source = "다른열"     # r2 로 갈 변경
    job.previous_rules = before_snapshot
    record = {"bidNtceNm": "옛 공고", "다른열": "새 공고"}
    assert previous_values(job, ("공고명",), record) == {"공고명": "옛 공고"}
    # 표시형만 바뀐 축도 같은 규율 — 이전 표시형으로 같은 값을 다시 렌더한다.
    assert previous_values(job, ("없는필드",), record) == {}


def test_before_is_absent_not_empty_when_there_is_no_previous_revision():
    """직전 판본이 없으면 before 를 **싣지 않는다** — 빈 값으로 세우면 "이전엔 비어
    있었다"는 거짓 증거가 된다(있는 것과 없는 것은 다르다)."""
    from hwpxfiller.gui.review_state import build_evidence, previous_values

    job = _reviewed(_job())
    job.mapping.mappings[1].source = "다른열"   # 금액 = 파일 이름 밖 → 의미 연결 위험
    assert previous_values(job, ("금액",), {"다른열": "100"}) == {}   # 보관본 없음
    req = review_requirement(job)
    ev = build_evidence(req, mapped=[{"금액": "100"}], names=("x.hwpx",),
                        converged=0, too_long=0, pos=0, before={})
    assert ev["rows"] and "before" not in ev["rows"][0]


def test_before_is_absent_for_fields_the_previous_revision_did_not_have():
    """그 판본에 없던 필드도 before 가 없다 — 필드 추가는 「이전엔 이랬다」가 성립하지 않는다."""
    from hwpxfiller.core.job import rules_values
    from hwpxfiller.gui.review_state import previous_values

    job = _reviewed(_job())
    job.previous_rules = rules_values(job)
    assert previous_values(job, ("새필드",), {"아무열": "값"}) == {}


def test_evidence_carries_before_when_the_previous_revision_exists():
    """증거 행이 두 규칙의 값을 함께 말한다(F5 가 되깎기 조건으로 박제한 자리의 이행)."""
    from hwpxfiller.core.job import rules_values
    from hwpxfiller.gui.review_state import build_evidence, previous_values

    job = _reviewed(_job())
    job.previous_rules = rules_values(job)
    job.mapping.mappings[1].source = "다른열"    # 금액 = 파일 이름 밖 → 행 증거가 선다
    req = review_requirement(job)
    record = {"presmptPrce": "1000", "다른열": "2000"}
    ev = build_evidence(
        req, mapped=[{"금액": "2,000"}], names=("x.hwpx",), converged=0, too_long=0,
        pos=0, before=previous_values(job, req.changed_fields, record),
    )
    row = next(r for r in ev["rows"] if r["name"] == "금액")
    # 값은 **표시형까지 적용된** 문자열이다(사용자가 문서에서 볼 그 모양).
    assert row["before"] == "1,000원" and row["value"] == "2,000"


def test_before_omits_fields_whose_source_column_is_gone(tmp_path):
    """**없는 열은 빈 값이 아니다**(3R P2) — 값을 못 말하는 것과 비어 있었다는 것은 다르다.

    `value_for` 는 `record.get(source, "")` 라 소스 열이 사라져도 조용히 ``""`` 를 낸다.
    그대로 실으면 증거가 "이전엔 비어 있었습니다"라고 **단정**한다.
    """
    from hwpxfiller.core.job import rules_values
    from hwpxfiller.gui.review_state import previous_values

    job = _reviewed(_job())
    job.previous_rules = rules_values(job)         # 금액 ← presmptPrce
    job.mapping.mappings[1].source = "다른열"
    # 지금 데이터에 옛 소스 열이 없다 → 이전 값을 **말할 수 없다**(빈 값이 아니다).
    assert previous_values(job, ("금액",), {"다른열": "2000"}) == {}
    # 열이 있으면 그때 값을 말한다.
    assert previous_values(job, ("금액",), {"presmptPrce": "1000", "다른열": "2000"})


def test_before_keeps_fields_that_were_genuinely_unconnected():
    """소스가 **애초에 없던** 필드는 그때도 빈 값이 참이라 남긴다 — 연결 신설의 before 다."""
    from hwpxfiller.core.job import rules_values
    from hwpxfiller.gui.review_state import previous_values

    job = _reviewed(_job())
    job.mapping.mappings[1].source = ""            # 이전 판본: 미연결
    job.previous_rules = rules_values(job)
    job.mapping.mappings[1].source = "추정가격"     # 새 판본: 연결
    assert previous_values(job, ("금액",), {"추정가격": "1000"}) == {"금액": ""}


# ------------------------------------------ blank_set 위험종(U2 §2.13 — ack 폐기의 보정)
def test_blank_fields_raise_a_requirement_even_when_rules_match_the_baseline():
    """침묵 금지(§2.13) — 규칙이 기준선과 같아도 빈 값이 있으면 요구가 선다.

    승인은 규칙 지문 기반이라 한 번 완주하면 영구히 조용해진다(판정 N). 이 위험종이
    없으면 다음 데이터의 새 빈 값이 표식이 박힌 문서를 조용히 생성한다.
    """
    req = review_requirement(_reviewed(_job()), blank_fields=("담당자", "개찰장소"))
    assert req.required and req.risk_class == "blank_set"
    assert req.changed_targets == ("담당자", "개찰장소")
    assert req.evidence_policy == "blank_scope_summary"
    assert req.selection_bound is True, (
        "빈 값 집합은 선택에 딸린 사실이다 — 선택 결속이 아니면 승인이 남의 선택에 산다."
    )
    text = review_gate_text(req)
    assert "빈 값" in text and "담당자" in text and "승인" in text
    assert "규칙이 바뀌었습니다" not in text  # 데이터축이다 — 규칙축 문안은 거짓말


def test_no_blanks_and_matching_rules_stay_quiet():
    """빈 값 0 + 규칙 일치 = 요구 없음 — §13-2(반복 실행에서 미리보기는 선택) 그대로."""
    req = review_requirement(_reviewed(_job()), blank_fields=())
    assert req.required is False and req.risk_class == ""


def test_rule_risk_outranks_blank_set_but_becomes_selection_bound():
    """규칙 위험이 있으면 그쪽이 이긴다(무거운 증거) — 단 빈 값이 있으면 표시형 승인도
    **선택 결속으로 승격**된다: 빈 값 집합은 선택·데이터에 딸린 사실이라, 규칙에만 결속된
    승인이 살아남으면 새 빈 값이 조용히 통과한다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"          # 표시형 변경(presentation)
    quiet = review_requirement(job)
    assert quiet.risk_class == "presentation" and quiet.selection_bound is False
    risky = review_requirement(job, blank_fields=("금액",))
    assert risky.risk_class == "presentation" and risky.selection_bound is True


def test_template_only_change_with_blanks_still_raises_blank_set():
    """템플릿만 바뀐 경우(승인 축 아님 — 판정 E)에도 빈 값이 있으면 blank_set 이 선다.

    드리프트 게이트가 늘 함께 서는 것은 아니다(호환 재연결은 지문만 갈린다) — 그 창에서
    빈 값이 조용히 통과하면 안 된다. 구조 변경 병기는 그대로 나른다.
    """
    job = _reviewed(_job())
    job.template_path = "T2.hwpx"
    req = review_requirement(job, blank_fields=("금액",))
    assert req.risk_class == "blank_set" and req.structure_changed is True


# ------------------- 홈 이동과 검토 기준선(#348 · PR #368 P2 판정) -------------------
def test_home_move_keeps_the_link_and_costs_only_the_structure_flag(tmp_path, monkeypatch):
    """#348 이 링크를 이식 가능하게 만들어도 **검토 지문은 절대경로 그대로다** — 판정이다(#368 P2).

    지적은 "홈을 옮길 때마다 미리보기·검토가 다시 강제된다"고 읽었지만 **그 결과는 실측되지
    않는다**: 템플릿은 승인 축이 아니라(판정 E) 지문이 갈려도 ``required`` 는 서지 않고
    ``structure_changed`` 병기 1비트만 붙는다. 실제 구조 게이트(``template_path_drift``)는 경로가
    아니라 **파일을 다시 읽어** 판정하니 같은 파일의 이사에는 조용하다.

    그래서 이 판정의 대가는 병기 1비트이고, 반대쪽(지문을 상대키로)의 대가는 **조용한 승인
    통로**다: 기준선은 작업 JSON 에 실려 다니므로(#351 패키지 부트스트래핑의 동선) 남에게서 받은
    작업이 한 번도 본 적 없는 템플릿에 대해 구조 변경 병기까지 지운 채 도착한다.

    세 사실을 한 자리에서 못박는다 — 하나만 단언하면 다음 사람이 나머지를 결함으로 다시 연다.
    """
    home_a = tmp_path / "home-A"
    (home_a / "templates" / "조달").mkdir(parents=True)
    monkeypatch.setenv("HWPXFILLER_HOME", str(home_a))
    tpl = home_a / "templates" / "조달" / "공고서.hwpx"

    reg = JobRegistry(home_a / "jobs")
    job = _job(template_path=str(tpl))
    reg.save(job)
    reg.stamp_last_run("공고", "2026-07-27T09:00:00", rules=rules_fingerprints(job))
    assert not review_requirement(reg.load("공고")).required     # 완주 직후 = 조용하다

    home_b = tmp_path / "home-B"
    shutil.copytree(home_a, home_b)                              # 홈 통째 이사·수령
    monkeypatch.setenv("HWPXFILLER_HOME", str(home_b))
    moved = JobRegistry(home_b / "jobs").load("공고")

    # ① 링크는 살아 있다 — 새 홈의 실제 파일로 해석된다(#348 의 이득은 그대로).
    assert moved.template_path == str(home_b / "templates" / "조달" / "공고서.hwpx")
    assert moved.template_key == "조달/공고서.hwpx"

    # ② 게이트는 서지 않는다 — 지적이 든 "매 이사마다 재검토 강제"는 일어나지 않는다.
    req = review_requirement(moved)
    assert req.required is False and req.risk_class == ""

    # ③ 병기는 붙는다 — 기준선이 옛 절대경로 그대로라 구조 축이 갈린 사실은 남는다(fail-safe).
    assert req.structure_changed is True
    assert moved.reviewed_rules["template"] == str(tpl), (
        "읽기가 기준선을 새 경로로 재기입했습니다 — 어떤 실행도 벌지 않은 승인입니다."
    )


def test_reading_a_moved_job_does_not_rebase_the_baseline_on_disk(tmp_path, monkeypatch):
    """지적이 제시한 대안(해석할 때 기준선 재기입)을 명시로 거절한다 — 읽기는 durable 을 안 고친다.

    #348 의 「마이그레이션 없음」과 같은 줄이다: 읽는 김에 기준선을 밀면 목록 렌더 한 번이
    사용자가 요청한 적 없는 **승인**을 만든다.
    """
    home_a = tmp_path / "home-A"
    (home_a / "templates").mkdir(parents=True)
    monkeypatch.setenv("HWPXFILLER_HOME", str(home_a))
    reg = JobRegistry(home_a / "jobs")
    job = _job(template_path=str(home_a / "templates" / "공고서.hwpx"))
    reg.save(job)
    reg.stamp_last_run("공고", "2026-07-27T09:00:00", rules=rules_fingerprints(job))

    home_b = tmp_path / "home-B"
    shutil.copytree(home_a, home_b)
    monkeypatch.setenv("HWPXFILLER_HOME", str(home_b))
    path = home_b / "jobs" / "공고.job.json"
    before = path.read_bytes()

    moved_reg = JobRegistry(home_b / "jobs")
    moved_reg.load("공고")
    moved_reg.list_jobs()
    assert path.read_bytes() == before        # 바이트 한 톨 안 바뀐다
    stored = json.loads(path.read_text(encoding="utf-8"))["reviewed_rules"]["template"]
    assert stored == str(home_a / "templates" / "공고서.hwpx")
