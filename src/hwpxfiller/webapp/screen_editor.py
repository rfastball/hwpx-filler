"""작업 정의 컨트롤러 — 템플릿·필드 매핑·저장 오케스트레이션(webview 비의존).

**매체 2종**(F6 PR-B): 「템플릿」 탭이 HWPX·TXT 두 밴드를 보이고, 선택 확장자가 세션
매체를 정한다(:func:`~hwpxfiller.domain.job.template_media` 파생 — 탭 구성·저장 게이트가
따라온다). TXT 작업 생성은 구 「기안」 화면의 승계처가 여기다(지도 §10.15.15 점검표 1행).

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
단계 경계가 아니라 관문의 데이터 선택 동사 둘(파일 고르기·등록 데이터에서 고르기)로
표현된다. 「데이터 없이 진행」(구 ``skip_data``)은 #932 U4-C 에서 사라졌다 — 작업이 데이터
결속을 durable 로 들고 저장 게이트가 그것을 요구하므로 옵트아웃은 저장할 수 없는 세션으로
가는 링크가 됐다.

**데이터 결속(U4 §2.4, #932 U4-C)**: 이 화면이 세운 데이터는 더는 검토용 문맥만이 아니다 —
경로·시트·헤더 행 한 벌이 :class:`~hwpxfiller.domain.job.Job` 에 실려 저장되고, 저장본 편집
진입은 그 결속을 다시 읽어 세운다(:meth:`EditorController._restore_from`). 저장 착지도 같은
경로를 지나므로 저장 한 번이 세션의 데이터를 내려놓지 않는다.

**#26 패리티 회수(이 라운드 포함)**: 편집 모드(:meth:`EditorController.load_job`).
매핑 베이스 프로파일(``_do_profile_*``, ADR J 축2)은 F22 로 제거 — 작업이 매핑을 자족
저장·복원하므로 재사용은 「작업 복제」로 수렴한다. 선언 데이터 자동등록(#18·#26)과
작업↔데이터 결속(#53-A)은 #347(U2 §5.3 판정 D)로 폐기 — 이 세션의 데이터는 검토용
문맥일 뿐 작업에 저장되지 않고, 풀 등록은 데이터 선택 면의 「이 데이터 고정」 하나다.

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)** — 태그 분류 편집(D14, #26 홈 조치 단위)·
인라인 누름틀 변환(fieldize, tpl 화면 경유로 충족 — 위저드 인라인은 별도 제안)은 여기 없다.
RAW 차단·PARTIAL 게이트·의도적 비움 이름게이트·저장 게이트·덮어쓰기 확인·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.dataset_pool import DatasetPoolRow
from ..domain.dataset_reference import STATUS_ACTIVE
from ..domain.format_engine import presets as format_presets
from ..domain.job import (
    DEFAULT_FILENAME_PATTERN,
    Job,
    data_binding_of,
    has_data_binding,
    template_media,
)
from ..domain.mapping import TYPES, MappingProfile
from ..domain.schema import FieldSpec, TemplateSchema, extract_schema, infer_type
from ..external import example_pack
from ..external.text_registry import TextTemplateRegistry
from ..domain.text_render import SEG_MISSING, render_segments, template_fields
from ..data.factory import source_for_path
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry, content_fingerprint
from ..host.locations import default_templates_dir, default_text_templates_dir
from ..gui.edit_session import (
    DATA_ANCHORED_ENTRY_REASONS,
    SECTION_BINDING,
    SECTION_FILENAME,
    SECTION_TEMPLATE,
    EditSession,
    make_context,
    sections_for,
)
from ..gui.job_editor_state import (
    BINDING_CONFIRM_HINT,
    BINDING_CONFIRM_LABEL,
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
from ..external.template_inspection import HWPX_TEMPLATE_OPS, inspect_hwpx_template
from ..external.hwpx_package_io import read_hwpx_package
from ..gui.template_manager_state import TemplateManagerViewModel
from ..gui.tutorial_state import Milestone
from ..gui.work_mode import work_mode_label  # 교차 매체 거절 문안의 방식 라벨(§19.1)
from ..naming import make_output_filename
from .screens import (
    MUTATION_KINDS,
    NO_ROWS_TEXT,
    TXT_RAW_BLOCK,
    PushSink,
    TutorialSink,
    load_pool_into,
    pool_reference_triple,
    reference_missing,
    unwired_tutorial,
)
from .template_groups import TemplateGroupModel, norm_library_path, rel_key

# 표시형 프리셋은 유형별 고정 → 한 번 계산해 스냅샷에 싣는다(코어 라벨 그대로).
_FMT_OPTIONS = {t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES}

# 2단계 데이터 미리보기에 싣는 샘플 행 수(#16 98DDFE96) — 전체 적재는 이미 self.records
# 에 있으나 스냅샷엔 매핑 감(感)만 주는 소량만 노출한다(record_count 로 "외 M건" 표기).
_SAMPLE_ROWS = 3

# 1단계 피커 행에 싣지 않는 링1 액션(F8 — tpl 화면 사망의 승계 표면): `preview` 는 #13
# 결정(10F2FF98-B — 작업 위저드와 중복), `make_job` 은 행 「이 템플릿으로」 버튼이 이미
# 소유한다(같은 동사 2벌 금지 — §10.17.2 판정 D).
_PICKER_HIDDEN_ACTIONS = frozenset({"preview", "make_job"})

# TXT 판 RAW 차단 문안은 `screens.TXT_RAW_BLOCK` 단일 출처 — 재연결 게이트와 같은 판정
# 같은 문안(리뷰 2R P1). 아래 import 로 이 모듈의 옛 소비자(테스트 포함)도 그대로 산다.

# 이 화면이 **편집하지 않는** durable 메타 — 저장이 Job 을 새로 조립하므로 여기 열거되지
# 않은 필드는 조용히 기본값으로 떨어진다. 태그·마지막 실행만 열거하던 시절 그룹이 실제로
# 그렇게 소실됐다(편집 한 번에 좌 목록 구획이 「그룹 없음」으로 초기화). 필드를 늘릴 땐 이
# 한 곳만 고치면 되도록 사전으로 모은다 — 즐겨찾기(슬라이스 2)가 같은 함정을 밟지 않게.
_EMPTY_PRESERVED: "dict[str, object]" = {
    "tags": {}, "last_run_at": "", "group": "", "favorited_at": "",
    # 검토 기준선(재작성 F5)도 **비-편집 메타**다: 에디터가 소유하는 것은 규칙(템플릿·매핑·
    # 파일명)이고, "마지막 완주가 그중 무엇을 썼는가"는 실행 이력의 일이다. 안 되싣으면
    # 규칙을 하나도 안 바꾸고 저장만 해도 기준선이 비어(§13-2 의 조용한 반복이 깨지고)
    # 다음 실행이 가장 무거운 검토를 다시 요구한다(3R P2).
    "reviewed_rules": {},
    # S3 권위 Work identity(S3-09) — 에디터가 소유하는 것은 규칙이고 identity 결속은
    # 템플릿 변경 코디네이터의 일이다. 안 되싣으면 규칙 저장 한 번이 작업의 적용
    # 이력(epoch·Preparation)을 조용히 끊는다.
    "authority_id": "",
}


#: 풀 seam 미배선(테스트 단독 구동·비완전 조립)의 거절 문구 — 없는 표면을 있다고 말하지
#: 않는다. 제품 조립은 늘 배선돼 있어 이 문구는 오배선의 신호다.
POOL_UNWIRED_TEXT = "등록 데이터 목록을 읽을 수 없습니다."


def _binding_source_ref(job: "Job") -> "dict | None":
    """저장본의 데이터 결속을 **인계 참조 한 벌**로 — 미결속이면 ``None``.

    ``{path, sheet, header_row, kind}`` 는 :meth:`EditorController._load_source_ref` 가 받는
    형상 그대로다(#878 인계와 같은 문). 결속을 경로 하나로 줄이지 않는 이유도 같다:
    참조 성분을 흘리면 마법사가 **다른 헤더**에 앵커를 걸고 그 어긋남은 화면 어디에도
    표시가 없다(#349 리뷰 P1). ``kind`` 도 같은 근거로 함께 간다 — 종류를 흘리면 받는 쪽이
    경로 모양으로 어느 어댑터인지를 되추측한다.
    """
    if not has_data_binding(job):
        return None
    path, sheet, header_row, kind = data_binding_of(job)
    return {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}


def pool_option_block(row: "DatasetPoolRow") -> str:
    """이 등록 데이터를 작업 데이터로 연결할 수 있는가 — 못 쓰면 사유, 쓸 수 있으면 ``""``.

    **숨기지 않고 비활성 + 사유 병기**다(#932 U4-C S2-5, 나라장터 동결 규율과 같은 줄):
    목록에서 지우면 사람이 등록해 둔 항목이 이유 없이 사라진 것으로 보이고, 그 침묵이
    이 라운드가 고치는 결함과 같은 종류다. 판정도 문구도 여기 한 곳이 낸다 — 표면이
    ``status``·``kind`` 로 문장을 다시 지으면 같은 상태가 두 어휘를 갖는다.
    """
    if row.kind != "excel":
        return f"{row.kind_label} 참조라 작업 데이터로 연결할 수 없습니다."
    if row.status != STATUS_ACTIVE:
        return "보관한 항목입니다. '문서 만들기'의 데이터 선택에서 활성화한 뒤 쓰세요."
    if reference_missing(row.locate_path):
        return "참조가 끊겼습니다. '문서 만들기'의 데이터 선택에서 다시 연결한 뒤 쓰세요."
    return ""


def _preserved_meta(job: "Job") -> "dict[str, object]":
    """저장이 그대로 되싣는 비-편집 메타(태그·마지막 실행·그룹·즐겨찾기·검토 기준선).

    이 목록이 **완전한지**는 산문이 아니라 구조 가드가 답한다
    (``test_job_editor_state`` 의 durable 필드 분류 가드): durable Job 필드는 저장이
    **다시 짓거나**(편집 대상) **보존하거나**(비-편집 메타) 둘 중 하나여야 하고, 새 필드가
    어느 쪽인지 선언되지 않으면 테스트가 실패한다. 그룹(슬라이스 2)·검토 기준선(F5 3R)이
    같은 자리에서 조용히 사라졌다 — 두 번 같은 결함이면 목록이 아니라 규율이 문제다.
    """
    return {
        "tags": dict(job.tags),
        "last_run_at": job.last_run_at,
        "group": job.group,
        "favorited_at": job.favorited_at,
        "reviewed_rules": dict(job.reviewed_rules),
        "authority_id": job.authority_id,
    }


class EditorController:
    """작업 에디터 화면 — 마법사 세션 상태 소유·링1 VM 위임."""

    name = "editor"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        clock: Callable[[], datetime],
        pool_registry: "DatasetPoolRegistry | None" = None,
        template_library: "TemplateManagerViewModel | None" = None,
        template_groups: "TemplateGroupModel | None" = None,
        text_registry: "TextTemplateRegistry | None" = None,
        txt_groups: "TemplateGroupModel | None" = None,
        library_result: "Callable[[], dict] | None" = None,
        library_slots: "Callable[[], dict | None] | None" = None,
        after_mapping_saved: "Callable[[str], object] | None" = None,
        binding_confirm_pending: "Callable[[str], bool] | None" = None,
        tutorial: TutorialSink = unwired_tutorial,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self._clock = clock
        # 튜토리얼 마일스톤 통지(#894) — 이 채널이 소유하는 전이 넷: 템플릿 적용(T1)·매핑
        # 전확정(T2)·작업 저장(T3 HWPX / T10 TXT)·비움 확정(T14). 전부 **이미 성립한** 전이
        # 지점에서만 부르고, 어느 것도 여기서 다시 판정하지 않는다.
        self._tutorial = tutorial
        # 등록 데이터(풀) 읽기 seam — **재판정으로 되살아났다**(#932 U4-C S2-5). #347 은 이
        # 주입을 지우며 "소비자 0 인 seam 은 남기지 않는다"고 적었고 그때는 사실이었다:
        # 자동등록·기본 데이터 재진술이 함께 죽어 이 화면이 풀을 읽을 일이 없었다. 지금은
        # 다르다 — 데이터 결속이 저장 게이트라 마법사가 데이터를 **고르는** 표면이고,
        # 「고정해 둔 데이터」를 마법사에서 못 고르면 사람은 같은 파일을 매번 다시 찾아야
        # 한다. 쓰기는 여기 없다(등록·다시 연결·삭제는 데이터 선택 면의 일). 미주입이면
        # 그 사실을 스냅샷이 말하고 목록 동사는 서지 않는다.
        self._pool_registry = pool_registry
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
        # TXT 템플릿 레지스트리·그룹 모델(F6 PR-B — 「템플릿」 탭 매체 분기): **앱 조립에선
        # tpl 화면과 같은 인스턴스를 주입**한다(hwpx 라이브러리·그룹과 같은 단일 실체 규율 —
        # 별도 인스턴스면 접힘·목록이 두 표면에서 갈린다). 미주입 시 표준 루트 지연 생성.
        self._text_registry = text_registry
        self._txt_groups = txt_groups
        # 라이브러리 결과 재진술 줄(F8 — tpl 화면 사망의 `#tplResult` 승계): 성형·수명은
        # TemplateController(result_text/level)가 계속 소유하고 여기는 **읽기만** 한다(성형
        # 두 벌 금지 — §10.17.2 판정 B). 미주입(테스트 단독 구동)은 빈 결과.
        self._library_result = library_result
        # 검토가 낸 Slot 목록(S8-03 #834) — 결과 줄과 같은 규율(투영·수명은 tpl 소유,
        # 여기는 읽기만). 미주입(테스트 단독 구동)은 목록 없음.
        self._library_slots = library_slots
        self._after_mapping_saved = after_mapping_saved
        # 연결 확정 대기 판정(#911) — `after_mapping_saved` 와 **같은 짝의 반대편**이다(쓰기 ↔
        # 읽기). 판정·문안은 백엔드 소유이고 이 화면은 사실 하나를 싣기만 한다. 미주입(테스트
        # 단독 구동·비관리 조립)이면 확정 대기는 없다 — 없는 표면을 있다고 말하지 않는다.
        self._binding_confirm_pending_probe = binding_confirm_pending
        self._reset()

    def _reset(self) -> None:
        # 현재 탭 = 계약 §5.1 의 section 문자열(재작성 F7 판정 B — 정수 단계 어휘 사망).
        self.section = SECTION_TEMPLATE
        # 편집 거래(§5.2) — 새 세션은 **초안**이라 base 가 없다(§10.13 판정 P): 비교 대상이
        # 없는 것을 patch 로 부르면 첫 저장이 "전 필드가 바뀝니다"를 재진술하게 된다.
        self.session = EditSession(context=make_context(""), base=None, section=self.section)
        self.template_path = ""
        self.schema = None
        self.gate: "PartialGate | None" = None
        self.gate_error = False
        self.raw_block = ""
        self.data_path = ""
        self.data_sheet = ""  # 다중 시트 확정값(#33) — 자동등록 참조에 함께 저장(#26)
        # 헤더 행(엑셀 참조 옵션) — 0 = 미지정(어댑터 기본 1행). 등록 데이터를 든 진입
        # (#349 리뷰 P1)이 채운다: 참조를 경로로만 줄이면 사용자가 고른 것과 **다른 헤더**로
        # 마법사가 서고, 그 어긋남은 화면 어디에도 표시가 없다.
        self.data_header_row = 0
        # 결속의 **종류**(""=엑셀/CSV) — 위 세 성분과 한 벌이다. 저장이 그대로 Job 에 실어
        # durable 이 되므로(`_EDITOR_REBUILDS` 갈래) 세션 리셋에서 함께 선다.
        self.data_kind = ""
        # 이 세션이 **서 있는 기준**의 데이터(#878) — 진입이 들고 온 것이면 그 참조, 사람이
        # 관문에서 고른 것이면 빈 값. `_extras_of` 의 기준값이라 「저장본과 다르다」의 뜻이
        # 여기서 갈린다: 인계 데이터를 변경으로 세면 손대지도 않은 진입이 곧바로 미저장이 돼
        # 이탈마다 헛확인이 뜬다(사람이 그 파일을 고른 적이 없다).
        self._entry_data: "dict[str, str]" = {"data_path": "", "data_sheet": ""}
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
        # (dataset_name·default_dataset_ref·_dataset_existing 은 #347 에서 사망 — 저장 시
        #  데이터 자동등록(#18·#26)과 작업↔데이터 결속(#53-A)이 U2 §5.3 판정 D 로 폐기됐다.
        #  등록은 데이터 선택 면의 「이 데이터 고정」 명시 행동 하나다.)
        # 편집 모드 상태(#26): 원점 이름(자기-갱신 판정)·보존 메타(:func:`_preserved_meta`) —
        # 편집 저장이 브라우저 태그·이력·구획·순위를 조용히 소실시키지 않는다.
        self._editing_origin = ""
        self._preserved_meta: "dict[str, object]" = dict(_EMPTY_PRESERVED)
        # 로드 시점 작업 내용 지문(태그·마지막 실행 제외) — 자기-갱신 저장이 편집 중
        # 외부 변경을 무확인으로 덮지 않게 하는 근거(_do_save 확인 게이트).
        self._editing_fingerprint = ""
        # 편집 모드에서 복원한 작성 출처 메타(#53-C) — 표시용 + 재저장 시 최초 작성시각 보존.
        self._loaded_provenance: "dict[str, str]" = {}
        # 진입·저장 착지가 결속 데이터를 다시 읽다 실패한 사유(#932 U4-C S2-1·S2-2).
        # 통지 문장을 짓는 자리가 둘(진입 notice / 저장 착지 notice)이라 사유를 값으로
        # 든다 — 실패를 성공 문안으로 덮으면 저장 뒤 화면이 빈 데이터 관문인 채로 "저장
        # 했습니다"만 말한다.
        self._reload_failure = ""
        self.notice_text = ""  # 복원·프로파일 반영 등 세션 통지(loud 재진술 채널)
        self.notice_level = "muted"
        # (별도 라이브러리 행 캐시 없음 — #138 리뷰 F8·F11: 공유 VM rows() 직독으로 발산 제거.)
        # 클린 세션 표지 — 편집 복원 직후·저장 착지 직후처럼 "디스크 저장본과 동일" 상태.
        # 사용자가 손대면(변이 액션·데이터/템플릿 로드) 꺼진다. has_unsaved_work 가 소비해
        # 미변경 세션의 헛확인(폐기 확인·T2 고지)을 억제한다(리뷰 — confirm-or-alarm 의
        # 「불필요한 프롬프트 억제」 확장).
        self._session_clean = False
        # 「모두 해제」 직전 확정 집합 1슬롯. 다음 해제/세션 리셋이 덮으며 durable 저장하지 않는다.
        self._unconfirm_undo: "list[int]" = []
        # 연결 확정 대기(#911) — **저장본**의 사실이라 세션 편집 중에는 움직이지 않는다. 그래서
        # 매 스냅샷마다 다시 묻지 않고 진입(:meth:`load_job`)과 저장 착지에서만 새로 잰다:
        # 판정은 durable 저장소를 mutation fence 안에서 읽는 일이라 렌더 경로에서 반복하면
        # 타이핑 한 번마다 그 값을 문다.
        self._binding_confirm_pending = False

    def _refresh_binding_confirm_pending(self) -> None:
        """저장본 기준으로 연결 확정 대기를 다시 잰다 — 진입·저장 착지 두 자리에서만 부른다.

        초안은 저장본이 없어 잴 것도 없다(권위 발급 자체가 저장 뒤의 일이다). 판정 실패는
        「대기 아님」으로 접는다: 확정할 수 없는 상태에서 확정 동사를 세우면 그 동사는 눌러도
        아무 일도 안 하고, 그 침묵이 지금 고치는 결함과 같은 것이다.
        """
        probe = self._binding_confirm_pending_probe
        if probe is None or not self._editing_origin or not self.job_name:
            self._binding_confirm_pending = False
            return
        try:
            self._binding_confirm_pending = bool(probe(self.job_name))
        except Exception:  # noqa: BLE001 - 판정 불가 = 확정 동사 없음(거짓 무장 금지).
            self._binding_confirm_pending = False

    def _set_notice(self, text: str, level: str = "muted") -> None:
        self.notice_text = text
        self.notice_level = level

    @property
    def template_library(self) -> TemplateManagerViewModel:
        """템플릿 라이브러리 VM — 미주입이면 첫 접근 때 표준 라이브러리로 지연 생성(리뷰 F5)."""
        if self._template_library is None:
            self._template_library = TemplateManagerViewModel(
                default_templates_dir(),
                inspect_template=inspect_hwpx_template,
                file_ops=HWPX_TEMPLATE_OPS,
            )
        return self._template_library

    @property
    def template_groups(self) -> TemplateGroupModel:
        """HWPX 그룹 모델 — 미주입이면 첫 접근 때 표준 hwpx 모델 지연 생성(라이브러리 VM 대칭)."""
        if self._template_groups is None:
            self._template_groups = TemplateGroupModel("hwpx")
        return self._template_groups

    @property
    def text_registry(self) -> TextTemplateRegistry:
        """TXT 템플릿 레지스트리 — 미주입이면 표준 루트 지연 생성(hwpx 라이브러리 VM 대칭)."""
        if self._text_registry is None:
            self._text_registry = TextTemplateRegistry(default_text_templates_dir())
        return self._text_registry

    @property
    def txt_groups(self) -> TemplateGroupModel:
        """TXT 그룹 모델 — 미주입이면 표준 txt 모델 지연 생성(template_groups 대칭)."""
        if self._txt_groups is None:
            self._txt_groups = TemplateGroupModel("txt")
        return self._txt_groups

    def _refresh_library(self) -> None:
        """공유 라이브러리 VM 재스캔 — 외부(탐색기) 변경을 새 세션·가져오기 시점에 걷는다.

        별도 행 캐시는 두지 않는다(#138 리뷰 F8·F11): ``_library_snapshot`` 이 공유 VM 의
        ``rows()`` 를 직독하므로, 이 refresh 는 공유 VM 의 실 디스크 재스캔만 트리거하면 된다."""
        self.template_library.refresh()

    def assert_library_path(self, path: str) -> None:
        """웹 유래 템플릿 경로의 라이브러리 소속 확인 — 바깥 입구 봉쇄의 공용 seam(리뷰 F4).

        use_library_template 가 쓴다(구 크로스스크린 load_template_into_editor 는 F8 사망) —
        한 입구만 막으면 「가져오기=복사가 유일한 바깥 입구」(2부)가 문서만의 불변식이 된다.
        불일치면 **새 스캔 결과를 먼저 push** 하고 거절한다(리뷰 F7: 방금 삭제된 파일의
        stale 행이 남아 같은 클릭을 반복하게 만드는 무행동 안내 금지 — 목록이 스스로 걷힌다).

        TXT 경로(F6 PR-B)는 TXT 레지스트리 소속을 같은 규율로 확인한다 — 레지스트리는
        캐시 없이 매번 실 디스크를 스캔하므로 별도 refresh 없이 판정 자체가 최신이다.
        """
        if template_media(path) == "txt":
            if all(str(t.path) != path for t in self.text_registry.list_templates()):
                self._push()  # 다음 스냅샷의 목록이 최신 스캔 — 거절 문구가 실행 가능해진다
                raise ValueError("라이브러리에 없는 템플릿입니다. 목록을 새로 고쳤으니 다시 고르세요.")
            return
        self._refresh_library()
        if all(r.path != path for r in self.template_library.rows()):
            self._push()  # 갱신된 목록을 먼저 보여준다 — 거절 문구가 실행 가능해진다
            raise ValueError("라이브러리에 없는 템플릿입니다. 목록을 새로 고쳤으니 다시 고르세요.")

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 진행 게이트
    def _template_ready(self) -> bool:
        return (
            self.schema is not None and bool(self.schema.fields) and not self.gate_error
            and (self.gate is None or self.gate.can_proceed())
        )

    def sections(self) -> "tuple[str, ...]":
        """이 세션의 탭 구성 — **매체 파생**(§10.13 판정 A). TXT 합류(F6 PR-B) 뒤에도
        템플릿 미선택 초안은 hwpx 구성으로 두되, TXT 를 고르면 파생이 파일 이름 탭을
        걷는다(§3.2 — 파일을 만들지 않는 작업). 미선택 폴백을 hwpx 로 두는 이유: 단계
        표지는 「고르면 무엇이 이어지는가」의 안내이고, 고르는 순간 실 매체로 정정된다
        (탭 접근은 전진 게이트가 템플릿 확정 전엔 어차피 막는다)."""
        return sections_for(
            template_media(self.template_path) if self.template_path else "hwpx"
        )

    def can_advance(self, from_section: str) -> bool:
        """`from_section` → 그 다음 탭으로의 진행 가부(신규 초안의 전진 게이트).

        3단계 접기(블록 2 결정 11): 데이터 선택이 매핑 탭의 관문으로 들어와 별도 단계가
        아니다 — 템플릿→연결은 템플릿 준비, 연결→파일 이름은 매핑 확정.

        **초안에만 걸리는 규율**(§10.13 판정 M): 저장된 작업 편집은 의존이 전부 충족된
        상태라 탭을 자유 이동한다. 초안은 순서 의존이 실재해(템플릿 없인 매핑 없음) 전진
        마다 게이트를 세운다 — 빈 표를 열어 두고 "채우세요"라고 말하지 않는다.
        """
        if from_section == SECTION_TEMPLATE:
            return self._template_ready()
        if from_section == SECTION_BINDING:
            return self.model is not None and self.model.is_complete()
        return False

    def _draft_job(self) -> "Job":
        """지금 세션이 저장한다면 나올 규칙만 담은 Job — patch 유도의 오른쪽 항.

        이름·기본 데이터 참조는 담지 않는다: 규칙이 아니라 정체·조준 힌트라 section 에
        속하지 않는다(§10.13 판정 L). 매핑은 **확정 행만**(:meth:`MappingModel.to_profile`)
        — 저장되는 것과 같은 집합이어야 "저장하면 무엇이 달라지나"가 참이 된다. 확정하지
        않은 편집은 :func:`dirty_sections` 의 ``pending_binding`` 이 따로 센다.
        """
        return Job(
            template_path=self.template_path,
            mapping=self.model.to_profile() if self.model is not None else MappingProfile(),
            filename_pattern=self.pattern,
        )

    def _pending_binding(self) -> bool:
        """확정되지 않은 사람 손길이 매핑에 남아 있는가 — 버리면 사라지는 편집."""
        if self.model is None:
            return False
        return any(r.touched and not r.confirmed for r in self.model.rows)

    def dirty_sections(self) -> "tuple[str, ...]":
        return self.session.dirty(self._draft_job(), pending_binding=self._pending_binding())

    # ------------------------------------ section 밖 세션 상태의 열거(8R 근본 조치)
    #
    # 어느 section 에도 속하지 않으면서 **저장되면 durable 로 가는** 세션 값의 전체 목록
    # (§10.13 판정 L). 이 튜플에 이름이 없으면 어떤 판정도 그 값을 세지 못한다 — 이탈
    # 가드·머리의 「저장됨」 표지·되돌리기 범위·되돌린 뒤의 정체 판정이 전부 여기서 파생된다.
    #
    # **왜 상수로 세우는가**: F7 리뷰는 같은 결함을 라운드마다 한 값씩 재발견했다(2R 이름 →
    # 3R 자동등록 이름 → 5R 데이터 선택 → 8R 전체 버리기의 과보존). 원인은 판정이 틀렸던
    # 것이 아니라 **열거가 판정마다 손으로 다시 쓰여 있던 것**이다. 새 세션 값을 더하는
    # 사람은 여기 한 줄만 고치면 네 판정이 함께 따라온다.
    #
    # ``data_sheet`` 가 함께 있는 이유(열거를 세우자 드러난 자리): 같은 엑셀의 **다른 시트**로
    # 갈아타면 경로는 그대로다 — 시트가 빠지면 그 갈아타기만 「저장됨」으로 위장한다(#33).
    # (dataset_name 은 자동등록(#18·#26)과 함께 사망 — #347, U2 §5.3 판정 D.)
    SESSION_EXTRAS = ("job_name", "data_path", "data_sheet")

    def _extras_now(self) -> "dict[str, str]":
        return {
            "job_name": self.job_name,
            "data_path": self.data_path,
            "data_sheet": self.data_sheet,
        }

    def _extras_of(self, base: "Job") -> "dict[str, str]":
        """이 세션이 **서 있는 기준**의 extras — 이름은 저장본의 것, 데이터는 진입이 세운 것.

        데이터 선택은 작업에 저장되지 않으므로(§5.3 — 작업↔데이터 결속 없음) 기준값을 저장본이
        낼 수 없다. 사람이 관문에서 고른 데이터는 종전대로 빈 기준 대비 「달라진 것」이고,
        **진입이 들고 온 데이터**(#878 인계)는 사람이 고른 적이 없으므로 기준 그 자체다 —
        그렇게 세지 않으면 아무것도 손대지 않은 수리 진입이 열리자마자 미저장이 된다.
        """
        return {"job_name": base.name, **self._entry_data}

    def dirty_extras(self) -> "tuple[str, ...]":
        """저장본 대비 달라진 extras 이름들 — 초안은 비교 대상이 없어 빈 튜플이다."""
        base = self.session.base
        if base is None:
            return ()
        now, was = self._extras_now(), self._extras_of(base)
        return tuple(k for k in self.SESSION_EXTRAS if now[k] != was[k])

    # --------------------------------------------------- 활성 헤더(#49)
    def _active_sources(self) -> "list[str]":
        """미사용을 뺀 활성 헤더(원 순서 보존) — 자동 제안·소스 드롭다운 후보의 단일 출처."""
        return [f for f in self.source_fields if f not in self._ignored_sources]

    # ------------------------------------------------------------- 스냅샷
    def _model_key_now(self) -> tuple:
        """매핑 모델의 **정체 키** — 짓는 자리를 하나로 모은다(성분 누락 = 조용한 우회).

        성분: 템플릿 · 데이터 경로 · 확정 시트 · **헤더 행** · 전체 소스 헤더. 세 자리가
        각자 짓던 것을 여기로 모은 이유가 곧 새 성분이 필요해진 이유다 — 한 곳만 빠뜨리면
        복원 세션의 키가 진입 세션과 달라 매핑이 조용히 재생성되거나(확정 전멸) 반대로
        바뀐 데이터에서 재생성이 안 일어난다.

        ``header_row`` 가 든 근거는 ``data_sheet`` 가 든 근거와 같다(#349 리뷰 P1): 같은
        파일·같은 시트라도 헤더 행이 다르면 다른 데이터인데, 두 판의 헤더 **이름**이 우연히
        겹치면 ``source_fields`` 가 안 바뀌어 키가 불변 → 조기 반환 → 이전 기준의 확정 행이
        그대로 저장·실행된다.
        """
        return (
            self.template_path, self.data_path, self.data_sheet,
            self.data_header_row, tuple(self.source_fields),
        )

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
        sections = self.sections()
        dirty = self.dirty_sections()
        snap: dict = {
            # 계약 §5.1 의 section 어휘 하나로 탭·patch·액션이 같은 문자열을 쓴다(판정 B).
            "section": self.section,
            "sections": list(sections),
            # 전진 게이트는 **초안에만**(판정 M) — 편집은 자유 이동이라 전부 True.
            "reachable": {
                s: (True if self._editing_origin else self.can_advance(s)) for s in sections
            },
            # 거래 상태(§5.2) — 손댄 자리(가드가 본다)와 저장하면 달라지는 것(재진술·판본이
            # 본다)을 **따로** 낸다. 둘을 하나로 뭉치면 미확정 편집이 조용히 버려진다.
            "is_draft": self.session.is_draft,
            "dirty_sections": list(dirty),
            # **"이 세션이 잃을 것이 있는가"의 단일 출처**(3R 근본 조치). 표면이 이 판정을
            # 스스로 조립하면(길이 검사 + 세션 표지) 소비자마다 다르게 답한다 — 실제로
            # 2R 은 이탈 가드만 고쳤고 머리·footer 는 「저장됨」이라 말하고 있었다.
            # `dirty_sections` 는 **탭 표지**의 자리이고, 세션 수준 판정은 이 값 하나다:
            # 이름·자동등록 이름처럼 어느 section 에도 없는 편집(판정 L)이 여기 든다.
            "dirty": bool(dirty) or self.has_unsaved_work(),
            "changes": self.session.changes(self._draft_job()),
            "context": self.session.context.to_dict(),
            # 판본(F7 판정 O 표시 자리 ①) — 저장된 작업만 세대가 있다. 초안은 아직 없다:
            # 저장되지 않은 규칙에 r1 을 붙이면 있지도 않은 세대를 말하게 된다.
            "revisions": (
                {
                    "template": self.session.base.template_revision,
                    "binding": self.session.base.binding_revision,
                }
                if self.session.base is not None else {}
            ),
            "template_path": self.template_path,
            "template_name": self.template_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
            # 선택 템플릿의 매체(F6 PR-B) — 뷰가 확장자를 재파싱하지 않게 판정을 싣는다.
            "template_media": template_media(self.template_path) if self.template_path else "",
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
            # 등록 데이터에서 고르기가 이 조립에 서 있는가(#932 U4-C S2-5) — 목록 자체는
            # 사건 때만 읽는다(`pool_options`). 미배선 조립에서 동사를 세우면 눌러도 아무
            # 일도 안 일어나고, 그 침묵이 이 라운드가 고치는 결함과 같은 종류다.
            "pool_enabled": self._pool_registry is not None,
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
            # 연결 확정 대기(#911) — footer 무장 사유를 **더한다**(빼지 않는다). dirty 기반
            # 무장은 그대로고, 바꿀 것이 없는데 관리 검토가 확정을 기다리는 상태에서만 이
            # 사실이 참이다. 판정·라벨·설명은 전부 여기서 실어 보낸다: 표면이 「저장 안 됨」
            # 같은 인접 사실로 확정 필요를 추론하면 두 곳이 같은 상태를 다르게 답한다.
            "binding_confirm": {
                "pending": self._binding_confirm_pending,
                "label": BINDING_CONFIRM_LABEL,
                "hint": BINDING_CONFIRM_HINT,
            },
            "unconfirm_undo_count": len(self._unconfirm_undo),
            # #26 편집 모드·프로파일 표면. (dataset_name·default_dataset 스냅샷 키는 #347
            # 에서 사망 — 자동등록·기본 데이터 연결이 U2 §5.3 판정 D 로 폐기됐다.)
            "editing_origin": self._editing_origin,
            # 작성 출처 provenance(#53-C) — 편집 모드에서 복원한 것(없으면 None).
            "provenance": self._loaded_provenance or None,
            # 템플릿 라이브러리(신규 1단계=라이브러리에서 그룹 구획으로 고르기, #108 슬라이스 3)
            # — 템플릿 분류(0)에서만 스캔한다(파일시스템 재스캔이라 매핑 편집의 잦은 push 에 지불
            # 금지). 그 외 단계는 빈 구획. F6 PR-B: 매체 2밴드({hwpx, txt}).
            "library": (
                self._library_snapshot() if self.section == SECTION_TEMPLATE
                else {
                    "hwpx": {"sections": [], "flat": True},
                    "txt": {"sections": [], "flat": True},
                }
            ),
            # F26 — 파일명 라이브 예시(표본 1행 고정). 저장 분류(2)에서만 계산.
            "pattern_preview": (
                self._pattern_preview() if self.section == SECTION_FILENAME else ""
            ),
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

        **매체 2밴드**(F6 PR-B — 「기안」 화면 사망의 승계처): ``{hwpx: {...}, txt: {...}}``.
        어느 밴드든 관리 화면과 같은 그룹 모델·같은 build_sections 로 성형해 두 표면이 한
        조직을 보인다(결정 6). 여기는 **선택 전용** — 카드 ⋮·이동·삭제·＋그룹지정 없이 상태
        배지·선택 버튼만. HWPX 상태 판정·배지는 링1(TemplateManagerViewModel) 소유, TXT 는
        tpl 화면 ``_txt_rows`` 와 같은 성형(필드 수·손상 loud). 오류 행도 숨기지 않는다.

        **공유 VM 직독**(#137·#138 리뷰 F8·F11): 별도 행 캐시를 두지 않고 공유 VM 의
        ``rows()``(재스캔 없이 캐시 반환)를 그대로 읽는다 — 관리 화면의 가져오기·삭제가
        공유 VM 을 refresh 하면 여기 피커도 즉시 반영된다(발산 캐시 제거). TXT 레지스트리는
        캐시가 없어 매 스냅샷이 실 스캔이다. **reconcile 미실행**:
        유령 지정 정리는 관리 화면의 위생 소관이고, 여기서 (부분/필터된) 목록으로 reconcile 하면
        살아있는 그룹 지정을 영구 삭제할 수 있어 실행하지 않는다(build_sections 는 표시에서
        고아를 이미 무시).
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
                # 채움 완화 사전 고지(#154) — tpl 화면 사망(F8)의 가시성 승계. 문안은 링1 확정.
                "fill_warns": list(r.fill_warns),
                # 상태 수선 동사(compile·review) — 라벨·구성은 링1 `_STATE_ACTIONS` 소유.
                # `preview` 는 #13 결정(10F2FF98-B), `make_job` 은 행 「이 템플릿으로」 버튼이
                # 이미 소유(같은 동사 2벌 금지 — §10.17.2 판정 D)라 여기서 걷는다.
                "actions": [
                    {"key": a.key, "label": a.label}
                    for a in r.actions() if a.key not in _PICKER_HIDDEN_ACTIONS
                ],
                "current": bool(self.template_path) and r.path == self.template_path,
            }
            for r in self.template_library.rows()
        ]
        # 그룹 축은 묻지 않는다(U4 §2-30) — 지정을 바꿀 동사가 표면에서 걷혔으므로 저장된
        # 지정이 남아 있어도 평면으로 답한다. 모델·영속은 동결이라 되살릴 때 그대로 쓴다.
        sections, flat = self.template_groups.build_sections(
            items, key_of=lambda it: it["key"], grouped_view=False
        )
        txt_rows = self._txt_library_rows()
        txt_sections, txt_flat = self.txt_groups.build_sections(
            txt_rows, key_of=lambda it: it["key"], grouped_view=False
        )
        # 밴드에 싣는 것은 개수·루트 경로다(이동 다이얼로그의 그룹 후보는 U4 §2-30 에서
        # 그 다이얼로그와 함께 걷혔다). **reconcile 은 여기서도 하지 않는다** — 유령 지정
        # 위생은 tpl 채널의 snapshot() 이 계속 소유한다(부분 목록 reconcile 이 살아있는
        # 지정을 지우는 결함 클래스 봉쇄, 위 docstring).
        result = self._library_result() if self._library_result is not None else {}
        return {
            "hwpx": {
                "sections": sections, "flat": flat,
                "count": len(items),
                "dir": str(root) if root is not None else "",
            },
            "txt": {
                "sections": txt_sections, "flat": txt_flat,
                "count": len(txt_rows),
                "dir": str(self.text_registry.directory),
            },
            "result": {
                "text": str(result.get("text", "") or ""),
                "level": str(result.get("level", "muted") or "muted"),
            },
            # 검토가 낸 Slot 목록(S8-03) — 없으면 ``None`` 이고 표면은 구획째 서지 않는다.
            "slots": self._library_slots() if self._library_slots is not None else None,
            # 동봉 예제 상시 진입점(#891 · §4.1) — 밴드의 ``emptyText`` 는 문자열 prop 이라
            # 버튼을 품지 못하므로 밴드 **밖** 공용 버튼 줄이 그 자리다. 라벨·설치 여부는
            # tpl·라이브러리 스냅샷과 같은 단일 출처를 읽는다(세 표면이 한 판정을 본다).
            "examples": example_pack.entry_point_state(),
        }

    def _txt_library_rows(self) -> "list[dict]":
        """TXT 밴드 행 — tpl 화면 ``_txt_rows`` 성형 미러(선택 전용 최소분 + current 표지).

        손상(비 UTF-8 등)은 삭제 가능한 오류 행으로 loud 노출한다(숨기면 관리 화면과 다른
        목록을 조용히 보인다). 필드 수는 토큰 유무의 사전 신호일 뿐 차단은 로드가 맡는다.
        """
        root = self.text_registry.directory
        rows: "list[dict]" = []
        for t in self.text_registry.list_templates():
            error = ""
            field_count = 0
            try:
                field_count = len(t.fields())
            except Exception as exc:  # noqa: BLE001 — 손상 파일도 loud 노출(tpl 화면 동형)
                error = str(exc)
            key = rel_key(t.path, root)
            rows.append({
                "key": key,
                "name": t.name,
                "path": str(t.path),
                "field_count": field_count,
                "error": error,
                "current": bool(self.template_path) and str(t.path) == self.template_path,
            })
        return rows

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
            return make_output_filename(self.pattern, data, now=self._clock())
        except Exception:  # noqa: BLE001 — 표시 전용(저장 게이트가 검증 소관)
            return ""

    # (_default_dataset_snapshot(#53-A 기본 데이터 연결 상태 재진술)은 #347 에서 삭제 —
    #  작업↔데이터 결속이 폐기돼 재진술할 참조 자체가 없다. U2 §5.3 판정 D.)

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
        now = self._clock().isoformat(timespec="seconds")
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
        # 데이터 표시명: 이번에 데이터를 골랐으면 그 파일 스템, 아니면(편집 저장) 복원 출처 보존.
        dataset = (
            Path(self.data_path).stem if self.data_path
            else self._loaded_provenance.get("dataset", "")
        )
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
    def close_guard_reason(self) -> str:
        """창 종료 가드 참여(F6 1R) — 잃을 것이 있으면 사유, 없으면 ``""``."""
        return "저장하지 않은 작업 편집" if self.has_unsaved_work() else ""

    def has_unsaved_work(self) -> bool:
        """버려질 **미저장** 변경이 있는가 — 폐기 전 확인·T2 고지 판단에 쓴다(#25).

        **저장된 작업 편집은 세어서 답한다**(8R 근본 조치): 잃을 것은 section patch
        (:meth:`dirty_sections`) 와 section 밖 세션 상태(:meth:`dirty_extras`) 의 합집합이고,
        둘 다 저장본과의 비교로 **파생**된다. 종전엔 손으로 켜고 끄는 표지(``_session_clean``)
        가 이 답을 대신했는데, 변이 자리와 되돌리기 자리가 늘 때마다 한 곳이 빠졌다 — 빠짐은
        「저장됨」이라는 거짓말(미저장 입력을 저장됨으로 표시)이나 되돌린 뒤의 헛확인으로
        나타났고, 라운드마다 그 두 얼굴 중 하나가 다시 잡혔다. 파생은 빠질 자리가 없다:
        되돌리면 비교가 같아져 저절로 깨끗해지고, 손대면 저절로 더러워진다.

        초안(base 없음)은 비교 대상이 없어 종전 판정을 그대로 쓴다 — ``_reset()`` 직후엔
        False, 클린 표지가 서 있으면 False, 그 외엔 이름·데이터·매핑 모델 중 하나라도 있으면
        사용자가 손댄 세션이므로 True(템플릿만 갓 로드한 상태는 아직 버릴 게 없어 False).
        """
        if self.session.base is not None:
            return bool(self.dirty_sections()) or bool(self.dirty_extras())
        if self._session_clean:
            return False
        return bool(self.job_name or self.data_path or self.model is not None)

    def new_job_session(self, path: str) -> None:
        """새 작업 세션을 원자적으로 시작 — 이전 세션 전량 초기화 후 템플릿 로드(#25).

        템플릿→에디터 진입(템플릿 관리 '작업 만들기', 에디터 0단계 피커)의 단일 seam.
        ``load_template_path`` 만 부르면 이름·데이터·매핑·단계가 이전 세션 값으로 남아
        새 템플릿과 섞인 혼합 세션이 조용히 저장될 수 있다 — 여기서 ``_reset()`` 로
        먼저 끊는다. 미저장 확인은 호출측(브리지/웹)이 ``has_unsaved_work`` 로 선판단한다.

        **예외 하나 — 데이터를 들고 온 진입**(U2 §2.4 · #349 리뷰 3R, #878): 그 세션의 데이터는
        「이전 세션의 잔재」가 아니라 **이 세션이 존재하는 이유**다. 1단계에서 템플릿을 고르는
        것은 마법사의 정상 진행인데, 그때 이 seam 이 앵커를 지우면 「이 데이터로 새 작업」이
        **모든 사용자에게** 보통의 빈 초안으로 퇴화한다(선언은 살고 결과가 죽는 자리).
        진입 문맥도 함께 산다 — 문맥이 죽으면 다음 템플릿 교체에서 앵커도 함께 죽고, 배너가
        말한 복귀처도 사라진다. 되싣는 것은 **데이터 문맥과 진입 문맥뿐**이고 이름·매핑·
        단계는 종전대로 끊긴다(혼합 세션 금지는 그대로다).
        """
        anchor = self._anchor_stash()
        self._reset()
        self._restore_anchor(anchor)
        self.load_template_path(path)

    def _anchor_stash(self) -> "dict":
        """템플릿 교체를 건너 살아야 할 것 — 없으면 빈 사전(호출측 분기 없음).

        판정은 **진입 사유** 하나다(:data:`DATA_ANCHORED_ENTRY_REASONS` 단일 출처): 데이터가
        있는 세션이라고 다 앵커가 아니다 — 관문에서 데이터를 골랐다가 1단계로 되돌아온
        세션은 종전대로 끊긴다(그쪽은 계약이 바뀐 적이 없다).

        저장본 유무(``session.base``)는 **보지 않는다**(#878). 종전엔 초안만 앵커였는데,
        데이터를 들고 오는 진입이 「이 데이터로 새 작업」(초안)뿐이라 그 조건이 사유 조건과
        구별되지 않았다. 수리 진입은 저장된 작업을 여는데(base 있음) 그 데이터도 진입이
        들고 온 것이고, 템플릿을 갈아 끼우는 것은 그 세션의 정상 진행이다.
        """
        context = self.session.context
        if context.entry_reason not in DATA_ANCHORED_ENTRY_REASONS or not self.data_path:
            return {}
        return {"context": context, "data": self._data_stash()}

    def _restore_anchor(self, anchor: "dict") -> None:
        """초기화 뒤 앵커 복원 — 데이터는 :meth:`_data_stash` 한 벌 그대로.

        ``_apply_data_stash`` 가 아니라 값 대입인 이유: 저쪽은 ``_ensure_model`` 을 태우는데
        여기선 템플릿(스키마)이 **아직 로드되기 전**이다. 모델은 종전 경로 그대로 2단계
        진입이 세운다(``goto_section`` → ``_ensure_model``) — 관문의 불변식을 우회하지 않는다.
        """
        if not anchor:
            return
        data = anchor["data"]
        self.data_path = data["data_path"]
        self.data_sheet = data["data_sheet"]
        self.data_header_row = data["data_header_row"]
        self.data_kind = data["data_kind"]
        self.source_fields = list(data["source_fields"])
        self.records = data["records"]
        self.session = EditSession(
            context=anchor["context"], base=None, section=self.section
        )

    def new_draft_with_data(
        self,
        source_ref: dict,
        *,
        entry_reason: str = "voluntary",
        evidence: "dict | None" = None,
        return_context: "dict | None" = None,
    ) -> None:
        """**데이터를 이미 고른 채** 시작하는 신규 초안(U2 §2.4·§4 판정 E, #349).

        마법사는 **새로 짓지 않는다** — 기존 3단계 그대로이고, 달라지는 것은 2단계(필드
        연결) 관문에 「문서 만들기」의 메인 데이터가 **앵커로 이미 서 있다**는 것뿐이다
        (멘탈모델 일관성, 사용자 확정). 그래서 이 seam 은 :meth:`new_job_session` 의
        데이터 판이다: 저쪽은 템플릿을 들고 오고 이쪽은 데이터를 들고 온다.

        **검증이 파기보다 먼저다**: 진입 사유·복귀 표면은 :func:`make_context` 가
        fail-closed 로 보는데, 그 거절이 ``_reset()`` **뒤에** 나면 배선 실수 한 번이
        사용자의 편집 세션을 조용히 지운다. 그래서 문맥을 먼저 세우고 통과한 뒤에 끊는다.

        데이터는 참조로 **다시 읽는다**(:meth:`load_data_path`) — 「문서 만들기」의 적재
        결과를 그대로 넘겨받지 않는 것은 풀 규약(참조만 보관하고 쓸 때 다시 읽음)과 같은
        이유다: 두 화면이 같은 파일의 서로 다른 판을 들고 있게 만들지 않는다. 그 재적재가
        실패하면(파일이 사라짐·잠김·빈 시트) loud 로 올라간다 — 호출측(브리지)이 사유를
        재진술하고, 세션은 이미 확인을 마친 폐기 상태로 남는다.

        ``source_ref`` 는 **참조 전체**다(``{path, sheet, header_row}``, 판정·조립은
        :meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin.new_work_handoff` 단일 출처).
        경로 하나로 줄여 받지 않는 이유가 #349 리뷰 P1 이다: 등록 데이터의 엑셀 참조가 든
        ``header_row`` 를 떨어뜨리면 마법사가 사용자가 고른 것과 **다른 헤더**에 앵커를
        걸고, 그 어긋남은 화면 어디에도 표시가 없다.
        """
        context = make_context(
            "",
            entry_reason=entry_reason,
            evidence=evidence,
            return_context=return_context,
        )
        self._reset()
        self.session = EditSession(context=context, base=None, section=self.section)
        # 템플릿은 아직 없다 — 1단계에서 고른다. 데이터만 먼저 서고 매핑 모델은 2단계 진입
        # (`_do_goto_section` → `_ensure_model`)이 세운다(모델 전 선로드의 기존 경로).
        self._load_source_ref(source_ref)

    # ---------------------------------- 템플릿 라이브러리 피커(R-info 2부 접합 최소분)
    def _do_use_library_template(self, p: dict) -> None:
        """라이브러리 목록에서 고른 템플릿으로 새 작업 세션(신규 1단계 정본 경로).

        경로 화이트리스트는 :meth:`assert_library_path` 공용 seam(리뷰 F4 — 크로스스크린
        진입과 단일 정의). 미저장·편집 맥락 확인은 호출측(웹)이 선판단한다.
        """
        path = str(p["path"])
        self.assert_library_path(path)
        self.new_job_session(path)
        # T1 템플릿 고르기(#894) — 세션에 템플릿이 실제로 앉은 뒤다. 자산 정체성(예제인가)은
        # 따지지 않는다: 루프를 돈 것이 판정이지 예제 강제가 아니다(§3.1-4 비강제).
        self._tutorial(Milestone.PICK_TEMPLATE)

    def adopt_imported_template(self, dest: str) -> str:
        """가져온 사본의 편집기 채택 판정(F8 — §10.17.2 판정 C, 가져오기 통일).

        **복사 권위는 :meth:`TemplateController.import_into_library` 하나다**(잠금·충돌
        접미·무잔재) — 여기는 그 사본으로 「세션을 시작할 수 있는가」만 판정한다.
        시작 가능(hwpx 누름틀 有 / txt UTF-8 판독 가능) = 즉시 새 세션(F7 거동 보존).
        불가(RAW·손상) = **세션 없이 목록 합류** + notice 가 수선 경로(행 ⋮ 변환·삭제)를
        지목한다 — 종전 선거부의 근거(인앱 삭제 어포던스 부재 → 영구 오류 행)는 F8 이
        행 ⋮ 삭제를 들이면서 소멸했다(근거가 죽으면 가드도 걷는다).
        """
        path = Path(dest)
        # 공유 VM 은 import_into_library 가 이미 refresh 했다 — 단독 구동(테스트)만을 위한
        # 재스캔이 아니라, 채택 판정 전 목록 정합의 방어적 재확인(앱에선 무해한 중복).
        self._refresh_library()
        if path.suffix.lower() == ".hwpx":
            try:
                schema = extract_schema(read_hwpx_package(path))
            except Exception:
                self._set_notice(
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다. "
                    "목록의 행 ⋮ 에서 삭제하거나 파일을 확인하세요.",
                    "warn",
                )
                self._push()
                return path.name
            if not schema.fields:
                self._set_notice(
                    f"'{path.name}' 은 누름틀이 없는 원본(RAW)입니다. "
                    "목록의 행 ⋮ → '누름틀로 변환'을 거친 뒤 시작하세요.",
                    "warn",
                )
                self._push()
                return path.name
        else:
            try:
                path.read_text(encoding="utf-8")
            except Exception:
                self._set_notice(
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다(UTF-8 아님). "
                    "목록의 행 ⋮ 에서 삭제하거나 파일을 확인하세요.",
                    "warn",
                )
                self._push()
                return path.name
        self.new_job_session(str(path))
        self._set_notice(f"'{path.name}' 을 라이브러리로 복사해 시작합니다.", "ok")
        self._push()
        return path.name

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_template_path(self, path: str, *, emit_push: bool = True) -> None:
        """선택 템플릿 로드 — **매체 분기**(F6 PR-B). hwpx 는 스키마 추출 + PARTIAL 게이트
        (Qt 위저드 _load_template 미러), txt 는 ``{{토큰}}`` 목록을 동형 스키마로 성형한다.

        txt 스키마를 :class:`TemplateSchema` 로 **동형 성형**하는 이유: ``_ensure_model`` ·
        ``validate_save`` 의 스키마 대조가 매체 무관하게 같은 술어를 돌게 한다(판정 단일
        출처 — 별도 txt 경로를 두면 스키마 정합 게이트를 txt 만 우회한다). PARTIAL 게이트·
        extract_schema 는 hwpx 전용이라 txt 에선 서지 않는다(누름틀이 없는 매체다).
        """
        self._session_clean = False  # 브리지 직행 변이(디스패치 밖) — 클린 표지 해제
        self.template_path = path
        self.gate = None
        self.gate_error = False
        self.raw_block = ""
        if template_media(path) == "txt":
            self._load_txt_template(path)
            if emit_push:
                self._push()
            return
        # 경로 열기는 ring 2 몫(P2-19R) — 한 번 열어 스키마·게이트가 같은 스냅샷을 본다.
        pkg = read_hwpx_package(path)
        self.schema = extract_schema(pkg)
        if not self.schema.fields:  # RAW: 채울 대상 없음 — 시끄럽게 차단.
            self.raw_block = RAW_BLOCK_MESSAGE
            self.schema = None
            if emit_push:
                self._push()
            return
        try:
            self.gate = gate_for_template(pkg)
        except Exception:  # noqa: BLE001  fail-closed(진행 차단)
            self.gate_error = True
        if emit_push:
            self._push()

    # ------------------------------------------- tpl 변이 재정산(S8G-00 #320)
    def reconcile_template_mutation(self, kind: str, path: str) -> None:
        """tpl 채널이 템플릿 파일을 바꾼 직후, 그 파일을 든 편집 세션을 다시 세운다.

        **디스패치 액션이 아니다** — 웹이 부르는 표면이 아니라 컨트롤러 간 seam 이고 배선은
        앱 조립부 한 줄이다(action registry 등록 불요). 인자는
        :data:`~hwpxfiller.webapp.screens.MUTATION_KINDS` 의 종류와 변이한 경로다.

        **이 세션의 파일이 아니면 아무 일도 하지 않는다**(푸시도 없다): 남의 템플릿 변이가
        내 세션에 통지를 남기면 사용자는 자기가 만지지도 않은 파일의 경고를 읽는다. 대조는
        :func:`~hwpxfiller.webapp.template_groups.norm_library_path` 단일 술어다.

        ``deleted`` 는 ``template_path`` 를 **지우지 않는다**: 되돌리기가 같은 경로로 파일을
        돌려놓고 ``restored`` 가 이 세션을 되살린다. 경로를 비우면 그 복원이 닿을 자리가
        사라져, 사용자는 실수로 지운 템플릿을 되살려도 세션을 처음부터 다시 세워야 한다.
        저장은 그동안 :meth:`_missing_template_block` 이 심층 방어로 막는다.
        """
        if kind not in MUTATION_KINDS:  # 오타·미지 종류는 조용히 무시하지 않는다
            raise ValueError(f"알 수 없는 템플릿 변이 종류: {kind!r}")
        if not self.template_path:
            return
        if norm_library_path(self.template_path) != norm_library_path(path):
            return
        if kind == "deleted":
            self._set_notice(
                "편집 중인 템플릿이 삭제됐습니다. 되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            )
            self._push()
            return
        # 재로드가 스키마의 단일 출처다(매체 분기·게이트·RAW 판정을 재구현하지 않는다).
        self.load_template_path(self.template_path, emit_push=False)
        if self.schema is None:
            # RAW 강등: 채울 대상이 사라졌다. 낡은 모델을 그대로 두면 이제는 없는 필드로
            # `is_complete()` 가 참을 내고 저장 게이트가 통과한다(조용한 게이트 우회).
            self.model = None
            self._model_key = None
            self._unconfirm_undo = []
            self._set_notice(
                "편집 중인 템플릿 파일이 바뀌어 채울 항목이 없어졌습니다. "
                "되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            )
            self._push()
            return
        message = "편집 중인 템플릿 파일이 바뀌어 세션을 다시 읽었습니다."
        if self.model is not None:
            # 정체 키에 스키마 성분이 없다(경로·데이터만 담는다 — :meth:`_model_key_now`).
            # 경로가 그대로인 bytes 변이는 그래서 키를 안 움직이고 `_ensure_model` 이 조기
            # 반환한다. 여기서 **명시로 무효화**해 기존 이월·강등 의미론을 그 위에 그대로
            # 돌린다(확정 전원 해제 + 값 이월 + 재확정 재진술을 재구현하지 않는다).
            before = self.notice_text
            self._model_key = None
            self._ensure_model()
            if self.notice_text != before:
                message = f"{message}\n{self.notice_text}"
        self._set_notice(message, "warn")
        self._push()

    def _load_txt_template(self, path: str) -> None:
        """TXT 원문 → 동형 스키마. 판독 실패는 loud raise(조용한 빈 스키마 금지).

        토큰 순회는 :func:`render_segments` 단일 출처를 지난다(빈 레코드 → 전 토큰이
        missing 세그먼트로 등장별 1개) — 등장 횟수까지 재구현 없이 그대로 센다.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"TXT 템플릿을 읽을 수 없습니다: {exc}") from exc
        segments, _report = render_segments(text, {})
        occurrences: "dict[str, int]" = {}
        for seg in segments:
            if seg.kind == SEG_MISSING:
                occurrences[seg.name] = occurrences.get(seg.name, 0) + 1
        names = template_fields(text)
        if not names:  # 토큰 0 = 채울 대상 없음(hwpx RAW 동형) — 시끄럽게 차단.
            self.raw_block = TXT_RAW_BLOCK
            self.schema = None
            return
        self.schema = TemplateSchema(fields=[
            FieldSpec(
                name=n,
                inferred_type=infer_type(n),
                occurrences=occurrences.get(n, 1),
                in_table=False,
            )
            for n in names
        ])

    def load_data_path(
        self, path: str, *, sheet: "str | None" = None, header_row: int = 0,
        emit_push: bool = True,
    ) -> None:
        """선택된 데이터 파일 로드. ``sheet`` = 웹에서 확정한 시트명(다중 시트 게이트 #33,
        None = CSV·단일 시트라 물을 것이 없는 경우).

        ``header_row`` 는 **등록 데이터 참조가 들고 있던 옵션의 승계 자리**다(#349 리뷰 P1)
        — 0 이면 어댑터 기본(1행). 관문에서 사람이 파일을 직접 고르는 경로는 이 옵션을
        만들지 않으므로 늘 0이고, 그 경로의 거동은 종전과 같다.

        ``emit_push=False`` 는 **더 큰 전이 안에서** 불릴 때의 자리다(``load_template_path``
        와 같은 규약): 작업 복원은 하나의 화면 전환이라 중간 상태를 먼저 내보내면 DOM 이 한 번
        더 재구성돼 화면이 깜빡인다.
        """
        opts: "dict[str, object]" = {"sheet": sheet}
        if header_row:
            opts["header_row"] = header_row
        source = source_for_path(path, **opts)
        records = source.records()
        if not records:
            raise ValueError(NO_ROWS_TEXT)
        self._session_clean = False  # 브리지 직행 변이(디스패치 밖) — 클린 표지 해제
        self.data_path = path
        self.data_sheet = sheet or ""  # 자동등록 참조에 확정 시트 동봉(#26 — 모호 참조 방지)
        self.data_header_row = header_row
        # 이 관문은 **파일 소스**의 것이다 — 종류는 늘 엑셀/CSV 이고, 이전 세션의 종류가
        # 새 결속에 남지 않게 같은 자리에서 세운다(성분 한 벌 규율).
        self.data_kind = ""
        self.source_fields = source.fields()
        # 새 데이터 = 새 헤더 어휘 → 이전 미사용 선택이 조용히 남지 않게 전원 활성으로.
        self._ignored_sources = set()
        self._ignored_expanded = False  # 새 데이터 = 펼침 힌트 초기화(결정 13)
        self.records = records
        self.preview_index = 0
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
        if emit_push:
            self._push()

    def _load_source_ref(self, source_ref: dict, *, emit_push: bool = True) -> None:
        """참조 한 벌(``{path, sheet, header_row, kind}``)로 데이터를 **다시 읽는다** — 인계의 공용 자리.

        「이 데이터로 새 작업」(:meth:`new_draft_with_data`)과 「수정…」(수리 진입, #878)이 같은
        성분을 같은 규칙으로 푼다. 두 자리가 각자 풀면 한쪽이 ``header_row`` 를 흘려도 아무도
        모른다 — 그 어긋남은 화면 어디에도 표시가 없다(#349 리뷰 P1 이 지목한 자리).
        참조를 낸 곳은 「문서 만들기」의 단일 판정
        (:meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin.new_work_handoff`)이다.

        ``kind`` 가 엑셀/CSV(``""``)가 아니면 **시끄럽게 거절한다**: 이 자리의 해석기는
        :meth:`load_data_path` 하나뿐이라 다른 종류의 참조를 그냥 넘기면 db 경로를 엑셀로
        오파싱하거나 빈 세션으로 조용히 착지한다. (계약 목록 결속의 실제 복원 배선은 다음
        단계에서 이 가드를 대체한다.)
        """
        path = str(source_ref.get("path") or "")
        if not path:
            raise ValueError("데이터 참조에 경로가 없습니다.")
        kind = str(source_ref.get("kind") or "")
        if kind:
            label = "계약 목록" if kind == "pclm" else f"'{kind}'"
            raise ValueError(f"{label} 데이터 결속은 아직 편집기에서 복원할 수 없습니다.")
        header = source_ref.get("header_row")
        self.load_data_path(
            path,
            sheet=str(source_ref.get("sheet") or "") or None,
            header_row=header if isinstance(header, int) and not isinstance(header, bool) else 0,
            emit_push=emit_push,
        )

    # ------------------------------------------------------- 편집 모드(#26 #1)
    def load_job(
        self,
        name: str,
        *,
        landing_section: str = SECTION_BINDING,
        emit_push: bool = True,
        entry_reason: str = "voluntary",
        evidence: "dict | None" = None,
        return_context: "dict | None" = None,
        target: str = "",
        source_ref: "dict | None" = None,
    ) -> None:
        """저장된 작업을 **문맥과 함께** 편집 세션으로 연다(계약 §5.1).

        진입 문맥(사유·증거·복귀처)은 여기서 한 번 세우고 그 뒤 재렌더·왕복을 건너 산다 —
        편집기는 스스로 열리지 않으므로(늘 다른 표면의 문제가 사람을 보낸다) 문맥 없는
        진입은 "왜 왔는지도 어디로 돌아갈지도 없는 표면"이 된다. 미지·미배선 사유·미지
        target 은 :func:`~hwpxfiller.gui.edit_session.make_context` 가 fail-closed 로 거절한다.

        ``target``(deep-link, §10.14.3) 이 서면 **착지 탭도 target 이 정한다**(값의 앞
        절 = section) — 겨눈다고 말하고 다른 탭에 내리는 반쪽 착지를 막는다. 행 단위
        조준(스크롤·포커스)은 뷰 소관이고, 스키마 드리프트로 행이 사라졌으면 뷰가
        fail-open 한다(탭 착지·배너 증거는 그대로 참이다).

        ``source_ref`` 는 **진입이 들고 온 데이터 참조**다(#878, ``{path, sheet, header_row}``
        한 벌). 「문서 만들기」가 데이터를 든 채 보낸 수리 진입
        (:data:`~hwpxfiller.gui.edit_session.DATA_ANCHORED_ENTRY_REASONS`)에만 서고, 참조를
        낸 곳도 그 화면의 단일 판정이다(``new_work_handoff``). 레코드가 아니라 **참조**를
        받아 여기서 다시 읽는 이유는 풀 규약과 같다: 두 화면이 같은 파일의 서로 다른 판을
        들고 있게 만들지 않는다.
        """
        job = self.registry.load(name)  # 부재·손상 → loud raise
        context = make_context(
            job.name,
            entry_reason=entry_reason,
            evidence=evidence,
            return_context=return_context,
            target=target,
        )
        if context.target:
            landing_section = context.target.partition("/")[0]
        self._restore_from(
            job,
            landing_section=landing_section,
            context=context,
            emit_push=emit_push,
            source_ref=source_ref,
        )

    def _restore_from(
        self,
        job: "Job",
        *,
        landing_section: str,
        context,
        emit_push: bool = True,
        keep_data: bool = False,
        source_ref: "dict | None" = None,
        probe_binding: bool = True,
    ) -> None:
        """작업 스냅샷 하나로 편집 세션 상태를 재구성 — 3분류 상태 재구성(단순 배선 아님).

        복원 경로: ``load_template_path``(스키마·게이트) → ``from_suggestions`` 초안 →
        ``apply_profile``(저장 매핑을 확정 상태로) → ``_model_key`` 정합 세팅(단계 이동이
        복원 모델을 초안으로 재생성하는 함정 봉쇄). ``from_profile`` 단독은 템플릿-무
        모델(schema=None)이라 마법사가 돌지 않는다 — 쓰지 않는다.

        confirm-or-alarm:
        - 작업 손상·템플릿 부재·RAW·게이트 오류는 loud raise(브리지가 ``ERROR:`` 재진술).
        - 템플릿 드리프트(저장 매핑에 있는데 현 스키마에 없는 필드)는 ``apply_profile`` 이
          조용히 누락시키므로 여기서 세어 notice 로 재진술한다.
        - 태그·마지막 실행 메타는 보존해 편집 저장이 조용히 소실시키지 않는다.

        입력이 **레지스트리 이름이 아니라 Job 스냅샷**인 이유(F7): 「변경 버리기」는 디스크가
        아니라 **진입 시점 스냅샷**으로 되돌아가야 한다(§5.2 의 baseSnapshot). 디스크를 다시
        읽으면 편집 중 밖에서 일어난 변경을 사용자가 요청하지도 않은 채 조용히 채택하게
        되고, 그 변경은 저장 시점의 외부 변경 확인이 잡을 기회도 잃는다.

        ``keep_data`` 는 **탭 단위 버리기** 전용이다(8R P2 로 좁혀졌다) — 「필드 연결에서 바꾼
        것만 되돌린다」고 말한 되돌리기가 사람이 고른 엑셀까지 내려놓으면 문안보다 넓은 파기다
        (데이터 선택은 patch 가 아니라 세션 문맥 — §10.13 판정 L). 반대로 **세션 전체** 버리기는
        데이터도 내려놓는다: 「저장된 상태로 되돌린다」가 문안이고, 남기면 버린 뒤에도 세션이
        미저장으로 남아 같은 파기를 다시 묻는다.

        ``source_ref``(#878)는 **모델보다 먼저** 선다. 진입이 참조를 들고 오지 않았으면
        **저장본의 결속**(:func:`_binding_source_ref`)이 그 자리를 잇는다(#932 U4-C S2-2):
        데이터를 나중에 얹으면
        :meth:`load_data_path` 의 ``_ensure_model`` 이 키 변화를 보고 매핑을 전원 미확정
        초안으로 재생성해, 고칠 필드 하나 때문에 온 사람에게 저장된 매핑 전량 재확정을 물린다.
        데이터를 먼저 세우면 저장 매핑은 **그 데이터 어휘 위로** 복원되고
        (``apply_profile(require_source=True)``), 데이터에 없는 열을 겨눈 행만 확정에서
        빠져 재진술 대상이 된다(조용한 게이트 우회 금지 — 그 행은 빈 값 문서를 찍는다).
        재읽기 실패는 진입을 막지 않고(고치러 온 필드는 데이터 없이도 고칠 수 있다) 사유를
        통지로 재진술한다 — 조용히 빈 데이터 관문으로 떨어지지 않는다.
        """
        if not Path(job.template_path).exists():
            raise ValueError(
                f"템플릿 파일을 찾을 수 없습니다: {job.template_path}\n"
                "파일을 되돌리거나, 홈/작업 화면의 [템플릿 다시 연결…]로 경로를 바꾸세요."
            )
        stash = self._data_stash() if keep_data else None
        # 기준 데이터도 함께 넘긴다 — 탭 되돌리기가 인계 데이터를 「사람이 고른 것」으로
        # 승격시키면 되돌린 세션이 곧바로 미저장이 된다(같은 헛확인의 다른 얼굴).
        entry_data = dict(self._entry_data) if keep_data else None
        self._reset()
        # 작업 복원은 하나의 화면 전환이다. 템플릿만 로드된 중간 상태를 먼저 내보내면
        # 최종 편집 상태 직전에 DOM 전체가 한 번 더 재구성돼 화면이 깜빡인다.
        self.load_template_path(job.template_path, emit_push=False)
        if self.schema is None:  # RAW/토큰 0 — 채울 필드가 없어 매핑 편집이 성립하지 않는다.
            raise ValueError(self.raw_block or RAW_BLOCK_MESSAGE)  # 매체별 문안(F6 PR-B)
        if self.gate_error:
            raise ValueError("템플릿 상태를 확인할 수 없어 편집을 열 수 없습니다.")
        # 진입이 참조를 들고 오지 않았으면 **저장본의 결속**이 선다(#932 U4-C S2-2).
        # 우선순위가 이 방향인 이유: 인계(``DATA_ANCHORED_ENTRY_REASONS``)는 사람이 방금
        # 고른 데이터라 저장된 결속보다 새 의사다. 결속은 그 의사가 없을 때의 기본값이고,
        # 구판 작업(결속 없음)은 조용히 지나간다 — 여기서 「데이터 연결 필요」를 말하는
        # 것은 저장 게이트(``validate_save``)의 일이라 같은 상태를 두 곳이 판정하지 않는다.
        # ``keep_data`` 갈래는 아래 스태시가 이기므로 읽지 않는다(같은 파일을 두 번 읽지 않는다).
        handoff_failure = ""
        carried_ref = source_ref if source_ref else (
            None if keep_data else _binding_source_ref(job)
        )
        if carried_ref:
            try:
                self._load_source_ref(carried_ref, emit_push=False)
            except Exception as exc:  # noqa: BLE001  (사유를 통지로 재진술 — 진입은 계속)
                handoff_failure = str(exc)
        carried_data = bool(self.data_path)
        self._entry_data = {"data_path": self.data_path, "data_sheet": self.data_sheet}
        self.job_name = job.name
        self.pattern = job.filename_pattern
        self._editing_origin = job.name
        self._preserved_meta = _preserved_meta(job)
        # 로드 시점 내용 지문 — 자기-갱신 저장 시 편집 중 외부 변경(같은 이름 작업 교체)을
        # 무확인으로 덮지 않기 위한 대조 기준(_do_save).
        self._editing_fingerprint = content_fingerprint(job)
        self._loaded_provenance = dict(job.mapping.provenance)  # 작성 출처 표시(#53-C)
        # 소스 어휘 = 저장 매핑이 참조하는 키 합집합(profile_source_vocabulary 단일 출처,
        # from_profile 과 공유) — 데이터 없이도 복원된 source 가 선택지에 있어야 드롭다운이
        # (비움)으로 오표시되지 않는다. 진입이 데이터를 들고 왔으면(#878) 어휘는 **그 데이터의
        # 열**이다: 새 필드에 붙일 열이 후보로 서야 수리 진입이 성립하고, 데이터에 없는 옛
        # source 는 뷰가 '(데이터에 없음)' 옵션으로 시끄럽게 드러낸다.
        if not carried_data:
            self.source_fields = profile_source_vocabulary(job.mapping)
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
        applied = self.model.apply_profile(job.mapping, require_source=carried_data)
        self._model_key = self._model_key_now()
        # 거래 상태 — base = **이 스냅샷**(§5.2 baseSnapshot). patch 는 여기서부터의 차이다.
        # 문맥의 대상은 늘 **지금 열려 있는 작업**이다: 초안이 저장으로 작업이 되는 전이에서
        # 진입 시점의 빈 이름이 남으면 배너가 남의(없는) 작업을 가리킨다.
        self.session = EditSession(
            context=replace(context, work=job.name), base=job, section=self.section
        )
        # 일반 진입은 연결 탭(기본값). 저장 직후 재로드는 호출자가 사용자가 머물던 탭을
        # 넘겨 같은 자리로 착지시킨다(저장할 때마다 연결 탭으로 튕김 방지).
        self.section = (
            landing_section if landing_section in self.sections() else SECTION_BINDING
        )
        self.session.section = self.section
        if stash is not None:
            self._apply_data_stash(stash)
        if entry_data is not None:
            self._entry_data = entry_data
        row_fields = {r.template_field for r in self.model.rows}
        dropped = [
            m.template_field for m in job.mapping.mappings
            if m.template_field not in row_fields
        ]
        # 미확정으로 도착한 행을 **사유별로** 가른다: 저장 매핑에 없던 필드는 템플릿이 새로
        # 낳은 것이고, 있었는데 확정에서 빠진 행은 인계 데이터에 그 열이 없는 것이다
        # (require_source). 한 문장으로 뭉치면 데이터 불일치가 "템플릿에 새로 생긴 필드"로
        # 오보돼 사람이 엉뚱한 곳을 본다.
        saved_fields = {m.template_field for m in job.mapping.mappings}
        fresh = [
            r.template_field for r in self.model.rows
            if not r.confirmed and r.template_field not in saved_fields
        ]
        detached = [
            r.template_field for r in self.model.rows
            if not r.confirmed and r.template_field in saved_fields
        ]
        # 사용자 어휘 재진술(F17) — "매핑 N행 복원" 같은 로그 어휘를 UI 로 내보내지 않는다.
        notice = f"'{job.name}' 을(를) 편집합니다. 저장된 매핑 {applied}행을 불러왔습니다."
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
        if detached:
            notice += (
                f"\n불러온 데이터에 없는 열을 쓰던 필드 {len(detached)}개는 확정이 필요합니다: "
                + ", ".join(detached)
            )
        # 실패 사유는 값으로도 든다 — 저장 착지는 이 notice 를 자기 문안으로 덮으므로,
        # 값이 없으면 그 갈래에서 사유가 조용히 사라진다(#932 U4-C S2-1).
        self._reload_failure = handoff_failure
        if handoff_failure:
            notice += f"\n연결된 데이터를 다시 읽지 못했습니다: {handoff_failure}"
        self._set_notice(
            notice, "warn" if (dropped or fresh or detached or handoff_failure) else "ok"
        )
        # 복원 직후 = 디스크 저장본과 동일(클린) — 손대기 전 전환·새 작업이 "저장하지 않은
        # 세션" 헛확인을 띄우지 않는다(리뷰). 내부의 load_template_path 가 표지를 껐으므로
        # 마지막에 켠다. 드리프트 경고(warn)가 있어도 내용 동일성은 참이다.
        self._session_clean = True
        # 연결 확정 대기(#911)는 진입에서 잰다 — 이 세션이 서 있는 저장본이 방금 정해졌다.
        # ``probe_binding=False`` 는 **저장 임계구역 안의 재로드** 하나다: 판정이 durable 결속
        # 저장소를 per-Work fence 안에서 읽으므로 레지스트리 쓰기 잠금을 쥔 채 부르면 잠금
        # 두 개를 문서화되지 않은 순서로 겹친다. 게다가 그 시점 값은 어차피 낡았다 — 확정을
        # 부르는 `_after_mapping_saved` 가 아직 돌지 않았다. 저장 갈래는 잠금 밖에서 다시 잰다.
        if probe_binding:
            self._refresh_binding_confirm_pending()
        if emit_push:
            self._push()

    def _data_stash(self) -> "dict":
        """세션 문맥으로서의 데이터 — 규칙을 되돌릴 때 함께 내려놓지 않을 값들(판정 L)."""
        return {
            "data_path": self.data_path,
            "data_sheet": self.data_sheet,
            # 참조 성분은 **한 벌로** 다닌다(#349 리뷰 2R·3R): 경로·시트만 되싣고 헤더 행·
            # 종류를 흘리면 되돌린 뒤의 세션이 같은 경로의 다른 판·다른 종류를 들게 된다.
            "data_header_row": self.data_header_row,
            "data_kind": self.data_kind,
            "source_fields": list(self.source_fields),
            "records": self.records,
            "ignored": set(self._ignored_sources),
            "ignored_expanded": self._ignored_expanded,
        }

    def _apply_data_stash(self, stash: "dict") -> None:
        """되돌린 규칙 위에 데이터 문맥을 다시 얹는다 — 데이터 선택 직후와 같은 경로.

        ``_ensure_model`` 을 통과시키는 이유: 데이터 어휘로 모델을 다시 세우는 일은 이미
        한 관문이 소유한다(값 이월 + 안 맞게 된 확정의 시끄러운 강등). 여기서 따로 조립하면
        그 관문이 지키는 불변식(어떤 행도 검토 없이 확정 상태로 도착하지 않는다)을 두 번째
        경로가 우회하게 된다.
        """
        if not stash["data_path"]:
            return
        self.data_path = stash["data_path"]
        self.data_sheet = stash["data_sheet"]
        self.data_header_row = stash.get("data_header_row", 0)
        self.data_kind = stash.get("data_kind", "")
        self.source_fields = stash["source_fields"]
        self.records = stash["records"]
        self._ignored_sources = stash["ignored"]
        self._ignored_expanded = stash["ignored_expanded"]
        self._ensure_model()

    # 세션 내용을 바꾸지 않는 액션 — 클린 표지를 끄지 않는다(보기 이동·미리보기·질의).
    _NONMUTATING_ACTIONS = frozenset(
        {"goto_section", "step_preview", "mapping_reset_stakes", "toggle_library_group",
         # 목록 조회는 세션을 안 바꾼다 — 데이터를 고르기 전에 클린 표지를 끄면 아무것도
         # 안 고른 사람에게 이탈 확인이 뜬다(#932 U4-C S2-5).
         "pool_options"}
    )

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 editor 액션: {action!r}")
        if action not in self._NONMUTATING_ACTIONS:
            self._session_clean = False  # 변이 = 더는 저장본과 동일하지 않다
        was_complete = self._mapping_complete()
        result = handler(payload)
        # T2 매핑 전확정(#894) — **상승 모서리**로 통지한다. 확정은 한 액션이 아니라 여러 갈래
        # (`confirm_all`·`confirm_blanks`·행별 `set_confirmed`·`restore_confirmed`)로 도달하므로
        # 액션마다 훅을 달면 그 목록이 곧 두 번째 판정자가 된다. 판정 자체는 링1
        # ``MappingModel.is_complete()`` 하나이고 여기는 그 값의 false→true 만 읽는다.
        if not was_complete and self._mapping_complete():
            self._tutorial(Milestone.CONFIRM_MAPPING)
        self._push()
        return result

    def _mapping_complete(self) -> bool:
        """지금 매핑이 전확정인가 — 링1 판정의 단순 조회(모델 부재는 False)."""
        return self.model is not None and self.model.is_complete()

    # ---- 세션 수명주기(F10)
    def _do_new_session(self, p: dict) -> None:
        """홈 「＋ 새 작업」 — 이전 세션 전량 초기화(라벨-행동 일치, F10).

        종전 홈 버튼은 bare nav 라 직전 세션(이름·데이터·매핑·편집 원점)이 그대로
        복원돼 '새'가 사실상 '이전 작성 계속'이었다. 미저장 확인은 호출측(웹)이
        ``has_unsaved_work`` 로 선판단한다 — ``new_job_session``(템플릿 진입 seam)과
        같은 분담. 초기 상태 notice 는 두지 않는다(정상은 조용히).
        """
        self._reset()

    def _do_discard_session(self, p: dict) -> None:
        """신규 마법사 취소 — 확인을 마친 호출측이 휘발 초안을 실제로 폐기한다(#218 G5)."""
        if self._editing_origin:
            raise ValueError("저장된 작업 편집은 신규 마법사 취소로 닫을 수 없습니다.")
        self._reset()

    # ---- 탭 이동(§5.2 거래 규율)
    #: 탭 라벨 — 거절 문안이 내부 키(`binding`)가 아니라 사람의 말로 자리를 지목하게 한다.
    SECTION_LABELS = {
        SECTION_TEMPLATE: "템플릿",
        SECTION_BINDING: "필드 연결·표시",
        SECTION_FILENAME: "파일 이름",
    }

    def _do_goto_section(self, p: dict) -> "dict | None":
        """탭 이동 — 신규(초안)는 전진 게이트, 편집은 자유 이동. **처분 미확정 이동은 거절**.

        §13-16(한 편집 진입은 한 section patch)은 전이 시점의 규율이다: 다른 탭의 규칙을
        손대려면 지금 patch 를 **저장하거나 버려야** 한다. 그래서 이동은 조용히 일어나지
        않고, 처분해야 할 자리가 있으면 ``needs_section_guard`` 로 되돌려 웹이 3택(저장하고
        이동·버리고 이동·머무르기)을 받게 한다 — 판정은 여기(Python), 문안은 웹이다.

        초안은 이 거래 밖이다(§10.13 판정 P): 아직 작업이 아니라 세션 전체가 하나의 초안이라
        「직전 판본과의 차이」가 성립하지 않는다. 대신 초안에는 전진 게이트가 산다(판정 M).
        """
        target = str(p["section"])
        sections = self.sections()
        if target not in sections:
            raise ValueError(f"이 작업에는 '{target}' 탭이 없습니다.")
        blocking = self.session.blocking_section(
            self._draft_job(), target, pending_binding=self._pending_binding()
        )
        if blocking and not p.get("disposition"):
            return {
                "ok": False,
                "needs_section_guard": True,
                "section": blocking,
                "section_label": self.SECTION_LABELS.get(blocking, blocking),
                "target": target,
            }
        if target == SECTION_TEMPLATE and self.section != SECTION_TEMPLATE:
            self._refresh_library()  # 템플릿 탭 재진입 = 공유 VM 실 디스크 재스캔(외부 변경 반영)
        if not self._editing_origin:  # 초안: 전진은 각 중간 탭의 게이트 통과 필요
            here, there = sections.index(self.section), sections.index(target)
            for s in sections[here:there]:
                if not self.can_advance(s):
                    raise ValueError(
                        f"「{self.SECTION_LABELS.get(s, s)}」 조건을 아직 채우지 못해 "
                        "다음으로 갈 수 없습니다."
                    )
        if target == SECTION_BINDING:  # 매핑 진입 — 데이터 유무 불문 모델 초안 생성.
            self._ensure_model()
        self.section = target
        self.session.section = target
        return None

    def _do_discard_patch(self, p: dict) -> None:
        """「변경 버리기」 — 진입 시점 스냅샷(baseSnapshot)으로 규칙만 되돌린다(§5.2).

        디스크가 아니라 스냅샷으로 되돌리는 이유는 :meth:`_restore_from` 의 docstring 에 있다.
        초안은 되돌릴 base 가 없으므로 거절한다 — 초안 전체를 버리는 것은 세션 폐기
        (``discard_session``)라는 다른 사건이고, 두 사건을 한 버튼이 겸하면 "변경만 버리려던"
        사람이 초안째 잃는다.

        **범위는 확인 문안과 같아야 한다**(8R 근본 조치 — 이 함수의 두 갈래가 각각 한 번씩
        어긴 자리다). 되돌리는 범위가 문안보다 넓으면 승인받지 않은 파기고, 좁으면 버렸다고
        말한 것이 남아 다음 전환에서 다시 묻는다. 그래서 두 갈래를 대칭으로 세운다:
        ``section`` 있음 = 그 탭만(extras 는 **보존**), 없음 = 세션 전체(extras 도 **함께**).
        """
        if self.session.is_draft or self.session.base is None:
            raise ValueError("아직 저장하지 않은 새 작업이라 되돌릴 이전 상태가 없습니다.")
        base = self.session.base
        section = str(p.get("section") or "")
        if not section:  # footer 「변경 버리기」·이탈의 「버리고 나가기」 = 세션 전체를 되돌린다
            # **데이터 선택도 함께 되돌린다**(8R P2): 문안이 「저장된 상태로 되돌린다」고
            # 말했는데 고른 엑셀을 남기면, 버리기를 마친 세션이 여전히 미저장이라 다음
            # 작업을 열 때 방금 버린 것을 또 묻고(같은 파기를 두 번 승인시킨다), 편집기로
            # 돌아가면 버렸다던 데이터 선택이 그대로 서 있다.
            #
            # **되돌아가는 자리는 「빈 값」이 아니라 「저장된 결속」이다**(#932 U4-C):
            # 결속이 durable 이 된 뒤로 저장본의 데이터는 버릴 대상이 아니라 되돌아갈
            # 자리다. 문안도 그 사실을 따라간다 — 결속이 있는 작업에 「내려놨습니다」라고
            # 말하면 화면에는 데이터가 서 있는데 문안만 거짓이 된다(과진술도 부정직이다).
            restored_ref = data_binding_of(base)
            data_changed = (
                self.data_path, self.data_sheet, self.data_header_row, self.data_kind
            ) != restored_ref
            base_bound = has_data_binding(base)
            self._restore_from(
                base, landing_section=self.section, context=self.session.context,
                emit_push=False,
            )
            if not data_changed:
                data_line = ""
            elif base_bound:
                data_line = "\n데이터도 이 작업에 연결된 것으로 되돌렸습니다."
            else:
                # 구판 작업(결속 없음) — 되돌아갈 자리가 없으므로 실제로 내려놓는다.
                data_line = "\n고른 데이터도 함께 내려놨습니다."
            self._set_notice(
                "바꾼 내용을 버리고 저장된 상태로 되돌렸습니다." + data_line,
                "ok",
            )
            return
        if section not in self.sections():
            raise ValueError(f"이 작업에는 '{section}' 탭이 없습니다.")
        # 탭 가드의 「버리고 이동」은 **그 자리만** 되돌린다(2R P2): 모달이 말한 것은 「필드
        # 연결·표시에서 바꾼 것」인데 세션 전체를 되돌리면 머리에서 고친 이름처럼 **어느
        # section 에도 속하지 않는 편집**(판정 L 계열)까지 함께 사라진다. 되돌리는 범위가
        # 확인 문안보다 넓으면 그건 사용자가 승인하지 않은 파기다.
        if section == SECTION_FILENAME:
            self.pattern = base.filename_pattern
        elif section == SECTION_BINDING:
            self._revert_binding(base)
        else:  # 템플릿 — 스키마·매핑이 함께 서야 하므로 규칙 전체를 다시 세운다(이름은 유지)
            name = self.job_name
            self._restore_from(
                base, landing_section=self.section, context=self.session.context,
                emit_push=False, keep_data=True,
            )
            self.job_name = name
        self._set_notice(
            f"「{self.SECTION_LABELS.get(section, section)}」 에서 바꾼 것만 되돌렸습니다.", "ok"
        )
        # 되돌린 뒤의 정체는 **여기서 다시 세지 않는다**(8R 근본 조치). 저장본이 있는 세션의
        # `has_unsaved_work` 는 section patch + extras 비교로 파생되므로, 이 자리에서 손으로
        # 열거를 되풀이하던 줄은 그 자체가 라운드의 재료였다(2R 이 이름만 보고 세웠고 5R 이
        # 데이터를 더했다 — 셋째 값이 생기면 또 빠졌을 자리다).

    def _revert_binding(self, base: "Job") -> None:
        """연결 patch 만 되돌린다 — 데이터·이름·파일 이름 규칙은 그대로 둔다.

        모델을 저장본 프로파일로 다시 세우는 일은 ``load_job`` 이 하는 것과 같다(초안 →
        `apply_profile`): 여기서 행을 하나씩 되돌리면 「어떤 행도 검토 없이 확정 상태로
        도착하지 않는다」는 ``_ensure_model`` 의 불변식을 두 번째 경로가 우회하게 된다.
        """
        if self.schema is None:
            return
        vocabulary = self._active_sources() or profile_source_vocabulary(base.mapping)
        if not self.data_path:
            # 데이터 없는 편집 세션의 어휘는 **저장 매핑이 참조하는 키**다(load_job 과 동형) —
            # 이걸 빼면 되돌린 행이 전부 "(데이터에 없음)"으로 오표시된다.
            self.source_fields = profile_source_vocabulary(base.mapping)
            vocabulary = self.source_fields
        self.model = MappingModel.from_suggestions(self.schema, vocabulary)
        self.model.apply_profile(base.mapping)
        self._model_key = self._model_key_now()

    def _do_dismiss_notice(self, p: dict) -> None:
        """사용자가 세션 통지를 끈다(U4 계열1-20).

        이 채널에는 **세우는 전이만** 있었고 지우는 전이가 :meth:`_reset` 밖에 없어서, 한 번
        선 통지가 사유가 해소돼도 화면에 남았다. 자동 소멸 대신 수동 닫기를 두는 이유는
        해소 판정을 통지마다 새로 지으면 그 술어가 같은 상태의 **두 번째 판정**이 되기
        때문이다 — 트리거는 그대로라 사유가 다시 서면 통지도 다시 선다.
        """
        self._set_notice("", "muted")

    def _do_ack_gate(self, p: dict) -> None:
        """PARTIAL 게이트 명시 확인 — 재진술된 미해결 토큰 전체를 확인(ADR-E)."""
        if self.gate is None:
            raise ValueError("확인할 항목이 없습니다.")
        self.gate.acknowledge(self.gate.unmet_tokens)

    # ---- 등록 데이터(풀)에서 고르기(#932 U4-C S2-5)
    #
    # 「데이터 없이 진행」(``_do_skip_data``)은 여기서 사라졌다: 데이터 결속이 저장 게이트가
    # 된 이상 옵트아웃은 **저장할 수 없는 세션**으로 데려가는 링크였고, 그것은 관문이 아니라
    # 막다른 길이다. 그 자리를 대신하는 것이 이 두 동사다 — 사람이 이미 고정해 둔 데이터를
    # 마법사 안에서 그대로 고른다(파일 피커와 같은 관문, 다른 출처).
    #
    # ``job`` 화면의 ``load_pool`` 을 공유하지 않고 편집기 소유 이름을 쓰는 이유: 화면별
    # 허용 목록(`action_registry`)이 곧 이 경계의 정의라 같은 이름을 두 화면이 나눠 쓰면
    # 「누가 무엇을 받는가」가 이름 하나로는 안 읽힌다. 포획 규율은 공유한다
    # (:func:`~hwpxfiller.webapp.screens.pool_reference_triple`).

    def _do_pool_options(self, p: dict) -> dict:
        """고정한 데이터 목록 1회 조회(무변이) — 목록·사유·손상 항목을 그대로 싣는다.

        렌더당 I/O 가 아니다: 스냅샷에 상주시키지 않고 사람이 목록을 여는 사건에서만
        지불한다(:func:`~hwpxfiller.webapp.screens.reference_missing` 와 같은 규율).

        쓸 수 없는 항목도 **빼지 않는다** — ``usable=False`` + 사유를 함께 실어 표면이
        비활성으로 그린다. 손상 등록도 목록 밖으로 밀지 않고 따로 재진술한다(RC-05).
        """
        if self._pool_registry is None:
            return {"ok": False, "error": POOL_UNWIRED_TEXT, "items": [], "corrupted": []}
        entries, corrupted = self._pool_registry.list_references()
        items = []
        for key, item in entries:
            row = DatasetPoolRow.from_item(key, item)
            reason = pool_option_block(row)
            items.append({
                "key": row.key,
                "name": row.name,
                "reference": row.reference,
                "usable": not reason,
                "reason": reason,
            })
        return {
            "ok": True,
            "items": items,
            "corrupted": [{"file": e.file_name, "error": e.error} for e in corrupted],
        }

    def _mount_pool_item(self, item) -> list:
        """풀 항목을 이 세션의 데이터로 마운트하고 레코드를 돌려준다(공유 관문의 loader).

        참조 포획은 :func:`~hwpxfiller.webapp.screens.pool_reference_triple` 하나가 진다 —
        경로·시트·헤더 행이 한 벌로 오지 않으면 마법사가 사람이 고른 것과 **다른 헤더**로
        선다(#349 리뷰 P1). 파일 참조가 아닌 항목은 여기서 시끄럽게 거절한다(목록이 이미
        비활성으로 그렸어도 그 판정을 표면에만 두지 않는다).
        """
        path, sheet, header_row = pool_reference_triple(item)
        if not path:
            raise ValueError(f"'{item.name}' 은(는) 파일 참조가 아니라 연결할 수 없습니다.")
        self.load_data_path(
            path, sheet=sheet or None, header_row=header_row, emit_push=False
        )
        return self.records

    def _do_use_pool_data(self, p: dict) -> dict:
        """고른 등록 데이터를 이 작업의 데이터로 연결 — 실패는 사유 dict 로 재진술.

        거절 사다리(나라 동결·항목 부재·모호 시트·죽은 참조·0행)는 공유 실행부
        (:func:`~hwpxfiller.webapp.screens.load_pool_into`)가 소유한다. 여기서 다시 적으면
        같은 실패가 화면마다 다른 문구를 갖는다.
        """
        if self._pool_registry is None:
            return {"ok": False, "error": POOL_UNWIRED_TEXT}
        res = load_pool_into(self._pool_registry, str(p["key"]), self._mount_pool_item)
        if not res["ok"]:
            return {"ok": False, "error": res["error"]}
        return {"ok": True, "label": res["item"].name}

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
                "확정한 매핑이 있어 전체 미사용을 할 수 없습니다. 확정을 먼저 해제하거나 "
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
                "사용할 데이터 열을 하나 이상 남겨 두세요. 전부 끄려면 '전체 미사용'을 쓰세요."
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
        msg = f"사용 데이터 열 {n_active}개 · 미사용 {n_ignored}개."
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
        key = self._model_key_now()
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
        # 「모두 해제」 undo 슬롯 무효화(#273 리뷰) — 슬롯은 **이전 모델의** 숫자 인덱스라
        # 재생성된 모델에선 엉뚱한(또는 우연히 같은 자리의) 행을 가리킨다. 살려두면 아직
        # 보이는 「되돌리기」가 새 입력의 행들을 검토 없이 확정해, 위 "전원 미확정 재생성"
        # 불변식을 그대로 우회한다(조용한 게이트 우회). 재생성 = 슬롯 소멸.
        self._unconfirm_undo = []
        if prior is not None:
            carried = self.model.apply_profile(prior, confirm=False)
            self._set_notice(
                f"템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 확정했거나 직접 "
                f"편집한 {carried}개 행의 소스·유형·서식은 이월했지만, 저장하려면 전 행을 "
                "다시 확정하세요.",
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
            return {"human": 0, "use_none_manual": 0, "resuggest_manual": 0, "confirmed": 0}
        rows = [r for r in self.model.human_owned_rows() if r.confirmed or r.has_content()]
        # 파괴 확인의 수치는 **행동마다 다르다** — 두 관문이 강등하는 집합이 다르기 때문이다.
        # 한 수치를 둘이 나눠 쓰면 좁은 쪽 술어가 넓은 쪽 파괴를 가려 준다(리뷰 R1 P1: 소스
        # 없는 수동 const 행이 일괄 재제안에서 확인 없이 지워졌다). 그래서 이름을 소비자에게
        # 붙인다 — 새 관문이 생기면 자기 수치를 여기 더한다.
        #
        # use_none: 소스를 겨눈 touched 미확정 행만 강등한다(PR-3 리뷰 F4 — 문안=파괴 집합).
        use_none_manual = [
            r for r in self.model.rows if r.touched and not r.confirmed and r.source
        ]
        # resuggest_all: 미확정 행 **전부**를 reset_to_system 한다 — 소스뿐 아니라 상수·유형·
        # 표시형까지 지우므로 소스 없는 수동 행도 잃을 것이 있다. 술어는 실제 루프
        # (`_resuggest_targets`)에서 되읽어 둘이 갈라질 자리를 없앤다.
        resuggest_manual = [i for i in self._resuggest_targets() if self.model.rows[i].touched]
        # confirmed 는 use_none 사전 차단의 근거(PR-3 리뷰 F5) — 확인 모달을 띄운 뒤에야
        # 백엔드가 거부하는 확인-후-오류 순서를 웹이 선차단으로 뒤집는다.
        return {
            "human": len(rows),
            "use_none_manual": len(use_none_manual),
            "resuggest_manual": len(resuggest_manual),
            "confirmed": self.model.confirmed_count(),
        }

    def _resuggest_targets(self) -> "list[int]":
        """일괄 재제안이 손대는 행 — 확인 수치와 실제 루프의 **단일 술어**(리뷰 R1 P1).

        수치를 따로 세면 좁은 쪽이 넓은 쪽 파괴를 가린다: 종전 확인은 `r.source` 를 요구했고
        루프는 요구하지 않아, 소스 없이 상수만 직접 입력한 미확정 행이 확인 없이 지워졌다
        (`revert_to_auto` 가 const·type·fmt 를 함께 리셋한다).
        """
        if self.model is None:
            return []
        return [i for i, r in enumerate(self.model.rows) if not r.confirmed]

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
            raise ValueError("확정한 행은 되돌릴 수 없습니다. 확정을 먼저 해제하세요.")
        self.model.revert_to_auto(index)
        self.model.resuggest_row(index, self._active_sources())

    def _do_resuggest_all(self, p: dict) -> dict:
        """전 행을 자동 제안으로 다시 받는다(U2 §2.4) — 행 단위 ``revert_source`` 의 일괄판.

        **확정한 행은 건드리지 않는다.** 행 단위가 확정 행을 시끄럽게 거절하는 것과 같은
        근거인데(오클릭 한 번에 확정이 조용히 풀리면 안 된다), 일괄에서는 거절이 아니라
        **제외**다: 확정 하나 때문에 나머지 전부를 못 돌리면 사용자는 확정을 풀었다 다시
        걸어야 한다. 대신 무엇을 건드리고 무엇을 뒀는지 수치로 돌려준다 — 부분 동작을
        조용히 하지 않는다(confirm-or-alarm).

        되돌린 행마다 ``revert_to_auto`` → ``resuggest_row`` 로 간다: 행 단위와 **같은
        착지**여야 「일괄로 한 것」과 「하나씩 N번 한 것」이 달라지지 않는다. 전집합
        ``apply_active_sources`` 를 쓰지 않는 이유도 같다 — 그쪽은 확정 행까지 훑는다.
        """
        if self.model is None:
            return {"resuggested": 0, "kept_confirmed": 0}
        active = self._active_sources()
        # 대상 술어는 `_resuggest_targets` 단일 출처 — 확인 수치가 여기서 파생돼야
        # 「물어본 것」과 「지운 것」이 갈라지지 않는다(리뷰 R1 P1).
        targets = self._resuggest_targets()
        for index in targets:
            self.model.revert_to_auto(index)
            self.model.resuggest_row(index, active)
        return {
            "resuggested": len(targets),
            "kept_confirmed": len(self.model.rows) - len(targets),
        }

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
        confirmed = self.model.confirm_fields(list(p.get("fields", [])))
        # T14 비움 확정(#894) — **실제로 확정된 행이 있을 때만**이다: 빈 목록·이미 확정된
        # 이름으로 온 무변이 호출에서 체크가 서면 지나지 않은 게이트를 지났다고 말하게 된다.
        # 수치 판정은 링1 ``confirm_fields`` 의 반환(새로 확정된 개수)이 이미 냈다.
        if confirmed:
            self._tutorial(Milestone.CONFIRM_EMPTY_FIELD)

    def _do_unconfirm_all(self, p: dict) -> dict:
        self._unconfirm_undo = [i for i, row in enumerate(self.model.rows) if row.confirmed]
        self.model.unconfirm_all()
        return {"undo_count": len(self._unconfirm_undo)}

    def _do_restore_confirmed(self, p: dict) -> dict:
        restored = 0
        for index in self._unconfirm_undo:
            if index < len(self.model.rows):
                self.model.set_confirmed(index, True)
                restored += 1
        self._unconfirm_undo = []
        return {"restored": restored}

    def _do_step_preview(self, p: dict) -> None:
        if self.records:
            self.preview_index = (self.preview_index + int(p["delta"])) % len(self.records)

    # ---- 저장
    def _do_set_name(self, p: dict) -> None:
        self.job_name = p["name"]

    def _do_set_pattern(self, p: dict) -> None:
        self.pattern = p["pattern"]

    # (_do_set_dataset_name·_dataset_gate 는 #347 에서 삭제 — 저장 시 데이터 자동등록
    #  (#18·#26)이 U2 §5.3 판정 D 로 폐기됐다. §2.8 이 기록한 danger 경보 인플레이션의
    #  발화 지점 자체가 없어졌고, 등록은 데이터 선택 면의 「이 데이터 고정」 하나다.)

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
        if content_fingerprint(current) != self._editing_fingerprint:
            return (
                f"편집 중 외부 변경: 작업 '{self._editing_origin}' 이 이 편집 세션을 "
                "여는 사이 다른 곳에서 바뀌었습니다.\n지금 저장하면 그 변경 내용을 "
                "이 편집 세션의 상태로 덮어씁니다."
            )
        return ""

    def _overwrite_gate(self) -> str:
        """덮어쓰기 확인이 필요하면 그 재진술 문구, 아니면 ``""`` — **쓰기 잠금 안** 판정(#149).

        두 갈래를 한 판정으로 모은다: 자기-갱신의 '편집 중 외부 변경'(지문 불일치)과, 이름을
        바꿔 남의 자리를 덮는 경우의 victim 재진술. 둘 다 디스크를 읽어 판정하므로 잠금 밖에서
        내리면 **읽은 상태와 실제로 덮는 상태가 갈라질 수 있다** — 사용자가 읽고 확정한 문안이
        실제로 일어난 일과 다른 것은 이 저장소의 지배 결함류다. 호출자(:meth:`_save_locked`)가
        잠금 안에서 부르고, 확인된 문안과 대조까지 한다.
        """
        self_update = bool(self._editing_origin) and self.job_name == self._editing_origin
        if self_update:
            return self._editing_drift_text()
        if not needs_overwrite_confirm(self.job_name, None, self.registry.exists(self.job_name)):
            return ""
        try:
            victim = self.registry.load(self.job_name).name
        except Exception:  # noqa: BLE001  손상 파일 → 이름 불명(추측 금지)
            victim = ""
        return overwrite_confirm_text(self.job_name, victim)

    def _missing_template_block(self) -> str:
        """세션 템플릿 파일이 사라졌으면 거절 문안, 아니면 ``""``(#320 심층 방어).

        재정산(:meth:`reconcile_template_mutation`)은 삭제를 danger 로 재진술하고 세션을
        붙잡아 두지만(복원 왕복을 살리려고 경로를 지우지 않는다), 그 상태로 저장하면 실행
        시점에야 터지는 죽은 템플릿 작업이 durable 로 남는다. 링1 ``validate_save`` 는 순수
        메모리 판정 계약이라(:meth:`_do_save` 참조) 파일시스템 접촉은 링2 인 여기 몫이고,
        재진술은 **기존 차단 채널**(``block_reason``)로 나간다 — 새 채널을 만들지 않는다.

        통지를 못 받은 경로(앱 밖 삭제 등)도 여기서 걸린다. 디스크를 읽으므로 쓰기 잠금
        안에서만 부른다(#149 규율, :meth:`_cross_media_block` 동형).
        """
        if not self.template_path:
            return ""  # 템플릿 미선택은 validate_save 의 자리다(여기서 두 번 말하지 않는다)
        if Path(self.template_path).is_file():
            return ""
        return (
            f"'{Path(self.template_path).name}' 템플릿 파일이 없어 저장하지 않았습니다. "
            "삭제를 되돌리거나 다른 템플릿을 선택하세요."
        )

    def _cross_media_block(self) -> str:
        """저장 대상 자리의 기존 작업과 이 세션의 매체가 갈리면 거절 문안, 아니면 ``""``(§10.16 판정 D).

        F6 PR-B 가 편집기에 TXT 를 들이며 열린 경로다: TXT 초안을 기존 HWPX 작업 이름으로
        저장하면 :meth:`_preserved_for_target` 이 victim 의 이력·즐겨찾기·검토 기준선을
        보존해 이력 위조가 된다(`last_run_at` 의 뜻은 매체가 정한다 — §19.4). 덮어쓰기
        확인의 승격이 아니라 **거절**이다 — 작업 방식은 생성 시점에 정해져 바뀌지 않는다
        (판정 A). 자기-갱신 분기도 일부러 가른다: 편집 사이 외부에서 같은 이름이 다른
        매체 작업으로 교체됐으면 '외부 변경' 확인만으로 덮는 것도 같은 위조다(심층 방어).
        **미상 매체 victim(로드 성공, `.docx` 등)도 거절이다**(리뷰 4R P2 — 손상과 다르다):
        로드가 성공하므로 `_preserved_for_target` 이 그 이력·즐겨찾기를 그대로 보존하는데,
        어느 매체의 술어로도 읽을 수 없는 이력이 새 방식에 이식되면 같은 위조다. 그 작업의
        정도(正道)는 덮어쓰기가 아니라 relink 복구(미상→기지, §10.16 판정 C)다.
        손상 victim(로드 실패)만 여기서 판정하지 않는다 — 보존 메타가 빈 값으로 서서 위조가
        없고, 기존 덮어쓰기 게이트의 victim 재진술 소관이다. 디스크를 읽으므로 쓰기 잠금
        안에서만 부른다(#149 규율, :meth:`_overwrite_gate` 동형).
        """
        if not self.registry.exists(self.job_name):
            return ""
        try:
            victim = self.registry.load(self.job_name)
        except Exception:  # noqa: BLE001 — 손상: _overwrite_gate 의 victim="" 문안 소관
            return ""
        draft_media = template_media(self.template_path) if self.template_path else "hwpx"
        if victim.media != draft_media:
            victim_label = work_mode_label(victim.work_mode)  # 미상은 「지원 작업 방식 확인 필요」
            return (
                f"작업 이름 '{self.job_name}' 은(는) 이미 '{victim_label}' 작업입니다. "
                "형식이 다른 작업은 덮어쓸 수 없으니 다른 이름으로 저장하거나 "
                "기존 작업을 삭제한 뒤 다시 저장하세요."
            )
        return ""

    def _preserved_for_target(self) -> "dict[str, object]":
        """저장 대상 파일이 **자기 것으로 유지해야 하는** 비-편집 메타(잠금 안에서 호출).

        세 갈래다(리뷰 3R P2 — 종전엔 세 경우 모두 편집 원점의 메타를 실어 남의 파일에
        원점의 순위·이력을 이식했다):

        - **자기-갱신**(대상 == 편집 원점): 원점 메타를 디스크에서 재읽어 보존. 편집 세션이
          열린 사이 홈에서 단 태그·다른 표면의 별을 stale 스냅샷으로 되돌리지 않는다.
        - **남의 자리 덮어쓰기**(대상이 이미 존재하는 다른 작업): **대상(victim)의** 메타를
          유지한다. 확인 문안이 약속한 것은 "그 파일을 덮어쓴다"이지 "그 작업의 분류·이력·
          즐겨찾기를 내 것으로 바꾼다"가 아니다 — 원점 메타를 실으면 남의 즐겨찾기가 조용히
          꺼지거나 남의 카드에 내 실행 이력이 붙는다. 매체가 같은 경우만 여기 도달한다
          (:meth:`_cross_media_block` 선차단, §10.16 판정 D — 교차 보존은 이력 위조).
        - **빈 자리에 새 이름**: 분류(그룹·태그)는 편집을 따라가되(사본이 「그룹 없음」으로
          조용히 튀지 않게 — 「기안」 저장의 같은 결정) **이력·즐겨찾기는 계승하지 않는다**:
          새 identity 는 실행된 적도, 사용자가 고른 적도 없다(복제 규칙과 동형).
        """
        target = self.job_name
        if self._editing_origin and target == self._editing_origin:
            try:
                return _preserved_meta(self.registry.load(self._editing_origin))
            except Exception:  # noqa: BLE001 — 원본이 사라졌으면 스냅샷 유지(추측 없음)
                return dict(self._preserved_meta)
        if self.registry.exists(target):
            try:
                return _preserved_meta(self.registry.load(target))
            except Exception:  # noqa: BLE001 — 손상 파일: 추측 대신 빈 메타로 새로 시작
                return dict(_EMPTY_PRESERVED)
        origin = dict(self._preserved_meta)
        if self._editing_origin:
            try:
                origin = _preserved_meta(self.registry.load(self._editing_origin))
            except Exception:  # noqa: BLE001
                pass
        return {**_EMPTY_PRESERVED, "tags": dict(origin["tags"]),  # type: ignore[arg-type]
                "group": origin["group"]}

    def _do_save(self, p: dict) -> dict:
        """저장 게이트 → 덮어쓰기 확인 → 저장. 결과 dict 로 재진술.

        웹은 ``needs_overwrite`` 이면 재진술 확인 후 ``confirm_overwrite`` 를 실어
        재호출한다. 덮어쓰기 확인은 **본 문안을 그대로 되돌려 준다**
        (``confirmed_overwrite_text``) — 아래 참조. (자동등록 확인 왕복
        ``needs_dataset_confirm``/``confirm_dataset`` 은 #347 에서 게이트째 사망.)

        편집 모드(#26): 원점 이름 그대로의 재저장은 자기-갱신이라 **디스크가 로드 시점
        그대로일 때만** 덮어쓰기 확인을 묻지 않는다(레지스트리 가드의 '같은 이름 재저장
        통과' 철학 미러). 편집 사이 외부에서 같은 이름 작업이 교체됐으면 '편집 중 외부
        변경' 확인을 승격한다(무확인 파괴 금지). 이름을 바꿔 다른 작업을 덮으려는 경우는
        평소처럼 확인을 요구한다. 태그·마지막 실행 메타는 보존.

        게이트 판정은 **쓰기 잠금 안**에서 내린다(#149). 잠금 밖 선판정은 판정과 실행 사이에
        디스크가 바뀔 수 있어 ①확인 없이 외부 변경을 덮거나 ②읽은 문안과 다른 자리를 덮는다.
        검증(``validate_save``)은 순수 메모리 판정이라 잠금 밖에 남는다.
        """
        verdict = validate_save(
            self.model, self.job_name, self.pattern, schema=self.schema,
            # 데이터 결속은 저장 게이트다(#932 U4-C S2-3) — 세션이 선 경로를 그대로 넘긴다.
            # 「데이터 없이 진행」은 이 술어와 함께 사라졌다(S2-4).
            data_path=self.data_path,
            # 파일명 패턴 게이트는 매체 인지(F6 PR-B) — TXT 는 파일 이름 축이 없다(§3.2).
            media=template_media(self.template_path) if self.template_path else "hwpx",
        )
        if not verdict.ok:
            # 어느 칸을 고쳐야 하는지도 함께 돌려준다(U2 §2.4) — 표면이 차단 문구를 파싱해
            # 알아내면 문안을 고칠 때마다 조준이 조용히 깨진다.
            return {
                "ok": False,
                "block_reason": verdict.block_reason,
                "blocked_field": verdict.blocked_field,
            }
        # 태그·마지막 실행 메타는 편집 세션 밖(홈 태그 편집 등)에서 바뀌었을 수 있어
        # load_job 시점 스냅샷이 아니라 저장 직전 디스크 상태를 다시 읽어 보존한다 — 편집
        # 세션이 열린 사이 홈에서 단 태그를 조용히 되돌리지 않는다(#26 confirm-or-alarm).
        #
        # 이 재읽기~저장 구간 전체가 **한 임계구역**이다(#129 리뷰 2R P1): 보존 값을 읽은 뒤
        # 저장까지 사이에 다른 writer(생성 스레드의 last_run_at 스탬프)가 끼면, 여기서 만든
        # Job 이 방금 찍힌 시각을 낡은 값으로 되돌린다. 잠금은 레지스트리가 소유해 모든
        # writer 가 공유한다 — 저장 한 번만 원자적인 것으로는 lost update 가 안 막힌다.
        with self.registry.write_lock():
            result = self._save_locked(p, verdict)
        saved_job = (
            self.registry.load(str(result["saved_name"])) if result.get("ok") else None
        )
        # T3/T10 작업 저장(#894) — 레지스트리 쓰기가 성립한 **직후**다. 뒤따르는 Field Binding
        # 검토가 실패해도 저장 자체는 이미 커밋됐으므로(`legacy_saved`) 그 갈래에서도 체크가
        # 선다: 하지 않은 일을 했다고 말하지 않는 것과 대칭으로, 한 일을 안 했다고도 하지
        # 않는다. HWPX/TXT 갈림은 링0 파생 사실(``Job.media``)이라 여기서 재판정하지 않는다.
        if saved_job is not None:
            self._tutorial(
                Milestone.SAVE_TXT_JOB if saved_job.media == "txt" else Milestone.SAVE_JOB
            )
        if (
            not result.get("ok")
            or self._after_mapping_saved is None
            or not (
                self.session.context.target.startswith("binding/")
                or (
                    saved_job is not None
                    and saved_job.media == "hwpx"
                    and bool(saved_job.authority_id)
                )
            )
        ):
            # 확정을 부르지 않은 갈래여도 저장본은 움직였다 — 확정 대기는 저장본의 사실이라
            # 여기서도 다시 잰다(#911). 잰 뒤에 반환해야 이 저장의 스냅샷이 최신을 싣는다.
            self._refresh_binding_confirm_pending()
            return result
        try:
            self._after_mapping_saved(str(result["saved_name"]))
        except Exception as exc:  # noqa: BLE001 - legacy save is already committed.
            message = (
                "작업 Mapping은 저장됐지만 Field Binding 검토를 완료하지 못했습니다: "
                f"{exc}"
            )
            self._set_notice(message, "danger")
            # 확정이 실패했으면 대기는 여전히 참이다 — 실패를 성공처럼 접어 동사를 걷지 않는다.
            self._refresh_binding_confirm_pending()
            return {
                "ok": False,
                "legacy_saved": True,
                "binding_commit_ok": False,
                "saved_name": result["saved_name"],
                "block_reason": message,
            }
        # 확정이 성립했다 — 대기 사실을 다시 재서 footer 의 확정 동사가 스스로 걷히게 한다.
        self._refresh_binding_confirm_pending()
        return result

    def _save_locked(self, p: dict, verdict) -> dict:
        """저장 임계구역 몸통 — 게이트 판정부터 저장까지(레지스트리 쓰기 잠금 안).

        덮어쓰기 게이트는 **확인한 문안과 지금 문안을 대조**한다(#149). 사용자가 모달을 읽는
        사이 디스크가 바뀌면 확인은 다른 상태에 대한 것이 되므로, 문안이 달라졌으면 새 문안으로
        **다시 묻는다** — 덮어쓰기는 되돌릴 수 없어 결과 재진술로 갈음하지 않는다. 문안이
        같으면 통과(같은 사실을 확인한 것). 게이트가 사라졌으면(외부 변경이 되돌려짐 등) 덮을
        것이 없으므로 그냥 통과한다.
        """
        # 템플릿 실재 선차단(#320 심층 방어) — 사라진 템플릿을 가리키는 작업을 만들지 않는다.
        missing = self._missing_template_block()
        if missing:
            return {"ok": False, "block_reason": missing}
        # 교차 매체 선차단(§10.16 판정 D) — 거절될 저장에 덮어쓰기 확인부터 보여주지 않는다.
        blocked = self._cross_media_block()
        if blocked:
            return {"ok": False, "block_reason": blocked}
        gate_text = self._overwrite_gate()
        if gate_text and (
            not p.get("confirm_overwrite")
            or p.get("confirmed_overwrite_text", "") != gate_text
        ):
            return {"ok": False, "needs_overwrite": True, "overwrite_text": gate_text}
        # (선언 데이터 자동등록(#18·#26)과 그 게이트는 #347 에서 폐기 — U2 §5.3 판정 D.
        #  이 세션이 고른 데이터는 검토용 문맥일 뿐 작업에 저장되지 않고, 풀 등록은 데이터
        #  선택 면의 「이 데이터 고정」 명시 행동 하나다. §2.8 의 danger 경보 인플레이션이
        #  이 게이트의 발화였고, 발화 지점째 사라졌다.)
        preserved = self._preserved_for_target()
        # 작성 출처 지문(#53-C) — 순수 설명 메타(실행 경로 무영향). 저장 매핑에 새긴다.
        verdict.profile.provenance = self._build_provenance(verdict.profile)
        job = Job(
            name=self.job_name,
            template_path=self.template_path,
            mapping=verdict.profile,
            filename_pattern=self.pattern,
            # 데이터 결속은 이 화면이 **다시 짓는** 것이다(U4 §2.4, #932 U4-C) —
            # 그래서 ``_preserved_meta`` 가 아니라 세션 값을 싣는다. 결속을 쓰는 자리는
            # 저장 하나뿐이라(사용자 확정 2026-08-29) 「데이터 바꾸기 → 저장」이 결속
            # 변경의 유일 동선이다.
            data_path=self.data_path,
            data_sheet=self.data_sheet,
            data_header_row=self.data_header_row,
            data_kind=self.data_kind,
            # 비-편집 메타는 사전 하나에서 통째로 되싣는다(_preserved_meta 단일 출처) —
            # 편집이 그룹·즐겨찾기를 조용히 초기화하던 자리(슬라이스 2 인접 수선).
            last_run_at=str(preserved["last_run_at"]),
            tags=dict(preserved["tags"]),  # type: ignore[arg-type]
            group=str(preserved["group"]),
            favorited_at=str(preserved["favorited_at"]),
            reviewed_rules=dict(preserved["reviewed_rules"]),  # type: ignore[arg-type]
            authority_id=str(preserved["authority_id"]),
        )
        # 위 게이트(needs_overwrite_confirm→confirm_overwrite)가 victim 을 재진술 확인시킨 뒤라
        # slug 충돌이어도 사용자가 확정한 상태 → core 가드에 명시적 opt-in 을 통과한다.
        self.registry.save(job, allow_overwrite=True)
        saved = self.job_name
        # 저장 착지 = **제자리**(U2 §2.14) — 신규·편집 불문 현재 탭 그대로. 구판은 신규 세션을
        # binding 으로 내렸는데, hwpx 신규 저장은 filename(3단계)에서 일어나므로 3→2 로 **뒤로
        # 가는** 착지였다(txt 는 binding 이 마지막 탭이라 무변화). 구판 ``_reset()`` 결함(빈
        # 마법사 방치·성공 표지 증발)의 되깎기 조건은 이미 충족돼 있다 — 아래 저장본 재로드
        # (emit_push=False)와 notice(ok) 채널이 각각 막는다. 분기값은 그 두 방어 어디에도
        # 참여하지 않으므로 지운다.
        landing_section = self.section
        # 저장 착지 = 방금 저장한 작업의 **편집 세션**(결정 40 저장 제자리 · 결정 41 전환점=저장:
        # 초안은 저장으로 작업이 되고 이후 편집은 탭). 구판 ``_reset()`` 은 사용자를 빈 0단계
        # 마법사에 방치하고, 그 리셋 push 가 성공 표지(#save-msg)를 지워 완결 신호가 증발했다
        # (리뷰 F2 — 슬라이스 4 push/반환 경합류). 재로드는 디스크 저장본 기준이라 지문·원점이
        # 새로 서고, 클린 착지(_session_clean)라 직후 전환·새 작업이 헛확인을 띄우지 않는다.
        # dispatch 가 notice 설정 뒤 최종 스냅샷을 한 번 push 한다. 재로드 중간 push 를 막아
        # 저장 한 번에 화면 전체가 여러 번 재구성되는 깜빡임을 없앤다.
        # 저장 착지도 **문맥을 잃지 않는다**(F7): 진입 사유·증거·복귀처는 저장 한 번으로
        # 사라지지 않는다 — 미리보기에서 값을 고치러 온 사람은 저장 뒤에도 미리보기로
        # 돌아가야 하고, 그 복귀 버튼이 저장으로 증발하면 문맥은 있으나 마나가 된다.
        self._restore_from(
            self.registry.load(saved),
            landing_section=landing_section,
            context=self.session.context,
            emit_push=False,
            probe_binding=False,  # 쓰기 잠금 안 — 확정 대기는 `_do_save` 가 잠금 밖에서 잰다.
        )
        # 착지 재로드가 결속 데이터를 못 읽었으면 그 사유를 성공 문안으로 덮지 않는다
        # (#932 U4-C S2-1) — 덮으면 화면은 빈 데이터 관문인 채 "저장했습니다"만 말한다.
        if self._reload_failure:
            self._set_notice(
                f"작업 '{saved}' 을(를) 저장했습니다."
                f"\n연결된 데이터를 다시 읽지 못했습니다: {self._reload_failure}",
                "warn",
            )
        else:
            self._set_notice(f"작업 '{saved}' 을(를) 저장했습니다.", "ok")
        return {"ok": True, "saved_name": saved}
