"""Compare the source Vite artifact with a PyInstaller bundled web tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwpxfiller.web_artifact import WebArtifactViolation, resolve_web_artifact

#: 배포본에 함께 실려야 하는 법적 고지 — PyInstaller datas(``packaging/hwpx_filler_web.spec``)가
#: bundle_root 에 싣는다(FB-06 #1082, 사용자 확정: 파일 동봉만·앱 내 표면 없음).
#: ``licenses/`` 아래는 THIRD_PARTY_NOTICES 가 가리키는 원문 동봉본이다(#1107).
REQUIRED_NOTICE_FILES: tuple[str, ...] = (
    "LICENSE",
    "THIRD_PARTY_NOTICES",
    "licenses/rhwp/LICENSE.txt",
    "licenses/rhwp/THIRD_PARTY_LICENSES.txt",
    "licenses/rhwp/FONTS.txt",
    "licenses/rhwp/SourceHanSerifK-OFL.txt",
    "licenses/rhwp/canvaskit-wasm-LICENSE.txt",
    "licenses/pretendard/OFL.txt",
    "licenses/python/LICENSE.txt",
)


def verify_third_party_notices(bundle_root: Path) -> None:
    """번들에 LICENSE·THIRD_PARTY_NOTICES 와 고지 원문 동봉본이 실제로 있는지 확인한다.

    누락은 조용한 성공이 아니라 :class:`WebArtifactViolation`이다 — 앱 산출물 검증과
    같은 실패 어휘를 쓴다.
    """
    missing = [name for name in REQUIRED_NOTICE_FILES if not (bundle_root / name).is_file()]
    if missing:
        raise WebArtifactViolation(
            f"bundle is missing required notice files: {', '.join(missing)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        required=True,
        help="PyInstaller _MEIPASS root containing exactly one sealed web/ tree",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    try:
        source = resolve_web_artifact(repo_root=args.repo_root)
        bundled = resolve_web_artifact(frozen_root=args.bundle_root)
        if (
            source.artifact_id != bundled.artifact_id
            or source.tree_sha256 != bundled.tree_sha256
        ):
            raise WebArtifactViolation(
                "source and bundled web artifacts do not have the same identity"
            )
        verify_third_party_notices(args.bundle_root)
    except (OSError, WebArtifactViolation) as exc:
        print(f"packaged web verification failed: {exc}", file=sys.stderr)
        return 2

    evidence = {
        "artifact_id": source.artifact_id,
        "tree_sha256": source.tree_sha256,
        "source_root": str(source.root),
        "bundled_root": str(bundled.root),
        "same_artifact": True,
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
