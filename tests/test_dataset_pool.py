"""데이터셋 풀(J1) 헤드리스 테스트 — 참조 직렬화·상태 전이·복원(네트워크·실 저장소 무접촉).

보안 불변식(나라 항목에 ServiceKey 비직렬화)과 복원 시 키 주입을 못박는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_RETIRED,
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from hwpxfiller.core.job import SlugCollisionError
from hwpxfiller.data.excel import ExcelDataSource
from hwpxfiller.data.factory import source_from_pool_item
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


# ------------------------------------------------------------------ 모델
def test_item_roundtrip_to_from_dict():
    it = DatasetPoolItem(
        name="6월 공고", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359", "num_rows": 100},
        created_at="2026-07-12T09:00:00", note="6월분",
    )
    back = DatasetPoolItem.from_dict(it.to_dict())
    assert back == it
    assert back.status == STATUS_ACTIVE  # 기본 active


def test_unknown_status_rejected():
    with pytest.raises(ValueError):
        DatasetPoolItem(name="x", kind="excel", status="bogus")


def test_status_transitions():
    it = DatasetPoolItem(name="x", kind="excel", opts={"path": "/d.xlsx"})
    assert it.is_active
    it.archive()
    assert it.status == STATUS_ARCHIVED and not it.is_active
    it.retire()
    assert it.status == STATUS_RETIRED
    it.activate()
    assert it.is_active


def test_from_dict_backward_compatible_defaults():
    it = DatasetPoolItem.from_dict({"name": "구", "kind": "excel"})
    assert it.opts == {} and it.status == STATUS_ACTIVE and it.note == ""


# ------------------------------------------------------------------ 레지스트리
def test_registry_save_load_list_delete(tmp_path):
    reg = DatasetPoolRegistry(tmp_path)
    assert reg.list_items() == []
    reg.save(DatasetPoolItem(name="B", kind="excel", opts={"path": "/b.xlsx"}))
    reg.save(DatasetPoolItem(name="A", kind="excel", opts={"path": "/a.xlsx"}))
    assert reg.names() == ["A", "B"]  # 이름순
    assert reg.exists("A")
    assert reg.load("A").opts["path"] == "/a.xlsx"
    reg.delete("A")
    assert not reg.exists("A")
    assert reg.names() == ["B"]


def test_registry_filters_by_status(tmp_path):
    reg = DatasetPoolRegistry(tmp_path)
    active = DatasetPoolItem(name="살아있음", kind="excel", opts={"path": "/x.xlsx"})
    retired = DatasetPoolItem(name="은퇴", kind="excel", opts={"path": "/y.xlsx"})
    retired.retire()
    reg.save(active)
    reg.save(retired)
    assert [it.name for it in reg.list_items(status=STATUS_ACTIVE)] == ["살아있음"]
    assert len(reg.list_items()) == 2


def test_registry_save_rejects_slug_collision_different_name(tmp_path):
    """다른 이름이 같은 slug(=같은 파일)로 매핑되면 loud raise — 첫 항목 소실 방지(#34)."""
    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="예산/2026", kind="excel", opts={"path": "/a.xlsx"}))
    with pytest.raises(SlugCollisionError):
        reg.save(DatasetPoolItem(name="예산_2026", kind="excel", opts={"path": "/b.xlsx"}))
    # 첫 항목이 온전 보존된다(덮이지 않음).
    assert reg.load("예산/2026").opts["path"] == "/a.xlsx"
    assert [it.opts["path"] for it in reg.list_items()] == ["/a.xlsx"]


def test_registry_save_same_name_update_is_not_collision(tmp_path):
    """같은 이름 재저장(상태 전이 등)은 충돌이 아니라 그대로 통과 — 자기 갱신."""
    reg = DatasetPoolRegistry(tmp_path)
    it = DatasetPoolItem(name="6월 공고", kind="excel", opts={"path": "/a.xlsx"})
    reg.save(it)
    it.archive()
    reg.save(it)  # allow_overwrite 없이도 통과(동명)
    assert reg.load("6월 공고").status == STATUS_ARCHIVED


def test_registry_save_allow_overwrite_bypasses_guard(tmp_path):
    """명시적 opt-in(allow_overwrite) 은 slug 충돌을 통과 — 확정된 덮어쓰기."""
    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="예산/2026", kind="excel", opts={"path": "/a.xlsx"}))
    reg.save(
        DatasetPoolItem(name="예산_2026", kind="excel", opts={"path": "/b.xlsx"}),
        allow_overwrite=True,
    )
    assert len(reg.list_items()) == 1
    assert reg.load("예산_2026").opts["path"] == "/b.xlsx"


def test_registry_save_corrupt_target_is_loud(tmp_path):
    """대상 파일이 손상돼 소유 항목을 확인할 수 없으면 allow_overwrite 없이는 raise."""
    reg = DatasetPoolRegistry(tmp_path)
    reg.directory.mkdir(parents=True, exist_ok=True)
    reg.path_for("공고").write_text('{"name": "절단', encoding="utf-8")
    with pytest.raises(SlugCollisionError):
        reg.save(DatasetPoolItem(name="공고", kind="excel", opts={"path": "/a.xlsx"}))
    reg.save(
        DatasetPoolItem(name="공고", kind="excel", opts={"path": "/a.xlsx"}),
        allow_overwrite=True,
    )
    assert reg.load("공고").opts["path"] == "/a.xlsx"


def test_default_pool_dir_uses_home_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_dataset_pool_dir() == tmp_path / "datasets"


# ------------------------------------------------------------ 키 비직렬화(보안)
def test_nara_item_never_serializes_service_key(tmp_path):
    """나라 풀 항목 opts 에 키가 없고, 저장 JSON 에도 키 흔적이 0이다."""
    reg = DatasetPoolRegistry(tmp_path)
    it = DatasetPoolItem(
        name="공고쿼리", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
    )
    reg.save(it)
    saved = reg.path_for("공고쿼리").read_text(encoding="utf-8")
    assert _LIVE_KEY not in saved
    assert "service_key" not in saved and "ServiceKey" not in saved


# ------------------------------------------------------------ 복원(factory)
def test_restore_excel_item_returns_live_source_without_reading():
    it = DatasetPoolItem(name="엑셀", kind="excel", opts={"path": "/nope.xlsx"})
    src = source_from_pool_item(it)
    # ExcelDataSource 는 지연 로드라 파일 없이도 인스턴스화된다(실행 때 재읽기=싱크).
    assert isinstance(src, ExcelDataSource)


def test_restore_excel_item_with_sheet_targets_that_sheet():
    """T2 — opts 의 sheet 임베딩이 복원에 그대로 관통(지정 시트 레코드)."""
    it = DatasetPoolItem(
        name="다중", kind="excel",
        opts={"path": str(FIXTURES / "multi_sheet.xlsx"), "sheet": "낙찰현황"},
    )
    src = source_from_pool_item(it)
    assert src.sheet == "낙찰현황"
    assert src.records()[0]["업체명"] == "가나상사"


def test_restore_nara_item_injects_key_from_store():
    it = DatasetPoolItem(
        name="나라", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359", "num_rows": 50},
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    src = source_from_pool_item(it, secret_store=store, fetcher=lambda url: _fixture_bytes())
    assert isinstance(src, NaraStdDataSource)
    assert src.service_key == _LIVE_KEY   # 복원 순간 저장소에서 주입
    assert src.num_rows == 50
    recs = src.records()  # 주입 fetcher 로 실제 취득 관통
    assert len(recs) == 2


def test_restore_nara_item_without_key_fails_loudly():
    it = DatasetPoolItem(
        name="나라", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
    )
    with pytest.raises(ValueError, match="서비스키"):
        source_from_pool_item(it, secret_store=MemorySecretStore())  # 키 미등록


# --------------------------------------------- 실행 시점 겨눔(RunViewModel, Qt 무관)
def _job():
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile

    return Job(
        name="실행", template_path="/t.hwpx",
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
        ]),
        filename_pattern="doc-{{공고명}}",
    )


def test_run_load_pool_item_excel_live(tmp_path):
    from hwpxfiller.gui.run_state import RunViewModel

    csv = tmp_path / "d.csv"
    csv.write_text("ID,공고명\n1,전산장비\n", encoding="utf-8")
    it = DatasetPoolItem(name="엑셀", kind="excel", opts={"path": str(csv)})
    vm = RunViewModel(_job())
    recs = vm.load_pool_item(it)
    assert len(recs) == 1 and recs[0]["공고명"] == "전산장비"
    assert vm.datasource is not None


def test_run_and_matrix_pool_targeting_returns_specified_sheet_records(tmp_path):
    """T2 — sheet 임베딩 풀 항목의 run/matrix 겨눔이 지정 시트 레코드를 반환한다."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.matrix_state import MatrixRunViewModel
    from hwpxfiller.gui.run_state import RunViewModel

    it = DatasetPoolItem(
        name="다중", kind="excel",
        opts={"path": str(FIXTURES / "multi_sheet.xlsx"), "sheet": "낙찰현황"},
    )
    vm = RunViewModel(_job())
    recs = vm.load_pool_item(it)
    assert [r["업체명"] for r in recs] == ["가나상사", "다라물산", "마바테크"]

    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(it)
    mvm = MatrixRunViewModel(JobRegistry(tmp_path / "jobs"), pool_registry=pool)
    assert mvm.load_pool_by_name("다중") == recs


def test_run_load_pool_item_nara_snapshots_once(tmp_path):
    """나라 풀 항목 겨눔 = 1회 취득 후 키 없는 스냅샷 — 반복 records() 가 재-fetch 안 함."""
    from hwpxfiller.gui.nara_state import AcquiredNaraData
    from hwpxfiller.gui.run_state import RunViewModel

    calls = {"n": 0}

    def counting_fetch(url: str) -> bytes:
        calls["n"] += 1
        return _fixture_bytes()

    it = DatasetPoolItem(
        name="나라", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = RunViewModel(_job())
    recs = vm.load_pool_item(it, secret_store=store, fetcher=counting_fetch)
    assert len(recs) == 2
    assert isinstance(vm.datasource, AcquiredNaraData)  # 스냅샷으로 고정
    # 실행뷰의 반복 조회를 흉내내도 fetcher 는 최초 1회만 불린다(스냅샷 캐시).
    for _ in range(5):
        vm.datasource.records()
    assert calls["n"] == 1
    # 스냅샷 어디에도 키가 없다.
    assert _LIVE_KEY not in repr(vm.datasource.__dict__)


def test_run_load_pool_item_nara_auth_failure_is_loud(tmp_path):
    """만료·인증실패 키(resultCode '07')는 조용한 '0건'이 아니라 시끄러운 실패 — 키 비노출."""
    from hwpxfiller.gui.run_state import RunViewModel

    auth_fail = (
        b'{"response":{"header":{"resultCode":"07",'
        b'"resultMsg":"INVALID_REQUEST_PARAMETER_ERROR"},"body":{}}}'
    )
    it = DatasetPoolItem(
        name="나라", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = RunViewModel(_job())
    with pytest.raises(RuntimeError) as ei:
        vm.load_pool_item(it, secret_store=store, fetcher=lambda url: auth_fail)
    assert "07" in str(ei.value)
    assert _LIVE_KEY not in str(ei.value)
    assert vm.datasource is None  # 실패면 datasource 미할당(조용한 진행 금지)


def test_run_load_pool_item_nara_no_key_is_loud(tmp_path):
    from hwpxfiller.gui.run_state import RunViewModel

    it = DatasetPoolItem(
        name="나라", kind="nara",
        opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
    )
    vm = RunViewModel(_job())
    with pytest.raises(RuntimeError, match="서비스키"):
        vm.load_pool_item(it, secret_store=MemorySecretStore())  # 키 미등록
