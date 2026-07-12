"""파이프라인 빌더 ViewModel(KB) 헤드리스 테스트 — Qt·네트워크 무접촉.

인수조건: 저작→저장(참조만)→실행 재읽기 라운드트립, merge 제안=게이트(스텝 미생성),
미리보기=실행 동일 파이프라인(divergence 0), 시끄러운 실패, 나라 서브소스 키 주입.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.data.factory import source_from_pool_item
from hwpxfiller.data.pipeline import PipelineSource
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore
from hwpxfiller.gui.pipeline_builder_state import PipelineBuilderViewModel

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


def _pool_with_csvs(tmp_path) -> DatasetPoolRegistry:
    """엑셀(CSV) 참조 2건이 등록된 풀 — 공유 컬럼 'id'."""
    a = tmp_path / "base.csv"
    b = tmp_path / "lookup.csv"
    a.write_text("id,name\n1,A\n2,B\n", encoding="utf-8-sig")
    b.write_text("id,city\n1,서울\n2,부산\n", encoding="utf-8-sig")
    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="기준", kind="excel", opts={"path": str(a)}))
    reg.save(DatasetPoolItem(name="참조표", kind="excel", opts={"path": str(b)}))
    return reg


# ------------------------------------------------------------------ 후보 소스
def test_available_sources_exclude_pipelines_and_inactive(tmp_path):
    reg = _pool_with_csvs(tmp_path)
    pl = DatasetPoolItem(name="기존조립", kind="pipeline", opts={"sources": [], "steps": []})
    reg.save(pl)
    archived = DatasetPoolItem(name="보관됨", kind="excel", opts={"path": "/x.csv"})
    archived.archive()
    reg.save(archived)
    vm = PipelineBuilderViewModel(reg)
    names = vm.available_source_names()
    assert "기준" in names and "참조표" in names
    assert "기존조립" not in names  # v1 중첩 미지원(순환 차단)
    assert "보관됨" not in names   # active 만


def test_add_source_rejects_pipeline_kind(tmp_path):
    reg = _pool_with_csvs(tmp_path)
    reg.save(DatasetPoolItem(name="조립", kind="pipeline", opts={"sources": [], "steps": []}))
    vm = PipelineBuilderViewModel(reg)
    with pytest.raises(ValueError, match="중첩"):
        vm.add_source("조립")


# ------------------------------------------------------------------ 소스/스텝 편집
def test_remove_source_referenced_by_step_fails_loudly(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.add_step("merge", 1, on="id", how="inner")
    with pytest.raises(ValueError, match="스텝"):
        vm.remove_source(1)  # 스텝이 참조 중 — 조용한 자동삭제 금지
    vm.remove_step(0)
    vm.remove_source(1)  # 스텝 제거 후엔 가능
    assert len(vm.sources) == 1


def test_remove_source_reindexes_higher_step_refs(tmp_path):
    tmp = tmp_path / "c.csv"
    tmp.write_text("id,x\n1,q\n", encoding="utf-8-sig")
    reg = _pool_with_csvs(tmp_path)
    reg.save(DatasetPoolItem(name="셋째", kind="excel", opts={"path": str(tmp)}))
    vm = PipelineBuilderViewModel(reg)
    vm.add_source("기준")     # 0
    vm.add_source("참조표")   # 1 — 스텝 없음
    vm.add_source("셋째")     # 2
    vm.add_step("append", 2)
    vm.remove_source(1)       # 참조 없는 소스 제거 → 스텝의 2 는 1 로 시프트(의미 보존)
    assert vm.steps[0]["source"] == 1
    assert [s.name for s in vm.sources] == ["기준", "셋째"]


def test_add_step_validates_loudly(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    with pytest.raises(ValueError, match="merge|append"):
        vm.add_step("filter", 0)  # v1 밖 op
    with pytest.raises(ValueError, match="소스"):
        vm.add_step("append", 5)  # 범위 밖
    with pytest.raises(ValueError, match="조인 키"):
        vm.add_step("merge", 0)   # on 누락
    with pytest.raises(ValueError, match="inner"):
        vm.add_step("merge", 0, on="id", how="outer")


# ------------------------------------------------------------------ merge 제안 = 게이트
def test_suggest_merge_keys_returns_shared_columns_without_adding_step(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")    # fields: id,name
    vm.add_source("참조표")  # fields: id,city
    keys = vm.suggest_merge_keys(1)
    assert keys == ["id"]        # 실제 공유 컬럼(구조축) — preset 휴리스틱 아님
    assert vm.steps == []        # 제안 전용: 스텝을 만들지 않는다(사람 확정 게이트)


def test_suggest_merge_keys_no_shared_columns_returns_empty(tmp_path):
    c = tmp_path / "other.csv"
    c.write_text("코드,값\nX,1\n", encoding="utf-8-sig")
    reg = _pool_with_csvs(tmp_path)
    reg.save(DatasetPoolItem(name="무관", kind="excel", opts={"path": str(c)}))
    vm = PipelineBuilderViewModel(reg)
    vm.add_source("기준")
    vm.add_source("무관")
    assert vm.suggest_merge_keys(1) == []


# ------------------------------------------------------------------ 미리보기 = 실행(divergence 0)
def test_preview_equals_execution_of_saved_item(tmp_path):
    """미리보기가 렌더한 행 == 저장된 풀 항목을 실행 경로로 복원해 읽은 행(문자 그대로)."""
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.add_step("merge", 1, on="id", how="inner")
    pv = vm.preview()
    assert pv.ok and pv.total == 2

    item = vm.save("6월 조립")
    restored = source_from_pool_item(item)
    assert isinstance(restored, PipelineSource)
    assert restored.records() == pv.rows       # divergence 0
    assert restored.fields() == pv.fields


def test_saved_item_stores_references_only(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.add_step("merge", 1, on="id", how="left")
    vm.save("조립저장")
    reg = vm.registry
    saved = reg.path_for("조립저장").read_text(encoding="utf-8")
    assert "서울" not in saved and "부산" not in saved  # 레코드 스냅샷 없음
    assert "base.csv" in saved and "merge" in saved     # 참조·레시피만
    assert reg.load("조립저장").kind == "pipeline"


def test_preview_surfaces_assembly_failure_loudly(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    assert not vm.preview().ok  # 소스 없음 → error 문구
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.steps.append({"op": "merge", "source": 1, "on": "없는키", "how": "inner"})
    pv = vm.preview()
    assert not pv.ok and "없는키" in pv.error  # 조용한 빈 표 금지 — 오류 표면화


def test_preview_limits_rows_but_reports_total(tmp_path):
    big = tmp_path / "big.csv"
    big.write_text("id\n" + "\n".join(str(i) for i in range(50)), encoding="utf-8-sig")
    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="큰것", kind="excel", opts={"path": str(big)}))
    vm = PipelineBuilderViewModel(reg)
    vm.add_source("큰것")
    pv = vm.preview(limit=20)
    assert pv.total == 50 and len(pv.rows) == 20


# ------------------------------------------------------------------ 저장 검증
def test_save_requires_name_and_sources(tmp_path):
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    with pytest.raises(ValueError, match="이름"):
        vm.save("  ")
    with pytest.raises(ValueError, match="소스"):
        vm.save("이름있음")


# ------------------------------------------------------------------ 나라 서브소스 키 주입
def test_builder_with_nara_subsource_inherits_key_injection(tmp_path):
    reg = _pool_with_csvs(tmp_path)
    reg.save(
        DatasetPoolItem(
            name="나라쿼리", kind="nara",
            opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
        )
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    vm = PipelineBuilderViewModel(
        reg, secret_store=store, fetcher=lambda url: _fixture_bytes()
    )
    vm.add_source("나라쿼리")
    pv = vm.preview()
    assert pv.ok and pv.total == 2  # 키 주입·주입 fetcher 로 실취득 관통
    # 저장물에도 키 흔적 0(KA 불변식 계승).
    vm.save("나라조립")
    saved = reg.path_for("나라조립").read_text(encoding="utf-8")
    assert _LIVE_KEY not in saved and "service_key" not in saved


def test_builder_nara_without_key_previews_loud_error(tmp_path):
    reg = _pool_with_csvs(tmp_path)
    reg.save(
        DatasetPoolItem(
            name="나라쿼리", kind="nara",
            opts={"bgn_dt": "202606010000", "end_dt": "202606302359"},
        )
    )
    vm = PipelineBuilderViewModel(reg, secret_store=MemorySecretStore())
    vm.add_source("나라쿼리")
    pv = vm.preview()
    assert not pv.ok and "서비스키" in pv.error  # 키 미등록 → 시끄럽게(조용한 빈 취득 금지)
