"""조립 파이프라인(KA) 헤드리스 테스트 — 여러 소스 → 하나의 DataSource.

merge/append 시맨틱·정규화·시끄러운 degrade(AssemblyError)·DataSource 계약을 못박고,
파이프라인 풀 항목 라운드트립(참조만·스냅샷 없음)과 나라 sub-source 키 주입 재귀를 검증한다
(네트워크·실 저장소 무접촉).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import SlugCollisionError
from hwpxfiller.data import DataSource, make_source
from hwpxfiller.data.factory import source_from_pool_item
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.data.pipeline import (
    AssemblyError,
    PipelineSource,
    StdlibAssemblyEngine,
)
from hwpxfiller.data.secret_store import NARA_SERVICE_KEY_NAME, MemorySecretStore

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


class FakeSource:
    """테스트용 인메모리 DataSource — 레코드·어휘를 주입해 조립 로직만 검증."""

    def __init__(self, records, labels=None):
        self._records = [dict(r) for r in records]
        self._labels = dict(labels or {})

    def records(self):
        return [dict(r) for r in self._records]

    def fields(self):
        seen, keys = set(), []
        for r in self._records:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        return keys

    def field_labels(self):
        return dict(self._labels)


# ------------------------------------------------------------ 엔진: merge 시맨틱
def test_merge_inner_keeps_only_matched_left_rows():
    eng = StdlibAssemblyEngine()
    left = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
    right = [{"id": "1", "city": "서울"}, {"id": "3", "city": "부산"}]
    out = eng.merge(left, right, on="id", how="inner")
    assert out == [{"id": "1", "name": "A", "city": "서울"}]  # id 2·3 은 무매칭 → 제외


def test_merge_left_keeps_all_left_rows_with_blank_right_fields():
    eng = StdlibAssemblyEngine()
    left = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
    right = [{"id": "1", "city": "서울"}]
    out = eng.merge(left, right, on="id", how="left")
    assert out == [
        {"id": "1", "name": "A", "city": "서울"},
        {"id": "2", "name": "B", "city": ""},  # 무매칭 좌측 유지·우측 필드 공란(정규화)
    ]


def test_merge_multiple_right_matches_produce_row_product():
    eng = StdlibAssemblyEngine()
    left = [{"id": "1", "name": "A"}]
    right = [{"id": "1", "city": "서울"}, {"id": "1", "city": "인천"}]
    out = eng.merge(left, right, on="id", how="inner")
    assert out == [
        {"id": "1", "name": "A", "city": "서울"},
        {"id": "1", "name": "A", "city": "인천"},
    ]


def test_merge_left_precedence_on_overlapping_nonkey_column():
    """비-키 겹침 컬럼은 좌측(베이스)이 우선 — 우측이 조용히 덮지 않는다."""
    eng = StdlibAssemblyEngine()
    left = [{"id": "1", "name": "베이스"}]
    right = [{"id": "1", "name": "덮어쓰기시도", "city": "서울"}]
    out = eng.merge(left, right, on="id", how="inner")
    assert out == [{"id": "1", "name": "베이스", "city": "서울"}]


def test_merge_missing_key_fails_loudly():
    eng = StdlibAssemblyEngine()
    left = [{"id": "1"}]
    right = [{"code": "x"}]  # 조인 키 'id' 없음
    with pytest.raises(AssemblyError, match="조인 키"):
        eng.merge(left, right, on="id", how="inner")


def test_merge_rejects_unknown_how():
    eng = StdlibAssemblyEngine()
    with pytest.raises(AssemblyError, match="inner"):
        eng.merge([{"id": "1"}], [{"id": "1"}], on="id", how="outer")


# ------------------------------------------------------------ 엔진: append 시맨틱
def test_append_unions_fields_and_pads_missing_cells():
    eng = StdlibAssemblyEngine()
    out = eng.append([[{"a": "1", "b": "2"}], [{"a": "3", "c": "4"}]])
    assert out == [
        {"a": "1", "b": "2", "c": ""},
        {"a": "3", "b": "", "c": "4"},  # 누락 셀 = "" (직사각형 정규화)
    ]


# ------------------------------------------------------------ PipelineSource 계약
def test_pipeline_source_satisfies_datasource_protocol():
    pipe = PipelineSource([FakeSource([{"id": "1"}])], [])
    assert isinstance(pipe, DataSource)  # runtime_checkable Protocol


def test_pipeline_merge_step_folds_source_into_seed():
    left = FakeSource([{"id": "1", "name": "A"}, {"id": "2", "name": "B"}])
    right = FakeSource([{"id": "1", "city": "서울"}, {"id": "2", "city": "부산"}])
    pipe = PipelineSource(
        [left, right], [{"op": "merge", "source": 1, "on": "id", "how": "inner"}]
    )
    assert pipe.records() == [
        {"id": "1", "name": "A", "city": "서울"},
        {"id": "2", "name": "B", "city": "부산"},
    ]
    assert pipe.fields() == ["id", "name", "city"]


def test_pipeline_append_step_unions_rows():
    a = FakeSource([{"공고명": "전산장비"}])
    b = FakeSource([{"공고명": "청소용역"}])
    pipe = PipelineSource([a, b], [{"op": "append", "source": 1}])
    assert pipe.records() == [{"공고명": "전산장비"}, {"공고명": "청소용역"}]


def test_pipeline_seed_only_returns_first_source_records():
    pipe = PipelineSource([FakeSource([{"x": "1"}])], [])
    assert pipe.records() == [{"x": "1"}]


def test_pipeline_multistep_merge_then_append():
    base = FakeSource([{"id": "1", "name": "A"}])
    lookup = FakeSource([{"id": "1", "city": "서울"}])
    extra = FakeSource([{"id": "2", "name": "C", "city": "대전"}])
    pipe = PipelineSource(
        [base, lookup, extra],
        [
            {"op": "merge", "source": 1, "on": "id", "how": "left"},
            {"op": "append", "source": 2},
        ],
    )
    assert pipe.records() == [
        {"id": "1", "name": "A", "city": "서울"},
        {"id": "2", "name": "C", "city": "대전"},
    ]


# ------------------------------------------------------------ 시끄러운 degrade
def test_pipeline_empty_sources_fails_loudly():
    with pytest.raises(AssemblyError, match="소스가 없습니다"):
        PipelineSource([], []).records()


def test_pipeline_bad_source_index_fails_loudly():
    pipe = PipelineSource([FakeSource([{"x": "1"}])], [{"op": "append", "source": 9}])
    with pytest.raises(AssemblyError, match="소스 인덱스"):
        pipe.records()


def test_pipeline_unknown_op_fails_loudly():
    pipe = PipelineSource([FakeSource([{"x": "1"}])], [{"op": "filter", "source": 0}])
    with pytest.raises(AssemblyError, match="op"):
        pipe.records()


def test_pipeline_missing_step_arg_fails_loudly():
    # merge 스텝에 'on' 누락 → 필수 인자 부재를 시끄럽게
    pipe = PipelineSource(
        [FakeSource([{"id": "1"}]), FakeSource([{"id": "1"}])],
        [{"op": "merge", "source": 1}],
    )
    with pytest.raises(AssemblyError, match="필수 인자"):
        pipe.records()


# ------------------------------------------------------------ 어휘 상속
def test_pipeline_inherits_sub_source_vocabulary():
    """조립 소스의 field_labels 는 서브소스 어휘 병합 — 나라 한글 라벨을 상속한다."""
    excel_like = FakeSource([{"공고명": "x"}], labels={})  # 빈 어휘(헤더=라벨)
    nara_like = FakeSource(
        [{"bidNtceNm": "y"}], labels={"bidNtceNm": "공고명", "presmptPrce": "추정가격"}
    )
    pipe = PipelineSource([excel_like, nara_like], [{"op": "append", "source": 1}])
    labels = pipe.field_labels()
    assert labels["bidNtceNm"] == "공고명"
    assert labels["presmptPrce"] == "추정가격"


# ------------------------------------------------------------ make_source 분기
def test_make_source_pipeline_from_built_sources():
    a = FakeSource([{"id": "1", "name": "A"}])
    b = FakeSource([{"id": "1", "city": "서울"}])
    pipe = make_source(
        "pipeline",
        sources=[a, b],
        steps=[{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
    )
    assert isinstance(pipe, PipelineSource)
    assert pipe.records() == [{"id": "1", "name": "A", "city": "서울"}]


# ------------------------------------------------------------ 풀 항목 라운드트립(참조만)
def _write_csv(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


def test_pipeline_pool_item_roundtrip_references_only(tmp_path):
    """파이프라인 풀 항목은 참조(sources refs + steps)만 담고 레코드를 스냅샷하지 않는다."""
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "id,name\n1,A\n2,B\n")
    _write_csv(b, "id,city\n1,서울\n2,부산\n")

    item = DatasetPoolItem(
        name="6월 조립",
        kind="pipeline",
        opts={
            "sources": [
                {"kind": "excel", "opts": {"path": str(a)}},
                {"kind": "excel", "opts": {"path": str(b)}},
            ],
            "steps": [{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
        },
    )
    # 직렬화 라운드트립 동일성 + 데이터(행) 미저장(참조·레시피만).
    reg = DatasetPoolRegistry(tmp_path)
    reg.save(item)
    saved = reg.path_for("6월 조립").read_text(encoding="utf-8")
    assert "서울" not in saved and "부산" not in saved  # 데이터 스냅샷 없음
    assert "a.csv" in saved and "merge" in saved  # 참조·레시피는 있음(JSON 은 \\ 이스케이프)
    assert reg.load("6월 조립").to_dict() == item.to_dict()

    # 복원 = 실행 시점 재읽기(싱크) → 실제 조립 관통.
    src = source_from_pool_item(item)
    assert isinstance(src, PipelineSource)
    assert src.records() == [
        {"id": "1", "name": "A", "city": "서울"},
        {"id": "2", "name": "B", "city": "부산"},
    ]


def test_pipeline_pool_item_slug_collision_is_loud(tmp_path):
    """파이프라인 항목도 다른 이름·같은 slug 저장 시 loud 거부 — 참조·레시피 소실 방지(#34)."""
    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="6월/조립", kind="pipeline", opts={"sources": [], "steps": []}))
    with pytest.raises(SlugCollisionError):
        reg.save(DatasetPoolItem(name="6월_조립", kind="pipeline", opts={"sources": [], "steps": []}))
    # 확정 덮어쓰기는 opt-in 으로만.
    reg.save(
        DatasetPoolItem(name="6월_조립", kind="pipeline", opts={"sources": [], "steps": []}),
        allow_overwrite=True,
    )
    assert reg.names() == ["6월_조립"]


# ------------------------------------------------------------ 나라 sub-source 키 주입 재귀
def test_pipeline_restore_injects_nara_key_recursively():
    """파이프라인 sub-source 가 나라면 재귀 복원이 기존 SecretStore 키 주입을 상속한다."""
    item = DatasetPoolItem(
        name="나라 조립",
        kind="pipeline",
        opts={
            "sources": [
                {
                    "kind": "nara",
                    "opts": {
                        "bgn_dt": "202606010000",
                        "end_dt": "202606302359",
                        "num_rows": 50,
                    },
                }
            ],
            "steps": [],
        },
    )
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    src = source_from_pool_item(
        item, secret_store=store, fetcher=lambda url: _fixture_bytes()
    )
    assert isinstance(src, PipelineSource)
    sub = src.sources[0]
    assert isinstance(sub, NaraStdDataSource)
    assert sub.service_key == _LIVE_KEY  # 재귀가 키 주입 경로 상속(make_source 직결 우회 안 함)
    assert sub.num_rows == 50
    assert len(src.records()) == 2  # 주입 fetcher 로 실제 취득 관통


def test_pipeline_restore_nara_subsource_without_key_fails_loudly():
    item = DatasetPoolItem(
        name="나라 조립",
        kind="pipeline",
        opts={
            "sources": [
                {"kind": "nara", "opts": {"bgn_dt": "202606010000", "end_dt": "202606302359"}}
            ],
            "steps": [],
        },
    )
    with pytest.raises(ValueError, match="서비스키"):
        source_from_pool_item(item, secret_store=MemorySecretStore())  # 키 미등록
