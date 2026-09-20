"""작업(Job) 데이터모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀: (1) 작업 저장→로드가 임베드된 매핑을 값·**행위**까지 온전 보존한다,
(2) 레지스트리가 작업당 JSON 1개로 목록/로드/삭제하며 이름 slug 이 파일명만 정리하고
원 이름은 JSON 안에 온전하다, (3) RunRequest 사전검증이 빠진 소스키(missing_columns)와
빈 출력값(empty_valued)을 Qt·Excel 없이 잡아낸다.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from hwpxfiller.domain.job import (
    Job,
    RunRequest,
    data_binding_matches,
    data_binding_of,
    has_data_binding,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
from hwpxfiller.external.template_inspection import template_compile_status
from hwpxfiller.external import settings
from hwpxfiller.external.job_store import (
    JobRegistry,
    JobSlugCollisionError,
    SlugCollisionError,
    _reject_unsafe_key,
    content_fingerprint,
    decode_job,
    encode_job,
    library_key_for,
    load_job,
    save_job,
)
from hwpxfiller.host.locations import default_jobs_dir


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
    from hwpxfiller.domain.job import DEFAULT_FILENAME_PATTERN
    from hwpxfiller.naming import pattern_field_tokens

    assert DEFAULT_FILENAME_PATTERN == "공고서-{{date}}-{{seq:001}}"
    assert pattern_field_tokens(DEFAULT_FILENAME_PATTERN) == []  # 데이터 토큰 0 = 항상 해소
    assert Job().filename_pattern == DEFAULT_FILENAME_PATTERN
    assert decode_job({}).filename_pattern == DEFAULT_FILENAME_PATTERN


def test_to_dict_from_dict_roundtrip_preserves_embedded_mapping():
    """작업 dict 왕복이 임베드된 매핑의 소스·표시형까지 보존한다."""
    loaded = decode_job(encode_job(_job()))
    assert loaded.name == "입찰공고서"
    assert loaded.template_path == "/tmp/template.hwpx"
    assert loaded.filename_pattern == "공고서-{{공고명}}"
    assert loaded.mapping.mappings[1].source == "presmptPrce"
    assert loaded.mapping.mappings[1].type == "amount"
    assert loaded.mapping.mappings[1].fmt == "{:,}"


def test_save_load_roundtrip_preserves_mapping_behavior(tmp_path):
    """저장→로드된 작업의 매핑이 같은 값을 낸다(표시형 서식 포함) — 행위 재검증."""
    path = tmp_path / "job.json"
    save_job(path, _job())
    loaded = load_job(path)
    assert loaded.mapping.apply({"bidNtceNm": "테스트", "presmptPrce": "21326800"}) == {
        "공고명": "테스트",
        "추정가격": "21,326,800",
    }


def test_last_run_at_roundtrip_and_backward_compat():
    """가산 필드 last_run_at — 왕복 보존 + 구 JSON(키 부재)은 기본값 ""(version 1 유지)."""
    job = _job()
    job.last_run_at = "2026-07-10T12:34:56"
    loaded = decode_job(encode_job(job))
    assert loaded.last_run_at == "2026-07-10T12:34:56"
    assert loaded.version == 1

    old_dict = encode_job(_job())
    del old_dict["last_run_at"]  # 구 버전이 저장한 JSON
    assert decode_job(old_dict).last_run_at == ""


def test_tags_roundtrip_and_backward_compat():
    """가산 필드 tags(브라우징 분류, JOB_BROWSER_DESIGN D13) — 왕복 보존 +
    구 JSON(키 부재)은 기본값 {}(version 1 유지). 축·값은 이름 문자열 그대로."""
    job = _job()
    job.tags = {"금액구간": "1억미만", "목적물": "물품"}
    loaded = decode_job(encode_job(job))
    assert loaded.tags == {"금액구간": "1억미만", "목적물": "물품"}
    assert loaded.version == 1

    old_dict = encode_job(_job())
    del old_dict["tags"]  # tags 필드 도입 전 저장된 JSON
    from_old = decode_job(old_dict)
    assert from_old.tags == {}
    assert from_old.version == 1

    # 미태깅이 기본(선택적 — D12): 빈 작업도 빈 dict.
    assert Job().tags == {}
    # from_dict 는 방어적 복사 — 원 dict 변형이 로드된 작업에 새지 않는다(opts 선례).
    src = {"tags": {"목적물": "용역"}}
    loaded2 = decode_job(src)
    src["tags"]["목적물"] = "공사"
    assert loaded2.tags == {"목적물": "용역"}


def test_legacy_name_axis_dataset_ref_stays_dead():
    """구 ``default_dataset_ref``(#53-A)의 **이름 축**은 U4-C 뒤에도 폐기된 채다.

    U4 §2.4 가 되들인 것은 결속이지 그 키가 아니다 — U2 §5.3 판정 C 가 데이터 정체성을
    경로+시트로 옮겼고(풀 항목 이름은 중복 허용·개명 자유라 정체가 못 된다), 결속이
    무너졌던 실제 지점이 거기다. 구 JSON 의 그 키는 계속 미지 키로 무시된다.
    """
    assert not hasattr(Job(), "default_dataset_ref")
    assert "default_dataset_ref" not in encode_job(_job())

    old_dict = {**encode_job(_job()), "default_dataset_ref": "월별_낙찰현황"}
    from_old = decode_job(old_dict)          # 구버전이 남긴 이름 축 — 조용히 무시
    assert from_old.version == 1
    assert "default_dataset_ref" not in encode_job(from_old)
    # 읽지 않는 키는 타입이 깨져 있어도 검증 대상이 아니다.
    assert decode_job({**encode_job(_job()), "default_dataset_ref": 7}).name == _job().name


def test_data_binding_round_trips_as_three_components():
    """데이터 결속은 경로·시트·헤더 행 **한 벌**로 저장·복원된다(U4 §2.4 · #932 U4-C).

    경로 하나로 줄이면 마법사·마운트가 다른 헤더에 앵커를 건다(#349 리뷰 2R). 그래서
    세 값이 함께 다니는지를 왕복으로 못박는다.
    """
    bound = Job(
        name="입찰공고서",
        template_path="/tmp/template.hwpx",
        mapping=_profile(),
        data_path="/data/2026-08.xlsx",
        data_sheet="낙찰",
        data_header_row=3,
    )
    d = encode_job(bound)
    assert (d["data_path"], d["data_sheet"], d["data_header_row"]) == (
        "/data/2026-08.xlsx", "낙찰", 3,
    )
    back = decode_job(d)
    assert (back.data_path, back.data_sheet, back.data_header_row) == (
        "/data/2026-08.xlsx", "낙찰", 3,
    )


def test_data_kind_round_trips_and_old_json_lands_on_excel():
    """종류 축도 결속 한 벌의 성분이다 — 왕복하고, 부재는 ``""``(=엑셀/CSV)다.

    부재를 기본값으로 착지시키는 것은 추측이 아니라 **구판의 뜻 그대로**다: 종류 축이
    생기기 전의 저장본은 전부 엑셀/CSV 결속이었다. 반대로 **존재하는데 타입이 깨진** 값은
    조용히 통과시키지 않는다(``_str`` loud 규칙) — 종류를 잘못 읽으면 어느 어댑터로 읽을지가
    통째로 갈린다.
    """
    bound = Job(name="계약목록", data_path="/db/pclm.sqlite", data_sheet="계약",
                data_kind="pclm")
    d = encode_job(bound)
    assert d["data_kind"] == "pclm"
    assert decode_job(d).data_kind == "pclm"

    legacy = encode_job(_job())
    legacy.pop("data_kind")
    assert decode_job(legacy).data_kind == ""

    with pytest.raises(ValueError):
        decode_job({**encode_job(_job()), "data_kind": 7})


def test_data_binding_of_carries_the_kind_in_the_tail():
    """결속 한 벌은 ``(path, sheet, header_row, kind)`` 네 값이다 — 종류가 꼬리에 선다."""
    assert data_binding_of(Job(name="빈")) == ("", "", 0, "")
    bound = Job(name="a", data_path="/db/pclm.sqlite", data_sheet="계약",
                data_kind="pclm")
    assert data_binding_of(bound) == ("/db/pclm.sqlite", "계약", 0, "pclm")


def test_data_binding_matches_splits_on_kind_before_identity():
    """종류가 다르면 같은 경로·시트라도 다른 데이터다(#932 U4-C 위의 종류 축).

    종류를 안 보면 계약 목록 db 를 가리키는 결속이 같은 경로의 엑셀 마운트에 조용히 맞고,
    그 순간 후보 줄이 남의 데이터로 서 있는 작업을 추천한다.
    """
    pclm = Job(name="a", data_path="/db/pclm.sqlite", data_sheet="계약", data_kind="pclm")
    assert data_binding_matches(pclm, "/db/pclm.sqlite", "계약", 0, kind="pclm")
    assert not data_binding_matches(pclm, "/db/pclm.sqlite", "계약", 0)  # kind="" 기본
    excel = Job(name="b", data_path="/db/pclm.sqlite", data_sheet="계약")
    assert data_binding_matches(excel, "/db/pclm.sqlite", "계약", 0)
    assert not data_binding_matches(excel, "/db/pclm.sqlite", "계약", 0, kind="pclm")


def test_old_job_json_lands_in_needs_connection_state_without_guessing():
    """구판 JSON 에는 결속이 없다 — 기본값으로 착지하되 **추측해 채우지 않는다**.

    빈 결속은 손상이 아니라 구판의 유효 상태라 loud raise 가 아니다. 대신 「데이터 연결
    필요」로 시끄럽게 서고(표면 계약), 되살리는 것은 사용자가 편집기에서 한다.
    """
    d = encode_job(_job())
    for key in ("data_path", "data_sheet", "data_header_row"):
        d.pop(key)
    old = decode_job(d)
    assert (old.data_path, old.data_sheet, old.data_header_row) == ("", "", 0)
    assert not has_data_binding(old)


def test_data_binding_type_corruption_is_loud():
    """결속 성분의 타입 훼손은 조용히 통과하지 않는다 — durable 값 loud 격리 관례 그대로.

    헤더 행의 ``bool`` 거절은 ``_revision`` 과 같은 근거다: 파이썬에서 ``True`` 는 ``int``
    라 무검사면 1행 헤더로 조용히 읽힌다.
    """
    for key, bad in (
        ("data_path", 7),
        ("data_sheet", ["낙찰"]),
        ("data_header_row", "3"),
        ("data_header_row", True),
        ("data_header_row", -1),
    ):
        with pytest.raises(ValueError):
            decode_job({**encode_job(_job()), key: bad})


def test_data_binding_is_in_the_content_fingerprint():
    """결속은 편집기가 **덮어쓰는** 값이라 내용 지문에 든다(U4 §2.4).

    제외 목록(태그·이력·즐겨찾기·그룹·권위·검토 기준선·판본)은 저장이 되싣거나 계산하는
    메타다. 결속을 거기 섞으면 열어 둔 편집 세션이 다른 자리에서 갈린 결속을 무확인으로
    덮어쓴다.
    """
    base = _job()
    moved = decode_job({**encode_job(base), "data_path": "/data/other.xlsx"})
    assert content_fingerprint(base) != content_fingerprint(moved)


def test_data_binding_is_not_a_rule_axis():
    """결속은 실행 **입력**이지 규칙이 아니다 — ``rules_values`` 에 들지 않는다(U4 §2.4).

    들면 데이터를 바꿀 때마다 ``binding_revision`` 이 올라 겪지 않은 세대와 검토 요구가
    선다(§13-6: 판본 변경 = validation·approval 폐기).
    """
    from hwpxfiller.domain.job import advance_revisions, rules_values

    base = _job()
    assert set(rules_values(base)) == {"template", "filename", "fields"}
    moved = decode_job({**encode_job(base), "data_path": "/data/other.xlsx"})
    advance_revisions(moved, base)
    assert (moved.template_revision, moved.binding_revision) == (1, 1)


def test_data_binding_matches_is_the_single_inverse_index_predicate():
    """후보 역인덱스의 술어 하나 — 정체성은 U2 판정 C(경로 정규화 + 시트) 재사용."""
    bound = Job(name="a", data_path="/data/A.xlsx", data_sheet="s1", data_header_row=2)
    assert data_binding_matches(bound, os.path.abspath("/data/A.xlsx"), "s1", 2)
    assert not data_binding_matches(bound, "/data/A.xlsx", "s2", 2)   # 다른 시트 = 다른 데이터
    assert not data_binding_matches(bound, "/data/A.xlsx", "s1", 1)   # 다른 헤더 행 = 다른 한 벌
    assert not data_binding_matches(bound, "/data/B.xlsx", "s1", 2)
    # 미결속 작업은 어떤 마운트에도 맞지 않는다 — 빈 결속은 「아무거나」가 아니다.
    assert not data_binding_matches(Job(name="b"), "/data/A.xlsx", "s1", 2)


def test_from_dict_rejects_type_corrupt_durable_values():
    """durable 로드 경계 — 문자열 계약 필드가 비문자열이면 loud 하게 던진다(내구성 라운드 #1·3·4).

    앱은 늘 str 값만 쓰므로 int/list/null 은 외부 훼손 신호다. 조용히 통과하면 나중에 홈
    렌더(혼합타입 sorted·_fmt_iso TypeError)에서 무관한 작업까지 죽이거나 계보 비교를 무성
    무효화한다 — 경계에서 격리해 RC-05 손상 행으로 표면화(confirm-or-alarm)."""
    base = encode_job(_job())
    corrupt_variants = [
        {**base, "tags": {"금액구간": 123}},   # 비문자열 tags 값 → group-by/facet 혼합 sorted 지뢰
        {**base, "tags": None},                # dict(None) 크래시 대신 loud
        {**base, "tags": ["금액구간"]},         # tags 가 리스트
        {**base, "last_run_at": 1720000000},   # 비문자열 시각 → refresh 의 _fmt_iso 지뢰
        {**base, "name": 5},                   # 비문자열 이름
        {**base, "group": 5},                  # 비문자열 그룹 → 좌 목록 구획 지뢰
    ]
    for d in corrupt_variants:
        with pytest.raises(ValueError):
            decode_job(d)


def test_from_dict_backward_compat_survives_boundary():
    """경계 강화가 가산 하위호환을 깨지 않는다 — 신 필드 없는 구 JSON 은 여전히 기본값 로드.

    역방향도 대칭: 제거된 필드(base_mapping_name, F22)가 남은 구 JSON 은 미지 키로
    무시된다(타입이 깨져 있어도 — 읽지 않는 키는 검증 대상이 아니다).
    """
    old = {"name": "구작업", "template_path": "/t.hwpx"}  # tags·last_run·version 전무
    job = decode_job(old)
    assert job.name == "구작업" and job.tags == {} and job.last_run_at == ""
    assert job.version == 1
    assert decode_job({"name": "잔재", "base_mapping_name": "베이스"}).name == "잔재"
    assert decode_job({}).name == ""  # 완전 빈 dict 도 기본값 작업


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


def test_source_keys_ignores_fields_that_declare_an_empty_constant():
    """빈 고정값은 데이터 열을 요구하지 않는다 — 소스 키에 유령이 서지 않는다."""
    job = Job(mapping=MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("비고", type="const"),
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
    assert report.missing_columns == ["presmptPrce"]
    assert report.empty_valued == []


def test_run_request_output_report_flags_empty_value():
    """매핑된 출력에 빈 값이 있으면 template_field 이름으로 empty_valued."""
    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])  # 공고명 빈값
    report = RunRequest(_job(), src, [0]).output_report()
    assert report.missing_columns == []
    assert report.empty_valued == ["공고명"]


def test_mapped_records_mark_missing_only_empty_values():
    """표식 주입 — 값이 빈 키만 치환, 비빈 값 불변, 의도적 공란(키 부재)은 그대로."""
    from hwpxfiller.domain.job import MISSING_MARKER

    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])
    req = RunRequest(_job(), src, [0])

    marked = req.mapped_records(mark_missing=MISSING_MARKER)
    assert marked[0]["공고명"] == "〘미입력·공고명〙"       # 미충족 공란 → 표식
    assert marked[0]["추정가격"] == "1,000"                 # 비빈 값 불변(표시형 유지)
    # 의도적 공란 = 프로파일이 키를 제외 → 표식 대상 자체가 아님.
    assert set(marked[0]) == set(_job().template_fields())


def test_mapped_records_default_unchanged_and_marker_silences_empty_report():
    """기본 인자 = 기존 동작 회귀 + 표식 주입 후 empty_valued 무경보(주입 확인의 거울)."""
    from hwpxfiller.domain.job import MISSING_MARKER
    from hwpxfiller.domain.validation import validate

    src = _FakeSource([{"bidNtceNm": "", "presmptPrce": "1000"}])
    req = RunRequest(_job(), src, [0])

    plain = req.mapped_records()
    assert plain[0]["공고명"] == ""  # 기본값이면 그대로(하위호환)

    marked = req.mapped_records(mark_missing=MISSING_MARKER)
    report = validate(_job().template_fields(), marked)
    assert not report.empty_valued  # 표식은 비어 있지 않은 값 — 엔진 빈값 스킵 통과


def test_declared_empty_skips_the_marker_and_writes_empty_into_a_real_hwpx(tmp_path):
    """빈 고정값은 표식 대상이 아니고, 산출물에는 **빈 문자열**로 들어간다(U6 §2.10)."""
    from pathlib import Path

    from hwpxfiller.external.hwpx_engine import make_hwpx_engine
    from hwpxfiller.domain.fields import read_fields
    from hwpxfiller.domain.job import MISSING_MARKER

    template = Path(__file__).parent / "corpus" / "real" / "bid_notice_limited_under100m.hwpx"
    mapping = MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("입찰공고번호", type="const"),
        FieldMapping("계약방법", type="const"),
        FieldMapping("추정가격", type="const"),
        FieldMapping("개찰일시", type="const"),
    ])
    req = RunRequest(
        Job(template_path=str(template), mapping=mapping),
        _FakeSource([{"name": ""}]),
        [0],
    )
    marked = req.mapped_records(mark_missing=MISSING_MARKER)[0]
    # 빈 고정값 선언은 표식이 아니라 빈 문자열이다 — 사람이 이미 답한 자리라 미입력이 아니다.
    assert marked == {
        "공고명": "〘미입력·공고명〙", "입찰공고번호": "", "계약방법": "",
        "추정가격": "", "개찰일시": "",
    }

    before = read_fields(read_hwpx_package(template))
    out = tmp_path / "marked.hwpx"
    result = make_hwpx_engine().generate(str(template), marked, str(out))
    assert result.ok
    after = read_fields(read_hwpx_package(out))
    assert after["공고명"] == "〘미입력·공고명〙"
    for declared in ["입찰공고번호", "계약방법", "추정가격", "개찰일시"]:
        assert before[declared] != ""          # 전제: 템플릿에 안내 문구가 있었다
        assert after[declared] == ""           # 선언한 비움은 실제로 비워진다


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
    save_job(path, job)
    existing = path.read_text(encoding="utf-8")

    def _boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("hwpxfiller.external.atomic.os.replace", _boom)
    with pytest.raises(OSError):
        save_job(path, job)
    assert path.read_text(encoding="utf-8") == existing  # 무손상
    assert load_job(path).name == "계약"                  # 여전히 로드 가능


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
    d = encode_job(job)
    assert d["group"] == "2026 상반기"
    assert decode_job(d).group == "2026 상반기"
    d.pop("group")  # 구 JSON(가산 스키마) — migrate-on-read 관용으로 기본값
    assert decode_job(d).group == ""


# ---------------------------------------------- 즐겨찾기(v6 §18.5, data-first 슬라이스 2)
def test_favorited_at_roundtrip_and_backward_compat():
    """즐겨찾기는 가산 필드 — 구 JSON 은 기본값 ""(미즐겨찾기)로 관용 로드된다."""
    job = _job()
    job.favorited_at = "2026-07-26T09:00:00"
    d = encode_job(job)
    assert d["favorited_at"] == "2026-07-26T09:00:00"
    assert decode_job(d).favorited_at == "2026-07-26T09:00:00"
    assert decode_job(d).version == 1  # 가산 필드는 version 을 올리지 않는다
    d.pop("favorited_at")
    assert decode_job(d).favorited_at == ""


def test_favorited_at_type_corruption_is_loud():
    d = encode_job(_job())
    d["favorited_at"] = True
    with pytest.raises(ValueError):
        decode_job(d)


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
    d = encode_job(job)
    assert (d["template_revision"], d["binding_revision"]) == (3, 7)
    assert decode_job(d).binding_revision == 7
    assert decode_job(d).version == 1  # 가산 필드는 version 을 올리지 않는다
    d.pop("template_revision"), d.pop("binding_revision"), d.pop("previous_rules")
    restored = decode_job(d)
    assert (restored.template_revision, restored.binding_revision) == (1, 1)
    assert restored.previous_rules == {}


@pytest.mark.parametrize("bad", [0, -1, "2", 1.0, True, None])
def test_revision_corruption_is_loud(bad):
    """판본은 1 이상의 정수 — ``True`` 도 거른다(파이썬에서 bool 은 int 라 조용히 r1 이 된다)."""
    d = encode_job(_job())
    d["binding_revision"] = bad
    with pytest.raises(ValueError):
        decode_job(d)


def test_previous_rules_shape_corruption_is_loud():
    """직전 판본은 축이 온전한 값 사전이어야 한다 — 증거를 짓는 자리의 조용한 결손 금지."""
    from hwpxfiller.domain.job import rules_values

    d = encode_job(_job())
    d["previous_rules"] = rules_values(_job())
    decode_job(d)                                    # 온전한 형상은 통과
    d["previous_rules"] = {"template": "t", "filename": "f", "fields": {"공고명": {"source": "x"}}}
    with pytest.raises(ValueError):                     # 축 누락
        decode_job(d)
    d["previous_rules"] = {"fields": []}
    with pytest.raises(ValueError):                     # fields 가 사전이 아님
        decode_job(d)


def test_revisions_are_outside_the_content_fingerprint():
    """판본 3필드는 지문 밖 — 저장이 계산해 다시 쓰는 파생 메타라 보존 메타와 같은 부류다.

    남기면 다른 표면의 저장·스탬프가 열어 둔 편집 세션에 거짓 파괴 확인을 띄운다.
    """
    from hwpxfiller.domain.job import rules_values

    job = _job()
    before = content_fingerprint(job)
    job.template_revision, job.binding_revision = 5, 9
    job.previous_rules = rules_values(_job())
    assert content_fingerprint(job) == before


def test_rules_fingerprints_are_assembled_from_rules_values(tmp_path):
    """지문과 직전 판본 값은 **같은 원재료**를 쓴다 — 한쪽만 고쳐지면 "무엇이 바뀌었나"와
    "무엇이었나"가 서로 다른 규칙을 말한다(§10.13 판정 H).
    """
    from hwpxfiller.domain.job import rules_fingerprints, rules_values

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
    from hwpxfiller.domain.job import rules_fingerprints

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
    d = encode_job(_job())
    d["group"] = 3
    with pytest.raises(ValueError):
        decode_job(d)


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


def test_corrupt_reviewed_rules_is_loud():
    """검토 기준선도 다른 durable 필드와 같은 규율 — 사전 아님·비문자열 항목은 loud 격리.

    조용히 통과하면 검토 요구 판정(rules_key 대조)이 훼손 값 위에서 조용히 틀린다 —
    승인 축이라 조용한 오판이 가장 비싼 자리다.
    """
    base = encode_job(_job())
    with pytest.raises(ValueError):
        decode_job({**base, "reviewed_rules": ["template"]})       # 사전이 아님
    with pytest.raises(ValueError):
        decode_job({**base, "reviewed_rules": {"template": 7}})    # 비문자열 지문
    with pytest.raises(ValueError):
        decode_job({**base, "reviewed_rules": {3: "fp"}})          # 비문자열 대상


def test_unknown_media_template_key_falls_back_to_the_stored_path():
    """탈출 방어는 통과하지만 매체 미상인 키(``x.docx``)는 해석하지 않는다 — 경로 폴백.

    루트를 확장자로 고르므로 미상 매체 키는 해석할 루트가 없다. 추측 해석 대신 저장된
    절대경로를 그대로 쓴다(모르는 것을 추측하지 않는다 — fail-closed).
    """
    d = {"name": "a", "template_path": "/legacy/절대경로.docx", "template_key": "조달/공고서.docx"}
    assert decode_job(d).template_path == "/legacy/절대경로.docx"


def test_registry_delete_missing_name_is_a_quiet_noop(tmp_path):
    """이미 없는 작업의 삭제는 조용한 no-op — 삭제의 목적 상태(부재)가 이미 성립해 있다."""
    reg = JobRegistry(tmp_path)
    reg.delete("없는작업")                                  # raise 없음
    assert not reg.exists("없는작업")


def test_soft_delete_missing_job_is_loud(tmp_path):
    """없는 작업의 소프트 삭제는 loud — "지웠다"고 말할 대상이 없으면 성공을 위조하지 않는다."""
    reg = JobRegistry(tmp_path / "jobs")
    with pytest.raises(ValueError, match="작업을 찾을 수 없습니다"):
        reg.soft_delete("없는작업")


def test_restore_refuses_when_the_name_was_recreated(tmp_path):
    """복원 자리에 같은 이름의 작업이 새로 생겼으면 loud 거절 — 새 작업을 조용히 덮지 않는다."""
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx"))
    slot = reg.soft_delete("공고서")
    reg.save(Job(name="공고서", template_path="new.hwpx"))   # 같은 이름 재작성
    with pytest.raises(ValueError, match="같은 이름의 작업이 이미 있어"):
        reg.restore_soft_deleted(slot)
    assert reg.load("공고서").template_path == "new.hwpx"    # 새 작업 무손상


def test_purge_failure_of_one_stale_file_does_not_block_the_deletion(tmp_path):
    """오래된 휴지통 항목 하나의 정리 실패(잠긴 파일)가 지금 삭제를 막지 않는다."""
    import os as _os
    import time as _time

    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx"))
    trash = tmp_path / "jobs" / ".trash"
    trash.mkdir(parents=True)
    stale = trash / f"0-locked-옛작업{JobRegistry.SUFFIX}"
    stale.write_text("{}", encoding="utf-8")
    old = _time.time() - (JobRegistry.TRASH_RETENTION_DAYS + 1) * 24 * 60 * 60
    _os.utime(stale, (old, old))

    with open(stale, encoding="utf-8"):                      # Windows: 열린 파일은 unlink 불가
        src, dst = reg.soft_delete("공고서")                 # 정리 실패에도 삭제는 완주
    assert dst.exists() and stale.exists()                   # 잠긴 항목은 다음 기회로 미뤄진다


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


def test_release_authority_id_clears_only_the_value_it_was_given(tmp_path):
    """권위 되돌림은 **대조 후 삭제**다 — 남의 결속을 끊지 않는다(#804).

    되돌림은 초기 등록에 실패해 「이력 없는 권위」만 남은 경우를 위한 것이라, 그사이 다른
    결속이 이겼으면 그 값은 이미 다른 이력을 가리킨다. 값이 다르면 **무변경**이어야 이
    되돌림이 안전한 동사다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path="t.hwpx"))
    reg.assign_authority_id("공고서", "w-mine")

    assert reg.release_authority_id("공고서", "w-남의것").authority_id == "w-mine"
    assert reg.release_authority_id("공고서", "w-mine").authority_id == ""
    assert reg.load("공고서").authority_id == ""  # durable 까지 반영된다


# ---- 쓰기 표면 전수 분류 가드(#129 리뷰 3R P1 — 4차 재발 차단) ----
#
# 같은 결함류가 세 라운드 연속 재발했다: ①스탬프가 남의 작업에 ②스탬프가 잠금 밖 ③delete·
# set_tags·relink 가 잠금 밖. 공통 원인은 "새 writer 가 조용히 늘어난다"이므로, 개별 결함이
# 아니라 **표면 전체를 분류하게** 만든다 — 새 공개 메서드가 생기면 아래 둘 중 하나에 이름을
# 올리기 전까지 테스트가 실패한다(미분류 = 실패).
_READERS = {
    "exists", "load", "list_jobs", "list_jobs_with_corruption", "names", "groups",
    "path_for", "write_lock", "content_fingerprint",
}
_WRITERS = {
    "save", "delete", "rename", "clone", "mutate", "stamp_last_run", "set_favorite",
    "set_group", "rename_group", "disband_group", "soft_delete", "restore_soft_deleted",
    "remove_corrupt_entry", "set_tags", "relink_template", "assign_authority_id",
    "release_authority_id",
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

    import hwpxfiller.external.job_store as job_store

    real_write = job_store.save_job
    real_unlink = Path.unlink
    real_replace = Path.replace

    def spy_write(path, job, **kwargs):
        _probe(f"save:{job.name}")
        return real_write(path, job, **kwargs)

    def spy_unlink(self, *a, **kw):
        if str(self).endswith(JobRegistry.SUFFIX):
            _probe(f"unlink:{self.name}")
        return real_unlink(self, *a, **kw)

    def spy_replace(self, target):
        if str(self).endswith(JobRegistry.SUFFIX) or str(target).endswith(JobRegistry.SUFFIX):
            _probe(f"replace:{self.name}")
        return real_replace(self, target)

    monkeypatch.setattr(job_store, "save_job", spy_write)
    monkeypatch.setattr(Path, "unlink", spy_unlink)
    monkeypatch.setattr(Path, "replace", spy_replace)

    deleted_slot = [None]

    def soft_delete():
        deleted_slot[0] = reg.soft_delete("B2")

    def restore_soft_deleted():
        reg.restore_soft_deleted(deleted_slot[0])

    def remove_corrupt_entry():
        bad = tmp_path / "jobs" / f"깨진{JobRegistry.SUFFIX}"
        bad.write_text("{ 이건 json 아님", encoding="utf-8")
        reg.remove_corrupt_entry(str(bad))

    exercised = {
        "save": lambda: reg.save(Job(name="C", template_path="t.hwpx"), allow_overwrite=True),
        "mutate": lambda: reg.mutate("A", lambda j: setattr(j, "filename_pattern", "p")),
        "assign_authority_id": lambda: reg.assign_authority_id("A", "w-test"),
        "release_authority_id": lambda: reg.release_authority_id("A", "w-test"),
        "set_tags": lambda: reg.set_tags("A", {"지역": "본청"}),
        "relink_template": lambda: reg.relink_template("A", "t2.hwpx"),  # 같은 매체 = 통과
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
        "remove_corrupt_entry": remove_corrupt_entry,
    }
    assert set(exercised) == _WRITERS, "writer 목록과 실행 목록이 어긋납니다(새 writer 미실행)."
    for run in exercised.values():
        run()
    assert not held_outside, (
        "파일 I/O 순간 쓰기 잠금 밖인 writer 가 있습니다(lost update·부활 회귀): "
        + ", ".join(sorted(held_outside))
    )


# ------------------------------------------------------------------ 매체 유도·가드 (3부 결정 4·13)
from hwpxfiller.domain.job import (  # noqa: E402 — 매체 헬퍼 테스트 그룹(파일 하단 응집)
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
    assert "media" not in encode_job(Job(template_path="/x/t.hwpx"))  # 유도지 저장 아님


def test_work_mode_derives_three_values_from_the_suffix_only():
    """§19.1 — 작업 방식은 확장자에서**만** 파생하고 v5 fallback(그 외 = hwpx)은 없다."""
    from hwpxfiller.domain.job import (
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
    from hwpxfiller.domain.job import WORK_MODE_UNSUPPORTED
    from hwpxfiller.gui.home_state import MODE_HWPX, JobRow, library_mode_of

    unlinked = Job(name="저작중", template_path="")
    assert unlinked.media == "" and unlinked.work_mode == WORK_MODE_UNSUPPORTED
    assert library_mode_of(JobRow.from_job(
        unlinked, engine=make_hwpx_engine(), inspect_status=template_compile_status,
    )) == MODE_HWPX
    assert "work_mode" not in encode_job(unlinked)  # 파생이지 저장 아님


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

    RunViewModel(Job(name="공고", template_path="/x/t.hwpx"), engine=make_hwpx_engine())  # hwpx 통과
    RunViewModel(Job(name="저작중", template_path=""), engine=make_hwpx_engine())          # 빈 템플릿(저작 중) 통과
    with pytest.raises(MediaMismatchError):
        RunViewModel(Job(name="기안", template_path="/x/d.txt"), engine=make_hwpx_engine())


def test_generate_batch_rejects_non_hwpx_template():
    """generate_batch(산출물=hwpx 파일, engine=make_hwpx_engine())는 hwpx 아닌 템플릿 경로를 첫머리에서 loud 거부(결정 9·13)."""
    from hwpxfiller.batch import generate_batch
    from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths

    with pytest.raises(MediaMismatchError):
        generate_batch(
            "/x/d.txt", [{"a": "1"}], "/tmp/out", "n-{{seq}}",
            engine=make_hwpx_engine(), existing_outputs=existing_output_paths,
            ensure_output_dir=ensure_output_directory,
        )


@pytest.mark.parametrize("bad", [None, [], "", 0, 3])
def test_falsy_previous_rules_corruption_is_loud(bad):
    """훼손 값이 「직전 판본 없음」이라는 **정상 상태로 위장**하지 못하게 한다(3R P2).

    형상 검사보다 falsy 검사가 앞서면 ``null``·``[]``·``""``·``0`` 이 조용히 통과해 그
    작업만 이력 증거를 잃는다 — 다른 durable 필드는 전부 loud 인데 여기만 조용해진다.
    빈 사전만이 「없음」이다.
    """
    d = encode_job(_job())
    d["previous_rules"] = bad
    with pytest.raises(ValueError):
        decode_job(d)
    d["previous_rules"] = {}                       # 빈 사전 = 정상(직전 판본 없음)
    assert decode_job(d).previous_rules == {}


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


# ------------------------------------------------- 라이브러리 상대키(#348, U2 §5.3 판정 B)
@pytest.fixture()
def library_home(tmp_path, monkeypatch):
    """``HWPXFILLER_HOME`` 을 못박고 서식 폴더를 실제로 만든 홈 — 이식성 회귀의 무대.

    U6-A(#975) 이후 루트는 **하나**다: hwpx·txt 가 같은 ``templates`` 아래 산다."""
    home = tmp_path / "home-A"
    (home / "templates" / "조달").mkdir(parents=True)
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    return home


def test_template_link_is_stored_as_a_library_relative_key(library_home):
    """저장은 절대경로 **옆에** 루트 상대 POSIX 키를 가산으로 싣는다(#348).

    키는 그룹 지정이 이미 쓰는 값(결정 8)과 같은 관례이고, 루트 선택은 확장자가 한다 —
    매체를 선언하는 새 필드는 없다. 신규 durable 필드는 상대키 하나뿐이다.
    """
    hwpx = library_home / "templates" / "조달" / "공고서.hwpx"
    txt = library_home / "templates" / "안내문.txt"
    root = library_home / "templates"

    job = Job(name="a", template_path=str(hwpx))
    assert library_key_for(job.template_path, root) == "조달/공고서.hwpx"    # 하위폴더까지 POSIX
    assert encode_job(job, root=root)["template_key"] == "조달/공고서.hwpx"
    assert encode_job(job, root=root)["template_path"] == str(hwpx)  # 절대경로는 **가산으로 유지**

    # 루트는 **하나**다(U6-A) — txt 도 같은 서식 폴더 기준이다.
    assert library_key_for(str(txt), root) == "안내문.txt"
    # 매체 미상은 승격하지 않는다(모르는 것을 추측하지 않는다).
    docx = library_home / "templates" / "x.docx"
    assert library_key_for(str(docx), root) == ""
    assert library_key_for("", root) == ""
    # 루트 미주입은 프로세스 홀더로 떨어진다 — 두 번째 정본을 지어내지 않는다.
    assert library_key_for(job.template_path) == "조달/공고서.hwpx"


def test_moving_the_home_keeps_the_keyed_template_resolved(library_home, tmp_path, monkeypatch):
    """홈을 **옮기면** 상대키가 작업의 템플릿을 계속 해석한다 — 이 이슈의 존재 이유.

    레지스트리는 원래 위치-불가지였는데 **내용물이 절대경로로 위치에 묶여** 홈 이동이 모든
    작업의 링크를 한꺼번에 끊었다. 키는 기계 고유 부분을 이름으로 치환해 그 결속을 끊는다.

    **진짜 이사로 잰다**(복사가 아니라): 키가 서는 조건은 「옛 절대경로가 죽었다」이고,
    복사본에서 재면 원본이 살아 있어 이 단언이 재는 것이 무엇인지 모호해진다.
    """
    tpl = library_home / "templates" / "조달" / "공고서.hwpx"
    tpl.write_bytes(b"")                                  # 실재하는 템플릿이라야 링크가 산다
    JobRegistry(library_home / "jobs").save(Job(name="a", template_path=str(tpl)))

    moved = tmp_path / "home-B"
    shutil.copytree(library_home, moved)                  # 홈 통째 이사(백업 복원·PC 교체)
    shutil.rmtree(library_home)                           # 옛 자리는 사라진다 — 그게 이사다
    monkeypatch.setenv("HWPXFILLER_HOME", str(moved))

    job = JobRegistry(moved / "jobs").load("a")
    assert job.template_path == str(moved / "templates" / "조달" / "공고서.hwpx")
    assert job.media == "hwpx"                            # 표면 파생(매체·방식)은 그대로 성립


def test_a_live_absolute_path_beats_the_key_when_the_root_changes(
    library_home, tmp_path
):
    """서식 폴더를 바꿔도 **살아 있는 절대경로**가 이긴다 — 조용한 재결속 금지(U6-A #975).

    루트가 사용자가 고르는 값이 되면서 「같은 키 = 같은 파일」 전제가 깨졌다. 새 루트에 같은
    이름 파일이 있다고 작업이 그쪽으로 갈아타면, 법적 효력이 있는 문서를 **다른 서식**으로
    만들게 된다. 그래서 키는 절대경로가 죽었을 때만 선다.
    """
    tpl = library_home / "templates" / "조달" / "공고서.hwpx"
    tpl.write_bytes(b"A")
    JobRegistry(library_home / "jobs").save(Job(name="a", template_path=str(tpl)))

    # 사용자가 서식 폴더를 옮긴다 — 새 루트에 **같은 이름**의 남의 파일이 있다.
    other = tmp_path / "새서식"
    (other / "조달").mkdir(parents=True)
    (other / "조달" / "공고서.hwpx").write_bytes(b"B")
    settings.save_templates_root(str(other))

    assert JobRegistry(library_home / "jobs").load("a").template_path == str(tpl)


def test_a_dead_absolute_path_does_not_fall_onto_a_same_named_file_in_the_new_root(
    library_home, tmp_path
):
    """옛 파일이 사라져도 새 루트의 동명 파일로 **갈아타지 않는다** — 끊긴 대로 보인다."""
    tpl = library_home / "templates" / "조달" / "공고서.hwpx"
    tpl.write_bytes(b"")
    JobRegistry(library_home / "jobs").save(Job(name="a", template_path=str(tpl)))
    tpl.unlink()                                          # 사용자가 옛 서식을 지웠다

    other = tmp_path / "새서식"
    (other / "조달").mkdir(parents=True)
    (other / "조달" / "공고서.hwpx").write_bytes(b"B")   # 붙으면 안 되는 미끼
    settings.save_templates_root(str(other))

    reloaded = JobRegistry(library_home / "jobs").load("a")
    assert reloaded.template_path == str(tpl)             # 끊긴 옛 자리 그대로(relink 동선)
    assert reloaded.template_path != str(other / "조달" / "공고서.hwpx")


def test_template_outside_the_root_fails_promotion_without_a_filename_fallback(
    library_home, tmp_path, monkeypatch
):
    """루트 밖 템플릿은 **폴백 없이** 승격에 실패하고 절대경로를 유지한다.

    그룹 키(:func:`~hwpxfiller.webapp.template_groups.rel_key`)는 루트 밖이면 파일명으로
    폴백하지만, 작업 링크에서 그 폴백은 **다른 폴더의 동명 파일에 조용히 붙는다**(끊긴 참조의
    자동 파일명 매칭 = 영상 편집 도구들이 대가를 치른 결함류). 여기서는 "이 작업은 이식 대상이
    아니다"를 정직하게 남긴다.
    """
    outside = tmp_path / "바탕화면" / "공고서.hwpx"          # 라이브러리 안 동명 파일과 같은 이름
    outside.parent.mkdir(parents=True)
    decoy = library_home / "templates" / "공고서.hwpx"      # 붙으면 안 되는 미끼
    decoy.write_bytes(b"")

    job = Job(name="a", template_path=str(outside))
    assert library_key_for(job.template_path) == ""                          # 파일명 폴백 없음
    d = encode_job(job)
    assert d["template_key"] == "" and d["template_path"] == str(outside)

    JobRegistry(library_home / "jobs").save(job)
    moved = tmp_path / "home-B"
    shutil.copytree(library_home, moved)
    monkeypatch.setenv("HWPXFILLER_HOME", str(moved))
    reloaded = JobRegistry(moved / "jobs").load("a")
    # 홈이 옮겨져도 미끼에 붙지 않는다 — 원래 절대경로 그대로(끊겼으면 끊긴 대로 보인다).
    assert reloaded.template_path == str(outside)
    assert reloaded.template_path != str(moved / "templates" / "공고서.hwpx")


def test_reading_a_job_does_not_migrate_the_file(library_home):
    """마이그레이션 없음 — 읽기는 옛 경로로 폴백만 하고 디스크를 고치지 않는다(조용한 변이 금지).

    승격은 **저장이 지나갈 때만** 일어난다. 읽는 김에 durable 을 고치면 목록 렌더 한 번이
    사용자가 요청한 적 없는 쓰기가 되고, 그 쓰기가 실패하는 환경에서 목록이 통째로 죽는다.
    """
    hwpx = library_home / "templates" / "조달" / "공고서.hwpx"
    legacy = {"name": "a", "template_path": str(hwpx)}     # 구 JSON = 키 없음
    path = library_home / "jobs" / "a.job.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()

    reg = JobRegistry(library_home / "jobs")
    assert reg.load("a").template_path == str(hwpx)        # 옛 경로 폴백으로 그대로 열린다
    reg.list_jobs()
    assert path.read_bytes() == before                     # 바이트 한 톨 안 바뀐다

    reg.save(reg.load("a"), allow_overwrite=True)          # 저장이 지날 때 **비로소** 승격
    assert json.loads(path.read_text(encoding="utf-8"))["template_key"] == "조달/공고서.hwpx"


def test_corrupt_template_key_is_loud(library_home):
    """상대키는 루트에 이어 붙여 해석되므로 절대·드라이브·``..`` 는 루트 밖으로 새는 값이다.

    다른 durable 필드와 같은 규율으로 경계에서 loud raise —
    :meth:`JobRegistry.list_jobs` 의 파일 단위 격리가 '손상됨' 행으로 표면화한다.
    """
    base = {"name": "a", "template_path": "/t.hwpx"}
    escapes = ["C:/훔친/x.hwpx", "/x.hwpx", "../../x.hwpx", "조달/../../x.hwpx", r"\\srv\x.hwpx"]
    for bad in escapes:
        with pytest.raises(ValueError):
            decode_job({**base, "template_key": bad})
    with pytest.raises(ValueError):
        decode_job({**base, "template_key": 7})         # 비문자열도 loud(문자열 계약)


def test_lexical_path_components_are_normalized_before_promotion(library_home):
    """쓰기가 **읽기 방어에 걸릴 키를 스스로 만들지 않는다**(#368 2R).

    ``relative_to`` 는 ``.``·``..`` 를 **보존**하므로 정규화 전에는 ``sub/../공고서.hwpx`` 같은
    키가 나왔고, 그 키는 로드에서 loud 거절돼 **앱이 자기가 저장한 작업을 스스로 손상됨으로
    읽었다**. 저장~로드 한 바퀴를 실제로 돌려 그 자기모순이 없음을 못박는다.
    """
    tpl = library_home / "templates" / "조달" / "공고서.hwpx"
    noisy = library_home / "templates" / "조달" / "sub" / ".." / "공고서.hwpx"

    job = Job(name="a", template_path=str(noisy))
    root = library_home / "templates"
    assert library_key_for(job.template_path, root) == "조달/공고서.hwpx"    # `..` 가 걷힌 키
    _reject_unsafe_key(library_key_for(job.template_path, root))                    # 읽기 방어를 통과하는 값이다

    reg = JobRegistry(library_home / "jobs")
    reg.save(job)
    # 해석은 **같은 파일**을 가리킨다. 문자열까지 정규화되지는 않는다(U6-A): 살아 있는
    # 절대경로는 저장된 그대로 이기고, 읽기가 durable 값을 손보지 않는다.
    assert os.path.normpath(reg.load("a").template_path) == str(tpl)
    assert reg.list_jobs()[0].name == "a"                   # '손상됨' 으로 떨어지지 않는다


def test_normalization_does_not_loosen_the_outside_the_root_judgment(library_home):
    """정규화가 「루트 밖은 폴백 없이 실패」를 흔들지 않는다 — 오히려 **조인다**.

    정규화 전에는 루트로 시작하기만 하면 ``relative_to`` 가 통과해서
    ``templates/../바깥/공고서.hwpx`` 가 ``../바깥/공고서.hwpx`` 라는 **루트를 벗어나는 키**가
    됐다. 어휘 정규화 뒤 그 경로는 정직하게 루트 밖으로 판정돼 승격되지 않는다.
    """
    escaping = library_home / "templates" / ".." / "바깥" / "공고서.hwpx"
    assert library_key_for(str(escaping), library_home / "templates") == ""
    # 루트 밖 판정은 그대로 절대경로 유지로 이어진다(폴백 없음).
    assert encode_job(Job(name="a", template_path=str(escaping)))["template_path"] == str(escaping)


def test_promotion_is_abandoned_when_normalization_would_name_another_file(
    library_home, monkeypatch
):
    """어휘 정규화가 **다른 파일**을 이름하면 승격을 포기한다 — 심볼릭 링크 경유 ``..`` 의 자리.

    ``resolve()`` 를 쓰지 않는 대신(관례 갈라짐·디스크 상태 의존, :func:`_lexically_normal` 선언)
    정규화가 성분을 실제로 걷은 경우에만 왕복을 실측한다. 실 심볼릭 링크 생성은 윈도우 권한에
    좌우되므로 그 실측 지점(``realpath``)을 대신 못박는다 — 조용한 재결속이 없다는 것이 계약이다.
    """
    noisy = library_home / "templates" / "조달" / "link" / ".." / "공고서.hwpx"
    root = library_home / "templates"
    assert library_key_for(str(noisy), root) == "조달/공고서.hwpx"

    real = os.path.realpath

    def _as_if_link_were_a_symlink(p):
        # 걷힌 성분이 링크였던 세상: 원본은 링크 대상 밑을 이름한다.
        if "link" in os.fspath(p):
            return real(library_home / "다른곳" / "공고서.hwpx")
        return real(p)

    monkeypatch.setattr(os.path, "realpath", _as_if_link_were_a_symlink)
    assert library_key_for(str(noisy), root) == "", (
        "정규화가 다른 파일을 이름하는데 승격했습니다 — 조용한 재결속입니다."
    )


def test_template_key_wins_over_a_stale_absolute_path(library_home):
    """키와 경로가 어긋나면 **키가 이긴다** — 경로는 기계 고유 잔재이고 키가 정체성이다."""
    stale = {
        "name": "a",
        "template_path": r"D:\옛PC\templates\조달\공고서.hwpx",
        "template_key": "조달/공고서.hwpx",
    }
    job = decode_job(stale)
    assert job.template_path == str(library_home / "templates" / "조달" / "공고서.hwpx")


# ---------------------------------------- 프로세스 writer lease(#192, P2-21 #569 host 이관)
# 물리 거처는 :mod:`hwpxfiller.host.job_writer_lease` 로 옮겨졌지만 계약의 주 소비자는
# JobRegistry 라 characterization 도 이 파일이 소유한다(새 테스트 파일 금지).
from pathlib import Path  # noqa: E402 — lease 테스트 그룹(파일 하단 응집)

from hwpxfiller.host.job_writer_lease import (  # noqa: E402 — lease 테스트 그룹(파일 하단 응집)
    JobRegistryOwnershipError,
    _OwnedWriteLock,
    _RegistryWriteState,
    shared_write_state,
)


def test_second_writer_state_is_refused_and_lease_frees_on_owner_death(tmp_path):
    """같은 디렉터리 키의 두 번째 소유권 주장은 loud 거절(ERROR_ALREADY_EXISTS 경로) —
    파일을 만지기 전에 막힌다. 소유자가 죽으면(mutex 해제) 재획득이 가능해야 한다:
    거절이 영구 잠김이면 앱 재시작 후에도 저장이 불가능해진다."""
    import gc

    first = _RegistryWriteState(str(tmp_path / "jobs"))
    first.claim_process_ownership()
    second = _RegistryWriteState(str(tmp_path / "jobs"))
    with pytest.raises(JobRegistryOwnershipError) as exc:
        second.claim_process_ownership()
    assert "다른 문서나르미 프로세스" in str(exc.value)
    assert second._owner is None                     # 실패는 소유 흔적을 남기지 않는다

    del first                                        # 소유자 소멸 = __del__ 이 mutex 를 닫는다
    gc.collect()
    second.claim_process_ownership()                 # 이제 같은 키를 새로 잡을 수 있다
    assert second._owner is not None
    del second
    gc.collect()


def test_mutex_creation_failure_is_loud(monkeypatch):
    """CreateMutexW 자체가 실패하면(핸들 0) 조용히 무소유로 진행하지 않고 WinError 를 재진술한다."""
    import ctypes

    class _Fn:
        def __init__(self, result):
            self._result = result

        def __call__(self, *args):
            return self._result

    class _Dll:
        def __init__(self):
            self.CreateMutexW = _Fn(0)               # 핸들 0 = 생성 실패
            self.CloseHandle = _Fn(1)

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: _Dll())
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)
    state = _RegistryWriteState("lease-create-fail")
    with pytest.raises(JobRegistryOwnershipError) as exc:
        state.claim_process_ownership()
    assert "WinError 5" in str(exc.value)
    assert state._owner is None


def test_posix_flock_claims_blocks_and_releases(tmp_path, monkeypatch):
    """POSIX 경로 — flock 성공은 스트림 소유, 실패는 스트림을 닫고 loud, 해제는 close.

    이 저장소는 Windows 전용이라 실 flock 을 돌릴 수 없다 — fake fcntl 주입으로 분기
    계약(성공/차단/해제/해제 실패 삼킴)을 결정론으로 못박는다.
    """
    import sys as _sys
    import tempfile as _tempfile

    calls: "list[tuple]" = []

    class _FakeFcntl:
        LOCK_EX, LOCK_NB = 2, 4

        @staticmethod
        def flock(fd, flags):
            calls.append((fd, flags))

    monkeypatch.setattr(_sys, "platform", "linux")
    monkeypatch.setitem(_sys.modules, "fcntl", _FakeFcntl)
    monkeypatch.setattr(_tempfile, "gettempdir", lambda: str(tmp_path))

    state = _RegistryWriteState("posix-key")
    state.claim_process_ownership()
    stream = state._owner
    assert stream is not None and calls == [(stream.fileno(), 2 | 4)]
    state.__del__()                                  # posix 해제 = 스트림 close
    assert stream.closed
    state._owner = None                              # GC 재호출이 닫힌 스트림을 다시 안 만지게

    class _BlockedFcntl:
        LOCK_EX, LOCK_NB = 2, 4

        @staticmethod
        def flock(fd, flags):
            raise OSError(11, "would block")         # 다른 프로세스가 쥐고 있다

    monkeypatch.setitem(_sys.modules, "fcntl", _BlockedFcntl)
    blocked = _RegistryWriteState("posix-key")
    with pytest.raises(JobRegistryOwnershipError):
        blocked.claim_process_ownership()
    assert blocked._owner is None                    # 실패 시 스트림이 남지 않는다

    class _ExplodingStream:
        def close(self):
            raise OSError("boom")

    exploding = _RegistryWriteState("posix-close-fail")
    exploding._owner = _ExplodingStream()
    exploding.__del__()                              # 해제 실패는 삼킨다(GC 경로 예외 금지)
    exploding._owner = None


def test_lease_del_without_ownership_is_a_noop():
    _RegistryWriteState("never-claimed").__del__()   # 소유 전 소멸 — 닫을 자원이 없다


def test_write_lock_rolls_back_the_thread_lock_when_ownership_fails(monkeypatch):
    """소유권 실패는 스레드 잠금을 쥔 채 남지 않는다 — 아니면 이 프로세스의 모든 registry
    가 영구 교착한다(첫 실패가 잠금을 삼키는 조용한 결함)."""
    import threading

    state = _RegistryWriteState("rollback-key")
    lock = _OwnedWriteLock(state)

    def _refuse():
        raise JobRegistryOwnershipError("소유권 거절")

    monkeypatch.setattr(state, "claim_process_ownership", _refuse)
    with pytest.raises(JobRegistryOwnershipError):
        lock.acquire()

    # 판정은 다른 스레드의 비차단 획득으로(RLock 은 같은 스레드에선 재획득되므로 무판별).
    acquired_elsewhere: "list[bool]" = []

    def _try():
        ok = state.lock.acquire(blocking=False)
        acquired_elsewhere.append(ok)
        if ok:
            state.lock.release()

    t = threading.Thread(target=_try)
    t.start()
    t.join(3)
    assert acquired_elsewhere == [True], "실패한 acquire 가 스레드 잠금을 되돌리지 않았습니다."

    monkeypatch.setattr(state, "claim_process_ownership", lambda: None)
    assert lock.acquire(True, 1) is True             # timeout 경로 포함 재획득 가능
    lock.release()


def test_shared_write_state_falls_back_to_lexical_key_for_unresolvable_paths(tmp_path):
    """resolve 가 실패하는 경로(오프라인 드라이브류)도 같은 디렉터리는 같은 상태를 공유한다."""
    class _Unresolvable(type(Path())):
        def resolve(self, *a, **kw):
            raise OSError("unresolvable")

    a = shared_write_state(_Unresolvable(tmp_path / "jobs"))
    b = shared_write_state(tmp_path / "jobs")
    assert a is b                                    # 해석 실패 = 어휘 키 폴백(같은 키)


def test_corruption_surface_gives_values_and_removal_rejudges_membership(tmp_path):
    """손상 표면(P2-21 #569) — 값 객체(file_name·token·error)와 잠금 안 재판정 삭제.

    구 :meth:`HomeViewModel.delete_corrupt` 임계구역의 하강분 owner: ①한 스캔이 (정상,
    손상 값 객체)를 함께 주고 token 은 종전 표시 문자열(str(path))과 동일하다(표시 의미
    불변), ②목록 밖 token 은 CORRUPT_PATH_REJECT 로 loud 거절돼 임의 경로 삭제 통로가
    없다(#137 F10 시간 축), ③목록 안 token 만 실제로 지워진다.
    """
    reg = JobRegistry(tmp_path)
    reg.save(Job(name="정상", template_path="", mapping=MappingProfile()))
    bad = tmp_path / "깨진.job.json"
    bad.write_text("{ 이건 json 아님", encoding="utf-8")

    jobs, corrupt = reg.list_jobs_with_corruption()
    assert [j.name for j in jobs] == ["정상"]
    assert [(e.file_name, e.token) for e in corrupt] == [("깨진.job.json", str(bad))]
    assert corrupt[0].error                          # 사유를 빈칸으로 나르지 않는다

    victim = tmp_path / "무관파일.txt"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="목록에 없는"):
        reg.remove_corrupt_entry(str(victim))
    assert victim.exists() and bad.exists()          # 거절 = 무손상

    reg.remove_corrupt_entry(str(bad))
    assert not bad.exists()
    assert reg.list_jobs_with_corruption()[1] == []  # 해소가 다음 스캔에 보인다


def test_save_reads_the_template_root_exactly_once(tmp_path):
    """한 저장은 루트를 **한 번** 읽는다 — 임계구역 안에서 세 번 읽으면 그 사이 재지정이
    끼어 한 저장이 두 루트를 뜻할 수 있다(U6-A 리뷰)."""
    reads: "list[int]" = []
    root = tmp_path / "서식"
    root.mkdir()

    def watched():
        reads.append(1)
        return root

    reg = JobRegistry(tmp_path / "jobs", template_root=watched)
    reg.save(Job(name="A", template_path=str(root / "t.hwpx")))
    assert len(reads) == 1, f"저장 한 번에 루트를 {len(reads)}회 읽었습니다."

    reads.clear()
    reg.save(Job(name="A", template_path=str(root / "t.hwpx")))   # 자기 갱신(직전 판본 읽기 포함)
    assert len(reads) == 1, f"재저장 한 번에 루트를 {len(reads)}회 읽었습니다."


# ------------------------- durable 훼손의 남은 갈래(무marker 계약 — 커버리지 하한)
def test_previous_rules_field_entry_shape_is_loud():
    """``previous_rules.fields`` 의 **항목**도 형상 검증을 지난다(이름=str · 축=dict).

    바깥에서 훼손된 durable 이 여기를 통과하면 「무엇이었나」를 말하는 증거가 조용히
    다른 모양이 된다 — 그 뒤의 판본 비교가 거짓말을 하게 되므로 읽는 자리에서 막는다.
    """
    d = encode_job(_job())
    d["previous_rules"] = {"template": "t", "filename": "f", "fields": {1: {}}}
    with pytest.raises(ValueError, match="필드이름"):        # 이름이 문자열이 아니다
        decode_job(d)
    d["previous_rules"] = {"template": "t", "filename": "f", "fields": {"공고명": "축아님"}}
    with pytest.raises(ValueError, match="필드이름"):        # 축이 사전이 아니다
        decode_job(d)


def test_previous_rules_template_and_filename_must_be_strings():
    """직전 판본의 template·filename 은 문자열이다 — 타입 훼손을 조용히 통과시키지 않는다."""
    from hwpxfiller.domain.job import rules_values

    d = encode_job(_job())
    base = rules_values(_job())
    d["previous_rules"] = {**base, "template": 3}
    with pytest.raises(ValueError, match="문자열이어야"):
        decode_job(d)
    d["previous_rules"] = {**base, "filename": None}
    with pytest.raises(ValueError, match="문자열이어야"):
        decode_job(d)


def test_assign_authority_id_is_idempotent_and_keeps_the_first_binding(tmp_path):
    """권위 id 는 **최초 1회만** 쓴다(S3-09) — 두 번째 발급은 기존 값을 이기지 못한다.

    다시 쓰면 그 작업의 적용 이력(epoch·Preparation)이 통째로 남의 것이 된다. 경합하는
    두 발급 중 먼저 커밋된 쪽이 이기고, 호출자는 **반환 Job 의 값**을 정본으로 쓴다.
    """
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(_job())
    first = registry.assign_authority_id("입찰공고서", "auth-1")
    assert first.authority_id == "auth-1"

    second = registry.assign_authority_id("입찰공고서", "auth-2")
    assert second.authority_id == "auth-1", "이미 결속된 권위를 덮었습니다"
    assert registry.load("입찰공고서").authority_id == "auth-1"


def test_a_directory_named_like_a_template_is_not_migrated(tmp_path, monkeypatch):
    """이관은 **파일만** 옮긴다 — ``.txt`` 로 끝나는 폴더는 건드리지 않는다(U6-A §4).

    ``rglob`` 은 이름만 보므로 폴더도 걸린다. 그것을 ``shutil.move`` 로 넘기면 폴더째
    옮겨져 새 루트에 목록이 읽지 못하는 하위트리가 생긴다 — 걸러 내되 사유를 지어내지도
    않는다(안 옮긴 것이 아니라 애초에 옮길 대상이 아니다).
    """
    from hwpxfiller.external.template_root import (
        TemplateRoot,
        migrate_legacy_text_templates,
    )

    home = tmp_path / "home"
    legacy = home / "text_templates"
    (legacy / "폴더인데.txt").mkdir(parents=True)         # 이름만 템플릿인 **폴더**
    (legacy / "진짜.txt").write_text("{{건명}}", encoding="utf-8")
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))

    result = migrate_legacy_text_templates(home=home, root=TemplateRoot())

    assert result.moved == ["진짜.txt"], f"파일 하나만 옮겨야 합니다: {result!r}"
    assert result.skipped == [], "옮길 대상이 아닌 것을 건너뛴 것으로 세지 않는다"
    assert (legacy / "폴더인데.txt").is_dir(), "폴더가 옮겨졌습니다"


def test_excluded_subtrees_are_skipped_with_a_reason(tmp_path, monkeypatch):
    """나열이 거르는 하위트리(``Results``)는 옮기지 않고 **사유와 함께** 남긴다.

    옮겨 봐야 새 루트에서도 걸러져 목록에서 사라진다 — 사라지는 것이 아니라 「안 옮겼다」는
    사실이 남아야 조용한 증발이 아니다.
    """
    from hwpxfiller.external.template_root import (
        TemplateRoot,
        migrate_legacy_text_templates,
    )

    home = tmp_path / "home"
    legacy = home / "text_templates"
    (legacy / "Results").mkdir(parents=True)
    (legacy / "Results" / "산출.txt").write_text("{{건명}}", encoding="utf-8")
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))

    result = migrate_legacy_text_templates(home=home, root=TemplateRoot())

    assert result.moved == []
    assert [name for name, _ in result.skipped] == ["Results/산출.txt"]
    assert "읽지 않는 하위 폴더" in result.skipped[0][1]
    assert (legacy / "Results" / "산출.txt").is_file(), "제외 대상이 옮겨졌습니다"


def test_source_file_exists_answers_for_files_only(tmp_path):
    """가져오기 원본 존재 판정은 **파일**만 참이다 — 폴더를 통과시키면 복사가 늦게 터진다."""
    from hwpxfiller.external.template_files import TemplateFileStore

    live = tmp_path / "서식.hwpx"
    live.write_bytes(b"x")
    folder = tmp_path / "폴더.hwpx"
    folder.mkdir()

    assert TemplateFileStore.source_file_exists(live) is True
    assert TemplateFileStore.source_file_exists(folder) is False
    assert TemplateFileStore.source_file_exists(tmp_path / "없음.hwpx") is False
