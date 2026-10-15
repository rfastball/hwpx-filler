"""데이터 계약을 든 작업의 편집기 없는 결속(#1193) — 불러오기 직후 자동 결속과 데이터 선택 뒤 결속.

같은 열의 데이터를 이미 가진 받는 사람은 꾸러미를 불러온 뒤 편집기·데이터 고르기·저장 없이 바로
「문서 만들기」에서 문서를 만든다. 조립은 제품 그대로(:class:`~hwpxfiller.webapp.app.WebFrontend`)이고
편집기 진입은 실패로 막아 두어 「편집기 방문 0」을 결과로 잰다.

- A — 받는 쪽 등록 데이터 가운데 계약을 통과하는 것이 정확히 하나면 결속한다. 둘이면·값이 맞지
  않으면 결속하지 않는다. 등록 데이터를 읽지 못해도 불러오기는 성공이다.
- B — 미결속 작업은 마운트한 데이터가 계약을 통과하면 후보로 서고, 고르면 결속되어 생성까지 간다.
  통과하지 못하면 결속 없이 Python 사유 줄이 안내에 실린다.
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder
from _work_package_homes import (
    export,
    frontend,
    import_package,
    inspect,
    sender_home,
    use_home,
)

from hwpxfiller.domain.data_contract import DataContract
from hwpxfiller.domain.data_contract_check import judge_job_contract
from hwpxfiller.domain.job import Job, data_binding_of
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.contract_data_binding import ContractBindingRefused, bind_contract_data
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.host.locations import default_dataset_pool_dir, default_jobs_dir
from hwpxfiller.webapp.contract_binding import (
    AUTOBIND_AMBIGUOUS,
    AUTOBIND_BOUND,
    AUTOBIND_NO_MATCH,
    AUTOBIND_UNREADABLE,
    CONTRACT_MISMATCH_HEAD,
    DataReading,
    choose_binding,
)
from hwpxfiller.webapp.work_package_panel import IMPORTED_NEXT_STEP

NAMES = ("계약A", "계약B")


@pytest.fixture
def package(monkeypatch, tmp_path):
    """홈 A 가 내보낸 꾸러미(작업 둘 · 템플릿 하나)와 A 의 데이터 파일."""
    app, data = sender_home(monkeypatch, tmp_path, *NAMES)
    path = tmp_path / "보낸작업.narumi"
    assert export(app, NAMES, path)["ok"] is True
    return path, data


def _receiver(monkeypatch, tmp_path: Path, home: str = "home-b"):
    use_home(monkeypatch, tmp_path / home)
    app = frontend()

    def no_editor(*_args, **_kwargs):
        raise AssertionError("편집기를 거치지 않아야 한다")

    editor = app.controllers["editor"]
    monkeypatch.setattr(editor, "load_job", no_editor)
    monkeypatch.setattr(editor, "load_data_path", no_editor)
    return app


def _copy(source: Path, target: Path, *, amount: "str | None" = None) -> Path:
    """보낸 쪽 데이터의 사본 — ``amount`` 를 주면 계약금액 열을 그 값으로 바꾼다."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if amount is None:
        shutil.copy2(source, target)
        return target
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, "계약금액": amount} for row in rows)
    return target


def _register(app, path: Path, name: str) -> str:
    result = app.dispatch("pool", "register_excel", {"name": name, "path": str(path)})
    assert result["ok"] is True, result
    entries = DatasetPoolRegistry(default_dataset_pool_dir()).list_entries()
    return next(key for key, item in entries if item.name == name)


def _import_all(app, path: Path) -> dict:
    result = import_package(app, path, inspect(app, path)["basis"])
    assert result["ok"] is True, result
    return result


def _job(name: str) -> Job:
    return JobRegistry(default_jobs_dir()).load(name)


def _generate(app, name: str, out: Path) -> dict:
    """「문서 만들기」의 제품 동선 — 작업 선택(결속 데이터 마운트)·전체 선택·저장 폴더·생성."""
    app.dispatch("job", "select_job", {"name": name})
    app.dispatch("job", "set_all", {})
    pick_output_folder(app.controllers["job"], out)
    app.dispatch("job", "resolve_execution", {})
    return app.generate("job")


def _candidate_names(app) -> "list[str]":
    return [card["name"] for card in app.controllers["job"].snapshot()["candidates"]["top"]]


# ------------------------------------------------------------------ A — 불러오기 직후


def test_import_binds_to_the_single_registered_data_that_passes_and_generates_without_editor(
    package, monkeypatch, tmp_path,
):
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    mine = _copy(sender_data, tmp_path / "b-data" / "우리계약.csv")
    _register(app, mine, "우리 계약")

    result = _import_all(app, path)
    assert result["bound"] == list(NAMES)
    assert result["outcomes"] == [{"name": name, "status": AUTOBIND_BOUND} for name in NAMES]
    assert result["message"] == "", "할 일이 남지 않으면 문장을 싣지 않는다"
    for name in NAMES:
        job = _job(name)
        assert data_binding_of(job) == (str(mine), "", 0, "")
        assert (job.template_revision, job.binding_revision, job.reviewed_rules) == (1, 1, {}), (
            "결속은 규칙 축이 아니라 판본·검토 기준선이 움직이지 않는다"
        )

    app.dispatch("job", "select_job", {"name": "계약A"})
    assert app.controllers["job"].snapshot()["data_notice"] is None, (
        "빈 세션에 결속 데이터를 세운 첫 마운트는 버린 것이 없어 낭독하지 않는다"
    )
    for index, name in enumerate(NAMES):
        outcome = _generate(app, name, tmp_path / f"out-{index}")
        assert outcome["ok"] is True and outcome["succeeded"] == 3 and outcome["failed"] == 0


def test_switching_to_bound_data_names_only_a_selection_it_discarded(package, monkeypatch, tmp_path):
    """고른 행이 있는 세션을 작업의 결속 데이터로 갈 때만 「항목 선택은 초기화됐습니다」가 선다."""
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    mine = _copy(sender_data, tmp_path / "b-data" / "우리계약.csv")
    _register(app, mine, "우리 계약")
    _import_all(app, path)
    job = app.controllers["job"]
    job.load_data_path(str(_copy(sender_data, tmp_path / "c-data" / "다른데이터.csv")))
    app.dispatch("job", "set_all", {})

    app.dispatch("job", "select_job", {"name": "계약A"})

    assert job.data.path == str(mine) and job.snapshot()["selected_count"] == 0
    assert job.snapshot()["data_notice"]["text"] == (
        "이 작업에 연결된 데이터 '우리계약.csv' 을(를) 불러왔습니다. 항목 선택은 초기화됐습니다."
    )


def test_two_passing_registered_data_leave_the_jobs_unbound(package, monkeypatch, tmp_path):
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    _register(app, _copy(sender_data, tmp_path / "b-data" / "상반기.csv"), "상반기")
    _register(app, _copy(sender_data, tmp_path / "b-data" / "하반기.csv"), "하반기")

    result = _import_all(app, path)
    assert result["bound"] == []
    assert {item["status"] for item in result["outcomes"]} == {AUTOBIND_AMBIGUOUS}
    assert result["message"] == IMPORTED_NEXT_STEP
    assert all(_job(name).data_path == "" for name in NAMES)


def test_registered_data_failing_the_contract_values_is_not_chosen(package, monkeypatch, tmp_path):
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    _register(app, _copy(sender_data, tmp_path / "b-data" / "미정.csv", amount="미정"), "미정")

    result = _import_all(app, path)
    assert {item["status"] for item in result["outcomes"]} == {AUTOBIND_NO_MATCH}
    assert all(_job(name).data_path == "" for name in NAMES)


def test_unreadable_registered_data_never_fails_the_import(package, monkeypatch, tmp_path):
    """읽지 못한 등록 데이터는 통과했을지 모른다 — 고르지 않고, 불러오기는 그대로 성공한다."""
    from openpyxl import Workbook

    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    _register(app, _copy(sender_data, tmp_path / "b-data" / "우리계약.csv"), "우리 계약")
    book = tmp_path / "b-data" / "깨질책.xlsx"
    workbook = Workbook()
    workbook.active.append(["공고번호"])
    workbook.active.append(["1"])
    workbook.save(book)
    _register(app, book, "깨질 책")
    book.write_bytes(b"not a workbook")

    result = _import_all(app, path)
    assert result["imported"] == list(NAMES)
    assert {item["status"] for item in result["outcomes"]} == {AUTOBIND_UNREADABLE}
    assert all(_job(name).data_path == "" for name in NAMES)


# ------------------------------------------------------------------ B — 데이터 선택 뒤


def test_mounted_data_that_passes_proposes_and_binds_the_unbound_job_without_editor(
    package, monkeypatch, tmp_path,
):
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    assert _import_all(app, path)["bound"] == [], "전제: 불러올 때는 등록 데이터가 없었다"
    key = _register(app, _copy(sender_data, tmp_path / "b-data" / "나중데이터.csv"), "나중 데이터")

    assert app.dispatch("job", "load_pool", {"key": key})["ok"] is True
    assert set(_candidate_names(app)) == set(NAMES), "계약을 통과하는 미결속 작업이 후보로 선다"

    outcome = _generate(app, "계약A", tmp_path / "out")
    assert outcome["ok"] is True and outcome["succeeded"] == 3
    assert data_binding_of(_job("계약A")) == (str(tmp_path / "b-data" / "나중데이터.csv"), "", 0, "")
    assert _job("계약B").data_path == "", "고른 작업만 결속된다"


def test_mounted_data_failing_the_contract_keeps_the_job_unbound_with_python_reasons(
    package, monkeypatch, tmp_path,
):
    path, sender_data = package
    app = _receiver(monkeypatch, tmp_path)
    _import_all(app, path)
    key = _register(app, _copy(sender_data, tmp_path / "b-data" / "미정.csv", amount="미정"), "미정")
    app.dispatch("job", "load_pool", {"key": key})
    assert _candidate_names(app) == [], "계약을 통과하지 못한 미결속 작업은 후보가 아니다"

    app.dispatch("job", "select_job", {"name": "계약A"})
    snapshot = app.controllers["job"].snapshot()
    assert snapshot["job_data_unbound"] is True, "결속이 없으니 「데이터 연결하기…」(편집기)로 간다"
    assert f"{CONTRACT_MISMATCH_HEAD}: 계약금액(금액으로 읽히지 않는 값 3행)" in snapshot["data_notice"]["text"]
    assert _job("계약A").data_path == ""


# ------------------------------------------------------------------ 판정·쓰기 단위


def _contract_job(name: str = "작업") -> Job:
    mapping = MappingProfile(mappings=[FieldMapping("금액", source="계약금액", type="amount")])
    records = [{"계약금액": "1000"}, {"계약금액": "2000"}]
    from hwpxfiller.domain.data_contract_check import profile_data_contract

    return Job(name=name, mapping=mapping, data_contract=profile_data_contract(mapping, records))


def test_job_contract_without_column_evidence_never_fits():
    job = Job(name="고정", mapping=MappingProfile(mappings=[FieldMapping("기관", type="const", const="가")]))
    fit = judge_job_contract(DataContract(fields=()), job.mapping, ["아무 열"], [{"아무 열": "x"}])
    assert fit.passed is False and fit.failures == ()


def test_choose_binding_needs_exactly_one_fit_and_no_unreadable_data():
    job = _contract_job()
    good = DataReading(("a.csv", "", 0, ""), ("계약금액",), [{"계약금액": "5"}])
    other = DataReading(("b.csv", "", 0, ""), ("계약금액",), [{"계약금액": "7"}])
    bad = DataReading(("c.csv", "", 0, ""), ("계약금액",), [{"계약금액": "미정"}])
    unreadable = DataReading(("d.csv", "", 0, ""), None)
    assert choose_binding(job, [good, bad]) == (AUTOBIND_BOUND, good.binding)
    assert choose_binding(job, [good, other]) == (AUTOBIND_AMBIGUOUS, None)
    assert choose_binding(job, [bad]) == (AUTOBIND_NO_MATCH, None)
    assert choose_binding(job, [good, unreadable]) == (AUTOBIND_UNREADABLE, None)


def test_bind_contract_data_refuses_a_job_that_changed_or_got_bound(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    judged = _contract_job()
    registry.save(judged)
    binding = (str(tmp_path / "a.csv"), "", 0, "")

    edited = registry.load("작업")
    edited.filename_pattern = "다른 {{금액}}"
    registry.save(edited, allow_overwrite=True)
    with pytest.raises(ContractBindingRefused):
        bind_contract_data(registry, judged, binding)
    assert registry.load("작업").data_path == ""

    fresh = registry.load("작업")
    assert data_binding_of(bind_contract_data(registry, fresh, binding)) == binding
    with pytest.raises(ContractBindingRefused):
        bind_contract_data(registry, fresh, (str(tmp_path / "b.csv"), "", 0, ""))
    assert registry.load("작업").data_path == binding[0], "이미 결속된 작업은 덮지 않는다"
