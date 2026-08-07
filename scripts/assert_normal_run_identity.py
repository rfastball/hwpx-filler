"""frozen 제품의 **정상(비-selftest) 국면**이 말한 web artifact identity 를 대조한다(R5-03).

「정상 실행과 selftest 는 동일 산출물이며 capability 만 다르다」는 R5-03 의 불변식이다. 그런데
frozen 쪽에서 in-process identity 를 말하는 자리는 오래도록 **시험 capability 경로 하나뿐**이었고,
정상 국면의 ``--selfcheck`` 는 같은 값을 stdout 으로 이미 내면서도 게이트가 ExitCode 만 읽어
그 줄을 버렸다. 그 줄을 듣는 것이 이 판별기다.

판정을 PowerShell 인라인이 아니라 여기 두는 이유는 **음성 대조가 붙을 자리를 만들기 위해서**다
(``classify_webview_evidence.py`` 가 같은 이유로 Python 이다). 러너가 지는 것은 호출과 배선이고,
"같은가"의 판정은 이 파일 하나가 진다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: ``hwpx_filler_web_entry._selfcheck`` 가 내는 형태. 두 값이 **한 줄에 함께** 있어야 한다 —
#: 따로 잡으면 서로 다른 실행의 값이 짝지어질 수 있다.
IDENTITY_RE = re.compile(
    r"artifact_id=(?P<artifact_id>[0-9a-f]{64}) tree_sha256=(?P<tree_sha256>[0-9a-f]{64})"
)


class NormalRunIdentityError(RuntimeError):
    """정상 국면의 identity 를 확인하지 못했다."""


def parse_identity(text: str) -> dict[str, str]:
    """selfcheck stdout 에서 identity 를 읽는다. 없음은 통과가 아니라 실패다."""
    matches = IDENTITY_RE.findall(text)
    if not matches:
        raise NormalRunIdentityError(
            "정상 실행이 자기 web artifact identity 를 말하지 않았습니다: "
            + (text.strip() or "<빈 출력>")
        )
    if len({pair for pair in matches}) != 1:
        raise NormalRunIdentityError(
            f"정상 실행 출력에 서로 다른 identity 가 {len(matches)}개 있습니다: {matches}"
        )
    artifact_id, tree_sha256 = matches[0]
    return {"artifact_id": artifact_id, "tree_sha256": tree_sha256}


def compare(actual: dict[str, str], expected: dict[str, str]) -> dict[str, object]:
    drift = [
        f"{field}: normal={actual[field]!r} bundled={expected.get(field)!r}"
        for field in ("artifact_id", "tree_sha256")
        if actual[field] != expected.get(field)
    ]
    if drift:
        raise NormalRunIdentityError(
            "정상 실행이 해석한 web artifact 가 번들 사본과 다릅니다 — " + " · ".join(drift)
        )
    return {
        "normal_run_artifact_id": actual["artifact_id"],
        "normal_run_tree_sha256": actual["tree_sha256"],
        "normal_matches_bundled": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck-output", type=Path, required=True)
    parser.add_argument(
        "--expect-identity",
        type=Path,
        required=True,
        help="verify_packaged_web.py 가 낸 번들 사본 증거 JSON",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    try:
        if not args.selfcheck_output.is_file():
            raise NormalRunIdentityError(
                f"정상 실행 출력이 없습니다: {args.selfcheck_output}"
            )
        text = args.selfcheck_output.read_text(encoding="utf-8", errors="replace")
        expected = json.loads(args.expect_identity.read_text(encoding="utf-8-sig"))
        evidence = compare(parse_identity(text), expected)
    except (OSError, json.JSONDecodeError, NormalRunIdentityError) as exc:
        print(f"normal-run identity check failed: {exc}", file=sys.stderr)
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
