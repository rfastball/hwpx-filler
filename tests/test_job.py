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
