"""「문서 작업」의 작업 꾸러미 동사 — 내보내기·불러오기 확인·불러오기(#1188 WP-03·WP-04).

라이브러리 채널(``library``)이 액션 셋을 이 패널에 위임한다(:meth:`WorkPackagePanel.handlers`). 파일
경로는 웹이 실어 보낸다 — 파일 선택 창·메뉴·끌어 놓기는 화면 슬라이스(WP-05)의 몫이다. 무엇이 들어오는지,
어떤 이름이 되는지, 그대로 내보내도 되는지는 전부 여기서 Python 이 판정하고 문장도 여기서 짓는다 —
웹은 판정하지 않고 보여 주기만 한다.

- ``export_work_package`` — 고른 작업들을 꾸러미 파일로 쓴다. 데이터를 읽지 못해 확인 조건(데이터
  계약) 없이 실릴 작업이 있으면 쓰기 전에 확인을 돌려주고, ``confirm`` 으로 다시 부를 때만 쓴다.
- ``inspect_work_package`` — 꾸러미를 읽어 들어올 것·이름·템플릿 처리를 보이고 계획 지문(``basis``)을
  준다. 아무것도 쓰지 않는다.
- ``import_work_package`` — 지문이 지금 계획과 같을 때만 전부 설치한다. 다르면 새 계획을 돌려준다.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..application.jobs import load_job
from ..application.work_package_export import draft_work_package
from ..application.work_package_import import TEMPLATE_NEW, TEMPLATE_REUSE, ImportPlan
from ..external.job_store import JobRegistry
from ..external.preset_store import PresetRegistry
from ..external.template_files import TemplateFileStore
from ..external.work_package_install import StaleImportPlan, WorkPackageInstaller
from ..external.work_package_io import write_work_package
from ..external.work_package_sources import WorkPackageSources

#: 계약 없이 실릴 작업이 있을 때의 확인 문장(#1188 확정 문구).
EXPORT_WITHOUT_CONTRACT = (
    "데이터를 읽을 수 없어 확인 조건 없이 내보냅니다. 받는 쪽에서 연결을 직접 확정해야 합니다."
)
#: 불러오기 확인의 데이터 안내(#1188 확정 문구).
DATA_NOTICE = "데이터는 들어 있지 않습니다. 불러온 뒤 작업마다 데이터를 연결하세요."
#: 템플릿 처리 표지(#1188 확정 문구).
TEMPLATE_LABELS = {TEMPLATE_NEW: "새로 추가", TEMPLATE_REUSE: "이미 있는 파일 사용"}


def _path_of(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path 는 비어 있지 않은 파일 경로여야 한다")
    return Path(raw)


def _names_of(raw: object) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(name, str) and name for name in raw):
        raise ValueError("names 는 작업 이름 목록이어야 한다")
    return list(dict.fromkeys(raw))


def _renamed_note(name: str) -> str:
    return f"‘{name}’로 불러옵니다"


def plan_view(plan: ImportPlan) -> dict:
    """불러오기 확인 창의 재료 — 문장·표지까지 Python 이 짓는다."""
    return {
        "title": f"작업 {len(plan.jobs)}개를 불러옵니다",
        "jobs": [
            {
                "name": item.source.name,
                "final_name": item.final_name,
                "note": _renamed_note(item.final_name) if item.renamed else "",
                "template": plan.template_for(item.source.template_digest).template.display_name,
                "has_contract": item.contract is not None,
            }
            for item in plan.jobs
        ],
        "templates": [
            {
                "display_name": item.template.display_name,
                "action": item.action,
                "label": TEMPLATE_LABELS[item.action],
                "target": item.target,
            }
            for item in plan.templates
        ],
        "presets": [
            {
                "name": item.original_name,
                "final_name": item.preset.name,
                "job": item.job_name,
                "note": _renamed_note(item.preset.name) if item.renamed else "",
            }
            for item in plan.presets
        ],
        "data_notice": DATA_NOTICE,
    }


class WorkPackagePanel:
    """작업 꾸러미 세 동사 — 저장소는 주입이고 서식 폴더 루트는 콜러블이다(재지정을 따른다)."""

    def __init__(
        self,
        registry: JobRegistry,
        *,
        template_files: TemplateFileStore,
        template_root: Callable[[], Path],
        presets: PresetRegistry,
        authority_root: Path,
        clock: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._sources = WorkPackageSources(registry, authority_root=authority_root)
        self._installer = WorkPackageInstaller(
            registry, template_files=template_files, template_root=template_root, presets=presets,
        )
        self._clock = clock

    def handlers(self) -> dict[str, Callable[[dict], dict]]:
        """액션 이름 → 처리기. 이름은 ``_do_<액션>`` 이다(배선 게이트가 컨트롤러와 함께 센다)."""
        return {
            name.removeprefix("_do_"): getattr(self, name)
            for name in vars(type(self)) if name.startswith("_do_")
        }

    def _do_export_work_package(self, p: dict) -> dict:
        names, path = _names_of(p["names"]), _path_of(p["path"])
        try:
            jobs = [load_job(self._registry, name) for name in names]
            draft = draft_work_package(
                jobs, self._sources, created_at=self._clock().isoformat(timespec="seconds")
            )
            if draft.without_contract and not p.get("confirm"):
                return {
                    "ok": True,
                    "needs_confirm": True,
                    "confirm_text": EXPORT_WITHOUT_CONTRACT,
                    "without_contract": list(draft.without_contract),
                }
            write_work_package(path, draft.manifest, draft.templates)
        except Exception as exc:  # noqa: BLE001 — 부재·손상·쓰기 실패: 사유와 함께 loud
            return {"ok": False, "error": f"작업 꾸러미를 만들 수 없습니다: {exc}"}
        return {
            "ok": True,
            "path": str(path),
            "jobs": len(draft.manifest.jobs),
            "templates": len(draft.manifest.templates),
            "without_contract": list(draft.without_contract),
        }

    def _do_inspect_work_package(self, p: dict) -> dict:
        path = _path_of(p["path"])
        try:
            _contents, plan = self._installer.inspect(path)
        except Exception as exc:  # noqa: BLE001 — 손상·변조·읽기 실패: 사유와 함께 loud
            return {"ok": False, "error": f"작업 꾸러미를 읽을 수 없습니다: {exc}"}
        return {"ok": True, "basis": plan.basis, "view": plan_view(plan)}

    def _do_import_work_package(self, p: dict) -> dict:
        path = _path_of(p["path"])
        if not isinstance(p["basis"], str):
            raise ValueError("basis 는 확인이 돌려준 문자열이어야 한다")
        try:
            plan = self._installer.commit(path, p["basis"])
        except StaleImportPlan as stale:
            return {
                "ok": False, "stale": True,
                "basis": stale.plan.basis, "view": plan_view(stale.plan),
            }
        except Exception as exc:  # noqa: BLE001 — 설치 실패는 되돌린 뒤 사유와 함께 loud
            return {"ok": False, "error": f"작업 꾸러미를 읽을 수 없습니다: {exc}"}
        return {
            "ok": True,
            "imported": [item.final_name for item in plan.jobs],
            "message": f"작업 {len(plan.jobs)}개를 불러왔습니다. 데이터 연결이 필요합니다.",
        }


__all__ = ["DATA_NOTICE", "EXPORT_WITHOUT_CONTRACT", "WorkPackagePanel", "plan_view"]
