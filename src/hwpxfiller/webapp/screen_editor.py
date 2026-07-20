"""작업 정의(HWPX) 컨트롤러 — 3분류(템플릿·필드 매핑·저장) 오케스트레이션(webview 비의존).

**에디터 흡수(R-flow 블록 2 개정, 결정 39~41)**: 이 컨트롤러의 표면은 별도 화면이 아니라
「작업」 화면 상세 패널의 **편집 모드**다 — 신규 초안은 같은 3분류를 마법사 **단계**(전진
게이트)로, 저장된 작업 편집은 **탭**(자유 이동)으로 공개한다(정보 완전 동등, 공개 방식만
상이). 브리지 화면 키 ``editor`` 와 렌더러(editor.js)는 그대로 산다 — 옮긴 것은 DOM 거처뿐.

원 이관: 목업 scr-editor 의 웹 이관(에픽 #20, 화면 #15·#16). 링1 VM 을 **그대로 임포트**해 구동한다:
매핑은 :class:`~hwpxfiller.gui.mapping_state.MappingModel`, PARTIAL 게이트는
:class:`~hwpxfiller.gui.mapping_state.PartialGate`, 저장 게이트는
:func:`~hwpxfiller.gui.job_editor_state.validate_save`. 이들은 Qt-free 라 그대로 산다
(스파이크 Q1 배당금). 표현 계층(단계 UI·행 색·표시형)만 웹으로 이식한다.

**단계**: 0 템플릿 → 1 매핑(데이터 관문 내장) → 2 저장. 진행 게이트: 0→1 은 스키마 有+
게이트 통과, 1→2 은 ``is_complete()``. R-flow 슬라이스 5 블록 2 결정 11(3단계 접기):
구 2단계 '데이터 선택'을 매핑 단계의 관문으로 인라인했다 — 데이터는 별도 단계가 아니라
매핑 단계의 머리(파일 선택/바꾸기·데이터 없이 진행)이며, 관문에서 데이터를 고르면 매핑표가
**그 자리에서** 다시 선다(단계 왕복이 만들던 유령 상태 소멸, 결정 11·12). 데이터 선택성은
단계 경계가 아니라 관문 옵트아웃(``skip_data``)으로 표현된다(ADR-J 승계).

**#26 패리티 회수(이 라운드 포함)**: 편집 모드(:meth:`EditorController.load_job`) ·
선언 데이터 자동등록(#18 31A5A484-C, ``_do_save`` 선차단 게이트). 자동등록은 **참조만**
저장한다(행·ServiceKey 없음 — [[nara-freeze-decision]]과 무관한 excel 참조).
매핑 베이스 프로파일(``_do_profile_*``, ADR J 축2)은 F22 로 제거 — 작업이 매핑을 자족
저장·복원하므로 재사용은 「작업 복제」로 수렴한다.

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)** — 태그 분류 편집(D14, #26 홈 조치 단위)·
인라인 누름틀 변환(fieldize, tpl 화면 경유로 충족 — 위저드 인라인은 별도 제안)은 여기 없다.
RAW 차단·PARTIAL 게이트·의도적 비움 이름게이트·저장 게이트·덮어쓰기 확인·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from ..core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from ..core.format_engine import presets as format_presets
from ..core.job import (
    DEFAULT_FILENAME_PATTERN,
    Job,
    JobRegistry,
    classify_existing,
)
from ..core.mapping import TYPES
from ..core.schema import extract_schema
from ..core.template_status import default_templates_dir
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
from ..gui.template_manager_state import TemplateManagerViewModel
from ..naming import make_output_filename
from .screens import NO_ROWS_TEXT, PushSink, default_pool_registry
from .template_groups import TemplateGroupModel, rel_key

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
        pool_registry: "DatasetPoolRegistry | None" = None,
        template_library: "TemplateManagerViewModel | None" = None,
        template_groups: "TemplateGroupModel | None" = None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        # 데이터풀 레지스트리 — 주입 가능(테스트), 기본은 홈 레지스트리(ADR J).
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        # HWPX 그룹 모델(#108 슬라이스 3) — **앱 조립에선 tpl 화면의 hwpx_groups 같은 인스턴스를
        # 주입**한다. 별도 인스턴스면 두 표면의 접힘·지정 인메모리 캐시가 갈라져(한쪽 토글이
        # 다른쪽에 반영 안 됨) 1단계 피커가 관리 화면과 다른 구획을 조용히 보인다(단일 실체).
        # 미주입 시 첫 접근에 표준 hwpx 모델을 지연 생성(라이브러리 VM 지연 생성과 대칭).
        self._template_groups = template_groups
        # 템플릿 라이브러리(R-info 2부 접합 최소분) — 신규 1단계=라이브러리에서 고르기(생 파일
        # 선택 폐기)·가져오기=복사. **앱 조립에선 tpl 화면의 VM 같은 인스턴스를 주입**(리뷰 F2:
        # 라이브러리=단일 실체 — 폴더 재지정이 두 표면에 함께 반영). 미주입 시 표준 라이브러리를
        # **지연 생성**(리뷰 F5: 생성자 즉시 스캔은 라이브러리를 안 쓰는 소비자·테스트에 실
        # 사용자 폴더 스캔 비용·비결정성을 물린다). 전체 개편(그룹·구획·F16)은 #108 소관.
        self._template_library = template_library
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
        # 미사용 구역 펼침 힌트(칩-라이브 결정 13) — '전체 미사용'이 세팅, 새 데이터·전체
        # 사용·개별 토글이 해제(리뷰 F7: 개별 토글 후에도 남으면 몇 步 전 행동의 stale
        # 상태가 이후 접힘 렌더를 계속 강제한다). 뷰의 수동 펼침 보존은 editor.js foldOpen.
        self._ignored_expanded = False
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
        # 편집 모드에서 복원한 작성 출처 메타(#53-C) — 표시용 + 재저장 시 최초 작성시각 보존.
        self._loaded_provenance: "dict[str, str]" = {}
        self.notice_text = ""  # 복원·프로파일 반영 등 세션 통지(loud 재진술 채널)
        self.notice_level = "muted"
        # (별도 라이브러리 행 캐시 없음 — #138 리뷰 F8·F11: 공유 VM rows() 직독으로 발산 제거.)
        # 클린 세션 표지 — 편집 복원 직후·저장 착지 직후처럼 "디스크 저장본과 동일" 상태.
        # 사용자가 손대면(변이 액션·데이터/템플릿 로드) 꺼진다. has_unsaved_work 가 소비해
        # 미변경 세션의 헛확인(폐기 확인·T2 고지)을 억제한다(리뷰 — confirm-or-alarm 의
        # 「불필요한 프롬프트 억제」 확장).
        self._session_clean = False

    def _set_notice(self, text: str, level: str = "muted") -> None:
        self.notice_text = text
        self.notice_level = level

    @property
    def template_library(self) -> TemplateManagerViewModel:
        """템플릿 라이브러리 VM — 미주입이면 첫 접근 때 표준 라이브러리로 지연 생성(리뷰 F5)."""
        if self._template_library is None:
            self._template_library = TemplateManagerViewModel(default_templates_dir())
        return self._template_library

    @property
    def template_groups(self) -> TemplateGroupModel:
        """HWPX 그룹 모델 — 미주입이면 첫 접근 때 표준 hwpx 모델 지연 생성(라이브러리 VM 대칭).

        에디터가 만드는 매체는 hwpx 뿐이라(마법사=.hwpx 산출) 그룹 축도 hwpx 하나면 족하다 —
        매체 자동 필터가 곧 단일 매체 소비 표면(결정 3·6)."""
        if self._template_groups is None:
            self._template_groups = TemplateGroupModel("hwpx")
        return self._template_groups

    def _refresh_library(self) -> None:
        """공유 라이브러리 VM 재스캔 — 외부(탐색기) 변경을 새 세션·가져오기 시점에 걷는다.

        별도 행 캐시는 두지 않는다(#138 리뷰 F8·F11): ``_library_snapshot`` 이 공유 VM 의
        ``rows()`` 를 직독하므로, 이 refresh 는 공유 VM 의 실 디스크 재스캔만 트리거하면 된다."""
        self.template_library.refresh()

    def assert_library_path(self, path: str) -> None:
        """웹 유래 템플릿 경로의 라이브러리 소속 확인 — 바깥 입구 봉쇄의 공용 seam(리뷰 F4).

        use_library_template 와 크로스스크린 load_template_into_editor 가 함께 쓴다 —
        한 입구만 막으면 「가져오기=복사가 유일한 바깥 입구」(2부)가 문서만의 불변식이 된다.
        불일치면 **새 스캔 결과를 먼저 push** 하고 거절한다(리뷰 F7: 방금 삭제된 파일의
        stale 행이 남아 같은 클릭을 반복하게 만드는 무행동 안내 금지 — 목록이 스스로 걷힌다).
        """
        self._refresh_library()
        if all(r.path != path for r in self.template_library.rows()):
            self._push()  # 갱신된 목록을 먼저 보여준다 — 거절 문구가 실행 가능해진다
            raise ValueError("라이브러리에 없는 템플릿입니다 — 목록을 새로 고쳤으니 다시 고르세요.")

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
        """from_step → from_step+1 진행 가부(Qt 위저드 isComplete 미러).

        3단계 접기(블록 2 결정 11): 데이터 선택이 매핑 단계의 관문으로 들어와 별도 단계가
        아니게 됐다 — 0→1(템플릿→매핑)은 템플릿 준비, 1→2(매핑→저장)은 매핑 확정.
        """
        if from_step == 0:
            return self._template_ready()
        if from_step == 1:
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
            "touched": row.touched,  # 소유권(칩-라이브 결정 12) — 뷰가 제안/수동 태그 파생
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
            "reachable": [self.can_advance(s) for s in range(2)],  # 0→1(템플릿→매핑),1→2(매핑→저장)
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
            "data_sheet": self.data_sheet,  # 관문 파일칩 시트 표기(#33 확정 시트)
            "record_count": len(self.records),
            # 전체 헤더(데이터 미리보기 컬럼·sample_rows 정렬의 짝, 불변).
            "source_fields": self.source_fields,
            # 활성/미사용 헤더(#49) — 드롭다운 후보는 활성만, 헤더 선택 UI는 둘 다 쓴다.
            "active_source_fields": active_sources,
            "ignored_source_fields": [f for f in self.source_fields if f in self._ignored_sources],
            "active_count": len(active_sources),
            "ignored_count": len(self._ignored_sources),
            "ignored_expanded": self._ignored_expanded,  # 미사용 구역 펼침 힌트(결정 13)
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
            "dataset_name": self.dataset_name,
            # 작성 출처 provenance(#53-C) — 편집 모드에서 복원한 것(없으면 None).
            "provenance": self._loaded_provenance or None,
            # 기본 데이터 연결 상태(#67) — 저장 단계(2)에서만 계산: 표시가 저장 단계뿐이라
            # 매핑 편집 등의 잦은 push 가 레지스트리 읽기+exists() 를 지불할 이유가 없다
            # (저장 단계 자체의 push 는 change 단위라 비용 무시 수준).
            "default_dataset": (
                self._default_dataset_snapshot() if self.step == 2 else None
            ),
            # 템플릿 라이브러리(신규 1단계=라이브러리에서 그룹 구획으로 고르기, #108 슬라이스 3)
            # — 템플릿 분류(0)에서만 스캔한다(파일시스템 재스캔이라 매핑 편집의 잦은 push 에 지불
            # 금지; default_dataset 선례). 그 외 단계는 빈 구획.
            "library": (
                self._library_snapshot() if self.step == 0 else {"sections": [], "flat": True}
            ),
            # F26 — 파일명 라이브 예시(표본 1행 고정). 저장 분류(2)에서만 계산.
            "pattern_preview": self._pattern_preview() if self.step == 2 else "",
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

    def _library_snapshot(self) -> "dict":
        """1단계 피커 = 라이브러리를 **관리 화면과 같은 그룹 구획**으로(선택 전용, #108 슬라이스 3).

        매체는 hwpx 하나뿐(마법사=.hwpx 산출 → 매체 자동 필터). 관리 화면 HWPX 구획과 같은
        그룹 모델·같은 build_sections 로 성형해 두 표면이 한 조직을 보인다(결정 6). 여기는
        **선택 전용** — 카드 ⋮·이동·삭제·＋그룹지정 없이 상태 배지·선택 버튼만. 상태 판정·
        배지는 링1(TemplateManagerViewModel) 소유, 오류 행도 숨기지 않고 detail 과 함께 싣는다.

        **공유 VM 직독**(#137·#138 리뷰 F8·F11): 별도 행 캐시를 두지 않고 공유 VM 의
        ``rows()``(재스캔 없이 캐시 반환)를 그대로 읽는다 — 관리 화면의 가져오기·삭제가
        공유 VM 을 refresh 하면 여기 피커도 즉시 반영된다(발산 캐시 제거). **reconcile 미실행**:
        유령 지정 정리는 관리 화면의 위생 소관이고, 여기서 (부분/필터된) 목록으로 reconcile 하면
        살아있는 그룹 지정을 영구 삭제할 수 있어 실행하지 않는다(build_sections 는 표시에서
        고아를 이미 무시). ``{sections, flat}`` 반환(작업/관리 목록 동형).
        """
        root = self.template_library.library_dir
        items = [
            {
                "key": rel_key(r.path, root),
                "name": r.name,
                "path": r.path,
                "badge_label": r.badge_label,
                "badge_level": r.badge_level,
                "is_error": r.is_error,
                "detail": r.detail_line(),
                "current": bool(self.template_path) and r.path == self.template_path,
            }
            for r in self.template_library.rows()
        ]
        sections, flat = self.template_groups.build_sections(items, key_of=lambda it: it["key"])
        return {"sections": sections, "flat": flat}

    def _pattern_preview(self) -> str:
        """F26 — 파일명 패턴의 라이브 예시 1행(표본 고정 = 첫 레코드, seq=1).

        **실제 생성기와 같은 함수**(:func:`make_output_filename`)로 만들어 예시가 거짓말하지
        않는다(별도 구현이면 예시·산출물이 조용히 어긋난다 — 단일 출처). 값은 현 매핑의
        표본 첫 행 기준(데이터 없으면 필드 토큰 미치환 그대로 노출 = 정직). 표시 전용이라
        실패는 빈 문자열(패턴 검증은 저장 게이트 소관).
        """
        if not self.pattern:
            return ""
        data: "dict[str, object]" = {}
        if self.model is not None:
            record = self.records[0] if self.records else {}
            for row in self.model.rows:
                if not row.has_content():
                    continue
                try:
                    data[row.template_field] = row.to_mapping().value_for(record)
                except ValueError:
                    data[row.template_field] = ""
        try:
            return make_output_filename(self.pattern, data)
        except Exception:  # noqa: BLE001 — 표시 전용(저장 게이트가 검증 소관)
            return ""

    def _default_dataset_snapshot(self) -> "dict | None":
        """복원한 기본 데이터 참조(#53-A)의 연결 상태 재진술(#67) — 저장 단계(2) 전용.

        이 세션이 데이터를 새로 골랐으면(저장 시 참조가 그 이름으로 바뀜) 자동등록
        블록이 이미 그 연결을 말하므로 None(이중 서사 금지). 참조가 없어도 None.
        상태: ``linked``(풀 항목·파일 실존) / ``dead``(항목은 있으나 파일 이동·삭제)
        / ``missing``(풀 항목 삭제) / ``corrupt``(항목 JSON 손상). 삭제와 손상을 한
        문구로 합치면 데이터 관리 화면(손상 격리 표시)과 다른 조치를 안내하게 된다
        (재진술 정직성 — PR #70 리뷰). 비파일 참조(nara 등)는 경로 없이 linked 로
        본다 — 파일 실존 판정 대상이 아니다(조준 시점 관문이 거절 담당).
        """
        ref = self.default_dataset_ref
        if self.data_path or not ref:
            return None
        try:
            item = self.pool_registry.load(ref)
        except FileNotFoundError:
            return {"name": ref, "status": "missing", "path": ""}
        except Exception:  # noqa: BLE001 — 손상 JSON 등: '삭제됨'으로 오진술 금지
            return {"name": ref, "status": "corrupt", "path": ""}
        raw = item.opts.get("path") if isinstance(item.opts, dict) else None
        path = raw if (item.kind == "excel" and isinstance(raw, str)) else ""
        if not path:
            return {"name": ref, "status": "linked", "path": ""}
        status = "linked" if Path(path).exists() else "dead"
        return {"name": ref, "status": status, "path": path}

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
        """버려질 **미저장** 변경이 있는가 — 폐기 전 확인·T2 고지 판단에 쓴다(#25).

        ``_reset()`` 직후엔 False. **클린 세션**(편집 복원 직후·저장 착지 직후 —
        ``_session_clean``)도 False: 내용이 디스크 저장본과 동일해 버릴 것이 없다(리뷰 —
        미변경 편집 세션의 전환마다 헛확인이 떴었다). 그 외엔 이름·데이터·매핑 모델 중
        하나라도 있으면 사용자가 손댄 세션이므로 True — 템플릿만 갓 로드한 상태(모델 전)는
        아직 버릴 게 없어 False(불필요한 프롬프트 억제).
        """
        if self._session_clean:
            return False
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

    # ---------------------------------- 템플릿 라이브러리 피커(R-info 2부 접합 최소분)
    def _do_use_library_template(self, p: dict) -> None:
        """라이브러리 목록에서 고른 템플릿으로 새 작업 세션(신규 1단계 정본 경로).

        경로 화이트리스트는 :meth:`assert_library_path` 공용 seam(리뷰 F4 — 크로스스크린
        진입과 단일 정의). 미저장·편집 맥락 확인은 호출측(웹)이 선판단한다.
        """
        path = str(p["path"])
        self.assert_library_path(path)
        self.new_job_session(path)

    def _do_toggle_library_group(self, p: dict) -> None:
        """1단계 피커 그룹 접힘 토글 — **관리 화면과 같은 모델**을 토글해 한 조직을 공유한다
        (한 표면에서 접으면 다른 표면도 접힌 채로; 설정 영속). 세션 변이가 아니라 뷰 상태라
        _session_clean 을 건드리지 않는다."""
        self.template_groups.toggle_collapse(p["group"])

    def import_template(self, path: str) -> str:
        """템플릿 **가져오기 = 복사**(R-info 2부: 앱 소유 루트 — 생 파일 참조 금지).

        고른 파일을 라이브러리 폴더로 복사하고 **그 사본**으로 새 작업 세션을 연다 — 원본의
        후속 이동·수정은 라이브러리에 불파급. 이름 충돌은 조용히 덮지 않고 ``이름 (2).hwpx``
        식 접미로 회피 + notice 재진술. 브리지(파일 다이얼로그)가 부른다.

        **선검증·무잔재**(리뷰 F3): 복사 전에 원본에서 스키마를 뽑아 손상·RAW(누름틀 0)를
        거른다 — 복사 먼저면 실패 사본이 앱 소유 라이브러리에 영구 오류 행으로 남는다(인앱
        삭제 어포던스 없음). 복사·로드 중 실패도 사본을 걷어내고 재던진다(반가져오기 금지).
        """
        src = Path(path)
        schema = extract_schema(str(src))  # 손상 = 여기서 loud(복사 전 — 잔재 없음)
        if not schema.fields:
            raise ValueError(
                "누름틀이 없는 템플릿(RAW)입니다 — 템플릿 관리의 변환(fieldize)을 먼저 "
                "거치거나 누름틀이 있는 파일을 가져오세요."
            )
        lib_dir = self.template_library.library_dir
        if lib_dir is None:
            raise ValueError("템플릿 라이브러리 폴더가 지정되지 않았습니다.")
        lib_dir.mkdir(parents=True, exist_ok=True)
        dest = lib_dir / src.name
        n = 2
        while dest.exists():
            dest = lib_dir / f"{src.stem} ({n}){src.suffix}"
            n += 1
        try:
            shutil.copy2(src, dest)
            self._refresh_library()
            self.new_job_session(str(dest))
        except Exception:
            dest.unlink(missing_ok=True)  # 반가져오기 잔재 제거(디스크 풀 등)
            self._refresh_library()  # 잔재 제거를 공유 VM 에 반영(stale 오류 행 방지)
            raise
        renamed = f" (이름 충돌로 '{dest.name}' 로 저장)" if dest.name != src.name else ""
        self._set_notice(
            f"'{src.name}' 을 라이브러리로 복사해 시작합니다{renamed} — 원본 수정은 "
            "라이브러리 사본에 반영되지 않습니다.",
            "ok",
        )
        self._push()
        return dest.name

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_template_path(self, path: str) -> None:
        """선택된 .hwpx 를 로드 — 스키마 추출 + PARTIAL 게이트 계산(Qt 위저드 _load_template 미러)."""
        self._session_clean = False  # 브리지 직행 변이(디스패치 밖) — 클린 표지 해제
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
            raise ValueError(NO_ROWS_TEXT)
        self._session_clean = False  # 브리지 직행 변이(디스패치 밖) — 클린 표지 해제
        self.data_path = path
        self.data_sheet = sheet or ""  # 자동등록 참조에 확정 시트 동봉(#26 — 모호 참조 방지)
        self.source_fields = source.fields()
        # 새 데이터 = 새 헤더 어휘 → 이전 미사용 선택이 조용히 남지 않게 전원 활성으로.
        self._ignored_sources = set()
        self._ignored_expanded = False  # 새 데이터 = 펼침 힌트 초기화(결정 13)
        self.records = records
        self.preview_index = 0
        # 자동등록 기본 이름 = 파일 스템(사용자가 저장 단계에서 수정 가능). 데이터를 바꾸면
        # 이전 파일 이름이 조용히 남지 않게 매번 재유도한다.
        self.dataset_name = Path(path).stem
        # 3단계 접기(블록 2 결정 11·12): 매핑 단계 관문에서 데이터를 고르면(모델이 이미
        # 있으면) 매핑표를 **그 자리에서** 다시 세운다 — 새 컬럼·자동 제안 반영, 안 맞게 된
        # 확정 행은 미확정 강등(_ensure_model 이 값 이월+재확정 재진술). 모델 전(step 0
        # 선로드·테스트 헬퍼)엔 goto_step 1 이 세우므로 여기선 세우지 않는다.
        if self.model is not None:
            before = self._model_key
            self._ensure_model()
            if self._model_key == before:
                # 같은 파일·시트 재겨눔(키 불변 = 재초안 없음) — 위에서 칩 상태만 전원 활성으로
                # 리셋됐다. 관문 재동기화로 시스템 행 재제안을 되살린다(PR-3 리뷰 F3: use_none
                # 뒤 같은 파일 재선택이 「후보 없음」 죽은 제안으로 남던 창).
                self.model.apply_active_sources(
                    self._active_sources(), vocabulary=self.source_fields
                )
        self._push()

    # ------------------------------------------------------- 편집 모드(#26 #1)
    def load_job(self, name: str) -> None:
        """저장된 작업을 편집 세션으로 복원 — 3단계 상태 재구성(단순 배선 아님).

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
        self._loaded_provenance = dict(job.mapping.provenance)  # 작성 출처 표시(#53-C)
        self.default_dataset_ref = job.default_dataset_ref  # 편집 저장 시 보존(#53-A)
        # 소스 어휘 = 저장 매핑이 참조하는 키 합집합(profile_source_vocabulary 단일 출처,
        # from_profile 과 공유) — 데이터 없이도 복원된 source 가 선택지에 있어야 드롭다운이
        # (비움)으로 오표시되지 않는다.
        self.source_fields = profile_source_vocabulary(job.mapping)
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
        applied = self.model.apply_profile(job.mapping)
        self._model_key = (self.template_path, self.data_path, self.data_sheet, tuple(self.source_fields))
        self.step = 1  # 매핑 확정 단계로 — 저장까지 사람 재검토를 거친다(3단계 접기).
        row_fields = {r.template_field for r in self.model.rows}
        dropped = [
            m.template_field for m in job.mapping.mappings
            if m.template_field not in row_fields
        ]
        fresh = [r.template_field for r in self.model.rows if not r.confirmed]
        # 사용자 어휘 재진술(F17) — "매핑 N행 복원" 같은 로그 어휘를 UI 로 내보내지 않는다.
        notice = f"'{job.name}' 을(를) 편집합니다 — 저장된 매핑 {applied}행을 불러왔습니다."
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
        # 복원 직후 = 디스크 저장본과 동일(클린) — 손대기 전 전환·새 작업이 "저장하지 않은
        # 세션" 헛확인을 띄우지 않는다(리뷰). 내부의 load_template_path 가 표지를 껐으므로
        # 마지막에 켠다. 드리프트 경고(warn)가 있어도 내용 동일성은 참이다.
        self._session_clean = True
        self._push()

    # 세션 내용을 바꾸지 않는 액션 — 클린 표지를 끄지 않는다(보기 이동·미리보기·질의).
    _NONMUTATING_ACTIONS = frozenset(
        {"goto_step", "step_preview", "mapping_reset_stakes", "toggle_library_group"}
    )

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 editor 액션: {action!r}")
        if action not in self._NONMUTATING_ACTIONS:
            self._session_clean = False  # 변이 = 더는 저장본과 동일하지 않다
        result = handler(payload)
        self._push()
        return result

    # ---- 세션 수명주기(F10)
    def _do_new_session(self, p: dict) -> None:
        """홈 「＋ 새 작업」 — 이전 세션 전량 초기화(라벨-행동 일치, F10).

        종전 홈 버튼은 bare nav 라 직전 세션(이름·데이터·매핑·편집 원점)이 그대로
        복원돼 '새'가 사실상 '이전 작성 계속'이었다. 미저장 확인은 호출측(웹)이
        ``has_unsaved_work`` 로 선판단한다 — ``new_job_session``(템플릿 진입 seam)과
        같은 분담. 초기 상태 notice 는 두지 않는다(정상은 조용히).
        """
        self._reset()

    # ---- 마법사/탭 이동
    def _do_goto_step(self, p: dict) -> None:
        """단계 이동 — 신규(마법사)는 전진 게이트, 편집(탭)은 자유 이동(결정 41).

        신규 초안은 순서 의존이 실재해(템플릿 없인 매핑 없음) 전진마다 게이트를 세운다.
        편집(``_editing_origin`` 有)은 저장된 작업 복원이라 의존이 전부 충족된 상태 — 같은
        3분류를 탭으로 자유 이동한다. 편집 중 사용자가 의존을 되무를 수는 있으나(매핑 해제
        등) 탭 이동은 보기 이동일 뿐이고, 저장 게이트(``_do_save`` 의 검증·재진술)는 그대로
        지켜져 무결성은 저장점에서 담보된다.
        """
        target = int(p["step"])
        if target == 0 and self.step != 0:
            self._refresh_library()  # 템플릿 분류 재진입 = 공유 VM 실 디스크 재스캔(외부 변경 반영)
        if target > self.step and not self._editing_origin:
            for s in range(self.step, target):  # 신규: 전진은 게이트 통과 필요(각 중간 단계).
                if not self.can_advance(s):
                    raise ValueError(f"{s}단계 게이트 미통과 — 진행할 수 없습니다.")
        if target == 1:  # 매핑 진입(3단계 접기) — 데이터 유무 불문 모델 초안 생성.
            self._ensure_model()
        self.step = max(0, min(2, target))

    def _do_ack_gate(self, p: dict) -> None:
        """PARTIAL 게이트 명시 확인 — 재진술된 미해결 토큰 전체를 확인(ADR-E)."""
        if self.gate is None:
            raise ValueError("확인할 게이트가 없습니다.")
        self.gate.acknowledge(self.gate.unmet_tokens)

    def _do_skip_data(self, p: dict) -> None:
        """데이터 없이 진행(스키마온리) — 매핑 단계 관문의 옵트아웃(F20).

        3단계 접기 후 별도 '데이터 단계'는 없다 — 이 액션은 매핑 관문에서 데이터 참조를
        비우고(고른 게 있었으면 해제) 스키마온리 모델로 매핑을 잇는다. 매핑 단계(1)에
        머문다(관문에서 호출) — step 0 에서 shortcut 으로 불려도 매핑으로 착지한다.

        **템플릿 게이트 선통과는 step 0 shortcut 에만**(PR#105 리뷰 F2 + PR-2 리뷰 F6):
        step 0 진입은 ``goto_step(1)`` 과 달리 게이트를 안 거치므로 PARTIAL 미확인 템플릿을
        매핑으로 밀어 넣을 수 있어 막는다. 이미 매핑에 정당히 서 있는 세션(편집 복원 —
        게이트 확인은 세션 국소라 재로드 시 미확인으로 돌아온다)의 관문 클릭까지 막으면,
        전부터 되던 옵트아웃이 엉뚱한 처방("토큰 확인")과 함께 하드 실패한다.

        **비울 참조가 없으면 어휘를 지우지 않는다**(PR-2 리뷰 F3): 편집 복원 세션은 데이터
        없이 저장-매핑 어휘(``profile_source_vocabulary``)로 서는데, 이 링크가 no-op 으로
        읽히는 상황에서 어휘를 비우면 전 행이 미확정 강등 + "(데이터에 없음)" 오표시된다.
        데이터가 실재할 때만 해제하고, 편집 세션의 해제는 현재 매핑이 참조하는 소스 어휘로
        복귀한다(load_job 초기 상태와 동형 — 빈 어휘 강등 금지).
        """
        if self.step == 0 and not self.can_advance(0):
            raise ValueError(
                "템플릿 게이트를 통과해야 매핑으로 진행할 수 있습니다 — "
                "미해결 토큰을 확인하거나 템플릿을 정리하세요."
            )
        had_data = bool(self.data_path)
        self.data_path = ""
        self.data_sheet = ""
        self.dataset_name = ""
        self.records = []
        self.preview_index = 0
        if had_data:
            if self._editing_origin and self.model is not None:
                seen: "list[str]" = []
                for row in self.model.rows:
                    if row.source and row.source not in seen:
                        seen.append(row.source)
                self.source_fields = seen
            else:
                self.source_fields = []
            self._ignored_sources = set()
            self._ignored_expanded = False
        self._ensure_model()
        self.step = 1

    # ---- 사용 헤더 칩(#49 + 칩-라이브 결정 12·13) — 즉시 동사, 활성/미사용 전환.
    # 체크박스 스테이징 소거(결정 13): 칩 토글이 곧 즉시 반영. 활성 집합 변화는 model.
    # apply_active_sources 단일 관문이 처리한다 — 시스템 소유 행은 라이브 재제안(조용),
    # 사람 소유 행은 소스가 꺼지면 R4 시끄러운 강등. 원본 데이터·매핑 계약은 불변.
    def _do_use_all_headers(self, p: dict) -> None:
        """전체 헤더를 다시 활성으로 — 미사용 일괄 해제(결정 13 대칭쌍)."""
        self._ignored_expanded = False
        self._apply_active(set(self.source_fields))

    def _do_use_none(self, p: dict) -> None:
        """전체 미사용(결정 13) — 확정 존재 시 차단, 아니면 전부 미사용 + 미사용 구역 자동 펼침.

        구 '전부 미사용 무조건 거부'(리뷰 #62)를 결정 13 이 개정: **확정이 있을 때만** 차단하고
        (되돌릴 수 없는 확정 파괴 방지), 확정이 없으면 '고른다→매핑한다' 흐름의 출발점으로
        허용한다(수동 touched 행은 강등·재진술하되 진행). 미사용 구역을 펼쳐 고르게 한다.
        """
        if self.model is not None and self.model.confirmed_count():
            raise ValueError(
                "확정한 매핑이 있어 전체 미사용을 할 수 없습니다 — 확정을 먼저 해제하거나 "
                "칩을 하나씩 끄세요."
            )
        self._ignored_expanded = True  # 고르는 흐름의 시작점 — 미사용 구역 펼침(결정 13)
        self._apply_active(set(), allow_empty=True)

    def _do_toggle_source_active(self, p: dict) -> None:
        """헤더 1개의 활성/미사용 즉시 토글(칩 클릭 — 결정 13). 마지막 활성은 남긴다."""
        self._ignored_expanded = False  # 개별 토글 = '전체 미사용' 펼침 힌트의 소임 종료(F7)
        field = str(p["field"])
        active = set(self._active_sources())
        if field in active:
            active.discard(field)
        else:
            active.add(field)
        self._apply_active(active)  # allow_empty=False → 마지막 헤더 토글은 '하나 이상'으로 차단

    def _apply_active(self, active: "set[str]", *, allow_empty: bool = False) -> None:
        """활성 헤더 집합을 확정한다 — 데이터에 있는 것만 채택하고, model.apply_active_sources
        단일 관문으로 라이브 재제안(시스템 소유) + R4 강등(사람 소유)을 재계산·재진술한다.

        개별 토글은 마지막 활성 헤더를 남긴다(``allow_empty=False`` — '하나 이상'). 명시
        동사 '전체 미사용'(``_do_use_none``)만 ``allow_empty=True`` 로 0개를 허용하되,
        확정이 있으면 그쪽에서 먼저 차단한다(결정 13 — 확정 파괴만 사전 차단)."""
        active = {f for f in active if f in self.source_fields}
        if self.source_fields and not active and not allow_empty:
            raise ValueError(
                "사용할 헤더를 하나 이상 남겨 두세요 — 하나씩 끄되 마지막 하나는 남기거나, "
                "'전체 미사용'으로 다시 골라 켜세요."
            )
        self._ignored_sources = {f for f in self.source_fields if f not in active}
        demoted: "list[str]" = []
        if self.model is not None:
            # vocabulary 로 강등을 현재 데이터 어휘 안으로 한정(PR-3 리뷰 F1) — 어휘 밖 소스를
            # 겨눈 이월 stale 사람 소유 행은 칩 조작과 무관하니 건드리지 않는다(뷰가 「데이터에
            # 없음」으로 이미 시끄럽다). 통지도 실제로 끈 헤더의 행만 지목하게 된다.
            demoted = self.model.apply_active_sources(
                self._active_sources(), vocabulary=self.source_fields
            )
        n_active = len(self._active_sources())
        n_ignored = len(self._ignored_sources)
        msg = f"사용 헤더 {n_active}개 · 미사용 {n_ignored}개."
        if demoted:
            self._set_notice(
                msg + f"\n미사용으로 바꾸며 확정·수동 매핑을 해제한 필드 {len(demoted)}개"
                "(재확정 필요): " + ", ".join(demoted),
                "warn",
            )
        else:
            self._set_notice(msg, "muted")

    def _ensure_model(self) -> None:
        """매핑 진입 시 초안 생성 — 키(템플릿·데이터·시트·소스) 불변이면 그대로, 바뀌면
        **전원 미확정 초안으로 재생성**하되 이전 확정 행의 값(소스·유형·상수·서식)은
        제안으로 이월한다(#26 UX 유지 + 확정 불변식 복원).

        불변식: 템플릿/데이터 키가 바뀌면 어떤 행도 확정 상태로 도착하지 않는다. 한때
        이전 확정을 ``apply_profile`` 로 확정 상태 그대로 되살렸는데 — 같은 이름 컬럼
        ('금액' 등)이 의미가 다른 새 데이터에서 사람 검토 없이 확정으로 도착해
        ``is_complete`` 를 통과, 저장·실행까지 흐르는 조용한 게이트 우회였다. 지금은
        값만 이월하고 확정은 전원 해제(``confirm=False``), 재확정 필요를 notice 로
        시끄럽게 재진술한다(조용한 소실도, 조용한 승계도 금지).

        키(#49 주의): 키는 **전체** ``source_fields`` 만 담고 미사용 집합은 담지 않는다 —
        의도된 설계다. 활성/미사용 변화는 재생성이 아니라 ``apply_active_sources`` 관문이
        제자리에서 처리한다(칩-라이브 결정 12·13): 시스템 소유 행은 재활성 헤더까지 포함해
        라이브 재제안을 받고, 확정·수동 행은 관문의 R4 강등 외엔 재생성으로 날아가지 않는다
        (재생성=전원 미확정이라 키에 담으면 토글마다 확정이 무너진다).

        **``data_sheet`` 는 키 성분이다**(3단계 접기 리뷰 F1): 관문에서 같은 workbook 의
        다른 시트로 재겨눔했는데 두 시트의 헤더명이 우연히 같으면(예: 둘 다 '업체명·금액')
        ``source_fields`` 가 안 바뀌어 키가 불변→조기 반환→확정 행이 이전 시트 기준으로 남아
        저장·실행되는 **조용한 게이트 우회**가 된다(슬라이스 4 '정체 키 성분 누락' 교훈).
        ``load_job`` 도 같은 성분 순서로 키를 세워 정합을 지킨다.
        """
        if self.schema is None:
            raise ValueError("템플릿이 로드되지 않았습니다.")
        key = (self.template_path, self.data_path, self.data_sheet, tuple(self.source_fields))
        if self.model is not None and self._model_key == key:
            return
        prior = None
        if self.model is not None:
            # 이월 = carry_profile(확정 + 내용 있는 touched — PR-2 리뷰 F1): 확정-전용
            # to_profile 로는 미확정 수동 편집(직접 고른 소스·상수)이 관문 재겨눔에서 조용히
            # 소실된다 — 확인 대화가 "값은 이월된다"고 말한 그 값이다. 내용 없는 touched 는
            # carry_profile 이 걸러 시스템 소유로 낙착시킨다(PR-1 리뷰 — 영구 동결 방지).
            carried_prior = self.model.carry_profile()
            if carried_prior.mappings:
                prior = carried_prior
        # 미사용 헤더(#49)는 자동 제안 후보에서 제외 — 매핑 진입 전 좁혀두면 여기서
        # 반영된다(진입 후의 활성 변화는 _apply_active → apply_active_sources 관문 소관).
        self.model = MappingModel.from_suggestions(self.schema, self._active_sources())
        if prior is not None:
            carried = self.model.apply_profile(prior, confirm=False)
            self._set_notice(
                f"템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다 — 확정했거나 직접 "
                f"편집한 {carried}개 행의 소스·유형·서식은 이월했지만 전 행이 미확정입니다.\n"
                "같은 이름 컬럼이라도 새 데이터에서는 의미가 다를 수 있습니다 — "
                "저장하려면 전 행을 다시 확정하세요.",
                "warn",
            )
        self._model_key = key

    def _do_mapping_reset_stakes(self, p: dict) -> dict:
        """관문 파괴 확인(데이터 교체/비우기)의 근거 수치 — **지금** Python 이 판정한다.

        웹 지역 스냅샷(LAST)으로 세면 push 지연 창에서 방금 확정한 행이 안 보여 확인
        대화가 조용히 생략된다(PR-2 리뷰 F7 — 슬라이스 4 stale 판독류, 처방="판정은
        Python 이 지금, JS 는 문안만"). 수치 = 이월 대상(확정 + 내용 있는 touched)
        — ``_ensure_model`` 의 carry_profile 과 같은 집합이라 확인 문안과 실제 이월이
        어긋나지 않는다.
        """
        if self.model is None:
            return {"human": 0, "manual_unconfirmed": 0, "confirmed": 0}
        rows = [r for r in self.model.human_owned_rows() if r.confirmed or r.has_content()]
        # manual_unconfirmed 는 '전체 미사용' 확인(리뷰 R2)의 근거 — **use_none 이 실제로
        # 강등하는 집합과 같은 술어**여야 문안과 파괴가 일치한다(PR-3 리뷰 F4): 소스를 겨눈
        # touched 미확정 행만. 소스 없는 수동 const 행은 강등 대상이 아니라 세지 않는다.
        manual = [
            r for r in self.model.rows if r.touched and not r.confirmed and r.source
        ]
        # confirmed 는 use_none 사전 차단의 근거(PR-3 리뷰 F5) — 확인 모달을 띄운 뒤에야
        # 백엔드가 거부하는 확인-후-오류 순서를 웹이 선차단으로 뒤집는다.
        return {
            "human": len(rows),
            "manual_unconfirmed": len(manual),
            "confirmed": self.model.confirmed_count(),
        }

    # ---- 매핑 행 편집(모두 편집=확정 해제, VM 이 처리)
    def _do_set_source(self, p: dict) -> None:
        """소스 지정(수동=사람 소유). 실제 데이터 열만 받는다 — '자동으로 되돌리기'는 별도
        액션 ``revert_source``(리뷰 R5: 센티넬을 소스값에 얹으면 동명 실열과 충돌해 그 열을
        영영 못 겨눈다 — 전용 액션으로 분리)."""
        self.model.set_source(int(p["index"]), p["source"])

    def _do_revert_source(self, p: dict) -> None:
        """소스를 자동 제안으로 되돌린다(칩-라이브 결정 12) — 그 행을 시스템 소유로 완전 리셋
        (소스·유형·상수·표시형)하고 **그 행만** 활성 집합 기준 재제안한다.

        전집합 apply_active_sources 가 아니라 단일 행 resuggest_row 를 쓴다(리뷰 R4): 되돌리기는
        그 행 하나의 의사표시라, 전집합을 돌리면 무관한 stale 사람 소유 행까지 조용히 강등된다.
        """
        index = int(p["index"])
        # 확정 행 방어(PR-3 리뷰 F2): 확정도 touched 라 ↩ 가 서면 오클릭 한 번에 확정이
        # 조용히 풀리고 다른 열로 치환될 수 있다 — 확정 해제(체크박스)가 의식적 1단계.
        if self.model.rows[index].confirmed:
            raise ValueError("확정한 행은 되돌릴 수 없습니다 — 확정을 먼저 해제하세요.")
        self.model.revert_to_auto(index)
        self.model.resuggest_row(index, self._active_sources())

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
        """자동등록 데이터셋 이름 수정(저장 단계) — 기본은 데이터 파일 스템."""
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
        # 저장 착지 = 방금 저장한 작업의 **편집 세션**(결정 40 저장 제자리 · 결정 41 전환점=저장:
        # 초안은 저장으로 작업이 되고 이후 편집은 탭). 구판 ``_reset()`` 은 사용자를 빈 0단계
        # 마법사에 방치하고, 그 리셋 push 가 성공 표지(#save-msg)를 지워 완결 신호가 증발했다
        # (리뷰 F2 — 슬라이스 4 push/반환 경합류). 재로드는 디스크 저장본 기준이라 지문·원점이
        # 새로 서고, 클린 착지(_session_clean)라 직후 전환·새 작업이 헛확인을 띄우지 않는다.
        self.load_job(saved)
        self._set_notice(f"작업 '{saved}' 을(를) 저장했습니다.", "ok")
        result = {"ok": True, "saved_name": saved, "dataset_registered": registered}
        if register_error:
            result["dataset_register_error"] = register_error
        return result

