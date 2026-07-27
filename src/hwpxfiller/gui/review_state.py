"""검토 요구와 승인 — 계약 §12(상태와 사건)·불변식 §13-2·3·4·6, 보고서 F-06 개정판.

재작성 F5(봉합 지도 §10.12)의 링1 신설분. v6 의 ``preview.required``/``approved`` 불리언
쌍은 §4 폐기 목록이라 이식하지 않고, 보고서 F-06 이 요구한 ``ReviewRequirement``
(위험 분류 + 증거 정책 + fingerprint)로 세운다.

## 무엇이 결함이었나

v6 에서는 표시형 변경(``2026. 07. 25.`` → ``2026년 7월 25일``)과 source 변경
(``기본급`` → ``지급액``)이 **같은 미리보기 승인 하나**로 수렴했다. 대표 레코드에서 두
source 의 값이 우연히 같으면 일반 미리보기는 의미 변경을 드러내지 못한다 — 사용자는
결과를 봤지만 변경의 의미를 확인하지 못하고, 승인 불리언이 **어떤 증거에 근거했는지**
추적할 수 없다(보고서 P0).

## 이 모듈의 답

규칙의 지문을 **대상별로** 뜨고(:func:`~hwpxfiller.core.job.rules_fingerprints`) 기준선과
비교해 무엇이 바뀌었는지 센 뒤, 위험 등급에 따라 **다른 증거**를 요구한다. 승인은 그
지문에 결속되므로 "무엇을 승인했는가"가 값으로 남는다.

## 기준선은 영속, 승인은 세션 (지도 §10.12 판정 B)

기준선(``Job.reviewed_rules``)은 마지막 **완주** 런이 쓴 규칙이라 앱을 껐다 켜도 남는다 —
§13-2("정상 반복 실행에서 미리보기는 선택")가 재시작을 넘어 성립하는 근거다. 반대로
승인 자체는 세션 상태다: 승인만 하고 실행하지 않은 채 재시작하면 요구가 되돌아온다
(열린 게이트로 시작하지 않는다 = fail-closed).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.job import Job, rules_fingerprints

#: 승인을 요구하는 위험 축 — **무거운 순**. 여러 축이 동시에 바뀌면 앞선 것이 이긴다
#: (그 증거 정책이 나머지를 덮는다).
#:
#: 템플릿 변경은 여기 **없다**(지도 §10.12 판정 E): master 의 드리프트 게이트가 이미
#: fail-closed 라 "값 미리보기로 구조 변경을 승인"하는 F-07 경로가 없고, 승인 표면을
#: 더하면 게이트를 우회하는 두 번째 권위가 생긴다. 대신 서열에 끼우지 **않는** 것이
#: 중요하다 — 서열 1위로 두고 면제하면 템플릿과 source 가 같이 바뀐 경우 의미 변경이
#: 검토를 통과해 버린다(구멍). 구조 변경은 :attr:`ReviewRequirement.structure_changed`
#: 병기로 문안이 말하고, 검토 표면 자체는 F8 소관이다.
RISK_ORDER = ("filename_set", "semantic_binding", "presentation")

#: 위험별 증거 정책 — 드로어가 무엇을 실을지의 단일 출처(표면이 분기를 재발명하지 않게).
EVIDENCE_POLICY = {
    "filename_set": "name_set_summary",
    "semantic_binding": "value_scope_summary",
    "presentation": "formatted_value",
}

#: 지문 키 → 사람이 읽는 대상 이름의 접미사. 표면 문안이 ``field:급여:source`` 같은
#: 내부 키를 그대로 말하지 않게 한다.
_AXIS_LABEL = {"source": "연결", "format": "표시형"}


@dataclass(frozen=True)
class ReviewRequirement:
    """이 작업을 지금 실행하기 전에 사람이 확인해야 하는 것 — 없으면 :attr:`risk_class` 가 ``""``.

    ``PreviewCreated != PreviewApproved``(불변식 §13-4)라 이 구조는 **요구**만 말한다.
    승인 여부는 세션이 :meth:`approval_key` 와 대조해 판정한다.
    """

    #: ``""`` = 요구 없음. 그 외는 :data:`RISK_ORDER` 의 한 값.
    risk_class: str = ""
    #: 사람이 읽는 변경 대상 이름(문서순). 문안·증거가 이것을 지목한다.
    changed_targets: "tuple[str, ...]" = ()
    #: :data:`EVIDENCE_POLICY` 의 값. ``""`` = 요구 없음.
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
    #: 승인이 결속되는 규칙 지문 해시.
    rules_key: str = ""
    #: 이 위험이 선택 집합·순서에 결속되는가(C-02 차등화, 판정 I).
    selection_bound: bool = False

    @property
    def required(self) -> bool:
        return bool(self.risk_class)

    def approval_key(self, selection_key: str) -> str:
        """이 요구를 해소하는 승인이 결속될 값(판정 I).

        ``presentation`` 은 규칙 지문에**만** 결속된다 — 표시형 증거는 레코드 집합과 무관해서,
        선택을 넓혔다고 「2026. 07. 25. → 2026년 7월 25일」을 다시 확인시키면 과경고다.
        ``semantic_binding``·``filename_set`` 은 증거가 "선택분 중 몇 건이 달라지나"·"이
        배치에서 몇 건이 수렴하나"라 선택·순서가 바뀌면 그 증거 자체가 무효다.
        """
        if not self.required:
            return ""
        return (
            f"{self.rules_key}|{selection_key}" if self.selection_bound else self.rules_key
        )


def rules_key(fingerprints: "dict[str, str]") -> str:
    """대상별 지문 묶음의 안정 해시 — 승인이 결속되는 값.

    사전 전체를 정렬 직렬화해 해시한다: 키 하나만 달라져도 값이 갈려야 하고(승인 자동
    무효), 같은 규칙이면 프로세스를 넘어 같아야 한다(``hash()`` 를 쓰지 않는 이유).
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


def review_requirement(job: Job) -> ReviewRequirement:
    """이 작업의 현재 규칙이 기준선과 어긋나는가 — 어긋나면 무엇이·어느 위험으로.

    기준선이 비어 있으면(``{}``) 규칙이 마지막 실행과 같다고 말할 근거가 없다: §13-3
    「새 문서 작업은 결과 확인 전 실행을 차단한다」에 따라 **전 축을 바뀐 것으로 본다** —
    그래야 가장 무거운 증거가 붙는다(새 작업에 표시형 증거만 보여주는 것은 확인의 의미를
    비운다). 그 안에서 두 갈래를 **문안용으로** 구분한다: 정말 처음인가(``first_run``),
    아니면 실행 이력은 있는데 기준선이 없는가(``unknown_baseline`` — 이 기능 이전에 만들어진
    작업). 처분은 같고 말이 다르다: 실행한 적 있는 작업에 "아직 한 번도 만들지 않았습니다"
    라고 말하면 그건 거짓말이고, 거짓 문안은 경보를 싸구려로 만든다.
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
        return ReviewRequirement(rules_key=key)

    structure = "template" in changed
    risk = ""
    if "filename" in changed:
        risk = "filename_set"
    elif any(k.endswith(":source") for k in changed):
        risk = "semantic_binding"
    elif any(k.endswith(":format") for k in changed):
        risk = "presentation"
    if not risk:
        # 템플릿만 바뀐 경우 — 승인 축이 아니다(판정 E). 드리프트 게이트가 진다.
        return ReviewRequirement(rules_key=key, structure_changed=True)

    # 문서순 = 매핑 순서. 정렬하면 사용자가 편집기에서 본 순서와 어긋난다.
    order = {k: i for i, k in enumerate(now)}
    targets = tuple(
        _target_label(k) for k in sorted(changed, key=lambda k: order.get(k, len(order)))
    )
    return ReviewRequirement(
        risk_class=risk,
        changed_targets=targets,
        evidence_policy=EVIDENCE_POLICY[risk],
        first_run=first_run,
        unknown_baseline=unknown,
        structure_changed=structure,
        rules_key=key,
        selection_bound=risk != "presentation",
    )


def review_gate_text(req: ReviewRequirement) -> str:
    """검토 요구가 게이트에 쓰는 문안 — ①무엇이 됐는가 ②다음에 뭘 하는가만
    (`docs/COPY_STYLE_GUIDE.md` §1·§2 오류 문형: 최대 2문장).

    변경 대상은 **다 적는다**: "규칙이 바뀌었습니다"만으로는 무엇을 확인하러 가는지
    모른 채 미리보기를 열게 되고, 그러면 확인이 형식이 된다(빈 값 게이트가 필드 이름을
    다 적는 것과 같은 근거).
    """
    if req.first_run:
        head = "아직 한 번도 문서를 만들지 않은 작업입니다."
    elif req.unknown_baseline:
        head = "마지막 실행에 쓴 규칙을 확인할 수 없습니다."
    else:
        head = f"규칙이 바뀌었습니다: {', '.join(req.changed_targets)}."
    return head + " 미리보기에서 결과를 확인해야 생성할 수 있습니다."


@dataclass
class ReviewState:
    """세션이 든 승인 사건 — 영속하지 않는다(판정 B).

    승인은 **키**로 든다: 규칙이 바뀌면 :func:`rules_key` 가 갈려 승인이 자동 무효가 되고,
    선택 결속 위험은 선택이 바뀔 때 같이 무효가 된다. 별도 폐기 코드를 두지 않는 것이
    핵심이다 — 불변식 §13-6(판본 변경은 관련 approval 을 폐기한다)을 **판정 주체 하나**로
    만족시키면 "폐기를 잊은 경로"가 원리적으로 생기지 않는다.
    """

    approved: "set[str]" = field(default_factory=set)

    def approve(self, req: ReviewRequirement, selection_key: str) -> bool:
        """명시 승인 사건. 요구가 없으면 **거절**한다(조용히 세우지 않는다)."""
        key = req.approval_key(selection_key)
        if not key:
            return False
        self.approved.add(key)
        return True

    def is_approved(self, req: ReviewRequirement, selection_key: str) -> bool:
        key = req.approval_key(selection_key)
        return bool(key) and key in self.approved

    def clear(self) -> None:
        """세션 경계(데이터 전환·작업 교체)에서의 초기화 — 키 결속이 이미 대부분을
        무효화하지만, 남은 키가 쌓여 메모리를 무한정 먹지 않게 한다."""
        self.approved.clear()
