"""현재 checkout의 sealed web resolver는 실제 build를 선행한 artifact job이 소유한다."""

from pathlib import Path

from hwpxfiller.web_artifact import (
    SEAL_FILENAME,
    VITE_MANIFEST_PATH,
    resolve_web_artifact,
)

ROOT = Path(__file__).resolve().parents[2]


def test_source_product_resolves_the_current_sealed_web() -> None:
    artifact = resolve_web_artifact(repo_root=ROOT)
    assert artifact.root == (ROOT / "build" / "web").resolve()
    assert artifact.index_path == (ROOT / "build" / "web" / "index.html").resolve()
    assert (artifact.root / SEAL_FILENAME).is_file()
    assert (artifact.root / VITE_MANIFEST_PATH).is_file()
