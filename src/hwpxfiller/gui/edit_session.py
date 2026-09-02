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
것을 쓴다. 차이의 원재료는 :func:`~hwpxfiller.domain.job.rules_values` 하나이고, 그것은
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

from ..domain.job import Job, rules_values

#: 편집기 section — 계약 §5.1 의 값 그대로다. 정수 단계 어휘는 F7 에서 사망했다(§10.13
#: 판정 B): patch 의 키와 화면의 탭이 같은 문자열을 써야 "같은 상태를 두 표면이 다르게
#: 부르는" 결함류가 애초에 생기지 않는다.
SECTION_TEMPLATE = "template"
SECTION_BINDING = "binding"
SECTION_FILENAME = "filename"

#: 매체별 탭 구성(계약 §3.1·§3.2) — **두 매체가 같은 세 단계**다(U6-D #978).
#:
#: 종전에 TXT 가 셋째를 갖지 않았던 것은 그 단계의 이름이 「파일 이름」이었기 때문이다:
#: TXT 작업은 파일을 만들지 않아 그 축이 없다. 그런데 그 단계가 「이름·저장」이 되면서
#: 묻는 것이 하나 더 생겼다 — **작업 이름**은 매체와 무관한 저장 게이트 술어다(모든 작업이
#: 이름을 갖는다). 없는 단계에 세우면 TXT 초안은 이름을 넣을 표면 없이 저장 차단만 받는다.
#: 갈리는 것은 그 단계 **안의 한 행**(문서 파일 이름)이고, 그 유무는 계속 매체가 정한다.
#: 계약이 넷째로 적던 「시험」은 F8 착수 실측에서 기각됐다(§10.17.1) — 이 목록이 최종형이다.
_SECTIONS_BY_MEDIA = {
    "hwpx": (SECTION_TEMPLATE, SECTION_BINDING, SECTION_FILENAME),
    "txt": (SECTION_TEMPLATE, SECTION_BINDING, SECTION_FILENAME),
}

#: 계약 §5.1 의 진입 사유 10종 — **전부** 열거한다. 지금 배선된 것만 적으면 나중에 표면이
#: 생겼을 때 사유를 새로 발명하게 되고, 발명된 어휘는 계약과 갈린다.
ENTRY_REASONS = (
    "voluntary", "library", "schema_new_field", "schema_missing_field",
    "run_failure", "output_result", "workbench_result",
    "document_browser_repair", "document_browser_new_work",
)

#: 이 슬라이스가 **실제로 세우는** 사유 — 보내는 표면이 존재하는 것들.
#:
#: ``document_browser_new_work`` 는 U2 §2.4·§4 판정 E(#349)에서 배제 표를 떠나 여기 왔다:
#: 「이 데이터로 신규 작업」(후보 줄)과 확인 필요 행 클릭이 **같은 한 흐름**의 두 입구로
#: 섰다. 유보 근거였던 F8 은 종결됐고, 선행이던 저장 시 데이터 자동등록은 #347 이 없앴다
#: (그 자동등록이 새 진입점을 전원 파괴 확인으로 끝내던 원인이다).
LIVE_ENTRY_REASONS = frozenset({
    "voluntary", "library", "run_failure", "output_result",
    "document_browser_repair", "document_browser_new_work",
})

#: 「문서 만들기」의 **마운트 데이터를 들고 서는** 진입 사유(#349 · #878).
#:
#: 이 사유로 열린 편집 세션의 데이터는 「이전 세션의 잔재」가 아니라 **그 세션이 존재하는
#: 이유**다. 그래서 두 자리가 이 목록 하나를 읽는다: ①브리지가 진입에 데이터 참조를
#: 실어 보낼지(``WebFrontend._mounted_data_handoff``) ②편집기가 템플릿 교체를 건너 그
#: 데이터를 살릴지(``EditorController._anchor_stash``). 사유로 판정하는 이유는 데이터가
#: 있는 세션이라고 다 여기 들지 않기 때문이다 — 관문에서 사람이 직접 고른 데이터는
#: 종전대로 끊긴다.
#:
#: ``document_browser_repair`` 가 든 근거(#878): 「입력이 필요한 항목」의 「수정…」은 데이터를
#: 든 화면에서 **그 데이터에 열을 붙이러** 가는 왕복이다. 인계가 없으면 편집기의 소스 어휘가
#: 저장 매핑이 참조하던 키뿐이라(§ ``profile_source_vocabulary``) 새 필드에 붙일 열이 아예
#: 없고, 사람이 같은 파일을 한 번 더 고르게 된다.
DATA_ANCHORED_ENTRY_REASONS = frozenset({
    "document_browser_new_work",
    "document_browser_repair",
})

#: 배제 **선언**(§10.13 판정 K): 조용한 무시와 선언된 배제는 다르다. 여기 사유로 진입하면
#: fail-closed 로 거절되고, 그 표면을 짓는 슬라이스가 이 표에서 자기 줄을 지운다.
DEFERRED_ENTRY_REASONS = {
    "schema_new_field": "새 데이터 열 제안 표면이 아직 없다(계약 §7)",
    "schema_missing_field": "필수 누락 제안 표면이 아직 없다(계약 §7)",
    # **영구 배제**(지도 §10.15.13 판정 E — 미배선이 아니라 설계다): 작업대는 인라인 필드
    # 연결 편집을 승계했으므로 편집기로 나가는 deep-link 를 갖지 않는다. 자기 화면 안에서
    # 겨눈다(wbMapPanel 착지). 이 줄을 지우려는 슬라이스는 그 판정을 먼저 뒤집어야 한다.
    "workbench_result": "작업대는 편집기로 나가지 않는다(판정 E — 인라인 편집 승계)",
    # (`document_browser_new_work` 줄은 #349 가 지웠다 — 이 표의 규율대로 "그 표면을 짓는
    #  슬라이스가 자기 줄을 지운다". 발신자는 후보 줄의 「이 데이터로 새 작업」과 문서 탐색
    #  확인 필요 행 둘이고, 착지는 `EditorController.new_draft_with_data` 하나다.)
}

#: 복귀 표면(계약 §5.1 `returnContext.surface`) — 진입 사유와 같은 규율로 전부 열거한다.
RETURN_SURFACES = ("data", "result", "library", "documents", "workbench")
LIVE_RETURN_SURFACES = frozenset({"data", "result", "library", "documents"})


def sections_for(media: str) -> "tuple[str, ...]":
    """이 매체의 탭 구성 — 미상 매체는 템플릿 탭 하나(고를 것을 먼저 고르게 한다).

    매체를 모른다고 HWPX 로 추측하지 않는다(§19.11-2). 두 매체의 단계 **집합**은 U6-D 에서
    같아졌지만 그 사실이 이 폴백을 지우지 않는다 — 매체가 정하는 것이 단계 안의 행(문서
    파일 이름)으로 좁아졌을 뿐, 모르는 매체에 단계를 세우면 여전히 없는 규칙을 편집시킨다.
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


#: 파일 이름 규칙을 겨누는 deep-link target(계약 §8) — 필드가 아니라 규칙 하나라 값이 닫혀 있다.
TARGET_FILENAME = "filename/filenamePattern"

#: 필드 단위 deep-link 의 접두 — ``binding/<fieldId>`` 형태(계약 §8 표).
_TARGET_BINDING_PREFIX = "binding/"


def target_or_raise(target: str) -> str:
    """deep-link target 검증 — 계약 §8 의 두 형태만, 그 외는 loud(fail-closed).

    조용한 폴백(빈 문자열로 떨어뜨리기)을 두지 않는 이유는 진입 사유와 같다: 그 폴백이 곧
    "겨눈다고 말했는데 아무 데도 겨누지 않는 진입"이고, 보낸 표면은 그 사실을 영영 모른다.
    """
    if not target or target == TARGET_FILENAME:
        return target
    if target.startswith(_TARGET_BINDING_PREFIX) and target[len(_TARGET_BINDING_PREFIX):]:
        return target
    raise ValueError(f"알 수 없는 deep-link target: {target!r}")


@dataclass(frozen=True)
class EditContext:
    """이 편집 진입의 문맥 — 계약 §5.1. **Python 소유**(재렌더·왕복을 건너 산다).

    `target`(필드 단위 deep-link, 계약 §8) — 드로어의 행별 「수정」이 싣는다(지도 §10.14.3).
    같은 축의 표면으로 함께 짓기로 했던 `runOverrides` 배지 쪽은 **기각**됐고(§10.14),
    deep-link 는 override 없이 성립한다: 이상한 값을 본 자리에서 그 필드의 탭으로 가고,
    고친 뒤 「변경 저장」 하나로 끝난다. 복귀 행 정체성도 이 축 하나에서 파생한다 —
    `return_context` 에 둘째 축을 만들지 않는다(§10.15.15 판정 B).
    """

    work: str = ""
    entry_reason: str = "voluntary"
    #: 사람이 읽는 증거 줄 {라벨: 값} — 보낸 표면이 **자기가 본 것**을 그대로 싣는다.
    #: 편집기가 다시 계산하지 않는다: 계산하면 배너가 말하는 것과 사용자가 방금 본 것이
    #: 갈릴 수 있고, 그 순간 증거는 증거이길 그만둔다.
    evidence: "dict[str, str]" = field(default_factory=dict)
    #: 복귀처 {surface, focus_target, ...} — 표면별 추가 키는 그 표면이 소유한다.
    return_context: "dict[str, object]" = field(default_factory=dict)
    #: deep-link 겨눔(계약 §8): ``""``(없음) · ``binding/<fieldId>`` · ``filename/filenamePattern``.
    target: str = ""

    def to_dict(self) -> dict:
        return {
            "work": self.work,
            "entry_reason": self.entry_reason,
            "evidence": dict(self.evidence),
            "return_context": dict(self.return_context),
            "target": self.target,
        }


def make_context(
    work: str,
    *,
    entry_reason: str = "voluntary",
    evidence: "dict | None" = None,
    return_context: "dict | None" = None,
    target: str = "",
) -> EditContext:
    """진입 문맥 조립 — 사유·복귀 표면·deep-link target 을 fail-closed 로 검증한다."""
    reason = entry_reason_or_raise(entry_reason)
    ret = dict(return_context or {})
    surface = str(ret.get("surface", ""))
    if surface and surface not in LIVE_RETURN_SURFACES:
        raise ValueError(f"알 수 없는 복귀 표면: {surface!r}")
    ev = {str(k): str(v) for k, v in (evidence or {}).items()}
    return EditContext(
        work=work, entry_reason=reason, evidence=ev, return_context=ret,
        target=target_or_raise(target),
    )


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

    계약 §5.2 의 합성 3층(`base + inheritedRunOverrides + patch`) 중 **가운데 층은 서지
    않는다** — `runOverrides` 는 기각됐다(지도 §10.14): override 로 풀리는 실패가 이 제품에
    없고(확정 실패 원인 4종은 권한·점유·공간·경로라 규칙과 무관하며, 이름 충돌은 실행 전
    계획·원자 차단으로 애초에 실패가 되지 않는다), 실패 복구를 빼고 남는 용도는 *파일에
    남지 않는 규칙으로 문서를 만드는 층*이라 재현 가능성과 검토 게이트를 동시에 깎는다.
    따라서 유효 초안은 `base + patch` 2층이 최종형이고, §13-14·15 는 금지할 상태가 없어
    **공허참**이다(불변식을 부정한 것이 아니라 그 전제를 짓지 않았다).
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
