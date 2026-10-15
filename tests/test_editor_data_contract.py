"""편집기의 데이터 계약 자동확정(#1188 WP-02) — 헤드리스 컨트롤러로 실제 데이터 채택 경로를 탄다.

데이터를 바꾸면 이월한 연결의 확정이 전원 풀린다(C1). 계약을 든 작업만 예외로, 계약을 통과한
행은 「자동확정 · 꾸러미 조건 일치」로 확정되고 통과하지 못한 행은 Python 이 지은 사유와 함께
미확정으로 남는다. 계약이 없는 작업은 종전 그대로다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hwpxfiller.domain.data_contract_check import profile_data_contract
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.template_root import TemplateRoot
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_template import TemplateController

CONTRACT_LABEL = "자동확정 · 꾸러미 조건 일치"
HEADER = "공고명,추정가격,계약일자"
SENDER = [
    {"공고명": "전산장비 구매", "추정가격": "24750000", "계약일자": "2026-06-15"},
    {"공고명": "사무용품", "추정가격": "1,200,000원", "계약일자": "2026-07-01"},
]
MAPPING = MappingProfile(mappings=[
    FieldMapping("건명", "공고명"),
    FieldMapping("금액", "추정가격", type="amount"),
    FieldMapping("계약일", "계약일자", type="date"),
    FieldMapping("담당", type="const", const="홍길동"),
])


def _controller(tmp_path: Path) -> EditorController:
    root = tmp_path / "text_templates"
    registry = TextTemplateRegistry(root)
    channel = TemplateController(
        registry,
        lambda s, snap: None,
        file_store=TemplateFileStore(root, registry),
        template_root=TemplateRoot(default_root=root),
        pool_registry=DatasetPoolRegistry(tmp_path / "datasets"),
    )
    return EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: None,
        clock=lambda: datetime(2026, 10, 15, 9, 0, 0),
        is_library_path=channel.is_live_path,
        template_root=TemplateRoot(default_root=root),
    )


def _save_job(tmp_path: Path, *, with_contract: bool) -> Path:
    """꾸러미로 받은 꼴의 작업 — 데이터 결속 없이 연결과(있으면) 계약만 든다."""
    root = tmp_path / "text_templates"
    root.mkdir(parents=True, exist_ok=True)
    template = root / "공고.txt"
    template.write_text("{{건명}} {{금액}} {{계약일}} {{담당}}", encoding="utf-8")
    JobRegistry(tmp_path / "jobs").save(Job(
        name="받은작업",
        template_path=str(template),
        mapping=MAPPING,
        data_contract=profile_data_contract(MAPPING, SENDER) if with_contract else None,
    ))
    return template


def _csv(tmp_path: Path, *rows: str, header: str = HEADER) -> str:
    path = tmp_path / "받은데이터.csv"
    path.write_text("\n".join((header, *rows)) + "\n", encoding="utf-8-sig")
    return str(path)


def _rows(ctrl: EditorController) -> "dict[str, dict]":
    return {row["template_field"]: row for row in ctrl.snapshot()["rows"]}


def test_contract_rows_auto_confirm_on_clean_received_data_and_save(tmp_path):
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01", "경비,700000원,2026-10-02"))

    rows = _rows(ctrl)
    assert all(row["confirmed"] for row in rows.values())
    assert {row["state_label"] for row in rows.values()} == {CONTRACT_LABEL}
    assert all(row["contract_reason"] == "" for row in rows.values())
    snap = ctrl.snapshot()
    assert snap["is_complete"] is True
    assert snap["notice"]["text"] == (
        "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. "
        "이월한 4개 행 중 4개 행은 꾸러미 조건과 일치해 자동확정했습니다."
    )
    assert ctrl.dispatch("save", {})["ok"] is True


def test_unreadable_date_leaves_only_that_row_unconfirmed_with_its_reason(tmp_path):
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01", "경비,700000,추후 협의"))

    rows = _rows(ctrl)
    assert rows["계약일"]["confirmed"] is False
    assert rows["계약일"]["contract_reason"] == "날짜로 읽히지 않는 값 1행"
    assert rows["계약일"]["state_label"] == "확인 필요"
    assert all(rows[name]["confirmed"] for name in ("건명", "금액", "담당"))
    snap = ctrl.snapshot()
    assert snap["is_complete"] is False
    assert "이월한 4개 행 중 3개 행은" in snap["notice"]["text"]
    assert snap["notice"]["text"].endswith("확인이 필요한 행을 다시 확정하세요.")

    # 사람이 확인하면 계약 판정이 아니라 사람의 확인이다 — 사유·계약 표지가 걷힌다.
    ctrl.dispatch("set_confirmed", {"index": rows["계약일"]["index"], "confirmed": True})
    row = _rows(ctrl)["계약일"]
    assert row["confirmed"] and row["state_label"] == "확인" and row["contract_reason"] == ""


def test_missing_column_is_named_as_the_reason(tmp_path):
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000", header="공고명,추정가격"))

    row = _rows(ctrl)["계약일"]
    assert row["confirmed"] is False and row["contract_reason"] == "데이터에 없음"


def test_editing_a_contract_row_clears_its_label_and_never_re_auto_confirms(tmp_path):
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    first = _csv(tmp_path, "청소용역,5000000,2026-09-01")
    ctrl.load_data_path(first)
    index = _rows(ctrl)["계약일"]["index"]
    ctrl.dispatch("set_display", {"index": index, "type": "date", "fmt": "kor"})
    assert _rows(ctrl)["계약일"]["state_label"] == "확인 필요"

    ctrl.load_data_path(str(_csv_other(tmp_path)))
    row = _rows(ctrl)["계약일"]
    assert row["confirmed"] is False and row["contract_reason"] == "꾸러미와 연결이 다름"


def _csv_other(tmp_path: Path) -> Path:
    path = tmp_path / "또다른데이터.csv"
    path.write_text(HEADER + "\n시설공사,9000000,2026-11-11\n", encoding="utf-8-sig")
    return path


def test_job_without_contract_keeps_the_reconfirm_rule(tmp_path):
    _save_job(tmp_path, with_contract=False)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01"))

    rows = _rows(ctrl)
    assert all(row["confirmed"] is False for row in rows.values())
    assert all(row["contract_reason"] == "" for row in rows.values())
    snap = ctrl.snapshot()
    assert snap["is_complete"] is False
    assert snap["notice"]["text"] == (
        "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 직접 확인하거나 편집한 4개 행의 "
        "소스·유형·서식은 이월했습니다. 확인이 필요한 행을 다시 확정하세요."
    )


def test_contract_survives_editor_save_and_reload(tmp_path):
    _save_job(tmp_path, with_contract=True)
    registry = JobRegistry(tmp_path / "jobs")
    contract = registry.load("받은작업").data_contract
    assert contract is not None
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01"))
    assert ctrl.dispatch("save", {})["ok"] is True

    saved = registry.load("받은작업")
    assert saved.data_contract == contract
    assert saved.data_path.endswith("받은데이터.csv")
    # 계약은 규칙이 아니다 — 연결이 그대로면 판본이 오르지 않는다.
    assert saved.binding_revision == 1


# ------------------------------------------------- 데이터 교체 확인의 수(#1193)


def _stakes(ctrl: EditorController, cause: str) -> int:
    return ctrl.dispatch("mapping_reset_stakes", {"cause": cause})["human"]


def test_data_swap_confirm_does_not_count_untouched_contract_rows(tmp_path):
    """계약이 다시 판정할 행은 사람이 만든 것을 잃지 않는다 — 확인이 그 행을 세지 않는다."""
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    assert len(_rows(ctrl)) == 4 and all(row["confirmed"] for row in _rows(ctrl).values())
    assert _stakes(ctrl, "data") == 0

    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01"))
    assert _stakes(ctrl, "data") == 0, "자동확정 뒤에도 같은 연결은 다시 판정된다"


def test_data_swap_confirm_counts_only_rows_edited_after_import(tmp_path):
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    ctrl.load_data_path(_csv(tmp_path, "청소용역,5000000,2026-09-01"))
    ctrl.dispatch("set_display", {"index": _rows(ctrl)["계약일"]["index"], "type": "date", "fmt": "kor"})
    assert _stakes(ctrl, "data") == 1
    ctrl.dispatch("set_const", {"index": _rows(ctrl)["담당"]["index"], "const": "김철수"})
    assert _stakes(ctrl, "data") == 2, "데이터를 읽지 않는 연결도 저장본과 달라지면 센다"


def test_template_swap_without_data_still_counts_contract_rows(tmp_path):
    """판정할 데이터가 없는 재조립은 계약이 다시 확정하지 못한다 — 이월 행 전부를 센다(C1)."""
    _save_job(tmp_path, with_contract=True)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    assert _stakes(ctrl, "template") == 4


def test_job_without_contract_counts_every_carried_row(tmp_path):
    _save_job(tmp_path, with_contract=False)
    ctrl = _controller(tmp_path)
    ctrl.load_job("받은작업")
    assert _stakes(ctrl, "data") == 4
