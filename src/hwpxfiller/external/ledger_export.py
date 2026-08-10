"""생성 원장 사이드카의 영속 어댑터 — 원장 payload 조립과 원자 저장(P2-18, #566).

원장의 **판정·행 구성은 Domain**(:mod:`hwpxfiller.core.fill_ledger`)이 소유하고, 이 모듈은
그 순수 산출을 durable JSON 사이드카로 **기록하는 효과**(경로 발급·마스킹 관통·원자 쓰기)만
소유한다. Domain 이 filesystem write 를 개시하던 형태의 승계다 — payload 는 영속 record/codec
이라 External Adapter 책임이고, concrete 원자 교체는 :func:`hwpxcore.atomic.write_text_atomic`
그대로다(RC-01·bytes 불변).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from hwpxcore.atomic import write_text_atomic

from hwpxfiller.core.fill_ledger import OutputLedger, ledger_outputs
from hwpxfiller.core.mapping import MappingProfile
from hwpxfiller.core.source_profile import FieldProfile, profile_fields
from hwpxfiller.domain.secret_redaction import redact

if TYPE_CHECKING:
    from hwpxfiller.gui.run_state import GenerationPlan

#: 사이드카 고정 파일명 — 경로를 직접 지정하는 호출용. 실행별 사이드카(배치 저장
#: 폴더)는 :func:`ledger_sidecar_path` 로 타임스탬프 이름을 발급받아 증거를 축적한다.
LEDGER_SIDECAR_NAME = "fill-ledger.json"

#: 사이드카에 박제하는 고지 — 값 미리보기는 HWPX 렌더가 아니다(ADR C 불변).
LEDGER_PREVIEW_NOTE = (
    "preview_text/read_back 은 주입될·주입된 텍스트 값이다. "
    "HWPX 렌더(서식·레이아웃)가 아니다."
)


def _redacted(payload: dict) -> dict:
    """export 직전 전 문자열 마스킹 관통(N1) — 키·값 어느 쪽도 예외 없이 걷는다.

    원장의 소스 표기는 포인터-온리라 정상 경로엔 비밀이 없지만, 소스 값·오류 메시지가
    URL(ServiceKey 포함)을 품고 흘러들 수 있다 — 과삭제 원칙으로 전면 방어한다.
    """

    def walk(v):
        if isinstance(v, str):
            return redact(v)
        if isinstance(v, dict):
            return {walk(k): walk(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(item) for item in v]
        return v

    return {walk(k): walk(v) for k, v in payload.items()}


def export_run_ledger(
    path: "str | Path",
    *,
    template: str,
    source: str,
    outputs: "tuple[OutputLedger, ...] | list[OutputLedger]",
    job_name: str = "",
    profiles: "list[FieldProfile] | tuple[FieldProfile, ...]" = (),
    generated_at: str = "",
) -> dict:
    """생성 원장 JSON 사이드카 저장(**opt-in per batch**) — 저장한 payload 를 반환.

    - ``source`` 는 **포인터-온리**(파일 경로·소스 종류 표기) — 나라 쿼리 URL·키를
      박제하지 않는다.
    - 저장 직전 :func:`_redacted` 로 전 문자열에 N1 마스킹을 관통시킨다(키 비직렬화).
    """
    payload = _redacted({
        "kind": "hwpx-fill-ledger",
        "version": 1,
        "generated_at": generated_at,
        "template": template,
        "source": source,
        "job": job_name,
        "note": LEDGER_PREVIEW_NOTE,
        "profiles": [p.to_dict() for p in profiles],
        "outputs": [o.to_dict() for o in outputs],
    })
    # 원자 쓰기(RC-01) — 저장 중 실패가 기존 원장(증거)을 파괴하지 않는다.
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def export_batch_ledger(
    out_dir: "str | Path",
    *,
    template: str,
    source: str,
    mapping: MappingProfile,
    template_fields: "Iterable[str]",
    results,
    mapped_records: "list[dict[str, str]] | tuple[dict[str, str], ...]",
    source_records: "list[dict[str, str]] | tuple[dict[str, str], ...]" = (),
    source_keys: "Iterable[str] | None" = None,
    labels: "dict[str, str] | None" = None,
    job_name: str = "",
    missing_marker: str = "",
    generated_at: str = "",
) -> Path:
    """원장 문맥 조립 + export 의 **단일 함수**(RC-03) — GUI(RunViewModel)·CLI 가 공유한다.

    표면별 병렬 구현(cli._export_ledger vs RunViewModel.export_run_ledger)이
    job명/missing_marker/profiles 축에서 이미 갈라졌던 결함의 봉합: 행 구성
    (:func:`~hwpxfiller.core.fill_ledger.ledger_outputs`)·프로파일링
    (:func:`~hwpxfiller.core.source_profile.profile_fields`)·사이드카 경로
    (:func:`ledger_sidecar_path`)·저장을 여기서만 한다.
    취소된 배치(부분 결과)도 증거를 남긴다 — 처리된 산출물만큼만 행을 만든다.
    저장한 사이드카 경로를 반환, 실패는 raise(증거 저장 실패는 조용히 넘기지 않는다).
    """
    from datetime import datetime

    if not generated_at:
        generated_at = datetime.now().isoformat(timespec="seconds")
    results = list(results)
    outputs = ledger_outputs(
        results, list(mapped_records)[: len(results)], mapping, template_fields,
        missing_marker=missing_marker,
    )
    profiles = profile_fields(
        list(source_records),
        list(source_keys) if source_keys is not None else None,
        labels=labels or {},
    )
    sidecar = ledger_sidecar_path(out_dir, generated_at)
    export_run_ledger(
        sidecar,
        template=template,
        source=source,
        outputs=outputs,
        job_name=job_name,
        profiles=profiles,
        generated_at=generated_at,
    )
    return sidecar


def export_plan_ledger(plan: "GenerationPlan", batch) -> str:
    """계획 스냅샷 + 배치 결과만으로 원장 사이드카 저장(RC-07) — 라이브 상태 재독 0.

    :class:`~hwpxfiller.gui.run_state.GenerationPlan` 은 Application 소유의 불변 계획이고,
    이 함수는 그 계획을 증거로 기록하는 effect 접합부다. 저장 경로 반환, 실패는 raise
    (호출측 워커/뷰가 시끄럽게 표면화).
    """
    if plan.mapping is None:
        raise ValueError("원장 export 에는 계획의 매핑 스냅샷이 필요합니다.")
    sidecar = export_batch_ledger(
        plan.out_dir,
        template=plan.template,
        source=plan.source_pointer,
        mapping=plan.mapping,
        template_fields=list(plan.template_fields),
        results=batch.results,
        mapped_records=list(plan.records),
        source_records=list(plan.source_records),
        source_keys=list(plan.source_keys),
        labels=dict(plan.labels),
        job_name=plan.job_name,
        missing_marker=plan.marker,
    )
    return str(sidecar)


def ledger_sidecar_path(out_dir: "str | Path", generated_at: str) -> Path:
    """실행별 원장 사이드카 경로 — 타임스탬프 파일명으로 이전 실행의 증거를 덮지 않는다(RC-02).

    ``generated_at``(ISO, 초 해상도)의 숫자만 취해 ``fill-ledger-YYYYMMDD-HHMMSS.json``
    을 만든다. 같은 초 재실행으로 그 경로가 이미 있으면 ``-1``·``-2`` 접미사로 비켜
    간다 — 원장은 교체가 아니라 **축적**이다(이전 실행의 증거 보존).
    """
    stamp = re.sub(r"\D", "", generated_at)
    if len(stamp) >= 14:
        base = f"fill-ledger-{stamp[:8]}-{stamp[8:14]}"
    else:  # 비정상 입력도 조용히 덮지 않도록 접미사 루프는 동일하게 태운다.
        base = "fill-ledger"
    out = Path(out_dir)
    cand = out / f"{base}.json"
    i = 1
    while cand.exists():
        cand = out / f"{base}-{i}.json"
        i += 1
    return cand
