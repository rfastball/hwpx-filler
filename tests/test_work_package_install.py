"""작업 꾸러미 설치·읽기의 실패 분기(#1188 WP-03·WP-04) — 저장소를 직접 조립해 실패를 주입한다.

제품 조립 왕복은 ``test_webapp_work_package.py`` 가 진다. 여기는 그 왕복이 닿지 않는 갈래를
실제 저장소(작업·프리셋 레지스트리, 서식 폴더 파일 저장소)와 주입한 실패로 고정한다:
되돌리기가 이번 확정이 만든 것만 걷는지, 걷지 못한 항목이 사유에 실리는지, 잠금 안 같은
이름 재확인, 보내는 쪽 템플릿·선택·데이터 읽기의 거절·부재 갈래, 서식 폴더 스캔의 제외 갈래.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.application.work_package_export import ExportDataUnavailable
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.preset import SelectionPreset
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
from hwpxfiller.domain.work_package import (
    PackagedJob,
    PackagedTemplate,
    WorkPackageError,
    WorkPackageManifest,
)
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.preset_store import PresetRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.work_package_install import WorkPackageInstaller
from hwpxfiller.external.work_package_io import write_work_package
from hwpxfiller.external.work_package_sources import WorkPackageSources, existing_templates

NOW = "2026-10-15T09:00:00"
BLOB = "공고명: {{공고명}}\n".encode("utf-8")
DIGEST = hashlib.sha256(BLOB).hexdigest()
SELECTION = SlotSelectionSet((SlotSelection(slot_id="s1", selected_option_ids=("o1",)),))


def _job(name: str) -> PackagedJob:
    return PackagedJob(
        name=name, media="txt", template_digest=DIGEST,
        mapping=MappingProfile(mappings=[FieldMapping("공고명", "공고명")]),
        filename_pattern="공고-{{seq:001}}",
        selection_presets=(
            SelectionPreset(name=name, selection_set=SELECTION, provenance={}, created_at=NOW),
        ),
    )


@pytest.fixture
def home(tmp_path: Path):
    """꾸러미(작업 둘·각자 프리셋·TXT 템플릿 하나)와 빈 받는 쪽 저장소."""
    package = tmp_path / "보낸.narumi"
    write_work_package(
        package,
        WorkPackageManifest(
            created_at=NOW,
            templates=(PackagedTemplate(DIGEST, "txt", "공고.txt", len(BLOB)),),
            jobs=(_job("가"), _job("나")),
        ),
        {DIGEST: BLOB},
    )
    root = tmp_path / "templates"
    root.mkdir()
    jobs = JobRegistry(tmp_path / "jobs", template_root=lambda: root)
    presets = PresetRegistry(tmp_path / "presets")
    installer = WorkPackageInstaller(
        jobs, template_files=TemplateFileStore(lambda: root, TextTemplateRegistry(root)),
        template_root=lambda: root, presets=presets,
    )
    return SimpleNamespace(package=package, root=root, jobs=jobs, presets=presets,
                           installer=installer)


def _state(home) -> tuple:
    return (
        sorted(p.name for p in home.root.iterdir()),
        sorted(home.jobs.names()),
        sorted(preset.name for _key, preset in home.presets.list_entries()),
    )


def _fail_second_preset(monkeypatch) -> None:
    real_add = PresetRegistry.add
    calls = {"n": 0}

    def add(self, preset):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("같은 이름의 프리셋이 이미 있습니다: 나")
        return real_add(self, preset)

    monkeypatch.setattr(PresetRegistry, "add", add)


def test_late_failure_walks_back_presets_jobs_and_files_this_commit_made(home, monkeypatch):
    _contents, plan = home.installer.inspect(home.package)
    _fail_second_preset(monkeypatch)

    with pytest.raises(ValueError, match="같은 이름의 프리셋"):
        home.installer.commit(home.package, plan.basis)

    assert _state(home) == ([], [], [])


def test_items_that_cannot_be_walked_back_are_named_in_the_failure(home, monkeypatch):
    _contents, plan = home.installer.inspect(home.package)
    _fail_second_preset(monkeypatch)

    def refuse(*_args, **_kwargs):
        raise OSError("잠김")

    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "공고.txt":  # 이번 확정이 들인 템플릿만 지울 수 없다(다른 임시 파일은 그대로)
            raise OSError("사용 중")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(PresetRegistry, "delete", refuse)
    monkeypatch.setattr(JobRegistry, "delete", refuse)
    monkeypatch.setattr(Path, "unlink", unlink)

    with pytest.raises(WorkPackageError) as caught:
        home.installer.commit(home.package, plan.basis)

    message = str(caught.value)
    assert message.startswith("같은 이름의 프리셋이 이미 있습니다: 나 (되돌리지 못한 항목: ")
    preset_key = next(key for key, preset in home.presets.list_entries() if preset.name == "가")
    for leftover in (preset_key, "나", "가", str(home.root / "공고.txt")):
        assert leftover in message, "남은 것을 숨기지 않는다"


def test_a_job_name_taken_after_planning_is_refused_inside_the_lock(home, monkeypatch):
    """계획과 설치 사이에 같은 이름이 생기면 덮지 않고 거절한다 — 남의 작업은 건드리지 않는다."""
    _contents, plan = home.installer.inspect(home.package)
    real_install = WorkPackageInstaller._install_templates

    def racing(self, *args):
        paths = real_install(self, *args)
        home.jobs.save(Job(name="가", template_path="C:/다른/것.txt"))
        return paths

    monkeypatch.setattr(WorkPackageInstaller, "_install_templates", racing)
    with pytest.raises(WorkPackageError, match="같은 이름의 작업이 이미 있습니다: 가"):
        home.installer.commit(home.package, plan.basis)

    assert _state(home) == ([], ["가"], [])
    assert home.jobs.load("가").template_path == "C:/다른/것.txt"


# ── 보내는 쪽 읽기 ─────────────────────────────────────────────────────────────

@pytest.fixture
def sources(tmp_path: Path) -> WorkPackageSources:
    registry = JobRegistry(tmp_path / "jobs")
    return WorkPackageSources(registry, authority_root=tmp_path / "authority")


def test_job_without_applied_history_exports_its_linked_template_file(sources, tmp_path):
    template = tmp_path / "공고.txt"
    template.write_bytes(BLOB)
    assert sources.template_bytes(Job(name="가", template_path=str(template))) == BLOB
    # 권위 id 만 있고 Work 상태가 없는 작업도 첫 사용 전이라 연결 파일이 근거다.
    orphan = Job(name="나", template_path=str(template), authority_id="w-missing")
    assert sources.template_bytes(orphan) == BLOB


def test_missing_or_unreadable_template_refuses_the_export_with_the_job_named(sources, tmp_path):
    with pytest.raises(WorkPackageError, match="'가'에 연결된 템플릿이 없습니다"):
        sources.template_bytes(Job(name="가"))
    with pytest.raises(WorkPackageError, match="'나'의 템플릿 파일을 읽을 수 없습니다"):
        sources.template_bytes(Job(name="나", template_path=str(tmp_path / "없음.txt")))


def test_unbound_job_has_no_data_to_profile(sources):
    with pytest.raises(ExportDataUnavailable):
        sources.records(Job(name="가", template_path="C:/공고.txt"))


class _Store:
    """``exists``·``load`` 만 쓰는 저장소 대역 — 선택 읽기의 갈래만 본다."""

    def __init__(self, value) -> None:
        self.value = value

    def exists(self, _work_id: str) -> bool:
        return True

    def load(self, _work_id: str):
        return self.value


def _config(application_id: str, selections: SlotSelectionSet) -> SimpleNamespace:
    return SimpleNamespace(base_template_application_id=application_id, selections=selections)


@pytest.mark.parametrize(
    ("configs", "expected"),
    [
        ([_config("다른 적용", SELECTION)], None),
        ([_config("app-1", SlotSelectionSet(()))], None),
        ([_config("다른 적용", SlotSelectionSet(())), _config("app-1", SELECTION)], SELECTION),
    ],
)
def test_only_the_current_applications_declared_selection_travels(sources, configs, expected):
    sources._works = _Store(SimpleNamespace(work=SimpleNamespace(
        current_template_application_id="app-1")))
    sources._configs = _Store(SimpleNamespace(configurations=SimpleNamespace(
        configurations=configs)))
    assert sources.declared_selection(Job(name="가", authority_id="w-1")) == expected


# ── 서식 폴더 스캔 ──────────────────────────────────────────────────────────────

def test_scan_hashes_only_same_media_same_size_readable_files(tmp_path, monkeypatch):
    root = tmp_path / "templates"
    (root / "하위").mkdir(parents=True)
    (root / "같음.txt").write_bytes(BLOB)
    (root / "하위" / "또같음.txt").write_bytes(BLOB)  # 같은 bytes 둘이면 경로 순서의 첫 파일
    (root / "같은크기.hwpx").write_bytes(BLOB)  # 형식이 다르다
    (root / "다른크기.txt").write_bytes(BLOB + b"!")
    (root / "메모.md").write_bytes(BLOB)
    (root / "폴더.txt").mkdir()
    (root / "잠김.txt").write_bytes(BLOB)
    real_read = Path.read_bytes

    def read(self: Path) -> bytes:
        if self.name == "잠김.txt":
            raise PermissionError("잠김")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    template = PackagedTemplate(DIGEST, "txt", "공고.txt", len(BLOB))

    assert existing_templates(root, [template]) == {DIGEST: str(root / "같음.txt")}
    assert existing_templates(tmp_path / "없는폴더", [template]) == {}
