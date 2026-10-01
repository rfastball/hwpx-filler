"""패키징 스모크가 배포 동봉 고지 파일 누락을 잡는지(FB-06 #1082, #1107).

실 PyInstaller 빌드 없이, ``verify_third_party_notices``가 bundle_root 에서 고지 파일
(LICENSE·THIRD_PARTY_NOTICES·licenses/ 원문 동봉본)을 찾는 계약만 잰다(전체 seal 대조는
``scripts/verify_packaged_web.py`` 의 다른 경로 — ``tests/test_web_runtime_artifact.py``가
이미 커버).
"""

from __future__ import annotations

import ast
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


def _write(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")


def test_passes_when_all_notice_files_present(tmp_path: Path) -> None:
    _write(tmp_path, REQUIRED_NOTICE_FILES)
    verify_third_party_notices(tmp_path)  # 예외 없음 = 통과


@pytest.mark.parametrize("missing_name", REQUIRED_NOTICE_FILES)
def test_fails_loudly_when_a_notice_file_is_missing(tmp_path: Path, missing_name: str) -> None:
    _write(tmp_path, tuple(name for name in REQUIRED_NOTICE_FILES if name != missing_name))
    with pytest.raises(WebArtifactViolation, match=missing_name):
        verify_third_party_notices(tmp_path)


def test_fails_when_all_notice_files_are_missing(tmp_path: Path) -> None:
    with pytest.raises(WebArtifactViolation) as excinfo:
        verify_third_party_notices(tmp_path)
    for name in REQUIRED_NOTICE_FILES:
        assert name in str(excinfo.value)


def _spec_datas_destinations() -> set[str]:
    """web spec 의 ``Analysis(datas=[...])`` 가 싣는 고지 파일의 번들 상대 경로."""
    spec = (ROOT / "packaging" / "hwpx_filler_web.spec").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(spec)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Analysis":
            datas = next(k.value for k in node.keywords if k.arg == "datas")
            break
    else:  # pragma: no cover - spec 구조가 바뀌면 시끄럽게
        raise AssertionError("Analysis(datas=...) 를 찾지 못했습니다")
    destinations: set[str] = set()
    for element in datas.elts:
        source, dest = element.elts
        if not (isinstance(dest, ast.Constant) and isinstance(dest.value, str)):
            continue
        # 원천의 마지막 경로 조각(파일 이름)만 읽는다 — 변수(PYTHON_LICENSE)는 LICENSE.txt.
        constants = sorted(
            (n for n in ast.walk(source) if isinstance(n, ast.Constant)),
            key=lambda n: (n.lineno, n.col_offset),
        )
        filename = str(constants[-1].value) if constants else "LICENSE.txt"
        destinations.add(filename if dest.value == "." else f"{dest.value}/{filename}")
    return destinations


def test_every_required_notice_is_shipped_by_the_web_spec() -> None:
    """검사가 요구하는 경로와 spec 이 싣는 경로가 한 목록에서 어긋나지 않는다."""
    missing = sorted(set(REQUIRED_NOTICE_FILES) - _spec_datas_destinations())
    assert not missing, f"spec datas 가 싣지 않는 고지 파일을 요구함: {missing}"
