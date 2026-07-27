"""편집 거래 — `EditContext` + patch(계약 §5·§6·§8, 불변식 §13-14·15·16).

재작성 F7 PR-A(봉합 지도 §10.13)의 링1 신설분. 이 모듈이 답하는 것은 셋이다.

## 1. 어디서 왜 들어왔고 어디로 돌아가는가 (`EditContext`)

편집기는 스스로 열리지 않는다 — 늘 **다른 표면의 문제**가 사람을 여기로 보낸다(미리보기의
이상한 값, 실패한 결과, 드리프트 경보, 라이브러리의 「편집」). 그 사유와 증거를 들고 오지
않으면 사용자는 편집기에서 "내가 왜 여기 왔더라"를 다시 재구성해야 하고, 돌아갈 자리도
잃는다. 그래서 진입은 **문맥과 함께** 일어나고 그 문맥이 배너·복귀 버튼의 원천이 된다.

## 2. 무엇이 바뀌었는가 (patch)

저장 단위는 화면이 보여주는 유효 초안 전체가 아니라 **한 section 의 patch** 다(§5.2).
이 모듈은 patch 를 따로 기록하지 않고 **진입 시점 스냅샷과의 차이로 유도**한다 — 이중
장부(모델을 고치면서 patch 도 적기)를 두면 둘이 갈리는 날 저장이 사용자가 본 것과 다른
것을 쓴다. 차이의 원재료는 :func:`~hwpxfiller.core.job.rules_values` 하나이고, 그것은
판본 정산·검토 요구가 쓰는 바로 그 값이다(판정 주체 단일화).

## 3. 나가도 되는가 (dirty)

§13-16 「한 편집 진입은 한 section patch 만 가진다」는 **전이 시점의 규율**이다: 다른
section 으로 가려면 지금 patch 를 저장하거나 버려야 한다. 그래서 이 모듈은 "무엇이
바뀌었나"(:func:`section_changes`)와 "사람이 손댄 자리가 어디인가"(:func:`dirty_sections`)를
**따로** 낸다. 둘은 다르다 — 확정하지 않은 편집은 저장되지 않지만(저장 게이트가 막는다)
버려지면 사라진다. 가드는 후자를 봐야 하고 판본·재진술은 전자를 봐야 한다.

**신규 초안은 patch 거래가 아니다**(§10.13 판정 P): 아직 작업이 아니므로 「직전 판본과의
차이」가 성립하지 않고, 세션 전체가 하나의 초안이다. 그 세션의 폐기는 종전대로 세션 폐기
확인이 지킨다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.job import Job, rules_values

#: 편집기 section — 계약 §5.1 의 값 그대로다. 정수 단계 어휘는 F7 에서 사망했다(§10.13
#: 판정 B): patch 의 키와 화면의 탭이 같은 문자열을 써야 "같은 상태를 두 표면이 다르게
#: 부르는" 결함류가 애초에 생기지 않는다.
SECTION_TEMPLATE = "template"
SECTION_BINDING = "binding"
SECTION_FILENAME = "filename"
SECTION_TEST = "test"

#: 매체별 탭 구성(계약 §3.1·§3.2) — TXT 는 파일 이름 탭을 **갖지 않는다**(HWPX 생성 속성).
#: 「시험」은 F8 소관이라 아직 어느 매체에도 없다: 빈 탭을 세워 두지 않는다(§8.2 ②).
_SECTIONS_BY_MEDIA = {
    "hwpx": (SECTION_TEMPLATE, SECTION_BINDING, SECTION_FILENAME),
    "txt": (SECTION_TEMPLATE, SECTION_BINDING),
}

#: 계약 §5.1 의 진입 사유 10종 — **전부** 열거한다. 지금 배선된 것만 적으면 나중에 표면이
#: 생겼을 때 사유를 새로 발명하게 되고, 발명된 어휘는 계약과 갈린다.
ENTRY_REASONS = (
    "voluntary", "library", "schema_new_field", "schema_missing_field",
    "preview_result", "run_failure", "output_result", "workbench_result",
    "document_browser_repair", "document_browser_new_work",
)

#: 이 슬라이스가 **실제로 세우는** 사유 — 보내는 표면이 존재하는 것들.
LIVE_ENTRY_REASONS = frozenset({
    "voluntary", "library", "preview_result", "run_failure", "output_result",
    "document_browser_repair",
})

#: 배제 **선언**(§10.13 판정 K): 조용한 무시와 선언된 배제는 다르다. 여기 사유로 진입하면
#: fail-closed 로 거절되고, 그 표면을 짓는 슬라이스가 이 표에서 자기 줄을 지운다.
DEFERRED_ENTRY_REASONS = {
    "schema_new_field": "새 데이터 열 제안 표면이 아직 없다(계약 §7)",
    "schema_missing_field": "필수 누락 제안 표면이 아직 없다(계약 §7)",
    "workbench_result": "TXT 검토·복사 작업대는 F6 소관",
    "document_browser_new_work": "신규 작업 분기(identityDecision)는 F8 소관",
}

#: 복귀 표면(계약 §5.1 `returnContext.surface`) — 진입 사유와 같은 규율로 전부 열거한다.
RETURN_SURFACES = ("data", "preview", "result", "library", "documents", "workbench")
LIVE_RETURN_SURFACES = frozenset({"data", "preview", "result", "library", "documents"})


def sections_for(media: str) -> "tuple[str, ...]":
    """이 매체의 탭 구성 — 미상 매체는 템플릿 탭 하나(고를 것을 먼저 고르게 한다).

    매체를 모른다고 HWPX 로 추측하지 않는다(§19.11-2) — 파일 이름 탭은 HWPX 의 속성이라
    추측이 틀리면 존재하지 않는 규칙을 편집시키게 된다.
    """
    return _SECTIONS_BY_MEDIA.get(media, (SECTION_TEMPLATE,))


def entry_reason_or_raise(reason: str) -> str:
    """진입 사유 검증 — 미지·배제 사유는 loud(fail-closed).

    조용한 폴백(`voluntary` 로 떨어뜨리기)을 두지 않는 이유: 그 폴백이 곧 "배너가 아무 말도
    안 하는 진입"이고, 문맥 없는 편집기는 이 표면이 존재하는 이유 자체를 잃는다.
    """
    if reason not in ENTRY_REASONS:
        raise ValueError(f"알 수 없는 편집 진입 사유: {reason!r}")
    if reason in DEFERRED_ENTRY_REASONS:
        raise ValueError(
            f"편집 진입 사유 '{reason}' 는 아직 배선되지 않았습니다"
            f"({DEFERRED_ENTRY_REASONS[reason]})."
        )
    return reason


@dataclass(frozen=True)
class EditContext:
    """이 편집 진입의 문맥 — 계약 §5.1. **Python 소유**(재렌더·왕복을 건너 산다).

    `target`(필드 단위 deep-link)은 PR-B 자리다: 드로어의 행별 「수정」과 `runOverrides`
    배지가 같은 축의 표면이라 함께 짓는다(§10.13 사용자 확정 1행).
    """

    work: str = ""
    entry_reason: str = "voluntary"
    #: 사람이 읽는 증거 줄 {라벨: 값} — 보낸 표면이 **자기가 본 것**을 그대로 싣는다.
    #: 편집기가 다시 계산하지 않는다: 계산하면 배너가 말하는 것과 사용자가 방금 본 것이
    #: 갈릴 수 있고, 그 순간 증거는 증거이길 그만둔다.
    evidence: "dict[str, str]" = field(default_factory=dict)
    #: 복귀처 {surface, focus_target, ...} — 표면별 추가 키는 그 표면이 소유한다.
    return_context: "dict[str, object]" = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "work": self.work,
            "entry_reason": self.entry_reason,
            "evidence": dict(self.evidence),
            "return_context": dict(self.return_context),
        }


def make_context(
    work: str,
    *,
    entry_reason: str = "voluntary",
    evidence: "dict | None" = None,
    return_context: "dict | None" = None,
) -> EditContext:
    """진입 문맥 조립 — 사유·복귀 표면을 fail-closed 로 검증한다."""
    reason = entry_reason_or_raise(entry_reason)
    ret = dict(return_context or {})
    surface = str(ret.get("surface", ""))
    if surface and surface not in LIVE_RETURN_SURFACES:
        raise ValueError(f"알 수 없는 복귀 표면: {surface!r}")
    ev = {str(k): str(v) for k, v in (evidence or {}).items()}
    return EditContext(work=work, entry_reason=reason, evidence=ev, return_context=ret)


def section_changes(base: "Job | None", draft: "Job") -> "dict[str, dict]":
    """저장하면 **무엇이 달라지는가** — section 별 변경분(빈 section 은 키 자체가 없다).

    `binding` 의 값은 `{필드: {"before": {축}|None, "after": {축}|None}}` 이다. `None` 은
    그 판본에 그 필드가 **없었다/없어진다**는 뜻이고 빈 사전으로 뭉뚱그리지 않는다 — 필드
    추가·삭제와 "축이 전부 빈 필드"는 사용자에게 전혀 다른 사건이다.

    `base` 가 없으면(신규 초안) 빈 사전을 돌려준다: 비교 대상이 없는 것을 「전부 변경」으로
    부르면 초안 저장이 매번 "전 필드가 바뀝니다"라고 말하게 된다(첫 저장에 그 재진술은
    정보가 0이다).
    """
    if base is None:
        return {}
    old, new = rules_values(base), rules_values(draft)
    out: "dict[str, dict]" = {}
    if old["template"] != new["template"]:
        out[SECTION_TEMPLATE] = {"before": old["template"], "after": new["template"]}
    if old["filename"] != new["filename"]:
        out[SECTION_FILENAME] = {"before": old["filename"], "after": new["filename"]}
    fields: "dict[str, dict]" = {}
    for name in list(old["fields"]) + [n for n in new["fields"] if n not in old["fields"]]:
        before, after = old["fields"].get(name), new["fields"].get(name)
        if before != after:
            fields[name] = {"before": before, "after": after}
    if fields:
        out[SECTION_BINDING] = fields
    return out


def dirty_sections(
    base: "Job | None", draft: "Job", *, pending_binding: bool = False
) -> "tuple[str, ...]":
    """사람이 **손댄 자리** — 이탈·탭 전환 가드가 보는 값(§13-16 의 전이 규율).

    :func:`section_changes` 와 갈리는 지점이 `pending_binding` 이다: 확정하지 않은 매핑 편집은
    저장되지 않지만(저장 게이트가 막는다) **버려지면 사라진다**. 저장될 것만 세면 그 편집이
    아무 확인 없이 증발한다 — 가드는 잃을 것이 있는지를 묻지, 저장 가능한지를 묻지 않는다.
    """
    sections = set(section_changes(base, draft))
    if pending_binding:
        sections.add(SECTION_BINDING)
    order = (SECTION_TEMPLATE, SECTION_BINDING, SECTION_FILENAME)
    return tuple(s for s in order if s in sections)


@dataclass
class EditSession:
    """한 편집 진입의 거래 상태 — 계약 §5.2 `editSession`.

    `base`(진입 시점 디스크 스냅샷)만 들고 patch 는 유도한다(모듈 docstring 2절).
    `inherited_run_overrides` 자리는 PR-B 다 — 없는 것을 빈 사전으로 세워 두면 §13-15
    ("기본 저장은 상속된 override 를 포함하지 않는다")를 만족하는 척하게 된다.
    """

    context: EditContext
    base: "Job | None" = None
    section: str = SECTION_BINDING

    @property
    def is_draft(self) -> bool:
        """신규 초안인가 — patch 거래가 아니라 세션 전체가 초안인 경우(§10.13 판정 P)."""
        return self.base is None

    def changes(self, draft: "Job") -> "dict[str, dict]":
        return section_changes(self.base, draft)

    def dirty(self, draft: "Job", *, pending_binding: bool = False) -> "tuple[str, ...]":
        return dirty_sections(self.base, draft, pending_binding=pending_binding)

    def blocking_section(
        self, draft: "Job", target: str, *, pending_binding: bool = False
    ) -> str:
        """`target` 으로 이동하기 전에 처분해야 할 section(없으면 ``""``).

        초안 세션은 ``""`` 다 — 초안의 탭 이동은 한 초안 안의 이동이라 잃을 것이 없다
        (그 세션 전체의 폐기는 세션 폐기 확인이 따로 지킨다).
        """
        if self.is_draft:
            return ""
        for section in self.dirty(draft, pending_binding=pending_binding):
            if section != target:
                return section
        return ""
