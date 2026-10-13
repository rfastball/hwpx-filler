"""서식 폴더 단일 루트 — 링0 도출과 External 홀더.

두 층을 한 파일에서 잰다: 판정(순수 함수)·관찰(설정 읽기 + 존재). 홈은
``tests/conftest.py`` 의 autouse 격리가 이미 tmp 로 못박는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.domain.template_root_default import (
    SOURCE_CONFIGURED,
    SOURCE_DEFAULT,
    resolve_templates_root,
    source_label,
)
from hwpxfiller.domain.template_status import library_display_name
from hwpxfiller.external import settings
from hwpxfiller.external.template_root import TemplateRoot


# ============================================================== 링0 도출(4갈래)
def test_unset_resolves_to_the_default_root_without_a_notice():
    r = resolve_templates_root(configured="", configured_exists=False, default_root="D:/home/templates")
    assert (r.directory, r.source, r.notice) == ("D:/home/templates", SOURCE_DEFAULT, "")


def test_configured_and_present_stands_as_is():
    r = resolve_templates_root(
        configured="D:/서식", configured_exists=True, default_root="D:/home/templates"
    )
    assert (r.directory, r.source, r.notice) == ("D:/서식", SOURCE_CONFIGURED, "")


def test_configured_but_missing_does_not_fall_back_to_the_default():
    """사라진 선택 폴더도 그대로 루트로 두고 사유만 병기한다."""
    r = resolve_templates_root(
        configured="D:/없는서식", configured_exists=False, default_root="D:/home/templates"
    )
    assert r.directory == "D:/없는서식" and r.source == SOURCE_CONFIGURED
    assert "찾을 수 없습니다" in r.notice and "D:/없는서식" in r.notice


def test_an_empty_configured_value_is_the_same_as_unset():
    r = resolve_templates_root(configured="", configured_exists=True, default_root="D:/기본")
    assert (r.directory, r.source, r.notice) == ("D:/기본", SOURCE_DEFAULT, "")


def test_source_labels_are_the_single_source_of_the_user_copy():
    assert source_label(SOURCE_CONFIGURED) == "설정한 폴더"
    assert source_label(SOURCE_DEFAULT) == "기본 폴더"
    assert source_label("자라나는미상") == ""
    r = resolve_templates_root(configured="D:/x", configured_exists=True, default_root="D:/y")
    assert r.source_label == "설정한 폴더"


# ================================================================ External 홀더
def test_holder_reads_the_setting_every_time(tmp_path):
    chosen = tmp_path / "서식"
    chosen.mkdir()
    root = TemplateRoot(default_root=tmp_path / "기본")

    assert root.path() == tmp_path / "기본"
    assert root.resolution().source == SOURCE_DEFAULT

    after = root.set(str(chosen))
    assert after.source == SOURCE_CONFIGURED and after.notice == ""
    assert root.path() == chosen
    assert settings.load_templates_root() == str(chosen)


def test_holder_observes_absence_and_says_so_without_moving(tmp_path):
    root = TemplateRoot(default_root=tmp_path / "기본")
    root.set(str(tmp_path / "사라진서식"))

    resolution = root.resolution()
    assert resolution.directory == str(tmp_path / "사라진서식")
    assert "찾을 수 없습니다" in resolution.notice


def test_an_untouched_home_falls_back_to_the_default_key(tmp_path):
    assert settings.load_templates_root() == ""
    assert TemplateRoot(default_root=tmp_path / "기본").path() == tmp_path / "기본"


def test_saving_an_empty_root_is_loud(tmp_path):
    with pytest.raises(ValueError, match="유효하지 않은 서식 폴더"):
        settings.save_templates_root("   ")


# ============================================== 표시명 규칙(hwpx·txt 동일)
def test_display_name_is_the_root_relative_posix_stem():
    root = Path("D:/서식")
    assert library_display_name(root, root / "공고서.hwpx") == "공고서"
    assert library_display_name(root, root / "온나라" / "기안.txt") == "온나라/기안"
    assert library_display_name(root, Path("E:/남의/문서.hwpx")) == "문서"
    assert library_display_name(None, Path("E:/남의/문서.hwpx")) == "문서"
