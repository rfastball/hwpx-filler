"""작업 꾸러미 불러오기의 설치 — 계획 대조 뒤 전부 아니면 전무(#1188 WP-04).

:meth:`WorkPackageInstaller.inspect` 는 꾸러미를 읽어 계획(:func:`~hwpxfiller.application.
work_package_import.plan_import`)을 세운다. 아무것도 쓰지 않는다. :meth:`WorkPackageInstaller.commit`
은 꾸러미를 **다시 읽고** 계획을 다시 세워 사람이 본 지문(``basis``)과 대조한다 — 다르면
:class:`StaleImportPlan` 으로 아무것도 쓰지 않고 새 계획을 돌려준다.

설치 순서는 템플릿 파일 → 작업 → 선택 프리셋이다. 각 단계는 그 저장소의 잠금을 지난다(서식
폴더 가져오기 잠금, 작업 레지스트리의 쓰기 잠금·프로세스 소유권, 프리셋 레지스트리 잠금). 어느
단계든 실패하면 **이번 확정이 만든 것만** 거꾸로 걷는다 — 이미 있던 파일·작업·프리셋은 어느 갈래에서도
건드리지 않는다(덮어쓰기가 없으므로 되돌릴 이전 값도 없다). 걷기마저 실패하면 남은 항목을 사유에
덧붙여 시끄럽게 올린다(부분 설치를 성공으로 낮추지 않는다).

생성 잠금은 잡지 않는다: 불러오기는 새 이름의 작업과 새 파일만 만들고 진행 중인 런이 고정한 작업·
템플릿은 건드리지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..application.work_package_import import (
    TEMPLATE_REUSE,
    ImportPlan,
    imported_job,
    plan_import,
)
from ..domain.work_package import WorkPackageError
from .job_store import JobRegistry
from .preset_store import PresetRegistry
from .template_files import TemplateFileStore
from .work_package_io import WorkPackageContents, read_work_package
from .work_package_sources import ReceivingSide


class StaleImportPlan(Exception):
    """확인한 계획과 지금 계획이 다르다 — 아무것도 쓰지 않았다. ``plan`` 이 지금 계획이다."""

    def __init__(self, plan: ImportPlan) -> None:
        super().__init__("불러오기 계획이 확인 뒤 바뀌었습니다")
        self.plan = plan


@dataclass
class _Created:
    """이번 확정이 만든 것 — 실패하면 이것만 거꾸로 걷는다."""

    files: list[Path] = field(default_factory=list)
    jobs: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)


class WorkPackageInstaller:
    """꾸러미 확인·확정 — 저장소는 전부 주입이다(서식 폴더 루트는 콜러블: 재지정을 따른다)."""

    def __init__(
        self,
        registry: JobRegistry,
        *,
        template_files: TemplateFileStore,
        template_root: Callable[[], Path],
        presets: PresetRegistry,
    ) -> None:
        self._registry = registry
        self._files = template_files
        self._template_root = template_root
        self._presets = presets

    def inspect(self, path: "str | Path") -> tuple[WorkPackageContents, ImportPlan]:
        """꾸러미를 읽고 계획을 세운다 — 쓰기 0. 손상·변조는 :class:`WorkPackageError`."""
        contents = read_work_package(path)
        side = ReceivingSide(
            self._registry, self._presets, self._template_root(), contents.manifest.templates
        )
        return contents, plan_import(contents.manifest, side)

    def commit(self, path: "str | Path", basis: str) -> ImportPlan:
        """다시 읽고 다시 계획해 ``basis`` 와 같을 때만 설치한다(전부 아니면 전무)."""
        contents, plan = self.inspect(path)
        if plan.basis != basis:
            raise StaleImportPlan(plan)
        created = _Created()
        try:
            template_paths = self._install_templates(contents, plan, created)
            self._create_jobs(plan, template_paths, created)
            self._register_presets(plan, created)
        except Exception as exc:
            leftovers = self._roll_back(created)
            if leftovers:
                raise WorkPackageError(
                    f"{exc} (되돌리지 못한 항목: {', '.join(leftovers)})"
                ) from exc
            raise
        return plan

    # ── 설치 단계 ───────────────────────────────────────────────────────────
    def _install_templates(
        self, contents: WorkPackageContents, plan: ImportPlan, created: _Created
    ) -> dict[str, str]:
        paths: dict[str, str] = {}
        for item in plan.templates:
            digest = item.template.digest
            if item.action == TEMPLATE_REUSE:
                paths[digest] = item.target
                continue
            path = self._files.add_bytes(item.target, contents.templates[digest])
            created.files.append(path)
            paths[digest] = str(path)
        return paths

    def _create_jobs(
        self, plan: ImportPlan, template_paths: dict[str, str], created: _Created
    ) -> None:
        with self._registry.write_lock():
            for item in plan.jobs:
                if self._registry.exists(item.final_name):
                    raise WorkPackageError(f"같은 이름의 작업이 이미 있습니다: {item.final_name}")
                job = imported_job(item, template_paths[item.source.template_digest])
                self._registry.save(job)
                created.jobs.append(item.final_name)

    def _register_presets(self, plan: ImportPlan, created: _Created) -> None:
        for item in plan.presets:
            created.presets.append(self._presets.add(item.preset))

    # ── 되돌리기 ────────────────────────────────────────────────────────────
    def _roll_back(self, created: _Created) -> list[str]:
        """만든 것만 거꾸로 걷는다 — 걷지 못한 항목의 이름을 돌려준다."""
        leftovers: list[str] = []
        for key in reversed(created.presets):
            try:
                self._presets.delete(key)
            except OSError:
                leftovers.append(key)
        if created.jobs:  # 만든 작업이 없으면 잠금도 다시 잡지 않는다(소유권 거절이 원인일 수 있다)
            with self._registry.write_lock():
                for name in reversed(created.jobs):
                    try:
                        self._registry.delete(name)
                    except OSError:
                        leftovers.append(name)
        for path in reversed(created.files):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                leftovers.append(str(path))
        return leftovers


__all__ = ["StaleImportPlan", "WorkPackageInstaller"]
