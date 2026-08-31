"""TXT 물질화 왕복(S10-04 · #861) — 선택 → 봉인 → 물질화 → 재스캔, 그리고 작업대 인수.

여기가 재는 것은 #861 의 종료 조건이다: slot-bearing TXT 의 산출물이 **Sealed Plan 만 소비해**
나오고, 화면이 보여 준 문장과 클립보드로 나가는 bytes 가 같으며, slotless 경로는 byte 동등하게
남는다. 단계별 후행조건의 위반 주입은 ``tests/test_text_materialization_conformance.py`` 가
따로 진다 — 여기는 실 store·실 봉인 기계를 지나는 왕복이다.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.text_structure import scan_text_structure
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.materialization_conformance_vocabulary import (
    MaterializedDocumentBytes,
)
from hwpxfiller.external.output_files import (
    ensure_output_directory,
    existing_output_paths,
)
from hwpxfiller.webapp.app import (
    _content_selection_reader,
    _txt_materialization_port,
)
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_workbench import (
    COPY_BLOCK_MATERIALIZATION_DIVERGED,
    COPY_BLOCK_MATERIALIZATION_UNAVAILABLE,
    WorkbenchController,
    TargetFontSetting,
)
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator
from hwpxfiller.webapp.txt_materialization import (
    TxtMaterializationRefused,
    TxtMaterializationService,
    materialized_text,
)

NOW = datetime(2026, 8, 25, 9, 0, 0)

SLOT_BODY = "\n".join(
    [
        "수신: {{수신}}",
        "{{#항목 첨부 첨부 서류}}",
        "담당자: {{담당자}}",
        "{{#선택 계약서 계약서}}",
        "계약서를 첨부합니다. {{건명}}",
        "{{/선택}}",
        "{{#선택 견적서 견적서}}",
        "견적서를 첨부합니다.",
        "{{/선택}}",
        "{{/항목}}",
        "끝.",
        "",
    ]
)

SLOTLESS_BODY = "수신: {{수신}}\n담당자: {{담당자}}\n끝.\n"

RECORD = {"수신처": "○○청", "담당": "홍길동", "건명": "무언가"}


def _clock():
    return lambda: NOW


def _profile() -> MappingProfile:
    return MappingProfile(
        name="안내문",
        mappings=[
            FieldMapping(template_field="수신", type="text", source="수신처"),
            FieldMapping(template_field="담당자", type="text", source="담당"),
            FieldMapping(template_field="건명", type="text", source="건명"),
        ],
    )


class _Harness:
    """실 store 세벌을 같은 authority root 로 배선한 헤드리스 조립(앱 조립과 같은 규약)."""

    def __init__(self, tmp_path: Path, body: str) -> None:
        self._choices = 0
        self.root = tmp_path / "authority"
        self.template = tmp_path / "안내문.txt"
        # LF 로 못박는다 — 줄 끝은 물질화가 원문 그대로 옮기는 축이라(``keepends``),
        # 플랫폼 번역이 끼면 이 테스트가 재는 것이 줄 끝 협상으로 바뀐다.
        self.template.write_text(body, encoding="utf-8", newline="\n")
        self.registry = JobRegistry(tmp_path / "jobs")
        self.registry.save(
            Job(name="안내문", template_path=str(self.template), mapping=_profile())
        )
        self.slot_product = SlotConfigurationProduct(
            self.registry, root=self.root, clock=_clock()
        )
        self.job = JobController(
            self.registry, lambda s, snap: None,
            clock=_clock(), engine=make_hwpx_engine(),
            pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
            generation_lock=threading.Lock(),
            file_source_factory=source_for_path,
            pool_source_factory=source_from_pool_item,
            existing_outputs=existing_output_paths,
            ensure_output_dir=ensure_output_directory,
            template_change=TemplateChangeCoordinator(
                self.registry, root=self.root, clock=_clock()
            ),
            slot_configuration=self.slot_product,
        )
        self.job.dispatch("select_job", {"name": "안내문"})
        self.job.dispatch("template_check", {"request_id": "k1"})
        self.seal = SealExecutionPlanService(
            self.registry, root=self.root, clock=_clock()
        )
        self.materialization = TxtMaterializationService(
            self.registry, self.seal, clock=_clock()
        )

    def choose(self, slot_id: str, option_id: str) -> None:
        token = self.job.dispatch("open_slot_configuration", {})["current_view"][
            "new_configuration_token"
        ]
        self._choices += 1
        self.job.dispatch(
            "select_slot_option",
            {
                "configuration_token": token,
                "slot_id": slot_id,
                "option_id": option_id,
                "request_id": f"r{self._choices}",
            },
        )

    def workbench(self, *, wire_materialization: bool = True) -> WorkbenchController:
        # 실 앱 조립의 포트 두 개를 그대로 쓴다 — 테스트가 번역 한 겹을 다시 짜면 그 사본만
        # 초록이고 제품 배선은 검사되지 않는다.
        port = (
            _txt_materialization_port(self.registry, self.seal)
            if wire_materialization
            else None
        )
        controller = WorkbenchController(
            self.registry, lambda s, snap: None, clock=_clock(),
            target_font=TargetFontSetting(),
            content_selection=_content_selection_reader(
                self.slot_product, self.registry
            ),
            txt_materialization=port,
        )
        controller.open(self.registry.load("안내문"), [(0, dict(RECORD))])
        return controller


# ── 왕복: 선택 → 봉인 → 물질화 → 재스캔 ────────────────────────────────────────
def test_selection_seals_and_materializes_only_the_chosen_option(tmp_path: Path) -> None:
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")

    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="copy-1"
    )
    assert isinstance(outcome, MaterializedDocumentBytes), outcome
    text = materialized_text(outcome)

    assert text == "수신: ○○청\n담당자: 홍길동\n견적서를 첨부합니다.\n끝.\n"
    # 재스캔 postcondition 의 사용자 얼굴: 마커 0, 고르지 않은 선택지 내용 부재.
    rescan = scan_text_structure(text)
    assert rescan.summary.markers == 0 and rescan.slots == ()
    assert "계약서를 첨부합니다." not in text
    assert outcome.output_digest.startswith("sha256:")


def test_changing_the_selection_changes_the_materialized_bytes(tmp_path: Path) -> None:
    """산출은 **지금 선택**의 함수다 — 봉인이 옛 선택을 들고 있으면 여기서 빨강이다."""
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    first = harness.materialization.materialize_record("안내문", RECORD, request_id="c1")
    harness.choose("첨부", "계약서")
    second = harness.materialization.materialize_record("안내문", RECORD, request_id="c2")

    assert isinstance(first, MaterializedDocumentBytes)
    assert isinstance(second, MaterializedDocumentBytes)
    assert "견적서를 첨부합니다." in materialized_text(first)
    assert materialized_text(second) == (
        "수신: ○○청\n담당자: 홍길동\n계약서를 첨부합니다. 무언가\n끝.\n"
    )


def test_unchosen_slot_refuses_with_the_upstream_blocker(tmp_path: Path) -> None:
    """고르지 않았으면 봉인이 서지 않는다 — 사유는 상류 blocker 의 재진술이다."""
    harness = _Harness(tmp_path, SLOT_BODY)
    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="copy-1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == "EXECUTION_PLAN_NOT_SEALED"
    assert "SLOT_CONFIGURATION_INCOMPLETE" in outcome.detail


# ── 작업대 인수: 관찰 bytes == 복사 bytes ──────────────────────────────────────
def test_workbench_copies_the_materialized_bytes_for_slot_bearing_txt(
    tmp_path: Path,
) -> None:
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    controller = harness.workbench()

    assert controller._copy_block() == ""  # S10-03 의 상시 차단이 걷혔다
    written: "list[str]" = []
    result = controller.copy_to(controller.copy_token(), written.append)
    assert result["copied"] is True, result
    assert len(written) == 1

    observed, _report = controller.render()  # 화면이 그린 그 문장
    materialized = materialized_text(
        harness.materialization.materialize_record("안내문", RECORD, request_id="probe")
    )
    assert written[0] == observed == materialized


def test_workbench_refuses_when_the_screen_and_the_document_diverge(
    tmp_path: Path,
) -> None:
    """전각 정렬은 표시 전용 치환이라 봉인된 실행에 없다 — 조용히 한쪽을 내보내지 않는다."""
    harness = _Harness(tmp_path, "\n".join([
        "수신:    {{수신}}",
        "{{#항목 첨부 첨부}}",
        "{{#선택 계약서 계약서}}",
        "계약서",
        "{{/선택}}",
        "{{/항목}}",
        "",
    ]))
    harness.choose("첨부", "계약서")
    controller = harness.workbench()
    controller.dispatch("set_fullwidth", {"value": True})

    written: "list[str]" = []
    result = controller.copy_to(controller.copy_token(), written.append)
    assert result["copied"] is False
    assert result["error"] == COPY_BLOCK_MATERIALIZATION_DIVERGED
    assert written == []  # 클립보드는 손대지 않았다


def test_unwired_materialization_port_blocks_slot_bearing_copy(tmp_path: Path) -> None:
    """포트 미주입은 오배선이다 — 투영을 대신 내보내지 않고 사유를 말한다."""
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    controller = harness.workbench(wire_materialization=False)

    assert controller._copy_block() == COPY_BLOCK_MATERIALIZATION_UNAVAILABLE
    written: "list[str]" = []
    assert controller.copy_to(controller.copy_token(), written.append)["copied"] is False
    assert written == []


def test_refusal_reason_reaches_the_copy_result(tmp_path: Path) -> None:
    """물질화가 거절하면 그 사유가 그대로 복사 결과에 실린다(조용한 실패 0)."""
    harness = _Harness(tmp_path, SLOT_BODY)  # 선택하지 않은 채로 연다
    controller = harness.workbench()

    result = controller.copy_to(controller.copy_token(), lambda _text: None)
    assert result["copied"] is False
    assert "SLOT_CONFIGURATION_INCOMPLETE" in result["error"]


# ── slotless 회귀축: 기존 산출과 byte 동등 ─────────────────────────────────────
def test_slotless_workbench_copy_is_byte_identical_to_the_legacy_path(
    tmp_path: Path,
) -> None:
    """마커 0 이면 물질화 경로를 타지 않는다 — 기존 카드 렌더 그대로다."""
    from hwpxfiller.domain.text_render import render_record

    harness = _Harness(tmp_path, SLOTLESS_BODY)
    controller = harness.workbench()
    assert controller._copy_block() == ""

    written: "list[str]" = []
    assert controller.copy_to(controller.copy_token(), written.append)["copied"] is True
    legacy, _report = render_record(SLOTLESS_BODY, _profile().apply(RECORD))
    assert written == [legacy]


# ── 순수 helper: capture 성형과 사유 재진술 ────────────────────────────────────
def test_source_value_capture_freezes_every_column_as_untyped_text() -> None:
    """소스 값은 언제나 타입 없는 텍스트다 — 해석은 없고, str 승격 관용만 남는다."""
    import hwpxfiller.webapp.txt_materialization as txt
    from hwpxfiller.domain.raw_data_record import SourceNull, SourceText
    from hwpxfiller.webapp.txt_materialization import _source_value

    assert not hasattr(txt, "_declared_source_types")
    assert _source_value(None) == SourceNull()
    assert _source_value(12) == SourceText("12")  # 비문자열은 문자열화(캡처 관용)
    assert _source_value("12.5") == SourceText("12.5")
    assert _source_value("계약 후 90일 이내") == SourceText("계약 후 90일 이내")
    assert _source_value("1,000,000") == SourceText("1,000,000")


def test_blocked_detail_restates_each_upstream_outcome_shape() -> None:
    """사유는 상류 판정의 재진술이다 — 여기서 새 문안을 발명하지 않는다."""
    from types import SimpleNamespace

    from hwpxfiller.webapp.txt_materialization import _blocked_detail

    assert "구성" in _blocked_detail(
        SimpleNamespace(normalized_blockers=("구성",))
    )
    assert "정책" in _blocked_detail(SimpleNamespace(policy_code="정책"))
    assert "바뀌었" in _blocked_detail(SimpleNamespace(stale_reason="basis"))
    assert _blocked_detail(SimpleNamespace()) == "실행 계획을 봉인할 수 없습니다."


def test_non_txt_job_is_refused_before_anything_else(tmp_path: Path) -> None:
    """HWPX 작업을 이 표면으로 보내면 오배선이다 — 조용히 평문 취급하지 않는다."""
    from hwpxfiller.webapp.txt_materialization import TXT_MEDIA_REQUIRED

    harness = _Harness(tmp_path, SLOTLESS_BODY)
    hwpx_path = tmp_path / "문서.hwpx"
    hwpx_path.write_bytes(b"not really hwpx")
    harness.registry.save(
        Job(name="hwpx작업", template_path=str(hwpx_path)), allow_overwrite=True
    )
    outcome = harness.materialization.materialize_record(
        "hwpx작업", RECORD, request_id="c1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == TXT_MEDIA_REQUIRED


def test_work_without_a_checked_template_is_refused(tmp_path: Path) -> None:
    """템플릿 확인 전에는 실행 권위가 없다 — 사유가 그 사실을 말한다."""
    from hwpxfiller.webapp.txt_materialization import TEMPLATE_INITIALIZATION_REQUIRED

    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "미확인.txt"
    tpl.write_text(SLOTLESS_BODY, encoding="utf-8", newline="\n")
    reg.save(Job(name="미확인", template_path=str(tpl), mapping=_profile()))
    seal = SealExecutionPlanService(reg, root=tmp_path / "authority", clock=_clock())
    service = TxtMaterializationService(reg, seal, clock=_clock())

    outcome = service.materialize_record("미확인", RECORD, request_id="c1")
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == TEMPLATE_INITIALIZATION_REQUIRED


def test_a_record_missing_a_required_column_is_a_validation_refusal(
    tmp_path: Path,
) -> None:
    """record 자격 판정은 record_validation 소유다 — 사유 코드를 그대로 재진술한다."""
    from hwpxfiller.webapp.txt_materialization import RECORD_VALIDATION_BLOCKED

    harness = _Harness(tmp_path, SLOTLESS_BODY)
    outcome = harness.materialization.materialize_record(
        "안내문", {"수신처": "○○청"}, request_id="c1"  # 「담당」 열이 없다
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == RECORD_VALIDATION_BLOCKED


def test_a_field_without_a_mapping_decision_is_a_binding_review_refusal(
    tmp_path: Path,
) -> None:
    """Active Field 에 Mapping 결정이 없으면 내부 pin 이 사용자 결정을 요구한다(자동 추측 0)."""
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "계약서")   # 「건명」이 Active 가 된다
    stripped = MappingProfile(
        name="안내문",
        mappings=[m for m in _profile().mappings if m.template_field != "건명"],
    )
    from dataclasses import replace

    # authority_id 를 승계한다 — 새 Job 객체로 덮으면 Work 권위가 끊겨 다른 사유가 나온다.
    harness.registry.save(
        replace(harness.registry.load("안내문"), mapping=stripped), allow_overwrite=True
    )

    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="c1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED"
    assert "건명" in outcome.detail


def test_start_gate_refusal_reaches_the_caller_verbatim(
    tmp_path: Path, monkeypatch
) -> None:
    """start gate 의 거절 어휘는 재조립하지 않는다 — 코드·사유가 그대로 온다."""
    from hwpxfiller.external.materialization_start_gate import (
        StartMaterializationRefusal,
    )
    from hwpxfiller.webapp import txt_materialization as module

    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    monkeypatch.setattr(
        module,
        "start_materialization",
        lambda **_kw: StartMaterializationRefusal("DIGEST_MISMATCH", "stale Plan"),
    )
    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="c1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert (outcome.code, outcome.detail) == ("DIGEST_MISMATCH", "stale Plan")


def test_postcondition_failure_reaches_the_caller_verbatim(
    tmp_path: Path, monkeypatch
) -> None:
    """후행조건 위반도 같은 규율이다 — 산출 대신 그 코드가 복사 차단 사유가 된다."""
    from hwpxfiller.external.materialization_conformance_vocabulary import (
        ConformanceFailure,
    )
    from hwpxfiller.webapp import txt_materialization as module

    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    monkeypatch.setattr(
        module,
        "start_materialization",
        lambda **_kw: ConformanceFailure("MARKER_CLEANUP_VIOLATION", "마커 잔존"),
    )
    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="c1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == "MARKER_CLEANUP_VIOLATION"


def test_missing_run_context_is_refused_without_touching_the_runner(
    tmp_path: Path, monkeypatch
) -> None:
    from hwpxfiller.webapp.txt_materialization import TEMPLATE_INITIALIZATION_REQUIRED

    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    monkeypatch.setattr(
        harness.seal, "managed_run_context", lambda *_a, **_kw: None
    )
    outcome = harness.materialization.materialize_record(
        "안내문", RECORD, request_id="c1"
    )
    assert isinstance(outcome, TxtMaterializationRefused)
    assert outcome.code == TEMPLATE_INITIALIZATION_REQUIRED


def test_a_throwing_materialization_port_blocks_the_copy_with_a_reason(
    tmp_path: Path,
) -> None:
    """포트가 터져도 세션은 산다 — 복사만 막고 사유를 말한다(조용한 성공 0)."""
    harness = _Harness(tmp_path, SLOT_BODY)
    harness.choose("첨부", "견적서")
    controller = harness.workbench()

    def _boom(_work_ref, _record, _request_id):
        raise RuntimeError("저장소가 사라졌다")

    controller._txt_materialization = _boom
    written: "list[str]" = []
    result = controller.copy_to(controller.copy_token(), written.append)
    assert result["copied"] is False
    assert "저장소가 사라졌다" in result["error"]
    assert written == []
    assert controller.is_open  # 세션은 그대로다
