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
from .naming import existing_outputs, plan_output_names


class OutputCollisionError(FileExistsError):
    """산출물 이름이 디스크의 기존 파일과 충돌(RC-02) — 덮어쓰기 확정 없이는 차단.

    환경성 :class:`FileExistsError` (예: ``--out`` 자리에 파일이 있어 makedirs 실패)
    와 구분한다 — 후자에 '덮어쓰려면 --overwrite' 안내를 붙이면 거짓 안내가 된다.
    """


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    results: "list[GenerateResult]" = field(default_factory=list)
    # 협조적 취소로 완주하지 못했는가(RC-06) — True 면 results 는 부분 결과다.
    cancelled: bool = False

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def attempted(self) -> int:
        """실제 시도한 레코드 수 — 취소 시 total(계획)과 갈라진다."""
        return len(self.results)


def generate_batch(
    template_path: str,
    records: "list[dict[str, str]]",
    out_dir: str,
    name_pattern: str,
    engine: "HwpxEngine | None" = None,
    *,
    progress: "Callable[[int, int], None] | None" = None,
    now: "datetime | None" = None,
    overwrite: bool = False,
    mapping=None,
    cancelled: "Callable[[], bool] | None" = None,
) -> BatchResult:
    """레코드 목록을 순회하며 문서를 일괄 생성한다.

    ``mapping``(:class:`~hwpxfiller.core.mapping.MappingProfile`)이 주어지면 **생성
    경계에서** 템플릿 구조 드리프트를 재검사한다(RC-03). 호출측
    validate 이후 템플릿이 교체돼도(TOCTOU) 다른 문서종이 '성공'으로 섞여 나가지
    않도록 첫 파일을 쓰기 전에 :class:`ValueError` 로 원자 차단한다. 문구는
    :meth:`~hwpxfiller.core.fill_ledger.TemplateStructureDrift.describe` 단일화.

    파일명은 :func:`~hwpxfiller.naming.plan_output_names` 로 **먼저 전부** 계산한다
    (연번·날짜 토큰·배치 내 충돌 접미사 — :class:`~hwpxfiller.naming.OutputNamer` 규칙).
    대상 중 디스크에 이미 존재하는 파일이 있으면 ``overwrite=True`` 없이는 생성을
    시작하기 전에 :class:`FileExistsError` 로 원자 차단한다(RC-02: 기존 산출물의
    무경고 파괴 금지 — GUI 는 사용자 확인 후, CLI 는 ``--overwrite`` 로만 통과).
    ``progress(done, total)`` 는 레코드마다 호출되는 선택적 콜백(GUI 워커의 진행률용).
    ``cancelled()`` 가 True 를 돌려주면 **레코드 경계에서** 중단한다(RC-06) — 진행
    중인 문서는 완결하고, 결과엔 ``cancelled=True`` 와 부분 결과가 남는다.
    ``now`` 는 날짜 토큰 기준 시각 주입(테스트 결정성).
    """
    if mapping is not None:
        from .core.fill_ledger import template_path_drift

        drift = template_path_drift(template_path, mapping)
        if drift.has_drift:
            raise ValueError(
                "템플릿 구조 드리프트로 생성을 차단했습니다 — " + drift.describe(sep="; ")
            )
    engine = engine or HwpxEngine()
    out = Path(out_dir)
    names = plan_output_names(name_pattern, records, now=now)
    clobbered = existing_outputs(out, names)
    if clobbered and not overwrite:
        raise OutputCollisionError(
            f"이미 존재하는 파일 {len(clobbered)}개를 덮어쓰게 됩니다 — 덮어쓰기 확정 "
            "없이는 생성하지 않습니다: "
            + ", ".join(Path(p).name for p in clobbered)
        )
    out.mkdir(parents=True, exist_ok=True)

    batch = BatchResult(total=len(records))
    for i, (rec, name) in enumerate(zip(records, names, strict=True), 1):
        if cancelled is not None and cancelled():
            batch.cancelled = True
            break
        target = str(out / name)
        res = engine.generate(template_path, rec, target)
        batch.results.append(res)
        if res.ok:
            batch.succeeded += 1
        if progress:
            progress(i, batch.total)
    return batch
