"""Windows에 등록된 계약목록 업무 자료의 기본 시트를 기존 데이터 풀에 연결한다."""
from __future__ import annotations

from ..data.pclm import registered_workfile_sheets
from ..domain.dataset_reference import DatasetReference, pclm_identity
from ..host.pclm_registration import registered_workfile


def registered_data_source(pool_registry) -> dict | None:
    located = registered_workfile()
    if located is None:
        return None
    path, dataset_id = located
    sheets = registered_workfile_sheets(path, dataset_id)
    found = pool_registry.find_identity_raw(pclm_identity(path, sheets[0]))
    if found is None:
        key = pool_registry.add(DatasetReference(
            name="계약 목록", kind="pclm",
            opts={"db": path, "view": sheets[0], "sheets": sheets},
        ))
    else:
        key, item = found
        if item.status != "active":
            return None
    return {"source": "pool", "path": path, "sheet": sheets[0],
            "pool_key": key, "header_row": 0}


def restore_data_session(controller, failed_text: str) -> None:
    """자동 발견과 마지막 마운트 복원을 부팅 한 번만 조정한다."""
    if controller._boot_data_restored:
        return
    controller._boot_data_restored = True
    descriptor = controller._remembered_data_source
    discovery_refusal = ""
    if controller._registered_data is not None:
        try:
            registered = controller._registered_data()
            descriptor = descriptor or registered
        except Exception as exc:  # noqa: BLE001 — 외부 설정/자료 실패를 기존 경보로 전달
            discovery_refusal = failed_text.format(reason=exc)
            controller.data.set_notice(discovery_refusal)
    if not descriptor or controller.data.source_kind:
        return  # 기억 없음(기존 settings.json) 또는 이미 마운트됨 = 기존 부팅 그대로
    controller._boot_restore_in_progress = True
    try:
        refusal = controller._mount_remembered_data(descriptor)
    finally:
        controller._boot_restore_in_progress = False
    refusal = "\n".join(message for message in (discovery_refusal, refusal) if message)
    if refusal:
        controller.data.notice_text = refusal
        controller.data.notice_level = "warn"

