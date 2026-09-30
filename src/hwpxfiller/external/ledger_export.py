"""생성 원장 사이드카의 영속 어댑터 — managed 배달 원장의 경로 발급·원자 저장.

원장은 판정하지 않는다 — 배달 coordinator 가 낸 사실(:class:`~hwpxfiller.external
.delivery_coordinator.DeliveredDocument`·중단 사실)과 봉인 basis·plan digest 를 그대로 싣는다.
GUI 「문서 만들기」와 CLI ``--ledger`` 가 같은 원장을 쓴다(#1081 PR3). 종전의 legacy 원장
(``hwpx-fill-ledger`` — 매핑 행·값 미리보기·원천 프로파일·되읽기 행)은 legacy 생성기와 함께
퇴역했다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .atomic import write_text_atomic
from hwpxfiller.domain.secret_redaction import redact


def write_managed_delivery_ledger(
    out_dir: "str | Path",
    *,
    generated_at: str,
    work_authority_id: str,
    execution_basis_digest: str,
    plan_semantic_digest: str,
    result,
    source: "str | None" = None,
) -> Path:
    """managed 배달 원장(S6-05 · #812) — DeliveredDocument 사실을 그대로 축적한다.

    ``source`` 는 CLI 가 싣는 데이터 출처 **포인터**다(``file:``·``nara:``·``sqlite:`` —
    값·쿼리·키를 박제하지 않는다). GUI 는 싣지 않는다(작업이 데이터 결속을 이미 든다).

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
    if source is not None:
        payload["source"] = redact(source)
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
