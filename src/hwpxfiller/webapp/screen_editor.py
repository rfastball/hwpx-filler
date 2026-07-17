"""작업 에디터(HWPX) 화면 컨트롤러 — 4단계 마법사 오케스트레이션(webview 비의존).

목업 scr-editor 의 웹 이관(에픽 #20, 화면 #15·#16). 링1 VM 을 **그대로 임포트**해 구동한다:
매핑은 :class:`~hwpxfiller.gui.mapping_state.MappingModel`, PARTIAL 게이트는
:class:`~hwpxfiller.gui.mapping_state.PartialGate`, 저장 게이트는
:func:`~hwpxfiller.gui.job_editor_state.validate_save`. 이들은 Qt-free 라 그대로 산다
(스파이크 Q1 배당금). 표현 계층(단계 UI·행 색·표시형)만 웹으로 이식한다.

**단계**: 0 템플릿 → 1 데이터(선택) → 2 매핑 확정 → 3 저장. 진행 게이트는 Qt 위저드와 동일:
0→1 은 스키마 有+게이트 통과, 1→2 은 무조건(데이터 선택적, ADR-J), 2→3 은 ``is_complete()``.

**#26 패리티 회수(이 라운드 포함)**: 편집 모드(:meth:`EditorController.load_job`) ·
선언 데이터 자동등록(#18 31A5A484-C, ``_do_save`` 선차단 게이트) · 매핑 베이스 프로파일
적용/저장/삭제(ADR J 축2, ``_do_profile_*``). 자동등록은 **참조만** 저장한다(행·ServiceKey
없음 — [[nara-freeze-decision]]과 무관한 excel 참조).

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)** — 태그 분류 편집(D14, #26 홈 조치 단위)·
인라인 누름틀 변환(fieldize, tpl 화면 경유로 충족 — 위저드 인라인은 별도 제안)은 여기 없다.
RAW 차단·PARTIAL 게이트·의도적 비움 이름게이트·저장 게이트·덮어쓰기 확인·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from ..core.format_engine import presets as format_presets
from ..core.job import (
    DEFAULT_FILENAME_PATTERN,
    Job,
    JobRegistry,
    SlugCollisionError,
    classify_existing,
)
from ..core.mapping import TYPES
from ..core.mapping_base import MappingBaseRegistry, default_mapping_bases_dir
from ..core.schema import extract_schema
from ..data import source_for_path
from ..gui.dataset_pool_state import kind_transition_clause, reference_summary
from ..gui.job_editor_state import (
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from ..gui.mapping_state import (
    RAW_BLOCK_MESSAGE,
    MappingModel,
    PartialGate,
    gate_for_template,
    profile_source_vocabulary,
)
from .screens import PushSink, default_pool_registry

# 표시형 프리셋은 유형별 고정 → 한 번 계산해 스냅샷에 싣는다(코어 라벨 그대로).
_FMT_OPTIONS = {t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES}

# 2단계 데이터 미리보기에 싣는 샘플 행 수(#16 98DDFE96) — 전체 적재는 이미 self.records
# 에 있으나 스냅샷엔 매핑 감(感)만 주는 소량만 노출한다(record_count 로 "외 M건" 표기).
_SAMPLE_ROWS = 3


def _job_content_fingerprint(job: Job) -> str:
    """편집 세션이 덮어쓰는 작업 **내용**의 지문 — 외부 변경 감지(자기-갱신 확인 게이트).

    태그·마지막 실행은 제외한다: 편집 저장이 어차피 저장 직전 디스크 값을 재읽어 보존하므로
    (홈 태그 편집과의 공존, ``_do_save``) 그 둘의 변경은 파괴가 아니다. 나머지(템플릿·매핑·
    파일명 패턴·계보·**기본 데이터셋 참조**)는 편집 세션 상태로 덮어써지므로, 로드 시점과
    달라져 있으면 '편집 중 외부 변경'으로 확인을 요구해야 한다(무확인 파괴 금지).

    기본 데이터셋 참조(#53-A)는 ``to_dict()`` 에 들어가 여기 지문에 **자동 포함**된다 —
    #53-B 가 재연결 동선을 추가해 외부에서 참조가 바뀌어도 편집 저장이 조용히 되돌리지
    않고 확인을 띄운다(의도된 설계).
    """
    d = job.to_dict()
    d.pop("tags", None)
    d.pop("last_run_at", None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


class EditorController:
    """작업 에디터 화면 — 마법사 세션 상태 소유·링1 VM 위임."""

    name = "editor"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        base_registry: "MappingBaseRegistry | None" = None,
        pool_registry: "DatasetPoolRegistry | None" = None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        # 프로파일·데이터풀 레지스트리 — 주입 가능(테스트), 기본은 홈 레지스트리(ADR J).
        self.base_registry = (
            base_registry if base_registry is not None
            else MappingBaseRegistry(default_mapping_bases_dir())
        )
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        self._reset()

    def _reset(self) -> None:
        self.step = 0
        self.template_path = ""
        self.schema = None
        self.gate: "PartialGate | None" = None
        self.gate_error = False
        self.raw_block = ""
        self.data_path = ""
        self.data_sheet = ""  # 다중 시트 확정값(#33) — 자동등록 참조에 함께 저장(#26)
        self.source_fields: "list[str]" = []
        # '미사용' 헤더(#49) — 세션 국소 상태. durable 저장 없음: 매핑이 곧 사용 헤더의
        # 기억(job.source_keys)이므로 재편집 시 활성 헤더는 저장 매핑에서 파생된다.
        # 자동 제안·소스 드롭다운 후보만 활성 헤더로 좁힌다(원본 데이터·매핑 계약 불변).
        self._ignored_sources: "set[str]" = set()
        self.records: "list[dict]" = []
        self.model: "MappingModel | None" = None
        self._model_key: "tuple | None" = None
        self.preview_index = 0
        self.job_name = ""
        self.pattern = DEFAULT_FILENAME_PATTERN
        self.dataset_name = ""  # 자동등록 이름(기본=데이터 파일 스템, 사용자 수정 가능)
        # 편집 모드에서 복원한 기본 데이터셋 참조(#53-A) — 데이터를 새로 안 고르고 저장하면
        # 이 값을 보존한다(편집 저장이 조용히 기본 데이터 연결을 소실시키지 않게).
        self.default_dataset_ref = ""
        # 편집 모드 상태(#26): 원점 이름(자기-갱신 판정)·보존 메타(태그·마지막 실행) —
        # 편집 저장이 브라우저 태그·이력을 조용히 소실시키지 않는다.
        self._editing_origin = ""
        self._preserved_tags: "dict[str, str]" = {}
        self._preserved_last_run = ""
        # 로드 시점 작업 내용 지문(태그·마지막 실행 제외) — 자기-갱신 저장이 편집 중
        # 외부 변경을 무확인으로 덮지 않게 하는 근거(_do_save 확인 게이트).
        self._editing_fingerprint = ""
        # _dataset_gate 가 로드한 동명 기존 풀 항목 stash — _do_save 말미 등록이 같은
        # .dataset.json 을 재로드·재판정하지 않게 한다(게이트/저장 판정 표류 방지).
        self._dataset_existing: "DatasetPoolItem | None" = None
        self._base_name = ""  # 이 세션 매핑을 시드/저장한 베이스 이름(J3 계보)
        # 편집 모드에서 복원한 작성 출처 메타(#53-C) — 표시용 + 재저장 시 최초 작성시각 보존.
        self._loaded_provenance: "dict[str, str]" = {}
        self.notice_text = ""  # 복원·프로파일 반영 등 세션 통지(loud 재진술 채널)
        self.notice_level = "muted"

    def _set_notice(self, text: str, level: str = "muted") -> None:
        self.notice_text = text
        self.notice_level = level

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 진행 게이트
    def _template_ready(self) -> bool:
        return (
            self.schema is not None and bool(self.schema.fields) and not self.gate_error
            and (self.gate is None or self.gate.can_proceed())
        )

    def can_advance(self, from_step: int) -> bool:
        """from_step → from_step+1 진행 가부(Qt 위저드 isComplete 미러)."""
        if from_step == 0:
            return self._template_ready()
        if from_step == 1:
            return True  # 데이터는 선택적(ADR-J)
        if from_step == 2:
            return self.model is not None and self.model.is_complete()
        return False

    # --------------------------------------------------- 활성 헤더(#49)
    def _active_sources(self) -> "list[str]":
        """미사용을 뺀 활성 헤더(원 순서 보존) — 자동 제안·소스 드롭다운 후보의 단일 출처."""
        return [f for f in self.source_fields if f not in self._ignored_sources]

    # ------------------------------------------------------------- 스냅샷
    def _current_record(self) -> "dict":
        if not self.records:
            return {}
        return self.records[self.preview_index % len(self.records)]

    def _row_snapshot(self, index: int, row, record: "dict", schema_only: bool) -> dict:
        try:
            preview = row.to_mapping().value_for(record)
            preview_error = False
        except ValueError:
            preview, preview_error = "", True
        empty = bool(row.has_content()) and preview == ""
        if row.confirmed:
            state = "confirmed"
        elif row.has_content():
            state = "unconfirmed"
        elif schema_only:
            state = "schemaonly"
        else:
            state = "unmatched"
        inferred = getattr(row.spec, "inferred_type", "") if row.spec else ""
        return {
            "index": index,
            "template_field": row.template_field,
            "inferred_type": inferred,
            "context": getattr(row.spec, "context", "") if row.spec else "",
            "source": row.source,
            "type": row.type,
            "const": row.const,
            "fmt": row.fmt,
            "confirmed": row.confirmed,
            "has_content": row.has_content(),
            "suggestion_score": round(row.suggestion_score, 3),
            "preview": preview,
            "preview_empty": empty,
            "preview_error": preview_error,
            "row_state": state,
        }

    def snapshot(self) -> dict:
        active_sources = self._active_sources()  # 활성/카운트 재사용(1회 계산)
        snap: dict = {
            "step": self.step,
            "reachable": [self.can_advance(s) for s in range(3)],  # 0→1,1→2,2→3
            "template_path": self.template_path,
            "template_name": self.template_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "field_count": len(self.schema.fields) if self.schema else 0,
            "schema_summary": self._schema_summary(),
            # 1단계 구조화 표(#16): 필드별 name/inferred_type/in_table/occurrences/context.
            # 나열식 요약(schema_summary)은 표 위 헤더 한 줄로 존치.
            "fields": [f.to_dict() for f in self.schema.fields] if self.schema else [],
            "raw_block": self.raw_block,
            "gate": self._gate_snapshot(),
            "gate_error": self.gate_error,
            "data_path": self.data_path,
            "data_name": self.data_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "record_count": len(self.records),
            # 전체 헤더(데이터 미리보기 컬럼·sample_rows 정렬의 짝, 불변).
            "source_fields": self.source_fields,
            # 활성/미사용 헤더(#49) — 드롭다운 후보는 활성만, 헤더 선택 UI는 둘 다 쓴다.
            "active_source_fields": active_sources,
            "ignored_source_fields": [f for f in self.source_fields if f in self._ignored_sources],
            "active_count": len(active_sources),
            "ignored_count": len(self._ignored_sources),
            # 2단계 데이터 미리보기(#16): source_fields 순서로 투영한 샘플 행 소량.
            # 빈 셀은 "" 로 보존해 렌더가 (빈 값)으로 시끄럽게 표기(ADR-B).
            "sample_rows": self._sample_rows(),
            "type_options": list(TYPES),
            "fmt_options": _FMT_OPTIONS,
            "name": self.job_name,
            "pattern": self.pattern,
            "has_unsaved_work": self.has_unsaved_work(),
            # #26 편집 모드·프로파일·자동등록 표면.
            "editing_origin": self._editing_origin,
            "base_name": self._base_name,
            "dataset_name": self.dataset_name,
            # 작성 출처 provenance(#53-C) — 편집 모드에서 복원한 것(없으면 None).
            "provenance": self._loaded_provenance or None,
            "notice": (
                {"text": self.notice_text, "level": self.notice_level}
                if self.notice_text else None
            ),
        }
        if self.model is not None:
            schema_only = self.model.is_schema_only()
            record = self._current_record()
            snap["rows"] = [
                self._row_snapshot(i, r, record, schema_only)
                for i, r in enumerate(self.model.rows)
            ]
            filled, empty, unmapped = self.model.preview_counts(record)
            snap["counts"] = {"filled": filled, "empty": empty, "unmapped": unmapped}
            snap["preview_empties"] = self.model.preview_empties(record)
            snap["preview_index"] = (self.preview_index % len(self.records)) + 1 if self.records else 0
            snap["preview_count"] = len(self.records)
            snap["is_complete"] = self.model.is_complete()
            snap["schema_only"] = schema_only
        else:
            snap["rows"] = []
            snap["is_complete"] = False
        return snap

    def _schema_summary(self) -> str:
        if self.schema is None:
            return ""
        head = ", ".join(f"{f.name}({f.inferred_type})" for f in self.schema.fields[:6])
        extra = "" if len(self.schema.fields) <= 6 else f" 외 {len(self.schema.fields) - 6}개"
        return f"필드 {len(self.schema.fields)}개: {head}{extra}"

    def _build_provenance(self, profile) -> "dict[str, str]":
        """작성 출처 지문(#53-C) — 순수 설명 메타(실행 경로 무영향, 실행 게이트는 여전히
        라이브 검증). 최초 작성시각(authored_at)은 편집 재저장에도 보존하고 updated_at 만
        갱신한다(태그·이력 보존 선례). 템플릿/데이터 스키마 지문은 ' · ' 결합 필드명."""
        now = datetime.now().isoformat(timespec="seconds")
        created = self._loaded_provenance.get("authored_at") or now
        prov: "dict[str, str]" = {
            "template": self.template_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "authored_at": created,
            "updated_at": now,
        }
        if self.schema is not None:
            prov["template_fields"] = " · ".join(self.schema.field_names())
        src = profile_source_vocabulary(profile)
        if src:
            prov["source_keys"] = " · ".join(src)
        # 데이터 표시명: 이번에 데이터를 골랐으면 그 이름, 아니면(편집 저장) 복원한 출처 보존.
        dataset = self.dataset_name if self.data_path else self._loaded_provenance.get("dataset", "")
        if dataset:
            prov["dataset"] = dataset
        return prov

    def _sample_rows(self) -> "list[list[str]]":
        """2단계 미리보기용 샘플 행 — source_fields 순서로 투영한 문자열 셀.

        빈 셀은 ``""`` 로 남겨 렌더가 "(빈 값)"으로 시끄럽게 표기하게 한다(ADR-B).
        """
        return [
            ["" if (v := rec.get(col)) is None else str(v) for col in self.source_fields]
            for rec in self.records[:_SAMPLE_ROWS]
        ]

    def _gate_snapshot(self) -> "dict | None":
        g = self.gate
        if g is None or not g.needs_gate():
            return None
        return {
            "message": g.message(),
            "unmet": list(g.unmet_tokens),
            "acked": g.is_acked(),
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 세션 수명주기(confirm-or-alarm)
    def has_unsaved_work(self) -> bool:
        """진행 중인 작업 세션이 있는가 — 폐기 전 확인 판단에 쓴다(#25).

        ``_reset()`` 직후(방금 저장 포함)엔 False. 이름·데이터·매핑 모델 중 하나라도
        있으면 사용자가 손댄 세션이므로 True — 템플릿만 갓 로드한 상태(모델 전)는 아직
        버릴 게 없어 False(불필요한 프롬프트 억제).
        """
        return bool(self.job_name or self.data_path or self.model is not None)

    def new_job_session(self, path: str) -> None:
        """새 작업 세션을 원자적으로 시작 — 이전 세션 전량 초기화 후 템플릿 로드(#25).

        템플릿→에디터 진입(템플릿 관리 '작업 만들기', 에디터 0단계 피커)의 단일 seam.
        ``load_template_path`` 만 부르면 이름·데이터·매핑·단계가 이전 세션 값으로 남아
        새 템플릿과 섞인 혼합 세션이 조용히 저장될 수 있다 — 여기서 ``_reset()`` 로
        먼저 끊는다. 미저장 확인은 호출측(브리지/웹)이 ``has_unsaved_work`` 로 선판단한다.
        """
        self._reset()
        self.load_template_path(path)

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_template_path(self, path: str) -> None:
        """선택된 .hwpx 를 로드 — 스키마 추출 + PARTIAL 게이트 계산(Qt 위저드 _load_template 미러)."""
        self.template_path = path
        self.gate = None
        self.gate_error = False
        self.raw_block = ""
        self.schema = extract_schema(path)
        if not self.schema.fields:  # RAW: 채울 대상 없음 — 시끄럽게 차단.
            self.raw_block = RAW_BLOCK_MESSAGE
            self.schema = None
            self._push()
            return
        try:
            self.gate = gate_for_template(path)
        except Exception:  # noqa: BLE001  fail-closed(진행 차단)
            self.gate_error = True
        self._push()

    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 데이터 파일 로드. ``sheet`` = 웹에서 확정한 시트명(다중 시트 게이트 #33,
        None = CSV·단일 시트라 물을 것이 없는 경우)."""
        source = source_for_path(path, sheet=sheet)
        records = source.records()
        if not records:
            raise ValueError("레코드 0건 — 데이터를 바꾸지 않았습니다.")
        self.data_path = path
        self.data_sheet = sheet or ""  # 자동등록 참조에 확정 시트 동봉(#26 — 모호 참조 방지)
        self.source_fields = source.fields()
        # 새 데이터 = 새 헤더 어휘 → 이전 미사용 선택이 조용히 남지 않게 전원 활성으로.
        self._ignored_sources = set()
        self.records = records
        self.preview_index = 0
        # 자동등록 기본 이름 = 파일 스템(사용자가 4단계에서 수정 가능). 데이터를 바꾸면
        # 이전 파일 이름이 조용히 남지 않게 매번 재유도한다.
        self.dataset_name = Path(path).stem
        self._push()

    # ------------------------------------------------------- 편집 모드(#26 #1)
    def load_job(self, name: str) -> None:
        """저장된 작업을 편집 세션으로 복원 — 4단계 상태 재구성(단순 배선 아님).

        복원 경로: ``load_template_path``(스키마·게이트) → ``from_suggestions`` 초안 →
        ``apply_profile``(저장 매핑을 확정 상태로) → ``_model_key`` 정합 세팅(단계 이동이
        복원 모델을 초안으로 재생성하는 함정 봉쇄). ``from_profile`` 단독은 템플릿-무
        모델(schema=None)이라 마법사가 돌지 않는다 — 쓰지 않는다.

        confirm-or-alarm:
        - 작업 손상·템플릿 부재·RAW·게이트 오류는 loud raise(브리지가 ``ERROR:`` 재진술).
        - 템플릿 드리프트(저장 매핑에 있는데 현 스키마에 없는 필드)는 ``apply_profile`` 이
          조용히 누락시키므로 여기서 세어 notice 로 재진술한다.
        - 태그·마지막 실행 메타는 보존해 편집 저장이 조용히 소실시키지 않는다.
        """
        job = self.registry.load(name)  # 부재·손상 → loud raise
        if not Path(job.template_path).exists():
            raise ValueError(
                f"템플릿 파일을 찾을 수 없습니다: {job.template_path}\n"
                "템플릿을 옮겼거나 지웠으면 파일을 되돌리거나, 실행/홈 화면의 "
                "[템플릿 다시 연결…]로 경로를 바꿔 주세요."
            )
        self._reset()
        self.load_template_path(job.template_path)
        if self.schema is None:  # RAW — 채울 필드가 없어 매핑 편집이 성립하지 않는다.
            raise ValueError(RAW_BLOCK_MESSAGE)
        if self.gate_error:
            raise ValueError("템플릿 상태를 확인할 수 없습니다 — 편집을 열 수 없습니다.")
        self.job_name = job.name
        self.pattern = job.filename_pattern
        self._editing_origin = job.name
        self._preserved_tags = dict(job.tags)
        self._preserved_last_run = job.last_run_at
        # 로드 시점 내용 지문 — 자기-갱신 저장 시 편집 중 외부 변경(같은 이름 작업 교체)을
        # 무확인으로 덮지 않기 위한 대조 기준(_do_save).
        self._editing_fingerprint = _job_content_fingerprint(job)
        self._base_name = job.base_mapping_name
        self._loaded_provenance = dict(job.mapping.provenance)  # 작성 출처 표시(#53-C)
        self.default_dataset_ref = job.default_dataset_ref  # 편집 저장 시 보존(#53-A)
        # 소스 어휘 = 저장 매핑이 참조하는 키 합집합(profile_source_vocabulary 단일 출처,
        # from_profile 과 공유) — 데이터 없이도 복원된 source 가 선택지에 있어야 드롭다운이
        # (비움)으로 오표시되지 않는다.
        self.source_fields = profile_source_vocabulary(job.mapping)
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
        applied = self.model.apply_profile(job.mapping)
        self._model_key = (self.template_path, self.data_path, tuple(self.source_fields))
        self.step = 2  # 매핑 확정 단계로 — 저장까지 사람 재검토를 거친다.
        row_fields = {r.template_field for r in self.model.rows}
        dropped = [
            m.template_field for m in job.mapping.mappings
            if m.template_field not in row_fields
        ]
        fresh = [r.template_field for r in self.model.rows if not r.confirmed]
        notice = f"작업 '{job.name}' 을 편집 모드로 열었습니다 — 매핑 {applied}개 행 복원."
        if dropped:
            notice += (
                f"\n템플릿에 더는 없는 저장 필드 {len(dropped)}개는 제외했습니다: "
                + ", ".join(dropped)
            )
        if fresh:
            notice += (
                f"\n템플릿에 새로 생긴 필드 {len(fresh)}개는 확정이 필요합니다: "
                + ", ".join(fresh)
            )
        self._set_notice(notice, "warn" if (dropped or fresh) else "ok")
        self._push()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 editor 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    # ---- 마법사 이동
    def _do_goto_step(self, p: dict) -> None:
        target = int(p["step"])
        if target > self.step:  # 전진은 게이트 통과 필요(각 중간 단계).
            for s in range(self.step, target):
                if not self.can_advance(s):
                    raise ValueError(f"{s}단계 게이트 미통과 — 진행할 수 없습니다.")
        if target == 2:
            self._ensure_model()
        self.step = max(0, min(3, target))

    def _do_ack_gate(self, p: dict) -> None:
        """PARTIAL 게이트 명시 확인 — 재진술된 미해결 토큰 전체를 확인(ADR-E)."""
        if self.gate is None:
            raise ValueError("확인할 게이트가 없습니다.")
        self.gate.acknowledge(self.gate.unmet_tokens)

    def _do_skip_data(self, p: dict) -> None:
        """데이터 없이 매핑으로(스키마온리) — 선택적 데이터 단계 건너뛰기."""
        self.data_path = ""
        self.data_sheet = ""
        self.dataset_name = ""
        self.source_fields = []
        self._ignored_sources = set()
        self.records = []
        self.preview_index = 0
        self._ensure_model()
        self.step = 2

    # ---- 사용 헤더 선택(#49) — 활성/미사용 전환. 원본 데이터·매핑 계약은 불변.
    def _do_use_only_selected(self, p: dict) -> None:
        """선택한 헤더만 활성으로, 나머지 일괄 미사용(#49)."""
        selected = {str(f) for f in (p.get("fields") or [])}
        self._apply_active(selected)

    def _do_use_all_headers(self, p: dict) -> None:
        """전체 헤더를 다시 활성으로 — 미사용 일괄 해제(#49)."""
        self._apply_active(set(self.source_fields))

    def _do_toggle_source_active(self, p: dict) -> None:
        """헤더 1개의 활성/미사용 토글(개별 재활성 포함, #49)."""
        field = str(p["field"])
        active = set(self._active_sources())
        if field in active:
            active.discard(field)
        else:
            active.add(field)
        self._apply_active(active)

    def _apply_active(self, active: "set[str]") -> None:
        """활성 헤더 집합을 확정한다 — 데이터에 있는 것만 채택하고, 새로 미사용이 된
        헤더에 매핑된 행은 해제(``ignore_source``)해 사람 재검토를 강제·재진술한다.

        confirm-or-alarm: **전부 미사용은 시끄럽게 거부**한다. 헤더 한 개 미사용은 강제
        재확정이 안전장치이지만, 전부 미사용은 확정 매핑 전 행을 한 번에 해제하고 '모두
        사용'으로도 지워진 행이 복구되지 않는(후보 자격만 되돌림) 되돌리기 불가 파괴다 —
        되돌릴 수 없는 파괴는 사후 통보가 아니라 사전 차단이 맞다(리뷰 #62 🔴)."""
        active = {f for f in active if f in self.source_fields}
        if self.source_fields and not active:
            raise ValueError(
                "사용할 헤더를 하나 이상 남겨 두세요 — 전부 미사용은 확정한 매핑을 "
                "모두 해제하며 되돌릴 수 없습니다."
            )
        new_ignored = {f for f in self.source_fields if f not in active}
        newly_ignored = new_ignored - self._ignored_sources
        self._ignored_sources = new_ignored
        affected: "list[str]" = []
        if self.model is not None:
            for f in sorted(newly_ignored):
                affected += self.model.ignore_source(f)
        n_active = len(self._active_sources())
        n_ignored = len(self._ignored_sources)
        msg = f"사용 헤더 {n_active}개 · 미사용 {n_ignored}개."
        if affected:
            self._set_notice(
                msg + f"\n미사용으로 바꾸며 매핑을 해제한 필드 {len(affected)}개"
                "(재확정 필요): " + ", ".join(affected),
                "warn",
            )
        else:
            self._set_notice(msg, "muted")

    def _ensure_model(self) -> None:
        """매핑 진입 시 초안 생성 — 키(템플릿·데이터·소스) 불변이면 그대로, 바뀌면
        **전원 미확정 초안으로 재생성**하되 이전 확정 행의 값(소스·유형·상수·서식)은
        제안으로 이월한다(#26 UX 유지 + 확정 불변식 복원).

        불변식: 템플릿/데이터 키가 바뀌면 어떤 행도 확정 상태로 도착하지 않는다. 한때
        이전 확정을 ``apply_profile`` 로 확정 상태 그대로 되살렸는데 — 같은 이름 컬럼
        ('금액' 등)이 의미가 다른 새 데이터에서 사람 검토 없이 확정으로 도착해
        ``is_complete`` 를 통과, 저장·실행까지 흐르는 조용한 게이트 우회였다. 지금은
        값만 이월하고 확정은 전원 해제(``confirm=False``), 재확정 필요를 notice 로
        시끄럽게 재진술한다(조용한 소실도, 조용한 승계도 금지).

        키(#49 주의): 키는 **전체** ``source_fields`` 만 담고 미사용 집합은 담지 않는다 —
        의도된 설계다. 매핑 진입 후 헤더를 재활성해도 모델이 재생성되지 않아 그 헤더는
        자동 제안을 다시 받지 못하고 수동 선택만 가능하다. 대신 이미 확정한 매핑을 재활성
        토글이 날리지 않는다(재생성=전원 미확정). 자동제안 재수확 < 확정 보존이라 이 쪽을
        택한다(버그 아님).
        """
        if self.schema is None:
            raise ValueError("템플릿이 로드되지 않았습니다.")
        key = (self.template_path, self.data_path, tuple(self.source_fields))
        if self.model is not None and self._model_key == key:
            return
        prior = None
        if self.model is not None and self.model.confirmed_count():
            prior = self.model.to_profile()
        # 미사용 헤더(#49)는 자동 제안 후보에서 제외 — 매핑 진입 전 좁혀두면 여기서
        # 반영된다(진입 후 좁히면 _apply_active 가 ignore_source 로 행을 해제).
        self.model = MappingModel.from_suggestions(self.schema, self._active_sources())
        if prior is not None:
            carried = self.model.apply_profile(prior, confirm=False)
            self._set_notice(
                f"템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다 — 이전에 확정했던 "
                f"{carried}개 행의 소스·유형·서식은 제안으로 이월했지만 전 행이 미확정입니다.\n"
                "같은 이름 컬럼이라도 새 데이터에서는 의미가 다를 수 있습니다 — "
                "저장하려면 전 행을 다시 확정하세요.",
                "warn",
            )
        self._model_key = key

    # ---- 매핑 행 편집(모두 편집=확정 해제, VM 이 처리)
    def _do_set_source(self, p: dict) -> None:
        self.model.set_source(int(p["index"]), p["source"])

    def _do_set_type(self, p: dict) -> None:
        self.model.set_type(int(p["index"]), p["type"])

    def _do_set_fmt(self, p: dict) -> None:
        self.model.set_fmt(int(p["index"]), p["fmt"])

    def _do_set_const(self, p: dict) -> None:
        self.model.set_const(int(p["index"]), p["const"])

    def _do_set_confirmed(self, p: dict) -> None:
        self.model.set_confirmed(int(p["index"]), bool(p["confirmed"]))

    def _do_confirm_all(self, p: dict) -> dict:
        """고신뢰(내용 있는) 행 즉시 확정 + 비움 승격 후보 이름 반환(ADR-E 이름게이트)."""
        self.model.confirm_content_rows()
        return {"blanks": self.model.unconfirmed_blank_fields()}

    def _do_confirm_blanks(self, p: dict) -> None:
        """재진술·확인된 미매칭 행을 의도적 비움으로 확정."""
        self.model.confirm_fields(list(p.get("fields", [])))

    def _do_unconfirm_all(self, p: dict) -> None:
        self.model.unconfirm_all()

    def _do_step_preview(self, p: dict) -> None:
        if self.records:
            self.preview_index = (self.preview_index + int(p["delta"])) % len(self.records)

    # ---- 저장
    def _do_set_name(self, p: dict) -> None:
        self.job_name = p["name"]

    def _do_set_pattern(self, p: dict) -> None:
        self.pattern = p["pattern"]

    def _do_set_dataset_name(self, p: dict) -> None:
        """자동등록 데이터셋 이름 수정(4단계) — 기본은 데이터 파일 스템."""
        self.dataset_name = p["name"]

    def _dataset_gate(self, p: dict) -> "dict | None":
        """선언 데이터 자동등록 선차단 게이트(#18 31A5A484-C·ST-09 사각 봉합).

        저장 **전에** 판정해 반저장 상태(작업은 저장·등록은 실패)를 만들지 않는다.
        분류(부재/동명/충돌/손상)는 :func:`~hwpxfiller.core.job.classify_existing` 단일
        출처(pool 수동 등록·프로파일 저장과 공유):
        - 같은 이름 기존 항목: guard 는 자기-갱신으로 통과시켜 **조용한 opts 덮어쓰기**가
          되므로 여기서 확인을 승격한다(기존 참조 요약 재진술 → ``confirm_dataset``).
        - 다른 이름·같은 slug(또는 손상): 덮어쓰기 경로를 열지 않고 이름 변경만 안내.
        통과(None 반환) 후의 실제 등록은 ``_do_save`` 말미가 수행한다 — 게이트가 로드한
        동명 기존 항목은 ``self._dataset_existing`` 에 stash 해 등록이 같은 파일을
        재로드·재판정하지 않는다(중복 파싱 + 게이트/저장 사이 판정 표류 제거).
        """
        ds_name = (self.dataset_name or "").strip() or Path(self.data_path).stem
        self.dataset_name = ds_name
        kind, existing = classify_existing(self.pool_registry, ds_name)
        self._dataset_existing = existing if kind == "same" else None
        if kind == "absent":
            return None
        if kind == "corrupt":
            return {
                "ok": False,
                "dataset_error": (
                    f"등록 데이터 '{ds_name}' 자리의 기존 파일이 손상돼 확인할 수 "
                    "없습니다 — 다른 이름을 지정하세요."
                ),
            }
        if kind == "collision":  # slug 충돌(다른 이름·같은 파일) — 이름 변경만
            return {
                "ok": False,
                "dataset_error": (
                    f"'{ds_name}' 은 기존 등록 데이터 '{existing.name}' 과 같은 파일로 "
                    f"저장됩니다 — 다른 이름을 지정하세요."
                ),
            }
        if not p.get("confirm_dataset"):  # kind == "same" — 확인 승격
            return {
                "ok": False,
                "needs_dataset_confirm": True,
                "dataset_name": ds_name,
                # cross-kind(나라/파이프라인→엑셀) 전이는 _do_save 확정 경로가 kind 를
                # excel 로 정규화하므로 여기서 함께 재진술한다(r4 — pool 화면 미러).
                "dataset_text": (
                    f"등록 데이터 '{ds_name}' 이 이미 있습니다"
                    f"({reference_summary(existing)}).\n"
                    "이 작업의 데이터 참조로 덮어씁니다"
                    f"{kind_transition_clause(existing)} — 계속할까요?"
                ),
            }
        return None

    def _editing_drift_text(self) -> str:
        """자기-갱신 저장 전 외부 변경 판정 — 확인이 필요하면 재진술 문구, 아니면 "".

        편집 세션이 열린 사이 같은 이름 작업이 밖에서 교체됐으면(내용 지문 불일치)
        자기-갱신이라도 무확인 덮어쓰기가 파괴가 된다 — 확인을 승격한다. 태그·마지막
        실행만의 변경은 지문에서 제외돼 걸리지 않는다(저장이 어차피 디스크 값을 보존).
        원점 파일이 삭제됐으면 덮을 기존 내용이 없어 확인 불요(저장이 재생성).
        """
        if not self.registry.exists(self._editing_origin):
            return ""
        try:
            current = self.registry.load(self._editing_origin)
        except Exception:  # noqa: BLE001 — 손상: 내용 불명, 조용히 덮지 않는다
            return (
                f"작업 '{self._editing_origin}' 파일이 편집을 여는 사이 손상돼 현재 "
                "내용을 확인할 수 없습니다.\n지금 저장하면 그 자리를 이 편집 세션의 "
                "상태로 덮어씁니다."
            )
        if _job_content_fingerprint(current) != self._editing_fingerprint:
            return (
                f"편집 중 외부 변경: 작업 '{self._editing_origin}' 이 이 편집 세션을 "
                "여는 사이 다른 곳에서 바뀌었습니다.\n지금 저장하면 그 변경 내용을 "
                "이 편집 세션의 상태로 덮어씁니다."
            )
        return ""

    def _do_save(self, p: dict) -> dict:
        """저장 게이트 → 덮어쓰기 확인 → 자동등록 게이트 → 저장·등록. 결과 dict 로 재진술.

        웹은 ``needs_overwrite`` / ``needs_dataset_confirm`` 이면 재진술 확인 후 해당
        플래그(``confirm_overwrite``/``confirm_dataset``)를 실어 재호출한다.

        편집 모드(#26): 원점 이름 그대로의 재저장은 자기-갱신이라 **디스크가 로드 시점
        그대로일 때만** 덮어쓰기 확인을 묻지 않는다(레지스트리 가드의 '같은 이름 재저장
        통과' 철학 미러). 편집 사이 외부에서 같은 이름 작업이 교체됐으면 '편집 중 외부
        변경' 확인을 승격한다(무확인 파괴 금지). 이름을 바꿔 다른 작업을 덮으려는 경우는
        평소처럼 확인을 요구한다. 태그·마지막 실행 메타는 보존.
        """
        verdict = validate_save(self.model, self.job_name, self.pattern, schema=self.schema)
        if not verdict.ok:
            return {"ok": False, "block_reason": verdict.block_reason}
        exists = self.registry.exists(self.job_name)
        self_update = bool(self._editing_origin) and self.job_name == self._editing_origin
        if self_update and not p.get("confirm_overwrite"):
            drift = self._editing_drift_text()
            if drift:
                return {"ok": False, "needs_overwrite": True, "overwrite_text": drift}
        if (
            not self_update
            and needs_overwrite_confirm(self.job_name, None, exists)
            and not p.get("confirm_overwrite")
        ):
            victim = ""
            try:
                victim = self.registry.load(self.job_name).name
            except Exception:  # noqa: BLE001  손상 파일 → 이름 불명(추측 금지)
                victim = ""
            return {
                "ok": False,
                "needs_overwrite": True,
                "overwrite_text": overwrite_confirm_text(self.job_name, victim),
            }
        if self.data_path:  # 선언 데이터 자동등록 게이트 — 저장 전 선차단(#26)
            blocked = self._dataset_gate(p)
            if blocked is not None:
                return blocked
        # 태그·마지막 실행 메타는 편집 세션 밖(홈 태그 편집 등)에서 바뀌었을 수 있어
        # load_job 시점 스냅샷이 아니라 저장 직전 디스크 상태를 다시 읽어 보존한다 — 편집
        # 세션이 열린 사이 홈에서 단 태그를 조용히 되돌리지 않는다(#26 confirm-or-alarm).
        preserved_tags = dict(self._preserved_tags)
        preserved_last_run = self._preserved_last_run
        if self._editing_origin:
            try:
                current = self.registry.load(self._editing_origin)
                preserved_tags = dict(current.tags)
                preserved_last_run = current.last_run_at
            except Exception:  # noqa: BLE001 — 원본이 사라졌으면 스냅샷 유지(추측 없음)
                pass
        # 작성 출처 지문(#53-C) — 순수 설명 메타(실행 경로 무영향). 저장 매핑에 새긴다.
        verdict.profile.provenance = self._build_provenance(verdict.profile)
        # 기본 데이터셋 참조(#53-A): 이 세션이 데이터를 골랐으면 곧 자동등록될 이름과 연결,
        # 아니면(편집 저장 등 데이터 미변경) 복원한 참조를 보존. 등록 실패해도 참조 이름은
        # 안정적이라 사용자가 그 이름으로 수동 등록하면 링크가 완성된다.
        default_dataset_ref = self.dataset_name if self.data_path else self.default_dataset_ref
        job = Job(
            name=self.job_name,
            template_path=self.template_path,
            mapping=verdict.profile,
            filename_pattern=self.pattern,
            last_run_at=preserved_last_run,
            base_mapping_name=self._base_name,
            tags=preserved_tags,
            default_dataset_ref=default_dataset_ref,
        )
        # 위 게이트(needs_overwrite_confirm→confirm_overwrite)가 victim 을 재진술 확인시킨 뒤라
        # slug 충돌이어도 사용자가 확정한 상태 → core 가드에 명시적 opt-in 을 통과한다.
        self.registry.save(job, allow_overwrite=True)
        registered = ""
        register_error = ""
        if self.data_path:
            # 참조만 저장(행·비밀 없음) — 확정 시트 동봉(모호 참조 방지). 게이트를 통과한
            # 뒤라(동명=확인됨·충돌=차단됨) opt-in 저장.
            opts: "dict[str, object]" = {"path": self.data_path}
            if self.data_sheet:
                opts["sheet"] = self.data_sheet
            # 기존 동명 항목(_dataset_gate 가 이번 호출에서 분류·stash — 재로드·재판정 없음)
            # 이 있으면 상태(보관)·메모·생성시각을 보존하고 참조(opts)만 갱신한다 —
            # 새 항목으로 통째 갈아치우면 보관해 둔 데이터셋이 조용히 재활성화되고 메모가
            # 지워진다(durable 수명 상태 소실). 확인 문구가 참조 덮어쓰기만 재진술하므로
            # 상태/메모는 건드리지 않는 것이 문구와도 일치한다(#26 confirm-or-alarm).
            # 등록 실패는 여기서 잡아 '작업 저장 성공 + 등록 실패' 반저장 상태를 결과에
            # 정직하게 재진술한다 — 예외가 dispatch 밖으로 새면 웹이 무반응 반저장이 된다.
            try:
                existing = self._dataset_existing
                if existing is not None:
                    # kind 도 excel 로 정규화(r4) — opts 만 갈아끼우면 동명 nara/pipeline
                    # 항목이 kind=nara + opts={path} 하이브리드로 손상돼 겨눔 시 동결
                    # 거절·요약 "기간 ?~?" 가 된다(update_excel_reference 미러).
                    existing.kind = "excel"
                    existing.opts = opts
                    self.pool_registry.save(existing, allow_overwrite=True)
                else:
                    self.pool_registry.save(
                        DatasetPoolItem(name=self.dataset_name, kind="excel", opts=opts),
                        allow_overwrite=True,
                    )
                registered = self.dataset_name
            except Exception as exc:  # noqa: BLE001 — 반저장을 조용히 삼키지 않는다
                register_error = (
                    f"작업 '{self.job_name}' 은 저장됐지만 등록 데이터 "
                    f"'{self.dataset_name}' 등록에 실패했습니다: {exc} — "
                    f"이 작업은 '{self.dataset_name}' 을 기본 데이터로 연결해 뒀으니, "
                    "데이터 관리 화면에서 같은 이름으로 등록하면 연결이 완성됩니다(#53-A)."
                )
        saved = self.job_name
        self._reset()  # 저장 후 새 작업 준비(에디터 초기화)
        result = {"ok": True, "saved_name": saved, "dataset_registered": registered}
        if register_error:
            result["dataset_register_error"] = register_error
        return result

    # ---- 매핑 베이스 프로파일(#26 #5 — ADR J 축2)
    def _base_ref_counts(self) -> "dict[str, int]":
        """베이스 이름 → 참조 작업 수(잡 1회 스캔) — 전파·삭제 경고 수치의 단일 출처.

        한때 같은 ``sum(1 for j in registry.list_jobs() ...)`` 스캔이 목록/저장/삭제에
        3중 복붙돼 있었다 — 여기로 수렴한다(K6).
        """
        refs: "dict[str, int]" = {}
        for j in self.registry.list_jobs():
            if j.base_mapping_name:
                refs[j.base_mapping_name] = refs.get(j.base_mapping_name, 0) + 1
        return refs

    def _base_refs(self, name: str) -> int:
        """베이스 ``name`` 을 참조하는 작업 수 — 덮어쓰기/삭제 확인 문구의 근거."""
        return self._base_ref_counts().get(name, 0)

    def _do_profile_list(self, p: dict) -> dict:
        """베이스 목록 + 각 베이스를 참조하는 작업 수(loud 전파 경고의 근거).

        손상 베이스 파일은 격리 수집해 함께 재진술한다(조용한 은닉 금지 — RC-05 미러).
        """
        corrupted: "list[tuple[Path, str]]" = []
        bases = self.base_registry.list_bases(corrupted=corrupted)
        refs = self._base_ref_counts()
        return {
            "bases": [
                {
                    "name": b.name,
                    "field_count": len(b.mappings),
                    "job_refs": refs.get(b.name, 0),
                }
                for b in bases
            ],
            "corrupted": [
                {"file": path.name, "error": err} for path, err in corrupted
            ],
        }

    def _do_profile_apply(self, p: dict) -> dict:
        """베이스를 현재 매핑에 반영 — 일치 필드는 확정 도착, 스키마 밖 필드는 세어 재진술.

        ``apply_profile`` 은 스키마에 없는 베이스 필드를 조용히 누락시키므로(드리프트)
        여기서 dropped 로 세어 웹이 재진술한다. ``require_source=True``: 현재 데이터에
        없는 소스를 겨눈 베이스 행은 확정으로 도착시키지 않는다 — 확정 도착이 그대로
        ``is_complete`` 를 통과해 실행 시 전 레코드 빈 값을 찍는 함정 봉쇄. 그런 필드는
        ``missing_source`` 로 세어 시끄럽게 재진술한다(미확정 = 사람 재확정 강제).
        반영 성공 시 이 세션의 베이스 계보를 갱신한다(J3 — ``base_mapping_name``).
        """
        if self.model is None:
            self._ensure_model()
        name = p["name"]
        try:
            base = self.base_registry.load(name)
        except Exception as exc:  # noqa: BLE001 — 부재·손상: 웹에 문구로 loud
            return {"ok": False, "error": f"매핑 프로파일을 불러올 수 없습니다: {exc}"}
        applied = self.model.apply_profile(base, require_source=True)
        row_fields = {r.template_field for r in self.model.rows}
        dropped = [
            m.template_field for m in base.mappings if m.template_field not in row_fields
        ]
        available = set(self.source_fields)
        missing_source = [
            m.template_field
            for m in base.mappings
            if m.template_field in row_fields
            and not m.is_blank and m.source and m.source not in available
        ]
        self._base_name = name
        notice = f"매핑 프로파일 '{name}' 반영 — {applied}개 행 확정 도착."
        if missing_source:
            notice += (
                f"\n현재 데이터에 없는 소스를 참조하는 필드 {len(missing_source)}개는 "
                "미확정으로 남았습니다(재확정 필요): " + ", ".join(missing_source)
            )
        if dropped:
            notice += (
                f"\n이 템플릿에 없는 프로파일 필드 {len(dropped)}개는 제외했습니다: "
                + ", ".join(dropped)
            )
        self._set_notice(notice, "warn" if (dropped or missing_source) else "ok")
        return {
            "ok": True,
            "applied": applied,
            "dropped": dropped,
            "missing_source": missing_source,
        }

    def _do_profile_save(self, p: dict) -> dict:
        """확정 행을 명명 베이스로 저장 — 동명 덮어쓰기는 참조 작업 수와 함께 확인 승격.

        베이스는 사람 확정 산출물이므로 확정 행이 없으면 저장을 거부한다. 부분 확정
        상태의 저장은 허용된다(sparse 베이스 — ADR J '변경 행만 덮는' 오버레이 설계).
        """
        name = (p.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "프로파일 이름을 입력하세요."}
        if self.model is None or not self.model.confirmed_count():
            return {"ok": False, "error": "확정된 매핑 행이 없습니다 — 행을 확정한 뒤 저장하세요."}
        # 분류(부재/동명/충돌/손상)는 classify_existing 단일 출처 — slug 는 비단사라
        # exists(name) 만으론 **다른 이름·같은 파일**(충돌)을 동명으로 오인해 confirm 후
        # 덮어써 파괴한다(_dataset_gate·pool 수동 등록과 같은 사다리). 충돌·손상은 confirm
        # 플래그와 무관하게 차단(이름 변경만 안내), 진짜 동명만 확인 승격.
        kind, existing = classify_existing(self.base_registry, name)
        if kind == "corrupt":
            return {
                "ok": False,
                "error": (
                    f"'{name}' 자리의 기존 프로파일 파일이 손상돼 확인할 수 없습니다 "
                    "— 다른 이름을 지정하세요."
                ),
            }
        if kind == "collision":  # 다른 이름·같은 slug — 덮어쓰기 경로 없이 이름 변경만
            return {
                "ok": False,
                "error": (
                    f"'{name}' 은 기존 매핑 프로파일 '{existing.name}' 과 같은 파일로 "
                    "저장됩니다 — 다른 이름을 지정하세요."
                ),
            }
        if kind == "same" and not p.get("confirm"):
            refs = self._base_refs(name)
            warn = (
                f"\n이 프로파일을 참조하는 작업이 {refs}개 있습니다 — "
                "오버레이 없는 행이 바뀝니다." if refs else ""
            )
            return {
                "ok": False,
                "needs_confirm": True,
                "confirm_text": (
                    f"매핑 프로파일 '{name}' 이 이미 있습니다.{warn}\n덮어쓸까요?"
                ),
            }
        profile = self.model.to_profile(name)
        try:
            self.base_registry.save(profile, allow_overwrite=bool(p.get("confirm")))
        except SlugCollisionError as exc:  # 다른 이름·같은 파일 — 이름 변경 안내
            return {"ok": False, "error": str(exc)}
        self._base_name = name
        self._set_notice(
            f"매핑 프로파일 '{name}' 저장 — 확정 {len(profile.mappings)}개 행.", "ok"
        )
        return {"ok": True, "saved": name, "rows": len(profile.mappings)}

    def _do_profile_delete(self, p: dict) -> dict:
        """베이스 삭제 — 파괴이므로 확인 라운드트립 + 참조 작업 수 재진술."""
        name = p["name"]
        if not p.get("confirm"):
            refs = self._base_refs(name)
            warn = (
                f"\n이 프로파일을 참조하는 작업이 {refs}개 있습니다"
                "(작업 자체는 남지만 계보가 끊깁니다)." if refs else ""
            )
            return {
                "ok": False,
                "needs_confirm": True,
                "confirm_text": f"매핑 프로파일 '{name}' 을 삭제합니다.{warn}\n계속할까요?",
            }
        self.base_registry.delete(name)
        self._set_notice(f"매핑 프로파일 '{name}' 삭제됨.", "ok")
        return {"ok": True}
