"""생성 원장 척추 — 매핑 전건 커버와 구조 드리프트의 순수 파생.

별도 스냅샷을 저장하지 않는다. 사람이 확정한 매핑 커버가 기준선이고, 현재 템플릿
누름틀과의 대칭차가 곧 템플릿-구조 드리프트다. 소스-구조와 값 공란은 서로 다른
상태축으로 유지해 템플릿 드리프트만 하드게이트하고 값 공란은 ADR-E 확인을 보존한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Iterable

from hwpxcore.atomic import write_text_atomic

from .engine import HwpxEngine
from .fields import FillNote, read_fields
from .mapping import FieldMapping, MappingProfile
from .source_profile import FieldProfile


class StructureState(str, Enum):
    """구조 이상 축. 템플릿과 소스의 처방이 달라 합쳐 버리지 않는다."""

    OK = "ok"
    TEMPLATE_DRIFT = "template_drift"
    SOURCE_DRIFT = "source_drift"
    TEMPLATE_AND_SOURCE_DRIFT = "template_and_source_drift"


class ValueState(str, Enum):
    """레코드 값 축(구조 드리프트와 독립, ADR-E 확인 대상)."""

    OK = "ok"
    EMPTY = "empty"


@dataclass(frozen=True)
class TemplateStructureDrift:
    """현재 템플릿 누름틀과 매핑 커버의 양방향 대칭차."""

    template_only: "tuple[str, ...]" = ()
    mapping_only: "tuple[str, ...]" = ()
    conflicting: "tuple[str, ...]" = ()
    read_error: str = ""

    @property
    def has_drift(self) -> bool:
        return bool(self.template_only or self.mapping_only or self.conflicting or self.read_error)

    @property
    def introduced(self) -> "tuple[str, ...]":
        """템플릿에 새로 유입됐으나 매핑이 커버하지 않는 필드."""
        return self.template_only

    @property
    def removed(self) -> "tuple[str, ...]":
        """매핑 계약에는 있으나 현재 템플릿에서 소멸한 필드."""
        return self.mapping_only

    @property
    def symmetric_difference(self) -> "set[str]":
        return set(self.template_only) | set(self.mapping_only)

    @property
    def template_uncovered(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``T - C``."""
        return self.template_only

    @property
    def mapping_orphaned(self) -> "tuple[str, ...]":
        """방향을 드러내는 별칭: ``C - T``."""
        return self.mapping_only

    def describe(self, sep: str = "\n") -> str:
        """차단 사유 상세 문구의 **단일 출처**(RC-03) — GUI·CLI·생성 경계가 같은 문장을 쓴다.

        표면별로 문구를 재조립하면 이미 갈라졌던 전례(run_state/run_view/cli/batch 4곳)가
        있어, 조립을 여기로 하강한다. 드리프트가 없으면 빈 문자열.
        """
        parts: "list[str]" = []
        if self.read_error:
            parts.append("템플릿 구조를 읽을 수 없음: " + self.read_error)
        if self.template_only:
            parts.append("새로 유입된 미매핑 필드: " + ", ".join(self.template_only))
        if self.mapping_only:
            parts.append("템플릿에서 소멸한 매핑 필드: " + ", ".join(self.mapping_only))
        if self.conflicting:
            parts.append("값 매핑과 비움 확정이 충돌하는 필드: " + ", ".join(self.conflicting))
        return sep.join(parts)


def template_structure_drift(
    template_fields: "Iterable[str]", mapping: MappingProfile
) -> TemplateStructureDrift:
    """``현재 템플릿 Δ effective mapping 커버``를 순서 안정적으로 계산한다."""
    template_order = list(dict.fromkeys(template_fields))
    cover_order = mapping.cover_fields()
    template_set = set(template_order)
    cover_set = set(cover_order)
    return TemplateStructureDrift(
        template_only=tuple(f for f in template_order if f not in cover_set),
        mapping_only=tuple(f for f in cover_order if f not in template_set),
        conflicting=tuple(mapping.coverage_conflicts()),
    )


# 간결한 호출명도 제공한다. L2가 원장 행을 확장할 때 같은 seam을 그대로 소비한다.
mapping_drift = template_structure_drift


def template_path_drift(path: "str", mapping: MappingProfile) -> TemplateStructureDrift:
    """HWPX 경로를 매 호출 다시 읽어 구조 드리프트를 fail-closed로 계산한다.

    GUI 실행·CLI가 공유하는 경계다. 파일 부재/손상/파싱 실패를 정상
    빈 템플릿으로 오인하지 않고 ``read_error`` 로 반환한다.
    """
    if not path:
        return TemplateStructureDrift(read_error="템플릿 경로가 비어 있습니다.")
    try:
        fields = HwpxEngine().required_fields(path)
    except Exception as exc:  # noqa: BLE001 - 구조를 증명 못 하면 fail-closed
        return TemplateStructureDrift(read_error=str(exc))
    return template_structure_drift(fields, mapping)


@dataclass(frozen=True)
class FillLedger:
    """생성 전 구조/값 상태의 최소 원장. L2 export가 확장할 척추."""

    template_drift: TemplateStructureDrift = field(default_factory=TemplateStructureDrift)
    missing_sources: "tuple[str, ...]" = ()
    empty_values: "tuple[str, ...]" = ()

    @property
    def structure_state(self) -> StructureState:
        template_bad = self.template_drift.has_drift
        source_bad = bool(self.missing_sources)
        if template_bad and source_bad:
            return StructureState.TEMPLATE_AND_SOURCE_DRIFT
        if template_bad:
            return StructureState.TEMPLATE_DRIFT
        if source_bad:
            return StructureState.SOURCE_DRIFT
        return StructureState.OK

    @property
    def value_state(self) -> ValueState:
        return ValueState.EMPTY if self.empty_values else ValueState.OK

    @property
    def template_structure_drift(self) -> bool:
        return self.template_drift.has_drift

    @property
    def source_structure_drift(self) -> bool:
        return bool(self.missing_sources)


def build_fill_ledger(
    template_fields: "Iterable[str]",
    mapping: MappingProfile,
    *,
    source_fields: "Iterable[str] | None" = None,
    empty_values: "Iterable[str]" = (),
) -> FillLedger:
    """구조/값 축을 한 번에 파생한다.

    소스의 추가 열은 정상이다. 매핑이 요구하는 소스가 사라진 경우만 소스-구조
    드리프트이며, 이는 loud 진단이되 템플릿 하드게이트와 달리 실행 하드락 사유가 아니다.
    """
    missing_sources: "tuple[str, ...]" = ()
    if source_fields is not None:
        available = set(source_fields)
        required = list(dict.fromkeys(
            m.source for m in mapping.mappings if not m.is_blank and m.source
        ))
        missing_sources = tuple(s for s in required if s not in available)
    return FillLedger(
        template_drift=template_structure_drift(template_fields, mapping),
        missing_sources=missing_sources,
        empty_values=tuple(dict.fromkeys(empty_values)),
    )


# ==================================================================== L2 원장 export
#: 사이드카 고정 파일명 — 경로를 직접 지정하는 호출용. 실행별 사이드카(배치 저장
#: 폴더)는 :func:`ledger_sidecar_path` 로 타임스탬프 이름을 발급받아 증거를 축적한다.
LEDGER_SIDECAR_NAME = "fill-ledger.json"

#: 사이드카에 박제하는 고지 — 값 미리보기는 HWPX 렌더가 아니다(ADR C 불변).
LEDGER_PREVIEW_NOTE = (
    "preview_text/read_back 은 주입될·주입된 텍스트 값이다. "
    "HWPX 렌더(서식·레이아웃)가 아니다."
)


@dataclass(frozen=True)
class LedgerRow:
    """생성 원장의 필드당 1행 — dry-run 매니페스트와 사후 증거가 같은 형태를 쓴다.

    ``injected`` 는 생성 후 :func:`verify_output` 이 문서를 **되읽어** 채우는 증거값이다
    (``GenerateResult.applied`` 는 엔진의 주장, 이 값은 산출물의 관측). ``None`` 은
    "검증 대상 아님/미검증"(공란 선언·빈값 스킵·생성 실패)이지 성공 추정이 아니다.
    """

    field: str
    status: str                          # "filled" | "blank" | "missing" | "drift"
    source: str = ""                     # 이 필드가 읽는 소스 키(포인터, 값 아님)
    type: str = ""
    fmt: str = ""
    preview_text: str = ""               # dry-run 결과값(텍스트) — HWPX 렌더 아님
    injected: "bool | None" = None       # 되읽기 증거: True/False, None=해당없음·미검증
    read_back: str = ""                  # injected=False 일 때 문서의 실제 값(증거)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "status": self.status,
            "source": self.source,
            "type": self.type,
            "fmt": self.fmt,
            "preview_text": self.preview_text,
            "injected": self.injected,
            "read_back": self.read_back,
        }


def manifest_rows(
    mapping: MappingProfile,
    template_fields: "Iterable[str]",
    mapped_record: "dict[str, str]",
    *,
    missing_marker: str = "",
) -> "tuple[LedgerRow, ...]":
    """레코드 1건의 dry-run 매니페스트 — 생성 전 "무엇이 어떻게 들어갈지".

    행 순서·상태 판정은 run_state ``field_states`` 와 같은 규칙(매핑 계약순 + 템플릿
    신규 유입순, 대칭차·충돌은 ``drift``)이다. ``missing_marker`` 가 주어지면 표식이
    주입된 값도 미충족(``missing``)으로 분류하되 ``preview_text`` 는 실제 주입값(표식)
    그대로 둔다 — 원장은 들어가는 값을 있는 그대로 기록한다.
    """
    drift = template_structure_drift(template_fields, mapping)
    drift_fields = drift.symmetric_difference | set(drift.conflicting)
    value_maps: "dict[str, FieldMapping]" = {}
    for m in mapping.mappings:
        if not m.is_blank:
            value_maps.setdefault(m.template_field, m)
    blanks = set(mapping.blank_fields())
    rows: "list[LedgerRow]" = []
    order = list(mapping.cover_fields()) + list(drift.template_only)
    for name in dict.fromkeys(order):
        m = value_maps.get(name)
        source = m.source if m else ""
        type_ = m.type if m else ""
        fmt = m.fmt if m else ""
        value = str(mapped_record.get(name, ""))
        if name in drift_fields:
            rows.append(LedgerRow(name, "drift", source, type_, fmt, value))
        elif name in blanks:
            rows.append(LedgerRow(name, "blank", type="blank"))
        else:
            is_missing = value == "" or (
                bool(missing_marker) and value == missing_marker.format(field=name)
            )
            rows.append(LedgerRow(
                name, "missing" if is_missing else "filled",
                source, type_, fmt, value,
            ))
    return tuple(rows)


def verify_output(
    output_path: str, rows: "tuple[LedgerRow, ...]"
) -> "tuple[LedgerRow, ...]":
    """생성물 실값 되읽기(C1 ``read_fields``) — 주입 주장 위에 관측 증거를 얹는다.

    비어 있지 않은 값이 주입됐어야 하는 행(``preview_text`` 有)만 판정한다. 빈값은
    엔진이 주입 자체를 건너뛰고(공란 선언은 키가 아예 안 넘어가고) 누름틀이 남으므로
    ``None`` 유지. 문서를 읽지 못하면 raise — 증거 없음을 조용한 통과로 바꾸지 않는다.
    """
    actual = read_fields(output_path)
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


@dataclass(frozen=True)
class OutputLedger:
    """산출물 1건의 원장 — 생성 결과 + 필드행(검증 여부 포함)."""

    output: str
    ok: bool
    rows: "tuple[LedgerRow, ...]" = ()
    error: str = ""                      # 생성 실패 사유(엔진 보고)
    verify_error: str = ""               # 되읽기 실패 사유(증거 부재는 시끄럽게)
    # 채움 완화 사실(#154 — 인라인 요소 제거·값 런 합성 등). 원장은 증거 채널이라
    # 완화가 여기 빠지면 "왜 표식이 사라졌나"가 사후에 복원 불가능해진다.
    notes: "tuple[FillNote, ...]" = ()

    def to_dict(self) -> dict:
        return {
            "output": self.output,
            "ok": self.ok,
            "error": self.error,
            "verify_error": self.verify_error,
            "notes": [
                {"field": n.field, "kind": n.kind, "detail": list(n.detail)}
                for n in self.notes
            ],
            "rows": [r.to_dict() for r in self.rows],
        }


def ledger_outputs(
    results,
    mapped_records: "list[dict[str, str]]",
    mapping: MappingProfile,
    template_fields: "Iterable[str]",
    *,
    missing_marker: str = "",
    verify: bool = True,
) -> "tuple[OutputLedger, ...]":
    """배치 결과(:class:`~hwpxfiller.core.engine.GenerateResult` 순서열)와 매핑된
    레코드를 합쳐 산출별 원장을 만든다. 성공 산출물은 되읽기 검증까지.
    """
    template_order = list(template_fields)
    entries: "list[OutputLedger]" = []
    for res, record in zip(results, mapped_records, strict=True):
        rows = manifest_rows(
            mapping, template_order, record, missing_marker=missing_marker
        )
        verify_error = ""
        if verify and res.ok:
            try:
                rows = verify_output(res.output_path, rows)
            except Exception as exc:  # noqa: BLE001 - 증거 부재를 조용히 넘기지 않는다
                verify_error = f"되읽기 실패: {exc}"
        entries.append(
            OutputLedger(
                res.output_path, res.ok, rows, res.error, verify_error,
                notes=tuple(res.notes),
            )
        )
    return tuple(entries)


def _redacted(payload: dict) -> dict:
    """export 직전 전 문자열 마스킹 관통(N1) — 키·값 어느 쪽도 예외 없이 걷는다.

    원장의 소스 표기는 포인터-온리라 정상 경로엔 비밀이 없지만, 소스 값·오류 메시지가
    URL(ServiceKey 포함)을 품고 흘러들 수 있다 — 과삭제 원칙으로 전면 방어한다.
    """
    from ..data.secret_store import redact

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
    (:func:`ledger_outputs`)·프로파일링(:func:`~hwpxfiller.core.source_profile.
    profile_fields`)·사이드카 경로(:func:`ledger_sidecar_path`)·저장을 여기서만 한다.
    취소된 배치(부분 결과)도 증거를 남긴다 — 처리된 산출물만큼만 행을 만든다.
    저장한 사이드카 경로를 반환, 실패는 raise(증거 저장 실패는 조용히 넘기지 않는다).
    """
    from datetime import datetime

    from .source_profile import profile_fields

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
