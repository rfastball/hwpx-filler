"""저장 폴더 존 — 두 표면이 **같은 함수**를 지나는가(U6-D #978).

이 파일이 지키는 것은 값 하나가 아니라 **출처의 단일성**이다. 링0 판정이 하나여도 관찰과
존 성형이 화면마다 손으로 쓰여 있으면, 한쪽만 하향 사유를 빠뜨리는 자리가 그대로 남는다 —
그리고 그 갈림은 「같은 질문에 두 답」이라 조용히 틀린다.
"""

from pathlib import Path

from hwpxfiller.domain.output_folder_default import (
    SOURCE_REMEMBERED,
    SOURCE_TEMPLATE_DEFAULT,
)
from hwpxfiller.webapp.output_folder_zone import output_folder_zone


def test_zone_carries_the_settings_folder_when_it_exists(tmp_path: Path) -> None:
    picked = tmp_path / "내보내기"
    picked.mkdir()
    zone = output_folder_zone(
        template_path=str(tmp_path / "t" / "공고서.hwpx"),
        remembered_directory=str(picked),
    )
    assert zone["directory"] == str(picked)
    assert zone["source"] == SOURCE_REMEMBERED
    assert zone["source_label"] == "설정한 저장 폴더"
    assert zone["notice"] == ""


def test_vanished_settings_folder_falls_back_loudly(tmp_path: Path) -> None:
    """존재 확인은 **관찰**이고 이 함수가 진다 — 사라진 폴더의 조용한 재사용 금지."""
    template = tmp_path / "t" / "공고서.hwpx"
    zone = output_folder_zone(
        template_path=str(template),
        remembered_directory=str(tmp_path / "없는폴더"),
    )
    assert zone["directory"] == str(template.parent / "Results")
    assert zone["source"] == SOURCE_TEMPLATE_DEFAULT
    assert zone["notice"], "하향은 사유와 함께 온다(조용한 하향 금지)."


def test_zone_is_empty_when_nothing_can_be_derived() -> None:
    zone = output_folder_zone(template_path="", remembered_directory="")
    assert zone == {"directory": "", "source": "", "source_label": "", "notice": ""}


def test_both_screens_read_the_same_function(tmp_path, monkeypatch) -> None:
    """작업 화면의 존과 편집기의 존이 **같은 함수 결과**인가 — 재조립이 있으면 갈린다.

    두 컨트롤러를 실제로 세우고 같은 템플릿·같은 설정값에서 두 존을 나란히 읽는다. 종전
    결함류(#905)의 얼굴이 정확히 이것이었다: 갈래마다 다른 자리에서 경로를 조립해 고른
    폴더가 갈래에 따라 조용히 무시됐다.
    """
    from datetime import datetime

    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.webapp.screen_editor import EditorController

    picked = tmp_path / "고른폴더"
    picked.mkdir()
    monkeypatch.setattr(
        "hwpxfiller.webapp.screen_editor.load_last_output_directory", lambda: str(picked)
    )
    template = tmp_path / "t" / "공고서.hwpx"
    editor = EditorController(
        JobRegistry(tmp_path / "jobs"), lambda screen, snap: None, clock=datetime.now,
    )
    editor.template_path = str(template)

    assert editor.snapshot()["output_folder"] == output_folder_zone(
        template_path=str(template), remembered_directory=str(picked),
    )
