"""변환 템플릿 여정의 **연결 확정** 관통 회귀(#911) — 편집기와 「문서 만들기」를 한 배선에서.

#895 3차 live 관측이 남긴 결함: 관리 검토가 ``REVIEW_BINDING`` 확정을 요구하는데 그 확정을
수행할 활성 동사가 화면에 없었다. 마법사 저장 시점에는 권위가 아직 없어(부트스트랩이 나중에
발급) 결속 커밋 가드가 열리지 않고, 재진입 시점에는 매핑이 이미 옳아 dirty 가 거짓이라 푸터
두 동사가 모두 잠겼다. 두 사실 각각은 참인데 합쳐 놓으면 닫을 길이 없는 사슬이 된다.

이 파일이 재는 것은 **여정 전체**다: 저장소의 다른 어느 테스트도 편집기와 「문서 만들기」를
같은 레지스트리 위에서 실제로 잇지 않았고(콜백은 늘 스텁이었다), 그래서 이 결함류는 두
컨트롤러 각자의 초록 사이 틈에서 살았다. 실 Product 넷(TemplateChange·SlotConfiguration·
WorkbenchObservation·SealExecutionPlan)을 같은 authority root 로 배선하고, 부트스트랩 발급도
실제 ``template_check`` 로 받는다.
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
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.external.template_inspection import HWPX_TEMPLATE_OPS, inspect_hwpx_template
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.template_root import TemplateRoot
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_template import TemplateController
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator
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

    콜백 두 짝이 이 여정의 심장이다: ``after_mapping_saved``(확정을 쓴다)와
    ``binding_confirm_pending``(그 확정이 남았는지 읽는다). 앱 조립(``app.py``)이 거는 것과
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
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
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
        binding_confirm_pending=job_ctrl.editor_binding_confirm_pending,
    )
    return job_ctrl, editor, tpl, reg


def _confirm_every_row(ctrl) -> None:
    """전 행 확인 — 표면이 실제로 밟는 경로(내용 행은 배지, 빈 행은 「비워 둠」)의 축약.

    구 「모두 확정」 2발(`confirm_all` + 비움 이름게이트 `confirm_blanks`)의 후계다(U6-C
    #977). 일괄 승격(`confirm_suggested`)은 **자동 제안만** 올리므로 전 행 확인은 남은 행을
    행별로 답해야 완성된다 — 그것이 이 표면의 실제 동선이고, 테스트가 제품에 없는 동사로
    상태를 만들지 않게 하는 자리다.
    """
    for row in ctrl.snapshot()["rows"]:
        if row["confirmable"]:
            ctrl.dispatch("set_confirmed", {"index": row["index"], "confirmed": True})
        else:
            ctrl.dispatch("set_blank", {"index": row["index"]})


def _wizard_save(editor: EditorController, tpl: Path, name: str) -> dict:
    """마법사 한 바퀴 — 템플릿·데이터를 고르고 전 필드를 고정값으로 확정한 뒤 저장.

    데이터 연결은 저장 게이트다(#932 U4-C S2-3). 열 이름은 템플릿 필드와 겹치지 않게
    둔다 — 자동 제안이 서면 이 여정이 재려는 것(확정 대기)이 아니라 매핑이 달라진다.
    """
    data = tpl.parent / "행목록.csv"
    if not data.exists():
        data.write_text("항목,수량\n연필,3\n", encoding="utf-8-sig")
    editor.load_template_path(str(tpl))
    editor.load_data_path(str(data))
    editor.dispatch("goto_section", {"section": "binding"})
    for index in range(len(editor.model.rows)):
        editor.dispatch("set_display", {"index": index, "type": "const", "fmt": ""})
        editor.dispatch("set_const", {"index": index, "const": f"v{index}"})
    _confirm_every_row(editor)
    editor.dispatch("set_name", {"name": name})
    editor.dispatch("set_pattern", {"pattern": "doc-{{seq:001}}"})
    return editor.dispatch("save", {})


def _blockers(job_ctrl: JobController) -> list:
    return job_ctrl._workbench_observation_zone(tmissing=False)["blockers"]


def test_converted_template_journey_closes_review_binding_with_an_unchanged_confirm(
    tmp_path: Path,
) -> None:
    """마법사 저장 → 부트스트랩 발급 → 재진입 확정 대기 → 무변경 확정 → REVIEW_BINDING 닫힘."""
    job_ctrl, editor, tpl, reg = _wire(tmp_path)
    committed: list[str] = []
    commit = job_ctrl.on_editor_mapping_saved
    editor._after_mapping_saved = lambda ref: (committed.append(ref), commit(ref))[1]

    # ① 마법사 저장 — 권위가 아직 없어 결속 확정은 **부르지 않는다**(가드 존치, 오커밋 방지).
    assert _wizard_save(editor, tpl, WORK)["ok"] is True
    assert committed == [], "권위 발급 전 마법사 저장이 결속을 커밋하면 안 된다"
    assert reg.load(WORK).authority_id == ""

    # ② 부트스트랩 — 「변경사항 확인」이 권위를 발급하고, 확인이 실행 관찰을 세운다.
    job_ctrl.dispatch("select_job", {"name": WORK})
    job_ctrl.dispatch("template_check", {"request_id": "k1"})
    assert reg.load(WORK).authority_id, "template_check 가 권위를 발급해야 한다"
    job_ctrl.dispatch("resolve_execution", {})
    assert "REVIEW_BINDING" in _blockers(job_ctrl), "확정 전에는 관리 검토가 결속을 요구한다"

    # ③ 편집기 재진입 — 손댈 것이 없다. 그래서 변경 기반 무장은 닫혀 있고, 확정 대기가 참이다.
    editor.load_job(WORK)
    snap = editor.snapshot()
    assert snap["dirty"] is False, "매핑이 이미 옳으므로 더럽힐 것이 없다(#911 의 전제)"
    assert snap["binding_confirm"]["pending"] is True
    assert snap["binding_confirm"]["label"], "확정 동사 라벨은 백엔드가 싣는다"

    # ④ 무변경 확정 — 새 백엔드 동사가 아니라 기존 저장 경로 그대로다.
    result = editor.dispatch("save", {})
    assert result["ok"] is True
    assert committed == [WORK], "무변경 저장이 결속 확정을 부른다"

    # ⑤ 사슬이 닫힌다 — 그리고 확정 동사는 스스로 걷힌다.
    assert "REVIEW_BINDING" not in _blockers(job_ctrl)
    assert editor.snapshot()["binding_confirm"]["pending"] is False
    assert job_ctrl.editor_binding_confirm_pending(WORK) is False


def test_confirm_pending_never_precedes_the_managed_review_that_asks_for_it(
    tmp_path: Path,
) -> None:
    """확정 대기는 관리 검토보다 **먼저 서지 않는다** — 거울상 결함(빈 확정 동사) 음성 대조.

    권위 발급 전에는 확정할 수 있는 것이 없고, 그 상태에서 동사를 세우면 누르는 순간 아무
    일도 일어나지 않는다(가드가 커밋을 부르지 않는다). 지금 고치는 침묵과 같은 종류다.
    """
    job_ctrl, editor, tpl, _reg = _wire(tmp_path)
    assert _wizard_save(editor, tpl, WORK)["ok"] is True

    editor.load_job(WORK)
    assert editor.snapshot()["binding_confirm"]["pending"] is False
    assert job_ctrl.editor_binding_confirm_pending(WORK) is False


def test_confirm_pending_is_false_for_a_work_this_session_has_no_evidence_about(
    tmp_path: Path,
) -> None:
    """세션이 겨눈 작업과 편집 대상이 다르면 대기는 거짓이다(정직한 「모른다」)."""
    job_ctrl, editor, tpl, reg = _wire(tmp_path)
    assert _wizard_save(editor, tpl, WORK)["ok"] is True
    job_ctrl.dispatch("select_job", {"name": WORK})
    job_ctrl.dispatch("template_check", {"request_id": "k1"})
    job_ctrl.dispatch("resolve_execution", {})
    assert "REVIEW_BINDING" in _blockers(job_ctrl)

    assert job_ctrl.editor_binding_confirm_pending("남의작업") is False
