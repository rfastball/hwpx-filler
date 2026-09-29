"""slot 없는 HWPX 작업의 문서 생성 좌표 — 권위를 가진 slot 없는 작업은 managed 작업이다.

#905 는 `bool(authority_id)` 와 「slot 보유」 두 축이 같은 스냅샷에서 모순을 말하던 결함이었다
(S6-05 #812 가 slot 없는 작업을 legacy 로 보낸 뒤 명령 좌표 일부가 옛 축에 남았다). 문서 생성이
managed 하나가 되며(#1081 PR2) 그 두 축은 하나로 합쳐졌다: HWPX ∧ 작업 권위면 managed 이고,
slot 유무는 생성 경로를 가르지 않는다.

여기가 재는 것은 그 **합쳐진 좌표**다. 그러려면 형상이 실제로 slotless 여야 하므로 관리
Product 를 미주입으로 우회하지 않는다 — 실 `SlotConfigurationProduct` 를 코디네이터와 **같은
authority root** 로 배선해 projection 이 「구간 0개」를 스스로 말하게 한다.

slot 보유 관리 작업의 관리 분기는 `test_webapp_job_binding_review.py` 가 소유한다.
"""
from __future__ import annotations

import threading
from pathlib import Path

from _output_folder_pick import pick_output_folder

from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.viewmodel.tutorial_state import Milestone
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.external.template_change import TemplateChangeCoordinator
from hwpxfiller.webapp.workbench_observation_product import WorkbenchObservationProduct

from tests.test_webapp_job import _clock, _data_csv, _mount_all, _registry


def _slotless_controller(tmp_path: Path):
    """실 코디네이터 + 실 Slot Product + 작업대 Observation + 마일스톤 sink 를 한 root 로.

    템플릿은 누름틀 둘뿐인 평범한 HWPX(`_registry`)라 구조 구간이 없다 — 튜토리얼
    「계약체결안내」와 같은 형상이다.
    """
    reg = _registry(tmp_path)
    root = tmp_path / "authority"
    seen: list[str] = []

    def notify(milestone) -> bool:
        seen.append(str(milestone))
        return True

    ctrl = JobController(
        reg,
        lambda screen, snap: None,
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=TemplateChangeCoordinator(reg, root=root, clock=_clock()),
        slot_configuration=SlotConfigurationProduct(reg, root=root, clock=_clock()),
        seal_execution=SealExecutionPlanService(reg, root=root, clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
        tutorial=notify,
    )
    return ctrl, seen


def _seated(ctrl, tmp_path: Path) -> None:
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("set_all", {})


def test_seating_mints_the_authority_and_a_slotless_work_is_a_managed_work(
    tmp_path: Path,
) -> None:
    """착석이 권위 id 를 발급하고(#932 B5), 권위를 가진 slot 없는 작업은 managed 작업이다.

    종전엔 첫 생성이 권위를 발급했고(`_resolve_managed_template`), 발급 뒤에도 slot 이 없으면
    managed 가 아니었다. 그 두 사실은 함께 사라졌다(#1081 PR2) — 판정의 원천은 HWPX ∧ 권위다.
    projection 은 여전히 「구간 0개」를 스스로 말한다(미주입 우회가 아니다).
    """
    ctrl, _seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)

    assert ctrl.registry.load("공고서").authority_id.startswith("w-")
    view = ctrl.execution.slot_configuration.current_slot_configuration_view("공고서")
    projection = view.current_view.projection
    assert projection is not None and projection.slots == ()
    assert ctrl.refresh_panel()["managed_hwpx"] is True


def test_generation_needs_no_approval_detour(tmp_path: Path) -> None:
    """착석 뒤 곧바로 생성이 선다 — 사이에 승인이라는 관문이 없다(#957).

    종전 이 자리는 「광고된 미리보기가 실제로 열린다」(#905 ①)와 「승인이 성립한다」(②)를
    쟀다. 그 표면과 승인 축이 통째로 철거됐으므로 지금 재는 것은 **우회로의 부재**다:
    아무 확인 왕복 없이 문서가 난다.
    """
    ctrl, seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)
    seen.clear()

    result = ctrl.generate()

    assert result["ok"] is True and result["succeeded"] == 2, result
    assert len(list(out.glob("*.hwpx"))) == 2
    # 생성 완주 마일스톤은 그대로 선다(#941 동결 seam) — 사라진 것은 승인 사건뿐이다.
    assert str(Milestone.GENERATE) in seen


def test_folder_picked_later_is_where_the_documents_land(tmp_path: Path) -> None:
    """나중에 고른 저장 폴더가 배달 계획이 읽는 축에 들어간다 — 조용히 무시되지 않는다.

    옛 축에서는 발급 뒤의 지정이 delivery intent 로 들어가고 legacy 생성이 보는 ``out_dir`` 는
    도출 기본값 그대로였다. 사용자가 고른 폴더가 아닌 곳에 문서가 나는 것은 「조용히 틀리지
    않는다」의 정면 위반이라, 여기서는 **파일이 난 자리**로 잰다.
    """
    ctrl, _seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    pick_output_folder(ctrl, tmp_path / "first")
    ctrl.refresh_panel()  # 첫 폴더로 배달 준비가 한 번 선 뒤에 바꾼다

    picked = tmp_path / "picked"
    pick_output_folder(ctrl, picked)
    assert ctrl.runs.out_dir == str(picked)

    assert ctrl.generate()["ok"] is True

    assert len(list(picked.glob("*.hwpx"))) == 2
    assert not list((tmp_path / "first").glob("*.hwpx"))
