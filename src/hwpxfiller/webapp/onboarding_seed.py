"""What each lesson's practice home holds before its first beat (#1126 · #1127).

Every name here is fixed so the beat text can name it exactly: no lesson title, batch id or
other runtime tail is ever part of a seeded job or file name. Seeding is an explicit course
prerequisite saved in the lesson home; it never awards prior evidence of a beat.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..domain.dataset_reference import DatasetReference
from ..domain.job import JOB_MAPPING_AUTHORITY, Job
from ..domain.mapping import FieldMapping, MappingProfile
from ..domain.schema import infer_type
from ..external.dataset_store import DatasetPoolRegistry
from ..external.job_store import JobRegistry
from ..external.tutorial_practice import fingerprint
from ..external.tutorial_workspace import DATA_NAME

__all__ = ["DERIVED", "TXT_NAME", "seed_before_switch", "seed_after_switch"]

HWPX_NAME = "물품 구매입찰 공고.hwpx"
TXT_NAME = "낙찰자 선정 및 계약체결 안내.txt"
PURCHASE_NAME = "계약방법 결정 및 구매추진 안내.txt"

#: 공고서 머리에만 쓰이는 날짜 필드(#1145). 다른 날짜 필드(입찰개시일시 등)는 시각까지
#: 그대로 두고, 머리 문구에 박히는 이 필드만 공문서 표준 연·월 표시형으로 시드한다.
HEAD_DATE_FIELD = "게시일시"
#: `domain.format_engine` 의 예약 표시형 코드 — 「표준(연·월)」(예: 2026. 10.).
HEAD_DATE_FMT = "ym"

#: lesson → (derived data kind, its fixed file name, its sheet).
DERIVED = {
    "replace_data": ("replacement", "공고목록(새 판).xlsx", "공고"),
    "blank_values": ("blank", "공고목록(빈 칸).xlsx", "계약"),
}

#: lesson → (job name, template, data: original or the derived copy, sheet).
_JOBS = {
    "replace_data": ("공고서 작업", HWPX_NAME, "original", "공고"),
    "purchase_txt": ("구매추진 안내 작업", PURCHASE_NAME, "original", "공고"),
    "blank_values": ("계약 안내 작업(빈 칸)", TXT_NAME, "derived", "계약"),
    "change_apply": ("계약 안내 작업", TXT_NAME, "original", "계약"),
}

#: Lessons that choose data from the registered list with one press (#1127 decision 3).
_POOL_LESSONS = {"first_hwpx", "contract_txt"}
_POOL_SHEETS = ("공고", "계약")
#: lesson → sheet → saved filters on that registered sheet: the notice lesson presses one chip
#: instead of finding the 메모 column off to the right of the table (#1136).
_POOL_FILTERS = {"first_hwpx": {"공고": [{"name": "소상공인", "state": {"columns": {"메모": {"text": "소상공인"}}}}]}}

_SOURCE_OVERRIDES = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화", "대표계약업체": "계약상대자"}
_PARAGRAPH = re.compile(r"^3\. .*$", re.MULTILINE)
_SLOT_BLOCK = ("{{{{#항목 예산재배정 예산재배정}}}}\n{{{{#선택 안내포함 안내포함}}}}\n{paragraph}\n"
               "{{{{/선택}}}}\n{{{{#선택 안내생략 안내생략}}}}\n\n{{{{/선택}}}}\n{{{{/항목}}}}")


def seed_before_switch(tutorial: Any, lesson_id: str, home: Path) -> None:
    """Files and the saved job, written into the home before the practice graph assembles."""
    ctx = tutorial._context()
    if lesson_id == "option_apply":
        # One empty line inside the paragraph's future item is what '안내생략' will hold.
        _rewrite_txt(ctx, lambda text: _PARAGRAPH.sub(lambda match: match.group(0) + "\n", text, count=1))
    job = _JOBS.get(lesson_id)
    if job is not None:
        _save_job(tutorial, home, *job)
    if lesson_id in _POOL_LESSONS:
        # Same home layout as the practice graph's registry (``datasets/``), written before it assembles.
        registry = DatasetPoolRegistry(home / "datasets")
        filters = _POOL_FILTERS.get(lesson_id, {})
        ctx["pool_keys"] = {sheet: registry.add(DatasetReference(
            name=Path(DATA_NAME).stem, kind="excel",
            opts={"path": tutorial._asset(DATA_NAME), "sheet": sheet, "header_row": 1},
            filters=filters.get(sheet, [])))
            for sheet in _POOL_SHEETS}


def seed_after_switch(tutorial: Any, lesson_id: str) -> None:
    """State that lives in the practice graph: the open editor, job or document."""
    ctx = tutorial._context()
    if lesson_id == "purchase_txt":
        tutorial._editor().load_job(ctx["job_name"])
    if lesson_id == "change_apply":
        # The job is seated on the original template; the template then gains the item the
        # previous lesson builds, so the change is there to apply.
        tutorial._job().dispatch("prefer_work", {"name": ctx["job_name"]})
        _rewrite_txt(ctx, lambda text: _PARAGRAPH.sub(
            lambda match: _SLOT_BLOCK.format(paragraph=match.group(0)), text, count=1))
    # The authoring lessons no longer open the practice TXT here: their first beats have the user open it from the
    # template list (#1146), the way '저장' then writes the library template in place.
    tutorial.switch.refresh()


def _rewrite_txt(ctx: dict, change) -> None:
    entry = ctx["assets"][TXT_NAME]
    path = Path(entry["path"])
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    entry["sha256"] = fingerprint(path)


def _save_job(tutorial: Any, home: Path, name: str, template: str, data: str, sheet: str) -> None:
    ctx = tutorial._context()
    template_path = tutorial._asset(template)
    data_path = ctx.get("derived_data_path") if data == "derived" else tutorial._asset(DATA_NAME)
    if not template_path or not data_path:
        raise ValueError("연습 파일을 먼저 준비하세요.")
    is_txt = template.endswith(".txt")
    job = Job(name=name, template_path=template_path,
              mapping=_mapping(_template_fields(template_path, is_txt), blank_unit=data == "derived"),
              filename_pattern="" if is_txt else "구매입찰공고-{{입찰공고번호}}",
              data_path=data_path, data_sheet=sheet, binding_authority=JOB_MAPPING_AUTHORITY)
    JobRegistry(home / "jobs", template_root=lambda: home / "templates").save(job)
    ctx["job_name"] = name
    ctx["seeded"] = True
    ctx["seed_notice"] = f"이 과정용 연습 작업 '{name}'을 준비했습니다. 다른 과정의 완료 기록은 바꾸지 않습니다."


def _template_fields(template_path: str, is_txt: bool) -> list[str]:
    if is_txt:
        content = Path(template_path).read_text(encoding="utf-8")
        return list(dict.fromkeys(re.findall(r"\{\{([^{}#/]+)\}\}", content)))
    from ..domain.schema import extract_schema
    from ..external.hwpx_package_io import read_hwpx_package

    return [field.name for field in extract_schema(read_hwpx_package(template_path)).fields]


def _mapping(fields: list[str], *, blank_unit: bool) -> MappingProfile:
    """Name-matched columns with the editor's name-inferred date and amount types."""
    def row(field: str) -> FieldMapping:
        if blank_unit and field == "단위":
            return FieldMapping("단위", type="const")  # 일부러 비워 둔 항목(비움 확정)
        kind = infer_type(field)
        kind = kind if kind in {"date", "amount"} else "text"
        fmt = HEAD_DATE_FMT if field == HEAD_DATE_FIELD and kind == "date" else ""
        return FieldMapping(field, _SOURCE_OVERRIDES.get(field, field), type=kind, fmt=fmt)

    return MappingProfile(mappings=[row(field) for field in fields])
