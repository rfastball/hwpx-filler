"""출하 사본들의 web artifact identity 를 **한자리에 놓고** 대조한다(R5-03).

사본을 각각 통과시키는 것만으로는 "어느 한 사본만 다른" 경우가 드러나지 않는다. 종전에는 그
대조가 ``release.yml`` 안의 인라인 PowerShell 이었고, 같은 판정이 패키징 게이트에도 필요해지자
두 곳이 같은 상태를 판정할 자리가 생겼다. 판정은 여기 하나이고 워크플로·러너는 호출만 한다.

호출자는 **어떤 사본이 있어야 하는가**를 ``--expect`` 로 선언한다. 선언과 실제가 다르면 거절이다
— 사본 하나가 조용히 빠진 채 "남은 것끼리 같다"로 초록이 나는 길을 막는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

#: 사본 하나를 "같은 것"으로 판정하는 필드. 경로는 러너마다 다르니 정체성이 아니다.
IDENTITY_FIELDS = ("artifact_id", "tree_sha256")

#: 두 필드의 **형태**. 값이 있기만 하면 통과시키면 빈 문자열 아닌 무엇이든 identity 가 되고,
#: 두 사본이 나란히 같은 쓰레기를 들면 "일치"가 나온다.
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ReconcileError(RuntimeError):
    """출하 사본 대조가 실패했다."""


def _load(path: Path, *, role: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"{role} 증거를 읽을 수 없습니다: {path} ({exc})") from exc
    if not isinstance(value, dict):
        raise ReconcileError(f"{role} 증거가 JSON object 가 아닙니다: {path}")
    return value


def _identity(document: dict, *, role: str) -> dict[str, str]:
    missing = [field for field in IDENTITY_FIELDS if not document.get(field)]
    if missing:
        raise ReconcileError(f"{role} 증거에 identity 필드가 없습니다: {', '.join(missing)}")
    identity = {field: str(document[field]) for field in IDENTITY_FIELDS}
    malformed = [field for field, value in identity.items() if not _DIGEST_RE.match(value)]
    if malformed:
        raise ReconcileError(
            f"{role} 증거의 identity 형태가 sha256 이 아닙니다: "
            + ", ".join(f"{field}={identity[field]!r}" for field in malformed)
        )
    return identity


def collect(
    *,
    copies: "Sequence[tuple[str, Path]]",
    build_metadata: Path | None,
) -> dict[str, dict[str, str]]:
    """이름 → identity. ``build_metadata`` 는 ``source`` 사본을 기여한다."""
    collected: dict[str, dict[str, str]] = {}
    if build_metadata is not None:
        metadata = _load(build_metadata, role="build metadata")
        web = metadata.get("web")
        if not isinstance(web, dict) or not web.get("present"):
            raise ReconcileError(
                "build metadata 에 sealed web artifact identity 가 없습니다 "
                f"({build_metadata})"
            )
        collected["source"] = _identity(web, role="source")
    for name, path in copies:
        if name in collected:
            raise ReconcileError(f"사본 이름이 중복됐습니다: {name}")
        collected[name] = _identity(_load(path, role=name), role=name)
    return collected


def reconcile(
    collected: dict[str, dict[str, str]],
    *,
    expected: tuple[str, ...],
) -> dict[str, object]:
    actual = tuple(sorted(collected))
    if actual != tuple(sorted(expected)):
        raise ReconcileError(
            "대조할 사본 집합이 선언과 다릅니다 — "
            f"선언={list(sorted(expected))} 실제={list(actual)}"
        )
    for field in IDENTITY_FIELDS:
        values = {identity[field] for identity in collected.values()}
        if len(values) != 1:
            raise ReconcileError(
                f"출하 사본들의 {field} 가 다릅니다: "
                + json.dumps(collected, ensure_ascii=False, sort_keys=True)
            )
    reference = collected[actual[0]]
    return {
        "copies": list(actual),
        "artifact_id": reference["artifact_id"],
        "tree_sha256": reference["tree_sha256"],
        "same_artifact": True,
    }


def _copy_argument(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError(f"--copy 는 NAME=PATH 형식입니다: {value}")
    return name, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--copy",
        action="append",
        default=[],
        type=_copy_argument,
        metavar="NAME=PATH",
        help="verify_packaged_web.py 가 낸 사본 증거 JSON",
    )
    parser.add_argument(
        "--build-metadata",
        type=Path,
        help="build-metadata.json — 그 안의 web identity 가 source 사본이 된다",
    )
    parser.add_argument(
        "--expect",
        required=True,
        help="쉼표로 구분한, 반드시 있어야 하는 사본 이름 전수",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    expected = tuple(name.strip() for name in args.expect.split(",") if name.strip())
    if not expected:
        parser.error("--expect 에는 사본 이름이 하나 이상 필요합니다")

    try:
        # `dict(args.copy)` 로 접으면 같은 이름의 둘째 `--copy` 가 첫째를 **조용히
        # 덮어써서** 중복 가드가 영영 안 문다(L16 반증: 다른 artifact 를 가리키는 증거가
        # 버려지고도 초록이었다). 목록 그대로 넘겨 `collect` 가 세게 한다.
        collected = collect(
            copies=args.copy,
            build_metadata=args.build_metadata,
        )
        evidence = reconcile(collected, expected=expected)
    except ReconcileError as exc:
        print(f"shipped copy reconciliation failed: {exc}", file=sys.stderr)
        return 2

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
