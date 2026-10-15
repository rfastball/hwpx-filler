"""계약 결속 조각의 단위 판정(#1193) — 등록 데이터 후보·읽기·선택 결속·불러오기 결과의 갈래.

제품 동선(불러오기·데이터 선택)은 ``test_work_package_autobind.py`` 가 실제 조립으로 잰다. 여기는
그 동선이 드물게만 밟는 갈래(파일이 아닌 등록·깨진 시트 선언·보관 항목·같은 데이터 두 번·
쓰기 거절·목록 읽기 실패)를 값으로 고정한다.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from hwpxfiller.domain.data_contract_check import JobContractFit, profile_data_contract
from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.contract_data_binding import ContractBindingRefused, bind_contract_data
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.webapp.contract_binding import (
    AUTOBIND_BOUND,
    AUTOBIND_NO_CONTRACT,
    AUTOBIND_REFUSED,
    ContractDataBinding,
    DataReading,
    ImportAutobinder,
    choose_binding,
    contract_mismatch_line,
    read_binding,
    registered_bindings,
)

MAPPING = MappingProfile(mappings=[FieldMapping("금액", source="계약금액", type="amount")])
RECORDS = [{"계약금액": "1000"}, {"계약금액": "2000"}]


def _contract_job(name: str = "받은작업", **extra) -> Job:
    return Job(
        name=name, mapping=MAPPING, data_contract=profile_data_contract(MAPPING, RECORDS), **extra
    )


def _csv(path, *rows: str):
    path.write_text("\n".join(("계약금액", *rows)) + "\n", encoding="utf-8-sig")
    return path


def _session(path: str = "d.csv", records=None, *, generation: int = 1, bound=()):
    return SimpleNamespace(
        path=path, sheet="", header_row=0, kind="",
        records=list(RECORDS if records is None else records),
        snapshot_generation=generation,
        bound_jobs=lambda jobs: [job for job in jobs if job.name in bound],
    )


# ------------------------------------------------------------------ 등록 데이터 후보


def test_registered_bindings_cover_declared_sheets_once_and_skip_non_file_missing_archived(tmp_path):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    book = tmp_path / "책.xlsx"
    book.write_bytes(b"")
    pool.add(DatasetReference(
        name="책", kind="excel", opts={"path": str(book), "sheet": "가", "sheets": ["가", "나"]},
    ))
    pool.add(DatasetReference(name="같은 책", kind="excel", opts={"path": str(book), "sheet": "나"}))
    broken = pool.slot_path(pool.add(DatasetReference(
        name="깨진 선언", kind="excel", opts={"path": str(book), "sheet": "다"},
    )))
    raw = json.loads(broken.read_text(encoding="utf-8"))
    raw["opts"]["sheets"] = ["가"]  # 앱 밖 편집 — 기본 시트가 선언에 없는 손상 항목은 후보가 아니다
    broken.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    pool.add(DatasetReference(name="없는 파일", kind="excel", opts={"path": str(tmp_path / "없음.csv")}))
    archived = pool.add(DatasetReference(name="보관", kind="excel", opts={"path": str(_csv(tmp_path / "보관.csv"))}))
    pool.archive(archived)
    pool.add(DatasetReference(name="나라", kind="nara", opts={}))

    assert sorted(registered_bindings(pool)) == [
        (str(book), "가", 0, ""), (str(book), "나", 0, ""),
    ]


def test_read_binding_reads_a_file_and_turns_failure_into_unknown(tmp_path):
    data = _csv(tmp_path / "받은.csv", "3000")
    reading = read_binding((str(data), "", 0, ""))
    assert reading.columns == ("계약금액",) and [dict(r) for r in reading.records] == [{"계약금액": "3000"}]
    assert read_binding((str(tmp_path / "없음.csv"), "", 0, "")).columns is None


def test_contract_mismatch_line_is_empty_without_failures():
    assert contract_mismatch_line(JobContractFit(False)) == ""
    assert contract_mismatch_line(JobContractFit(False, (("금액", "데이터에 없음"),))) == (
        "꾸러미 조건과 다른 연결: 금액(데이터에 없음)"
    )


# ------------------------------------------------------------------ 데이터 선택 뒤


def test_unwired_binding_proposes_only_bound_jobs_and_never_binds():
    unwired = ContractDataBinding()
    job, other = _contract_job(), _contract_job("결속된작업", data_path="d.csv")
    data = _session(bound={"결속된작업"})
    assert unwired.candidates(data, [job, other]) == [other]
    assert unwired.bind_for_selection(job, data) == (job, "")


def test_fit_is_computed_once_per_mount_and_recomputed_on_a_new_mount():
    calls: "list[str]" = []

    def bind(job, binding):
        calls.append(binding[0])
        return job

    binding = ContractDataBinding(bind)
    job = _contract_job()
    first = _session()
    assert binding.candidates(first, [job]) == [job]
    assert binding.candidates(first, [job]) == [job]
    failing = _session(records=[{"계약금액": "미정"}], generation=2)
    assert binding.candidates(failing, [job]) == []
    selected, line = binding.bind_for_selection(job, failing)
    assert selected is job and line.startswith("꾸러미 조건과 다른 연결: 금액(")
    assert calls == []


def test_refused_bind_keeps_the_job_unbound_without_a_line():
    def refuse(job, binding):
        raise ContractBindingRefused()

    job = _contract_job()
    assert ContractDataBinding(refuse).bind_for_selection(job, _session()) == (job, "")


# ------------------------------------------------------------------ 불러오기 직후


def test_import_autobinder_skips_reading_when_no_job_carries_a_contract(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(Job(name="일반", mapping=MAPPING))

    def never(_binding):
        raise AssertionError("계약이 없으면 등록 데이터를 읽지 않는다")

    binder = ImportAutobinder(registry, DatasetPoolRegistry(tmp_path / "pool"), read=never)
    assert [(o.name, o.status) for o in binder.bind_imported(["일반"])] == [("일반", AUTOBIND_NO_CONTRACT)]


def test_import_autobinder_reports_a_refused_write_and_an_unreadable_registry(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(_contract_job())
    pool = DatasetPoolRegistry(tmp_path / "pool")
    data = _csv(tmp_path / "받은.csv", "3000")
    pool.add(DatasetReference(name="받은", kind="excel", opts={"path": str(data)}))
    binding = (str(data), "", 0, "")

    def read_then_bind_elsewhere(candidate):
        registry.mutate("받은작업", lambda job: setattr(job, "data_path", "다른.csv"))
        return DataReading(candidate, ("계약금액",), [{"계약금액": "3000"}])

    racing = ImportAutobinder(registry, pool, read=read_then_bind_elsewhere)
    assert [(o.status, o.binding) for o in racing.bind_imported(["받은작업"])] == [(AUTOBIND_REFUSED, None)]

    registry.save(_contract_job(), allow_overwrite=True)
    assert ImportAutobinder(registry, pool).bind_imported(["받은작업"])[0].binding == binding
    assert registry.load("받은작업").data_path == str(data)
    assert [o.status for o in ImportAutobinder(registry, pool).bind_imported(["없는작업"])] == [AUTOBIND_REFUSED]
    assert AUTOBIND_BOUND != AUTOBIND_REFUSED


def test_jobs_without_a_contract_are_never_chosen_or_written(tmp_path):
    plain = Job(name="일반", mapping=MAPPING)
    reading = DataReading(("d.csv", "", 0, ""), ("계약금액",), RECORDS)
    assert choose_binding(plain, [reading]) == (AUTOBIND_NO_CONTRACT, None)
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(plain)
    for job, binding in ((plain, reading.binding), (_contract_job(), ("", "", 0, ""))):
        try:
            bind_contract_data(registry, job, binding)
        except ContractBindingRefused:
            continue
        raise AssertionError("계약 없는 작업·경로 없는 결속은 쓰지 않는다")
    assert registry.load("일반").data_path == ""
