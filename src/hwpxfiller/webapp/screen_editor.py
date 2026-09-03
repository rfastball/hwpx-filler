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

from ..domain.dataset_reference import STATUS_ACTIVE
from ..domain.job import (
    DEFAULT_FILENAME_PATTERN,
    Job,
    data_binding_of,
    has_data_binding,
    template_media,
)
from ..domain.mapping import MappingProfile
from ..domain.schema import FieldSpec, TemplateSchema, extract_schema, infer_type
from ..domain.template_status import library_display_name

from ..domain.text_render import SEG_MISSING, render_segments, template_fields
from ..data.factory import (
    pclm_reference,
    source_for_binding,
    source_for_path,
    source_from_pool_item,
)
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.template_root import TemplateRoot
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
    NAME_DERIVED_HINT,
    derive_job_name,
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from ..gui.mapping_state import (
    NO_SOURCE_LABEL,
    RAW_BLOCK_MESSAGE,
    SPECIAL_SOURCE_LABEL,
    MappingModel,
    PartialGate,
    gate_for_template,
    pairing_preview,
    profile_source_vocabulary,
    row_projection,
)
from ..external.hwpx_package_io import read_hwpx_package
from ..gui.template_manager_state import CONVERT_ACTION_LABEL as RAW_CONVERT_LABEL
from ..gui.tutorial_state import Milestone
from ..gui.work_mode import work_mode_label  # 교차 매체 거절 문안의 방식 라벨(§19.1)
from ..domain.output_name import format_seq_token
from ..naming import make_output_filename, pattern_uses_seq, seq_token_pads
from .output_folder_zone import output_folder_zone
from .screens import (
    MUTATION_KINDS,
    NO_ROWS_TEXT,
    TXT_RAW_BLOCK,
    PushSink,
    TutorialSink,
    dataset_reference_identity,
    load_pool_into,
    pool_reference_quad,
    registered_dataset_name,
    reference_missing,
    unwired_tutorial,
)
from .template_groups import norm_library_path

# 2단계 데이터 미리보기에 싣는 샘플 행 수(#16 98DDFE96) — 전체 적재는 이미 self.records
# 에 있으나 스냅샷엔 매핑 감(感)만 주는 소량만 노출한다(record_count 로 "외 M건" 표기).
_SAMPLE_ROWS = 3

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


#: 세션 템플릿이 서식 폴더 밖이라 항목 상세를 열 수 없을 때의 사유(U6-E 리뷰 5).
#: 저장본이 든 절대경로는 루트 재지정·폴더 이동 뒤에도 살아 있을 수 있는데, 시트는 `tpl`
#: 채널이 아는 항목만 연다 — 조용히 실패하는 버튼 대신 비활성 + 사유를 세운다.
SESSION_DETAIL_OUTSIDE_TEXT = (
    "서식 폴더 밖의 템플릿이라 항목 상세를 열 수 없습니다. 설정에서 서식 폴더를 확인하세요."
)
#: 관문 미배선(테스트 단독 구동·비완전 조립)의 사유 — 없는 표면을 있다고 말하지 않는다.
SESSION_DETAIL_UNWIRED_TEXT = "템플릿 라이브러리 관문이 배선되지 않아 항목 상세를 열 수 없습니다."

#: 작성 당시와 지금의 템플릿 필드 구성이 갈렸을 때의 경고(#53-C 승계 · U6-E 리뷰 6).
#: **세션 판정**이라 풀 항목 시트가 아니라 1단계 게이트 존에 선다: 이 작업이 저장될 때
#: 기록한 필드 지문과 지금 연 파일의 필드가 다르다는 뜻이고, 그건 이 세션의 사실이다.
PROVENANCE_DRIFT_TEXT = (
    "작성 당시와 템플릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다."
)


#: 연번 예시의 이름 구분자 — 이름 기본값과 **같은 글자**다(문장 안 em dash 금지, §3-1).
_EXAMPLE_SEPARATOR = " · "


def _sequence_example(first: str, pattern: str) -> str:
    """첫 이름 + **연번 자리의 다음 두 값**(순수) — ``X-001.hwpx · 002 · 003``.

    이 규칙이 만드는 것은 파일 하나가 아니라 여러 건이고, 첫 이름만 보면 「번호가 어디에
    붙는가」를 모른 채 저장한다. 그래서 뒤 둘을 잇는다.

    **판정도 서식도 패턴이 낸다**(리뷰 5): 연번이 있는지는
    :func:`~hwpxfiller.naming.pattern_uses_seq`(토큰 판정기 단일 출처)가 답하고, 붙는 모양은
    그 토큰의 폭(:func:`~hwpxfiller.domain.output_name.format_seq_token`)이 답한다. 종전에는
    만들어진 이름 셋의 공통 앞·뒤를 걷고 숫자 자리를 되감아 「달라지는 부분」을 유추했는데,
    그 휴리스틱은 **연번에 붙어 있는 데이터 값**을 연번으로 오인한다 —
    ``A{{연도}}{{seq}}`` 는 ``A20261.hwpx · 20262 · 20263`` 이 되어 연도가 매 건 바뀐다고
    말한다(값이 그대로인데). 토큰이 아는 것을 문자열에서 되추측하지 않는다.

    seq 토큰이 없으면 **첫 이름 하나**만 낸다: 없는 연번을 있는 것처럼 그리면 실제로는
    이름 셋이 충돌하는 자리를 정상으로 보이게 한다.
    """
    if not first or not pattern_uses_seq(pattern):
        return first
    pads = seq_token_pads(pattern)
    # 폭은 **첫 토큰**의 것이다 — 한 패턴에 seq 가 둘 이상이면 같은 값이 같은 폭으로 두 번
    # 박히므로 어느 쪽을 읽어도 같고, 없으면 폭 0(``{{seq}}``)이다.
    pad = pads[0] if pads else None
    tails = [format_seq_token(pad, n) for n in (2, 3)]
    return _EXAMPLE_SEPARATOR.join([first, *tails])


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
        template_root: "TemplateRoot | None" = None,
        remembered_output_directory: "Callable[[], str] | None" = None,
        is_library_path: "Callable[[str, str], bool] | None" = None,
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
        # (`template_groups`·`txt_groups` 주입은 U6-B(#976)에서 퇴역했다 — 목록 성형이
        #  `tpl` 채널 하나로 모이면서 이 화면에 그룹 모델 소비자가 0 이 됐다. 모델·영속
        #  자체는 U4 §2-30 의 동결 그대로 tpl 컨트롤러가 계속 든다.)
        # 서식 폴더 권위(U6-A #975) — **앱 조립에선 tpl 화면과 같은 인스턴스**를 주입한다.
        # 이 화면이 루트를 쓰는 자리는 하나로 좁아졌다(U6-E #979): 표시명 도출
        # (`library_display_name` — 루트 상대·확장자 없음). 라이브러리 VM·TXT 레지스트리의
        # 지연 생성은 함께 퇴역했다 — 목록도 소속 판정도 `tpl` 채널 하나가 진다. 홀더는
        # 상태를 캐시하지 않으므로(매 호출이 설정을 다시 읽는다) 재지정 직후의 첫 스냅샷이
        # 곧 새 루트다. 미주입이면 표준 홀더를 지연 생성한다.
        self._template_root_holder = template_root
        # **전역 저장 폴더의 소유자는 작업 화면 하나다**(리뷰 3). 이 화면은 그 값을 읽기만
        # 하므로 설정 파일을 직접 읽지 않고 그쪽의 메모리 값을 **콜러블로** 받는다: 디스크를
        # 다시 읽으면 설정 쓰기가 실패한 순간 두 표면이 서로 다른 폴더를 말한다(한쪽은 방금
        # 고른 값, 한쪽은 디스크의 옛 값). 미주입이면 도출 재료가 없다 — 없는 값을 추측하지
        # 않고 빈 문자열이며, 그때 도출은 템플릿 옆 ``Results`` 로 내려간다.
        self._remembered_output_directory = remembered_output_directory
        # 라이브러리 소속 관문(U6-E #979) — `tpl` 채널의 공개 술어
        # (:meth:`~hwpxfiller.webapp.screen_template.TemplateController.is_live_path`)를
        # **handoff callable** 로 받는다(`after_mapping_saved` 선례). 종전에는 이 화면이
        # 자기 hwpx VM·자기 TXT 레지스트리를 들고 같은 판정을 다시 썼다 — 같은 질문에 답하는
        # 스캔이 둘이라 한쪽만 최신인 순간이 실재했고, 그 둘이 곧 편집기가 tpl 과 별개로
        # 들고 있던 템플릿 관리 중복이었다. 미주입이면 관문이 없다: 통과시키지 않고 시끄럽게
        # 거절한다(:meth:`assert_library_path`) — 바깥 파일 입구를 무배선으로 여는 것이
        # 이 seam 이 막는 바로 그 결함이다.
        self._is_library_path = is_library_path
        # (`library_result`·`library_slots` 중계 seam 은 U6-B(#976)에서 퇴역했다: 결과 줄과
        #  구간 항목 목록의 정본은 `tpl` 채널 스냅샷이고, 편집기 표면이 그 채널을 직접
        #  구독하면서 편집기 스냅샷이 같은 값을 한 번 더 실어 나를 이유가 사라졌다.)
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
        # (이 세션이 연 템플릿의 구간 축 요약 `template_slots`(U4-E2 #939)은 U6-E(#979)에서
        #  퇴역했다 — 그 존은 항목 상세 시트로 흡수됐다. 판정 승계는 `UX_FEEDBACK_U6` §2.9:
        #  동사는 편집 세션이 아니라 **풀 항목(파일)** 을 겨누고, 세션과 같은 파일일 때의
        #  무효화는 `reconcile_template_mutation` seam 이 그대로 진다.)
        self.data_path = ""
        self.data_sheet = ""  # 다중 시트 확정값(#33) — 자동등록 참조에 함께 저장(#26)
        # 헤더 행(엑셀 참조 옵션) — 0 = 미지정(어댑터 기본 1행). 등록 데이터를 든 진입
        # (#349 리뷰 P1)이 채운다: 참조를 경로로만 줄이면 사용자가 고른 것과 **다른 헤더**로
        # 마법사가 서고, 그 어긋남은 화면 어디에도 표시가 없다.
        self.data_header_row = 0
        # 결속의 **종류**(""=엑셀/CSV) — 위 세 성분과 한 벌이다. 저장이 그대로 Job 에 실어
        # durable 이 되므로(`_EDITOR_REBUILDS` 갈래) 세션 리셋에서 함께 선다.
        self.data_kind = ""
        # 지금 마운트가 겨눈 **풀 슬롯 키**(U6-B #976 — `screen_job.data_pool_key` 미러).
        # 고르기 단계의 우 열이 「어느 항목이 선택돼 있는가」를 이 값으로 그린다: 표면이
        # 경로를 대조해 되추측하면 정체성 규칙(kind-스코프 · #347)이 두 곳에 산다. 파일
        # 마운트는 슬롯이 없으므로 빈 값이고, 그 자리는 「고정」 동사가 대신 선다.
        self.data_pool_key = ""
        # 결속 정체성 → 등록명 memo(U6-D #978 리뷰 2) — 조회가 풀 폴더 스캔이라 스냅샷마다
        # 지불하지 않는다. 마운트와 세션 리셋이 비우고, 그 둘이 정체성이 바뀌는 전부다.
        # (세션 표지 `data_pool_name` 은 여기서 사망했다: 「방금 풀에서 골랐다」를 세션에
        #  기억하면 저장하고 다시 연 세션이 같은 데이터를 다른 이름으로 부른다.)
        self._data_name_cache: "tuple[str, str] | None" = None
        # 이 세션이 **서 있는 기준**의 데이터(#878) — 진입이 들고 온 것이면 그 참조, 사람이
        # 관문에서 고른 것이면 빈 값. `_extras_of` 의 기준값이라 「저장본과 다르다」의 뜻이
        # 여기서 갈린다: 인계 데이터를 변경으로 세면 손대지도 않은 진입이 곧바로 미저장이 돼
        # 이탈마다 헛확인이 뜬다(사람이 그 파일을 고른 적이 없다).
        self._entry_data: "dict[str, str]" = {"data_path": "", "data_sheet": ""}
        # 데이터의 **전체** 헤더. 「사용할 데이터 열」 선별(구 `_ignored_sources`·펼침 힌트)은
        # U6-C(#977 · U6 §2.5)에서 사슬째 퇴역했다 — 스키마 재활용 전제가 사라졌고, 매핑되지
        # 않은 열은 자연히 쓰이지 않는다. 남은 질문 하나(안 쓰는 열이 몇인가)는 링1
        # `unused_source_fields` 가 답하고 표 바닥 한 줄이 잇는다.
        self.source_fields: "list[str]" = []
        self.records: "list[dict]" = []
        self.model: "MappingModel | None" = None
        self._model_key: "tuple | None" = None
        # 연결 카드 미리보기 수치의 memo(리뷰 7) — `(정체 키, (자동, 확인 필요))`.
        # 세션 리셋이 함께 비운다: 남기면 새 짝의 카드가 지난 짝의 수치를 말한다.
        self._pairing_cache: "tuple[tuple, tuple[int, int]] | None" = None
        self.preview_index = 0
        self.job_name = ""
        # 지금 이름이 **도출값인가**(U6-D #978) — 세션 표지 하나다.
        #
        # 이 표지가 지는 것 셋: ①고르기가 바뀔 때 이름을 다시 도출할지 ②힌트를 세울지
        # ③dirty 기준선을 무엇으로 잡을지. 셋을 각자 판정하면 「사용자가 고친 이름을 다음
        # 데이터 마운트가 덮어쓰는」 것과 「도출값이 곧바로 미저장 변경이 되는」 것이 서로
        # 다른 조건에서 되살아난다. 초안 진입이 참, ``load_job`` 과 사람의 편집이 거짓이다.
        self._job_name_is_derived = True
        # 그 도출값의 **기록**(리뷰 9) — dirty 기준선이 이것이다. 기준선을 매 스냅샷에서 다시
        # 도출하면 도출의 입력(표시명)이 바뀌는 순간(서식 폴더 재지정 등) 손대지도 않은 초안이
        # 「저장하지 않은 변경」으로 선다: 기준선과 현재값이 서로 다른 시점의 도출이 된다.
        self._derived_name_baseline = ""
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
        # 게이트 존 「자세히…」 가부의 memo(U6-E 리뷰 5) — `(경로, 판정)` 한 벌.
        # 관문 질의는 서식 폴더 스캔을 물 수 있어 스냅샷마다 지불할 것이 아니다. 무효화는
        # 템플릿이 바뀌는 두 자리(:meth:`load_template_path` · 세션 리셋)뿐이고, 그것이 곧
        # 이 판정의 입력이 바뀌는 전부다.
        self._session_detail_cache: "tuple[str, dict] | None" = None

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

    # ------------------------------------------------- 표시명(U6-D #978)
    def template_display_name(self) -> str:
        """이 세션 템플릿의 **표시명** — 1단계 좌 열이 부르는 그 이름이다.

        종전에는 편집기가 basename+확장자(``공고서.hwpx``)를 실어 나르고 좌 열은
        :func:`~hwpxfiller.domain.template_status.library_display_name` 의 루트 상대·확장자
        없는 이름(``온나라/기안``)을 그렸다 — 같은 파일을 두 어휘로 부르는 자리였고, 머리
        부제가 목록과 다른 말을 했다. 도출은 그 함수 하나이고 루트는 홀더가 낸다.
        """
        if not self.template_path:
            return ""
        return library_display_name(self.template_root.path(), self.template_path)

    def data_display_name(self) -> str:
        """이 세션 데이터의 **표시명** — 풀에 등록된 데이터면 등록명, 아니면 basename.

        풀 항목의 정체는 사람이 붙인 이름이다(같은 파일을 다른 이름으로 둘 이상 고정할 수
        있다). 경로에서 되짚으면 그 이름이 사라지고, 목록에서 「7월 발주」로 부르던 것이
        여기서는 「대장」이 된다.

        **세션 값이 아니라 풀 조회다**(리뷰 2). 「방금 풀에서 골랐다」를 세션 표지로 기억하면
        저장하고 다시 연 세션은 그 표지가 없어(``_reset``) 같은 데이터를 다른 이름으로 부른다
        — 결속은 durable 인데 이름만 세션 수명이 되는 자리다. 정체성 규칙은 등록 게이트가
        쓰는 것 하나(:func:`~hwpxfiller.domain.dataset_reference.reference_identity`)를 그대로
        지나므로, 경로·시트·종류 세 성분이 여기서 다시 조립되지 않는다.
        """
        if not self.data_path:
            return ""
        registered = self._registered_data_name()
        return registered or Path(self.data_path).stem

    def _registered_data_name(self) -> str:
        """이 결속이 풀에 등록돼 있으면 그 등록명(아니면 ``""``).

        결과는 결속 정체성으로 memo 한다 — 조회가 풀 폴더 스캔이라 스냅샷마다 지불할 것이
        아니다. 무효화는 마운트(:meth:`_adopt_datasource`)와 세션 리셋 두 자리이고, 그것이
        곧 정체성이 바뀔 수 있는 전부다.
        """
        if self._pool_registry is None:
            return ""
        ident = dataset_reference_identity(
            path=self.data_path, sheet=self.data_sheet, kind=self.data_kind
        )
        if not ident:
            return ""
        cached = self._data_name_cache
        if cached is not None and cached[0] == ident:
            return cached[1]
        name = registered_dataset_name(
            self._pool_registry,
            path=self.data_path, sheet=self.data_sheet, kind=self.data_kind,
        )
        self._data_name_cache = (ident, name)
        return name

    def _derived_job_name(self) -> str:
        """지금 고르기로부터 나오는 이름 기본값(링1 순수 함수의 호출 한 줄).

        템플릿 쪽은 **마지막 세그먼트**를 쓴다(리뷰 6): 표시명은 루트 상대경로라 하위 폴더
        템플릿이면 ``온나라/기안`` 이고, 그 슬래시가 작업 이름에 들어가면 레지스트리 slug 가
        경로 구분자를 접어 서로 다른 두 이름이 같은 파일로 저장될 수 있다. 목록이 부르는
        이름(경로 병기)과 **작업의 이름**은 답하는 질문이 다르다.
        """
        return derive_job_name(
            self.template_display_name().rsplit("/", 1)[-1], self.data_display_name()
        )

    def _rederive_job_name(self) -> None:
        """도출 표지가 참일 때만 이름을 다시 채운다 — 템플릿 채택·데이터 마운트 뒤.

        호출 자리를 두 몸통(``load_template_path`` · ``_adopt_datasource``)으로 좁힌 이유는
        갈래마다 부르면 한 갈래가 빠지는 날 「데이터를 바꿨는데 이름은 옛 데이터를 말하는」
        상태가 실재하기 때문이다. 표지가 거짓이면 사람이 지은 이름이라 건드리지 않는다.
        """
        if self._job_name_is_derived:
            self.job_name = self._derived_job_name()
            self._derived_name_baseline = self.job_name

    @property
    def template_root(self) -> TemplateRoot:
        """서식 폴더 권위 — 미주입이면 첫 접근 때 표준 홀더를 지연 생성한다.

        이 화면의 루트 소비자는 하나다(U6-E #979 — 표시명 도출). 종전의 두 지연 생성
        (hwpx VM · TXT 레지스트리)은 각자 ``TemplateRoot()`` 를 새로 만들 수 있었고, 그
        중복은 소속 판정이 `tpl` 채널로 위임되면서 사슬째 사라졌다.
        """
        if self._template_root_holder is None:
            self._template_root_holder = TemplateRoot()
        return self._template_root_holder

    def assert_library_path(self, path: str) -> None:
        """웹 유래 템플릿 경로의 라이브러리 소속 확인 — 바깥 입구 봉쇄의 공용 seam(리뷰 F4).

        use_library_template 가 쓴다(구 크로스스크린 load_template_into_editor 는 F8 사망) —
        한 입구만 막으면 「가져오기=복사가 유일한 바깥 입구」(2부)가 문서만의 불변식이 된다.

        **판정은 `tpl` 채널 하나가 진다**(U6-E #979 —
        :meth:`~hwpxfiller.webapp.screen_template.TemplateController.is_live_path`). 그 관문이
        hwpx 는 재스캔 뒤 판정하고 TXT 는 캐시 없는 실 디스크 스캔이라, 방금 사라진 파일을
        통과시키지 않는 성질이 매체별로 갈리지 않는다. 여기 남은 것은 **거절의 처분**이다:
        불일치면 새 스냅샷을 먼저 push 하고 거절한다(리뷰 F7 — 방금 삭제된 파일의 stale 행이
        남아 같은 클릭을 반복하게 만드는 무행동 안내 금지).

        관문 미배선은 통과가 아니다: 없는 관문을 「열려 있다」로 접으면 이 seam 이 막는 바로
        그 입구가 조립 실수 하나로 열린다.
        """
        gate = self._is_library_path
        if gate is None:
            raise ValueError("템플릿 라이브러리 관문이 배선되지 않아 경로를 확인할 수 없습니다.")
        if not gate(template_media(path), path):
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

        **U6-B(#976) — 1단계 게이트가 데이터까지 요구한다**: 「고르기」가 묻는 질문은
        「어느 템플릿을 어느 데이터에?」 하나이므로(U6 §2.2) 반쪽만 고르고 다음으로
        갈 수 있으면 그 단계가 두 질문을 가진 것이 된다. 데이터 관문이 2단계 머리에서
        걷혔으므로 통과시키면 고칠 표면이 없는 화면에 착지한다 — 저장 게이트
        (:func:`~hwpxfiller.gui.job_editor_state.validate_save`)가 이미 요구하던 것을
        같은 순서로 앞당겨 세운다(술어는 하나, 서는 자리만 늘었다).

        **초안에만 걸리는 규율**(§10.13 판정 M): 저장된 작업 편집은 의존이 전부 충족된
        상태라 탭을 자유 이동한다. 초안은 순서 의존이 실재해(템플릿 없인 매핑 없음) 전진
        마다 게이트를 세운다 — 빈 표를 열어 두고 "채우세요"라고 말하지 않는다.
        """
        if from_section == SECTION_TEMPLATE:
            return self._template_ready() and bool(self.data_path)
        if from_section == SECTION_BINDING:
            return self.model is not None and self.model.is_complete()
        return False

    def _advance_block_reason(self) -> str:
        """1단계에서 다음으로 못 가는 사유(갈 수 있으면 ``""``) — 문안도 여기가 낸다.

        순서는 :meth:`can_advance` 의 술어 순서 그대로다: 템플릿이 필드를 정하고 그 다음에
        그 필드를 채울 데이터가 온다(U4 §2.4). 두 사유를 한 문장에 합치지 않는 이유는
        고칠 자리가 좌·우로 갈리기 때문이다 — 사람은 지금 막힌 한쪽만 고치면 된다.
        """
        if self.raw_block:
            return self.raw_block
        if self.gate_error:
            return "템플릿 상태를 확인할 수 없습니다."
        if not self.template_path:
            return "왼쪽에서 템플릿을 고르세요."
        # 채울 대상이 0 인 템플릿의 사유는 **링1 문안 하나**다(리뷰 3): 아래 미해결 토큰
        # 문장을 돌려쓰면 「토큰을 확인하라」고 말해 놓고 확인할 토큰이 없는 화면을 준다.
        if self.schema is None or not self.schema.fields:
            return RAW_BLOCK_MESSAGE
        if not self._template_ready():
            return "이 템플릿은 아직 진행할 수 없습니다. 미해결 토큰을 확인하세요."
        if not self.data_path:
            return "오른쪽에서 데이터를 고르세요."
        return ""

    def _pairing_snapshot(self) -> dict:
        """고르기 단계 연결 카드 — 「무엇과 무엇이 붙었고 몇 개가 자동으로 이어지는가」.

        **수치의 출처를 명시로 든다**(``basis``). 1단계는 매핑 모델을 만들지 않는다:
        생성은 2단계 진입의 :meth:`_ensure_model` 하나가 지고, 카드가 미리 만들면
        고르기를 바꿔 보는 것만으로 「전원 미확정 재생성」 전이가 돌아 확정이 조용히
        무너진다. 그래서 두 갈래다 —

        - ``model``: 이미 있는 모델의 키가 지금 선택과 같으면 그 모델의 **실제** 수치
          (확인 = 확정 행, 확인 필요 = 나머지). 2단계를 다녀온 뒤 1단계로 돌아온 자리다.
        - ``preview``: 그 밖에는 순수 함수
          (:func:`~hwpxfiller.gui.mapping_state.pairing_preview`)를 읽기 전용으로 한 번
          돌린 미리보기. 2단계가 실제로 세울 제안과 같은 함수라 수치가 갈리지 않는다.

        **이름은 표시명이다**(U6-D #978): ``template_name``·``data_name`` 은 1단계 좌·우
        열이 부르는 그 이름이고(:meth:`template_display_name`·:meth:`data_display_name`)
        확장자·경로를 들지 않는다. 머리 부제도 이 두 키를 읽으므로 단계가 바뀌어도 같은
        이름을 말한다.

        **``ready`` 는 「짝이 실제로 섰는가」다**(리뷰 3): 경로 둘만 보면 채울 필드가 0 인
        템플릿(hwpx RAW · 토큰 0 인 TXT)에서도 참이 되어 「필드 0개 · 자동 연결 0」 카드가
        비활성 CTA 위에 선다 — 화면이 「짝이 섰다」고 말하면서 다음으로 못 가는 자리다.
        그래서 필드 1개 이상까지가 조건이고, 그 사유는 ``advance_block_reason`` 이 진다.

        **수치는 이 단계에서만 센다**(리뷰 7): ``suggest_mappings`` 는 필드×열 SequenceMatcher
        라 매핑 편집의 잦은 push 마다 지불할 것이 아니다. 고르기 단계 밖에서는 세지 않고
        ``basis=""`` 로 **세지 않았음을 명시**한다(0 을 사실처럼 말하지 않는다). 같은 단계
        안의 재렌더는 정체 키(:meth:`_model_key_now`)로 memoize 한다.
        """
        template_name = self.template_display_name()
        data_name = self.data_display_name()
        field_names = [f.name for f in self.schema.fields] if self.schema else []
        ready = bool(self.template_path) and bool(self.data_path) and bool(field_names)
        auto = confirm = 0
        basis = ""
        if ready and self.section == SECTION_TEMPLATE:
            if self.model is not None and self._model_key == self._model_key_now():
                # 모델 수치는 확정 토글마다 바뀌므로 memoize 하지 않는다(행 합 하나라 싸다).
                auto = sum(1 for r in self.model.rows if r.confirmed)
                confirm = len(self.model.rows) - auto
                basis = "model"
            else:
                auto, confirm = self._pairing_preview_cached(field_names)
                basis = "preview"
        return {
            "ready": ready,
            "template_name": template_name,
            "data_name": data_name,
            "field_count": len(field_names),
            "column_count": len(self.source_fields),
            "auto_count": auto,
            "confirm_count": confirm,
            "basis": basis,
            "advance_block_reason": self._advance_block_reason(),
        }

    def _pairing_preview_cached(self, field_names: "list[str]") -> "tuple[int, int]":
        """읽기 전용 미리보기 수치 — 같은 정체 키에서는 **한 번만** 센다(리뷰 7).

        캐시 키는 매핑 모델의 정체 키(:meth:`_model_key_now`)와 같다: 그 키가 곧
        「무엇과 무엇을 붙였는가」이고, 제안 결과가 달라질 수 있는 축이 정확히 그 성분들이다
        (템플릿·데이터 경로·시트·헤더 행·소스 헤더). 별도 키를 지으면 성분 하나를 빠뜨린
        날 카드가 옛 수치를 계속 말한다 — 그래서 있는 키를 그대로 쓴다.

        종전에는 키에 **활성 헤더 튜플**을 함께 실었다. 그 성분이 빠져도 안전한 것은 열
        선별(#49)이 U6-C 에서 퇴역해 제안 후보가 언제나 ``source_fields`` 전부이고, 그
        튜플은 이미 정체 키의 성분이기 때문이다 — 세는 입력이 달라지는 축이 키 안에 남아
        있다.
        """
        key = self._model_key_now()
        cached = self._pairing_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        counts = pairing_preview(field_names, self.source_fields)
        self._pairing_cache = (key, counts)
        return counts

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

    def _extras_of(self, base: "Job | None") -> "dict[str, str]":
        """이 세션이 **서 있는 기준**의 extras — 이름은 저장본의 것, 데이터는 진입이 세운 것.

        데이터 선택은 작업에 저장되지 않으므로(§5.3 — 작업↔데이터 결속 없음) 기준값을 저장본이
        낼 수 없다. 사람이 관문에서 고른 데이터는 종전대로 빈 기준 대비 「달라진 것」이고,
        **진입이 들고 온 데이터**(#878 인계)는 사람이 고른 적이 없으므로 기준 그 자체다 —
        그렇게 세지 않으면 아무것도 손대지 않은 수리 진입이 열리자마자 미저장이 된다.

        ``base`` 가 없으면(초안) 이름의 기준은 빈 문자열이다 — 초안은 아직 이름이 없는 것이
        기준이고, 데이터 축의 면제는 저장본 갈래와 **같은 것 하나**를 쓴다(#945 F7): 인계
        면제가 저장본에만 서면 「이 데이터로 새 작업」 무조작 진입이 곧바로 미저장이 된다.

        **도출된 이름은 변경이 아니다**(U6-D #978): 표지가 참인 동안 기준선은 **재도출 시점에
        기록한 그 값**이다(``_derived_name_baseline``). 빈 문자열을 기준으로 두면 템플릿·데이터를
        고르는 정상 진행이 이름을 채우는 순간 「저장하지 않은 변경」이 켜지고, 아무것도 손대지
        않은 초안이 이탈에서 잃을 것이 있다고 주장한다. 기준선을 여기서 **다시 도출**해도 같은
        결함의 다른 얼굴이 된다(리뷰 9): 도출의 입력이 바뀌면(서식 폴더 재지정으로 표시명이
        갈리면) 기준선과 현재값이 서로 다른 시점의 도출이 되어 손대지 않은 초안이 미저장으로
        선다. 사람이 이름을 고치면 표지가 꺼지고(:meth:`_do_set_name`) 그 뒤로는 종전 규칙
        그대로다.
        """
        name_base = (
            self._derived_name_baseline if self._job_name_is_derived
            else (base.name if base is not None else "")
        )
        return {"job_name": name_base, **self._entry_data}

    def _extras_diff(self, base: "Job | None") -> "tuple[str, ...]":
        """기준 대비 달라진 extras 이름들 — 저장본·초안 두 갈래의 공용 셈."""
        now, was = self._extras_now(), self._extras_of(base)
        return tuple(k for k in self.SESSION_EXTRAS if now[k] != was[k])

    def dirty_extras(self) -> "tuple[str, ...]":
        """**저장본** 대비 달라진 extras 이름들 — 초안은 비교 대상이 없어 빈 튜플이다.

        초안의 셈은 :meth:`has_unsaved_work` 이 :meth:`_extras_diff` 로 직접 한다: 여기서
        초안까지 답하면 「저장본과 다르다」를 참칭한다(비교할 저장본이 없다).
        """
        base = self.session.base
        return () if base is None else self._extras_diff(base)

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

    def _row_snapshot(
        self, index: int, row, record: "dict", *, now: "datetime | None" = None,
    ) -> dict:
        """행 1개의 스냅샷 — 링1 투영(:func:`~hwpxfiller.gui.mapping_state.row_projection`)
        의 얇은 래퍼다(U6-F #980).

        성형이 여기 있던 동안에는 이 표를 읽기 전용으로 한 번 더 세우려는 표면이 **자기
        사본**을 만들 수밖에 없었다(#966 이 라이브러리 상세에서 걷은 그 사슬). 투영이 링1 로
        올라가면서 두 표면이 같은 값을 소비한다 — 이 화면이 더하는 것은 세션 사실 둘
        (지금 헤더·레코드 유무)과 스냅샷당 한 번 찍은 시각뿐이다.

        편집기는 데이터를 이미 들고 있으므로 첫 행 상태는 언제나 ``ready`` 다.
        """
        return row_projection(
            row, record,
            index=index,
            source_fields=self.source_fields,
            has_records=bool(self.records),
            now=now,
        )

    def snapshot(self) -> dict:
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
            # 표시명(U6-D #978) — 루트 상대·확장자 없음. 목록·머리·본문이 한 이름을 쓴다.
            "template_name": self.template_display_name(),
            # 선택 템플릿의 매체(F6 PR-B) — 뷰가 확장자를 재파싱하지 않게 판정을 싣는다.
            "template_media": template_media(self.template_path) if self.template_path else "",
            # 1단계 게이트 존이 말하는 수치 하나(U6-E #979) — 필드 **표**와 나열식 요약
            # (구 `schema_summary`)은 항목 상세 시트로 갔다. 고르기 단계가 답할 질문은
            # 「어느 템플릿을 어느 데이터에?」 하나이고, 「그 템플릿에 무엇이 들어 있나」는
            # 그 답 뒤에 묻는 별개의 질문이라 자리도 따로 선다.
            "field_count": len(self.schema.fields) if self.schema else 0,
            # 이 세션이 **연 파일**의 필드 명세(name/inferred_type/in_table/occurrences/
            # context) — 스키마 파이프라인이 실제로 돌았음의 증거이고 패키징 스모크가 읽는
            # 자리다. 시트의 `detail.fields` 와 겨누는 대상이 다르다: 저것은 풀 항목(파일)의
            # 판독이고 이것은 이 편집 세션이 든 스키마다.
            "fields": [f.to_dict() for f in self.schema.fields] if self.schema else [],
            "raw_block": self.raw_block,
            # 게이트 존의 「자세히…」 가부 + 사유(U6-E 리뷰 5) — 서식 폴더 밖 템플릿에서
            # 열리지 않는 문을 세우지 않는다. 판정·문안은 Python 이고 웹은 비활성 + title.
            "session_detail": self._session_detail(),
            # 작성 출처 드리프트 경고(#53-C 승계 · 리뷰 6) — **세션 판정**이라 여기 산다.
            "schema_drift": self._provenance_drift(),
            "gate": self._gate_snapshot(),
            "gate_error": self.gate_error,
            "data_path": self.data_path,
            # 표시명(U6-D #978) — 풀 항목은 등록명, 파일은 확장자 없는 basename.
            "data_name": self.data_display_name(),
            "data_sheet": self.data_sheet,  # 데이터 항목 부제의 시트 표기(#33 확정 시트)
            # 참조 성분 한 벌(U6-B #976) — 우 열의 「현재 데이터」 행이 시트·헤더 행을
            # 다시 묻지 않고 재진술한다(U4 §2.4 정체성 축).
            "data_header_row": self.data_header_row,
            "data_kind": self.data_kind,
            # 지금 마운트가 겨눈 풀 슬롯(없으면 "") — 우 열의 `aria-pressed` 판정.
            "data_pool_key": self.data_pool_key,
            "record_count": len(self.records),
            # 전체 헤더(데이터 미리보기 컬럼·sample_rows 정렬의 짝, 불변).
            "source_fields": self.source_fields,
            # 데이터 열 select 의 항목 전수(U6-C #977) — 실 열 + 특수 항목 3개. 특수 항목은
            # 열 이름 공간에 얹지 않고 `kind` 로 갈린다(웹이 그 값으로 발행 액션을 가른다).
            "data_column_options": self._data_column_options(),
            # 2단계 데이터 미리보기(#16): source_fields 순서로 투영한 샘플 행 소량.
            # 빈 셀은 "" 로 보존해 렌더가 (빈 값)으로 시끄럽게 표기(ADR-B).
            "sample_rows": self._sample_rows(),
            "name": self.job_name,
            # 지금 이름이 도출값인가(U6-D #978) — 힌트가 서는 조건이자 재도출의 조건이다.
            # 웹이 「이름이 {템플릿} · {데이터} 와 같은가」로 되유추하면 사람이 우연히 같은
            # 이름을 지은 순간 힌트가 되살아난다(같은 상태를 두 곳이 판정).
            "job_name_is_derived": self._job_name_is_derived,
            "name_hint": NAME_DERIVED_HINT if self._job_name_is_derived else "",
            "pattern": self.pattern,
            # 저장 폴더(U6-D #978) — **읽기 전용 재진술**이다. 고르는 자리는 설정 모달 하나이고
            # (`docs/UI_CONTRACT.md` 「저장 폴더 — 전역 단일 값」) 이 존은 작업 화면이 그리는
            # 것과 **같은 함수**가 낸다. 편집기가 자기 세션 템플릿으로 부르는 이유는 기본값이
            # 「템플릿 옆 Results」라서다 — 아직 저장되지 않은 초안의 저장 폴더도 그 자리에서
            # 답할 수 있다. **TXT 는 ``None``**(리뷰 4): 파일을 만들지 않는 작업이라 폴더가
            # 축이 아니고, 빈 재진술을 세우면 만들지 않을 파일이 어디에 저장되는지를 말한다.
            "output_folder": self._output_folder_zone(),
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
            # (작성 출처 `provenance` 스냅샷 키는 U6-E(#979)에서 퇴역했다 — 고르기 존 아래의
            #  「작성 출처」 블록이 걷히며 소비자가 0 이 됐다. **생산은 그대로 산다**: 저장
            #  경로가 `_build_provenance` 로 mapping 에 찍고, 그 값은 durable 이라 편집 재저장의
            #  최초 작성시각 보존(`_loaded_provenance`)도 불변이다.)
            # 고르기 단계의 **연결 카드**(U6-B #976) — 좌·우에서 하나씩 고른 결과를 한 줄로
            # 재진술하고 전진 게이트의 사유를 함께 싣는다. 목록 자체는 여기 없다: 좌 열은
            # `tpl` 채널 스냅샷이, 우 열은 `pool` 채널 스냅샷이 정본이고 편집기가 그것을
            # 다시 성형하면 같은 목록을 두 컨트롤러가 그린다(구 `library` 존이 그랬다).
            "pairing": self._pairing_snapshot(),
            # F26 — 파일명 라이브 예시(표본 1행 고정). 저장 분류(2)에서만 계산.
            # 3단계의 파일명 라이브 예시 — **매체 인지**다(U6-D #978). TXT 작업은 파일을
            # 만들지 않으므로 그 단계에 서 있어도 보여줄 이름이 없다: 계산하면 화면이 만들지
            # 않을 파일의 이름을 예시로 말한다.
            "pattern_preview": (
                self._pattern_preview()
                if self.section == SECTION_FILENAME
                and template_media(self.template_path) != "txt"
                else ""
            ),
            "notice": (
                {"text": self.notice_text, "level": self.notice_level}
                if self.notice_text else None
            ),
        }
        if self.model is not None:
            schema_only = self.model.is_schema_only()
            record = self._current_record()
            # 「오늘 날짜」 미리보기의 기준 시각 — **스냅샷당 1회**(RC-02 확장).
            rows_now = self._clock()
            snap["rows"] = [
                self._row_snapshot(i, r, record, now=rows_now)
                for i, r in enumerate(self.model.rows)
            ]
            filled, empty, unmapped = self.model.preview_counts(record, now=rows_now)
            snap["counts"] = {"filled": filled, "empty": empty, "unmapped": unmapped}
            snap["preview_empties"] = self.model.preview_empties(record, now=rows_now)
            snap["preview_index"] = (self.preview_index % len(self.records)) + 1 if self.records else 0
            snap["preview_count"] = len(self.records)
            snap["is_complete"] = self.model.is_complete()
            snap["schema_only"] = schema_only
            snap["binding_head"] = self._binding_head()
        else:
            snap["rows"] = []
            snap["is_complete"] = False
            snap["binding_head"] = self._binding_head()
        return snap

    def _data_column_options(self) -> "list[dict]":
        """데이터 열 select 의 항목 전수 — 실 열 + 특수 항목 3개(U6-C #977).

        ``kind`` 가 곧 **발행할 액션**이다: ``column``→``set_source`` ·
        ``const``/``today``→``set_display`` · ``blank``→``set_blank`` · ``none``→결속 해제.
        특수 항목을 소스 값으로 실어 보내지 않는 이유는 리뷰 R5 그대로다 — 같은 이름의 실
        열이 있으면 그 열을 영영 못 겨눈다. 그래서 값의 이름 공간을 접두로 가른다.
        """
        options: "list[dict]" = [
            {"value": "", "label": NO_SOURCE_LABEL, "kind": "none", "field": ""},
        ]
        options.extend(
            {"value": f"col:{name}", "label": name, "kind": "column", "field": name}
            for name in self.source_fields
        )
        options.extend(
            {"value": f"sp:{kind}", "label": SPECIAL_SOURCE_LABEL[kind], "kind": kind,
             "field": ""}
            for kind in ("const", "today", "blank")
        )
        return options

    def _binding_head(self) -> dict:
        """2단계 머리 — pill 3개 + 일괄 승격 버튼의 **수치와 문안**(U6-C #977).

        수치는 전부 링1 질의이고 문안도 여기서 완성해 보낸다: 「제안 n건 모두 확인」의 n 은
        곧 이 동사가 실제로 확정할 행 수라 웹이 따로 세면 버튼이 약속과 다른 일을 한다.
        승격할 것이 없을 때의 문안(``promoted_label``)이 두 갈래인 이유는 0 의 뜻이 둘이기
        때문이다 — 다 확인한 0 과 애초에 제안이 없던 0 은 같은 문장으로 말할 수 없다.
        """
        model = self.model
        if model is None:
            return {
                "suggested": 0, "needs_confirm": 0, "const": 0,
                "promote_label": "", "promoted_label": "", "unused_columns": 0,
            }
        suggested = model.suggested_count()
        return {
            "suggested": suggested,
            "needs_confirm": model.needs_confirm_count(),
            "const": model.const_count(),
            "promote_label": f"제안 {suggested}건 모두 확인",
            "promoted_label": (
                "제안을 모두 확인했습니다" if model.confirmed_count()
                else "확인할 제안이 없습니다"
            ),
            "unused_columns": len(model.unused_source_fields()),
        }

    def _output_folder_zone(self) -> "dict[str, str] | None":
        """3단계의 저장 폴더 존 — TXT 면 ``None``(폴더가 축이 아니다 · 리뷰 4).

        값·출처·하향 사유는 작업 화면과 **같은 함수**가 낸다. 「기억한 지정」은 그 화면의
        메모리 값을 콜러블로 읽는다(리뷰 3 — 설정 파일 재판독 금지: 소유자가 둘이 되면
        쓰기가 실패한 순간 두 표면이 다른 폴더를 말한다).
        """
        if not self.template_path or template_media(self.template_path) == "txt":
            return None
        remembered = self._remembered_output_directory
        return output_folder_zone(
            template_path=self.template_path,
            remembered_directory=remembered() if remembered is not None else "",
        )

    def _pattern_preview(self) -> str:
        """F26 — 파일명 패턴의 라이브 예시(표본 고정 = 첫 레코드, seq=1 + 연번 두 자리).

        **실제 생성기와 같은 함수**(:func:`make_output_filename`)로 만들어 예시가 거짓말하지
        않는다(별도 구현이면 예시·산출물이 조용히 어긋난다 — 단일 출처). 값은 현 매핑의
        표본 첫 행 기준(데이터 없으면 필드 토큰 미치환 그대로 노출 = 정직). 표시 전용이라
        실패는 빈 문자열(패턴 검증은 저장 게이트 소관).

        **한 건이 아니라 연번을 보여준다**(U6-D #978 · 동결 시안 장면 3): 이 규칙이 만드는
        것은 파일 하나가 아니라 여러 건이고, 첫 이름만 보면 「번호가 어디에 붙는가」를
        모른 채 저장한다. 첫 이름은 실제 생성기가 만들고, 뒤 둘은 **seq 토큰 자체의 서식**이
        낸다(:func:`_sequence_example`) — 프런트가 번호를 조립하면 seq 토큰이 없는 패턴에서도
        「· 002 · 003」이 서서, 실제로는 이름 셋이 충돌하는 자리를 정상으로 그린다.
        """
        if not self.pattern:
            return ""
        data: "dict[str, object]" = {}
        # 값과 이름이 **한 시각**을 말하게 1회만 찍는다(RC-02) — 본문의 「오늘 날짜」와
        # 파일명 날짜 토큰이 예시 안에서 갈리면 예시가 거짓말한다.
        now = self._clock()
        if self.model is not None:
            # 토큰 재료도 링1 하나다(U6-F #980) — 「문서 작업」 상세의 계획 한 줄이 같은
            # 재료로 같은 이름을 말한다(두 곳이 각자 모으면 한쪽만 빈 값 갈래를 흘린다).
            data = self.model.name_token_values(
                self.records[0] if self.records else {}, now=now
            )
        try:
            first = make_output_filename(self.pattern, data, seq=1, now=now)
        except Exception:  # noqa: BLE001 — 표시 전용(저장 게이트가 검증 소관)
            return ""
        return _sequence_example(first, self.pattern)

    # (_default_dataset_snapshot(#53-A 기본 데이터 연결 상태 재진술)은 #347 에서 삭제 —
    #  작업↔데이터 결속이 폐기돼 재진술할 참조 자체가 없다. U2 §5.3 판정 D.)

    # (`_schema_summary`(나열식 필드 요약)는 U6-E(#979)에서 퇴역했다 — 그 문장의 승계처는
    #  항목 상세 시트의 필드 표 머리이고, 성형은 링1 `TemplateDetail.field_summary` 하나다.)

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
        # 데이터 표시명: 이번에 데이터를 골랐으면 **화면이 부르는 그 이름**(리뷰 7 — 등록명이
        # 있으면 등록명), 아니면(편집 저장) 복원 출처 보존. 여기서 stem 을 따로 지으면 같은
        # 세션이 화면과 출처 기록에서 데이터를 다른 이름으로 부른다.
        dataset = (
            self.data_display_name() if self.data_path
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

    def _session_detail(self) -> dict:
        """게이트 존 「자세히…」의 가부와 사유(U6-E 리뷰 5) — **판정은 여기 하나**다.

        시트는 `tpl` 채널이 아는 항목만 연다(그 왕복이 경로 관문을 지난다). 저장본이 든
        절대경로는 루트 재지정·폴더 이동 뒤에도 살아 있을 수 있으므로, 그 상태에서 문을
        열어 두면 누를 때마다 거절만 돌아온다 — 비활성 + 사유가 이 저장소의 처분이다.

        **memo 는 경로 하나**다: 관문 질의가 서식 폴더 스캔을 물 수 있어 스냅샷마다 지불할
        것이 아니고, 판정의 입력은 세션 템플릿 경로 하나다.
        """
        if not self.template_path:
            return {"available": False, "reason": ""}
        cached = self._session_detail_cache
        if cached is not None and cached[0] == self.template_path:
            return cached[1]
        gate = self._is_library_path
        if gate is None:
            value = {"available": False, "reason": SESSION_DETAIL_UNWIRED_TEXT}
        else:
            try:
                live = bool(gate(template_media(self.template_path), self.template_path))
            except Exception:  # noqa: BLE001 — 판정 불가 = 문을 열지 않는다(fail-closed)
                live = False
            value = (
                {"available": True, "reason": ""} if live
                else {"available": False, "reason": SESSION_DETAIL_OUTSIDE_TEXT}
            )
        self._session_detail_cache = (self.template_path, value)
        return value

    def _provenance_drift(self) -> str:
        """작성 당시와 지금의 템플릿 필드 구성이 갈렸으면 경고, 아니면 ``""``(#53-C 승계).

        **세션 판정이다**(U6-E 리뷰 6): 비교하는 것은 이 작업이 저장될 때 찍은 필드 지문
        (:meth:`_build_provenance` 의 ``template_fields``)과 **지금 연 파일**의 필드다. 풀
        항목의 사실이 아니므로 항목 상세 시트가 아니라 1단계 게이트 존에 선다 — 종전에는
        걷힌 「작성 출처」 블록이 이 경고를 이고 있어서 그 블록과 함께 사라졌다.

        지문은 저장 경로와 **같은 구분자**로 잇는다(`' · '`) — 여기서 다시 지으면 같은
        스키마가 두 문법으로 적혀 늘 다르다고 말한다.
        """
        recorded = self._loaded_provenance.get("template_fields", "")
        if not recorded or self.schema is None or not self.schema.fields:
            return ""
        if recorded == " · ".join(self.schema.field_names()):
            return ""
        return PROVENANCE_DRIFT_TEXT

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

    # ------------------------------------------------------ 세션 수명주기(자동 버리기)
    # (close_guard_reason 은 확인 모달 전면 제거와 함께 사망 — 편집기의 미저장 변경은
    # 묻지 않고 버리는 것이 계약이라, 창 닫기에서만 되살아나는 확인은 그 계약을 어긴다.)

    def has_unsaved_work(self) -> bool:
        """버려질 **미저장** 변경이 있는가 — 자동 버리기의 no-op 판정과 ``dirty`` 합성에 쓴다.

        **저장된 작업 편집은 세어서 답한다**(8R 근본 조치): 잃을 것은 section patch
        (:meth:`dirty_sections`) 와 section 밖 세션 상태(:meth:`dirty_extras`) 의 합집합이고,
        둘 다 저장본과의 비교로 **파생**된다. 종전엔 손으로 켜고 끄는 표지(``_session_clean``)
        가 이 답을 대신했는데, 변이 자리와 되돌리기 자리가 늘 때마다 한 곳이 빠졌다 — 빠짐은
        「저장됨」이라는 거짓말(미저장 입력을 저장됨으로 표시)이나 되돌린 뒤의 헛확인으로
        나타났고, 라운드마다 그 두 얼굴 중 하나가 다시 잡혔다. 파생은 빠질 자리가 없다:
        되돌리면 비교가 같아져 저절로 깨끗해지고, 손대면 저절로 더러워진다.

        초안(base 없음)은 저장본이 없으니 section patch 가 성립하지 않는다 — ``_reset()``
        직후엔 False, 클린 표지가 서 있으면 False, 그 외엔 **기준선 대비 이탈**(이름·데이터)
        이나 매핑 모델이 있으면 사용자가 손댄 세션이므로 True(템플릿만 갓 로드한 상태는
        아직 버릴 게 없어 False).

        **기준선은 저장본 갈래와 같은 것**이다(#945 F7): 초안의 이름 기준은 빈 값이고 데이터
        기준은 :attr:`_entry_data`(진입이 들고 온 참조)라, 「이 데이터로 새 작업」으로 열자마자
        아무것도 손대지 않은 세션이 미저장으로 서지 않는다 — 종전엔 ``data_path`` 를 날것으로
        세어, 사람이 고른 적 없는 인계 데이터 하나 때문에 첫 이탈부터 「버리고 계속」을 물었다
        (수리 진입에서 #878 이 이미 끊어 낸 것과 같은 결함의 초안 얼굴). 사람이 관문에서
        데이터를 갈아 끼우거나 이름을 넣으면 기준선을 벗어나 그 즉시 다시 True 다.
        """
        if self.session.base is not None:
            return bool(self.dirty_sections()) or bool(self.dirty_extras())
        if self._session_clean:
            return False
        return bool(self._extras_diff(None)) or self.model is not None

    def new_job_session(self, path: str) -> None:
        """새 작업 세션을 원자적으로 시작 — 이전 세션 전량 초기화 후 템플릿 로드(#25).

        템플릿→에디터 진입(템플릿 관리 '작업 만들기', 에디터 0단계 피커)의 단일 seam.
        ``load_template_path`` 만 부르면 이름·데이터·매핑·단계가 이전 세션 값으로 남아
        새 템플릿과 섞인 혼합 세션이 조용히 저장될 수 있다 — 여기서 ``_reset()`` 로
        먼저 끊는다.

        **무엇을 묻고 무엇을 안 묻는가**(U6-B #976 리뷰 2 — 종전 두 독스트링이 서로 다른
        말을 하던 자리): section patch 류의 미저장 편집은 **묻지 않고 버린다**(자동 버리기
        계약). 갈리는 것은 **확정하거나 직접 편집한 매핑** 하나다 — 그것은 데이터 교체와
        똑같이 표면이 :meth:`_do_mapping_reset_stakes` 로 수치를 받아 먼저 확인을 치른다.
        두 제스처(좌 열 클릭 · 끌어 놓기)가 같은 규칙을 지나야 하고, 데이터 쪽만 묻고
        템플릿 쪽은 안 묻는 상태는 같은 파괴에 두 규칙을 두는 것이다.

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
        # 기준선도 함께 건넌다(#945 F7): 앵커는 「진입이 들고 온 데이터」라는 사실 그 자체이므로
        # 템플릿을 고르는 정상 진행에서 그 사실만 잃으면, 살아남은 데이터가 그 순간 「사람이
        # 고른 것」으로 승격돼 손대지 않은 세션이 미저장이 된다(`load_job` 의 ``entry_data``
        # 인계와 같은 규율).
        return {
            "context": context,
            "data": self._data_stash(),
            "entry_data": dict(self._entry_data),
        }

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
        # 풀 슬롯 키도 한 벌이다 — 흘리면 살아남은 데이터가 우 열에서 「고른 적 없음」으로
        # 보인다. 앵커의 계약은 「데이터를 `_data_stash` 한 벌 그대로 건넨다」다.
        self.data_pool_key = data.get("data_pool_key", "")
        self.source_fields = list(data["source_fields"])
        self.records = data["records"]
        self._entry_data = dict(anchor["entry_data"])
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
        # 인계 데이터는 이 세션의 **기준선**이다(#945 F7 — `load_job` 과 같은 자리·같은 값):
        # 사람이 고른 적이 없으므로 「달라진 것」으로 세면 열자마자 미저장이 된다. 적재가
        # 실패하면 여기 닿지 않고 사유가 그대로 올라간다(빈 기준선을 지어내지 않는다).
        self._entry_data = {"data_path": self.data_path, "data_sheet": self.data_sheet}

    # ---------------------------------- 템플릿 라이브러리 피커(R-info 2부 접합 최소분)
    def _do_use_library_template(self, p: dict) -> None:
        """라이브러리 목록에서 고른 템플릿으로 새 작업 세션(신규 1단계 정본 경로).

        경로 화이트리스트는 :meth:`assert_library_path` 공용 seam(리뷰 F4 — 크로스스크린
        진입과 단일 정의).

        **이미 그 템플릿이면 아무 일도 하지 않는다**(U6-B #976 리뷰 1). 종전 표면에서는
        현재 항목이 클릭 핸들러 없는 span 이라 이 호출이 구조적으로 불가능했는데, 고르기
        화면은 현재 항목도 누를 수 있고 끌어 놓을 수도 있다 — 통과시키면
        :meth:`new_job_session` 이 이름·매핑·단계를 통째로 끊는다(누른 사람은 「이미 고른
        것을 다시 골랐을」 뿐이다). 프런트도 같은 자리를 막지만 판정은 **여기도** 선다:
        표면만 막으면 프로브·다른 호출자가 그대로 뚫는다.

        확인은 여기서 묻지 않는다 — 확정 매핑이 걸린 **교체**의 확인 왕복은 호출측(웹)이
        :meth:`_do_mapping_reset_stakes` 로 수치를 받아 먼저 치른다(데이터 교체와 같은
        규율). 그 밖의 미저장 편집은 :meth:`new_job_session` 이 묻지 않고 버린다.
        """
        path = str(p["path"])
        self.assert_library_path(path)
        if self.template_path and norm_library_path(path) == norm_library_path(
            self.template_path
        ):
            return  # 같은 템플릿 재선택 — 세션을 끊을 이유가 없다(리뷰 1)
        self.new_job_session(path)
        # T1 템플릿 고르기(#894) — 세션에 템플릿이 실제로 앉은 뒤다. 자산 정체성(예제인가)은
        # 따지지 않는다: 루프를 돈 것이 판정이지 예제 강제가 아니다(§3.1-4 비강제).
        self._tutorial(Milestone.PICK_TEMPLATE)

    def adopt_imported_template(self, dest: str) -> str:
        """가져온 사본의 편집기 채택 판정(F8 — §10.17.2 판정 C, 가져오기 통일).

        **복사 권위는 :meth:`TemplateController.import_into_library` 하나다**(잠금·충돌
        접미·무잔재) — 여기는 그 사본으로 「세션을 시작할 수 있는가」만 판정한다.
        시작 가능(hwpx 누름틀 有 / txt UTF-8 판독 가능) = 즉시 새 세션(F7 거동 보존).
        불가(RAW·손상) = **세션 없이 목록 합류** + notice 가 수선 경로를 지목한다.

        **사유 문안은 살아 있는 동사만 지목한다**(U6-E #979): 종전 문안은 「행 ⋮ 에서
        삭제」와 「'누름틀로 변환'」을 가리켰는데, 앞의 것은 U6-A(#975)에서 퇴역했고
        (앱은 사용자 서식 폴더에 쓰지 않는다 — 「폴더에서 보기」가 그 자리다) 뒤의 것은
        S8-03 에서 「누름틀·구간 변환」으로 개명됐다. 라벨은 **링1 상수에서 가져온다** —
        여기서 리터럴로 다시 쓰면 링1 이 라벨을 고치는 날 이 문장만 옛말을 계속 한다.
        """
        path = Path(dest)
        # (채택 전 목록 재스캔은 U6-E 에서 걷혔다 — 복사 권위(`import_into_library`)가 이미
        #  자기 VM 을 refresh 했고, 이 화면은 더 이상 자기 목록을 들지 않는다. 소속 판정이
        #  필요한 자리는 `assert_library_path` 하나이고 그것은 tpl 관문을 지난다.)
        if path.suffix.lower() == ".hwpx":
            try:
                schema = extract_schema(read_hwpx_package(path))
            except Exception:
                self._set_notice(
                    f"'{path.name}' 을 가져왔지만 읽을 수 없습니다. "
                    "목록의 행 ⋮ → '자세히…'에서 사유를 보거나 "
                    "'폴더에서 보기'로 파일을 확인하세요.",
                    "warn",
                )
                self._push()
                return path.name
            if not schema.fields:
                self._set_notice(
                    f"'{path.name}' 은 누름틀이 없는 원본(RAW)입니다. "
                    f"목록의 행 ⋮ → '{RAW_CONVERT_LABEL}'을 거친 뒤 시작하세요.",
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
                    "목록의 행 ⋮ → '자세히…'에서 사유를 보거나 "
                    "'폴더에서 보기'로 파일을 확인하세요.",
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
        self._session_detail_cache = None  # 경로가 바뀌면 시트 가부도 다시 묻는다(리뷰 5)
        self.template_path = path
        # 이름 기본값 재도출(U6-D #978) — 표지가 참일 때만 실제로 바뀐다. 스키마·게이트보다
        # **앞**인 이유는 이름이 경로 하나에서 나오기 때문이다: 아래 갈래는 RAW·판독 실패로
        # 여러 자리에서 되돌아가고, 그 뒤에 두면 갈래마다 같은 줄을 다시 적게 된다.
        self._rederive_job_name()
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

        ``deleted`` 는 ``template_path`` 를 **지우지 않는다**: 사용자가 탐색기에서 파일을
        되돌려 놓으면 같은 경로가 다시 살아난다. 경로를 비우면 그 복귀가 닿을 자리가 사라져
        세션을 처음부터 다시 세워야 한다. 저장은 그동안 :meth:`_missing_template_block` 이
        심층 방어로 막는다. (앱 안의 복원 동사는 U6-A 에서 퇴역했다 — ``restored`` 종류도
        생산자 0 으로 함께 걷혔고, 남은 ``deleted`` 생산자는 동결 온보딩의 예제 제거다.)
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
        self._adopt_datasource(
            source, source.records(), path=path, sheet=sheet or "",
            header_row=header_row,
            # 이 관문은 **파일 소스**의 것이다 — 종류는 늘 엑셀/CSV 다.
            kind="", emit_push=emit_push,
        )

    def _adopt_pclm(self, db: str, view: str, *, emit_push: bool = True) -> None:
        """계약 목록(pclm) 뷰를 이 세션의 데이터로 — :meth:`load_data_path` 의 자매(#937).

        참조 형상은 :func:`~hwpxfiller.data.factory.pclm_reference` 하나가 짓는다(「문서
        만들기」의 마운트와 같은 한 벌) — 두 화면이 각자 덕타입을 조립하면 opts 키가
        갈리는 날 한쪽만 조용히 기본 db 를 읽는다. 복원은 풀 항목 복원과 **같은 함수**를
        지난다: 참조로부터 소스를 세우는 규칙이 이 저장소에 두 벌이 되지 않게.

        읽기 실패(db 부재·미지 뷰)는 :meth:`load_data_path` 와 같은 규약으로 raise 한다 —
        호출자(공유 관문·인계 복원)가 자기 채널의 문안으로 재진술한다.
        """
        source = source_from_pool_item(pclm_reference(db, view))
        self._adopt_datasource(
            source, source.records(), path=db, sheet=view,
            # 계약면에는 헤더 행 축이 없다 — 0 이 곧 「해당 없음」이다.
            header_row=0, kind="pclm", emit_push=emit_push,
        )

    def _adopt_datasource(
        self, source, records: list, *, path: str, sheet: str, header_row: int,
        kind: str, emit_push: bool = True,
    ) -> None:
        """읽어 온 소스·레코드를 이 세션의 데이터로 **채택**한다 — 종류 무관 공용 몸통.

        종류별로 다른 것은 **소스를 어떻게 세우는가** 하나이고(파일 확장자 · 계약 목록
        참조), 그 뒤의 전이 — 0행 거절·클린 표지 해제·참조 성분 한 벌·어휘 초기화·매핑
        재조립 — 는 전부 같다. 갈래마다 이 몸통을 복붙하면 한쪽만 미사용 칩을 안 비우거나
        한쪽만 모델을 안 다시 세우는 표류가 난다(#937).

        ``path``·``sheet``·``header_row``·``kind`` 는 **한 벌로** 세운다: 이전 세션의 성분이
        새 결속에 남지 않게 같은 자리에서 넷 다 대입한다.
        """
        if not records:
            raise ValueError(NO_ROWS_TEXT)
        self._session_clean = False  # 브리지 직행 변이(디스패치 밖) — 클린 표지 해제
        self.data_path = path
        self.data_sheet = sheet  # 자동등록 참조에 확정 시트 동봉(#26 — 모호 참조 방지)
        self.data_header_row = header_row
        self.data_kind = kind
        # 새 마운트 = 풀 겨눔 해제(§5.3 슬롯 정체 · `screen_job` 과 같은 규율). 풀 항목
        # 경로는 이 대입 **뒤에** 자기 키·등록명을 다시 세운다(`_do_use_pool_data`).
        self.data_pool_key = ""
        self._data_name_cache = None
        self.source_fields = source.fields()
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
                # 같은 파일·시트 재겨눔(키 불변 = 재초안 없음) — 어휘 재동기화로 시스템 행
                # 재제안을 되살린다(PR-3 리뷰 F3). 열 선별이 퇴역한 뒤로 강등 집합은 늘 비지만
                # 재제안 쪽은 여전히 일한다: 앞 세션에서 후보를 못 찾아 비어 있던 시스템 행이
                # 같은 파일을 다시 겨누며 제안을 되받는 자리다.
                self.model.apply_active_sources(
                    self.source_fields, vocabulary=self.source_fields
                )
        # 이름 기본값 재도출(U6-D #978) — 마운트의 공용 몸통이라 갈래(파일·계약 목록·인계
        # 복원)가 전부 여기를 지난다. 풀 항목은 **등록명**이 표시명이라 그 키를 세우는
        # `_do_use_pool_data` 가 마운트 뒤에 한 번 더 도출한다(이 시점엔 아직 basename 이다).
        self._rederive_job_name()
        if emit_push:
            self._push()

    def _load_source_ref(self, source_ref: dict, *, emit_push: bool = True) -> None:
        """참조 한 벌(``{path, sheet, header_row, kind}``)로 데이터를 **다시 읽는다** — 인계의 공용 자리.

        「이 데이터로 새 작업」(:meth:`new_draft_with_data`)과 「수정…」(수리 진입, #878)이 같은
        성분을 같은 규칙으로 푼다. 두 자리가 각자 풀면 한쪽이 ``header_row`` 를 흘려도 아무도
        모른다 — 그 어긋남은 화면 어디에도 표시가 없다(#349 리뷰 P1 이 지목한 자리).
        참조를 낸 곳은 「문서 만들기」의 단일 판정
        (:meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin.new_work_handoff`)이다.

        ``kind`` 가 **해석기를 가른다**(#937): ``""`` 는 파일(엑셀/CSV), ``"pclm"`` 은 계약
        목록(db+뷰)이다. 그 분기 자체는 데이터층 하나가 진다
        (:func:`~hwpxfiller.data.factory.source_for_binding` — U6-F #980 승격): 「문서 작업」
        상세도 같은 참조로 첫 행을 읽게 되면서 소비자가 둘이 됐고, 입구마다 분기를 적으면
        한쪽만 db 경로를 엑셀로 오파싱한다. 이름 없는 종류는 그 함수가 시끄럽게 거절한다.
        여기 남는 것은 **채택**(세션 성분 한 벌 대입)이고 그것은 종류와 무관한 공용 몸통이다.
        """
        source = source_for_binding(source_ref)
        header = source_ref.get("header_row")
        kind = str(source_ref.get("kind") or "")
        self._adopt_datasource(
            source, source.records(),
            path=str(source_ref.get("path") or ""),
            sheet=str(source_ref.get("sheet") or ""),
            # 계약면에는 헤더 행 축이 없다(0 = 해당 없음).
            header_row=(
                header
                if not kind and isinstance(header, int) and not isinstance(header, bool)
                else 0
            ),
            kind=kind, emit_push=emit_push,
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
        # 저장본의 이름은 도출값이 아니다(U6-D #978) — 사람이 한 번 지어 저장한 것이라
        # 이 세션의 어떤 고르기 변경도 그것을 덮지 않는다.
        self._job_name_is_derived = False
        self.pattern = job.filename_pattern
        self._editing_origin = job.name
        self._preserved_meta = _preserved_meta(job)
        # 로드 시점 내용 지문 — 자기-갱신 저장 시 편집 중 외부 변경(같은 이름 작업 교체)을
        # 무확인으로 덮지 않기 위한 대조 기준(_do_save).
        self._editing_fingerprint = self.registry.content_fingerprint(job)
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
            "data_pool_key": self.data_pool_key,
            "source_fields": list(self.source_fields),
            "records": self.records,
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
        self.data_pool_key = stash.get("data_pool_key", "")
        self.source_fields = stash["source_fields"]
        self.records = stash["records"]
        self._ensure_model()

    # 세션 내용을 바꾸지 않는 액션 — 클린 표지를 끄지 않는다(보기 이동·미리보기·질의).
    # (`toggle_library_group` 은 U4 §2-30 에서, `pool_options` 는 U6-B(#976)에서 액션
    #  자체가 퇴역했다 — 목록 조회가 사라지고 우 열이 `pool` 채널을 직접 구독한다.)
    _NONMUTATING_ACTIONS = frozenset(
        {"goto_section", "step_preview", "mapping_reset_stakes"}
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
        # (`confirm_suggested`·`set_blank`·행별 `set_confirmed`·`restore_confirmed`)로 도달하므로
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
        복원돼 '새'가 사실상 '이전 작성 계속'이었다. 앞선 세션에 남은 미저장 변경은
        **묻지 않고 버린다** — ``new_job_session``(템플릿 진입 seam)과 같은 계약이다.
        초기 상태 notice 는 두지 않는다(정상은 조용히).
        """
        self._reset()

    def _do_discard_session(self, p: dict) -> None:
        """신규 마법사 취소 — 확인을 마친 호출측이 휘발 초안을 실제로 폐기한다(#218 G5)."""
        if self._editing_origin:
            raise ValueError("저장된 작업 편집은 신규 마법사 취소로 닫을 수 없습니다.")
        self._reset()

    # ---- 탭 이동(§5.2 거래 규율)
    #: 탭 라벨 — 거절 문안이 내부 키(`binding`)가 아니라 사람의 말로 자리를 지목하게 한다.
    #: 단계 이름 — **사용자에게 보이는 문안**이라 표면(`editor.ts` 의 `SECTION_TITLES`)과
    #: 글자가 같아야 한다. 되돌린 자리를 지목하는 notice 가 이 표를 쓰므로, 갈리면 화면이
    #: 「연결 확인」이라 부르는 탭을 알림이 다른 이름으로 지목한다(U6-B #976 라벨 개정).
    SECTION_LABELS = {
        SECTION_TEMPLATE: "고르기",
        SECTION_BINDING: "연결 확인",
        # id 는 계약이라 그대로이고 라벨만 갈렸다(U6-D #978): 이 단계는 이제 이름과 파일
        # 이름을 함께 묻는다. 두 매체가 같은 라벨을 쓰고, 갈리는 것은 그 안의 한 행이다.
        SECTION_FILENAME: "이름·저장",
    }

    def _do_goto_section(self, p: dict) -> None:
        """탭 이동 — 신규(초안)는 전진 게이트, 편집은 자유 이동. **막는 patch 는 자동으로 버린다**.

        §13-16(한 편집 진입은 한 section patch)은 전이 시점의 규율이다: 다른 탭의 규칙을
        손대려면 지금 patch 를 처분해야 한다. 종전엔 그 처분을 3택 모달로 물었지만, 편집기
        한 탭에서 하는 작업량은 확인을 요구할 만큼 크지 않다 — 확인은 마찰만 남기고 왕복·
        분기·재발신이라는 내부 복잡도를 벌었다. 그래서 이동은 막히지 않고, 막는 자리를
        :meth:`_do_discard_patch` 로 **그 탭만** 되돌린 뒤 지나간다(이름처럼 어느 section 에도
        속하지 않는 편집은 종전 「버리고 이동」과 똑같이 살아남는다). 버렸다는 사실은 그
        discard 가 세우는 notice 로 재진술된다 — 확인은 걷어도 알림은 남는 쪽이다.

        초안은 이 거래 밖이다(§10.13 판정 P): 아직 작업이 아니라 세션 전체가 하나의 초안이라
        「직전 판본과의 차이」가 성립하지 않는다. 대신 초안에는 전진 게이트가 산다(판정 M).
        """
        target = str(p["section"])
        sections = self.sections()
        if target not in sections:
            raise ValueError(f"이 작업에는 '{target}' 탭이 없습니다.")
        # ``blocking_section`` 은 막는 자리를 한 번에 하나만 지목하므로 소진될 때까지 돈다.
        # 되돌렸는데 같은 자리가 다시 막으면 되돌리기가 성립하지 않은 것이다 — 그때는 조용히
        # 지나가지도, 영원히 돌지도 않고 **시끄럽게 거절**한다(통과시키면 이동한 화면이 버렸다고
        # 말한 것을 그대로 들고 서 있게 된다).
        discarded: "set[str]" = set()
        while True:
            blocking = self.session.blocking_section(
                self._draft_job(), target, pending_binding=self._pending_binding()
            )
            if not blocking:
                break
            if blocking in discarded:
                raise ValueError(
                    f"「{self.SECTION_LABELS.get(blocking, blocking)}」 에서 바꾼 것을 "
                    "되돌리지 못해 이동할 수 없습니다."
                )
            discarded.add(blocking)
            self._do_discard_patch({"section": blocking})
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

    def _do_discard_patch(self, p: dict) -> None:
        """「변경 버리기」 — 진입 시점 스냅샷(baseSnapshot)으로 규칙만 되돌린다(§5.2).

        디스크가 아니라 스냅샷으로 되돌리는 이유는 :meth:`_restore_from` 의 docstring 에 있다.
        초안은 되돌릴 base 가 없으므로 거절한다 — 초안 전체를 버리는 것은 세션 폐기
        (``discard_session``)라는 다른 사건이고, 두 사건을 한 버튼이 겸하면 "변경만 버리려던"
        사람이 초안째 잃는다.

        **범위는 알린 문안과 같아야 한다**(8R 근본 조치 — 이 함수의 두 갈래가 각각 한 번씩
        어긴 자리다). 되돌리는 범위가 문안보다 넓으면 말하지 않은 것까지 파기한 것이고, 좁으면
        버렸다고 말한 것이 남아 다음 전이에서 또 되돌아온다. 그래서 두 갈래를 대칭으로 세운다:
        ``section`` 있음 = 그 탭만(extras 는 **보존**), 없음 = 세션 전체(extras 도 **함께**).
        확인이 사라진 뒤로 이 문안은 승인 요청이 아니라 **사후 재진술**이지만, 범위가 같아야
        한다는 규율은 그대로다 — 알림이 실제와 다르면 그것이 곧 조용한 파기다.
        """
        if self.session.is_draft or self.session.base is None:
            raise ValueError("아직 저장하지 않은 새 작업이라 되돌릴 이전 상태가 없습니다.")
        base = self.session.base
        section = str(p.get("section") or "")
        if not section:  # footer 「변경 버리기」·이탈의 자동 버리기 = 세션 전체를 되돌린다
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
            # **되돌릴 것이 없으면 아무 일도 일어나지 않는다.** 이탈이 확인 없이 이 자리를
            # 무조건 부르게 되면서, 손대지 않은 세션의 이탈마다 디스크 재적재와 「되돌렸습니다」
            # 라는 거짓 통지가 서게 됐다. 판정은 여기 한 곳에서 한다 — 웹이 dirty 를 다시
            # 세어 부를지 말지 고르면 같은 상태를 두 곳이 판정하게 된다.
            #
            # 술어가 둘인 것은 두 번째 판정이 아니라 **이 갈래가 실제로 되돌리는 것의 합**
            # 이다: `has_unsaved_work` 의 extras 축은 이름·경로·시트까지만 보고(헤더 행·종류는
            # 안 본다), 결속 비교는 네 성분을 전부 본다. 좁은 쪽만 물으면 헤더 행만 갈린
            # 세션의 되돌리기가 조용히 무동작이 된다.
            if not data_changed and not self.has_unsaved_work():
                return
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
        # 탭 이동의 자동 버리기는 **그 자리만** 되돌린다(2R P2): 되돌렸다고 알리는 것은 「필드
        # 연결·표시에서 바꾼 것」인데 세션 전체를 되돌리면 머리에서 고친 이름처럼 **어느
        # section 에도 속하지 않는 편집**(판정 L 계열)까지 함께 사라진다. 탭 하나를 옮겼을 뿐인
        # 사람에게 알린 적 없는 손실이 생기는 자리다.
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
        vocabulary = list(self.source_fields) or profile_source_vocabulary(base.mapping)
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
    # (:func:`~hwpxfiller.webapp.screens.pool_reference_quad`).

    def _mount_pool_item(self, item) -> list:
        """풀 항목을 이 세션의 데이터로 마운트하고 레코드를 돌려준다(공유 관문의 loader).

        참조 포획은 :func:`~hwpxfiller.webapp.screens.pool_reference_quad` 하나가 진다 —
        경로·시트·헤더 행·종류가 한 벌로 오지 않으면 마법사가 사람이 고른 것과 **다른
        헤더**로 서거나 db 를 엑셀로 읽는다(#349 리뷰 P1 · #937). 파일 참조가 아닌 항목은
        여기서 시끄럽게 거절한다(목록이 이미 비활성으로 그렸어도 그 판정을 표면에만 두지
        않는다) — 술어는 ``path`` 이고 계약 목록은 그 자리에 db 를 채운다.
        """
        path, sheet, header_row, kind = pool_reference_quad(item)
        if not path:
            raise ValueError(f"'{item.name}' 은(는) 파일 참조가 아니라 연결할 수 없습니다.")
        if kind == "pclm":
            self._adopt_pclm(path, sheet, emit_push=False)
        else:
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
        key = str(p["key"])
        res = load_pool_into(self._pool_registry, key, self._mount_pool_item)
        if not res["ok"]:
            return {"ok": False, "error": res["error"]}
        # 겨눈 슬롯을 기억한다 — 마운트 몸통(`_adopt_datasource`)이 방금 비운 자리다.
        self.data_pool_key = key
        # 표시명이 방금 등록명으로 바뀌었으므로(마운트 몸통은 basename 만 알았다) 이름 도출도
        # 다시 돈다. 이름 자체는 풀 조회가 답한다 — 세션에 복사해 두지 않는다(리뷰 2).
        self._data_name_cache = None
        self._rederive_job_name()
        return {"ok": True, "label": res["item"].name}

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

        키는 **전체** ``source_fields`` 다. 종전에 「미사용 집합은 키에 담지 않는다」는
        단서가 붙어 있었는데 그 축(#49 열 선별)이 U6-C 에서 퇴역해 담을 것 자체가 없다 —
        어휘 변화는 이제 ``source_fields`` 하나로만 온다.

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
        self.model = MappingModel.from_suggestions(self.schema, self.source_fields)
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
            return {"human": 0, "resuggest_manual": 0, "confirmed": 0}
        rows = [r for r in self.model.human_owned_rows() if r.confirmed or r.has_content()]
        # 파괴 확인의 수치는 **행동마다 다르다** — 두 관문이 강등하는 집합이 다르기 때문이다.
        # 한 수치를 둘이 나눠 쓰면 좁은 쪽 술어가 넓은 쪽 파괴를 가려 준다(리뷰 R1 P1: 소스
        # 없는 수동 const 행이 일괄 재제안에서 확인 없이 지워졌다). 그래서 이름을 소비자에게
        # 붙인다 — 새 관문이 생기면 자기 수치를 여기 더한다.
        #
        # resuggest_all: 미확정 행 **전부**를 reset_to_system 한다 — 소스뿐 아니라 상수·유형·
        # 표시형까지 지우므로 소스 없는 수동 행도 잃을 것이 있다. 술어는 실제 루프
        # (`_resuggest_targets`)에서 되읽어 둘이 갈라질 자리를 없앤다.
        resuggest_manual = [i for i in self._resuggest_targets() if self.model.rows[i].touched]
        # confirmed 는 템플릿·데이터 **교체**의 파괴 규모다(U6-B #976) — 고르기 단계가
        # 확인 왕복을 세울지 그 수치로 판정한다.
        return {
            "human": len(rows),
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
        self.model.resuggest_row(index, self.source_fields)

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
        active = self.source_fields
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

    def _do_set_display(self, p: dict) -> None:
        """(유형, 표시형) 원자 갱신 — 표시형 select 와 데이터 열의 특수 항목이 함께 쓴다.

        구 `set_type`·`set_fmt` 두 액션의 후계다(리뷰 1): 유형이 바뀌면 표시형 키가 무효라
        둘은 애초에 한 전이였고, 나눠 두면 그 사이에 「유형만 바뀐」 상태가 실재해 사람이 고른
        표시형이 왕복 하나에 조용히 사라진다.
        """
        self.model.set_display(int(p["index"]), str(p["type"]), str(p.get("fmt") or ""))

    def _do_set_const(self, p: dict) -> None:
        self.model.set_const(int(p["index"]), p["const"])

    def _do_set_confirmed(self, p: dict) -> None:
        self.model.set_confirmed(int(p["index"]), bool(p["confirmed"]))

    def _do_confirm_suggested(self, p: dict) -> dict:
        """자동 제안 행 **일괄 승격**(U6-C #977) — 사람이 손댄 행·열 필요 행은 안 건드린다.

        구 `confirm_all`(내용 있는 전 행) + `confirm_blanks`(이름 재진술 모달) 두 발의
        후계다. 승격 뒤에도 남은 행이 있으면 저장 게이트가 그대로 막고, 그 사실은 머리
        pill 「확인 필요 n」이 말한다 — 부분 동작을 조용히 하지 않는다.
        """
        return {"promoted": self.model.confirm_suggested()}

    def _do_set_blank(self, p: dict) -> None:
        """이 행은 채우지 않는다 — 행별 비움 선언(U6-C #977)."""
        index = int(p["index"])
        already = self.model.rows[index].is_empty_confirmed()
        self.model.set_blank(index)
        # T14 비움 확정(#894) — **상태가 실제로 옮겨갔을 때만**이다: 이미 비움 확정인 행을
        # 다시 고른 무변이 호출에서 체크가 서면 지나지 않은 게이트를 지났다고 말하게 된다.
        if not already:
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
        """작업 이름 커밋 — **여기서 도출이 끝난다**(U6-D #978).

        표지를 끄는 자리를 이 한 곳으로 두는 이유: 사람이 지은 이름을 다음 데이터 마운트가
        덮어쓰면 그것은 조용한 소실이다. 되돌려 쳐서 도출값과 같아져도 표지는 켜지지 않는다
        — 그 순간 다시 켜면 이름을 「고쳤다가 되돌린」 사람의 다음 고르기가 이름을 또 바꾼다.
        """
        self.job_name = p["name"]
        self._job_name_is_derived = False

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
        if self.registry.content_fingerprint(current) != self._editing_fingerprint:
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
