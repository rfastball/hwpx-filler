"""exact applied Candidate bytes → content-addressed read-only staging path (S4-11 #681).

legacy generator 는 template **경로**를 요구한다. mutable `Job.template_path` 를 직독하는 대신,
applied Candidate blob 의 exact bytes 를 digest 로 이름 붙인 read-only 경로에 byte-exact 로 옮겨
그 경로를 generator 에 준다. 규칙: staged bytes digest == Revision.exact_content_digest,
serialize/normalize/parse 0 회, run lifetime 동안 immutable, cleanup 은 Host lifecycle 소유.
staging path 는 identity 가 아니다 — exact digest 와 Application ID 가 provenance 다.
"""

from __future__ import annotations

import stat
from pathlib import Path

from hwpxfiller.application.candidate_revision import CandidateObjectStorePort, blob_digest

_STAGING_SUBDIR = "run_staging"
_MEDIA_EXT = {"hwpx": ".hwpx", "txt": ".txt"}


def _staging_dir(home: Path) -> Path:
    return home / _STAGING_SUBDIR


def stage_exact_applied_bytes(
    candidate_store: CandidateObjectStorePort, home: "str | Path", digest: str
) -> str:
    """digest 로 지목된 Candidate blob 을 read-only content-addressed 경로로 staging 한다.

    blob 을 읽어(get_blob 이 재해시로 손상 검출) byte-exact 로 쓰고, 쓴 뒤 재읽기 digest 를
    다시 확인한다(staging 자체가 bytes 를 바꾸지 않았음을 증명). parse/normalize 는 하지 않는다.
    """
    blob = candidate_store.get_blob(digest)  # get_blob 이 digest 재확인(손상 fail-closed)
    if blob.digest != digest:
        raise ValueError(f"blob digest {blob.digest} 가 요청 digest {digest} 와 다르다")

    staging = _staging_dir(Path(home))
    staging.mkdir(parents=True, exist_ok=True)
    ext = _MEDIA_EXT.get(blob.media, "")
    path = staging / f"{digest.replace(':', '_')}{ext}"

    # content-addressed: 같은 digest 면 같은 파일. 이미 있으면 재검증만 하고 재사용한다.
    if path.exists():
        if blob_digest(path.read_bytes()) != digest:
            _make_writable(path)
            path.write_bytes(blob.exact_bytes)
            _make_readonly(path)
    else:
        path.write_bytes(blob.exact_bytes)
        _make_readonly(path)

    if blob_digest(path.read_bytes()) != digest:  # pragma: no cover - write/read 손상 방어 post-cond
        raise ValueError("staged bytes digest 가 exact_content_digest 와 불일치")
    return str(path)


def clear_run_staging(home: "str | Path") -> None:
    """staged run input 정리 — Host lifecycle 소유(run 종료·앱 종료 시)."""
    staging = _staging_dir(Path(home))
    if not staging.exists():
        return
    for entry in staging.iterdir():
        _make_writable(entry)
        entry.unlink()


def _make_readonly(path: Path) -> None:
    path.chmod(stat.S_IREAD)


def _make_writable(path: Path) -> None:
    path.chmod(stat.S_IWRITE | stat.S_IREAD)
