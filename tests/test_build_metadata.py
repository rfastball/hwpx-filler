"""릴리스 메타데이터가 **무엇을 실었는지** 말하는가(N-11 · #383).

``build-metadata.json`` 은 릴리스와 함께 나가는 유일한 서술 자산이다. 종전에는
version/commit/python/pyinstaller 넷뿐이라, 받은 사람이 이 릴리스가 어떤 프런트 산출물을
실었는지 물을 방법이 없었다. 이제 잠금과 sealed web artifact identity 를 함께 싣는다.

여기서 세는 것은 두 가지다: 실린 값이 **seal 과 같은가**(같은 출처에서 왔는가)와,
요구했는데 없을 때 **시끄럽게 실패하는가**(조용히 빈 키로 새지 않는가).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hwpxfiller.web_artifact import SEAL_FILENAME, resolve_web_artifact

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_build_metadata.py"


def _sealed_web_document() -> dict:
    """검증된 산출물의 seal 을 중앙 resolver 를 거쳐 읽는다.

    물리 경로를 여기서 다시 조립하지 않는다(``test_web_source_role`` 계약). 그리고 sealed
    산출물은 이 suite 의 **전제**다 — ``test.ps1`` 과 CI 의 ``pytest-contract`` 가 둘 다
    pytest 앞에서 그것을 만들거나 내려받는다. 부재를 감지해 조용히 건너뛰지 않는다.
    """
    artifact = resolve_web_artifact(repo_root=ROOT)
    return json.loads((artifact.root / SEAL_FILENAME).read_text(encoding="utf-8"))


def _generator():
    spec = importlib.util.spec_from_file_location(
        "hwpx_build_metadata_contract", GENERATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generate(out: Path, *extra: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(out), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((out / "build-metadata.json").read_text(encoding="utf-8"))


def test_metadata_reports_the_sealed_frontend_it_shipped(tmp_path: Path) -> None:
    metadata = _generate(tmp_path / "version", "--require-web")
    seal = _sealed_web_document()

    assert metadata["web"]["present"] is True
    assert metadata["web"]["artifact_id"] == seal["artifact_id"]
    assert metadata["web"]["tree_sha256"] == seal["output"]["tree_sha256"]
    assert metadata["web"]["source_commit"] == seal["source"]["commit"]
    assert metadata["web"]["package_lock_sha256"] == seal["package_lock"]["sha256"]
    assert metadata["web"]["toolchain"] == seal["toolchain"]


def test_metadata_pins_the_python_lock_it_was_built_from(tmp_path: Path) -> None:
    """잠금 digest 는 실제 ``uv.lock`` 에서 온다 — 상수로 굳지 않는다."""
    import hashlib

    metadata = _generate(tmp_path / "version", "--require-web")
    expected = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()

    assert metadata["uv_lock_sha256"] == expected


def test_version_resources_still_come_from_the_single_version(tmp_path: Path) -> None:
    """버전 단일 출처(pyproject) 계약은 그대로다 — 확장이 그것을 흔들지 않았다."""
    out = tmp_path / "version"
    metadata = _generate(out)

    assert (out / "hwpx_filler_version.txt").is_file()
    issue = (out / "version.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{metadata["version"]}"' in issue


def test_missing_sealed_artifact_fails_loudly_when_required(tmp_path: Path) -> None:
    """음성 대조 — 요구했는데 없으면 빈 키가 아니라 실패다.

    이 게이트가 없으면 seal 이 사라진 빌드가 ``web`` 없는 메타데이터를 조용히 내고,
    받는 사람은 그것을 "프런트를 안 실은 빌드"와 구별하지 못한다.
    """
    module = _generator()
    empty_repo = tmp_path / "repo"
    (empty_repo / "build").mkdir(parents=True)

    with pytest.raises(SystemExit) as excinfo:
        module._web_metadata(empty_repo, required=True)
    assert "sealed web artifact" in str(excinfo.value)


def test_absent_artifact_is_recorded_with_a_reason_when_not_required(
    tmp_path: Path,
) -> None:
    """CLI 전용 빌드의 부재는 정상이지만 **사유와 함께** 기록된다(조용한 공백 금지)."""
    module = _generator()
    empty_repo = tmp_path / "repo"
    (empty_repo / "build").mkdir(parents=True)

    web = module._web_metadata(empty_repo, required=False)

    assert web["present"] is False
    assert web["reason"], "부재에 사유가 없습니다"
