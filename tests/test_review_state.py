"""검토 요구 — 재작성 F5(지도 §10.12) 링0·링1 계약. Qt 불필요(헤드리스).

여기서 못박는 것은 둘이다: ①대상별 지문이 **무엇이** 바뀌었는지 답한다(F-06 이 P0 로
지목한 결함의 봉합) ②기준선은 완주가 찍고 영속하며, 그 사이 아무도 조용히 기준선을
밀지 않는다.

**승인 축은 #957 슬라이스 ③ 에서 사망했다.** ``ReviewState``·``approval_key``·
``build_evidence``·``previous_values``·``review_gate_text`` 가 함께 사라졌으므로 그것들을
겨누던 단언은 여기 없다 — 검토는 생성을 막지 않고 :func:`review_notice_text` 의 비차단
고지로 나가며, 확인의 자리는 만들어진 문서다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from hwpxfiller.domain.job import (
    Job,
    rules_fingerprints,
)
from hwpxfiller.external.job_store import (
    JobRegistry,
    content_fingerprint,
    decode_job,
    encode_job,
    library_key_for,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.review_state import (
    review_notice_text,
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
    assert decode_job(encode_job(job)).reviewed_rules == job.reviewed_rules


# ------------------------------------------------------------------ 요구 판정


def test_never_run_job_requires_review_with_heaviest_evidence():
    """§13-3 새 문서 작업 — 기준선이 없으면 전 축을 바뀐 것으로 본다(판정: 새 작업에
    표시형 증거만 보여주면 확인의 의미가 빈다)."""
    req = review_requirement(_job())
    assert req.required and req.first_run
    assert req.risk_class == "filename_set"  # 서열 1위(파일명 축도 처음이라 바뀐 것)


def test_completed_job_with_unchanged_rules_requires_nothing():
    """§13-2 정상 반복 실행은 조용하다(#957 이후: 고지도 서지 않는다)."""
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


def test_template_only_change_raises_no_requirement():
    """판정 E — 구조 위험은 드리프트 게이트가 fail-closed 로 진다. 검토 요구를 여기 더하면
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


# ------------------------------------------------------- 규칙 지문 결속(승인 없이 성립)


def test_rule_change_changes_the_rules_key_without_any_disposal_code():
    """규칙이 바뀌면 :func:`rules_key` 가 갈린다 — 폐기 코드 없이 성립하는 무효화다.

    #957 이전에는 이 사실이 「승인 자동 폐기」(불변식 §13-6)를 지었다. 승인 축이 사라진
    뒤에도 남는 것은 그 아래의 사실 하나다: 같은 규칙이면 같은 키, 한 축만 달라져도 다른 키.
    """
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    first = review_requirement(job).rules_key
    job.mapping.mappings[1].fmt = "다른표시형"
    assert review_requirement(job).rules_key != first


def test_the_approval_axis_is_gone_from_the_repository():
    """#957 슬라이스 ③ — 승인 축의 이름이 ``src`` 어디에도 없다는 사실을 형상으로 못박는다.

    이름 하나가 조용히 돌아오면 "…승인해야 생성할 수 있습니다"라는 차단 서술도 함께 돌아오고,
    그 순간 「확인의 자리는 만들어진 문서」와 두 목소리가 된다.
    """
    from hwpxfiller.gui import review_state

    dead = (
        "ReviewState", "approval_key", "build_evidence", "previous_values",
        "review_gate_text",
    )
    for name in dead:
        assert not hasattr(review_state, name), f"승인 축이 되살아났습니다: {name}"

    # 호출 자리도 0 이어야 한다 — 이름을 괄호와 함께 찾는다(``:func:`` 서술은 역사 기록이라
    # 그대로 두고, 되살아난 **소비처**만 잡는 겨냥이다).
    src = Path(__file__).resolve().parents[1] / "src" / "hwpxfiller"
    hits = sorted({
        f"{path.relative_to(src).as_posix()}:{name}"
        for path in src.rglob("*.py")
        for name in dead
        if f"{name}(" in path.read_text(encoding="utf-8")
    })
    assert hits == [], hits


# ------------------------------------------------------------ 비차단 고지 문안(#957)
def test_a_first_run_is_not_announced_at_all():
    """첫 실행은 **고지 대상이 아니다**(사용자 판정, 간소화 라운드).

    결과 문서를 열어 확인하는 것은 첫 실행이든 백 번째든 언제나 하는 일이라, 「첫
    실행입니다」는 행동을 바꾸지 못하는 상수의 재진술이다. 동시에 이 갈래가 사라지면
    안 된다는 것도 함께 잰다: 갈래가 없으면 요구가 선 첫 실행이 일반 문안으로 새어
    "마지막 실행 이후"라는 **없는 실행**을 말하게 된다.
    """
    req = review_requirement(_job())
    assert req.required and req.first_run
    text = review_notice_text(req)
    assert text == ""
    assert "첫 실행" not in text and "마지막 실행" not in text


def test_notice_text_for_changed_rules_names_the_targets():
    job = _reviewed(_job())
    job.mapping.mappings[1].source = "다른열"
    text = review_notice_text(review_requirement(job))
    assert text.startswith("마지막 실행 이후 바뀐 규칙이 있습니다: ")
    assert "금액(연결)" in text and text.endswith("결과 문서를 열어 확인하세요.")


def test_notice_text_for_unknown_baseline_does_not_claim_a_first_run():
    job = _job()
    job.last_run_at = "2026-08-01T09:00:00"          # 실행 이력은 있는데 기준선이 없다
    text = review_notice_text(review_requirement(job))
    assert text == "마지막 실행에 쓴 규칙을 확인할 수 없습니다. 결과 문서를 열어 확인하세요."


def test_notice_text_is_empty_for_blank_set_and_for_no_requirement():
    """빈 값은 사전검증 「[경고] 빈 값 필드」가 이미 말한다 — 두 줄로 세우지 않는다."""
    blanks = review_requirement(_reviewed(_job()), blank_fields=("담당자",))
    assert blanks.risk_class == "blank_set"
    assert review_notice_text(blanks) == ""
    assert review_notice_text(review_requirement(_reviewed(_job()))) == ""


def test_notice_text_never_speaks_of_blocking_or_approval():
    """#957 — 고지는 비차단이다. 종전 게이트 문안("…승인해야 생성할 수 있습니다")의
    어휘가 한 갈래라도 남으면 사용자는 막혀 있다고 읽는다."""
    for req in (
        review_requirement(_job()),                                   # 첫 실행
        review_requirement(_reviewed(_job(filename_pattern="{{금액}}.hwpx"))),
    ):
        text = review_notice_text(req)
        for banned in ("승인", "미리보기", "생성할 수 없", "해야 생성"):
            assert banned not in text, f"고지가 차단 어휘를 씁니다: {banned!r} in {text!r}"
        assert "—" not in text  # 표기 규칙 1(em dash 금지)


def test_rules_key_is_stable_across_processes():
    """hash() 가 아니라 안정 해시 — 같은 규칙이면 언제나 같은 키다."""
    assert rules_key(rules_fingerprints(_job())) == rules_key(rules_fingerprints(_job()))


def test_requirement_survives_a_durable_round_trip():
    """판정 B — 기준선은 **완주가** 찍는다. 규칙만 고쳐 두고 재시작하면 요구가 그대로 선다
    (열린 게이트로 시작하지 않는다는 종전 판정의, 승인 축 없는 잔여분)."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"
    reloaded = decode_job(encode_job(job))  # durable 왕복 = 재시작
    assert review_requirement(reloaded).required
    assert review_requirement(reloaded).rules_key == review_requirement(job).rules_key


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


def test_a_presentation_change_on_a_filename_field_stays_selection_bound():
    """표시형은 규칙축 사실이라 선택과 무관하지만(판정 I), 그 필드가 **파일 이름을 만들면**
    이야기가 다르다 — 위험이 ``filename_set`` 으로 올라가고 선택 결속이 함께 선다."""
    job = _reviewed(_job(filename_pattern="{{금액}}.hwpx"))
    job.mapping.mappings[1].fmt = "천단위"
    req = review_requirement(job)
    assert req.risk_class == "filename_set" and req.selection_bound is True


def test_a_field_the_filename_ignores_keeps_its_own_risk():
    """반대 방향 — 이름이 안 쓰는 필드까지 파일명 위험으로 올리면 증거가 엉뚱해진다."""
    job = _reviewed(_job(filename_pattern="{{공고명}}.hwpx"))
    job.mapping.mappings[1].fmt = "천단위"             # 금액은 이름에 안 쓰인다
    assert review_requirement(job).risk_class == "presentation"


# ---- 직전 판본 before/after 증거는 #957 슬라이스 ③ 에서 사망했다 -------------------------
# 승인 드로어가 사라지며 `previous_values`·`build_evidence` 도 함께 걷혔다. 남은 원재료
# (`Job.previous_rules`·`domain.job.rules_values`)의 계약은 `tests/test_job.py` 가 진다 —
# 여기서 소비자 없는 투영을 다시 세우지 않는다.


# ------------------------------------------ blank_set 위험종(U2 §2.13 — ack 폐기의 보정)
def test_blank_fields_raise_a_requirement_even_when_rules_match_the_baseline():
    """침묵 금지(§2.13) — 규칙이 기준선과 같아도 빈 값이 있으면 요구가 선다.

    규칙축 요구는 한 번 완주하면 조용해진다(판정 N). 이 위험종이 없으면 다음 데이터의
    새 빈 값이 표식이 박힌 문서를 조용히 생성한다.
    """
    req = review_requirement(_reviewed(_job()), blank_fields=("담당자", "개찰장소"))
    assert req.required and req.risk_class == "blank_set"
    assert req.changed_targets == ("담당자", "개찰장소")
    assert req.evidence_policy == "blank_scope_summary"
    assert req.selection_bound is True, (
        "빈 값 집합은 선택에 딸린 사실이다 — 선택 결속이 아니면 요구가 남의 선택에 산다."
    )
    # 고지 문안은 여기서 침묵한다 — 사전검증의 "[경고] 빈 값 필드" 가 같은 자리에서
    # 필드 이름을 다 적으므로, 한 사실이 한 면에 두 줄로 서지 않는다(#957).
    assert review_notice_text(req) == ""


def test_no_blanks_and_matching_rules_stay_quiet():
    """빈 값 0 + 규칙 일치 = 요구 없음 — §13-2(반복 실행은 조용하다) 그대로."""
    req = review_requirement(_reviewed(_job()), blank_fields=())
    assert req.required is False and req.risk_class == ""


def test_rule_risk_outranks_blank_set_but_becomes_selection_bound():
    """규칙 위험이 있으면 그쪽이 이긴다(무거운 증거) — 단 빈 값이 있으면 표시형 요구도
    **데이터축으로 승격**된다: 빈 값 집합은 선택·데이터에 딸린 사실이라, 규칙축 사실로만
    남기면 새 빈 값이 조용히 통과한다."""
    job = _reviewed(_job())
    job.mapping.mappings[1].fmt = "천단위"          # 표시형 변경(presentation)
    quiet = review_requirement(job)
    assert quiet.risk_class == "presentation" and quiet.selection_bound is False
    risky = review_requirement(job, blank_fields=("금액",))
    assert risky.risk_class == "presentation" and risky.selection_bound is True


def test_template_only_change_with_blanks_still_raises_blank_set():
    """템플릿만 바뀐 경우(요구 축 아님 — 판정 E)에도 빈 값이 있으면 blank_set 이 선다.

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
    shutil.rmtree(home_a)                                        # 옛 자리는 사라진다(진짜 이사)
    monkeypatch.setenv("HWPXFILLER_HOME", str(home_b))
    moved = JobRegistry(home_b / "jobs").load("공고")

    # ① 링크는 살아 있다 — 새 홈의 실제 파일로 해석된다(#348 의 이득은 그대로).
    assert moved.template_path == str(home_b / "templates" / "조달" / "공고서.hwpx")
    assert library_key_for(moved.template_path) == "조달/공고서.hwpx"

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
