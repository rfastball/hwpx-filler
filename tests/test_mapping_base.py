"""공유 베이스 매핑(J3) 코어 테스트 — 레지스트리·작업 계보·프로파일 행 구성(헤드리스).

베이스 = 명명 MappingProfile(데이터·키 없음). 작업의 base_mapping_name 은 계보 메타(run-path 무관).
"""

from __future__ import annotations

import pytest

from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.mapping_base import (
    MappingBaseRegistry,
    default_mapping_bases_dir,
)


def _base(name="조달어휘") -> MappingProfile:
    return MappingProfile(name=name, mappings=[
        FieldMapping(template_field="공고명", sources=["bidNtceNm"]),
        FieldMapping(template_field="추정가격", sources=["presmptPrce"], transform="amount"),
    ])


# ------------------------------------------------------------------ 레지스트리
def test_registry_roundtrip(tmp_path):
    reg = MappingBaseRegistry(tmp_path)
    assert reg.list_bases() == []
    reg.save(_base())
    assert reg.exists("조달어휘")
    loaded = reg.load("조달어휘")
    assert loaded.template_fields() == ["공고명", "추정가격"]
    assert loaded.mappings[1].transform == "amount"


def test_registry_list_sorted_and_delete(tmp_path):
    reg = MappingBaseRegistry(tmp_path)
    reg.save(_base("나"))
    reg.save(_base("가"))
    assert reg.names() == ["가", "나"]  # 이름순
    reg.delete("가")
    assert reg.names() == ["나"]
    reg.delete("없음")  # 멱등


def test_registry_rejects_empty_name(tmp_path):
    reg = MappingBaseRegistry(tmp_path)
    with pytest.raises(ValueError):
        reg.save(MappingProfile(name="", mappings=[]))


def test_default_dir_uses_home_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_mapping_bases_dir() == tmp_path / "mapping_bases"


# ------------------------------------------------------------------ 작업 계보
def test_job_base_name_roundtrip():
    job = Job(name="공고작업", template_path="/t.hwpx",
              mapping=_base(), base_mapping_name="조달어휘")
    back = Job.from_dict(job.to_dict())
    assert back.base_mapping_name == "조달어휘"


def test_job_base_name_backward_compatible():
    """구 JSON(base_mapping_name 없음) → 기본 ""(하위호환)."""
    old = {"name": "구작업", "template_path": "/t.hwpx", "mapping": {"mappings": []}}
    job = Job.from_dict(old)
    assert job.base_mapping_name == ""


def test_base_name_does_not_affect_run_path():
    """계보 필드는 순수 메타 — RunRequest 매핑 적용에 무영향(엔진은 job.mapping 만 소비)."""
    from hwpxfiller.core.job import RunRequest

    class _Src:
        def records(self):
            return [{"bidNtceNm": "전산장비", "presmptPrce": "1000"}]

    job = Job(name="j", template_path="/t.hwpx", mapping=_base(),
              base_mapping_name="조달어휘")
    req = RunRequest(job, _Src(), [0])
    mapped = req.mapped_records()
    assert mapped[0]["공고명"] == "전산장비"  # base_mapping_name 유무와 무관


# ------------------------------------------------------------ from_profile
def test_mapping_model_from_profile_builds_confirmed_rows():
    from hwpxfiller.gui.mapping_state import MappingModel

    model = MappingModel.from_profile(_base())
    assert [r.template_field for r in model.rows] == ["공고명", "추정가격"]
    assert all(r.confirmed for r in model.rows)  # 베이스는 확정본
    assert model.rows[1].transform == "amount"
    # source_fields = 참조 소스 키 합집합(테이블 소스 피커 후보).
    assert set(model.source_fields) == {"bidNtceNm", "presmptPrce"}
    assert model.is_complete()  # 전 행 확정 → 게이트 통과
