"""「문서 작업」의 작업 꾸러미 동사 — 내보내기·불러오기 확인·불러오기(#1188 WP-03·WP-04).

라이브러리 채널(``library``)이 액션 셋을 이 패널에 위임한다(:meth:`WorkPackagePanel.handlers`). 파일
경로는 웹이 실어 보낸다 — 웹은 직접 브리지 ``pick_work_package_path`` 로 고른 경로를 받고, 그 선택 창의
필터·기본 이름은 :func:`pick_package_path` 가 정한다(WP-05). 무엇이 들어오는지,
어떤 이름이 되는지, 그대로 내보내도 되는지는 전부 여기서 Python 이 판정하고 문장도 여기서 짓는다 —
웹은 판정하지 않고 보여 주기만 한다.

- ``export_work_package`` — 작업들(``names`` 가 없으면 이 작업 공간의 **모든 작업**)을 꾸러미 파일로
  쓴다. 템플릿을 읽지 못해 빠질 작업이나 데이터를 읽지 못해 확인 조건(데이터 계약) 없이 실릴 작업이
  있으면 쓰기 전에 두 사실을 한 확인으로 돌려주고, ``confirm`` 으로 다시 부를 때만 쓴다. 실을 작업이
  하나도 없으면 쓰지 않고 거절한다.
- ``inspect_work_package`` — 꾸러미를 읽어 들어올 것·이름·템플릿 처리를 보이고 계획 지문(``basis``)을
  준다. 아무것도 쓰지 않는다.
- ``import_work_package`` — 지문이 지금 계획과 같을 때만 전부 설치한다. 다르면 새 계획을 돌려준다.
  설치가 성사된 **뒤** 데이터 계약을 든 작업을 받는 쪽 등록 데이터에 자동 결속한다
  (:class:`~hwpxfiller.webapp.contract_binding.ImportAutobinder`, #1193). 결속은 설치의 전부 아니면
  전무 밖이다 — 등록 데이터 읽기(바깥 파일 I/O)를 계획 대조와 설치 사이에 끼우지 않고, 결속이 실패해도
  설치한 작업은 문서에 적힌 착지(「데이터 연결 필요」)로 남는다. 결과는 작업별 판정 이름으로 싣는다.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from ..application.jobs import load_job
from ..application.work_package_export import NothingToExport, WorkPackageDraft, draft_work_package
from ..domain.job import Job
from ..application.work_package_import import TEMPLATE_NEW, TEMPLATE_REUSE, ImportPlan, PlannedJob
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.preset_store import PresetRegistry
from ..external.template_files import TemplateFileStore
from ..external.work_package_install import StaleImportPlan, WorkPackageInstaller
from ..external.work_package_io import write_work_package
from ..external.work_package_sources import WorkPackageSources
from .contract_binding import AUTOBIND_BOUND, ImportAutobinder

#: 계약 없이 실릴 작업이 있을 때의 확인 문장(#1188 확정 문구).
EXPORT_WITHOUT_CONTRACT = (
    "데이터를 읽을 수 없어 확인 조건 없이 내보냅니다. 받는 쪽에서 연결을 직접 확정해야 합니다."
)
#: 템플릿을 읽지 못해 빠질 작업이 있을 때의 확인 문장 머리(#1188 후속 확정 문구) — 뒤에 `: 이름, 이름`.
EXPORT_SKIPPED = "템플릿을 읽을 수 없는 작업은 빠집니다"
#: 실을 작업이 하나도 없을 때의 거절 사유.
NOTHING_TO_EXPORT = "내보낼 수 있는 작업이 없습니다."
#: 모든 작업을 담는 꾸러미의 저장 창 기본 이름.
PACKAGE_DEFAULT_NAME = "작업 꾸러미"
#: 불러오기 확인의 데이터 안내(#1188 확정 문구, #1193 축소 — 자동 결속되면 연결 지시가 거짓이 된다).
DATA_NOTICE = "데이터는 들어 있지 않습니다."
#: 불러오기 뒤 할 일(#1188 확정 문구) — 들어온 작업은 목록이 보이므로 완료는 낭독하지 않는다.
#: 자동 결속(#1193)으로 모든 작업이 결속됐으면 할 일이 없으므로 싣지 않는다.
IMPORTED_NEXT_STEP = "데이터 연결이 필요합니다."
#: 템플릿 처리 표지(#1188 확정 문구).
TEMPLATE_LABELS = {TEMPLATE_NEW: "새로 추가", TEMPLATE_REUSE: "이미 있는 파일 사용"}
#: 꾸러미 파일의 확장자와 선택 창 필터(#1188 확정 기능 이름·확장자).
PACKAGE_EXTENSION = "narumi"
PACKAGE_FILTERS = [(f"작업 꾸러미 (*.{PACKAGE_EXTENSION})", f"*.{PACKAGE_EXTENSION}")]


def pick_package_path(
    action: str,
    *,
    open_file: Callable[[list[tuple[str, str]]], "str | None"],
    save_file: Callable[[str, list[tuple[str, str]], str], "str | None"],
) -> "str | None":
    """꾸러미 파일 선택 — ``export`` 는 저장 창(기본 이름 ``작업 꾸러미.narumi``), ``import`` 는 열기 창.

    선택 창 자체는 호스트의 단일 입구(``app._file_dialog``·``app._save_dialog``)가 주입된다 — 라이브
    실행의 대체가 이 자리를 비껴가지 않는다. ``None`` 은 취소다.
    """
    if action == "export":
        name = f"{PACKAGE_DEFAULT_NAME}.{PACKAGE_EXTENSION}"
        return save_file(name, PACKAGE_FILTERS, PACKAGE_EXTENSION)
    if action == "import":
        return open_file(PACKAGE_FILTERS)
    raise ValueError(f"꾸러미 파일 선택 action 은 export·import 중 하나여야 한다: {action!r}")


def _path_of(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path 는 비어 있지 않은 파일 경로여야 한다")
    return Path(raw)


def _names_of(raw: object) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(name, str) and name for name in raw):
        raise ValueError("names 는 작업 이름 목록이어야 한다")
    return list(dict.fromkeys(raw))


def skipped_line(names: Sequence[str]) -> str:
    """빠질 작업 줄 — 「템플릿을 읽을 수 없는 작업은 빠집니다: 이름, 이름」."""
    return f"{EXPORT_SKIPPED}: {', '.join(names)}"


def _export_confirm_text(draft: WorkPackageDraft) -> str:
    """빠질 작업과 계약 없이 실릴 작업 — 쓰기 전 확인 한 창에 함께 싣는 문장들(해당하는 것만)."""
    lines = []
    if draft.skipped:
        lines.append(skipped_line(draft.skipped))
    if draft.without_contract:
        lines.append(EXPORT_WITHOUT_CONTRACT)
    return "\n\n".join(lines)


def _nothing_to_export(exc: NothingToExport) -> str:
    """실을 작업이 없을 때의 거절 — 템플릿 때문에 빠진 작업이 있으면 그 이름까지 말한다."""
    lines = [f"작업 꾸러미를 만들 수 없습니다: {NOTHING_TO_EXPORT}"]
    if exc.skipped:
        lines.append(skipped_line(exc.skipped))
    return "\n".join(lines)


def _renamed_note(name: str) -> str:
    return f"‘{name}’ 이름으로 불러옵니다"


def _job_row(plan: ImportPlan, item: PlannedJob) -> dict:
    """확인 창의 작업 한 줄 — 그 작업이 쓰는 템플릿의 처리 표지까지 싣는다(웹은 짝을 맞추지 않는다)."""
    template = plan.template_for(item.source.template_digest)
    return {
        "name": item.source.name,
        "final_name": item.final_name,
        "note": _renamed_note(item.final_name) if item.renamed else "",
        "template": template.template.display_name,
        "template_label": TEMPLATE_LABELS[template.action],
        "has_contract": item.contract is not None,
    }


def plan_view(plan: ImportPlan) -> dict:
    """불러오기 확인 창의 재료 — 문장·표지까지 Python 이 짓는다."""
    return {
        "title": f"작업 {len(plan.jobs)}개를 불러옵니다",
        "jobs": [_job_row(plan, item) for item in plan.jobs],
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
        pool_registry: DatasetPoolRegistry,
    ) -> None:
        self._registry = registry
        self._autobind = ImportAutobinder(registry, pool_registry)
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

    def _jobs_to_export(self, p: dict) -> list[Job]:
        """``names`` 가 있으면 그 작업들, 없으면 이 작업 공간의 모든 작업(HWPX·TXT, 손상 파일 제외)."""
        if "names" in p:
            return [load_job(self._registry, name) for name in _names_of(p["names"])]
        return self._registry.list_jobs()

    def _do_export_work_package(self, p: dict) -> dict:
        path = _path_of(p["path"])
        try:
            draft = draft_work_package(
                self._jobs_to_export(p), self._sources,
                created_at=self._clock().isoformat(timespec="seconds"),
            )
            if (draft.skipped or draft.without_contract) and not p.get("confirm"):
                return {
                    "ok": True,
                    "needs_confirm": True,
                    "confirm_text": _export_confirm_text(draft),
                    "skipped": list(draft.skipped),
                    "without_contract": list(draft.without_contract),
                }
            write_work_package(path, draft.manifest, draft.templates)
        except NothingToExport as exc:
            return {"ok": False, "error": _nothing_to_export(exc), "skipped": list(exc.skipped)}
        except Exception as exc:  # noqa: BLE001 — 부재·손상·쓰기 실패: 사유와 함께 loud
            return {"ok": False, "error": f"작업 꾸러미를 만들 수 없습니다: {exc}"}
        return {
            "ok": True,
            "path": str(path),
            "jobs": len(draft.manifest.jobs),
            "templates": len(draft.manifest.templates),
            "skipped": list(draft.skipped),
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
        outcomes = self._autobind.bind_imported([item.final_name for item in plan.jobs])
        bound = [outcome.name for outcome in outcomes if outcome.status == AUTOBIND_BOUND]
        return {
            "ok": True,
            "imported": [item.final_name for item in plan.jobs],
            "bound": bound,
            "outcomes": [{"name": outcome.name, "status": outcome.status} for outcome in outcomes],
            "message": IMPORTED_NEXT_STEP if len(bound) < len(outcomes) else "",
        }


__all__ = [
    "DATA_NOTICE", "EXPORT_SKIPPED", "EXPORT_WITHOUT_CONTRACT", "IMPORTED_NEXT_STEP",
    "NOTHING_TO_EXPORT", "PACKAGE_FILTERS",
    "WorkPackagePanel", "pick_package_path", "plan_view", "skipped_line",
]
