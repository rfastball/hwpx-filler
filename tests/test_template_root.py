"""서식 폴더 단일 루트(U6-A · #975) — 링0 도출 · External 홀더 · 레거시 TXT 이관.

세 층을 한 파일에서 잰다: 판정(순수 함수)·관찰(설정 읽기 + 존재)·효과(1회 이관). 홈은
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
from hwpxfiller.external.template_root import (
    LEGACY_TEXT_TEMPLATES_DIRNAME,
    TemplateRoot,
    TextTemplatesMigration,
    migrate_legacy_text_templates,
)


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
    """**저장 폴더와 다른 점**: 사라진 폴더도 그대로 루트다 — 사유만 병기한다.

    내려가면 사용자가 고른 것과 **다른 템플릿 집합**이 목록에 서고, 그것으로 문서를 만드는
    것이 곧 조용한 추측이다.
    """
    r = resolve_templates_root(
        configured="D:/없는서식", configured_exists=False, default_root="D:/home/templates"
    )
    assert r.directory == "D:/없는서식" and r.source == SOURCE_CONFIGURED
    assert "찾을 수 없습니다" in r.notice and "D:/없는서식" in r.notice


def test_an_empty_configured_value_is_the_same_as_unset():
    """빈 문자열은 「지정한 적 없음」이다 — 존재 관찰 결과와 무관하게 기본 폴더가 선다."""
    r = resolve_templates_root(configured="", configured_exists=True, default_root="D:/기본")
    assert (r.directory, r.source, r.notice) == ("D:/기본", SOURCE_DEFAULT, "")


def test_source_labels_are_the_single_source_of_the_user_copy():
    assert source_label(SOURCE_CONFIGURED) == "설정한 폴더"
    assert source_label(SOURCE_DEFAULT) == "기본 폴더"
    assert source_label("자라나는미상") == ""     # 모르는 출처를 지어내지 않는다
    r = resolve_templates_root(configured="D:/x", configured_exists=True, default_root="D:/y")
    assert r.source_label == "설정한 폴더"


# ================================================================ External 홀더
def test_holder_reads_the_setting_every_time(tmp_path):
    """홀더는 캐시하지 않는다 — :meth:`TemplateRoot.set` 직후의 첫 판독이 곧 새 루트다."""
    chosen = tmp_path / "서식"
    chosen.mkdir()
    root = TemplateRoot(default_root=tmp_path / "기본")

    assert root.path() == tmp_path / "기본"
    assert root.resolution().source == SOURCE_DEFAULT

    after = root.set(str(chosen))
    assert after.source == SOURCE_CONFIGURED and after.notice == ""
    assert root.path() == chosen
    assert settings.load_templates_root() == str(chosen)   # 영속까지 갔다


def test_holder_observes_absence_and_says_so_without_moving(tmp_path):
    root = TemplateRoot(default_root=tmp_path / "기본")
    root.set(str(tmp_path / "사라진서식"))

    resolution = root.resolution()
    assert resolution.directory == str(tmp_path / "사라진서식")   # 기본으로 안 내려간다
    assert "찾을 수 없습니다" in resolution.notice


def test_an_untouched_home_falls_back_to_the_default_key(tmp_path):
    """새 설정 키는 임시 홈의 빈 settings 에서 **기본값으로 떨어진다**(격리 계약)."""
    assert settings.load_templates_root() == ""
    assert TemplateRoot(default_root=tmp_path / "기본").path() == tmp_path / "기본"


def test_saving_an_empty_root_is_loud(tmp_path):
    with pytest.raises(ValueError, match="유효하지 않은 서식 폴더"):
        settings.save_templates_root("   ")


# ==================================================== 레거시 TXT 1회 이관(§4)
def _legacy(home: Path, relative: str, body: str = "{{건명}}") -> Path:
    path = home / LEGACY_TEXT_TEMPLATES_DIRNAME / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_migration_moves_legacy_txt_into_the_default_root(tmp_path):
    home = tmp_path / "home"
    root = TemplateRoot(default_root=home / "templates")
    _legacy(home, "기안.txt")
    _legacy(home, "온나라/협조전.txt")

    done = migrate_legacy_text_templates(home=home, root=root)

    assert done.moved == ["기안.txt", "온나라/협조전.txt"]
    assert done.skipped == []
    assert (home / "templates" / "기안.txt").is_file()
    assert (home / "templates" / "온나라" / "협조전.txt").is_file()
    # **옮긴다**(복사가 아니다) — 다음 부팅에 걷을 것이 남지 않는다.
    assert not (home / LEGACY_TEXT_TEMPLATES_DIRNAME / "기안.txt").exists()
    assert "TXT 템플릿 2건" in done.restate(root.path())


def test_migration_skips_a_name_that_is_already_taken_and_says_which(tmp_path):
    home = tmp_path / "home"
    root = TemplateRoot(default_root=home / "templates")
    (home / "templates").mkdir(parents=True)
    (home / "templates" / "기안.txt").write_text("이미 있는 것", encoding="utf-8")
    _legacy(home, "기안.txt", "옛것")

    done = migrate_legacy_text_templates(home=home, root=root)

    assert done.moved == []
    assert done.skipped == [("기안.txt", "같은 이름이 이미 있습니다")]
    assert (home / "templates" / "기안.txt").read_text(encoding="utf-8") == "이미 있는 것"
    assert (home / LEGACY_TEXT_TEMPLATES_DIRNAME / "기안.txt").exists()  # 남긴다
    assert "옮기지 못한 파일 1건" in done.restate(root.path())


def test_migration_leaves_the_trash_subtree_alone(tmp_path):
    home = tmp_path / "home"
    root = TemplateRoot(default_root=home / "templates")
    _legacy(home, ".trash/0-old-지운기안.txt")
    _legacy(home, "살아있는.txt")

    done = migrate_legacy_text_templates(home=home, root=root)

    assert done.moved == ["살아있는.txt"]
    assert (home / LEGACY_TEXT_TEMPLATES_DIRNAME / ".trash" / "0-old-지운기안.txt").exists()


def test_migration_is_a_no_op_when_the_user_chose_a_root(tmp_path):
    """사용자가 고른 폴더에는 앱이 파일을 넣지 않는다 — 이관은 기본 루트일 때만이다."""
    home = tmp_path / "home"
    chosen = tmp_path / "내서식"
    chosen.mkdir()
    root = TemplateRoot(default_root=home / "templates")
    root.set(str(chosen))
    _legacy(home, "기안.txt")

    done = migrate_legacy_text_templates(home=home, root=root)

    assert done.moved == [] and done.skipped == [] and not done.happened
    assert list(chosen.iterdir()) == []
    assert (home / LEGACY_TEXT_TEMPLATES_DIRNAME / "기안.txt").exists()


def test_migration_without_a_legacy_folder_says_nothing(tmp_path):
    home = tmp_path / "home"
    root = TemplateRoot(default_root=home / "templates")
    done = migrate_legacy_text_templates(home=home, root=root)
    assert not done.happened and done.restate(root.path()) == ""


# ============================================== 표시명 규칙(hwpx·txt 동일)
def test_display_name_is_the_root_relative_posix_stem():
    root = Path("D:/서식")
    assert library_display_name(root, root / "공고서.hwpx") == "공고서"
    assert library_display_name(root, root / "온나라" / "기안.txt") == "온나라/기안"
    # 루트 밖·루트 미상은 확장자 없는 basename 으로 강등한다(이름이 통째로 비지 않게).
    assert library_display_name(root, Path("E:/남의/문서.hwpx")) == "문서"
    assert library_display_name(None, Path("E:/남의/문서.hwpx")) == "문서"


def test_migration_skips_subtrees_the_listing_would_filter_out(tmp_path):
    """``Results``·``.trash`` 는 옮기지 않는다 — 옮기면 새 루트에서도 걸러져 사라진다.

    나열 술어(:func:`is_excluded_subtree`)와 **같은 목록**을 쓰는지까지 잰다: 한쪽만 알면
    「옮겼다고 했는데 목록에 없다」가 된다.
    """
    home = tmp_path / "home"
    root = TemplateRoot(default_root=home / "templates")
    _legacy(home, "Results/완성문서.txt")
    _legacy(home, ".trash/0-old-지운기안.txt")
    _legacy(home, "살아있는.txt")

    done = migrate_legacy_text_templates(home=home, root=root)

    assert done.moved == ["살아있는.txt"]
    assert dict(done.skipped) == {
        "Results/완성문서.txt": "서식 폴더가 읽지 않는 하위 폴더입니다",
        ".trash/0-old-지운기안.txt": "서식 폴더가 읽지 않는 하위 폴더입니다",
    }
    # 안 옮긴 것은 **제자리에 그대로** 남는다(조용한 증발 금지).
    assert (home / LEGACY_TEXT_TEMPLATES_DIRNAME / "Results" / "완성문서.txt").exists()
    assert not (home / "templates" / "Results").exists()


def test_restate_gives_one_line_per_reason(tmp_path):
    """사유가 둘이면 줄도 둘 — 한 줄로 뭉치면 안 옮긴 이유가 하나로 읽힌다."""
    done = TextTemplatesMigration(
        moved=["가.txt"],
        skipped=[("나.txt", "같은 이름이 이미 있습니다"),
                 ("Results/다.txt", "서식 폴더가 읽지 않는 하위 폴더입니다")],
    )
    lines = done.restate(tmp_path / "templates").splitlines()
    assert len(lines) == 3
    assert "같은 이름이 이미 있습니다: 나.txt" in lines[1]
    assert "읽지 않는 하위 폴더입니다: Results/다.txt" in lines[2]
