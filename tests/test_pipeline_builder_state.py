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


def test_remove_seed_source_with_steps_fails_loudly(tmp_path):
    """씨앗(index 0) 제거는 스텝이 있는 한 거부 — 조용한 승격·자기조인 금지(적대 리뷰 결함 1).

    씨앗은 스텝이 명시 참조하지 않아도 파이프라인 의미가 암묵 참조한다. 제거를 허용하면
    다음 소스가 기준으로 승격되며 merge 스텝이 자기조인(행 제곱)으로 조용히 변한다.
    """
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.add_step("merge", 1, on="id", how="inner")
    with pytest.raises(ValueError, match="기준"):
        vm.remove_source(0)
    # 스텝 제거 후엔 허용 — 승격이 일어나되 스텝 없는 상태라 의미 왜곡 없음(목록에 가시).
    vm.remove_step(0)
    vm.remove_source(0)
    assert [s.name for s in vm.sources] == ["참조표"]


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


def test_suggest_merge_keys_zero_rows_fails_loudly_not_false_negative(tmp_path):
    """0행 중간결과에선 '공유 컬럼 없음' 확언 대신 감지 불가를 시끄럽게(적대 리뷰 결함 2).

    파이프라인 fields 는 레코드 유도라 0행에선 스키마상 공유 컬럼(양쪽 헤더의 id)이
    실재해도 안 보인다 — 불확실을 오답으로 단정하지 않는다.
    """
    empty = tmp_path / "empty.csv"
    empty.write_text("id,name\n", encoding="utf-8-sig")  # 헤더만, 0행
    reg = _pool_with_csvs(tmp_path)
    reg.save(DatasetPoolItem(name="빈것", kind="excel", opts={"path": str(empty)}))
    vm = PipelineBuilderViewModel(reg)
    vm.add_source("빈것")    # 씨앗 0행
    vm.add_source("참조표")  # id 공유(스키마상 실재)
    with pytest.raises(ValueError, match="감지"):
        vm.suggest_merge_keys(1)


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


def test_save_refuses_invalid_assembly_loudly(tmp_path):
    """저장 게이트가 실행과 같은 복원 경로로 조립 유효성을 확인 — 깨진 조립은 실행 시점이
    아니라 저장 시점에 시끄럽게 실패하고 커밋되지 않는다(UD-01: save 가 build_source 무호출로
    부재 키·빈 취득을 통과시키던 결함).
    """
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.steps.append({"op": "merge", "source": 1, "on": "없는키", "how": "inner"})  # 부재 키
    with pytest.raises(ValueError, match="유효하지 않아"):
        vm.save("깨진조립")
    assert not vm.registry.exists("깨진조립")  # 깨진 조립은 커밋되지 않는다


def test_save_valid_assembly_still_commits(tmp_path):
    """유효성 게이트가 정상 조립의 저장을 막지 않는다(회귀 가드)."""
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    vm.add_source("참조표")
    vm.add_step("merge", 1, on="id", how="inner")
    item = vm.save("정상조립")
    assert item.kind == "pipeline" and vm.registry.exists("정상조립")


def test_save_name_collision_refused_without_explicit_overwrite(tmp_path):
    """동명 풀 항목을 조용히 덮지 않는다 — overwrite 명시로만(적대 리뷰 결함 3).

    빌더 소스 콤보에 노출되는 기존 이름('기준' 등)으로 저장하면 durable 참조가
    무경고 소실되던 경로를 닫는다.
    """
    vm = PipelineBuilderViewModel(_pool_with_csvs(tmp_path))
    vm.add_source("기준")
    with pytest.raises(ValueError, match="이미 있습니다"):
        vm.save("기준")  # 기존 excel 항목과 동명 — 거부
    assert vm.registry.load("기준").kind == "excel"  # 원본 무손실
    item = vm.save("기준", overwrite=True)  # 사람 확정 경유(대화상자)만 이 플래그를 쓴다
    assert item.kind == "pipeline"
    assert vm.registry.load("기준").kind == "pipeline"


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
