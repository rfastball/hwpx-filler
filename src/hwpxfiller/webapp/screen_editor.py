"""작업 에디터(HWPX) 화면 컨트롤러 — 4단계 마법사 오케스트레이션(webview 비의존).

목업 scr-editor 의 웹 이관(에픽 #20, 화면 #15·#16). 링1 VM 을 **그대로 임포트**해 구동한다:
매핑은 :class:`~hwpxfiller.gui.mapping_state.MappingModel`, PARTIAL 게이트는
:class:`~hwpxfiller.gui.mapping_state.PartialGate`, 저장 게이트는
:func:`~hwpxfiller.gui.job_editor_state.validate_save`. 이들은 Qt-free 라 그대로 산다
(스파이크 Q1 배당금). 표현 계층(단계 UI·행 색·표시형)만 웹으로 이식한다.

**단계**: 0 템플릿 → 1 데이터(선택) → 2 매핑 확정 → 3 저장. 진행 게이트는 Qt 위저드와 동일:
0→1 은 스키마 有+게이트 통과, 1→2 은 무조건(데이터 선택적, ADR-J), 2→3 은 ``is_complete()``.

**이번 이관의 스코프 경계(조용히 빠뜨리지 않고 명시)** — 아래는 이 커밋에서 미구현이며
후속 이관 대상이다(confirm-or-alarm: 없는 기능을 있는 척하지 않는다):
- 편집 모드(기존 Job 로드)·태그 분류(D12)·데이터풀 자동등록·매핑 베이스 프로파일 적용/저장.
- 인라인 누름틀 변환(fieldize).
RAW 차단·PARTIAL 게이트·의도적 비움 이름게이트·저장 게이트·덮어쓰기 확인·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

from ..core.format_engine import presets as format_presets
from ..core.job import DEFAULT_FILENAME_PATTERN, Job, JobRegistry
from ..core.mapping import TYPES
from ..core.schema import extract_schema
from ..data import source_for_path
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
)
from .screens import PushSink

# 표시형 프리셋은 유형별 고정 → 한 번 계산해 스냅샷에 싣는다(코어 라벨 그대로).
_FMT_OPTIONS = {t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES}


class EditorController:
    """작업 에디터 화면 — 마법사 세션 상태 소유·링1 VM 위임."""

    name = "editor"

    def __init__(self, registry: JobRegistry, push: PushSink) -> None:
        self.registry = registry
        self._push_sink = push
        self._reset()

    def _reset(self) -> None:
        self.step = 0
        self.template_path = ""
        self.schema = None
        self.gate: "PartialGate | None" = None
        self.gate_error = False
        self.raw_block = ""
        self.data_path = ""
        self.source_fields: "list[str]" = []
        self.records: "list[dict]" = []
        self.model: "MappingModel | None" = None
        self._model_key: "tuple | None" = None
        self.preview_index = 0
        self.job_name = ""
        self.pattern = DEFAULT_FILENAME_PATTERN

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
        snap: dict = {
            "step": self.step,
            "reachable": [self.can_advance(s) for s in range(3)],  # 0→1,1→2,2→3
            "template_path": self.template_path,
            "template_name": self.template_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "field_count": len(self.schema.fields) if self.schema else 0,
            "schema_summary": self._schema_summary(),
            "raw_block": self.raw_block,
            "gate": self._gate_snapshot(),
            "gate_error": self.gate_error,
            "data_path": self.data_path,
            "data_name": self.data_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            "record_count": len(self.records),
            "source_fields": self.source_fields,
            "type_options": list(TYPES),
            "fmt_options": _FMT_OPTIONS,
            "name": self.job_name,
            "pattern": self.pattern,
            "has_unsaved_work": self.has_unsaved_work(),
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
        self.source_fields = source.fields()
        self.records = records
        self.preview_index = 0
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
        self.source_fields = []
        self.records = []
        self.preview_index = 0
        self._ensure_model()
        self.step = 2

    def _ensure_model(self) -> None:
        """매핑 진입 시 초안 생성 — 키(템플릿·데이터·소스) 불변이면 사람 확정 보존."""
        if self.schema is None:
            raise ValueError("템플릿이 로드되지 않았습니다.")
        key = (self.template_path, self.data_path, tuple(self.source_fields))
        if self.model is not None and self._model_key == key:
            return
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
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

    def _do_save(self, p: dict) -> dict:
        """저장 게이트 → 덮어쓰기 확인 → 레지스트리 저장. 결과 dict 로 웹에 재진술.

        웹은 ``needs_overwrite`` 면 재진술 확인 후 ``confirm_overwrite=True`` 로 재호출한다.
        """
        verdict = validate_save(self.model, self.job_name, self.pattern, schema=self.schema)
        if not verdict.ok:
            return {"ok": False, "block_reason": verdict.block_reason}
        exists = self.registry.exists(self.job_name)
        if needs_overwrite_confirm(self.job_name, None, exists) and not p.get("confirm_overwrite"):
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
        job = Job(
            name=self.job_name,
            template_path=self.template_path,
            mapping=verdict.profile,
            filename_pattern=self.pattern,
        )
        # 위 게이트(needs_overwrite_confirm→confirm_overwrite)가 victim 을 재진술 확인시킨 뒤라
        # slug 충돌이어도 사용자가 확정한 상태 → core 가드에 명시적 opt-in 을 통과한다.
        self.registry.save(job, allow_overwrite=True)
        saved = self.job_name
        self._reset()  # 저장 후 새 작업 준비(에디터 초기화)
        return {"ok": True, "saved_name": saved}
