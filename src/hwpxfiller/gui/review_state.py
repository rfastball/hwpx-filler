"""검토 요구 — 계약 §12(상태와 사건), 보고서 F-06 개정판.

재작성 F5(봉합 지도 §10.12)의 링1 신설분. **승인 축은 #957 정책 선회에서 사망했다**:
검토는 생성을 막지 않고 비차단 고지로 나가며(:func:`review_notice_text`), 확인의 자리는
만들어진 문서다. 그래서 이 모듈이 남기는 것은 「무엇이 어느 위험으로 바뀌었는가」라는
**요구의 사실** 하나이고, 그 요구를 해소하는 사건·상태는 저장소에 없다.

## 무엇이 결함이었나

v6 에서는 표시형 변경(``2026. 07. 25.`` → ``2026년 7월 25일``)과 source 변경
(``기본급`` → ``지급액``)이 **같은 미리보기 승인 하나**로 수렴했다. 대표 레코드에서 두
source 의 값이 우연히 같으면 일반 미리보기는 의미 변경을 드러내지 못한다 — 사용자는
결과를 봤지만 변경의 의미를 확인하지 못했다(보고서 P0).

## 이 모듈의 답

규칙의 지문을 **대상별로** 뜨고(:func:`~hwpxfiller.domain.job.rules_fingerprints`) 기준선과
비교해 무엇이 바뀌었는지 센 뒤, **무엇이 바뀌었는지를 지목해** 말한다. 대표 한 건이 답할
수 없는 것을 승인 불리언으로 뭉개지 않는 것이 요지였고, 그 요지는 고지 문안이 승계한다.

## 기준선은 영속 (지도 §10.12 판정 B)

기준선(``Job.reviewed_rules``)은 마지막 **완주** 런이 쓴 규칙이라 앱을 껐다 켜도 남는다 —
「정상 반복 실행은 조용하다」가 재시작을 넘어 성립하는 근거다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..domain.job import Job, rules_fingerprints
from ..naming import pattern_field_tokens

#: 승인을 요구하는 위험 축 — **무거운 순**. 여러 축이 동시에 바뀌면 앞선 것이 이긴다
#: (그 증거 정책이 나머지를 덮는다).
#:
#: 템플릿 변경은 여기 **없다**(지도 §10.12 판정 E): master 의 드리프트 게이트가 이미
#: fail-closed 라 "값 미리보기로 구조 변경을 승인"하는 F-07 경로가 없고, 승인 표면을
#: 더하면 게이트를 우회하는 두 번째 권위가 생긴다. 대신 서열에 끼우지 **않는** 것이
#: 중요하다 — 서열 1위로 두고 면제하면 템플릿과 source 가 같이 바뀐 경우 의미 변경이
#: 검토를 통과해 버린다(구멍). 구조 변경은 :attr:`ReviewRequirement.structure_changed`
#: 병기로 문안이 말하고, 검토 표면 자체는 F8 소관이다.
#:
#: ``blank_set``(U2 §2.13 — 필드축 ack 폐기의 보정)은 규칙축이 아니라 **데이터축**이다:
#: 규칙이 기준선과 같아도 이번 실행 입력에 빈 값이 있으면 선다 — 표식(`MISSING_MARKER`)이
#: 문서에 박히는 실행이라, 승인 없이는 조용히 생성되지 않는다(규칙 위험이 있으면 그쪽이
#: 이긴다 — 빈 값 집합은 어차피 승인 결속 범위(`selection_bound`)가 함께 나른다).
RISK_ORDER = ("filename_set", "semantic_binding", "presentation", "blank_set")

#: 위험별 증거 정책 — 이 위험이 어떤 종류의 사실로 설명되는지의 정본.
EVIDENCE_POLICY = {
    "filename_set": "name_set_summary",
    "semantic_binding": "value_scope_summary",
    "presentation": "formatted_value",
    "blank_set": "blank_scope_summary",
}

#: 지문 키 → 사람이 읽는 대상 이름의 접미사. 표면 문안이 ``field:급여:source`` 같은
#: 내부 키를 그대로 말하지 않게 한다.
_AXIS_LABEL = {"source": "연결", "format": "표시형"}


@dataclass(frozen=True)
class ReviewRequirement:
    """이 작업을 실행하면 사람이 결과에서 확인해야 하는 것 — 없으면 :attr:`risk_class` 가 ``""``.

    #957 이후 이 구조는 **요구**만 말하고 그 요구를 지우는 사건은 없다: 고지는 비차단이고
    확인의 자리는 만들어진 문서다.
    """

    #: ``""`` = 요구 없음. 그 외는 :data:`RISK_ORDER` 의 한 값.
    risk_class: str = ""
    #: 사람이 읽는 변경 대상 이름(문서순). 문안이 이것을 지목한다.
    changed_targets: "tuple[str, ...]" = ()
    #: 바뀐 **필드 이름**(문서순·중복 제거). 증거 행이 이것을 키로 값을 뜬다 — 표시용
    #: 라벨(`금액(연결)`)에서 필드 이름을 되파싱하면 표시 문자열이 곧 조회 키가 된다
    #: (F2 §10.8.6 규칙 ③ "표시용 정규화 값에서 행동 경로를 파생하지 않는다").
    changed_fields: "tuple[str, ...]" = ()
    #: :data:`EVIDENCE_POLICY` 의 값 — 이 위험을 설명하는 사실의 종류. ``""`` = 요구 없음.
    evidence_policy: str = ""
    #: 한 번도 완주한 적 없는 작업인가 — §13-3 「새 문서 작업」. 문안이 갈린다
    #: ("규칙이 바뀌었습니다" vs "아직 한 번도 만들어 본 적 없습니다").
    first_run: bool = False
    #: 실행 이력은 있는데 기준선이 없는가 — 이 기능 **이전에 만들어진 작업**의 자리.
    #: 요구는 선다(불확실 시 허용 전이는 확정 요구뿐)지만 문안이 갈린다: 실행한 적 있는
    #: 작업에 "아직 한 번도 만들지 않았습니다"라고 말하면 그건 거짓말이다.
    unknown_baseline: bool = False
    #: 템플릿이 기준선과 다른가 — 승인 축은 아니지만(판정 E) 병기해 문안이 말한다.
    structure_changed: bool = False
    #: 이 요구가 선 규칙의 지문 해시 — 실행 입력 정체의 규칙 성분이다.
    rules_key: str = ""
    #: 이 위험이 선택 집합·순서에 딸린 사실인가(C-02 차등화, 판정 I). ``blank_set`` 처럼
    #: 데이터축인 위험이 참이고, 규칙축만 보는 ``presentation`` 은 거짓이다.
    selection_bound: bool = False

    @property
    def required(self) -> bool:
        return bool(self.risk_class)


def rules_key(fingerprints: "dict[str, str]") -> str:
    """대상별 지문 묶음의 안정 해시 — 실행 입력 정체의 규칙 성분.

    사전 전체를 정렬 직렬화해 해시한다: 키 하나만 달라져도 값이 갈려야 하고, 같은 규칙이면
    프로세스를 넘어 같아야 한다(``hash()`` 를 쓰지 않는 이유).
    """
    blob = json.dumps(fingerprints, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _target_label(key: str) -> str:
    """지문 키 → 사람이 읽는 이름."""
    if key == "template":
        return "템플릿"
    if key == "filename":
        return "파일 이름 규칙"
    _, _, rest = key.partition("field:")
    name, _, axis = rest.rpartition(":")
    return f"{name}({_AXIS_LABEL.get(axis, axis)})"


def review_requirement(
    job: Job, *, blank_fields: "tuple[str, ...]" = ()
) -> ReviewRequirement:
    """이 작업의 현재 규칙이 기준선과 어긋나는가 — 어긋나면 무엇이·어느 위험으로.

    기준선이 비어 있으면(``{}``) 규칙이 마지막 실행과 같다고 말할 근거가 없다: §13-3
    「새 문서 작업은 결과 확인 전 실행을 차단한다」에 따라 **전 축을 바뀐 것으로 본다** —
    그래야 가장 무거운 증거가 붙는다(새 작업에 표시형 증거만 보여주는 것은 확인의 의미를
    비운다). 그 안에서 두 갈래를 **문안용으로** 구분한다: 정말 처음인가(``first_run``),
    아니면 실행 이력은 있는데 기준선이 없는가(``unknown_baseline`` — 이 기능 이전에 만들어진
    작업). 처분은 같고 말이 다르다: 실행한 적 있는 작업에 "아직 한 번도 만들지 않았습니다"
    라고 말하면 그건 거짓말이고, 거짓 문안은 경보를 싸구려로 만든다.

    ``blank_fields`` 는 **이번 실행 입력**에서 값이 빈 필드(U2 §2.13 — 필드축 ack 폐기의
    보정). 규칙이 기준선과 같아 규칙축 요구가 없어도 이것이 비어 있지 않으면 ``blank_set``
    요구가 선다 — 그대로 두면 새로 생긴 빈 값이 **표식으로 박힌 문서를 조용히 생성**한다.
    """
    now = rules_fingerprints(job)
    key = rules_key(now)
    base = job.reviewed_rules
    first_run = unknown = False
    if not base:
        changed = set(now)
        first_run = not job.last_run_at
        unknown = not first_run
    else:
        # 키의 등장·소멸도 변경이다 — 필드 추가·삭제가 여기서 잡힌다(F-06 「의도적 미사용」).
        changed = {k for k in set(now) | set(base) if now.get(k) != base.get(k)}
    if not changed:
        if blank_fields:
            # 빈 값이 문서에 표식으로 박히는 실행 — 규칙이 그대로여도 사실로 남긴다
            # (침묵 금지, §2.13). #957 이후 이것은 차단이 아니다: 표식이 문서에 박히는
            # 것 자체가 고지이고, 사전검증의 "[경고] 빈 값 필드" 가 그 자리를 진다.
            # 선택 결속 표식은 유지 — 빈 값 집합은 선택에 따라 달라지는 사실이다.
            return ReviewRequirement(
                risk_class="blank_set",
                changed_targets=tuple(blank_fields),
                changed_fields=tuple(blank_fields),
                evidence_policy=EVIDENCE_POLICY["blank_set"],
                rules_key=key,
                selection_bound=True,
            )
        return ReviewRequirement(rules_key=key)

    structure = "template" in changed
    # 파일명이 **소비하는 필드**가 바뀌면 패턴 문자열이 그대로여도 이름 집합이 바뀐다(4R P2).
    # 이걸 의미·표시형으로만 분류하면 ⓐ드로어가 수렴·경로 증거를 건너뛰고 ⓑ표시형 승인은
    # 선택 결속이 아니라(판정 I) 선택을 넓혀도 살아남아, **새로 고른 레코드가 만드는 이름
    # 충돌이 검토를 통과한다**. 위험은 "무엇을 편집했는가"가 아니라 **무엇이 달라지는가**로
    # 정한다 — 파일명 토큰 판정기는 링0 단일 출처(`pattern_field_tokens`)다.
    name_fields = set(pattern_field_tokens(job.filename_pattern))
    touches_name = any(
        k.startswith("field:") and k[len("field:"):].rpartition(":")[0] in name_fields
        for k in changed
    )
    risk = ""
    if "filename" in changed or touches_name:
        risk = "filename_set"
    elif any(k.endswith(":source") for k in changed):
        risk = "semantic_binding"
    elif any(k.endswith(":format") for k in changed):
        risk = "presentation"
    if not risk:
        # 템플릿만 바뀐 경우 — 승인 축이 아니다(판정 E). 드리프트 게이트가 진다.
        # 단 빈 값이 있으면 blank_set 은 그와 무관하게 선다(§2.13 침묵 금지) —
        # 구조 변경 병기는 그대로 나른다.
        if blank_fields:
            return ReviewRequirement(
                risk_class="blank_set",
                changed_targets=tuple(blank_fields),
                changed_fields=tuple(blank_fields),
                evidence_policy=EVIDENCE_POLICY["blank_set"],
                structure_changed=True,
                rules_key=key,
                selection_bound=True,
            )
        return ReviewRequirement(rules_key=key, structure_changed=True)

    # 문서순 = 매핑 순서. 정렬하면 사용자가 편집기에서 본 순서와 어긋난다.
    order = {k: i for i, k in enumerate(now)}
    ordered = sorted(changed, key=lambda k: order.get(k, len(order)))
    targets = tuple(_target_label(k) for k in ordered)
    fields: "dict[str, None]" = {}
    for k in ordered:
        if k.startswith("field:"):
            fields.setdefault(k[len("field:"):].rpartition(":")[0], None)
    return ReviewRequirement(
        risk_class=risk,
        changed_targets=targets,
        changed_fields=tuple(fields),
        evidence_policy=EVIDENCE_POLICY[risk],
        first_run=first_run,
        unknown_baseline=unknown,
        structure_changed=structure,
        rules_key=key,
        # 표시형은 규칙축 사실(판정 I)이되, **빈 값이 있으면 데이터축으로 승격**한다
        # (§2.13): 빈 값 집합은 선택·데이터에 딸린 사실이다.
        selection_bound=risk != "presentation" or bool(blank_fields),
    )


def review_reason_text(req: ReviewRequirement) -> str:
    """**왜** 확인을 묻는가 — 판정 N 의 세 갈래를 한 문장으로.

    변경 대상은 **다 적는다**: "규칙이 바뀌었습니다"만으로는 결과에서 무엇을 대조할지 모른 채
    지나가게 되고, 그러면 확인이 형식이 된다(빈 값 고지가 필드 이름을 다 적는 것과 같은 근거).
    """
    if req.first_run:
        return "아직 한 번도 문서를 만들지 않은 작업입니다."
    if req.unknown_baseline:
        return "마지막 실행에 쓴 규칙을 확인할 수 없습니다."
    if req.risk_class == "blank_set":
        # 규칙축이 아니라 데이터축이다(§2.13) — "규칙이 바뀌었습니다"는 여기서 거짓말이다.
        return (
            f"빈 값 필드가 표식으로 문서에 박힙니다: {', '.join(req.changed_targets)}."
        )
    return f"규칙이 바뀌었습니다: {', '.join(req.changed_targets)}."


def review_notice_text(req: ReviewRequirement) -> str:
    """검토 요구의 **비차단 고지** 문안 — 생성을 막지 않고 확인 자리를 결과 문서로 지목한다.

    #957 정책 선회의 문안 자리다: 종전 :func:`review_gate_text` 가 "…승인해야 생성할 수
    있습니다"로 차단을 선언하던 것을 대체한다. 판정은 여기서 새로 하지 않는다 —
    :func:`review_requirement` 가 낸 같은 :class:`ReviewRequirement` 를 읽을 뿐이라
    고지와 드로어가 같은 사실을 다르게 부르지 않는다.

    ``blank_set`` 은 **빈 문자열**이다: 빈 값은 이미 사전검증의 "[경고] 빈 값 필드" 가
    같은 자리에서 말하고 있어, 여기서 한 번 더 말하면 한 사실이 한 면에 두 줄로 선다.

    문형은 `docs/COPY_STYLE_GUIDE.md` §1 을 따른다 — em dash 대신 두 문장이다.
    """
    if not req.required:
        return ""
    if req.first_run:
        return "이 작업의 첫 실행입니다. 결과 문서를 열어 확인하세요."
    if req.unknown_baseline:
        return "마지막 실행에 쓴 규칙을 확인할 수 없습니다. 결과 문서를 열어 확인하세요."
    if req.risk_class == "blank_set":
        return ""
    return (
        f"마지막 실행 이후 바뀐 규칙이 있습니다: {', '.join(req.changed_targets)}. "
        "결과 문서를 열어 확인하세요."
    )
