"""생성 원장 사이드카의 영속 어댑터 — 원장 payload 조립·원자 저장 + 산출물 되읽기.

원장의 **판정·행 구성은 Domain**(:mod:`hwpxfiller.domain.fill_ledger`)이 소유하고, 이 모듈은
그 순수 산출을 durable JSON 사이드카로 **기록하는 효과**(경로 발급·마스킹 관통·원자 쓰기)와
산출물 실값 **되읽기 효과**(:func:`verify_output` — P2-19R #576 에서 Domain 이월)를
소유한다. Domain 이 filesystem IO 를 개시하던 형태의 승계다 — payload 는 영속 record/codec
이라 External Adapter 책임이고, concrete 원자 교체는 :func:`.atomic.write_text_atomic`
그대로다(RC-01·bytes 불변).
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from .atomic import write_text_atomic
from hwpxfiller.domain.fields import read_fields
from hwpxfiller.domain.fill_ledger import LedgerRow, OutputLedger, ledger_outputs
from hwpxfiller.domain.mapping import MappingProfile
from hwpxfiller.domain.source_profile import FieldProfile, profile_fields
from hwpxfiller.domain.secret_redaction import redact

from .hwpx_package_io import read_hwpx_package

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


def verify_output(
    output_path: str, rows: "tuple[LedgerRow, ...]"
) -> "tuple[LedgerRow, ...]":
    """생성물 실값 되읽기(C1 ``read_fields``) — 주입 주장 위에 관측 증거를 얹는다.

    비어 있지 않은 값이 주입됐어야 하는 행(``preview_text`` 有)만 판정한다. 빈값은
    엔진이 주입 자체를 건너뛰고(공란 선언은 키가 아예 안 넘어가고) 누름틀이 남으므로
    ``None`` 유지. 문서를 읽지 못하면 raise — 증거 없음을 조용한 통과로 바꾸지 않는다.

    (P2-19R #576 에서 ``domain.fill_ledger`` 와 분리 — 산출물 경로를 다시 여는 read 효과라
    Domain 에 둘 수 없다. 판정 의미 불변.)
    """
    actual = read_fields(read_hwpx_package(output_path))
    verified: "list[LedgerRow]" = []
    for row in rows:
        if row.status in ("filled", "missing") and row.preview_text.strip():
            got = actual.get(row.field)
            ok = got == row.preview_text
            verified.append(replace(
                row, injected=ok, read_back="" if ok else str(got),
            ))
        else:
            verified.append(row)
    return tuple(verified)


def verified_outputs(
    outputs: "tuple[OutputLedger, ...]",
) -> "tuple[OutputLedger, ...]":
    """순수 원장(:func:`~hwpxfiller.domain.fill_ledger.ledger_outputs`) 위에 되읽기 증거를 얹는다.

    성공 산출물만 되읽고, 되읽기 실패는 ``verify_error`` 로 시끄럽게 남긴다 — 종전
    Domain ``ledger_outputs(verify=True)`` 의 관측 의미 그대로다.
    """
    entries: "list[OutputLedger]" = []
    for entry in outputs:
        if entry.ok:
            try:
                entry = replace(entry, rows=verify_output(entry.output, entry.rows))
            except Exception as exc:  # noqa: BLE001 - 증거 부재를 조용히 넘기지 않는다
                entry = replace(entry, verify_error=f"되읽기 실패: {exc}")
        entries.append(entry)
    return tuple(entries)


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
    (:func:`~hwpxfiller.domain.fill_ledger.ledger_outputs`)·프로파일링
    (:func:`~hwpxfiller.domain.source_profile.profile_fields`)·사이드카 경로
    (:func:`ledger_sidecar_path`)·저장을 여기서만 한다.
    취소된 배치(부분 결과)도 증거를 남긴다 — 처리된 산출물만큼만 행을 만든다.
    저장한 사이드카 경로를 반환, 실패는 raise(증거 저장 실패는 조용히 넘기지 않는다).
    """
    from datetime import datetime

    if not generated_at:
        generated_at = datetime.now().isoformat(timespec="seconds")
    results = list(results)
    outputs = verified_outputs(ledger_outputs(
        results, list(mapped_records)[: len(results)], mapping, template_fields,
        missing_marker=missing_marker,
    ))
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


def write_managed_delivery_ledger(
    out_dir: "str | Path",
    *,
    generated_at: str,
    work_authority_id: str,
    execution_basis_digest: str,
    plan_semantic_digest: str,
    result,
) -> Path:
    """managed 배달 원장(S6-05 · #812) — DeliveredDocument 사실을 그대로 축적한다.

    legacy ``OutputLedger``(MappingProfile 형)는 managed 실행의 사실(plan/basis digest·
    disposition·output digest·완화 노트)을 담을 수 없어 별도 사이드카 종류를 둔다.
    경로 규약(:func:`ledger_sidecar_path` — 축적, 덮지 않음)과 원자 쓰기는 공유한다.
    ``result`` 는 delivery coordinator 의 Completed/Aborted 값이다 — 재판정 없이 기록만.
    """
    from dataclasses import asdict

    delivered = [
        {**asdict(doc), "execution_notes": [asdict(note) for note in doc.execution_notes]}
        for doc in result.delivered
    ]
    payload: dict = {
        "ledger_kind": "managed-delivery/v1",
        "generated_at": generated_at,
        "work_authority_id": work_authority_id,
        "execution_basis_digest": execution_basis_digest,
        "plan_semantic_digest": plan_semantic_digest,
        "outcome": type(result).__name__,
        "delivered": delivered,
    }
    if hasattr(result, "code"):  # DeliveryAborted — 멈춘 사실도 증거다(숨기지 않는다).
        payload["aborted"] = {
            "code": result.code,
            "detail": result.detail,
            "failed_item_ordinal": result.failed_item_ordinal,
        }
    sidecar = ledger_sidecar_path(out_dir, generated_at)
    write_text_atomic(sidecar, json.dumps(payload, ensure_ascii=False, indent=2))
    return sidecar


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
