"""Output-directory filesystem effects.

기존 파일 충돌 관찰은 managed 배달 계획의 점유 관찰
(:func:`hwpxfiller.external.current_execution_preparation.observe_path_occupancy`)이 진다 —
legacy 일괄 생성의 ``existing_output_paths`` 는 #1081 PR3 에서 퇴역했다.
"""

from __future__ import annotations

from pathlib import Path


def ensure_output_directory(out_dir: "str | Path") -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
