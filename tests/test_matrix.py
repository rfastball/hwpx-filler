"""매트릭스 실행(J2) — generate_matrix 헤드리스 테스트(가짜 엔진, 실 HWPX 무접촉).

M 작업 × 공유 데이터(N행) → 작업별 하위폴더, 교차 충돌 차단, 빈값 표식/스킵, 진행률.
"""

from __future__ import annotations

import ast
from pathlib import Path

from hwpxfiller.batch import MatrixResult, generate_batch, generate_matrix
from hwpxfiller.core.engine import GenerateResult
from hwpxfiller.core.job import MISSING_MARKER, Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile


class _FakeEngine:
    """엔진 계약을 흉내낸다: 빈값 스킵(engine.py:42) + 대상 파일에 주입 데이터 기록."""

    def generate(self, template_path, data, output_path) -> GenerateResult:
        active = {k: str(v) for k, v in data.items() if str(v).strip() != ""}
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(repr(active), encoding="utf-8")
        return GenerateResult(True, output_path, applied=set(active))


class _Src:
    def __init__(self, records):
        self._records = records

    def records(self):
        return list(self._records)

    def fields(self):
        return list(self._records[0]) if self._records else []


def _job(name, tfield, source, pattern):
    return Job(
        name=name, template_path=f"/{name}.hwpx",
        mapping=MappingProfile(mappings=[FieldMapping(template_field=tfield, sources=[source])]),
        filename_pattern=pattern,
    )


def _read(path: Path) -> dict:
    return ast.literal_eval(path.read_text(encoding="utf-8"))


def test_matrix_m_jobs_per_job_subfolders(tmp_path):
    jobs = [
        _job("공고", "공고명", "bidNtceNm", "공고-{{공고명}}"),
        _job("요청", "품명", "itemNm", "요청-{{품명}}"),
    ]
    src = _Src([{"bidNtceNm": "A", "itemNm": "X"}, {"bidNtceNm": "B", "itemNm": "Y"}])
    res = generate_matrix(jobs, src, [0, 1], str(tmp_path), engine=_FakeEngine())

    assert isinstance(res, MatrixResult)
    assert res.job_count == 2 and res.total == 4 and res.succeeded == 4 and res.failed == 0
    # 작업별 하위폴더에 각 2건.
    assert sorted(p.name for p in (tmp_path / "공고").glob("*.hwpx")) == [
        "공고-A.hwpx", "공고-B.hwpx"
    ]
    assert sorted(p.name for p in (tmp_path / "요청").glob("*.hwpx")) == [
        "요청-X.hwpx", "요청-Y.hwpx"
    ]
    # per_job 메타의 out_dir 이 하위폴더를 가리킨다.
    dirs = {j.job_name: j.out_dir for j in res.per_job}
    assert dirs["공고"].endswith("공고") and dirs["요청"].endswith("요청")


def test_matrix_same_pattern_no_cross_collision(tmp_path):
    """두 작업이 같은 파일명 패턴이어도 하위폴더 분리로 교차 충돌이 없다."""
    jobs = [
        _job("잡A", "공고명", "bidNtceNm", "문서-{{공고명}}"),
        _job("잡B", "공고명", "bidNtceNm", "문서-{{공고명}}"),
    ]
    src = _Src([{"bidNtceNm": "같은값"}])
    res = generate_matrix(jobs, src, [0], str(tmp_path), engine=_FakeEngine())
    assert res.total == 2 and res.succeeded == 2
    assert (tmp_path / "잡A" / "문서-같은값.hwpx").exists()
    assert (tmp_path / "잡B" / "문서-같은값.hwpx").exists()  # 폴더가 달라 덮어쓰기 없음


def test_matrix_marks_missing_loudly_by_default(tmp_path):
    """빈 필드는 기본으로 MISSING_MARKER 표식이 주입된다(누락은 시끄럽게)."""
    jobs = [_job("요청", "품명", "itemNm", "요청-{{seq}}")]
    src = _Src([{"itemNm": ""}])  # 품명 소스가 빈 값
    generate_matrix(jobs, src, [0], str(tmp_path), engine=_FakeEngine())
    data = _read(tmp_path / "요청" / "요청-1.hwpx")
    assert data["품명"] == MISSING_MARKER.format(field="품명")


def test_matrix_blank_skip_when_marking_off(tmp_path):
    """mark_missing='' 이면 빈 필드는 표식 없이 스킵(엔진 빈값 스킵 불변)."""
    jobs = [_job("요청", "품명", "itemNm", "요청-{{seq}}")]
    src = _Src([{"itemNm": ""}])
    generate_matrix(jobs, src, [0], str(tmp_path), engine=_FakeEngine(), mark_missing="")
    data = _read(tmp_path / "요청" / "요청-1.hwpx")
    assert "품명" not in data  # 빈값 → 엔진 active 에서 제외


def test_matrix_progress_is_cumulative(tmp_path):
    jobs = [
        _job("A", "f", "s", "a-{{seq}}"),
        _job("B", "f", "s", "b-{{seq}}"),
    ]
    src = _Src([{"s": "1"}, {"s": "2"}])
    seen = []
    generate_matrix(
        jobs, src, [0, 1], str(tmp_path), engine=_FakeEngine(),
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen[-1] == (4, 4)          # 누적 done == grand_total
    assert all(t == 4 for _, t in seen)  # grand_total 은 M×N 고정
    assert [d for d, _ in seen] == [1, 2, 3, 4]  # 작업 경계 넘어 단조 증가


def test_single_job_generate_batch_unchanged(tmp_path):
    """단일 잡×단일 데이터 회귀 — generate_batch 는 매트릭스와 무관하게 그대로."""
    res = generate_batch(
        "/t.hwpx", [{"공고명": "A"}, {"공고명": "B"}], str(tmp_path), "d-{{공고명}}",
        engine=_FakeEngine(),
    )
    assert res.total == 2 and res.succeeded == 2
    assert (tmp_path / "d-A.hwpx").exists() and (tmp_path / "d-B.hwpx").exists()
