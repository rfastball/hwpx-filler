"""tmp_path fixture로 gen_studio_runtime_manifest.py의 줄끝 독립성을 검증한다.

--check는 내용(파싱된 JSON)을 비교해야 하며, 트래킹된 매니페스트가 LF든 CRLF든
Studio 출력과 같은 내용이면 통과해야 한다. --write는 항상 LF·끝 개행 1개로 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from scripts import gen_studio_runtime_manifest as manifest_script


def _write_studio_output(studio_dir: Path) -> None:
    studio_dir.mkdir(parents=True)
    (studio_dir / "index.html").write_bytes(b"<html></html>\n")
    (studio_dir / "app.js").write_bytes(b"window.boot = () => 'ready';\n")


class Repo(NamedTuple):
    manifest: dict[str, object]
    manifest_path: Path


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    (tmp_path / "vendor" / "rhwp").mkdir(parents=True)
    (tmp_path / "vendor" / "rhwp" / "source.json").write_text(
        json.dumps({"commit": "a" * 40}), encoding="utf-8"
    )
    studio_dir = tmp_path / "build" / "rhwp" / "studio"
    _write_studio_output(studio_dir)
    manifest_path = tmp_path / "vendor" / "rhwp" / "studio-runtime.json"

    monkeypatch.setattr(manifest_script, "ROOT", tmp_path)
    monkeypatch.setattr(manifest_script, "SOURCE", tmp_path / "vendor" / "rhwp" / "source.json")
    monkeypatch.setattr(manifest_script, "OUTPUT_DIR", studio_dir)
    monkeypatch.setattr(manifest_script, "MANIFEST", manifest_path)
    monkeypatch.setattr(sys, "argv", ["gen_studio_runtime_manifest.py"])

    manifest = manifest_script.build_manifest(studio_dir, "a" * 40)
    return Repo(manifest=manifest, manifest_path=manifest_path)


def test_check_passes_when_tracked_manifest_is_lf(repo: Repo) -> None:
    text = json.dumps(repo.manifest, indent=2) + "\n"
    repo.manifest_path.write_bytes(text.encode("utf-8"))

    sys.argv.append("--check")
    assert manifest_script.main() == 0


def test_check_passes_when_tracked_manifest_is_crlf(repo: Repo) -> None:
    """줄끝만 다르고 내용이 같으면 --check는 통과해야 한다 (결함 재현 케이스)."""
    text = json.dumps(repo.manifest, indent=2) + "\n"
    crlf_text = text.replace("\n", "\r\n")
    repo.manifest_path.write_bytes(crlf_text.encode("utf-8"))

    sys.argv.append("--check")
    assert manifest_script.main() == 0


def test_check_fails_when_content_differs(repo: Repo) -> None:
    changed = dict(repo.manifest)
    changed["source_commit"] = "b" * 40
    text = json.dumps(changed, indent=2) + "\n"
    repo.manifest_path.write_bytes(text.encode("utf-8"))

    sys.argv.append("--check")
    assert manifest_script.main() == 1


def test_write_output_is_lf_with_single_trailing_newline(repo: Repo) -> None:
    assert manifest_script.main() == 0

    raw = repo.manifest_path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    # 파싱 가능한 유효 JSON이어야 한다.
    json.loads(raw.decode("utf-8"))
