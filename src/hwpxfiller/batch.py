"""일괄 생성 오케스트레이션 — VBA ``Process_HWP_Generation`` 의 순수 로직 포트.

UI(MsgBox) 를 제거하고, 템플릿 + 레코드 목록 + 저장경로/파일명 패턴을 받아
문서를 일괄 생성하고 결과를 구조화해 반환한다. GUI/CLI 가 이를 감싼다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .core.engine import GenerateResult, HwpxEngine
from .naming import OutputNamer


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
    *,
    progress: "Callable[[int, int], None] | None" = None,
    now: "datetime | None" = None,
) -> BatchResult:
    """레코드 목록을 순회하며 문서를 일괄 생성한다.

    파일명은 :class:`OutputNamer` 가 배치 단위로 할당한다(연번·날짜 토큰·충돌 접미사).
    ``progress(done, total)`` 는 레코드마다 호출되는 선택적 콜백(GUI 워커의 진행률용).
    ``now`` 는 날짜 토큰 기준 시각 주입(테스트 결정성).
    """
    engine = engine or HwpxEngine()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    namer = OutputNamer(name_pattern, now=now)

    batch = BatchResult(total=len(records))
    for i, rec in enumerate(records, 1):
        target = str(out / namer.next(rec))
        res = engine.generate(template_path, rec, target)
        batch.results.append(res)
        if res.ok:
            batch.succeeded += 1
        if progress:
            progress(i, batch.total)
    return batch
