"""데이터셋 풀(J1) 헤드리스 테스트 — 참조 직렬화·상태 전이·복원(네트워크·실 저장소 무접촉).

보안 불변식(나라 항목에 ServiceKey 비직렬화)과 복원 시 키 주입을 못박는다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hwpxfiller.domain import dataset_reference as dataset_domain
from hwpxfiller.core.dataset_pool import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_RETIRED,
    DatasetPoolItem,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
    excel_identity,
    item_identity,
)
from hwpxfiller.data.excel import ExcelDataSource
from hwpxfiller.data.factory import source_from_pool_item
from hwpxfiller.data.nara import NaraStdDataSource, make_nara_acquirer
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


# ------------------------------------------------------------------ 모델
def test_item_roundtrip_to_from_dict():
    # Core는 파일 I/O 호환 타입만 더하고 값·정체성 권위는 Domain 객체를 그대로 승계한다.
    assert issubclass(DatasetPoolItem, dataset_domain.DatasetReference)
    assert item_identity is dataset_domain.reference_identity
    assert STATUS_ACTIVE is dataset_domain.STATUS_ACTIVE
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
    it.activate()
    assert it.is_active


def test_retired_status_migrates_to_archived_on_read():
    """폐기된 retired 상태의 구 .dataset.json 은 읽기 시 archived 로 정준 정규화(#5).

    무손실 forward-마이그레이션 — retired 와 archived 는 실행 후보 여부가 동일했다.
    loud raise 로 죽지 않고 조용히 접어, durable 참조가 보존된다.
    """
    it = DatasetPoolItem.from_dict(
        {"name": "구은퇴", "kind": "excel", "opts": {"path": "/d.xlsx"}, "status": STATUS_RETIRED}
    )
    assert it.status == STATUS_ARCHIVED and not it.is_active


def test_retired_not_a_valid_constructed_status():
    """retired 는 이제 직접 생성할 수 없다(마이그레이션 별칭 전용, #5) — 새 저장 금지."""
    with pytest.raises(ValueError):
        DatasetPoolItem(name="x", kind="excel", status=STATUS_RETIRED)


def test_from_dict_backward_compatible_defaults():
    it = DatasetPoolItem.from_dict({"name": "구", "kind": "excel"})
    assert it.opts == {} and it.status == STATUS_ACTIVE and it.note == ""


# ------------------------------------------------------------------ 정체성(§5.3 C)
def test_excel_identity_normalizes_path_and_carries_sheet(tmp_path):
    """정체성 = normcase(abspath(path)) + sheet — 표기 변형은 같고, 시트가 다르면 다르다."""
    a = tmp_path / "대장.xlsx"
    assert excel_identity(a) == excel_identity(str(a).upper())  # Windows normcase 흡수
    assert excel_identity(a, "1월") != excel_identity(a, "2월")  # 같은 워크북·다른 시트(#33)
    assert excel_identity(a, "") != excel_identity(a, "1월")


def test_item_identity_only_for_pathful_excel():
    """정체성은 경로 있는 엑셀 참조만 — 나라·파이프라인·경로 없는 opts 는 None(추측 금지)."""
    assert item_identity(
        DatasetPoolItem(name="a", kind="excel", opts={"path": "/d.xlsx"})
    ) == excel_identity("/d.xlsx")
    assert item_identity(DatasetPoolItem(name="b", kind="nara", opts={})) is None
    assert item_identity(DatasetPoolItem(name="c", kind="excel", opts={})) is None
    assert item_identity(
        DatasetPoolItem(name="d", kind="excel", opts={"path": 3})  # 훼손 opts
    ) is None


# ------------------------------------------------------------------ 레지스트리(슬롯 키)
def test_registry_add_load_list_delete(tmp_path):
    reg = DatasetPoolRegistry(tmp_path)
    assert reg.list_items() == []
    kb = reg.add(DatasetPoolItem(name="B", kind="excel", opts={"path": "/b.xlsx"}))
    ka = reg.add(DatasetPoolItem(name="A", kind="excel", opts={"path": "/a.xlsx"}))
    assert reg.names() == ["A", "B"]  # 이름순
    assert [k for k, _ in reg.list_entries()] == [ka, kb]
    assert reg.exists(ka)
    assert reg.load(ka).opts["path"] == "/a.xlsx"
    reg.delete(ka)
    reg.delete(ka)  # 이미 없는 슬롯 삭제도 조용한 no-op — 멱등 계약
    assert not reg.exists(ka)
    assert reg.names() == ["B"]


def test_registry_filters_by_status(tmp_path):
    reg = DatasetPoolRegistry(tmp_path)
    archived = DatasetPoolItem(name="보관됨", kind="excel", opts={"path": "/y.xlsx"})
    archived.archive()
    reg.add(DatasetPoolItem(name="살아있음", kind="excel", opts={"path": "/x.xlsx"}))
    reg.add(archived)
    assert [it.name for it in reg.list_items(status=STATUS_ACTIVE)] == ["살아있음"]
    assert len(reg.list_items()) == 2


def test_names_are_labels_duplicates_allowed(tmp_path):
    """이름은 순수 라벨(§5.3 C) — 같은 이름·다른 데이터가 서로 다른 슬롯으로 공존한다."""
    reg = DatasetPoolRegistry(tmp_path)
    k1 = reg.add(DatasetPoolItem(name="매출", kind="excel", opts={"path": "/1월.xlsx"}))
    k2 = reg.add(DatasetPoolItem(name="매출", kind="excel", opts={"path": "/2월.xlsx"}))
    assert k1 != k2
    assert reg.names() == ["매출", "매출"]
    assert {reg.load(k1).opts["path"], reg.load(k2).opts["path"]} == {"/1월.xlsx", "/2월.xlsx"}


def test_registry_add_rejects_same_identity_loudly(tmp_path):
    """같은 데이터(경로+시트)의 재추가는 이름이 달라도 loud 거절 — 조용한 2건 등록 봉쇄."""
    reg = DatasetPoolRegistry(tmp_path)
    reg.add(DatasetPoolItem(name="7월", kind="excel", opts={"path": "/a.xlsx"}))
    with pytest.raises(ValueError, match="이미"):
        reg.add(DatasetPoolItem(name="다른이름", kind="excel", opts={"path": "/a.xlsx"}))
    # 다른 시트는 다른 데이터라 통과한다(#33 — 시트가 축에 든다).
    reg.add(DatasetPoolItem(name="다른시트", kind="excel", opts={"path": "/a.xlsx", "sheet": "2월"}))
    assert len(reg.list_items()) == 2


def test_slot_key_is_not_derived_from_content(tmp_path):
    """슬롯 키는 내용에서 파생되지 않는다 — 같은 데이터를 다른 슬롯에 넣어도 키가 다르다.

    키가 정체성 다이제스트면 「내용물 교체가 정상 수명 사건」인 개체의 파일명이 내용에
    묶인다(#347 이 dataset_id 를 기각한 근거를 파일명에 다시 심는 구조) — 4R P2 의 뿌리다.
    """
    reg_a = DatasetPoolRegistry(tmp_path / "a")
    reg_b = DatasetPoolRegistry(tmp_path / "b")
    same = {"path": "/same.xlsx", "sheet": "물품"}
    key_a = reg_a.add(DatasetPoolItem(name="갑", kind="excel", opts=dict(same)))
    key_b = reg_b.add(DatasetPoolItem(name="갑", kind="excel", opts=dict(same)))
    assert key_a != key_b, "슬롯 키가 내용(정체성)에서 파생됩니다."


def test_relinked_slot_releases_its_old_identity_key(tmp_path):
    """A 로 만든 슬롯을 B 로 재연결하면 A 는 **다시 고정할 수 있다**(코덱스 4R P2).

    키가 정체성에서 파생되던 시절엔 슬롯이 hash(identity(A)) 를 계속 점유해, 정체성
    조회는 통과하는데(A 를 참조하는 항목이 0건) 키 충돌로 막혔다 — 사용자에게는
    「없는 것과 충돌」로 보이는 자리였다.
    """
    reg = DatasetPoolRegistry(tmp_path)
    key = reg.add(DatasetPoolItem(name="보고", kind="excel", opts={"path": "/A.xlsx"}))
    reg.mutate(key, lambda it: it.opts.update({"path": "/B.xlsx"}))  # 다시 연결
    assert reg.find_identity("/A.xlsx") is None          # A 를 참조하는 항목은 0건

    again = reg.add(DatasetPoolItem(name="A 재고정", kind="excel", opts={"path": "/A.xlsx"}))
    assert again != key
    assert reg.load(again).opts["path"] == "/A.xlsx"
    assert reg.load(key).opts["path"] == "/B.xlsx"        # 재연결한 슬롯은 그대로 산다
    assert reg.duplicate_identity_groups(corrupted=[]) == []
    # 대조군 — **실제** 중복(현재 B 를 가리키는 항목이 있는데 또 B)은 여전히 loud 거절.
    with pytest.raises(ValueError, match="이미"):
        reg.add(DatasetPoolItem(name="B 재고정", kind="excel", opts={"path": "/B.xlsx"}))


def test_find_identity_matches_normalized_path(tmp_path):
    reg = DatasetPoolRegistry(tmp_path)
    key = reg.add(DatasetPoolItem(name="7월", kind="excel", opts={"path": "C:/d/a.xlsx"}))
    found = reg.find_identity("C:\\d\\A.XLSX")  # 구분자·대소문자 변형 = 같은 실파일
    assert found is not None and found[0] == key
    assert reg.find_identity("C:/d/a.xlsx", "물품") is None  # 시트가 다르면 다른 데이터


def test_slot_path_rejects_traversal_keys(tmp_path):
    """슬롯 키는 웹 페이로드가 흘러드는 자리 — 경로 탈출 키를 loud 거절한다."""
    reg = DatasetPoolRegistry(tmp_path)
    for bad in ("", "..", "a/b", "a\\b", "../x"):
        with pytest.raises(ValueError):
            reg.slot_path(bad)


def test_legacy_slug_filename_is_a_valid_slot(tmp_path):
    """구판(이름 slug 파일명) 파일은 그 stem 그대로 유효한 슬롯 — 디스크 마이그레이션 없음."""
    reg = DatasetPoolRegistry(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    legacy = DatasetPoolItem(name="7월 공고", kind="excel", opts={"path": "/a.xlsx"})
    (tmp_path / "7월 공고.dataset.json").write_text(
        __import__("json").dumps(legacy.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    entries = reg.list_entries()
    assert [(k, it.name) for k, it in entries] == [("7월 공고", "7월 공고")]
    key = entries[0][0]
    assert reg.find_identity("/a.xlsx") == (key, reg.load(key))
    reg.mutate(key, lambda it: it.archive())  # 키 기반 조작이 구판 슬롯에도 그대로 선다
    assert reg.load(key).status == STATUS_ARCHIVED


def test_duplicate_identity_groups_surface_legacy_merge_targets(tmp_path):
    """구판이 남긴 다른 이름·같은 경로 2건은 조용히 접히지 않고 병합 그룹으로 표면화된다(§5.3)."""
    import json as _json

    reg = DatasetPoolRegistry(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("7월 공고", "공고 최신"):
        item = DatasetPoolItem(name=name, kind="excel", opts={"path": "/same.xlsx"})
        (tmp_path / f"{name}.dataset.json").write_text(
            _json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
    groups = reg.duplicate_identity_groups(corrupted=[])
    assert len(groups) == 1
    assert {it.name for _k, it in groups[0]} == {"7월 공고", "공고 최신"}
    # 두 항목 모두 목록에 그대로 산다(숨김 금지 — 병합 전에도 쓸 수 있다).
    assert len(reg.list_items()) == 2


def test_mutate_failure_preserves_json_and_cleans_temp(tmp_path, monkeypatch):
    """원자 교체 실패는 기존 JSON과 디렉터리 청결을 함께 보존한다(#182)."""
    reg = DatasetPoolRegistry(tmp_path)
    key = reg.add(DatasetPoolItem(name="공고", kind="excel", opts={"path": "/old.xlsx"}))
    path = reg.slot_path(key)
    before = path.read_bytes()

    def fail_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr("hwpxcore.atomic.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        reg.mutate(key, lambda it: it.archive())

    assert path.read_bytes() == before
    assert list(tmp_path.glob(path.name + ".*.tmp")) == []


def test_shared_path_lock_merges_reference_update_and_transition(tmp_path):
    """서로 다른 registry instance의 참조 갱신과 상태 전이가 lost update 없이 합쳐진다."""
    directory = tmp_path / "datasets"
    updater = DatasetPoolRegistry(directory)
    transitioner = DatasetPoolRegistry(directory)
    key = updater.add(DatasetPoolItem(name="공고", kind="excel", opts={"path": "/old.xlsx"}))

    update_entered = threading.Event()
    release_update = threading.Event()
    transition_started = threading.Event()
    transition_finished = threading.Event()

    def update_reference() -> None:
        def change(item: DatasetPoolItem) -> None:
            update_entered.set()
            assert release_update.wait(2)
            item.opts = {"path": "/new.xlsx"}

        updater.mutate(key, change)

    def archive() -> None:
        assert update_entered.wait(2)
        transition_started.set()
        transitioner.mutate(key, lambda item: item.archive())
        transition_finished.set()

    first = threading.Thread(target=update_reference)
    second = threading.Thread(target=archive)
    first.start()
    assert update_entered.wait(2)
    second.start()
    assert transition_started.wait(2)
    assert not transition_finished.wait(0.05)  # 같은 path lock에서 대기 중
    release_update.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    saved = updater.load(key)
    assert saved.opts["path"] == "/new.xlsx"
    assert saved.status == STATUS_ARCHIVED


def test_transition_delete_race_cannot_resurrect_deleted_item(tmp_path):
    """전이와 삭제가 경합해도 delete 뒤의 stale save가 항목을 되살리지 않는다."""
    directory = tmp_path / "datasets"
    transitioner = DatasetPoolRegistry(directory)
    deleter = DatasetPoolRegistry(directory)
    key = transitioner.add(
        DatasetPoolItem(name="공고", kind="excel", opts={"path": "/a.xlsx"})
    )

    transition_entered = threading.Event()
    release_transition = threading.Event()
    delete_started = threading.Event()
    delete_finished = threading.Event()

    def archive() -> None:
        def change(item: DatasetPoolItem) -> None:
            transition_entered.set()
            assert release_transition.wait(2)
            item.archive()

        transitioner.mutate(key, change)

    def delete() -> None:
        assert transition_entered.wait(2)
        delete_started.set()
        deleter.delete(key)
        delete_finished.set()

    first = threading.Thread(target=archive)
    second = threading.Thread(target=delete)
    first.start()
    assert transition_entered.wait(2)
    second.start()
    assert delete_started.wait(2)
    assert not delete_finished.wait(0.05)  # 전이 전체가 끝날 때까지 삭제도 같은 lock에서 대기
    release_transition.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert not transitioner.exists(key)


def test_every_registry_writer_uses_shared_path_lock(tmp_path, monkeypatch):
    """add/mutate/delete의 실제 파일 I/O가 모두 동일한 path-scoped lock 안에서 일어난다."""
    directory = tmp_path / "datasets"
    reg = DatasetPoolRegistry(directory)
    peer = DatasetPoolRegistry(directory)
    key_a = reg.add(DatasetPoolItem(name="A", kind="excel", opts={"path": "/a.xlsx"}))
    probes: "list[bool]" = []

    def probe_lock() -> None:
        acquired: "list[bool]" = []

        def try_acquire() -> None:
            lock = peer.write_lock()
            got = lock.acquire(blocking=False)
            acquired.append(got)
            if got:
                lock.release()

        thread = threading.Thread(target=try_acquire)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        probes.append(acquired == [False])

    real_save = DatasetPoolItem.save
    real_unlink = Path.unlink

    def spy_save(item, path):
        probe_lock()
        return real_save(item, path)

    def spy_unlink(path, *args, **kwargs):
        probe_lock()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(DatasetPoolItem, "save", spy_save)
    monkeypatch.setattr(Path, "unlink", spy_unlink)
    key_b = reg.add(DatasetPoolItem(name="B", kind="excel", opts={"path": "/b.xlsx"}))
    reg.mutate(key_a, lambda item: item.archive())
    reg.delete(key_b)

    assert probes and all(probes)


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
    key = reg.add(it)
    saved = reg.slot_path(key).read_text(encoding="utf-8")
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


def test_run_pool_targeting_returns_specified_sheet_records(tmp_path):
    """T2 — sheet 임베딩 풀 항목의 run 겨눔이 지정 시트 레코드를 반환한다."""
    from hwpxfiller.gui.run_state import RunViewModel

    it = DatasetPoolItem(
        name="다중", kind="excel",
        opts={"path": str(FIXTURES / "multi_sheet.xlsx"), "sheet": "낙찰현황"},
    )
    vm = RunViewModel(_job())
    recs = vm.load_pool_item(it)
    assert [r["업체명"] for r in recs] == ["가나상사", "다라물산", "마바테크"]


def test_run_load_pool_item_nara_snapshots_once(tmp_path):
    """나라 풀 항목 겨눔 = 1회 취득 후 키 없는 스냅샷 — 반복 records() 가 재-fetch 안 함."""
    from hwpxfiller.application.nara_acquire import AcquiredNaraData
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
    recs = vm.load_pool_item(
        it,
        secret_store=store,
        fetcher=counting_fetch,
        nara_factory=make_nara_acquirer,
    )
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
        vm.load_pool_item(
            it,
            secret_store=store,
            fetcher=lambda _url: auth_fail,
            nara_factory=make_nara_acquirer,
        )
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
        vm.load_pool_item(
            it,
            secret_store=MemorySecretStore(),
            nara_factory=make_nara_acquirer,
        )
