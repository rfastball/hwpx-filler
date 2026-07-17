"""추적성 로케이트(#53-B) — 화이트리스트 순수 로직·네이티브 헬퍼·풀 행 경로(헤드리스).

열기/폴더보기/경로복사의 보안 경계는 백엔드 화이트리스트다: 웹 페이로드로 임의 경로를
실행하는 통로를 봉쇄하고, 사용자 소유 참조(작업 템플릿·등록 데이터·현재 세션)만 통과한다.
순수 함수(collect_owned_paths/validate_owned_path)라 창 없이 검증한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import MappingProfile
from hwpxfiller.gui.dataset_pool_state import DatasetPoolRow
from hwpxfiller.webapp.screens import (
    collect_owned_paths,
    norm_path,
    validate_owned_path,
)
from hwpxcore.native.reveal import open_path, reveal_in_explorer


def _setup(tmp_path: Path):
    tpl = tmp_path / "t.hwpx"; tpl.write_text("x", encoding="utf-8")
    data = tmp_path / "d.xlsx"; data.write_text("x", encoding="utf-8")
    jobs = JobRegistry(tmp_path / "jobs")
    jobs.save(Job(name="작업", template_path=str(tpl), mapping=MappingProfile()))
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="데이터", kind="excel", opts={"path": str(data)}))
    pool.save(DatasetPoolItem(name="나라", kind="nara", opts={"bgn_dt": "1", "end_dt": "2"}))
    return jobs, pool, tpl, data


# ------------------------------------------------ 화이트리스트 수집·검증
def test_collect_owned_gathers_templates_pool_and_session(tmp_path):
    jobs, pool, tpl, data = _setup(tmp_path)
    sess = tmp_path / "sess.csv"
    owned = collect_owned_paths(jobs, pool, [str(sess), ""])  # 빈 세션 경로는 무시
    assert norm_path(tpl) in owned            # 작업 템플릿
    assert norm_path(data) in owned           # 엑셀 등록 데이터
    assert norm_path(sess) in owned           # 현재 세션 경로
    assert len(owned) == 3                    # nara 는 파일 경로 없음 → 미포함


def test_validate_owned_accepts_owned_rejects_foreign_and_empty(tmp_path):
    jobs, pool, tpl, _data = _setup(tmp_path)
    owned = collect_owned_paths(jobs, pool)
    assert validate_owned_path(str(tpl), owned) == str(tpl)   # 소유 → 통과
    with pytest.raises(ValueError, match="추적하는 참조"):     # 남의 경로 → 거부
        validate_owned_path(str(tmp_path / "남의파일.exe"), owned)
    with pytest.raises(ValueError, match="비어"):              # 빈 경로 → 거부
        validate_owned_path("", owned)


def test_validate_owned_is_case_and_separator_insensitive(tmp_path):
    """Windows 대소문자·구분자 차이를 흡수 — 같은 파일을 같게 본다(경로 표기 우회 방지)."""
    jobs, pool, tpl, _data = _setup(tmp_path)
    owned = collect_owned_paths(jobs, pool)
    variant = str(tpl).upper().replace("/", "\\")
    assert validate_owned_path(variant, owned) == variant     # 정규화 후 동일 → 통과


def test_collect_owned_survives_corrupt_pool(tmp_path):
    """손상 데이터셋 파일이 있어도 화이트리스트 수집이 raise 하지 않는다(로케이트 가용성)."""
    jobs, pool, tpl, _data = _setup(tmp_path)
    (tmp_path / "pool" / "깨진.dataset.json").write_text("{bad json", encoding="utf-8")
    owned = collect_owned_paths(jobs, pool)                   # raise 없이 수집
    assert norm_path(tpl) in owned


# ------------------------------------------------ 네이티브 헬퍼(존재하지 않는 경로)
def test_reveal_and_open_missing_path_is_loud(tmp_path):
    """죽은 참조는 조용히 무시하지 않고 시끄럽게 실패(성공 경로는 앱을 띄우므로 테스트 안 함)."""
    missing = str(tmp_path / "없음.hwpx")
    with pytest.raises(FileNotFoundError):
        reveal_in_explorer(missing)
    with pytest.raises(FileNotFoundError):
        open_path(missing)


# ------------------------------------------------ 풀 행 로케이트 경로
def test_pool_row_locate_path_excel_only():
    """엑셀 참조만 locate_path 를 갖는다 — nara/파이프라인은 파일이 아니라 ""."""
    excel = DatasetPoolRow.from_item(
        DatasetPoolItem(name="e", kind="excel", opts={"path": "C:/d.xlsx"}))
    assert excel.locate_path == "C:/d.xlsx"
    nara = DatasetPoolRow.from_item(
        DatasetPoolItem(name="n", kind="nara", opts={"bgn_dt": "1", "end_dt": "2"}))
    assert nara.locate_path == ""


# ------------------------------------------- 매트릭스 세션 경로 화이트리스트(#67)
def test_frontend_whitelist_covers_matrix_session_paths(tmp_path, monkeypatch):
    """매트릭스가 파일로 겨눈 공통 데이터·저장 폴더가 소유 화이트리스트에 들어간다(#67).

    #53-B 의 세션 목록은 editor.template_path/data_path·run.out_dir 뿐이라 매트릭스
    화면 자신의 로케이트 버튼이 loud 거부되는 갭이 있었다 — 갭 봉합의 회귀 심.
    """
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    monkeypatch.setattr(
        app_mod, "default_pool_registry",
        lambda: DatasetPoolRegistry(tmp_path / "pool"))
    frontend = app_mod.WebFrontend(tmp_path / "txt")

    csv = tmp_path / "공통.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    out = tmp_path / "결과"
    out.mkdir()

    mx = frontend._controller("matrix")
    with pytest.raises(ValueError):                       # 겨눔 전 = 세션 밖(거부)
        frontend._validate_owned(str(csv))
    mx.load_data_path(str(csv))
    mx.set_output_folder(str(out))
    assert frontend._validate_owned(str(csv)) == str(csv)  # 겨눔 후 = 소유
    assert frontend._validate_owned(str(out)) == str(out)
