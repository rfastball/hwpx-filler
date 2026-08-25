"""slotless HWPX 작업이 authority id 를 획득한 뒤의 명령 좌표 정렬(#905).

S6-05(#812)는 「관리 작업인가」를 `bool(authority_id)` → **slot 보유**로 좁혔지만 이관이
스냅샷 파생·실행 분기에서 멈췄다. 미리보기 열기·승인·저장 폴더 지정 셋은 옛 축에 남아,
같은 스냅샷이 모순을 말했다: `managed_hwpx=False` 라 프런트는 활성 「생성 값 미리보기」를
그리는데 그 버튼은 관리 분기로 들어가 거짓 사유로 거절했다.

여기가 재는 것은 그 **모순의 부재**다. 그러려면 형상이 실제로 slotless 여야 하므로 관리
Product 를 미주입으로 우회하지 않는다 — 실 `SlotConfigurationProduct` 를 코디네이터와 **같은
authority root** 로 배선해 projection 이 「구간 0개」를 스스로 말하게 한다. 술어가 미주입으로
False 인 것과 slot 이 없어서 False 인 것은 다른 사실이고, 결함이 산 자리는 후자다.

slot 보유 관리 작업의 관리 분기는 `test_webapp_job_binding_review.py` 가 소유한다.
"""
from __future__ import annotations

import threading
from pathlib import Path

from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.gui.tutorial_state import Milestone
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator
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
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=TemplateChangeCoordinator(reg, root=root, clock=_clock()),
        slot_configuration=SlotConfigurationProduct(reg, root=root, clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
        tutorial=notify,
    )
    return ctrl, seen


def _seated(ctrl, tmp_path: Path) -> None:
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("set_all", {})


def test_first_generate_mints_the_authority_id_of_a_slotless_work(tmp_path: Path) -> None:
    """mint 고리 — 「변경사항 확인」을 누른 적 없어도 **첫 생성**이 권위 id 를 발급한다.

    좌표는 `screen_job._resolve_managed_template` → `TemplateChangeCoordinator.
    resolve_generation_template_for_seated_context` → `_work_id_for(create=True)` →
    `application.jobs.ensure_job_authority_id` 다. 발급은 생성 **성사 전**에 일어나므로
    (여기서는 빈 값 게이트가 그 뒤에 닫는다) 사용자는 한 번도 성공하지 않고도 발급된
    작업을 손에 쥔다 — #905 가 튜토리얼 전용이 아닌 이유가 이것이다.
    """
    ctrl, _seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    assert ctrl.registry.load("공고서").authority_id == ""

    rejected = ctrl.generate()

    assert rejected["ok"] is False and "빈 값" in rejected["error"]
    assert ctrl.registry.load("공고서").authority_id.startswith("w-")
    # 발급됐어도 관리 작업이 아니다 — 판정의 원천은 slot 보유이고, projection 이 그 사실을
    # 스스로 말한다(미주입 우회가 아니라 「구간 0개」).
    view = ctrl._slot_configuration.current_slot_configuration_view("공고서")
    projection = view.current_view.projection
    assert projection is not None and projection.slots == ()
    assert ctrl.snapshot()["managed_hwpx"] is False


def test_advertised_preview_actually_opens_after_the_mint(tmp_path: Path) -> None:
    """한 스냅샷이 두 말을 하지 않는다 — 활성 버튼과 열림이 함께 성립한다(#905 ①)."""
    ctrl, _seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.generate()  # mint
    assert ctrl.registry.load("공고서").authority_id != ""

    snap = ctrl.snapshot()
    assert snap["managed_hwpx"] is False
    assert snap["preview"]["can_open"] is True

    assert ctrl.dispatch("preview_open", {}) == {"ok": True}
    assert ctrl.snapshot()["preview"]["open"] is True


def test_approval_stands_and_blank_reapproval_reaches_the_milestone(tmp_path: Path) -> None:
    """승인 성립(②) + 빈 값 재승인이 T13 까지 닿는다(③) — #895 여정이 멎던 자리."""
    ctrl, seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.generate()  # mint
    seen.clear()

    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_approve", {})
    ctrl.dispatch("preview_close", {})
    assert str(Milestone.APPROVE_VALUES) in seen
    # 승인만으로는 서지 않는다 — T13 은 「빈 값 포함 승인 **+** 생성 완료」다.
    assert str(Milestone.APPROVE_WITH_BLANKS) not in seen

    result = ctrl.generate()

    assert result["ok"] is True and result["succeeded"] == 2
    assert str(Milestone.APPROVE_WITH_BLANKS) in seen
    assert len(list(out.glob("*.hwpx"))) == 2


def test_folder_picked_after_the_mint_is_where_the_documents_land(tmp_path: Path) -> None:
    """저장 폴더 지정이 legacy 실행이 읽는 축에 들어간다 — 조용히 무시되지 않는다.

    옛 축에서는 발급 뒤의 지정이 delivery intent(관리 면이 읽는 값)로 들어가고 legacy 생성이
    보는 ``out_dir`` 는 도출 기본값 그대로였다. 사용자가 고른 폴더가 아닌 곳에 문서가 나는
    것은 「조용히 틀리지 않는다」의 정면 위반이라, 여기서는 **파일이 난 자리**로 잰다.
    """
    ctrl, _seen = _slotless_controller(tmp_path)
    _seated(ctrl, tmp_path)
    ctrl.set_output_folder(str(tmp_path / "first"))
    ctrl.generate()  # mint

    picked = tmp_path / "picked"
    ctrl.set_output_folder(str(picked))
    assert ctrl.out_dir == str(picked)
    assert ctrl._run_delivery_intent is None

    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_approve", {})
    ctrl.dispatch("preview_close", {})
    assert ctrl.generate()["ok"] is True

    assert len(list(picked.glob("*.hwpx"))) == 2
    assert not list((tmp_path / "first").glob("*.hwpx"))
