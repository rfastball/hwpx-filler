"""Produce the single fail-closed Vite web artifact seal for ``build/web``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwpxfiller.web_artifact import (
    SEAL_FILENAME,
    VerifiedWebArtifact,
    WebArtifactViolation,
    resolve_web_artifact,
    seal_repository_web_artifact,
)

#: identity 문서의 형식 버전. 생산자와 소비자가 **다른 job** 에서 돌므로, 형식이 바뀌었을 때
#: 없는 키끼리 조용히 같아지는 대신 시끄럽게 죽게 버전을 함께 싣는다.
IDENTITY_SCHEMA = 1

#: 두 산출물이 **같은 것**인지 판정하는 필드. 경로(`root`)는 러너마다 다르니 정체성이 아니다.
IDENTITY_FIELDS = ("artifact_id", "tree_sha256", "source_commit")


def _identity(artifact: VerifiedWebArtifact) -> dict[str, object]:
    """검증된 산출물의 **비교 가능한** 정체성.

    commit 은 seal 에서 읽는다 — 이 시점의 seal 은 이미 현재 checkout 과의 대조를 통과했으므로
    "무엇으로 만든 것인가"의 정본이다.
    """
    seal = json.loads((artifact.root / SEAL_FILENAME).read_text(encoding="utf-8"))
    return {
        "schema": IDENTITY_SCHEMA,
        "artifact_id": artifact.artifact_id,
        "tree_sha256": artifact.tree_sha256,
        "source_commit": seal["source"]["commit"],
    }


def _refuse_identity_drift(actual: dict[str, object], expected_path: Path) -> None:
    """기대한 정체성과 다르면 **무엇이 다른지 이름을 대며** 거절한다.

    무엇을 잡는지 정확히 적어 둔다 — 봉인은 트리가 **자기 자신과** 일관된지를 보고, 이
    검사는 그 트리가 **생산자가 올린 바로 그것인지**를 본다. 그래서 잡히는 것은 다운로드
    누락·부분 전송·다른 source 상태에서 만들어진 트리다.

    반대로 **잡지 못하는 것**도 적어 둔다: Vite 빌드는 같은 commit 에서 바이트 재현되므로,
    소비자가 내려받는 대신 자기가 다시 만들어도 같은 값이 나와 여기서는 통과한다. 그 축은
    수치가 아니라 구조가 닫는다 — 워크플로 계약(`tests/repo_contract/test_quality_workflow.py`)이 소비자
    job 에 빌드 흔적이 없음을 센다.
    """
    # `utf-8-sig` — 이 파일은 PowerShell 손을 거쳐 올 수 있고 PS 5.1 의 `Set-Content -Encoding
    # utf8` 은 BOM 을 붙인다. BOM 하나로 "정체성이 다르다" 대신 "JSON 이 깨졌다"가 나오면
    # 진단이 엉뚱한 자리를 가리킨다.
    expected = json.loads(expected_path.read_text(encoding="utf-8-sig"))
    if expected.get("schema") != IDENTITY_SCHEMA:
        raise WebArtifactViolation(
            f"identity schema mismatch: expected={IDENTITY_SCHEMA} "
            f"actual={expected.get('schema')!r} ({expected_path})"
        )
    drift = [
        f"{field}: producer={expected.get(field)!r} local={actual[field]!r}"
        for field in IDENTITY_FIELDS
        if expected.get(field) != actual[field]
    ]
    if drift:
        raise WebArtifactViolation("web artifact identity mismatch — " + " · ".join(drift))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--node-command")
    parser.add_argument("--npm-command")
    parser.add_argument("--vite-command")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the existing source-checkout build/web seal without invoking build tools",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="write the artifact identity (artifact_id/tree_sha256/source_commit) as JSON",
    )
    parser.add_argument(
        "--expect-identity",
        type=Path,
        help="refuse unless this artifact matches the given producer identity JSON",
    )
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if any((args.node_command, args.npm_command, args.vite_command)):
                parser.error("tool command overrides cannot be used with --verify")
            artifact = resolve_web_artifact(repo_root=args.repo_root)
        else:
            artifact = seal_repository_web_artifact(
                args.repo_root,
                node_command=args.node_command,
                npm_command=args.npm_command,
                vite_command=args.vite_command,
            )
        identity = _identity(artifact)
        if args.expect_identity is not None:
            _refuse_identity_drift(identity, args.expect_identity)
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, WebArtifactViolation) as exc:
        print(f"web artifact seal failed: {exc}", file=sys.stderr)
        return 2
    print(f"artifact_id={identity['artifact_id']}")
    print(f"tree_sha256={identity['tree_sha256']}")
    print(f"source_commit={identity['source_commit']}")
    print(f"root={artifact.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
