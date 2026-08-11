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

규칙의 지문을 **대상별로** 뜨고(:func:`~hwpxfiller.domain.job.rules_fingerprints`) 기준선과
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

from ..domain.job import MISSING_MARKER, Job, rules_fingerprints
from ..domain.mapping import FieldMapping
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

#: 위험별 증거 정책 — 드로어가 무엇을 실을지의 단일 출처(표면이 분기를 재발명하지 않게).
EVIDENCE_POLICY = {
    "filename_set": "name_set_summary",
    "semantic_binding": "value_scope_summary",
    "presentation": "formatted_value",
    "blank_set": "blank_scope_summary",
}

#: 소스 열을 **읽어** 값을 내는 유형 — `const`(리터럴)·`blank`(언제나 빈 값)는 여기 없다.
#: 이전 판본의 값을 되세울 때 "그 열이 지금 있는가"를 물어야 하는 대상의 목록이다.
_SOURCE_BACKED = frozenset({"text", "date", "amount"})

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
    #: 사람이 읽는 변경 대상 이름(문서순). 문안이 이것을 지목한다.
    changed_targets: "tuple[str, ...]" = ()
    #: 바뀐 **필드 이름**(문서순·중복 제거). 증거 행이 이것을 키로 값을 뜬다 — 표시용
    #: 라벨(`금액(연결)`)에서 필드 이름을 되파싱하면 표시 문자열이 곧 조회 키가 된다
    #: (F2 §10.8.6 규칙 ③ "표시용 정규화 값에서 행동 경로를 파생하지 않는다").
    changed_fields: "tuple[str, ...]" = ()
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
    요구가 선다 — 승인은 규칙 지문 기반이라 한 번 완주하면 영구히 조용해지는데(판정 N),
    그대로 두면 다음 데이터에서 새로 생긴 빈 값이 **표식으로 박힌 문서를 조용히 생성**한다.
    빈 값 집합 자체는 선택·데이터에 딸린 사실이라 승인 결속 키(호출측 scope key)가 나른다.
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
            # 빈 값이 문서에 표식으로 박히는 실행 — 규칙이 그대로여도 승인 없이는
            # 생성이 열리지 않는다(침묵 금지, §2.13). 선택 결속 필수: 빈 값 집합은
            # 선택에 따라 달라지므로 승인이 그 집합을 본 사건이어야 한다.
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
        # 표시형은 규칙 지문에만 결속(판정 I)이되, **빈 값이 있으면 선택 결속으로
        # 승격**한다(§2.13): 빈 값 집합은 선택·데이터에 딸린 사실이라, 규칙 승인이
        # 살아남은 채 새 빈 값이 생기면 표식이 박힌 문서가 조용히 생성된다.
        selection_bound=risk != "presentation" or bool(blank_fields),
    )


def previous_values(job: Job, fields: "tuple[str, ...]", record: "dict") -> "dict[str, str]":
    """**직전 판본의 규칙으로 같은 레코드를 렌더**한 값(재작성 F7 판정 H — F5 되깎기 이행).

    F5 는 before/after 를 비웠다: 기준선이 지문만 저장해 이전 표시를 복원할 원천이 없었다.
    F7 이 직전 판본의 **값**(`Job.previous_rules`)을 1세대 보관하므로 이제 지을 수 있다.

    저장된 값을 되읽는 것이 **아니라** 이전 규칙을 지금 레코드에 적용한다 — 그래야 사용자가
    보는 두 값이 **같은 레코드의 두 규칙**이 된다. 다른 시점의 다른 데이터를 before 라고
    부르면 그게 곧 지어낸 증거다(§10.3 계열).

    반환에 없는 필드는 세 경우다: ①직전 판본이 없다(첫 저장·구 버전 작업) ②그 판본엔 그
    필드가 없었다 ③이전 규칙으로는 값을 낼 수 없다. 셋 다 **비워 둔다** — 표면이 "없음"과
    "빈 값"을 가르는 문안을 지고, 여기서 빈 문자열로 뭉개면 그 구분이 사라진다.
    """
    fields_before = (job.previous_rules or {}).get("fields") or {}
    out: "dict[str, str]" = {}
    for name in fields:
        axes = fields_before.get(name)
        if not axes:
            continue
        # **없는 열은 빈 값이 아니다**(3R P2). `value_for` 는 `record.get(source, "")` 라
        # 소스 열이 지금 데이터에 없어도 조용히 ``""`` 를 낸다 — 그대로 실으면 증거가
        # "이전엔 비어 있었습니다"라고 **단정**한다. 이전 값을 못 말하는 것과 이전 값이
        # 비어 있었다는 것은 다르다. 소스를 읽는 유형(text·date·amount)에서 그 열이 지금
        # 레코드에 없으면 뺀다 — 소스가 애초에 없던 필드(미연결)는 그때도 빈 값이 참이라
        # 남긴다.
        source = axes.get("source", "")
        if axes.get("type", "text") in _SOURCE_BACKED and source and source not in record:
            continue
        try:
            # `blank` 축은 따로 넘기지 않는다 — `is_blank` 는 ``type == "blank"`` 의 파생이라
            # 두 자리에서 세우면 서로 어긋날 수 있다(지문이 둘을 다 적는 것은 비교용이다).
            out[name] = FieldMapping(
                template_field=name,
                source=axes.get("source", ""),
                type=axes.get("type", "text"),
                const=axes.get("const", ""),
                fmt=axes.get("fmt", ""),
            ).value_for(record)
        except (ValueError, KeyError):
            # 이전 규칙이 지금 데이터에서 값을 못 내는 경우(그 열이 사라졌다 등) — 지어내지
            # 않고 비운다. "이전엔 이랬다"를 못 말하는 것과 틀리게 말하는 것은 다르다.
            continue
    return out


def build_evidence(
    req: ReviewRequirement, *, mapped: "list[dict]", names: "tuple[str, ...]",
    converged: int, too_long: int, pos: int, before: "dict[str, str] | None" = None,
) -> dict:
    """이 요구가 요구하는 증거(지도 §10.12 판정 D) — 표면이 분기를 재발명하지 않게 한 모양.

    ``before`` 는 :func:`previous_values` 가 낸 「직전 판본 규칙으로 렌더한 같은 레코드」다
    (재작성 F7 판정 H). 없으면 행에 싣지 않는다 — 직전 판본이 없는 작업(첫 저장·구 버전)에
    빈 before 를 세우면 "이전엔 비어 있었다"는 **거짓 증거**가 된다.

    ``mapped`` 는 **선택 순서**(=표시순 투영)의 매핑 결과이고 ``pos`` 는 그 안의 자리다.
    """
    if not req.required or not mapped:
        return {"policy": "", "reason": "", "rows": [], "note": ""}
    record = mapped[pos] if 0 <= pos < len(mapped) else {}
    rows: "list[dict]" = []
    note = ""
    if req.risk_class == "filename_set":
        # 이 레코드의 실이름은 **footer 가 소유**한다 — 증거 행에 다시 실으면 같은 문자열이
        # 한 면에 두 번 서고(눈검증), 무엇을 확인하라는 건지 흐려진다. 여기서 말할 것은
        # 대표 한 건이 답할 수 없는 것, 곧 **집합 성질**이다(C-01 의 요지).
        bits = []
        if converged:
            bits.append(f"같은 이름으로 겹쳐 꼬리표가 붙은 문서 {converged}건")
        if too_long:
            bits.append(f"저장 경로가 너무 긴 문서 {too_long}건")
        # 0건이면 **비운다**(U2 §2.3). 판정 K 가 요구한 것은 **건수 증거**이지 0건 성공
        # 문장이 아니다 — 「확인할 변경」 아래에서 "아무 문제 없습니다"는 확인할 것을 주지
        # 않으면서 자리만 차지하고, 진짜 건수가 뜰 자리를 무해한 문장으로 길들인다.
        note = " · ".join(bits)
    else:
        n = len(mapped)
        for name in req.changed_fields:
            value = str(record.get(name, ""))
            if req.risk_class == "semantic_binding":
                # `mapped` 는 생성 입력 그대로라 빈 값 자리에 표식이 서 있다(§2.13 —
                # 표식 조건이 「빈 값이 있으면」으로 단순해지며 승인 전 미리보기에도 선다).
                # 「비는 문서」 수는 표식도 빈 값으로 센다 — 표식은 빈 값의 문서 표기다.
                marker = MISSING_MARKER.format(field=name)
                vals = [str(r.get(name, "")) for r in mapped]
                distinct = len(set(vals))
                empty = sum(1 for v in vals if v == marker or not v.strip())
                row_note = f"선택 {n}건에서 서로 다른 값 {distinct}개"
                if empty:
                    row_note += f" · 값이 비는 문서 {empty}건"
            elif req.risk_class == "blank_set":
                # 동의의 **결과**를 그 자리에서 말한다(§2.13) — 무엇에 동의하는지 모르고
                # 누르던 종전 「클릭=확인」과 갈리는 지점. `mapped` 는 생성 입력 그대로라
                # 빈 값 자리엔 이미 표식이 서 있다 — 그 표식으로 빈 건을 센다.
                marker = MISSING_MARKER.format(field=name)
                vals = [str(r.get(name, "")) for r in mapped]
                k = sum(1 for v in vals if v == marker or not v.strip())
                row_note = (
                    f"선택 {n}건 중 {k}건이 빈 값 — 문서에는 {marker} 로 박힙니다"
                )
            else:
                row_note = "표시형이 적용된 값입니다."
            row = {"name": name, "value": value, "note": row_note}
            # before 는 **있을 때만** 싣는다(판정 H): 없는 세대를 빈 값으로 세우면
            # "이전엔 비어 있었다"는 거짓 증거가 된다.
            if before and name in before:
                row["before"] = before[name]
            rows.append(row)
    # 드로어 안에서는 게이트 문안이 안 보인다 — **왜 확인을 묻는지**를 면이 스스로 말한다
    # (눈검증: 첫 실행인데 "이름이 모두 서로 다릅니다"만 뜨면 묻지 않은 질문에 답한 꼴).
    # 같은 문장을 게이트와 공유해 두 표면이 같은 상태를 다르게 부르지 않게 한다.
    return {
        "policy": req.evidence_policy, "reason": review_reason_text(req),
        "rows": rows, "note": note,
    }


def review_reason_text(req: ReviewRequirement) -> str:
    """**왜** 확인을 묻는가 — 게이트와 드로어가 공유하는 한 문장(판정 N 의 세 갈래).

    변경 대상은 **다 적는다**: "규칙이 바뀌었습니다"만으로는 무엇을 확인하러 가는지 모른 채
    미리보기를 열게 되고, 그러면 확인이 형식이 된다(빈 값 게이트가 필드 이름을 다 적는 것과
    같은 근거).
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


def review_gate_text(req: ReviewRequirement) -> str:
    """검토 요구가 게이트에 쓰는 문안 — ①무엇이 됐는가 ②다음에 뭘 하는가만
    (`docs/COPY_STYLE_GUIDE.md` §1·§2 오류 문형: 최대 2문장)."""
    # 두 이름을 다 실물에 맞춘다: 「생성 값 미리보기」는 그 버튼에 적힌 말이고(U2 §2.3 —
    # 게이트가 다르게 부르면 지시받은 사람이 누를 것을 찾아야 한다), 「승인」은 규칙축의
    # 어휘다(U2 §2.10 — 「확인」은 필드축 ack 단독). 지목까지 준다: 이 축이 보는 것은 거울이
    # 못 보여 주는 **이름**과 값이다.
    return review_reason_text(req) + (
        " '생성 값 미리보기'에서 나갈 이름과 값을 승인해야 생성할 수 있습니다."
    )


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
