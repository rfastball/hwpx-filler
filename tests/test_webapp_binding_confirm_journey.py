"""변환 템플릿 여정의 **연결 확정** 관통 회귀(#911) — 편집기와 「문서 만들기」를 한 배선에서.

#895 3차 live 관측이 남긴 결함: 관리 검토가 ``REVIEW_BINDING`` 확정을 요구하는데 그 확정을
수행할 활성 동사가 화면에 없었다. 마법사 저장 시점에는 권위가 아직 없어(부트스트랩이 나중에
발급) 결속 커밋 가드가 열리지 않고, 재진입 시점에는 매핑이 이미 옳아 dirty 가 거짓이라 푸터
두 동사가 모두 잠겼다. 두 사실 각각은 참인데 합쳐 놓으면 닫을 길이 없는 사슬이 된다.

이 파일이 재는 것은 **여정 전체**다: 저장소의 다른 어느 테스트도 편집기와 「문서 만들기」를
같은 레지스트리 위에서 실제로 잇지 않았고(콜백은 늘 스텁이었다), 그래서 이 결함류는 두
컨트롤러 각자의 초록 사이 틈에서 살았다. 실 Product 넷(TemplateChange·SlotConfiguration·
WorkbenchObservation·SealExecutionPlan)을 같은 authority root 로 배선하고, 권위 발급도
실제 착석(``select_job``)으로 받는다.

새 작업은 저장된 Job Mapping 자체가 연결 권위다. 착석 뒤 첫 준비는 추가 판본 쓰기 없이
그 저장본을 실행 입력으로 읽는다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.field_binding_store import WorkFieldBindingStore
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.template_root import TemplateRoot
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_template import TemplateController
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.external.template_change import TemplateChangeCoordinator
from hwpxfiller.webapp.workbench_observation_product import WorkbenchObservationProduct

NOW = datetime(2026, 8, 25, 9, 0, 0)
WORK = "공고서"


def _clock():
    return lambda: NOW


def _template(path: Path, fields) -> None:
    """누름틀만 든 최소 HWPX — 변환이 끝난 템플릿의 형상(구간 표기 없음)."""
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{n}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{n}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for n in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + "</hp:p></hs:sec>"
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _wire(tmp_path: Path):
    """편집기 ↔ 「문서 만들기」를 **한 레지스트리·한 authority root** 로 실제로 잇는다.

    저장 가드와 관찰 콜백은 앱 조립(``app.py``)이 거는 것과
    같은 두 메서드를 그대로 건다 — 스텁으로 바꾸면 재려던 틈이 그대로 남는다.
    """
    root = tmp_path / "authority"
    tpl = tmp_path / "공고서.hwpx"
    _template(tpl, ["공고명", "수요기관"])
    reg = JobRegistry(tmp_path / "jobs")
    job_ctrl = JobController(
        reg,
        lambda s, snap: None,
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=TemplateChangeCoordinator(reg, root=root, clock=_clock()),
        slot_configuration=SlotConfigurationProduct(reg, root=root, clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
        seal_execution=SealExecutionPlanService(reg, root=root, clock=_clock()),
    )
    # 라이브러리 소속 관문은 `tpl` 채널 하나다(U6-E #979) — 이 여정의 템플릿이 실제로
    # 사는 폴더 위에 그 채널을 세워 공개 술어를 그대로 넘긴다(제품 조립과 같은 짝).
    tpl_root = TemplateRoot(default_root=tmp_path)
    tpl_registry = TextTemplateRegistry(tpl_root.path)
    tpl_ctrl = TemplateController(
        tpl_registry,
        lambda s, snap: None,
        file_store=TemplateFileStore(tpl_root.path, tpl_registry),
        template_root=tpl_root,
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
    )
    editor = EditorController(
        reg,
        lambda s, snap: None,
        clock=lambda: NOW,
        is_library_path=tpl_ctrl.is_live_path,
        template_root=tpl_root,
        after_mapping_saved=job_ctrl.on_editor_mapping_saved,
        save_guard=job_ctrl.editor_save_guard,
        unrepresented_legacy_rules=job_ctrl.unrepresented_legacy_rules,
        binding_confirm_pending=job_ctrl.editor_binding_confirm_pending,
    )
    return job_ctrl, editor, tpl, reg


def _confirm_every_row(ctrl) -> None:
    """전 행 확인 — 표면이 실제로 밟는 경로(내용 행은 배지, 빈 행은 빈 고정값 선언)의 축약.

    구 「모두 확정」 2발(`confirm_all` + 비움 이름게이트 `confirm_blanks`)의 후계다(U6-C
    #977). 일괄 승격(`confirm_suggested`)은 **자동 제안만** 올리므로 전 행 확인은 남은 행을
    행별로 답해야 완성된다 — 그것이 이 표면의 실제 동선이고, 테스트가 제품에 없는 동사로
    상태를 만들지 않게 하는 자리다.
    """
    for row in ctrl.snapshot()["rows"]:
        if not row["confirmable"]:
            # 채울 것이 없는 행의 답은 **빈 고정값 선언**이다(「비워 둠」 표시형 퇴역).
            ctrl.dispatch("set_display", {"index": row["index"], "type": "const", "fmt": ""})
        ctrl.dispatch("set_confirmed", {"index": row["index"], "confirmed": True})


def _wizard_save(editor: EditorController, tpl: Path, name: str) -> dict:
    """마법사 한 바퀴 — 템플릿·데이터를 고르고 전 필드를 고정값으로 확정한 뒤 저장.

    데이터 연결은 저장 게이트다(#932 U4-C S2-3). 열 이름은 템플릿 필드와 겹치지 않게
    둔다 — 자동 제안이 서면 이 여정이 재려는 것(확정 대기)이 아니라 매핑이 달라진다.
    """
    data = tpl.parent / "행목록.csv"
    if not data.exists():
        data.write_text("항목,수량\n연필,3\n", encoding="utf-8-sig")
    editor.loader.load_template_path(str(tpl))
    editor.load_data_path(str(data))
    editor.dispatch("goto_section", {"section": "binding"})
    for index in range(len(editor.edit.model.rows)):
        editor.dispatch("set_display", {"index": index, "type": "const", "fmt": ""})
        editor.dispatch("set_const", {"index": index, "const": f"v{index}"})
    _confirm_every_row(editor)
    editor.dispatch("set_name", {"name": name})
    editor.dispatch("set_pattern", {"pattern": "doc-{{seq:001}}"})
    return editor.dispatch("save", {})


def _blockers(job_ctrl: JobController) -> list:
    return job_ctrl._workbench_observation_zone(tmissing=False)["blockers"]


def test_new_work_prepares_its_saved_mapping_without_a_binding_commit(
    tmp_path: Path,
) -> None:
    """마법사 저장 → 착석 발급 → 저장본 그대로 준비 → REVIEW_BINDING 이 서지 않는다.

    #911 은 이 자리를 「재진입 무변경 확정」으로 닫았다. 사용자가 방금 편집기에서 확정한 연결을
    「문서 만들기」가 모든 필드의 「입력이 필요한 항목」으로 한 번 더 묻는 것이었고(0.9.0 실사용
    보고), 그 사이의 사실은 권위가 저장 뒤에 섰다는 것 하나뿐이다. 저장본이 활성 Field 를 전부
    덮으면 권위가 서는 순간 그 결정이 곧 최초 판본이다.
    """
    job_ctrl, editor, tpl, reg = _wire(tmp_path)
    # ① 마법사 저장은 Job Mapping 한 파일에 완료된다.
    assert _wizard_save(editor, tpl, WORK)["ok"] is True
    assert reg.load(WORK).authority_id == ""

    # ② 착석 — 권위가 서고, 저장본에서 실행 연결을 파생한다.
    job_ctrl.dispatch("select_job", {"name": WORK})
    assert reg.load(WORK).authority_id, "착석이 권위를 발급해야 한다"
    review = job_ctrl.execution.current_binding_review(WORK)
    assert review is not None
    assert [item.field_id for item in review.input_requirements] == ["공고명", "수요기관"]
    assert not any(item.action_required for item in review.input_requirements), (
        "저장본이 덮은 활성 Field 가 입력이 필요한 항목으로 남았습니다"
    )

    # ③ 확인 — 결속 축 blocker 가 없고 S5 판본도 쓰지 않았다.
    job_ctrl.dispatch("resolve_execution", {})
    assert "REVIEW_BINDING" not in _blockers(job_ctrl)
    assert not WorkFieldBindingStore(tpl.parent / "authority" / "field_bindings").exists(
        reg.load(WORK).authority_id
    )

    # ④ 편집기 재진입 — 확정할 것이 없으므로 확정 동사도 서지 않는다(거울상 음성).
    editor.load_job(WORK)
    assert editor.snapshot()["binding_confirm"]["pending"] is False
    assert job_ctrl.editor_binding_confirm_pending(WORK) is False


def test_generation_busy_refuses_save_before_job_replacement(tmp_path: Path) -> None:
    job_ctrl, editor, tpl, registry = _wire(tmp_path)
    assert _wizard_save(editor, tpl, WORK)["ok"] is True
    before = registry.content_fingerprint(registry.load(WORK))
    editor.load_job(WORK)
    editor.dispatch("set_const", {"index": 0, "const": "new value"})
    editor.dispatch("set_confirmed", {"index": 0, "confirmed": True})

    assert job_ctrl.runs.lock.acquire(blocking=False)
    try:
        result = editor.dispatch("save", {})
    finally:
        job_ctrl.runs.lock.release()
    assert result["ok"] is False
    assert "문서 생성" in result["block_reason"]
    assert registry.content_fingerprint(registry.load(WORK)) == before
    assert editor.dispatch("save", {})["ok"] is True
    assert registry.content_fingerprint(registry.load(WORK)) != before


def test_confirm_pending_never_precedes_the_managed_review_that_asks_for_it(
    tmp_path: Path,
) -> None:
    job_ctrl, editor, tpl, _reg = _wire(tmp_path)
    assert _wizard_save(editor, tpl, WORK)["ok"] is True
    editor.load_job(WORK)
    assert editor.snapshot()["binding_confirm"]["pending"] is False
    assert job_ctrl.editor_binding_confirm_pending(WORK) is False
