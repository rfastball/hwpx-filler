"""일괄 생성 오케스트레이션 — VBA ``Process_HWP_Generation`` 의 순수 로직 포트.

UI(MsgBox) 를 제거하고, 템플릿 + 레코드 목록 + 저장경로/파일명 패턴을 받아
문서를 일괄 생성하고 결과를 구조화해 반환한다. GUI/CLI 가 이를 감싼다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core.engine import GenerateResult, HwpxEngine
from .naming import make_output_filename


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    results: "list[GenerateResult]" = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded


def generate_batch(
    template_path: str,
    records: "list[dict[str, str]]",
    out_dir: str,
    name_pattern: str,
    engine: "HwpxEngine | None" = None,
) -> BatchResult:
    engine = engine or HwpxEngine()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    batch = BatchResult(total=len(records))
    for rec in records:
        filename = make_output_filename(name_pattern, rec)
        target = str(out / filename)
        res = engine.generate(template_path, rec, target)
        batch.results.append(res)
        if res.ok:
            batch.succeeded += 1
    return batch
