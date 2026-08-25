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
import threading
import time
from pathlib import Path

import pytest

from hwpxfiller.domain.job import Job
from hwpxfiller.domain.template_status import TRASH_DIR_NAME
from hwpxfiller.external import example_pack, settings
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.host.locations import default_example_data_dir, home_dir
from hwpxfiller.webapp.screen_library import LibraryController
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
        # 시계는 **실시간**이다: 휴지통 이동이 30일 컷오프 정리를 함께 지므로, 먼 미래로
        # 못박으면 방금 넣은 항목이 다음 이동에서 만료로 지워져 제거 검증이 허수가 된다.
        file_store=TemplateFileStore(
            lib, registry, clock=time.time, new_id=lambda: "fixedid"
        ),
        library_dir=lib,
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
    )
    return ctrl, lib, txt_dir, pushes


def _installed_names(lib: Path, txt_dir: Path) -> "set[str]":
    """라이브러리 두 루트의 **파일** 이름 — 제거가 만드는 ``.trash`` 폴더는 목록이 아니다."""
    return {p.name for p in lib.iterdir() if p.is_file()} | {
        p.name for p in txt_dir.iterdir() if p.is_file()
    }


def _trashed_names(root: Path) -> "set[str]":
    """휴지통에 실제로 앉은 원본 이름들 — 이동 몸통이 붙이는 ``<시각>-<id>-`` 접두를 뗀다."""
    trash = root / TRASH_DIR_NAME
    if not trash.exists():
        return set()
    return {p.name.split("-", 2)[2] for p in trash.iterdir() if p.is_file()}


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
        # 걷을 것이 없는 자리에 파괴 동사를 세우지 않는다(#892).
        "removable": False,
        "remove_label": "예제 걷어내기…",
        "remove_hint": "설치한 예제만 걷습니다. 되돌리려면 다시 설치하세요.",
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


# ---------------------------------------------------------------- 일괄 제거(#892 · D4)
def test_removal_restates_what_disappears_and_writes_nothing_first(tmp_path):
    """1차 호출은 **재진술만** — 템플릿·데이터·고정·그룹 수치와 「되돌리기는 재설치」."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})

    ask = ctrl.dispatch("remove_examples", {})
    assert ask["needs_confirm"] is True
    text = ask["confirm_text"]
    assert f"템플릿 {len(example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS)}건" in text
    assert f"예제 데이터 {len(example_pack.DATA_ASSETS)}건" in text
    assert f"데이터 풀 고정 {len(example_pack.DATA_ASSETS)}건" in text
    assert f"'{example_pack.EXAMPLE_GROUP}' 그룹 1개" in text
    assert "되돌리기는 다시 설치하기입니다" in text  # 벌크 undo 가 없다는 사실을 숨기지 않는다
    # 확정을 지나지 않았으므로 아무것도 걷히지 않았다.
    assert _installed_names(lib, txt_dir) == set(
        example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )
    assert settings.load_tutorial_manifest() is not None


def test_confirmed_removal_sweeps_every_manifest_entry_and_returns_the_empty_state(tmp_path):
    """제거 한 번으로 기재 자산 전부 소거 — 템플릿·데이터·고정·그룹·manifest(#892 완료 기준)."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    pool = DatasetPoolRegistry(tmp_path / "datasets")

    done = ctrl.dispatch("remove_examples", {"confirm": True})
    assert done == {"ok": True, "removed": len(ALL_ASSETS)}

    assert _installed_names(lib, txt_dir) == set()
    # 템플릿은 **지워지지 않고** 매체별 휴지통으로 갔다(기존 삭제 기제 재사용).
    assert _trashed_names(lib) == set(example_pack.HWPX_ASSETS)
    assert _trashed_names(txt_dir) == set(example_pack.TXT_ASSETS)
    # 데이터는 파일이 지워지고 풀 고정도 풀린다(풀은 파일을 품지 않으므로 둘 다 걷어야 한다).
    assert list(default_example_data_dir().glob("*")) == []
    assert pool.list_items() == []
    assert settings.load_tutorial_manifest() is None

    snap = ctrl.snapshot()
    assert snap["hwpx"]["count"] == 0 and snap["txt"]["count"] == 0
    assert example_pack.EXAMPLE_GROUP not in snap["hwpx"]["group_names"]
    assert example_pack.EXAMPLE_GROUP not in snap["txt"]["group_names"]
    assert snap["examples"]["installed"] is False
    assert snap["examples"]["removable"] is False
    assert snap["result"]["level"] == "ok"
    assert "되돌리려면 다시 설치하세요" in snap["result"]["text"]


def test_removal_notifies_each_open_session_per_template(tmp_path):
    """열린 편집 세션 통지는 **건별**이다 — 벌크 통지를 새로 짓지 않는다(#320 계약)."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    seen: list = []
    ctrl.mutation_sinks.append(lambda kind, path: seen.append((kind, Path(path).name)))

    ctrl.dispatch("remove_examples", {"confirm": True})
    assert sorted(seen) == sorted(
        ("deleted", name)
        for name in example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )


def test_files_outside_the_manifest_are_untouchable(tmp_path):
    """기재 밖 파일은 남의 것이다 — 예제를 고쳐 **다른 이름**으로 저장한 것은 그대로 남는다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    mine_hwpx = lib / f"{Path(example_pack.HWPX_ASSETS[0]).stem} (2).hwpx"
    mine_hwpx.write_bytes(b"my own edit of the example")
    mine_txt = txt_dir / "내기안.txt"
    mine_txt.write_text("제목: {{공고번호}}", encoding="utf-8")
    # 그룹까지 예제와 같이 묶어 둔 경우에도 파일은 안전하다(해산은 소속만 걷는다).
    ctrl.dispatch("set_group", {"media": "hwpx", "key": mine_hwpx.name,
                                "group": example_pack.EXAMPLE_GROUP})

    ctrl.dispatch("remove_examples", {"confirm": True})

    assert mine_hwpx.read_bytes() == b"my own edit of the example"
    assert mine_txt.is_file()
    assert _installed_names(lib, txt_dir) == {mine_hwpx.name, mine_txt.name}
    assert _trashed_names(lib) == set(example_pack.HWPX_ASSETS)  # 남의 파일은 휴지통에도 없다
    assert ctrl.snapshot()["hwpx"]["group_names"] == []  # 그룹은 해산됐고 파일은 남았다


def test_a_user_edited_manifest_file_is_still_removed(tmp_path):
    """제자리에서 고쳤어도 **manifest 기준으로** 걷는다 — 판정 축이 흔들리지 않는다."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    edited = lib / example_pack.HWPX_ASSETS[0]
    edited.write_bytes(b"user edited in place")

    ctrl.dispatch("remove_examples", {"confirm": True})
    assert not edited.exists()
    assert _installed_names(lib, txt_dir) == set()


def test_a_manifest_path_outside_its_root_is_refused_loudly(tmp_path):
    """제자리를 벗어난 기재는 **임의 파일 삭제 권한**이 될 뻔한 값이다 — 재진술 전에 막는다."""
    ctrl, lib, _txt, _ = _controller(tmp_path)
    outside = tmp_path / "남의문서.hwpx"
    outside.write_bytes(b"not mine to delete")
    settings.save_tutorial_manifest(
        group=example_pack.EXAMPLE_GROUP,
        templates=[{"media": "hwpx", "path": str(outside), "key": "../남의문서.hwpx"}],
        data_files=[], pool_keys=[],
    )

    ask = ctrl.dispatch("remove_examples", {})  # 1차부터 거절 — 확인을 묻지 않는다
    assert ask["ok"] is False and "제자리를 벗어났습니다" in ask["error"]
    assert "needs_confirm" not in ask
    done = ctrl.dispatch("remove_examples", {"confirm": True})
    assert done["ok"] is False
    assert outside.read_bytes() == b"not mine to delete"
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert settings.load_tutorial_manifest() is not None  # 지우지 못했으면 기재도 남는다


def test_a_relinked_pin_is_left_alone_and_said_out_loud(tmp_path):
    """사용자가 자기 데이터로 다시 연결한 슬롯은 manifest 밖 참조다 — 남기고 재진술한다."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    pool = DatasetPoolRegistry(tmp_path / "datasets")
    key = settings.load_tutorial_manifest()["pool_keys"][0]
    mine = tmp_path / "내데이터.csv"
    mine.write_text("공고번호\n1\n", encoding="utf-8")
    pool.relink_excel(key, str(mine), name="내 데이터")

    ctrl.dispatch("remove_examples", {"confirm": True})
    assert pool.exists(key)                      # 남의 참조는 조용히 지우지 않는다
    assert pool.load(key).name == "내 데이터"
    assert "다시 연결된 고정은 남겼습니다" in ctrl.snapshot()["result"]["text"]
    assert len(pool.list_items()) == 1           # 예제 쪽 고정 1건만 풀렸다


def test_removal_keeps_tutorial_progress_so_reinstall_continues(tmp_path):
    """제거해도 학습 진행은 남는다 — 재설치가 **이어서** 배우는 경로다(진행 초기화는 다른 동사)."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    settings.save_tutorial_progress(achieved=["T0", "T1"], dismissed=False)
    ctrl.dispatch("install_examples", {"confirm": True})

    ctrl.dispatch("remove_examples", {"confirm": True})
    assert settings.load_tutorial_progress() == {"achieved": ["T0", "T1"], "dismissed": False}
    assert settings.load_tutorial_manifest() is None


def test_reinstall_after_removal_restores_the_same_state(tmp_path):
    """제거 → 재설치가 같은 상태를 복원한다 — 되돌리기를 재설치에 맡긴 대가(#892 완료 기준)."""
    ctrl, lib, txt_dir, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    before = settings.load_tutorial_manifest()

    ctrl.dispatch("remove_examples", {"confirm": True})
    ctrl.dispatch("install_examples", {"confirm": True})

    assert _installed_names(lib, txt_dir) == set(
        example_pack.HWPX_ASSETS + example_pack.TXT_ASSETS
    )  # "이름 (2).hwpx" 사본이 서지 않았다(제거가 자리를 비워 뒀다)
    after = settings.load_tutorial_manifest()
    assert after["templates"] == before["templates"]
    snap = ctrl.snapshot()
    for name in example_pack.HWPX_ASSETS:
        assert _group_of(snap, "hwpx", name) == example_pack.EXAMPLE_GROUP
    assert {p.name for p in default_example_data_dir().iterdir()} == set(
        example_pack.DATA_ASSETS
    )
    assert len(DatasetPoolRegistry(tmp_path / "datasets").list_items()) == len(
        example_pack.DATA_ASSETS
    )
    assert snap["examples"]["removable"] is True


def test_a_job_left_pointing_at_a_removed_example_uses_the_existing_alarm(tmp_path):
    """제거 뒤 남은 실습 작업의 템플릿 결핍은 **기존** 미존재 경보가 드러낸다(신규 표면 없음).

    D4 가 벌크 undo 를 만들지 않은 대가로 반드시 서야 하는 정직함이다 — 작업이 조용히
    「실행 가능」으로 남으면 누를 때야 사라진 템플릿을 만난다.
    """
    ctrl, lib, _txt, _ = _controller(tmp_path)
    ctrl.dispatch("install_examples", {"confirm": True})
    example = lib / example_pack.HWPX_ASSETS[0]
    jobs = JobRegistry(tmp_path / "jobs")
    jobs.save(Job(name="실습", template_path=str(example), filename_pattern="실습-{{ID}}"))
    library = LibraryController(
        jobs, TextTemplateRegistry(tmp_path / "txt"), lambda _s, _snap: None,
        engine=make_hwpx_engine(), pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
        generation_lock=threading.Lock(),
    )
    assert library.snapshot()["alerts"]["missing_template_count"] == 0

    ctrl.dispatch("remove_examples", {"confirm": True})

    # 「문서 작업」으로 돌아올 때 도는 **기존** 재조회다 — 새 표면을 만들지 않았다.
    library.dispatch("refresh", {})
    snap = library.snapshot()
    assert snap["alerts"]["missing_template_count"] == 1
    row = next(r for sec in snap["sections"] for r in sec["rows"] if r["name"] == "실습")
    assert row["health"] == {"severity": 3, "text": "템플릿 파일을 찾을 수 없습니다."}
    assert row["runnable"] is False


def test_removing_when_nothing_is_installed_refuses_loudly(tmp_path):
    """미설치 상태의 호출은 조용한 성공이 아니다 — 사유를 재진술한다."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    result = ctrl.dispatch("remove_examples", {})
    assert result == {"ok": False, "error": "설치된 예제가 없습니다."}
    assert ctrl.snapshot()["result"]["level"] == "danger"


def test_library_empty_state_reads_the_same_entry_point_source(tmp_path):
    """라이브러리 빈 상태의 버튼도 tpl 스냅샷과 **같은 단일 출처**를 읽는다(문안 이중 판정 금지)."""
    ctrl, _lib, _txt, _ = _controller(tmp_path)
    before = example_pack.entry_point_state()
    assert ctrl.snapshot()["examples"] == before
    ctrl.dispatch("install_examples", {"confirm": True})
    after = example_pack.entry_point_state()
    assert after["installed"] is True
    assert ctrl.snapshot()["examples"] == after
