"""생성 경계 게이트(RC-03) + 협조적 취소(RC-06) — generate_batch/generate_matrix 헤드리스.

검증이 호출자(GUI validate·CLI --profile 분기)에만 있으면 validate 이후 템플릿 교체
(TOCTOU)나 새 호출측(파이프라인·API)이 자동으로 게이트 밖이 된다 — 경계 자체가 막는지,
취소가 레코드 경계에서 부분 결과를 남기는지를 못박는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.batch import generate_batch, generate_matrix
from hwpxfiller.core.engine import GenerateResult
from hwpxfiller.core.fill_ledger import TemplateStructureDrift
from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


class _FakeEngine:
    """엔진 계약 흉내 — 대상 파일에 주입 데이터 기록(실 HWPX 무접촉)."""

    def generate(self, template_path, data, output_path) -> GenerateResult:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(repr(dict(data)), encoding="utf-8")
        return GenerateResult(True, output_path, applied=set(data))


class _Src:
    def __init__(self, records):
        self._records = records

    def records(self):
        return list(self._records)

    def fields(self):
        return list(self._records[0]) if self._records else []


def _write_template(path: Path, fields) -> None:
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{field}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{field}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for field in fields
    )
    xml = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(
        entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}
    ).save(str(path))


def _mapping(*fields: str) -> MappingProfile:
    return MappingProfile(
        mappings=[FieldMapping(template_field=f, sources=[f]) for f in fields]
    )


# ------------------------------------------------ 생성 경계 드리프트 재검사(RC-03)
def test_generate_batch_blocks_drifted_template_before_any_write(tmp_path):
    """매핑이 주어지면 생성 경계에서 원자 차단 — 다른 문서종이 '성공'으로 못 섞인다."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "신규필드"])  # 매핑이 못 덮는 필드 유입
    out = tmp_path / "out"

    with pytest.raises(ValueError, match="구조 드리프트"):
        generate_batch(
            str(template), [{"공고명": "A"}], str(out), "d-{{공고명}}",
            engine=_FakeEngine(), mapping=_mapping("공고명"),
        )
    assert not out.exists()  # 출력 폴더조차 만들기 전에 차단


def test_generate_batch_between_batches_template_swap_is_blocked(tmp_path):
    """FX1(TOCTOU) — 검증 시점 통과 후 템플릿이 교체되면 **다음 배치 호출**이 차단.

    검사 시점은 배치 착수 경계(generate_batch 진입 시 1회)다 — 배치 **도중**(레코드
    경계) 교체까지 재검사하지는 않는다(U9 개명: 과장 없는 이름으로 정직하게).
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    mapping = _mapping("공고명")
    out = tmp_path / "out"

    # 검증 시점: 드리프트 없음 → 1차 배치 정상.
    res = generate_batch(
        str(template), [{"공고명": "A"}], str(out), "d-{{공고명}}",
        engine=_FakeEngine(), mapping=mapping,
    )
    assert res.succeeded == 1

    _write_template(template, ["품명"])  # 다른 문서종으로 교체(구매요청서 모사)
    with pytest.raises(ValueError, match="구조 드리프트"):
        generate_batch(
            str(template), [{"공고명": "B"}], str(out), "d2-{{공고명}}",
            engine=_FakeEngine(), mapping=mapping,
        )
    assert sorted(p.name for p in out.glob("*.hwpx")) == ["d-A.hwpx"]  # 혼종 산출 0


def test_generate_batch_without_mapping_skips_gate(tmp_path):
    """mapping 미제공(하위호환) — 기존 호출측 동작 불변."""
    res = generate_batch(
        "/no-such.hwpx", [{"공고명": "A"}], str(tmp_path), "d-{{공고명}}",
        engine=_FakeEngine(),
    )
    assert res.succeeded == 1


def test_drift_describe_is_single_source_of_message():
    """차단 문구 조립의 단일 출처(RC-03) — 4축 전부 한 함수에서 나온다."""
    drift = TemplateStructureDrift(
        template_only=("신규",), mapping_only=("소멸",),
        conflicting=("충돌",), read_error="깨짐",
    )
    text = drift.describe(sep="; ")
    assert "템플릿 구조를 읽을 수 없음: 깨짐" in text
    assert "새로 유입된 미매핑 필드: 신규" in text
    assert "템플릿에서 소멸한 매핑 필드: 소멸" in text
    assert "값 매핑과 비움 선언이 충돌하는 필드: 충돌" in text
    assert TemplateStructureDrift().describe() == ""  # 무드리프트 = 빈 문자열


# ------------------------------------------------------- 협조적 취소(RC-06)
def test_generate_batch_cancel_stops_at_record_boundary(tmp_path):
    """레코드 1 완료 직후 취소 → 부분 결과 + cancelled 플래그(완주 강제 금지)."""
    flag = {"stop": False}

    def progress(done, total):
        if done == 1:
            flag["stop"] = True  # 사용자 취소 클릭 모사(레코드 1 직후)

    res = generate_batch(
        "/t.hwpx", [{"n": str(i)} for i in range(50)], str(tmp_path), "d-{{n}}",
        engine=_FakeEngine(), progress=progress, cancelled=lambda: flag["stop"],
    )
    assert res.cancelled is True
    assert res.attempted == 1 and res.succeeded == 1
    assert res.total == 50  # 계획 대비 부분 결과임이 드러난다
    assert len(list(tmp_path.glob("*.hwpx"))) == 1  # 디스크도 1건뿐


def test_generate_batch_cancelled_before_start_writes_nothing(tmp_path):
    res = generate_batch(
        "/t.hwpx", [{"n": "1"}], str(tmp_path / "out"), "d-{{n}}",
        engine=_FakeEngine(), cancelled=lambda: True,
    )
    assert res.cancelled and res.attempted == 0
    assert not list((tmp_path / "out").glob("*.hwpx"))


def test_generate_matrix_cancel_skips_remaining_jobs(tmp_path):
    """작업 1의 레코드 1 직후 취소 → 작업 2는 시작조차 안 한다 + 부분 결과 집계."""
    def _job(name, tfield, source, pattern):
        path = tmp_path / f"{name}.hwpx"
        _write_template(path, [tfield])
        return Job(
            name=name, template_path=str(path),
            mapping=MappingProfile(
                mappings=[FieldMapping(template_field=tfield, sources=[source])]
            ),
            filename_pattern=pattern,
        )

    jobs = [
        _job("공고", "공고명", "bidNtceNm", "공고-{{공고명}}"),
        _job("요청", "품명", "itemNm", "요청-{{품명}}"),
    ]
    src = _Src([{"bidNtceNm": "A", "itemNm": "X"}, {"bidNtceNm": "B", "itemNm": "Y"}])
    out = tmp_path / "out"
    flag = {"stop": False}

    def progress(done, total):
        if done == 1:
            flag["stop"] = True

    res = generate_matrix(
        jobs, src, [0, 1], str(out), engine=_FakeEngine(),
        progress=progress, cancelled=lambda: flag["stop"],
    )
    assert res.cancelled is True
    assert len(res.per_job) == 1 and res.per_job[0].batch.cancelled
    assert res.per_job[0].batch.attempted == 1
    assert not (out / "요청").exists()  # 다음 작업 미착수
