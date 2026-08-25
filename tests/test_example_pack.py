"""동봉 예제 세트 설치의 헤드리스 계약(#891 · 설계 정본 ONBOARDING_TUTORIAL.md §1 D1·D4·§4.1~4.2).

이 슬라이스의 지배 위험은 **누르기 전 홈 쓰기**다: 최초 부팅 자동 설치가 무단 쓰기라 기각되고
「빈 상태 제안 + 명시 버튼」이 결정됐으므로(D1), 확정을 지나지 않은 어떤 경로도 홈을 건드리면
안 된다. 그래서 여기 첫 두 테스트가 「설치 전 홈 불가침」과 「확인 왕복」이다.

나머지는 설치가 **성립시키는 것 전수**(템플릿 5·그룹 지정·데이터 고정 2·manifest)와, D4 가
되돌리기를 재설치에 맡긴 대가로 반드시 성립해야 하는 **재설치 = 같은 상태 복원**이다.
자산 자체의 계약(허구화·필드 수)은 ``tests/test_onboarding_assets.py`` 소관이라 겹치지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hwpxfiller.external import example_pack, settings
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.host.locations import default_example_data_dir, home_dir
from hwpxfiller.webapp.screen_template import TemplateController

ALL_ASSETS = example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS + example_pack.DATA_ASSETS


def _controller(tmp_path):
    """tpl 컨트롤러 1대 — 라이브러리 루트는 tmp, 홈(설정·데이터 자리)은 conftest 격리분."""
    lib = tmp_path / "lib"
    lib.mkdir()
    txt_dir = tmp_path / "txt"
    txt_dir.mkdir()
    registry = TextTemplateRegistry(txt_dir)
    pushes: list = []
    ctrl = TemplateController(
        registry,
        lambda screen, snap: pushes.append((screen, snap)),
        file_store=TemplateFileStore(
            lib, registry, clock=lambda: 2_000_000_000.0, new_id=lambda: "fixed-id"
        ),
        library_dir=lib,
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
    )
    return ctrl, lib, txt_dir, pushes


def _installed_names(lib: Path, txt_dir: Path) -> "set[str]":
    return {p.name for p in lib.iterdir()} | {p.name for p in txt_dir.iterdir()}


def _group_of(snapshot: dict, media: str, name: str) -> str:
    for section in snapshot[media]["sections"]:
        for item in section["items"]:
            if Path(item["path"]).name == name:
                return section["group"]
    raise AssertionError(f"{media} 목록에 '{name}' 이 없습니다")


# ---------------------------------------------------------------- 누르기 전 홈 불가침
def test_home_is_untouched_before_the_install_action_runs(tmp_path):
    """컨트롤러 조립·스냅샷만으로는 홈에 아무것도 서지 않는다(D1 — 무단 쓰기 금지).

    스냅샷은 진입점 라벨을 실어야 하므로 설정을 **읽는다**. 읽기가 쓰기로 새면 첫 부팅이
    곧 설치가 되므로, 예제 데이터 자리·manifest 부재를 여기서 못박는다.
    """
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert snap["examples"] == {
        "installed": False,
        "label": "예제로 시작하기…",
        "hint": f"동봉 예제 {len(ALL_ASSETS)}건을 라이브러리에 넣고 데이터를 고정합니다.",
    }
    assert not default_example_data_dir().exists()
    assert settings.load_tutorial_manifest() is None
    assert _installed_names(lib, txt_dir) == set()
    assert DatasetPoolRegistry(tmp_path / "datasets").list_items() == []


def test_first_call_restates_and_writes_nothing(tmp_path):
    """1차 호출은 **재진술만** — 무엇을 몇 건 어디에 쓰는지 말하고 홈은 그대로다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    result = ctrl.dispatch("install_examples", {})
    assert result["needs_confirm"] is True
    text = result["confirm_text"]
    assert f"HWPX 서식 {len(example_pack.HWPX_ASSETS)}건" in text
    assert f"TXT 기안 {len(example_pack.TXT_ASSETS)}건" in text
    assert f"예제 데이터 {len(example_pack.DATA_ASSETS)}건" in text
    assert str(lib) in text and str(txt_dir) in text and str(default_example_data_dir()) in text
    assert f"'{example_pack.EXAMPLE_GROUP}' 그룹" in text
    assert "덮어쓰고" not in text  # 첫 설치는 덮어쓸 것이 없다
    # 확정을 지나지 않았으므로 홈·라이브러리는 불변이다.
    assert not default_example_data_dir().exists()
    assert settings.load_tutorial_manifest() is None
    assert _installed_names(lib, txt_dir) == set()


# ---------------------------------------------------------------- 설치가 성립시키는 것
def test_confirmed_install_lands_templates_groups_data_and_manifest(tmp_path):
    """설치 한 번으로 「예제」 그룹 hwpx 3·TXT 2 + 고정 데이터 2 가 선다(#891 완료 기준)."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {})
    done = ctrl.dispatch("install_examples", {"confirm": True})
    assert done == {"ok": True, "installed": len(ALL_ASSETS)}

    assert _installed_names(lib, txt_dir) == set(
        example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )
    snap = ctrl.snapshot()
    for name in example_pack.HWPX_ASSETS:
        assert _group_of(snap, "hwpx", name) == example_pack.EXAMPLE_GROUP
    for name in example_pack.TXT_ASSETS:
        assert _group_of(snap, "txt", name) == example_pack.EXAMPLE_GROUP
    assert snap["examples"]["installed"] is True
    assert snap["examples"]["label"] == "예제 다시 설치…"
    assert snap["result"]["level"] == "ok"
    assert "5건" in snap["result"]["text"] and "2건" in snap["result"]["text"]

    # 데이터는 홈의 예제 자리로 복사되고 풀에 **고정**된다(경로 참조 — 풀은 파일을 품지 않는다).
    data_dir = default_example_data_dir()
    assert {p.name for p in data_dir.iterdir()} == set(example_pack.DATA_ASSETS)
    pinned = DatasetPoolRegistry(tmp_path / "datasets").list_items()
    assert sorted(item.name for item in pinned) == sorted(
        Path(n).stem for n in example_pack.DATA_ASSETS
    )
    assert all(item.kind == "excel" and item.is_active for item in pinned)


def test_manifest_records_every_installed_path_and_pool_key(tmp_path):
    """manifest 가 설치 항목 **전수**를 기록한다 — 제거(슬라이스 C)가 읽을 유일한 입력이다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})

    manifest = settings.load_tutorial_manifest()
    assert manifest["group"] == example_pack.EXAMPLE_GROUP
    assert len(manifest["templates"]) == len(
        example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )
    for entry in manifest["templates"]:
        assert entry["media"] in ("hwpx", "txt")
        assert Path(entry["path"]).is_file()
        assert entry["key"] == Path(entry["path"]).name  # 루트 직속 = 파일명이 곧 식별키
    assert {Path(p).name for p in manifest["data_files"]} == set(example_pack.DATA_ASSETS)
    assert all(Path(p).is_file() for p in manifest["data_files"])
    pool = DatasetPoolRegistry(tmp_path / "datasets")
    assert len(manifest["pool_keys"]) == len(example_pack.DATA_ASSETS)
    assert all(pool.exists(key) for key in manifest["pool_keys"])


def test_manifest_and_progress_share_the_tutorial_bucket_without_erasing_each_other(tmp_path):
    """진행 칸(#893)과 설치 manifest 는 같은 ``tutorial`` 아래 공존한다 — 한쪽 저장이 다른쪽을 지우지 않는다."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    settings.save_tutorial_progress(achieved=["T0"], dismissed=False)
    ctrl.dispatch("install_examples", {"confirm": True})
    assert settings.load_tutorial_progress() == {"achieved": ["T0"], "dismissed": False}
    assert settings.load_tutorial_manifest() is not None

    settings.save_tutorial_progress(achieved=["T0", "T1"], dismissed=True)
    assert settings.load_tutorial_manifest() is not None  # 진행 저장이 manifest 를 걷지 않는다


# ---------------------------------------------------------------- 재설치 = 복원
def test_reinstall_restores_the_same_state_instead_of_piling_up_copies(tmp_path):
    """재설치는 되돌리기다(D4) — 지난 설치분을 덮어쓰고 사본을 쌓지 않는다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    first = settings.load_tutorial_manifest()
    (lib / example_pack.HWPX_ASSETS[0]).write_bytes(b"broken")  # 사용자가 망가뜨린 상태

    ask = ctrl.dispatch("install_examples", {})
    assert "덮어쓰고 처음 상태로 되돌립니다" in ask["confirm_text"]
    ctrl.dispatch("install_examples", {"confirm": True})

    assert _installed_names(lib, txt_dir) == set(
        example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )  # "이름 (2).hwpx" 사본이 서지 않았다
    assert (lib / example_pack.HWPX_ASSETS[0]).read_bytes() != b"broken"
    second = settings.load_tutorial_manifest()
    assert second["templates"] == first["templates"]
    # 같은 데이터 = 슬롯 1개(정체성 불변식) — 재설치가 풀을 부풀리지 않는다.
    assert second["pool_keys"] == first["pool_keys"]
    assert len(DatasetPoolRegistry(tmp_path / "datasets").list_items()) == len(
        example_pack.DATA_ASSETS
    )


def test_reinstall_returns_an_archived_example_dataset_to_the_run_candidates(tmp_path):
    """보관해 둔 예제 데이터는 재설치로 실행 후보에 되돌아온다 — 라벨·메모는 사용자 것이라 보존."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    pool = DatasetPoolRegistry(tmp_path / "datasets")
    key = settings.load_tutorial_manifest()["pool_keys"][0]
    pool.relabel(key, "내가 붙인 이름")
    pool.archive(key)

    ctrl.dispatch("install_examples", {"confirm": True})
    item = pool.load(key)
    assert item.is_active
    assert item.name == "내가 붙인 이름"


def test_a_users_own_file_with_the_same_name_is_not_clobbered(tmp_path):
    """기재에 없는 동명 파일은 남의 파일이다 — 접미로 비켜 가고 결과가 그 사실을 재진술한다."""
    ctrl, lib, _txt, _ = _controller(tmp_path)
    mine = lib / example_pack.HWPX_ASSETS[0]
    mine.write_bytes(b"my own template")

    ctrl.dispatch("install_examples", {"confirm": True})
    assert mine.read_bytes() == b"my own template"
    assert "같은 이름의 파일이 있어" in ctrl.snapshot()["result"]["text"]
    installed = {Path(t["path"]).name for t in settings.load_tutorial_manifest()["templates"]}
    assert f"{Path(example_pack.HWPX_ASSETS[0]).stem} (2).hwpx" in installed


# ---------------------------------------------------------------- 자산 원천 해석
def test_missing_assets_refuse_loudly_before_touching_home(tmp_path, monkeypatch):
    """동봉 누락·손상 배포본은 **부분 설치를 남기지 않는다** — 홈을 건드리기 전에 멈춘다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    monkeypatch.setattr(example_pack, "asset_root", lambda: tmp_path / "없는곳")
    result = ctrl.dispatch("install_examples", {"confirm": True})
    assert result["ok"] is False
    assert "동봉 예제 자산을 찾지 못했습니다" in result["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert _installed_names(lib, txt_dir) == set()
    assert settings.load_tutorial_manifest() is None
    assert not default_example_data_dir().exists()


def test_asset_root_follows_the_frozen_branch(tmp_path, monkeypatch):
    """frozen 제품은 ``sys._MEIPASS`` 동봉 사본을, source 실행은 저장소 폴더를 본다(§4.2)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    assert example_pack.asset_root() == tmp_path / "meipass" / "examples" / "onboarding"

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    source_root = example_pack.asset_root()
    assert source_root.name == "onboarding" and source_root.parent.name == "examples"
    assert (source_root / "templates" / example_pack.HWPX_ASSETS[0]).is_file()


# ---------------------------------------------------------------- manifest 영속 계약
@pytest.mark.parametrize(
    "kwargs",
    [
        {"group": "  ", "templates": [], "data_files": [], "pool_keys": []},
        {"group": "예제", "templates": [{"media": "pdf", "path": "p", "key": "k"}],
         "data_files": [], "pool_keys": []},
        {"group": "예제", "templates": [{"media": "hwpx", "path": 1, "key": "k"}],
         "data_files": [], "pool_keys": []},
        {"group": "예제", "templates": [], "data_files": [7], "pool_keys": []},
        {"group": "예제", "templates": [], "data_files": [], "pool_keys": [None]},
    ],
)
def test_save_tutorial_manifest_rejects_invalid_input_loudly(kwargs):
    """비유효 입력은 조용히 무시되지 않는다 — 반쯤 쓰인 manifest 는 제거를 못 믿게 만든다."""
    with pytest.raises(ValueError):
        settings.save_tutorial_manifest(**kwargs)
    assert settings.load_tutorial_manifest() is None


def test_damaged_manifest_reads_as_not_installed(tmp_path):
    """형상이 계약과 다른 manifest 는 **없는 것**으로 읽는다 — 반쯤 해석해 제거를 돌리지 않는다."""
    settings.save_tutorial_progress(achieved=[], dismissed=False)
    path = home_dir() / "settings.json"
    path.write_text('{"tutorial": {"manifest": {"templates": "hwpx"}}}', encoding="utf-8")
    assert settings.load_tutorial_manifest() is None
    assert example_pack.entry_point_state()["installed"] is False


def test_library_empty_state_reads_the_same_entry_point_source(tmp_path):
    """라이브러리 빈 상태의 버튼도 tpl 스냅샷과 **같은 단일 출처**를 읽는다(문안 이중 판정 금지)."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    before = example_pack.entry_point_state()
    assert ctrl.snapshot()["examples"] == before
    ctrl.dispatch("install_examples", {"confirm": True})
    after = example_pack.entry_point_state()
    assert after["installed"] is True
    assert ctrl.snapshot()["examples"] == after
