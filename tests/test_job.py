"""작업(Job) 데이터모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀: (1) 작업 저장→로드가 임베드된 매핑을 값·**행위**까지 온전 보존한다,
(2) 레지스트리가 작업당 JSON 1개로 목록/로드/삭제하며 이름 slug 이 파일명만 정리하고
원 이름은 JSON 안에 온전하다, (3) RunRequest 사전검증이 빠진 소스키(missing_columns)와
빈 출력값(empty_valued)을 Qt·Excel 없이 잡아낸다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.core.job import (
    Job,
    JobRegistry,
    JobSlugCollisionError,
    RunRequest,
    SlugCollisionError,
    content_fingerprint,
    default_jobs_dir,
)
from hwpxfiller.core.mapping import FieldMapping, MappingProfile


class _FakeSource:
    """dict 백드 DataSource — 실 Excel/Qt 없이 실행 사전검증을 테스트."""

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
            FieldMapping("공고명", "bidNtceNm", type="text"),
            FieldMapping("추정가격", "presmptPrce", type="amount", fmt="{:,}"),
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
def test_default_filename_pattern_is_single_source():
    """기본 패턴 단일 출처(RC-20) — dataclass·from_dict 하위호환이 같은 상수를 참조하고,
    값은 **예약 토큰만** 쓴다(F34b) — 데이터 필드 토큰이 섞이면 그 열이 없는 데이터에서
    기본값이 곧 보장된 미해소 파일명 + 전 레코드 동일명이 된다."""
    from hwpxfiller.core.job import DEFAULT_FILENAME_PATTERN
    from hwpxfiller.naming import pattern_field_tokens

    assert DEFAULT_FILENAME_PATTERN == "공고서-{{date}}-{{seq:001}}"
    assert pattern_field_tokens(DEFAULT_FILENAME_PATTERN) == []  # 데이터 토큰 0 = 항상 해소
    assert Job().filename_pattern == DEFAULT_FILENAME_PATTERN
    assert Job.from_dict({}).filename_pattern == DEFAULT_FILENAME_PATTERN


def test_to_dict_from_dict_roundtrip_preserves_embedded_mapping():
    """작업 dict 왕복이 임베드된 매핑의 소스·표시형까지 보존한다."""
    loaded = Job.from_dict(_job().to_dict())
    assert loaded.name == "입찰공고서"
    assert loaded.template_path == "/tmp/template.hwpx"
    assert loaded.filename_pattern == "공고서-{{공고명}}"
    assert loaded.mapping.mappings[1].source == "presmptPrce"
    assert loaded.mapping.mappings[1].type == "amount"
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


def test_last_run_at_roundtrip_and_backward_compat():
    """가산 필드 last_run_at — 왕복 보존 + 구 JSON(키 부재)은 기본값 ""(version 1 유지)."""
    job = _job()
    job.last_run_at = "2026-07-10T12:34:56"
    loaded = Job.from_dict(job.to_dict())
    assert loaded.last_run_at == "2026-07-10T12:34:56"
    assert loaded.version == 1

    old_dict = _job().to_dict()
    del old_dict["last_run_at"]  # 구 버전이 저장한 JSON
    assert Job.from_dict(old_dict).last_run_at == ""


def test_tags_roundtrip_and_backward_compat():
    """가산 필드 tags(브라우징 분류, JOB_BROWSER_DESIGN D13) — 왕복 보존 +
    구 JSON(키 부재)은 기본값 {}(version 1 유지). 축·값은 이름 문자열 그대로."""
    job = _job()
    job.tags = {"금액구간": "1억미만", "목적물": "물품"}
    loaded = Job.from_dict(job.to_dict())
    assert loaded.tags == {"금액구간": "1억미만", "목적물": "물품"}
    assert loaded.version == 1

    old_dict = _job().to_dict()
    del old_dict["tags"]  # tags 필드 도입 전 저장된 JSON
    from_old = Job.from_dict(old_dict)
    assert from_old.tags == {}
    assert from_old.version == 1

    # 미태깅이 기본(선택적 — D12): 빈 작업도 빈 dict.
    assert Job().tags == {}
    # from_dict 는 방어적 복사 — 원 dict 변형이 로드된 작업에 새지 않는다(opts 선례).
    src = {"tags": {"목적물": "용역"}}
    loaded2 = Job.from_dict(src)
    src["tags"]["목적물"] = "공사"
    assert loaded2.tags == {"목적물": "용역"}


def test_default_dataset_ref_roundtrip_and_backward_compat():
    """가산 필드 default_dataset_ref(#53-A) — 왕복 보존 + 구 JSON(키 부재)은 기본값 ""
    (version 1 유지). 없으면 실행 화면이 현행처럼 수동 데이터 선택."""
    job = _job()
    job.default_dataset_ref = "월별_낙찰현황"
    loaded = Job.from_dict(job.to_dict())
    assert loaded.default_dataset_ref == "월별_낙찰현황"
    assert loaded.version == 1

    old_dict = _job().to_dict()
    del old_dict["default_dataset_ref"]  # 필드 도입 전 저장된 JSON
    from_old = Job.from_dict(old_dict)
    assert from_old.default_dataset_ref == ""  # 기본 데이터 없음으로 동작
    assert from_old.version == 1
    assert Job().default_dataset_ref == ""     # 미연결이 기본(선택적)


def test_from_dict_rejects_type_corrupt_durable_values():
    """durable 로드 경계 — 문자열 계약 필드가 비문자열이면 loud 하게 던진다(내구성 라운드 #1·3·4).

    앱은 늘 str 값만 쓰므로 int/list/null 은 외부 훼손 신호다. 조용히 통과하면 나중에 홈
    렌더(혼합타입 sorted·_fmt_iso TypeError)에서 무관한 작업까지 죽이거나 계보 비교를 무성
    무효화한다 — 경계에서 격리해 RC-05 손상 행으로 표면화(confirm-or-alarm)."""
    base = _job().to_dict()
    corrupt_variants = [
        {**base, "tags": {"금액구간": 123}},   # 비문자열 tags 값 → group-by/facet 혼합 sorted 지뢰
        {**base, "tags": None},                # dict(None) 크래시 대신 loud
        {**base, "tags": ["금액구간"]},         # tags 가 리스트
        {**base, "last_run_at": 1720000000},   # 비문자열 시각 → refresh 의 _fmt_iso 지뢰
        {**base, "name": 5},                   # 비문자열 이름
        {**base, "default_dataset_ref": 7},    # 비문자열 참조 → 겨눔 이름 조회 지뢰
    ]
    for d in corrupt_variants:
        with pytest.raises(ValueError):
            Job.from_dict(d)


def test_from_dict_backward_compat_survives_boundary():
    """경계 강화가 가산 하위호환을 깨지 않는다 — 신 필드 없는 구 JSON 은 여전히 기본값 로드.

    역방향도 대칭: 제거된 필드(base_mapping_name, F22)가 남은 구 JSON 은 미지 키로
    무시된다(타입이 깨져 있어도 — 읽지 않는 키는 검증 대상이 아니다).
    """
    old = {"name": "구작업", "template_path": "/t.hwpx"}  # tags·last_run·version 전무
    job = Job.from_dict(old)
    assert job.name == "구작업" and job.tags == {} and job.last_run_at == ""
    assert job.version == 1
    assert Job.from_dict({"name": "잔재", "base_mapping_name": "베이스"}).name == "잔재"
    assert Job.from_dict({}).name == ""  # 완전 빈 dict 도 기본값 작업


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
                FieldMapping("개찰일", "d", type="date"),
                FieldMapping("개찰시각", "t", type="date", fmt="%H:%M"),
                FieldMapping("다른", "d"),  # d 재등장
            ]
        )
    )
    assert job.source_keys() == ["d", "t"]


def test_source_keys_skips_even_malformed_blank_source():
    job = Job(mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("비고", "must_not_be_required", type="blank"),
    ]))
    assert job.source_keys() == ["name"]


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


def test_registry_exists_guards_missing_and_deleted_name(tmp_path):
    """UD-03 실행 진입 가드의 링0 술어 — 미저장·삭제 후 이름은 exists()=False,
    load 는 예외. app._open_run 이 load 직행 전 이 술어로 '사라진 작업'을 걸러낸다."""
    reg = JobRegistry(tmp_path)
    assert not reg.exists("사라진작업")            # 미저장 → False
    with pytest.raises(FileNotFoundError):
        reg.load("사라진작업")                     # 가드 없이 load 직행하면 예외
    reg.save(Job(name="사라진작업", template_path="/t.hwpx"))
    assert reg.exists("사라진작업")
    reg.delete("사라진작업")
    assert not reg.exists("사라진작업")            # 삭제 후 → False(가드가 잡는 상태)


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


def test_registry_save_rejects_slug_collision_different_name(tmp_path):
    """다른 이름이 같은 slug(=같은 파일)로 매핑되면 loud raise — 첫 작업 소실 방지(#1)."""
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="예산/2026", template_path="/a.hwpx", tags={"금액구간": "1억미만"}))
    with pytest.raises(JobSlugCollisionError):
        reg.save(Job(name="예산_2026", template_path="/b.hwpx", tags={"낙찰방법": "협상"}))
    # 첫 작업이 온전 보존된다(덮이지 않음).
    assert reg.load("예산/2026").template_path == "/a.hwpx"
    assert [j.template_path for j in reg.list_jobs()] == ["/a.hwpx"]


def test_registry_save_allow_overwrite_bypasses_guard(tmp_path):
    """명시적 opt-in(allow_overwrite) 은 slug 충돌을 통과 — 확정된 덮어쓰기."""
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="예산/2026", template_path="/a.hwpx"))
    reg.save(Job(name="예산_2026", template_path="/b.hwpx"), allow_overwrite=True)
    assert len(reg.list_jobs()) == 1
    assert reg.load("예산_2026").template_path == "/b.hwpx"


def test_registry_save_corrupt_target_is_loud(tmp_path):
    """대상 파일이 손상돼 소유 작업을 확인할 수 없으면 allow_overwrite 없이는 raise."""
    reg = JobRegistry(tmp_path)
    reg.directory.mkdir(parents=True, exist_ok=True)
    reg.path_for("입찰공고서").write_text('{"name": "절단', encoding="utf-8")
    with pytest.raises(JobSlugCollisionError):
        reg.save(_job())
    # 명시 opt-in 이면 손상 파일도 덮어쓸 수 있다.
    reg.save(_job(), allow_overwrite=True)
    assert reg.load("입찰공고서").template_path == "/tmp/template.hwpx"


def test_job_slug_collision_error_is_generalized_alias():
    """#34: JobSlugCollisionError 는 공용 SlugCollisionError 의 하위호환 별칭(같은 클래스).

    세 레지스트리가 한 계약을 공유하도록 일반화했고, #1 이 도입한 이름은 기존 호출·테스트가
    잡던 예외 계약을 깨지 않게 같은 클래스를 가리킨다."""
    assert JobSlugCollisionError is SlugCollisionError


def test_registry_list_jobs_sorted_by_name(tmp_path):
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="나공고", template_path="/t.hwpx"))
    reg.save(Job(name="가공고", template_path="/t.hwpx"))
    assert [j.name for j in reg.list_jobs()] == ["가공고", "나공고"]


def test_registry_list_jobs_isolates_corrupt_files(tmp_path):
    """손상 .job.json 1개가 목록 전체를 죽이지 않는다(RC-05) — 격리 + (경로, 오류) 수집."""
    reg = JobRegistry(tmp_path)
    reg.save(_job())
    # 절단 JSON(비원자 저장 실패의 전형) + 유효 JSON 이지만 dict 아님(from_dict 전제 위반).
    (tmp_path / "절단.job.json").write_text('{"name": "절단", "template_pa', encoding="utf-8")
    (tmp_path / "비딕트.job.json").write_text("[1, 2, 3]", encoding="utf-8")

    corrupted: "list[tuple]" = []
    jobs = reg.list_jobs(corrupted=corrupted)
    assert [j.name for j in jobs] == ["입찰공고서"]  # 정상 작업은 살아남는다
    assert {p.name for p, _err in corrupted} == {"절단.job.json", "비딕트.job.json"}
    assert all(err for _p, err in corrupted)  # 오류 사유가 함께 수집된다

    # 수집 리스트를 안 넘긴 기존 호출측도 예외 전파 없이 정상 작업만 받는다.
    assert [j.name for j in reg.list_jobs()] == ["입찰공고서"]
    assert reg.names() == ["입찰공고서"]


def test_registry_isolates_type_corrupt_files(tmp_path):
    """JSON 은 정상 파싱되지만 값 타입이 깨진 파일도 RC-05 격리(내구성 라운드).

    int/null 값은 JSON 정상 파싱이라 구 무검증 로더는 조용히 통과시켜 홈 렌더의 지뢰가
    됐다 — 강화된 from_dict 경계가 loud 하게 격리해 손상 1건이 정상 작업을 죽이지 못한다.
    """
    import json as _json

    reg = JobRegistry(tmp_path)
    reg.save(_job())  # 정상
    (tmp_path / "정수태그.job.json").write_text(
        _json.dumps({"name": "정수태그", "tags": {"금액구간": 123}}), encoding="utf-8"
    )
    (tmp_path / "정수시각.job.json").write_text(
        _json.dumps({"name": "정수시각", "last_run_at": 1720000000}), encoding="utf-8"
    )
    corrupted: "list[tuple]" = []
    jobs = reg.list_jobs(corrupted=corrupted)
    assert [j.name for j in jobs] == ["입찰공고서"]  # 정상 작업만 생존
    assert {p.name for p, _e in corrupted} == {"정수태그.job.json", "정수시각.job.json"}
    assert all(err for _p, err in corrupted)


# ------------------------------------------------------------ 실행 사전검증
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


def test_mapped_records_mark_missing_only_empty_values():
    """표식 주입 — 값이 빈 키만 치환, 비빈 값 불변, 의도적 공란(키 부재)은 그대로."""
    from hwpxfiller.core.job import MISSING_MARKER

    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])
    req = RunRequest(_job(), src, [0])

    marked = req.mapped_records(mark_missing=MISSING_MARKER)
    assert marked[0]["공고명"] == "〘미입력·공고명〙"       # 미충족 공란 → 표식
    assert marked[0]["추정가격"] == "1,000"                 # 비빈 값 불변(표시형 유지)
    # 의도적 공란 = 프로파일이 키를 제외 → 표식 대상 자체가 아님.
    assert set(marked[0]) == set(_job().template_fields())


def test_mapped_records_default_unchanged_and_marker_silences_empty_report():
    """기본 인자 = 기존 동작 회귀 + 표식 주입 후 empty_valued 무경보(주입 확인의 거울)."""
    from hwpxfiller.core.job import MISSING_MARKER
    from hwpxcore.validate import validate

    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])
    req = RunRequest(_job(), src, [0])

    plain = req.mapped_records()
    assert plain[0]["공고명"] == ""  # 기본값이면 그대로(하위호환)

    marked = req.mapped_records(mark_missing=MISSING_MARKER)
    report = validate(_job().template_fields(), marked)
    assert not report.empty_valued  # 표식은 비어 있지 않은 값 — 엔진 빈값 스킵 통과


def test_blank_key_and_placeholder_survive_mark_missing_and_real_hwpx(tmp_path):
    """blank는 RunRequest 표식 대상에도 엔진 입력에도 없고 실제 누름틀 값이 보존된다."""
    from pathlib import Path

    from hwpxfiller.core.engine import HwpxEngine
    from hwpxfiller.core.fields import read_fields
    from hwpxfiller.core.job import MISSING_MARKER

    template = Path(__file__).parent / "corpus" / "real" / "bid_notice_limited_under100m.hwpx"
    mapping = MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("입찰공고번호", type="blank"),
        FieldMapping("계약방법", type="blank"),
        FieldMapping("추정가격", type="blank"),
        FieldMapping("개찰일시", type="blank"),
    ])
    req = RunRequest(
        Job(template_path=str(template), mapping=mapping),
        _FakeSource([{"name": ""}]),
        [0],
    )
    marked = req.mapped_records(mark_missing=MISSING_MARKER)[0]
    assert marked == {"공고명": "〘미입력·공고명〙"}

    before = read_fields(str(template))
    out = tmp_path / "marked.hwpx"
    result = HwpxEngine().generate(str(template), marked, str(out))
    assert result.ok
    after = read_fields(str(out))
    assert after["공고명"] == "〘미입력·공고명〙"
    for blank in ["입찰공고번호", "계약방법", "추정가격", "개찰일시"]:
        assert after[blank] == before[blank]


def test_default_jobs_dir_honors_env_override(monkeypatch, tmp_path):
    """HWPXFILLER_HOME 로 레지스트리 위치를 재지정(테스트·이식성)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_jobs_dir() == tmp_path / "jobs"


def test_job_save_failure_preserves_existing_json(tmp_path, monkeypatch):
    """RC-01 — 재저장 중 실패가 기존 작업 JSON 을 절단하지 않는다(원자 쓰기)."""
    import pytest

    job = Job(name="계약", template_path="/t.hwpx",
              mapping=MappingProfile(mappings=[FieldMapping("공고명", "name")]))
    path = tmp_path / "j.job.json"
    job.save(path)
    existing = path.read_text(encoding="utf-8")

    def _boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("hwpxcore.atomic.os.replace", _boom)
    with pytest.raises(OSError):
        job.save(path)
    assert path.read_text(encoding="utf-8") == existing  # 무손상
    assert Job.load(path).name == "계약"                  # 여전히 로드 가능


def test_clone_concurrent_calls_get_unique_names(tmp_path):
    """동시 복제 원자화(F22 리뷰 P2) — pywebview 스레드별 호출의 동시 진입 재현.

    잠금 없이는 여러 호출이 같은 '(복사본)' 이름을 고르고(파일 1개만 남음, 일부는
    원자 쓰기 교체 경합으로 OSError) 이름이 조용히 중복 반환됐다 — 후보 선점~저장을
    인스턴스 잠금으로 직렬화해 4개 동시 호출이 전부 유일 이름·실파일을 얻는다.
    """
    from concurrent.futures import ThreadPoolExecutor

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(_job())
    with ThreadPoolExecutor(max_workers=4) as ex:
        names = list(ex.map(lambda _i: reg.clone("입찰공고서"), range(4)))
    assert len(set(names)) == 4                       # 중복 이름 없음
    for n in names:
        assert reg.exists(n) and reg.load(n).name == n  # 이름만큼 실파일 실재


# ------------------------------------------------------------------ 그룹·이름 변경(결정 43)
def test_group_roundtrip_and_backward_compat():
    job = _job()
    job.group = "2026 상반기"
    d = job.to_dict()
    assert d["group"] == "2026 상반기"
    assert Job.from_dict(d).group == "2026 상반기"
    d.pop("group")  # 구 JSON(가산 스키마) — migrate-on-read 관용으로 기본값
    assert Job.from_dict(d).group == ""


# ---------------------------------------------- 즐겨찾기(v6 §18.5, data-first 슬라이스 2)
def test_favorited_at_roundtrip_and_backward_compat():
    """즐겨찾기는 가산 필드 — 구 JSON 은 기본값 ""(미즐겨찾기)로 관용 로드된다."""
    job = _job()
    job.favorited_at = "2026-07-26T09:00:00"
    d = job.to_dict()
    assert d["favorited_at"] == "2026-07-26T09:00:00"
    assert Job.from_dict(d).favorited_at == "2026-07-26T09:00:00"
    assert Job.from_dict(d).version == 1  # 가산 필드는 version 을 올리지 않는다
    d.pop("favorited_at")
    assert Job.from_dict(d).favorited_at == ""


def test_favorited_at_type_corruption_is_loud():
    d = _job().to_dict()
    d["favorited_at"] = True
    with pytest.raises(ValueError):
        Job.from_dict(d)


def test_preserved_metadata_is_outside_the_content_fingerprint():
    """보존(재읽기) 메타는 지문 밖이다 — 저장이 되싣는 값의 변경으로 파괴 확인을 띄우면 과경고다.

    즐겨찾기는 정렬 메타만 바꾸고(§18.5), 그룹 이동도 저장이 디스크 값을 그대로 되싣는다 —
    별을 눌렀다고, 다른 화면에서 그룹을 옮겼다고 편집 세션이 '외부 변경'을 물어선 안 된다.
    """
    job = _job()
    before = content_fingerprint(job)
    job.favorited_at = "2026-07-26T09:00:00"
    job.group = "조달"
    job.tags = {"물품": "의약품"}
    job.last_run_at = "2026-07-26T10:00:00"
    assert content_fingerprint(job) == before
    job.filename_pattern = "다른패턴"          # 편집 대상 필드는 여전히 지문에 든다
    assert content_fingerprint(job) != before


# ------------------------------- Template·Binding 판본(v6 §13-6·7, 재작성 F7 §10.13)
def test_revisions_roundtrip_and_backward_compat():
    """판본도 가산 필드 — 구 JSON 은 r1·직전 판본 없음으로 관용 로드된다."""
    job = _job()
    job.template_revision, job.binding_revision = 3, 7
    d = job.to_dict()
    assert (d["template_revision"], d["binding_revision"]) == (3, 7)
    assert Job.from_dict(d).binding_revision == 7
    assert Job.from_dict(d).version == 1  # 가산 필드는 version 을 올리지 않는다
    d.pop("template_revision"), d.pop("binding_revision"), d.pop("previous_rules")
    restored = Job.from_dict(d)
    assert (restored.template_revision, restored.binding_revision) == (1, 1)
    assert restored.previous_rules == {}


@pytest.mark.parametrize("bad", [0, -1, "2", 1.0, True, None])
def test_revision_corruption_is_loud(bad):
    """판본은 1 이상의 정수 — ``True`` 도 거른다(파이썬에서 bool 은 int 라 조용히 r1 이 된다)."""
    d = _job().to_dict()
    d["binding_revision"] = bad
    with pytest.raises(ValueError):
        Job.from_dict(d)


def test_previous_rules_shape_corruption_is_loud():
    """직전 판본은 축이 온전한 값 사전이어야 한다 — 증거를 짓는 자리의 조용한 결손 금지."""
    from hwpxfiller.core.job import rules_values

    d = _job().to_dict()
    d["previous_rules"] = rules_values(_job())
    Job.from_dict(d)                                    # 온전한 형상은 통과
    d["previous_rules"] = {"template": "t", "filename": "f", "fields": {"공고명": {"source": "x"}}}
    with pytest.raises(ValueError):                     # 축 누락
        Job.from_dict(d)
    d["previous_rules"] = {"fields": []}
    with pytest.raises(ValueError):                     # fields 가 사전이 아님
        Job.from_dict(d)


def test_revisions_are_outside_the_content_fingerprint():
    """판본 3필드는 지문 밖 — 저장이 계산해 다시 쓰는 파생 메타라 보존 메타와 같은 부류다.

    남기면 다른 표면의 저장·스탬프가 열어 둔 편집 세션에 거짓 파괴 확인을 띄운다.
    """
    from hwpxfiller.core.job import rules_values

    job = _job()
    before = content_fingerprint(job)
    job.template_revision, job.binding_revision = 5, 9
    job.previous_rules = rules_values(_job())
    assert content_fingerprint(job) == before


def test_rules_fingerprints_are_assembled_from_rules_values(tmp_path):
    """지문과 직전 판본 값은 **같은 원재료**를 쓴다 — 한쪽만 고쳐지면 "무엇이 바뀌었나"와
    "무엇이었나"가 서로 다른 규칙을 말한다(§10.13 판정 H).
    """
    from hwpxfiller.core.job import rules_fingerprints, rules_values

    job = _job()
    values, fp = rules_values(job), rules_fingerprints(job)
    assert values["template"] == fp["template"] and values["filename"] == fp["filename"]
    for name, axes in values["fields"].items():
        assert fp[f"field:{name}:format"] == axes["fmt"]
        assert axes["source"] in fp[f"field:{name}:source"]


def test_save_advances_only_the_axis_whose_rules_changed(tmp_path):
    """판본은 **규칙이 갈릴 때만** 오른다(§10.13 판정 G) — 저장 횟수가 아니다."""
    reg = JobRegistry(tmp_path)
    reg.save(_job())
    assert (reg.load("입찰공고서").template_revision,
            reg.load("입찰공고서").binding_revision) == (1, 1)

    same = _job()
    reg.save(same, allow_overwrite=True)                 # 내용 동일 재저장
    saved = reg.load("입찰공고서")
    assert (saved.template_revision, saved.binding_revision) == (1, 1)
    assert saved.previous_rules == {}                    # 바뀐 적 없으면 직전 판본도 없다

    changed = _job()
    changed.filename_pattern = "공고서-{{공고명}}-2"       # 파일 이름 = Binding 축(판정 F)
    reg.save(changed, allow_overwrite=True)
    saved = reg.load("입찰공고서")
    assert (saved.template_revision, saved.binding_revision) == (1, 2)
    assert saved.previous_rules["filename"] == "공고서-{{공고명}}"

    moved = _job()
    moved.filename_pattern = "공고서-{{공고명}}-2"
    moved.template_path = "/tmp/other.hwpx"
    reg.save(moved, allow_overwrite=True)
    saved = reg.load("입찰공고서")
    assert (saved.template_revision, saved.binding_revision) == (2, 2)  # 템플릿 축만 추가로
    assert saved.previous_rules["template"] == "/tmp/template.hwpx"


def test_stamping_a_run_does_not_advance_revisions(tmp_path):
    """완주 스탬프·즐겨찾기·그룹은 규칙이 아니다 — 세대를 올리지 않는다(§19.10 표)."""
    from hwpxfiller.core.job import rules_fingerprints

    reg = JobRegistry(tmp_path)
    reg.save(_job())
    reg.stamp_last_run("입찰공고서", "2026-07-27T09:00:00", rules=rules_fingerprints(_job()))
    reg.set_favorite("입찰공고서", True, when="2026-07-27T09:01:00")
    reg.set_group("입찰공고서", "조달")
    saved = reg.load("입찰공고서")
    assert (saved.template_revision, saved.binding_revision) == (1, 1)
    assert saved.last_run_at and saved.group == "조달"   # 다른 갱신은 그대로 일어났다


def test_rename_keeps_the_generation_but_clone_starts_over(tmp_path):
    """이름 변경은 세대를 잇고(같은 규칙의 같은 계보), 복제는 r1 부터 — 겪지 않은 세대 금지."""
    reg = JobRegistry(tmp_path)
    reg.save(_job())
    changed = _job()
    changed.filename_pattern = "공고서-{{공고명}}-2"
    reg.save(changed, allow_overwrite=True)              # binding r2

    reg.rename("입찰공고서", "입찰공고서 2026")
    assert reg.load("입찰공고서 2026").binding_revision == 2
    assert reg.load("입찰공고서 2026").previous_rules["filename"] == "공고서-{{공고명}}"

    copy_name = reg.clone("입찰공고서 2026")
    copied = reg.load(copy_name)
    assert (copied.template_revision, copied.binding_revision) == (1, 1)
    assert copied.previous_rules == {}                   # 이 identity 에서 일어난 변경이 없다


def test_save_over_a_corrupt_slot_starts_a_new_generation(tmp_path):
    """읽을 수 없는 과거는 잇지 않는다 — 저장 자체는 막지 않는다(판본은 저장의 전제가 아니다)."""
    reg = JobRegistry(tmp_path)
    reg.save(_job())
    reg.path_for("입찰공고서").write_text("{ 깨진 JSON", encoding="utf-8")
    reg.save(_job(), allow_overwrite=True)
    assert reg.load("입찰공고서").binding_revision == 1


def test_set_favorite_stamps_under_the_write_lock_when_time_is_not_given():
    """시각 미지정이면 레지스트리가 **잠금 안에서** 찍는다(리뷰 P2 — 교차 작업 순위 역전 차단).

    호출측이 미리 찍으면 서로 다른 작업 둘을 연속으로 별 찍을 때 스레드 스케줄링이 나중
    클릭에 이른 시각을 줄 수 있다. 잠금 안 스탬프는 쓰기 순서 = 시각 순서를 담보한다.
    """
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        reg = JobRegistry(_Path(tmp) / "jobs")
        reg.save(Job(name="갑", template_path="t.hwpx"))
        reg.save(Job(name="을", template_path="t.hwpx"))
        first = reg.set_favorite("갑", True).favorited_at
        second = reg.set_favorite("을", True).favorited_at
        assert first and second and first < second   # 쓰기 순서 = 시각 순서


def test_set_favorite_toggles_and_keeps_first_timestamp(tmp_path):
    """지정/해제는 단일 필드 갱신이고, 이미 즐겨찾기면 시각을 다시 쓰지 않는다.

    재지정에서 시각을 갱신하면 같은 별을 두 번 누른 것만으로 순위가 앞으로 튄다 —
    사용자가 만든 우선순위가 클릭 노이즈에 진다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx", mapping=_profile(),
                 filename_pattern="패턴", group="입찰"))
    reg.set_favorite("공고서", True, "2026-07-26T09:00:00")
    assert reg.load("공고서").favorited_at == "2026-07-26T09:00:00"
    reg.set_favorite("공고서", True, "2026-07-27T09:00:00")   # 재지정
    after = reg.load("공고서")
    assert after.favorited_at == "2026-07-26T09:00:00"        # 최초 지정 시각 유지
    assert after.group == "입찰" and after.filename_pattern == "패턴"  # 단일 필드 갱신
    reg.set_favorite("공고서", False, "2026-07-28T09:00:00")
    assert reg.load("공고서").favorited_at == ""


def test_clone_does_not_inherit_favorite(tmp_path):
    """복제본은 사용자가 고른 적 없다 — 즐겨찾기를 계승하면 메인 Top 5 를 조용히 점유한다."""
    reg = JobRegistry(tmp_path / "jobs")
    job = _job()
    job.favorited_at = "2026-07-26T09:00:00"
    job.last_run_at = "2026-07-25T09:00:00"
    reg.save(job)
    copy = reg.load(reg.clone(job.name))
    assert copy.favorited_at == "" and copy.last_run_at == ""


def test_group_type_corruption_is_loud():
    d = _job().to_dict()
    d["group"] = 3
    with pytest.raises(ValueError):
        Job.from_dict(d)


def test_registry_rename_moves_file_and_updates_name(tmp_path):
    reg = JobRegistry(tmp_path)
    job = _job()
    reg.save(job)
    reg.rename(job.name, "개명된 작업")
    assert not reg.exists(job.name)  # 옛 파일 제거(저장 후 — 중단 시 소실 없음)
    assert reg.load("개명된 작업").name == "개명된 작업"


def test_registry_rename_rejects_empty_and_taken_name(tmp_path):
    reg = JobRegistry(tmp_path)
    a = _job()
    reg.save(a)
    b = _job()
    b.name = "둘째 작업"
    reg.save(b)
    with pytest.raises(ValueError):
        reg.rename(a.name, "   ")  # 빈 이름 loud
    with pytest.raises(ValueError):
        reg.rename(a.name, "둘째 작업")  # 자리 선점 — 동명 작업을 조용히 덮지 않는다
    assert reg.exists(a.name) and reg.load("둘째 작업").name == "둘째 작업"  # 실패 무손상


def test_registry_rename_same_slug_updates_in_place(tmp_path):
    # '예산/2026' 과 '예산_2026' 은 같은 slug 파일 — 제자리 갱신이지 선점 충돌이 아니다.
    reg = JobRegistry(tmp_path)
    job = _job()
    job.name = "예산/2026"
    reg.save(job)
    reg.rename("예산/2026", "예산_2026")
    assert reg.names() == ["예산_2026"]
    assert reg.load("예산_2026").name == "예산_2026"


def test_registry_rename_same_name_is_noop(tmp_path):
    reg = JobRegistry(tmp_path)
    job = _job()
    reg.save(job)
    reg.rename(job.name, job.name)
    assert reg.names() == [job.name]


def test_registry_set_group_and_groups_listing(tmp_path):
    reg = JobRegistry(tmp_path)
    a = _job()
    reg.save(a)
    b = _job()
    b.name = "둘째 작업"
    reg.save(b)
    reg.set_group(a.name, " 입찰 ")  # 공백 트리밍
    assert reg.load(a.name).group == "입찰"
    assert reg.groups() == ["입찰"]  # 소속 있는 그룹만
    reg.set_group(a.name, "")  # 해제 = 「그룹 없음」
    assert reg.groups() == []


def test_registry_clone_inherits_group(tmp_path):
    reg = JobRegistry(tmp_path)
    job = _job()
    job.group = "입찰"
    reg.save(job)
    copy = reg.clone(job.name)
    assert reg.load(copy).group == "입찰"  # 복사본이 원본 옆 같은 그룹(결정 43 인접)


def test_registry_rename_group_moves_members(tmp_path):
    reg = JobRegistry(tmp_path)
    a = _job()
    reg.save(a)
    b = _job()
    b.name = "둘째 작업"
    reg.save(b)
    reg.set_group(a.name, "입찰")
    reg.set_group(b.name, "입찰")
    assert reg.rename_group("입찰", "2026 입찰") == 2
    assert reg.groups() == ["2026 입찰"]
    with pytest.raises(ValueError):
        reg.rename_group("2026 입찰", "  ")  # 빈 새 이름 loud


def test_registry_rename_group_into_existing_merges(tmp_path):
    reg = JobRegistry(tmp_path)
    a = _job()
    reg.save(a)
    b = _job()
    b.name = "둘째 작업"
    reg.save(b)
    reg.set_group(a.name, "입찰")
    reg.set_group(b.name, "수의")
    assert reg.rename_group("수의", "입찰") == 1  # 병합(확인 재진술은 화면 게이트 소관)
    assert reg.groups() == ["입찰"]


def test_registry_disband_group_returns_members_to_ungrouped(tmp_path):
    reg = JobRegistry(tmp_path)
    a = _job()
    reg.save(a)
    reg.set_group(a.name, "입찰")
    assert reg.disband_group("입찰") == 1
    assert reg.load(a.name).group == "" and reg.groups() == []
    with pytest.raises(ValueError):
        reg.disband_group("")  # ""(그룹 없음)는 그룹이 아니다 — 무그룹 전원 오이동 차단


# ---------------------------------------- 쓰기 직렬화(#129 리뷰 2R P1)
def test_write_lock_serializes_read_modify_write(tmp_path):
    """읽기-수정-쓰기는 서로를 배제한다 — 늦게 착지한 저장이 상대 변경을 되돌리지 않는다.

    pywebview 는 API 호출을 스레드별로 돌리므로 생성 스레드의 스탬프와 에디터 저장이 진짜로
    겹친다. 저장 **한 번**만 원자적인 것으로는 lost update 가 안 막힌다 — 되돌리는 쪽은 읽은
    시점이 낡은 저장이기 때문이다. 그래서 잠금은 레지스트리가 소유하고 모든 writer 가 쓴다.
    """
    import threading

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx", filename_pattern="원래"))

    held = threading.Event()      # 스탬프가 임계구역에 들어가 값을 읽었다
    release = threading.Event()   # 그 안에서 머무는 동안
    entered = threading.Event()   # 다른 writer 가 임계구역에 들어갔다

    def stamper():
        with reg.write_lock():
            job = reg.load("공고서")
            held.set()
            release.wait(3)                       # 임계구역을 쥔 채 대기
            job.last_run_at = "2026-07-21T09:00:00"
            reg.save(job, allow_overwrite=True)

    def editor():
        with reg.write_lock():                    # screen_editor._do_save 와 같은 규율
            job = reg.load("공고서")
            job.filename_pattern = "동시 편집"
            reg.save(job, allow_overwrite=True)
            entered.set()

    t1 = threading.Thread(target=stamper)
    t1.start()
    assert held.wait(3)
    t2 = threading.Thread(target=editor)
    t2.start()
    # 음성 대조 — 잠금이 실제로 막지 않으면 여기서 이미 들어가 낡은 값을 읽는다.
    assert not entered.wait(0.2), "쓰기 잠금이 다른 writer 를 막지 않습니다."
    release.set()
    t1.join(3)
    t2.join(3)
    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"   # 스탬프 생존
    assert saved.filename_pattern == "동시 편집"          # 편집도 생존(둘 다 남는다)


def test_stamp_last_run_is_a_single_field_mutation(tmp_path):
    """스탬프는 단일 필드만 만진다 — 다른 durable(매핑·패턴·태그·그룹)은 디스크 값 그대로."""
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path="t.hwpx", mapping=_profile(),
        filename_pattern="패턴", tags={"부서": "계약"}, group="입찰",
    ))
    reg.stamp_last_run("공고서", "2026-07-21T09:00:00")
    after = reg.load("공고서")
    assert after.last_run_at == "2026-07-21T09:00:00"
    assert after.filename_pattern == "패턴" and after.group == "입찰"
    assert after.tags == {"부서": "계약"}
    assert after.mapping.cover_fields() == _profile().cover_fields()


def test_soft_delete_retains_trash_30_days_and_undo_error_names_no_trash(tmp_path):
    """U2 §2.12(#345) — 「휴지통」 어휘는 사용자 문안에서 내렸지만(도달 표면 없음 · 표면은
    별건 #350) 보존 의무는 삭제가 상속한다: ①soft_delete 는 ``.trash`` 로 이동(파일 실재 =
    복원 재료) ②보존 기간 지난 항목은 다음 삭제의 ``_purge_trash`` 컷오프가 걷는다 ③복원
    실패 문안은 「휴지통」 없이 실패 사실(파일 부재)만 말한다."""
    import os
    import time

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx"))
    trash = tmp_path / "jobs" / ".trash"
    trash.mkdir(parents=True)
    stale = trash / f"0-stale-옛작업{JobRegistry.SUFFIX}"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - (JobRegistry.TRASH_RETENTION_DAYS + 1) * 24 * 60 * 60
    os.utime(stale, (old, old))

    src, dst = reg.soft_delete("공고서")
    assert dst.exists() and dst.parent == trash          # 30일 보존 실재(의무 상속)
    assert not stale.exists()                            # 컷오프 정리 생존
    dst.unlink()                                         # 보존 기간 밖 소실 시나리오
    with pytest.raises(ValueError) as exc:
        reg.restore_soft_deleted((src, dst))
    assert str(exc.value) == "되돌릴 작업 파일을 찾을 수 없습니다."


# ---- 쓰기 표면 전수 분류 가드(#129 리뷰 3R P1 — 4차 재발 차단) ----
#
# 같은 결함류가 세 라운드 연속 재발했다: ①스탬프가 남의 작업에 ②스탬프가 잠금 밖 ③delete·
# set_tags·relink 가 잠금 밖. 공통 원인은 "새 writer 가 조용히 늘어난다"이므로, 개별 결함이
# 아니라 **표면 전체를 분류하게** 만든다 — 새 공개 메서드가 생기면 아래 둘 중 하나에 이름을
# 올리기 전까지 테스트가 실패한다(미분류 = 실패).
_READERS = {
    "exists", "load", "list_jobs", "names", "groups", "path_for", "write_lock",
}
_WRITERS = {
    "save", "delete", "rename", "clone", "mutate", "stamp_last_run", "set_favorite",
    "set_group", "rename_group", "disband_group", "soft_delete", "restore_soft_deleted",
}


def _public_registry_api() -> set:
    return {n for n in dir(JobRegistry) if not n.startswith("_") and callable(getattr(JobRegistry, n))}


def test_every_registry_surface_is_classified_reader_or_writer():
    """레지스트리 공개 표면은 전부 읽기/쓰기로 분류돼 있다 — 미분류 writer 잠입 차단."""
    api = _public_registry_api()
    unclassified = api - _READERS - _WRITERS
    assert not unclassified, (
        "분류되지 않은 JobRegistry 공개 메서드입니다 — 읽기면 _READERS, 쓰기면 _WRITERS 에 "
        f"올리고 쓰기라면 잠금 참여를 확인하세요: {sorted(unclassified)}"
    )
    assert not (_READERS | _WRITERS) - api, "사라진 메서드가 분류 목록에 남아 있습니다."


def test_every_writer_holds_the_write_lock_during_file_io(tmp_path, monkeypatch):
    """분류된 모든 writer 는 **파일 I/O 순간** 쓰기 잠금을 쥐고 있다.

    판정은 다른 스레드에서 비차단 획득을 시도해 실패하는지로 한다(RLock 은 같은 스레드에선
    재획득되므로 자기 스레드 검사는 판별력이 없다 — 계측 리트머스의 부재 판별력).
    """
    import threading
    from pathlib import Path

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="A", template_path="t.hwpx", group="G"))
    reg.save(Job(name="B", template_path="t.hwpx", group="G"))

    held_outside: "list[str]" = []

    def _probe(tag: str) -> None:
        got = [False]

        def attempt():
            lock = reg.write_lock()
            got[0] = lock.acquire(blocking=False)
            if got[0]:
                lock.release()

        t = threading.Thread(target=attempt)
        t.start()
        t.join(3)
        if got[0]:
            held_outside.append(tag)

    real_write = Job.save
    real_unlink = Path.unlink
    real_replace = Path.replace

    def spy_write(self, path):
        _probe(f"save:{self.name}")
        return real_write(self, path)

    def spy_unlink(self, *a, **kw):
        if str(self).endswith(JobRegistry.SUFFIX):
            _probe(f"unlink:{self.name}")
        return real_unlink(self, *a, **kw)

    def spy_replace(self, target):
        if str(self).endswith(JobRegistry.SUFFIX) or str(target).endswith(JobRegistry.SUFFIX):
            _probe(f"replace:{self.name}")
        return real_replace(self, target)

    monkeypatch.setattr(Job, "save", spy_write)
    monkeypatch.setattr(Path, "unlink", spy_unlink)
    monkeypatch.setattr(Path, "replace", spy_replace)

    deleted_slot = [None]

    def soft_delete():
        deleted_slot[0] = reg.soft_delete("B2")

    def restore_soft_deleted():
        reg.restore_soft_deleted(deleted_slot[0])

    exercised = {
        "save": lambda: reg.save(Job(name="C", template_path="t.hwpx"), allow_overwrite=True),
        "mutate": lambda: reg.mutate("A", lambda j: setattr(j, "filename_pattern", "p")),
        "stamp_last_run": lambda: reg.stamp_last_run("A", "2026-07-21T09:00:00"),
        "set_favorite": lambda: reg.set_favorite("A", True, "2026-07-26T09:00:00"),
        "set_group": lambda: reg.set_group("A", "G2"),
        "rename_group": lambda: reg.rename_group("G", "G3"),
        "disband_group": lambda: reg.disband_group("G3"),
        "clone": lambda: reg.clone("A"),
        "rename": lambda: reg.rename("B", "B2"),
        "soft_delete": soft_delete,
        "restore_soft_deleted": restore_soft_deleted,
        "delete": lambda: reg.delete("B2"),
    }
    assert set(exercised) == _WRITERS, "writer 목록과 실행 목록이 어긋납니다(새 writer 미실행)."
    for run in exercised.values():
        run()
    assert not held_outside, (
        "파일 I/O 순간 쓰기 잠금 밖인 writer 가 있습니다(lost update·부활 회귀): "
        + ", ".join(sorted(held_outside))
    )


# ------------------------------------------------------------------ 매체 유도·가드 (3부 결정 4·13)
from hwpxfiller.core.job import (  # noqa: E402 — 매체 헬퍼 테스트 그룹(파일 하단 응집)
    MediaMismatchError,
    require_hwpx,
    require_hwpx_template,
    template_media,
)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/x/template.hwpx", "hwpx"),
        ("/x/template.HWPX", "hwpx"),      # 대소문자 무시
        ("draft.txt", "txt"),
        ("draft.TxT", "txt"),
        ("", ""),                          # 빈 경로 = 미상(조용히 hwpx 아님)
        ("/x/report.docx", ""),            # 미지 접미사 = 미상
        ("/x/no_suffix", ""),
        ("/x/archive.hwpx.bak", ""),       # 끝 접미사만 본다(중간의 .hwpx 는 매체 아님)
    ],
)
def test_template_media_derives_from_suffix_no_io(path, expected):
    """매체는 template_path 접미사에서만 유도 — I/O 없음, 미상은 조용히 hwpx 로 안 본다(결정 4)."""
    assert template_media(path) == expected


def test_job_media_is_derived_not_stored():
    """Job.media 는 파생 프로퍼티 — 저장 필드가 아니라 to_dict 에 매체 키가 없다(선언≠실제 자리 금지)."""
    assert Job(template_path="/x/t.hwpx").media == "hwpx"
    assert Job(template_path="/x/d.txt").media == "txt"
    assert Job(template_path="").media == ""
    assert "media" not in Job(template_path="/x/t.hwpx").to_dict()  # 유도지 저장 아님


def test_work_mode_derives_three_values_from_the_suffix_only():
    """§19.1 — 작업 방식은 확장자에서**만** 파생하고 v5 fallback(그 외 = hwpx)은 없다."""
    from hwpxfiller.core.job import (
        WORK_MODE_HWPX,
        WORK_MODE_TEXT,
        WORK_MODE_UNSUPPORTED,
        work_mode,
    )

    assert work_mode("/x/t.hwpx") == WORK_MODE_HWPX
    assert work_mode("/x/d.TXT") == WORK_MODE_TEXT
    for unknown in ("", "/x/r.docx", "/x/no_suffix", "/x/a.hwpx.bak"):
        assert work_mode(unknown) == WORK_MODE_UNSUPPORTED, unknown


def test_work_mode_and_media_stay_two_axes():
    """방식과 매체를 한 값으로 뭉치지 않는다(지도 §10.15 판정 A).

    미연결 작업에서 둘의 뜻이 갈린다: 매체는 ``""``(형식을 모른다), 방식은
    ``unsupported``(이 앱이 할 수 있는 일이 아니다 — 후보에서 fail-closed 제외).
    라이브러리 **필터**는 같은 행을 hwpx 칸에 놓는데(고치러 오는 자리에 남기려고),
    그 귀속을 방식 파생이 흉내 내면 세 축이 서로를 덮어쓴다.
    """
    from hwpxfiller.core.job import WORK_MODE_UNSUPPORTED
    from hwpxfiller.gui.home_state import MODE_HWPX, JobRow, library_mode_of

    unlinked = Job(name="저작중", template_path="")
    assert unlinked.media == "" and unlinked.work_mode == WORK_MODE_UNSUPPORTED
    assert library_mode_of(JobRow.from_job(unlinked)) == MODE_HWPX
    assert "work_mode" not in unlinked.to_dict()  # 파생이지 저장 아님


def test_require_hwpx_template_passes_hwpx_and_rejects_others():
    """require_hwpx_template: hwpx 는 경로 그대로 반환(체이닝), txt·미상·빈 경로는 loud."""
    assert require_hwpx_template("/x/t.hwpx") == "/x/t.hwpx"
    for bad in ("/x/d.txt", "/x/r.docx", ""):
        with pytest.raises(MediaMismatchError):
            require_hwpx_template(bad)


def test_require_hwpx_job_passes_hwpx_and_authoring_rejects_nonhwpx():
    """require_hwpx(job): hwpx·빈(저작 중 미링크)은 통과, txt·기타 비어있지 않은 비-hwpx 는 loud.

    빈 경로 예외를 보존하면서(복구 대상 = relink), 비어있지 않은 미지 매체(txt·.docx)는 막는다 —
    그대로 두면 RunViewModel 하위 메서드가 hwpx 파서로 흘려 조용한 오작동이 된다(#148 리뷰 #1·#4).
    """
    hwpx_job = Job(name="공고", template_path="/x/t.hwpx")
    assert require_hwpx(hwpx_job) is hwpx_job
    # 빈/미링크 = 저작 중 hwpx 작업 → 통과(파싱 경계는 require_hwpx_template 가 별도로 막는다).
    authoring = Job(name="새 작업", template_path="")
    assert require_hwpx(authoring) is authoring
    # txt 기안 작업 → 자기 화면(「기안」) 소관이라 loud(이름 문맥 동반).
    txt_job = Job(name="기안메모", template_path="/x/d.txt")
    with pytest.raises(MediaMismatchError) as ei:
        require_hwpx(txt_job)
    assert "기안메모" in str(ei.value)
    # 비어있지 않은 미지 접미사(.docx 등)도 거부 — 조용한 hwpx 파싱 진입 차단(리뷰 #4).
    with pytest.raises(MediaMismatchError):
        require_hwpx(Job(name="문서", template_path="/x/report.docx"))


def test_run_view_model_rejects_txt_but_allows_hwpx_and_authoring():
    """실행뷰: txt·비-hwpx 는 생성 시점 loud 거부(결정 13), hwpx·빈 템플릿(저작 중)은 관용."""
    from hwpxfiller.gui.run_state import RunViewModel

    RunViewModel(Job(name="공고", template_path="/x/t.hwpx"))  # hwpx 통과
    RunViewModel(Job(name="저작중", template_path=""))          # 빈 템플릿(저작 중) 통과
    with pytest.raises(MediaMismatchError):
        RunViewModel(Job(name="기안", template_path="/x/d.txt"))


def test_generate_batch_rejects_non_hwpx_template():
    """generate_batch(산출물=hwpx 파일)는 hwpx 아닌 템플릿 경로를 첫머리에서 loud 거부(결정 9·13)."""
    from hwpxfiller.batch import generate_batch

    with pytest.raises(MediaMismatchError):
        generate_batch("/x/d.txt", [{"a": "1"}], "/tmp/out", "n-{{seq}}")


@pytest.mark.parametrize("bad", [None, [], "", 0, 3])
def test_falsy_previous_rules_corruption_is_loud(bad):
    """훼손 값이 「직전 판본 없음」이라는 **정상 상태로 위장**하지 못하게 한다(3R P2).

    형상 검사보다 falsy 검사가 앞서면 ``null``·``[]``·``""``·``0`` 이 조용히 통과해 그
    작업만 이력 증거를 잃는다 — 다른 durable 필드는 전부 loud 인데 여기만 조용해진다.
    빈 사전만이 「없음」이다.
    """
    d = _job().to_dict()
    d["previous_rules"] = bad
    with pytest.raises(ValueError):
        Job.from_dict(d)
    d["previous_rules"] = {}                       # 빈 사전 = 정상(직전 판본 없음)
    assert Job.from_dict(d).previous_rules == {}


def test_previous_revision_snapshot_advances_per_axis(tmp_path):
    """직전 판본은 **축별로** 밀린다(7R P2).

    두 축이 한 스냅샷에 살지만 각자의 세대를 가진다 — 연결을 A→B 로 바꿔 두고 템플릿만
    저장했다고 연결의 직전 값까지 현재로 밀면, 아직 검토받지 않은 그 변경의 증거가
    「B → B」가 된다(아무것도 안 바뀐 것처럼 보인다).
    """
    reg = JobRegistry(tmp_path)
    reg.save(_job())                                     # 연결 A
    changed = _job()
    changed.mapping.mappings[0].source = "B열"            # 연결 A → B
    reg.save(changed, allow_overwrite=True)
    saved = reg.load("입찰공고서")
    assert saved.binding_revision == 2
    assert saved.previous_rules["fields"]["공고명"]["source"] == "bidNtceNm"   # 직전 = A

    moved = _job()
    moved.mapping.mappings[0].source = "B열"              # 연결은 그대로 B
    moved.template_path = "/tmp/other.hwpx"              # 템플릿만 저장
    reg.save(moved, allow_overwrite=True)
    saved = reg.load("입찰공고서")
    assert (saved.template_revision, saved.binding_revision) == (2, 2)
    # 템플릿 축은 밀리고,
    assert saved.previous_rules["template"] == "/tmp/template.hwpx"
    # **연결 축의 직전 값은 A 그대로**다 — 아직 그 변경은 검토받지 않았다.
    assert saved.previous_rules["fields"]["공고명"]["source"] == "bidNtceNm"
