"""작업(Job) 데이터모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀: (1) 작업 저장→로드가 임베드된 매핑을 값·**행위**까지 온전 보존한다,
(2) 레지스트리가 작업당 JSON 1개로 목록/로드/삭제하며 이름 slug 이 파일명만 정리하고
원 이름은 JSON 안에 온전하다, (3) RunRequest 사전검증이 빠진 소스키(missing_columns)와
빈 출력값(empty_valued)을 Qt·Excel 없이 잡아낸다.
"""

from __future__ import annotations

from hwpxfiller.core.job import Job, JobRegistry, RunRequest, default_jobs_dir
from hwpxfiller.core.mapping import FieldMapping, MappingProfile


class _FakeSource:
    """dict 백드 DataSource — 실 Excel/Qt 없이 집행 사전검증을 테스트."""

    def __init__(self, records: "list[dict]"):
        self._records = records

    def records(self) -> "list[dict]":
        return self._records

    def fields(self) -> "list[str]":
        keys: "dict[str, None]" = {}
        for r in self._records:
            for k in r:
                keys.setdefault(k, None)
        return list(keys)


def _profile() -> MappingProfile:
    return MappingProfile(
        name="p",
        mappings=[
            FieldMapping("공고명", ["bidNtceNm"], transform="join"),
            FieldMapping("추정가격", ["presmptPrce"], transform="amount", fmt="{:,}"),
        ],
    )


def _job() -> Job:
    return Job(
        name="입찰공고서",
        template_path="/tmp/template.hwpx",
        mapping=_profile(),
        filename_pattern="공고서-{{공고명}}",
    )


# ------------------------------------------------------------------ 직렬화
def test_to_dict_from_dict_roundtrip_preserves_embedded_mapping():
    """작업 dict 왕복이 임베드된 매핑의 소스·표시형까지 보존한다."""
    loaded = Job.from_dict(_job().to_dict())
    assert loaded.name == "입찰공고서"
    assert loaded.template_path == "/tmp/template.hwpx"
    assert loaded.filename_pattern == "공고서-{{공고명}}"
    assert loaded.mapping.mappings[1].sources == ["presmptPrce"]
    assert loaded.mapping.mappings[1].fmt == "{:,}"


def test_save_load_roundtrip_preserves_mapping_behavior(tmp_path):
    """저장→로드된 작업의 매핑이 같은 값을 낸다(표시형 서식 포함) — 행위 재검증."""
    path = tmp_path / "job.json"
    _job().save(path)
    loaded = Job.load(path)
    assert loaded.mapping.apply({"bidNtceNm": "테스트", "presmptPrce": "21326800"}) == {
        "공고명": "테스트",
        "추정가격": "21,326,800",
    }


def test_default_mapping_is_empty_profile():
    """빈 작업은 빈 프로파일을 갖는다(데이터·행 미포함 원칙의 최소형)."""
    job = Job()
    assert job.mapping.mappings == []
    assert job.template_fields() == []
    assert job.source_keys() == []


# ------------------------------------------------------------ 필드 질의
def test_template_fields_and_source_keys():
    """template_fields=매핑 방출 집합, source_keys=매핑이 읽는 소스 키."""
    job = _job()
    assert job.template_fields() == ["공고명", "추정가격"]
    assert job.source_keys() == ["bidNtceNm", "presmptPrce"]


def test_source_keys_dedupes_across_mappings_preserving_order():
    """여러 매핑이 같은 소스 키를 읽어도 문서순 1회만(중복 제거)."""
    job = Job(
        mapping=MappingProfile(
            mappings=[
                FieldMapping("일시", ["d", "t"], transform="datetime"),
                FieldMapping("다른", ["d"]),  # d 재등장
            ]
        )
    )
    assert job.source_keys() == ["d", "t"]


# ------------------------------------------------------------ 레지스트리
def test_registry_save_load_names_delete(tmp_path):
    """작업당 JSON 1개 — 저장·존재·목록·로드·삭제 왕복."""
    reg = JobRegistry(tmp_path)
    assert reg.list_jobs() == []  # 빈 디렉터리
    reg.save(_job())
    assert reg.exists("입찰공고서")
    assert reg.names() == ["입찰공고서"]
    assert reg.load("입찰공고서").filename_pattern == "공고서-{{공고명}}"
    reg.delete("입찰공고서")
    assert not reg.exists("입찰공고서")
    assert reg.list_jobs() == []


def test_registry_missing_directory_lists_empty(tmp_path):
    """없는 디렉터리를 가리켜도 목록은 조용히 빈 리스트(생성 전)."""
    reg = JobRegistry(tmp_path / "nope")
    assert reg.list_jobs() == []
    assert reg.names() == []


def test_registry_save_twice_same_name_overwrites(tmp_path):
    """같은 이름 재저장은 덮어씀 — 목록에 중복 안 생김."""
    reg = JobRegistry(tmp_path)
    reg.save(_job())
    j2 = _job()
    j2.filename_pattern = "새-{{공고명}}"
    reg.save(j2)
    assert len(reg.list_jobs()) == 1
    assert reg.load("입찰공고서").filename_pattern == "새-{{공고명}}"


def test_registry_slug_keeps_original_name_in_json(tmp_path):
    """파일명은 slug 로 정리하되 이름 자체는 JSON 안에 온전 — 로드가 원 이름 복원."""
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="2026/06 공고:안", template_path="/t.hwpx", mapping=_profile()))
    assert reg.load("2026/06 공고:안").name == "2026/06 공고:안"


def test_registry_list_jobs_sorted_by_name(tmp_path):
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="나공고", template_path="/t.hwpx"))
    reg.save(Job(name="가공고", template_path="/t.hwpx"))
    assert [j.name for j in reg.list_jobs()] == ["가공고", "나공고"]


# ------------------------------------------------------------ 집행 사전검증
def test_run_request_selected_and_mapped_records():
    """선택 인덱스만, 원본 순서로 → 작업 매핑 적용 결과."""
    src = _FakeSource(
        [
            {"bidNtceNm": "가", "presmptPrce": "1000"},
            {"bidNtceNm": "나", "presmptPrce": "2000"},
            {"bidNtceNm": "다", "presmptPrce": "3000"},
        ]
    )
    req = RunRequest(_job(), src, [0, 2])
    assert req.selected_records() == [
        {"bidNtceNm": "가", "presmptPrce": "1000"},
        {"bidNtceNm": "다", "presmptPrce": "3000"},
    ]
    assert req.mapped_records() == [
        {"공고명": "가", "추정가격": "1,000"},
        {"공고명": "다", "추정가격": "3,000"},
    ]


def test_run_request_source_report_flags_missing_source_key():
    """겨눈 소스에 매핑이 읽는 소스키가 없으면 소스 수준 missing_columns 로 뜬다."""
    src = _FakeSource([{"bidNtceNm": "가"}])  # presmptPrce 부재
    report = RunRequest(_job(), src, [0]).source_report()
    assert "presmptPrce" in report.missing_columns
    assert "bidNtceNm" not in report.missing_columns


def test_run_request_output_report_flags_empty_value():
    """매핑된 출력에 빈 값이 있으면 template_field 이름으로 empty_valued."""
    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])  # 공고명 빈값
    report = RunRequest(_job(), src, [0]).output_report()
    assert "공고명" in report.empty_valued


def test_default_jobs_dir_honors_env_override(monkeypatch, tmp_path):
    """HWPXFILLER_HOME 로 레지스트리 위치를 재지정(테스트·이식성)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_jobs_dir() == tmp_path / "jobs"
