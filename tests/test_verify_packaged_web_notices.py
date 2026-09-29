"""패키징 스모크가 배포 동봉 고지 파일(LICENSE·THIRD_PARTY_NOTICES) 누락을 잡는지(FB-06 #1082).

실 PyInstaller 빌드 없이, ``verify_third_party_notices``가 bundle_root 최상단에서 두 파일을
찾는 계약만 잰다(전체 seal 대조는 ``scripts/verify_packaged_web.py`` 의 다른 경로 —
``tests/test_web_runtime_artifact.py``가 이미 커버).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from verify_packaged_web import (  # noqa: E402
    REQUIRED_NOTICE_FILES,
    WebArtifactViolation,
    verify_third_party_notices,
)


def test_passes_when_both_notice_files_present(tmp_path: Path) -> None:
    for name in REQUIRED_NOTICE_FILES:
        (tmp_path / name).write_text("stub", encoding="utf-8")
    verify_third_party_notices(tmp_path)  # 예외 없음 = 통과


@pytest.mark.parametrize("missing_name", ["LICENSE", "THIRD_PARTY_NOTICES"])
def test_fails_loudly_when_a_notice_file_is_missing(tmp_path: Path, missing_name: str) -> None:
    for name in REQUIRED_NOTICE_FILES:
        if name != missing_name:
            (tmp_path / name).write_text("stub", encoding="utf-8")
    with pytest.raises(WebArtifactViolation, match=missing_name):
        verify_third_party_notices(tmp_path)


def test_fails_when_both_notice_files_are_missing(tmp_path: Path) -> None:
    with pytest.raises(WebArtifactViolation) as excinfo:
        verify_third_party_notices(tmp_path)
    for name in REQUIRED_NOTICE_FILES:
        assert name in str(excinfo.value)
