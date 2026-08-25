"""U3-06(#879) 저장 폴더 도출 — 순수 판정과 그 영속 재료.

여기가 재는 것은 두 가지다: (1) ① 명시 지정 → ② 기억한 지정 → ③ 템플릿 옆 ``Results`` 의
우선순위와 각 단계가 **무엇이라고 말하는지**(출처·사유), (2) 마지막 명시 지정이 설정에
남아 다음 도출의 재료가 된다는 것. 컨트롤러 배선은 `test_webapp_job_binding_review.py` 가 잰다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.domain.output_folder_default import (
    SOURCE_EXPLICIT,
    SOURCE_NONE,
    SOURCE_REMEMBERED,
    SOURCE_TEMPLATE_DEFAULT,
    default_output_directory,
    resolve_output_folder,
)
from hwpxfiller.domain.template_status import OUTPUT_SUBDIR_NAME
from hwpxfiller.external.settings import (
    load_last_output_directory,
    save_last_output_directory,
)


def test_default_is_the_results_folder_beside_the_template() -> None:
    template = Path("C:/서고/공고서.hwpx")
    assert default_output_directory(str(template)) == str(
        template.parent / OUTPUT_SUBDIR_NAME
    )
    assert default_output_directory("") == ""


def test_explicit_pick_outranks_memory_and_default() -> None:
    resolution = resolve_output_folder(
        explicit_directory="C:/이번-세션",
        remembered_directory="C:/지난번",
        remembered_exists=True,
        template_path="C:/서고/공고서.hwpx",
    )
    assert (resolution.directory, resolution.source) == ("C:/이번-세션", SOURCE_EXPLICIT)
    assert resolution.source_label == "직접 지정"
    assert resolution.notice == ""


def test_memory_outranks_the_default_when_the_folder_is_still_there() -> None:
    resolution = resolve_output_folder(
        remembered_directory="C:/지난번",
        remembered_exists=True,
        template_path="C:/서고/공고서.hwpx",
    )
    assert (resolution.directory, resolution.source) == ("C:/지난번", SOURCE_REMEMBERED)
    assert resolution.source_label == "기억한 폴더"
    assert resolution.notice == ""


def test_vanished_memory_falls_back_to_the_default_with_a_stated_reason() -> None:
    resolution = resolve_output_folder(
        remembered_directory="C:/사라진",
        remembered_exists=False,
        template_path="C:/서고/공고서.hwpx",
    )
    assert resolution.source == SOURCE_TEMPLATE_DEFAULT
    assert resolution.directory == str(Path("C:/서고") / OUTPUT_SUBDIR_NAME)
    # 조용한 하향 금지 — 사유를 문안으로 낸다.
    assert resolution.notice == (
        "지난번에 지정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다."
    )


def test_vanished_memory_without_a_default_asks_for_a_pick() -> None:
    resolution = resolve_output_folder(
        remembered_directory="C:/사라진", remembered_exists=False, template_path=""
    )
    assert (resolution.directory, resolution.source) == ("", SOURCE_NONE)
    assert resolution.resolved is False
    assert resolution.source_label == ""
    assert resolution.notice == (
        "지난번에 지정한 저장 폴더를 찾을 수 없습니다. 저장 폴더를 선택하세요."
    )


def test_nothing_to_derive_from_is_stated_as_unresolved() -> None:
    resolution = resolve_output_folder()
    assert (resolution.directory, resolution.source, resolution.notice) == (
        "",
        SOURCE_NONE,
        "",
    )
    assert resolution.resolved is False


@pytest.mark.parametrize(
    "template_path", ["managed.hwpx", "서고/공고서.hwpx", "./공고서.hwpx"]
)
def test_a_relative_template_yields_no_default(template_path: str) -> None:
    """작업 디렉터리를 따라 움직이는 자리는 기본값이 되지 못한다 — 지정을 요구한다."""
    assert resolve_output_folder(template_path=template_path).resolved is False


def test_a_relative_memory_is_not_used_even_if_something_exists_there() -> None:
    resolution = resolve_output_folder(
        remembered_directory="Results",
        remembered_exists=True,
        template_path="C:/서고/공고서.hwpx",
    )
    assert resolution.source == SOURCE_TEMPLATE_DEFAULT


def test_last_pick_persists_and_reads_back(tmp_path: Path) -> None:
    assert load_last_output_directory() == ""  # 미저장 = 기본 거동
    save_last_output_directory(str(tmp_path / "고른-폴더"))
    assert load_last_output_directory() == str(tmp_path / "고른-폴더")


def test_saving_an_empty_pick_is_loud(tmp_path: Path) -> None:
    save_last_output_directory(str(tmp_path))
    with pytest.raises(ValueError, match="유효하지 않은 저장 폴더 경로"):
        save_last_output_directory("   ")
    # 거절이 기존 값을 지우지 않는다.
    assert load_last_output_directory() == str(tmp_path)


def test_a_corrupt_key_reads_as_unsaved(tmp_path: Path) -> None:
    from hwpxfiller.external import settings as settings_module

    settings_module._save_key("last_output_directory", 7)
    assert load_last_output_directory() == ""
