"""작업 공간 하나의 제품 컨트롤러 그래프 조립 — 사용자 환경과 튜토리얼 연습 환경이 공유(#1126).

종전에는 :class:`~hwpxfiller.webapp.app.WebFrontend` 생성자가 화면 컨트롤러 전부를 직접
세웠다. 연습 환경은 **같은 조립을 그 과정의 홈에서 한 번 더** 하는 것이라 조립을 이 모듈로
분리했다: 저장소 기본 위치는 호출 시점의 활성 작업 공간에서 풀리고, 전환은
:class:`~hwpxfiller.webapp.workspace_switch.WorkspaceSwitch` 한 곳에서만 일어난다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..data.factory import source_for_path, source_from_pool_item
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.seal_execution_plan_service import SealExecutionPlanService
from ..external.template_change import TemplateChangeCoordinator
from ..external.template_files import TemplateFileStore
from ..external.template_root import TemplateRoot
from ..external.text_registry import TextTemplateRegistry
from ..host.locations import default_dataset_pool_dir, default_jobs_dir, default_template_authority_dir
from .authoring_proposal import PoolProposalData, pool_source_of
from .onboarding import OnboardingController
from .screen_authoring import AuthoringController
from .screen_editor import EditorController
from .screen_job import JobController
from .screen_library import LibraryController
from .screen_pool import PoolController
from .screen_template import TemplateController
from .screen_workbench import TargetFontSetting, WorkbenchController
from .slot_configuration_product import SlotConfigurationProduct, SlotConfigurationProductError
from .template_groups import TemplateGroupModel
from .txt_materialization import (
    TxtMaterializationRefused,
    TxtMaterializationService,
    materialized_text,
)
from .workbench_observation_product import WorkbenchObservationProduct
from .workspace_switch import WorkspaceGraph

__all__ = ["build_graph"]


def _content_selection_reader(
    product: SlotConfigurationProduct, registry: JobRegistry
) -> "Callable[[str], dict[str, frozenset[str]]]":
    """Slot Configuration Product → 작업대의 「포함할 내용」 조회 포트(S10-03 #860).

    작업대가 Product 를 직접 들지 않게 하는 번역 한 겹이다(`workbench_open` 이 컨트롤러가
    아니라 handoff callable 인 것과 같은 규율). 넘기는 것은 **항목 id → 고른 선택 id 들**
    뿐이고, 그 값은 :meth:`~hwpxfiller.webapp.slot_configuration_product.
    SlotConfigurationProduct.current_slot_configuration_view` 의 read-only projection 에서
    나온다 — durable S4 를 mutate 하지 않는다(#744).

    **effective 를 읽는다**(declared 아님): 사용자가 골랐어도 구조에서 사라진 선택은 지금 그릴
    수 있는 내용이 아니다. 그 사연은 「문서 만들기」의 retained/blocking 축이 이미 말한다.

    실패는 삼키지 않고 ``ValueError`` 로 올린다 — 작업대가 그것을 사유로 바꿔 재진술한다.
    context error(템플릿 확인 전·구조 불일치)도 같은 실패다: 그때 projection 은 없으므로
    「고른 것이 없다」로 접으면 전 선택지가 사라진 카드를 조용히 그리게 된다.

    **durable id 미발급 Work 는 Product 를 부르지 않는다**(스냅샷 존과 같은 규율): Product
    route 는 read 중 Work 권위 id 를 lazy 발급하므로(write-on-read), 확인 전 Work 를 그냥
    넘기면 작업대를 여는 것만으로 durable 표식이 생긴다. 결과는 어차피 같은 거절이므로,
    부작용 없는 쪽으로 먼저 닫는다.
    """

    def read(work_ref: str) -> "dict[str, frozenset[str]]":
        if not registry.load(work_ref).authority_id:
            raise ValueError("포함할 내용을 불러오지 못했습니다(TEMPLATE_INITIALIZATION_REQUIRED)")
        try:
            response = product.current_slot_configuration_view(work_ref)
        except SlotConfigurationProductError as exc:
            raise ValueError(f"포함할 내용을 불러오지 못했습니다({exc.code})") from exc
        projection = response.current_view.projection
        if projection is None:
            raise ValueError(
                "포함할 내용을 불러오지 못했습니다"
                f"({response.current_view.context_error or 'NO_PROJECTION'})"
            )
        return {
            slot.slot_id: frozenset(slot.effective_option_ids) for slot in projection.slots
        }

    return read


def _txt_materialization_port(
    registry: JobRegistry, seal_execution: SealExecutionPlanService
) -> "Callable[[str, dict, str, datetime], tuple[str | None, str]]":
    """TXT 물질화 서비스 → 작업대의 복사 포트(S10-04 #861).

    `_content_selection_reader` 와 같은 규율의 번역 한 겹이다: 작업대는 봉인·VDR·start gate 의
    타입을 모른 채 **(검증된 텍스트, 사유)** 두 값만 받는다(정확히 한쪽만 산다). 서비스는
    :class:`SealExecutionPlanService` 를 「문서 만들기」와 **공유**한다 — 봉인 권위가 표면마다
    갈리면 같은 Work 가 두 basis 로 보인다.
    """
    service = TxtMaterializationService(registry, seal_execution, clock=datetime.now)

    def materialize(
        work_ref: str, record: dict, request_id: str, now: datetime
    ) -> "tuple[str | None, str]":
        # ``now`` 는 작업대가 카드 렌더에 쓴 그 시각이다 — 「오늘 날짜」가 카드와 같은 글자(RC-02).
        outcome = service.materialize_record(
            work_ref, record, request_id=request_id, runtime_now=now
        )
        if isinstance(outcome, TxtMaterializationRefused):
            return None, outcome.detail
        return materialized_text(outcome), ""

    return materialize


def build_graph(
    home: "Path | None", push, token: object, *, template_root: TemplateRoot,
    migration_notice: str, tutorial_ctrl: OnboardingController,
    generation_lock: threading.Lock, hwpx_engine,
) -> WorkspaceGraph:
    """한 홈에 결속된 제품 컨트롤러 그래프(#1126) — 사용자 환경과 연습 환경이 같은 조립을 쓴다.

    저장소 위치는 호출 시점의 활성 작업 공간(:func:`~hwpxfiller.host.locations.workspace_home`)
    에서 풀린다. 그래서 이 함수는 :class:`WorkspaceSwitch` 가 그 홈을 활성으로 세운 뒤에만 부른다.
    """
    registry = TextTemplateRegistry(template_root.path)
    job_registry = JobRegistry(
        default_jobs_dir(), template_root=template_root.path
    )
    # 데이터셋 풀(#26) — 단일 인스턴스를 화면들이 공유: 에디터 자동등록(#3)·실행 겨눔(#6)·
    # 관리 화면(#4)의 변경이 서로 즉시 보인다(레지스트리는 무상태 디렉터리 어댑터).
    pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
    # txt 템플릿 그룹 모델 — 관리 화면과 편집기 TXT 밴드가 공유하는 단일 실체(#135).
    txt_groups = TemplateGroupModel("txt")
    # 대상 글꼴 선언(결정 17)은 **앱 전역 영속** — 단일 실체 주입 규율은 소비자가
    # 작업대 하나가 된 지금도 유지한다(사본 캐시 = 선언≠실제 결함류, 코덱스 P2).
    target_font = TargetFontSetting()
    # S4 Working Slot Configuration(SX-02 #679·#725) — TemplateChangeCoordinator 와
    # **같은 authority root** 를 공유한다: bootstrap 이 세운 Work/Application 을 그대로
    # 읽어 slot projection·durable command 를 낸다(별도 스토어 조립 없음).
    slot_configuration = SlotConfigurationProduct(
        job_registry, root=default_template_authority_dir(), clock=datetime.now,
    )
    # SealExecutionPlan production 결선 — 「문서 만들기」와 작업대가 **같은 인스턴스**를
    # 쓴다(S10-04 #861): 봉인 권위가 표면마다 갈리면 같은 Work 를 두 basis 로 보게 된다.
    seal_execution = SealExecutionPlanService(
        job_registry, root=default_template_authority_dir(), clock=datetime.now,
    )
    template_files = TemplateFileStore(template_root.path, registry)
    # 「문서 만들기」 — 세션 패널(v6 screen-data 2열). 링1 VM 을 직접 소유하며
    # 실행 결정 계약을 소비하는 유일 세션 표면이다. TXT 레지스트리는 고지 ①
    # (후보 TXT 구획 빈 상태, F6 PR-B)의 술어 전용 — tpl·편집기와 같은 인스턴스.
    # **목록보다 먼저 세운다**(U6-F #980): 전역 저장 폴더의 소유자가 이 컨트롤러라
    # 라이브러리 상세도 그 값을 콜러블로 받는다. 화면 **순서**는 아래 목록이 그대로
    # 진다(닫기 가드 질의 순서라 이유 없이 갈리면 안 된다).
    template_change = TemplateChangeCoordinator(
        job_registry,
        root=default_template_authority_dir(),
        clock=datetime.now,
    )
    job_ctrl = JobController(job_registry, push, pool_registry=pool_registry,
        clock=datetime.now,
        generation_lock=generation_lock, engine=hwpx_engine,
        text_registry=registry,
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=template_change,
        slot_configuration=slot_configuration,
        # SealExecutionPlan production 결선(SX-SEAL #719) — SlotConfigurationProduct
        # 와 **같은 authority root** 를 공유해 같은 workspace·HMAC secret·per-Work
        # fence 아래에서 exact execution plan 을 봉인·관찰한다(dispatch 배선은 SX-03).
        seal_execution=seal_execution,
        # 작업대 Observation 합성(SX-01 #724 소비 어댑터) — 세션 사실을
        # WorkbenchCompositionInput 으로 shape 만 한다(stateless).
        workbench_observation=WorkbenchObservationProduct(),
        tutorial=tutorial_ctrl.notify)

    # 화면 등록 — 새 화면 = 컨트롤러 1개 추가(순수 데이터는 dispatch, 네이티브는 아래 메서드).
    controllers = [
        AuthoringController(push, job_registry=job_registry,
                            template_change=template_change,
                            # 「데이터로 필드 찾기」(#1156) — 등록 데이터 풀과 「문서 작업」이 지금 쓰는 데이터.
                            proposal_data=PoolProposalData(
                                pool_registry, source_from_pool_item,
                                current=lambda: pool_source_of(job_ctrl.data))),
        # 「문서 작업」 전역 라이브러리(§19.6) — 홈 화면의 승계자(재작성 F2). TXT
        # 레지스트리는 편집기·템플릿 관리와 공유(변경이 반영). pool_registry 공유 =
        # 등록 데이터에서 생긴 손상이 라이브러리 경보에 즉시 보인다(#45).
        LibraryController(job_registry, registry, push, pool_registry=pool_registry,
                          generation_lock=generation_lock, engine=hwpx_engine,
                          # 서식 폴더 권위는 **같은 홀더**다(U6-A #975) — 상세 연결 카드의
                          # 템플릿 표시명이 목록·편집기와 같은 이름이어야 한다.
                          template_root=template_root,
                          clock=datetime.now),
        job_ctrl,
        # 템플릿 관리(#13) — TXT 레지스트리는 편집기·「문서 만들기」와 공유(변경이 반영).
        TemplateController(
            registry, push, file_store=template_files, txt_groups=txt_groups,
            template_root=template_root,
            migration_notice=migration_notice,
            # 예제 세트 설치(#891)의 데이터 고정 대상 — 풀 화면과 **같은 인스턴스**다.
            pool_registry=pool_registry,
        tutorial=tutorial_ctrl.notify,
        ),
        # 등록 데이터 참조·수명(#26 #4) — 화면은 사망하고 데이터 선택 다이얼로그가 소비(F1).
        # 「자세히…」의 열 목록만 쓰는 복원기를 함께 준다(고르기 열 공용 ④) — 작업
        # 마운트가 쓰는 것과 **같은 함수**다(복원 규칙이 두 벌이 되지 않는다).
        PoolController(
            pool_registry, push, source_factory=source_from_pool_item
        ),
        # TXT 검토·복사 작업대(v6 S7, 재작성 F6) — 「문서 만들기」에서 TXT 작업을 실행하면
        # 여기로 온다. 대상 글꼴(TargetFontSetting)은 앱 전역 영속 선언의 단일 실체다.
        # 「포함할 내용」 투영(S10-03 #860)은 **읽기 포트 하나**로 붙는다: 작업대는 Product
        # 의 형체를 모르고 「항목 → 고른 선택」 사전만 받는다(workbench_open 이 handoff
        # callable 인 것과 같은 규율). read-only projection 이라 durable 변이는 0 이다.
        # slot-bearing TXT 의 복사는 **봉인된 실행 산출**을 내보낸다(S10-04 #861) — 그
        # 물질화도 읽기 포트 하나로 붙는다: 작업대는 봉인·VDR·start gate 의 형체를 모르고
        # 「검증된 텍스트 아니면 사유」만 받는다.
        WorkbenchController(job_registry, push, clock=datetime.now,
                            target_font=target_font,
                            content_selection=_content_selection_reader(
                                slot_configuration, job_registry
                            ),
                            txt_materialization=_txt_materialization_port(
                                job_registry, seal_execution
                            ),
                            tutorial=tutorial_ctrl.notify),
        # 튜토리얼 체크리스트(#894) — 화면이 아니라 채널이다(표면은 셸 레벨 React 패널).
        # 목록 **끝**에 둔다: 앞 순서는 닫기 가드 질의 순서라 기존 화면 사이에 끼우면
        # 그 순서가 이유 없이 갈린다.
        tutorial_ctrl,
    ]
    # 편집기의 라이브러리 소속 판정 = tpl 채널의 공개 관문(U6-E #979): 종전에는 VM·TXT
    # 레지스트리를 같은 인스턴스로 넘겨 스캔 캐시가 갈라지지 않게 했고, 이제는 판정
    # 자체를 넘겨 **두 곳이 같은 상태를 판정하는 일**이 없다.
    tpl_ctrl = next(c for c in controllers if c.name == "tpl")
    controllers.insert(
        2,
        EditorController(
            job_registry, push,
            clock=datetime.now,
            # 등록 데이터 풀 = 데이터 선택 면·라이브러리와 **같은 인스턴스**(#932 U4-C
            # S2-5): 마법사 데이터 관문의 「등록 데이터에서 고르기」가 이것을 읽는다.
            # #347 이 이 주입을 지우며 "소비자 0 인 seam 은 남기지 않는다"고 적은 것은
            # 그때 사실이었고 지금은 아니다 — 결속이 저장 게이트라 마법사가 데이터를
            # 고르는 표면이 됐다. 편집기는 읽기만 한다(등록·다시 연결·삭제는 그 면의 일).
            pool_registry=pool_registry,
            # 라이브러리 소속 관문(U6-E #979) — 판정은 `tpl` 채널 하나가 진다.
            # 종전에는 편집기가 tpl 의 VM·TXT 레지스트리를 **같은 인스턴스로** 받아
            # 같은 술어를 다시 썼다(단일 실체는 지켜졌지만 판정은 두 곳에 있었다).
            # 이제 넘기는 것은 그 판정 하나이고, 편집기는 상대의 형체를 모른다.
            is_library_path=tpl_ctrl.is_live_path,
            # 서식 폴더 권위도 **같은 홀더**다(U6-A #975 · U6-D #978): 목록이 부르는
            # 표시명(루트 상대·확장자 없음)을 편집기가 그대로 말하려면 루트가 하나여야
            # 한다. 두 홀더를 두면 재지정 직후 한쪽만 새 루트를 보고, 같은 파일이 두
            # 이름으로 불린다.
            template_root=template_root,
            # **전역 저장 폴더의 소유자는 작업 컨트롤러 하나다**(U6-D #978 리뷰 3):
            # 편집기 3단계의 재진술은 그 메모리 값을 **읽기만** 한다. 편집기가 설정 파일을
            # 따로 읽으면 설정 쓰기가 실패한 순간 두 표면이 서로 다른 폴더를 말한다.
            remembered_output_directory=job_ctrl.remembered_output_directory,
            # (`template_library`·`text_registry` 주입은 U6-E(#979)에서 퇴역했다 — 위
            #  `is_library_path` 관문 하나가 그 둘이 답하던 유일한 질문을 진다. 그룹
            #  모델 주입은 그보다 앞서 U6-B 에서 소비자 0 으로 퇴역했다.)
            # (`library_result`·`library_slots` 중계는 U6-B(#976)에서 퇴역했다 — 결과
            #  줄과 구간 항목 목록은 `tpl` 채널 스냅샷이 정본이고 고르기 단계 표면이
            #  그 채널을 직접 구독한다. 중계가 있으면 같은 값이 두 스냅샷에 실린다.)
            after_mapping_saved=job_ctrl.on_editor_mapping_saved,
            save_guard=job_ctrl.editor_save_guard,
            unrepresented_legacy_rules=job_ctrl.unrepresented_legacy_rules,
            # 그 확정의 **읽기 짝**(#911) — 편집기 footer 가 확정 동사를 세울지 말지는
            # 같은 컨트롤러가 관리 검토에 쓰는 사실 하나로 정해진다(두 표면 한 판정).
            binding_confirm_pending=job_ctrl.editor_binding_confirm_pending,
            tutorial=tutorial_ctrl.notify,
        ),
    )
    by_name = {c.name: c for c in controllers}
    _wire_graph(by_name)
    return WorkspaceGraph(home, by_name, template_root, job_registry, pool_registry, token)


def _wire_graph(by_name: dict) -> None:
    """조립된 컨트롤러 사이의 사후 결선 — 화면 간 결합은 이 함수의 줄뿐이다."""
    # 라이브러리 삭제의 타 화면 무장 세션 가드 배선(#268 리뷰) — 라이브러리가 「문서
    # 만들기」보다 먼저 생성되므로 사후 주입. 삭제는 이 조회로 무장 세션을 먼저 묻는다.
    # (「기안」 가드는 화면 사망(F6 PR-B)과 함께 걷혔다 — 작업대는 몰입 표면이라
    # 라이브러리와 동시에 보이지 않고, 진입 자체가 「문서 만들기」 세션을 지난다.)
    # 작업대 배선(F6) — 「문서 만들기」가 진입 판정을 내고 세션 개시만 위임한다.
    # 컨트롤러 객체가 아니라 **handoff callable** 을 결선한다(P2-24): 화면 간 결합은
    # 이 조립부의 한 줄뿐이고, 「문서 만들기」는 작업대의 형체를 모른다.
    by_name["job"].workbench_open = by_name["workbench"].open
    by_name["library"].session_guards = [
        by_name["job"].session_guard_for,
    ]
    # 템플릿 bytes 변이 → 편집 세션 재정산(S8G-00 #320) — tpl 이 편집기보다 먼저 조립되고
    # 편집기는 tpl 을 모르므로 여기서 사후 배선한다(workbench_open·session_guards 선례).
    # 디스패치 액션이 아니라 **컨트롤러 간 seam** 이라 action registry 밖이다: 웹이 부르는
    # 표면이 아니고, 원인 동사(tpl 변이)의 완료와 같은 줄에서 파이썬이 스스로 부른다.
    by_name["tpl"].mutation_sinks.append(
        by_name["editor"].reconcile_template_mutation
    )
    # 저작 화면의 파일 저장도 템플릿 bytes 변이다(TXT 편집 모달의 승계자) — 같은 sink 가
    # 같은 파일을 든 편집 세션을 재정산한다.
    by_name["authoring"].mutation_sinks.append(
        by_name["editor"].reconcile_template_mutation
    )
    # 누름틀 변환 성립 → 「문서 만들기」 세션 기억(#894). 위 변이 sink 와 **갈라** 붙이는
    # 이유는 동사가 다르기 때문이다: 변이는 「파일이 바뀌었다」 전부(개명·삭제·복원·TXT
    # 저장 포함)이고 여기 필요한 것은 「누름틀로 변환됐다」 하나다. 같은 sink 를 쓰면
    # slot 개명 한 번이 T16「변환본으로 생성」을 거짓으로 켠다. 이것도 디스패치 액션이
    # 아니라 컨트롤러 간 seam 이라 action registry 밖이다.
    by_name["tpl"].compile_sinks.append(
        by_name["job"].note_template_compiled
    )
