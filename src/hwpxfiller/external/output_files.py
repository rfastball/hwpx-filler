"""Output-directory filesystem effects."""

from __future__ import annotations

from pathlib import Path

from ..domain.output_name import collision_key


def existing_output_paths(out_dir: "str | Path", names: "list[str]") -> "list[str]":
    """계획된 이름 중 저장 폴더에 **이미 있는** 것 — 충돌 판정은 이름 kernel 의 키(대소문자 무관).

    배치 안 충돌과 같은 규칙이어야 한다(#798): 폴더에 ``Report.hwpx`` 가 있을 때 ``report.hwpx``
    를 「새 파일」로 세면 대소문자를 구분하지 않는 Windows 에서 확인 없이 덮어쓴다. 그래서 폴더
    항목을 한 번 읽어 같은 키로 대조하고, 돌려주는 경로는 **디스크의 실제 철자**다(확인창이 실제로
    사라질 파일을 말한다). 폴더가 없으면 충돌도 없다.
    """
    out = Path(out_dir)
    if not out.is_dir():
        return []
    on_disk = {collision_key(entry.name): entry.name for entry in out.iterdir()}
    existing: list[str] = []
    for name in names:
        actual = on_disk.get(collision_key(name))
        if actual is not None:
            existing.append(str(out / actual))
    return existing


def ensure_output_directory(out_dir: "str | Path") -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
