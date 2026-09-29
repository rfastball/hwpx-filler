"""THIRD_PARTY_NOTICES.md 가 실제 런타임 의존성 정본(lock file)과 어긋나지 않는지(FB-06 #1082).

생성 스크립트 대신 손으로 유지하는 고지 파일이므로, 이 테스트가 각 정본의 런타임
의존성 이름이 고지 파일에 등장하는지 대조해 누락을 잡는다(전문 검증은 아니다 —
`docs/manifest.toml`의 `current` kind 가 문서 전체의 리뷰 drift 는 별도로 잰다).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES"


def _notices_text() -> str:
    return NOTICES.read_text(encoding="utf-8")


def test_notices_file_exists() -> None:
    assert NOTICES.is_file()


def test_python_runtime_dependencies_are_listed() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = list(pyproject["project"]["dependencies"])
    deps += list(pyproject["project"]["optional-dependencies"].get("gui", []))
    names = {re.split(r"[><=!\[; ]", d, maxsplit=1)[0] for d in deps}
    text = _notices_text().lower()
    missing = [n for n in names if n.lower() not in text]
    assert not missing, f"pyproject.toml 런타임 의존성이 고지에 없음: {missing}"


def test_npm_runtime_dependencies_are_listed() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    names = set(package.get("dependencies", {}))
    text = _notices_text().lower()
    missing = [n for n in names if n.lower() not in text]
    assert not missing, f"frontend/package.json 런타임 의존성이 고지에 없음: {missing}"


def test_rhwp_and_fonts_are_listed() -> None:
    text = _notices_text()
    for marker in ("rhwp", "Source Han Serif", "Pretendard", "OFL"):
        assert marker in text, f"{marker} 가 고지에 없음"


def test_project_license_is_referenced() -> None:
    text = _notices_text()
    assert "LICENSE" in text
    assert "MIT" in text
