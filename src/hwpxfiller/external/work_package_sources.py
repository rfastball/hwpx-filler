"""작업 꾸러미가 읽는 저장소 사실 — 보내는 쪽의 템플릿·선택·데이터, 받는 쪽의 이름·서식 폴더(#1188).

내보내기(:class:`WorkPackageSources`)는 :class:`~hwpxfiller.application.work_package_export.ExportSourcePort`
를, 불러오기(:class:`ReceivingSide`)는 :class:`~hwpxfiller.application.work_package_import.ReceivingSidePort`
를 구현한다. 둘 다 **읽기만** 한다 — 권위 id 를 발급하거나 구성을 물질화하는 경로는 지나지 않는다.

**템플릿 bytes 의 출처**: 적용 이력(Work)이 있는 작업은 생성이 실제로 쓰는 적용 판본(Candidate blob,
:meth:`~hwpxfiller.external.applied_template_asset.AppliedTemplateAsset.current_bytes`)을 낸다. 앱 안
편집 파일은 적용 전 변경을 들 수 있어 쓰지 않는다. 적용 이력이 아직 없는 작업은 연결된 템플릿 파일
bytes 를 낸다 — 그 작업의 첫 사용(초기 등록)이 캡처할 bytes 가 바로 그것이라 생성 근거와 같다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from ..application.work_package_export import ExportDataUnavailable, ExportTemplateUnavailable
from ..application.work_slot_configuration import has_declared_selection
from ..data.factory import source_for_binding
from ..domain.job import Job, data_binding_of, has_data_binding
from ..domain.slot_selection import SlotSelectionSet
from ..domain.work_package import TEMPLATE_MEDIA, PackagedTemplate
from .applied_template_asset import AppliedTemplateAsset
from .candidate_store import CandidateObjectStore
from .job_store import JobRegistry
from .preset_store import PresetRegistry
from .qualification_store import QualificationObjectStore
from .work_configuration_store import WorkSlotConfigurationStore
from .work_template_store import AtomicWorkTemplateStateStore


class WorkPackageSources:
    """보내는 쪽 사실 — 템플릿 권위 루트의 저장소를 **읽기 전용**으로 연다."""

    def __init__(self, registry: JobRegistry, *, authority_root: Path) -> None:
        root = Path(authority_root)
        self._works = AtomicWorkTemplateStateStore(root / "works")
        self._configs = WorkSlotConfigurationStore(root / "slot_configs")
        self._applied = AppliedTemplateAsset(
            root, registry, self._works,
            CandidateObjectStore(root / "candidates"),
            QualificationObjectStore(root / "qualification"),
        )

    def template_bytes(self, job: Job) -> bytes:
        """읽지 못하는 갈래(적용 판본 손상 포함)는 전부 :class:`ExportTemplateUnavailable` 로 모은다.

        한 작업의 템플릿이 꾸러미 전체를 깨지 않게 그 작업만 빠지는 근거다 — 빠짐은 쓰기 전에 사람에게 묻는다.
        """
        try:
            applied = self._applied.current_bytes(job)
        except Exception as exc:  # noqa: BLE001 — 적용 판본 손상·형식 불일치도 「읽을 수 없음」이다
            raise ExportTemplateUnavailable(
                f"작업 {job.name!r}의 적용 템플릿을 읽을 수 없습니다: {exc}"
            ) from exc
        if applied is not None:
            return applied
        if not job.template_path:
            raise ExportTemplateUnavailable(f"작업 {job.name!r}에 연결된 템플릿이 없습니다")
        try:
            return Path(job.template_path).read_bytes()
        except OSError as exc:
            raise ExportTemplateUnavailable(
                f"작업 {job.name!r}의 템플릿 파일을 읽을 수 없습니다: {exc}"
            ) from exc

    def declared_selection(self, job: Job) -> "SlotSelectionSet | None":
        work_id = job.authority_id
        if not work_id or not self._works.exists(work_id) or not self._configs.exists(work_id):
            return None
        application_id = self._works.load(work_id).work.current_template_application_id
        for config in self._configs.load(work_id).configurations.configurations:
            if config.base_template_application_id == application_id:
                return config.selections if has_declared_selection(config) else None
        return None

    def records(self, job: Job) -> "Sequence[Mapping[str, object]]":
        if not has_data_binding(job):
            raise ExportDataUnavailable(job.name)
        path, sheet, header_row, kind = data_binding_of(job)
        try:
            return source_for_binding(
                {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}
            ).records()
        except Exception as exc:  # noqa: BLE001 — 부재·손상·권한·시트 없음: 전부 「읽을 수 없음」
            raise ExportDataUnavailable(job.name) from exc


def _file_fact(path: Path, wanted: "dict[tuple[str, int], set[str]]") -> "str | None":
    """후보 파일의 sha256 — 형식·크기가 꾸러미의 어느 템플릿과도 안 맞거나 못 읽으면 ``None``.

    읽을 수 없는 파일은 재사용 후보가 아니다(그 템플릿은 새 파일로 들인다 — 잃는 것이 없다).
    """
    media = path.suffix.lower().removeprefix(".")
    if media not in TEMPLATE_MEDIA:
        return None
    try:
        if not path.is_file() or (media, path.stat().st_size) not in wanted:
            return None
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def existing_templates(root: Path, templates: Sequence[PackagedTemplate]) -> dict[str, str]:
    """서식 폴더(하위 포함)에서 꾸러미 템플릿과 같은 bytes 인 파일 — ``{digest: 경로}``.

    형식(확장자)과 크기가 맞는 파일만 해시한다. 같은 bytes 가 여럿이면 경로 순서의 첫 파일이다.
    """
    wanted: dict[tuple[str, int], set[str]] = {}
    for item in templates:
        wanted.setdefault((item.media, item.size), set()).add(item.digest)
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        digest = _file_fact(path, wanted)
        if digest is not None and digest not in found and any(
            digest in digests for digests in wanted.values()
        ):
            found[digest] = str(path)
    return found


class ReceivingSide:
    """받는 쪽 사실의 스냅샷 — 서식 폴더 해시는 만들 때 한 번만 잰다."""

    def __init__(
        self,
        registry: JobRegistry,
        presets: PresetRegistry,
        template_root: Path,
        templates: Sequence[PackagedTemplate],
    ) -> None:
        self._registry = registry
        self._presets = presets
        self._root = Path(template_root)
        self._existing = existing_templates(self._root, templates)

    def job_taken(self, name: str) -> bool:
        return self._registry.exists(name)

    def job_key(self, name: str) -> str:
        return self._registry.path_for(name).name.casefold()

    def preset_taken(self, name: str) -> bool:
        return self._presets.find_name(name) is not None

    def file_taken(self, file_name: str) -> bool:
        return (self._root / file_name).exists()

    def existing_template(self, template: PackagedTemplate) -> "str | None":
        return self._existing.get(template.digest)


__all__ = ["ReceivingSide", "WorkPackageSources", "existing_templates"]
