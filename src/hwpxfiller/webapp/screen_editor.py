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

from pathlib import Path

from ..core.dataset_pool import (
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from ..core.format_engine import presets as format_presets
from ..core.job import DEFAULT_FILENAME_PATTERN, Job, JobRegistry, SlugCollisionError
from ..core.mapping import TYPES
from ..core.mapping_base import MappingBaseRegistry, default_mapping_bases_dir
from ..core.schema import extract_schema
from ..data import source_for_path
from ..gui.dataset_pool_state import reference_summary
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
            pool_registry if pool_registry is not None
            else DatasetPoolRegistry(default_dataset_pool_dir())
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
        self.records: "list[dict]" = []
        self.model: "MappingModel | None" = None
        self._model_key: "tuple | None" = None
        self.preview_index = 0
        self.job_name = ""
        self.pattern = DEFAULT_FILENAME_PATTERN
        self.dataset_name = ""  # 자동등록 이름(기본=데이터 파일 스템, 사용자 수정 가능)
        # 편집 모드 상태(#26): 원점 이름(자기-갱신 판정)·보존 메타(태그·마지막 실행) —
        # 편집 저장이 브라우저 태그·이력을 조용히 소실시키지 않는다.
        self._editing_origin = ""
        self._preserved_tags: "dict[str, str]" = {}
        self._preserved_last_run = ""
        self._base_name = ""  # 이 세션 매핑을 시드/저장한 베이스 이름(J3 계보)
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
            # #26 편집 모드·프로파일·자동등록 표면.
            "editing_origin": self._editing_origin,
            "base_name": self._base_name,
            "dataset_name": self.dataset_name,
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
                "템플릿을 옮겼거나 지웠으면 파일을 되돌리거나 새 작업으로 다시 만들어 주세요."
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
        self._base_name = job.base_mapping_name
        # 소스 어휘 = 저장 매핑이 참조하는 키 합집합(from_profile 미러) — 데이터 없이도
        # 복원된 source 가 선택지에 있어야 드롭다운이 (비움)으로 오표시되지 않는다.
        seen: "dict[str, None]" = {}
        for m in job.mapping.mappings:
            if not m.is_blank and m.source:
                seen.setdefault(m.source, None)
        self.source_fields = list(seen)
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
        self.records = []
        self.preview_index = 0
        self._ensure_model()
        self.step = 2

    def _ensure_model(self) -> None:
        """매핑 진입 시 초안 생성 — 키(템플릿·데이터·소스) 불변이면 그대로, 바뀌면 재생성하되
        **사람 확정 행은 보존**한다(#26).

        예전엔 키 불일치 시 무조건 ``from_suggestions`` 초안으로 갈아치웠다 — 확정을 마친 뒤
        1단계로 돌아가 데이터만 바꿔도 확정 전량이 조용히 초안으로 대체되는 함정(편집 모드
        복원 직후엔 복원 자체가 소실). 지금은 확정분을 프로파일로 떠서 새 초안 위에 재적용해
        확정 상태로 되살리고, 무슨 일이 있었는지 notice 로 재진술한다(조용한 소실 금지).
        새 데이터에 없는 소스를 참조하게 된 행은 미리보기 오류/빈 값으로 시끄럽게 드러난다.
        """
        if self.schema is None:
            raise ValueError("템플릿이 로드되지 않았습니다.")
        key = (self.template_path, self.data_path, tuple(self.source_fields))
        if self.model is not None and self._model_key == key:
            return
        prior = None
        if self.model is not None and self.model.confirmed_count():
            prior = self.model.to_profile()
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
        if prior is not None:
            kept = self.model.apply_profile(prior)
            self._set_notice(
                f"데이터가 바뀌어 매핑 초안을 다시 만들었습니다 — "
                f"확정돼 있던 {kept}개 행은 유지했습니다(빈 미리보기는 소스 확인).",
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
        - 같은 이름 기존 항목: guard 는 자기-갱신으로 통과시켜 **조용한 opts 덮어쓰기**가
          되므로 여기서 확인을 승격한다(기존 참조 요약 재진술 → ``confirm_dataset``).
        - 다른 이름·같은 slug(또는 손상): 덮어쓰기 경로를 열지 않고 이름 변경만 안내.
        통과(None 반환) 후의 실제 등록은 ``_do_save`` 말미가 수행한다.
        """
        ds_name = (self.dataset_name or "").strip() or Path(self.data_path).stem
        self.dataset_name = ds_name
        ds_path = self.pool_registry.path_for(ds_name)
        if not ds_path.exists():
            return None
        try:
            existing = DatasetPoolItem.load(ds_path)
        except Exception:  # noqa: BLE001 — 손상: 소유 불명, 조용히 덮지 않는다
            return {
                "ok": False,
                "dataset_error": (
                    f"등록 데이터 '{ds_name}' 자리의 기존 파일이 손상돼 확인할 수 "
                    "없습니다 — 다른 이름을 지정하세요."
                ),
            }
        if existing.name != ds_name:  # slug 충돌(다른 이름·같은 파일) — 이름 변경만
            return {
                "ok": False,
                "dataset_error": (
                    f"'{ds_name}' 은 기존 등록 데이터 '{existing.name}' 과 같은 파일로 "
                    f"저장됩니다 — 다른 이름을 지정하세요."
                ),
            }
        if not p.get("confirm_dataset"):
            return {
                "ok": False,
                "needs_dataset_confirm": True,
                "dataset_name": ds_name,
                "dataset_text": (
                    f"등록 데이터 '{ds_name}' 이 이미 있습니다"
                    f"({reference_summary(existing)}).\n"
                    "이 작업의 데이터 참조로 덮어씁니다 — 계속할까요?"
                ),
            }
        return None

    def _do_save(self, p: dict) -> dict:
        """저장 게이트 → 덮어쓰기 확인 → 자동등록 게이트 → 저장·등록. 결과 dict 로 재진술.

        웹은 ``needs_overwrite`` / ``needs_dataset_confirm`` 이면 재진술 확인 후 해당
        플래그(``confirm_overwrite``/``confirm_dataset``)를 실어 재호출한다.

        편집 모드(#26): 원점 이름 그대로의 재저장은 자기-갱신이라 덮어쓰기 확인을 묻지
        않는다(레지스트리 가드의 '같은 이름 재저장 통과' 철학 미러). 이름을 바꿔 다른
        작업을 덮으려는 경우는 평소처럼 확인을 요구한다. 태그·마지막 실행 메타는 보존.
        """
        verdict = validate_save(self.model, self.job_name, self.pattern, schema=self.schema)
        if not verdict.ok:
            return {"ok": False, "block_reason": verdict.block_reason}
        exists = self.registry.exists(self.job_name)
        self_update = bool(self._editing_origin) and self.job_name == self._editing_origin
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
        job = Job(
            name=self.job_name,
            template_path=self.template_path,
            mapping=verdict.profile,
            filename_pattern=self.pattern,
            last_run_at=self._preserved_last_run,
            base_mapping_name=self._base_name,
            tags=dict(self._preserved_tags),
        )
        # 위 게이트(needs_overwrite_confirm→confirm_overwrite)가 victim 을 재진술 확인시킨 뒤라
        # slug 충돌이어도 사용자가 확정한 상태 → core 가드에 명시적 opt-in 을 통과한다.
        self.registry.save(job, allow_overwrite=True)
        registered = ""
        if self.data_path:
            # 참조만 저장(행·비밀 없음) — 확정 시트 동봉(모호 참조 방지). 게이트를 통과한
            # 뒤라(동명=확인됨·충돌=차단됨) opt-in 저장.
            opts: "dict[str, object]" = {"path": self.data_path}
            if self.data_sheet:
                opts["sheet"] = self.data_sheet
            self.pool_registry.save(
                DatasetPoolItem(name=self.dataset_name, kind="excel", opts=opts),
                allow_overwrite=True,
            )
            registered = self.dataset_name
        saved = self.job_name
        self._reset()  # 저장 후 새 작업 준비(에디터 초기화)
        return {"ok": True, "saved_name": saved, "dataset_registered": registered}

    # ---- 매핑 베이스 프로파일(#26 #5 — ADR J 축2)
    def _do_profile_list(self, p: dict) -> dict:
        """베이스 목록 + 각 베이스를 참조하는 작업 수(loud 전파 경고의 근거).

        손상 베이스 파일은 격리 수집해 함께 재진술한다(조용한 은닉 금지 — RC-05 미러).
        """
        corrupted: "list[tuple[Path, str]]" = []
        bases = self.base_registry.list_bases(corrupted=corrupted)
        refs: "dict[str, int]" = {}
        for j in self.registry.list_jobs():
            if j.base_mapping_name:
                refs[j.base_mapping_name] = refs.get(j.base_mapping_name, 0) + 1
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
        여기서 dropped 로 세어 웹이 재진술한다. 반영 성공 시 이 세션의 베이스 계보를
        갱신한다(J3 — 저장되는 작업의 ``base_mapping_name``).
        """
        if self.model is None:
            self._ensure_model()
        name = p["name"]
        try:
            base = self.base_registry.load(name)
        except Exception as exc:  # noqa: BLE001 — 부재·손상: 웹에 문구로 loud
            return {"ok": False, "error": f"매핑 프로파일을 불러올 수 없습니다: {exc}"}
        applied = self.model.apply_profile(base)
        row_fields = {r.template_field for r in self.model.rows}
        dropped = [
            m.template_field for m in base.mappings if m.template_field not in row_fields
        ]
        self._base_name = name
        notice = f"매핑 프로파일 '{name}' 반영 — {applied}개 행 확정 도착."
        if dropped:
            notice += (
                f"\n이 템플릿에 없는 프로파일 필드 {len(dropped)}개는 제외했습니다: "
                + ", ".join(dropped)
            )
        self._set_notice(notice, "warn" if dropped else "ok")
        return {"ok": True, "applied": applied, "dropped": dropped}

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
        if self.base_registry.exists(name) and not p.get("confirm"):
            refs = sum(
                1 for j in self.registry.list_jobs() if j.base_mapping_name == name
            )
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
            refs = sum(
                1 for j in self.registry.list_jobs() if j.base_mapping_name == name
            )
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
