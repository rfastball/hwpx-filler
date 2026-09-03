"""데이터셋 풀 워크숍 ViewModel(J1) 헤드리스 테스트 — Qt 무접촉.

등록(참조만)·상태 전이·행 성형·KPI(home_state)를 못박는다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.dataset_pool import (
    DatasetPoolRow,
    DatasetPoolViewModel,
    available_actions,
    reference_summary,
)
from hwpxfiller.domain.dataset_reference import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    DatasetReference,
)
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.template_inspection import template_compile_status


def _vm(tmp_path):
    return DatasetPoolViewModel(DatasetPoolRegistry(tmp_path))


def test_register_excel_stores_complete_reference_and_restores_sheet(tmp_path):
    """T2 — 확정 시트가 풀 항목 opts 에 임베딩되고, 복원이 그 시트 레코드를 준다."""
    from pathlib import Path

    from hwpxfiller.data.factory import source_from_pool_item

    fixture = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"
    vm = _vm(tmp_path)
    assert vm.is_empty()
    item = vm.register_excel("다중시트", str(fixture), sheet="낙찰현황")
    assert item.opts["sheet"] == "낙찰현황"
    row = vm.rows()[0]
    assert row.kind == "excel" and row.status == STATUS_ACTIVE
    assert "multi_sheet.xlsx" in row.reference and "낙찰현황" in row.reference
    assert vm.count_label() == "1건"
    # 복원 경로(source_from_pool_item)는 무수정 통과 — opts 그대로 관통해
    # 지정 시트 레코드가 온다(실행 시점 재읽기=싱크).
    src = source_from_pool_item(item)
    assert src.records()[0]["업체명"] == "가나상사"
    assert len(src.records()) == 3


def test_register_nara_stores_query_only_no_key(tmp_path):
    vm = _vm(tmp_path)
    item = vm.register_nara("공고쿼리", "202606010000", "202606302359", num_rows=100)
    assert "service_key" not in item.opts
    reg = DatasetPoolRegistry(tmp_path)
    key = vm.rows()[0].key
    saved = reg.slot_path(key).read_text(encoding="utf-8")
    assert "ServiceKey" not in saved and "service_key" not in saved
    assert "기간" in vm.rows()[0].reference


def test_register_validation_is_fail_closed(tmp_path):
    vm = _vm(tmp_path)
    with pytest.raises(ValueError):
        vm.register_excel("  ", "/x.xlsx")
    with pytest.raises(ValueError):
        vm.register_nara("이름있음", "", "202606302359")
    with pytest.raises(ValueError, match="1개월"):
        vm.register_nara("긴기간", "202601010000", "202607010000")
    with pytest.raises(ValueError):
        vm.register_nara("형식오류", "2026-06-01 00", "202606302359")
    assert vm.is_empty()  # 거절된 등록은 흔적 없음


def test_status_transitions_and_action_matrix(tmp_path):
    """상태 전이와 허용 액션은 하나의 수명주기 표를 따른다."""
    vm = _vm(tmp_path)
    vm.register_excel("D", "/d.xlsx")
    key = vm.rows()[0].key
    assert [a.key for a in available_actions(STATUS_ACTIVE)] == ["archive", "delete"]
    vm.archive(key)
    assert vm.rows()[0].status == STATUS_ARCHIVED
    assert [a.key for a in available_actions(STATUS_ARCHIVED)] == ["activate", "delete"]
    vm.activate(key)
    assert vm.rows()[0].status == STATUS_ACTIVE
    vm.delete(key)
    assert vm.is_empty()


def test_unknown_status_transition_fails_loudly(tmp_path):
    vm = _vm(tmp_path)
    vm.register_excel("D", "/d.xlsx")
    key = vm.rows()[0].key
    with pytest.raises(ValueError, match="지원하지 않는 데이터셋 전이"):
        vm._transition(key, "typo")


def test_stale_reference_update_does_not_resurrect_deleted_item(tmp_path):
    """확인 전에 읽은 항목이 삭제되면 갱신은 loud 실패하고 신규 항목으로 부활하지 않는다."""
    directory = tmp_path / "datasets"
    reg = DatasetPoolRegistry(directory)
    vm = DatasetPoolViewModel(reg)
    vm.register_excel("D", "/old.xlsx")
    key = vm.rows()[0].key
    DatasetPoolRegistry(directory).delete(key)

    with pytest.raises(FileNotFoundError):
        vm.update_excel_reference(key, "/new.xlsx")
    assert not reg.exists(key)


def test_find_same_data_and_relabel(tmp_path):
    """같은 데이터(경로+시트) 재고정 = 새 항목이 아니라 기존 슬롯의 라벨·메모 갱신(§5.3 C)."""
    vm = _vm(tmp_path)
    vm.register_excel("7월", "/a.xlsx", note="첫 등록")
    found = vm.find_same_data("/a.xlsx")
    assert found is not None
    key, existing = found
    assert existing.name == "7월"
    updated = vm.relabel(key, "7월 최신")
    assert updated.name == "7월 최신"
    assert updated.note == "첫 등록"       # 빈 메모 입력 = 진술 없음(보존)
    assert len(vm.rows()) == 1             # 여전히 1건 — 정체성이 같다
    # 다른 시트는 다른 데이터 — 판정에 시트가 든다(#33).
    assert vm.find_same_data("/a.xlsx", "물품") is None


def test_update_excel_reference_keeps_slot_but_rejects_identity_theft(tmp_path):
    """다시 연결 = 같은 슬롯의 참조 교체(수명 보존). 남의 정체성으로는 못 갈아탄다."""
    vm = _vm(tmp_path)
    vm.register_excel("A", "/a.xlsx")
    vm.register_excel("B", "/b.xlsx")
    rows = {r.name: r for r in vm.rows()}
    vm.archive(rows["A"].key)  # 보관 상태가 재연결에도 보존되는지 함께 본다
    updated = vm.update_excel_reference(rows["A"].key, "/a2.xlsx")
    assert updated.opts["path"] == "/a2.xlsx"
    assert updated.status == STATUS_ARCHIVED  # 수명 보존 — 조용한 재활성화 금지
    with pytest.raises(ValueError, match="이미"):
        vm.update_excel_reference(rows["B"].key, "/a2.xlsx")  # A 슬롯의 정체성과 충돌


def test_concurrent_relink_to_same_identity_loses_loudly(tmp_path, monkeypatch):
    """서로 다른 슬롯 둘을 같은 경로+시트로 동시 재연결하면 하나만 이기고 하나는 loud 거절.

    코덱스 1R P2 — 정체성 검사가 잠금 밖이면 둘 다 선검사를 통과하고 mutate 만 직렬화돼
    같은 정체성의 슬롯 2개가 남는다(레지스트리 불변식 붕괴). 검사·변이가 공유 쓰기 잠금
    한 경계 안이어야 한다: A 가 잠금 안(원자 쓰기 중)에 있는 동안 B 는 검사에 못 들어가고,
    A 커밋 뒤 B 의 잠금 안 재검사가 충돌을 잡는다.
    """
    import threading

    from hwpxfiller.external import dataset_store

    directory = tmp_path / "datasets"
    vm_a = DatasetPoolViewModel(DatasetPoolRegistry(directory))
    vm_b = DatasetPoolViewModel(DatasetPoolRegistry(directory))
    vm_a.register_excel("A", "/a.xlsx")
    vm_a.register_excel("B", "/b.xlsx")
    rows = {r.name: r for r in vm_a.rows()}

    entered = threading.Event()
    release = threading.Event()
    real_save = dataset_store.save_reference

    def slow_save(path, item):
        entered.set()
        assert release.wait(2)
        return real_save(path, item)

    monkeypatch.setattr(dataset_store, "save_reference", slow_save)
    errors: "list[Exception]" = []

    def relink(vm, key):
        try:
            vm.update_excel_reference(key, "/target.xlsx")
        except ValueError as exc:
            errors.append(exc)

    first = threading.Thread(target=relink, args=(vm_a, rows["A"].key))
    first.start()
    assert entered.wait(2)                       # A: 검사 통과, 잠금 안에서 쓰기 중
    second = threading.Thread(target=relink, args=(vm_b, rows["B"].key))
    second.start()
    second.join(0.05)
    assert second.is_alive()                     # B: 검사가 잠금 안이라 진입 자체가 대기
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()

    assert len(errors) == 1 and "이미" in str(errors[0])   # 한쪽만 loud 패배
    reg = DatasetPoolRegistry(directory)
    winners = [
        (key, it) for key, it in reg.list_entries()
        if it.opts.get("path") == "/target.xlsx"
    ]
    assert [k for k, _ in winners] == [rows["A"].key]       # 같은 정체성 슬롯은 1개뿐
    assert DatasetPoolViewModel(reg).duplicates() == []      # 불변식 유지(중복 그룹 0)


def test_duplicates_surface_from_legacy_files(tmp_path):
    """구판(이름=키)이 남긴 같은 경로 2건이 VM duplicates 로 표면화된다(§5.3 병합 loud)."""
    import json as _json

    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("7월 공고", "공고 최신"):
        item = DatasetReference(name=name, kind="excel", opts={"path": "/same.xlsx"})
        (tmp_path / f"{name}.dataset.json").write_text(
            _json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
    vm = _vm(tmp_path)
    groups = vm.duplicates()
    assert len(groups) == 1
    assert {r.name for r in groups[0]} == {"7월 공고", "공고 최신"}
    assert len(vm.rows()) == 2  # 병합 전에도 목록에는 둘 다 산다(숨김 금지)


def test_reference_summary_unknown_kind():
    it = DatasetReference(name="x", kind="excel", opts={})
    assert "경로 없음" in reference_summary(it)
    # 미지 kind 의 fallback 은 불변 — 새 종류가 늘어도 모르는 것은 모른다고 말한다.
    assert reference_summary(
        DatasetReference(name="y", kind="미래소스", opts={"db": "/x.db"})
    ) == "(알 수 없는 소스)"


def test_pclm_row_renders_kind_label_summary_and_locate_path(tmp_path):
    """계약 목록 항목의 행 성형 — 종류 라벨·DB/시트 요약·로케이트 경로(끊김 배지가 볼 파일)."""
    vm = _vm(tmp_path)
    db = tmp_path / "pclm.db"
    vm.register_pclm("계약 목록", str(db), view="v_품목_v1", note="품목 명세")
    row = vm.rows()[0]
    assert row.kind == "pclm" and row.kind_label == "계약 목록"
    # 표면 어휘는 「시트」이고 면 이름은 제목으로 옮긴다 — 내부 이름(v_…)은 요약에 없다.
    assert row.reference == "DB: pclm.db · 시트 품목"
    assert row.locate_path == str(db)   # 「끊김」 배지·로케이트가 같은 파일을 본다
    assert row.sheet == ""              # 시트는 엑셀 축 — 계약 목록은 뷰가 그 자리다
    assert row.note == "품목 명세"

    # 미지 kind 는 로케이트 대상이 아니다(파일 참조가 아닌 종류의 판정 밖).
    row_unknown = DatasetPoolRow.from_item(
        "k", DatasetReference(name="z", kind="미래소스", opts={"db": "/x.db"})
    )
    assert row_unknown.locate_path == "" and row_unknown.kind_label == "미래소스"


def test_pipeline_row_renders_kind_label_and_summary(tmp_path):
    """파이프라인 풀 항목(KB)이 풀 목록에서 종류 라벨·조립 요약으로 성형된다."""
    it = DatasetReference(
        name="6월 조립", kind="pipeline",
        opts={
            "sources": [{"kind": "excel", "opts": {"path": "/a.csv"}},
                        {"kind": "excel", "opts": {"path": "/b.csv"}}],
            "steps": [{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
        },
    )
    reg = DatasetPoolRegistry(tmp_path)
    reg.add(it)
    vm = DatasetPoolViewModel(reg)
    r = vm.rows()[0]
    assert r.kind_label == "파이프라인"
    assert "소스 2개" in r.reference and "merge" in r.reference


# ------------------------------------------------------------ home KPI (헤드리스)
def test_home_kpi_counts_only_active_pool_items_and_defaults_to_zero(tmp_path):
    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.gui.home_state import HomeViewModel

    pool = DatasetPoolRegistry(tmp_path / "datasets")
    pvm = DatasetPoolViewModel(pool)
    pvm.register_excel("A", "/a.xlsx")
    pvm.register_excel("B", "/b.xlsx")
    key_b = next(r.key for r in pvm.rows() if r.name == "B")
    pvm.archive(key_b)  # 보관은 활성 카운트에서 제외

    home = HomeViewModel(
        JobRegistry(tmp_path / "jobs"), pool_registry=pool,
        engine=make_hwpx_engine(), inspect_status=template_compile_status,
    )
    assert home.kpi().pool_count == 1  # A 만 활성
    assert HomeViewModel(
        JobRegistry(tmp_path / "jobs-without-pool"),
        engine=make_hwpx_engine(), inspect_status=template_compile_status,
    ).kpi().pool_count == 0


# ------------------------- 고르기 판정·동사 목록의 단일 자리(고르기 열 공용 계약 ①)
def test_select_block_reason_admits_pclm_and_speaks_its_own_broken_line(tmp_path):
    """「이 데이터를 쓸 수 있는가」의 판정 자리는 **행 하나**다(U6-B #976 → 링1 이동).

    종전에는 셋이 각자 답했다: 데이터 선택 다이얼로그의 웹 함수(`usableReason`), 편집기
    축약 목록의 `screen_editor.pool_option_block`, 그리고 마운트 관문. 앞의 둘이 한
    컴포넌트가 되면서 그 어긋남이 화면 안에서 드러나므로 판정을 행으로 올렸고, 좌 열의
    판정(`TemplateRow.select_block_reason`)과 **같은 링**에 서려고 링2 자유함수에서 여기로
    내려왔다.

    **끊김 처방은 종류가 가른다**(#937): 엑셀에는 「다시 연결」이 있고 계약 목록에는 없다.
    """
    db = tmp_path / "pclm.db"
    db.write_bytes(b"x")
    live = DatasetPoolRow.from_item(
        "k1", DatasetReference(name="계약목록", kind="pclm", opts={"db": str(db), "view": "v"})
    )
    assert live.select_block_reason() == ""
    assert live.missing is False

    gone = DatasetPoolRow.from_item(
        "k2",
        DatasetReference(
            name="사라진목록", kind="pclm",
            opts={"db": str(tmp_path / "none.db"), "view": "v"},
        ),
    )
    reason = gone.select_block_reason()
    assert gone.missing is True
    assert "참조가 끊겼습니다" in reason
    assert "계약 목록 DB 파일" in reason      # 엑셀 전용 동사(「다시 연결」)를 지시하지 않는다
    assert "다시 연결" not in reason

    frozen = DatasetPoolRow.from_item(
        "k3", DatasetReference(name="나라", kind="nara", opts={})
    )
    assert "작업 데이터로 연결할 수 없습니다" in frozen.select_block_reason()
    # 파일을 가리키지 않는 참조는 끊김 판정의 대상이 아니다(빈 경로 = 끊김 아님).
    assert frozen.missing is False


def test_archived_row_is_disabled_with_the_activate_verb_not_hidden(tmp_path):
    """보관 항목은 숨기지 않고 **비활성 + 사유**로 선다 — 그 사유가 같은 행의 동사를 지목한다."""
    vm = _vm(tmp_path)
    live = tmp_path / "발주.xlsx"
    live.write_bytes(b"x")
    vm.register_excel("발주", str(live), sheet="s")
    row = vm.rows()[0]
    assert row.select_block_reason() == ""
    vm.archive(row.key)
    archived = vm.rows()[0]
    assert "보관한 항목입니다" in archived.select_block_reason()
    assert "활성화" in archived.select_block_reason()
    assert "activate" in [a.key for a in archived.actions()]


def test_row_actions_carry_every_verb_the_column_menu_will_show(tmp_path):
    """행이 ⋯ 메뉴의 동사 **전부**를 낸다 — 표면이 자기 판정으로 더하지 않는다.

    「다시 연결…」은 **종류**가 가르고(엑셀만) 보관·활성화는 **상태**가 가른다. 종전에는
    앞의 것만 표면이 `kind === "excel"` 로 다시 판정해 덧붙였고, 좌·우 열이 한 컴포넌트가
    되면 그 재판정이 곧 두 열의 어긋남이 된다. 키는 `pool` 채널 액션 이름 그대로다.
    """
    vm = _vm(tmp_path)
    vm.register_excel("엑셀", "/a.xlsx", sheet="s")
    vm.register_pclm("계약", str(tmp_path / "pclm.db"), view="v_통합_v1")
    rows = {r.name: r for r in vm.rows()}
    assert [a.key for a in rows["엑셀"].actions()] == ["relink", "archive", "delete"]
    assert [a.label for a in rows["엑셀"].actions()][0] == "다시 연결…"
    # 계약 목록에는 그 동사가 없다 — 참조 교체 대상이 「사람이 고를 파일 하나」가 아니다.
    assert [a.key for a in rows["계약"].actions()] == ["archive", "delete"]

    vm.archive(rows["엑셀"].key)
    archived = {r.name: r for r in vm.rows()}["엑셀"]
    assert [a.key for a in archived.actions()] == ["relink", "activate", "delete"]


def test_empty_hint_speaks_only_while_the_pool_is_empty(tmp_path):
    """빈 상태 문안은 Python 이 낸다(종전 `pool_list.ts` 리터럴) — 비어 있지 않으면 침묵."""
    vm = _vm(tmp_path)
    assert vm.empty_hint() == "고정한 데이터가 없습니다."
    vm.register_excel("A", "/a.xlsx")
    assert vm.empty_hint() == ""
