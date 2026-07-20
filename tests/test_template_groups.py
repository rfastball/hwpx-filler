"""템플릿 그룹 모델(webapp.template_groups.TemplateGroupModel) 가드 — R-info 2부 결정 2·3·8.

작업 그룹 모델과 **단일 규칙** 재사용을 실증한다: 지정 CRUD·구획 뷰(flat 퇴화 불변식)·접힘
영속·개명/해산의 접힘 승계·고아→「그룹 없음」 복귀(reconcile). 매체별 격리는 설정 계층 가드
(test_webapp_settings)와 상보 — 여기선 모델 로직을 헤드리스로 검증한다(실 홈에 영속).
"""
from __future__ import annotations

import pytest

from hwpxfiller.webapp import settings
from hwpxfiller.webapp.template_groups import TemplateGroupModel


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    return tmp_path


def test_invalid_media_is_loud(home):
    with pytest.raises(ValueError):
        TemplateGroupModel("pdf")


def test_persist_failure_leaves_model_unchanged(home, monkeypatch):
    """#136 리뷰 F4 — 영속이 최종 실패하면 라이브 상태를 바꾸지 않는다(실패분이 group_of 로
    새거나 다음 무관 저장에 뒤늦게 묻어 영속되지 않게)."""
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")

    def boom(*a, **k):
        raise PermissionError("locked")

    monkeypatch.setattr(m._settings, "save_template_group_state", boom)
    with pytest.raises(PermissionError):
        m.set_group("a.hwpx", "수의")
    assert m.group_of("a.hwpx") == "입찰"  # 라이브 미변경
    monkeypatch.undo()
    # 다음 무관 저장이 실패분(수의)을 뒤늦게 영속하지 않는다.
    m.set_group("b.hwpx", "계약")
    fresh = TemplateGroupModel("hwpx")
    assert fresh.group_of("a.hwpx") == "입찰" and fresh.group_of("b.hwpx") == "계약"


def test_group_state_saved_atomically(home):
    """#136 리뷰 F5 — 접힌 그룹 개명 시 지정·접힘이 한 원자 저장으로 함께 반영(반쪽 상태 없음)."""
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")
    m.toggle_collapse("입찰")
    m.rename_group("입찰", "2026 입찰")
    fresh = TemplateGroupModel("hwpx")  # 새 인스턴스 = 디스크 재판독
    assert fresh.group_of("a.hwpx") == "2026 입찰"
    assert fresh.is_collapsed("2026 입찰") and not fresh.is_collapsed("입찰")


def test_set_group_and_existing_groups(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", " 입찰 ")  # 공백 트리밍
    assert m.group_of("a.hwpx") == "입찰"
    assert m.existing_groups() == ["입찰"]
    m.set_group("a.hwpx", "")  # 해제 = 「그룹 없음」
    assert m.group_of("a.hwpx") == ""
    assert m.existing_groups() == []


def test_set_group_persists_across_instances(home):
    TemplateGroupModel("hwpx").set_group("a.hwpx", "입찰")
    assert TemplateGroupModel("hwpx").group_of("a.hwpx") == "입찰"  # 새 인스턴스가 설정에서 복원


def test_existing_groups_counts_only_live_members(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("live.hwpx", "입찰")
    m.set_group("gone.hwpx", "고아그룹")
    # 살아있는 키만 주면 고아 지정(gone)이 후보에서 빠진다(결정 8).
    assert m.existing_groups(keys=["live.hwpx"]) == ["입찰"]


def test_rename_group_moves_members_and_carries_collapse(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")
    m.set_group("b.hwpx", "입찰")
    m.toggle_collapse("입찰")
    assert m.rename_group("입찰", "2026 입찰") == 2
    assert m.existing_groups() == ["2026 입찰"]
    assert m.is_collapsed("2026 입찰") and not m.is_collapsed("입찰")  # 순수 개명 = 접힘 승계


def test_rename_into_existing_merges_and_respects_target_collapse(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")   # 대상(펼침)
    m.set_group("b.hwpx", "수의")
    m.toggle_collapse("수의")       # 옛 이름만 접힘
    assert m.rename_group("수의", "입찰") == 1  # 병합(확인 재진술은 화면 소관)
    assert m.existing_groups() == ["입찰"]
    # 병합이면 대상 접힘 존중(입찰은 펼침 유지) + 옛 이름만 접힘 집합에서 걷힘.
    assert not m.is_collapsed("입찰") and not m.is_collapsed("수의")


def test_rename_group_empty_names_are_loud(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")
    with pytest.raises(ValueError):
        m.rename_group("입찰", "  ")
    with pytest.raises(ValueError):
        m.rename_group("", "새이름")


def test_disband_group_returns_members_to_ungrouped(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")
    m.toggle_collapse("입찰")
    assert m.disband_group("입찰") == 1
    assert m.group_of("a.hwpx") == "" and m.existing_groups() == []
    assert not m.is_collapsed("입찰")  # 해산은 접힘도 걷는다
    with pytest.raises(ValueError):
        m.disband_group("")  # ""(그룹 없음)은 그룹이 아니다


def test_reconcile_prunes_ghost_assignments(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("live.hwpx", "입찰")
    m.set_group("gone.hwpx", "입찰")
    m.reconcile(["live.hwpx"])  # gone 은 파일이 사라졌다
    # 유령 지정이 걷혀 설정에도 반영(새 인스턴스에서 확인).
    assert TemplateGroupModel("hwpx").group_of("gone.hwpx") == ""
    assert TemplateGroupModel("hwpx").group_of("live.hwpx") == "입찰"


def test_toggle_collapse_persists(home):
    m = TemplateGroupModel("txt")
    m.toggle_collapse("입찰")
    assert TemplateGroupModel("txt").is_collapsed("입찰")
    m.toggle_collapse("입찰")
    assert not TemplateGroupModel("txt").is_collapsed("입찰")


# ------------------------------------------------- build_sections 구획 뷰
def _rows(*specs):
    """(key, name) 튜플 목록 → dict 행."""
    return [{"key": k, "name": n} for k, n in specs]


def test_sections_group_ordering_and_ungrouped_last(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("b.hwpx", "나그룹")
    m.set_group("a.hwpx", "가그룹")
    rows = _rows(("a.hwpx", "a"), ("b.hwpx", "b"), ("c.hwpx", "c"))
    sections, flat = m.build_sections(rows, key_of=lambda r: r["key"])
    assert flat is False
    assert [s["group"] for s in sections] == ["가그룹", "나그룹", ""]  # 이름순 + 「그룹 없음」 마지막
    assert sections[-1]["count"] == 1 and sections[-1]["items"][0]["name"] == "c"


def test_sections_flat_when_no_named_groups(home):
    """퇴화 불변식 — 그룹 0개면 flat=True(헤더 없는 평면), 무그룹 1구획으로 반환."""
    m = TemplateGroupModel("hwpx")
    rows = _rows(("a.hwpx", "a"), ("b.hwpx", "b"))
    sections, flat = m.build_sections(rows, key_of=lambda r: r["key"])
    assert flat is True
    assert len(sections) == 1 and sections[0]["group"] == "" and sections[0]["count"] == 2


def test_sections_collapse_projection(home):
    m = TemplateGroupModel("hwpx")
    m.set_group("a.hwpx", "입찰")
    m.toggle_collapse("입찰")
    rows = _rows(("a.hwpx", "a"), ("b.hwpx", "b"))
    sections, flat = m.build_sections(rows, key_of=lambda r: r["key"])
    by_group = {s["group"]: s for s in sections}
    assert by_group["입찰"]["collapsed"] is True
    assert by_group[""]["collapsed"] is False  # 접힘 지정 안 된 「그룹 없음」


def test_sections_orphan_assignment_falls_to_ungrouped(home):
    """고아 지정(파일은 있지만 그 파일이 목록에 없음) 아닌, 지정된 그룹이 목록 밖이면 그 행은
    「그룹 없음」에 뜬다 — build_sections 는 넘어온 live 행만 묶으므로 자동 성립(결정 8)."""
    m = TemplateGroupModel("hwpx")
    m.set_group("moved.hwpx", "입찰")  # 이 키의 파일이 이동/개명돼 아래 목록엔 다른 키만 온다
    rows = _rows(("현재.hwpx", "현재"))  # moved.hwpx 는 목록에 없다
    sections, flat = m.build_sections(rows, key_of=lambda r: r["key"])
    assert flat is True  # 명명 그룹의 live 멤버 0 → 평면
    assert sections[0]["group"] == "" and sections[0]["items"][0]["name"] == "현재"
