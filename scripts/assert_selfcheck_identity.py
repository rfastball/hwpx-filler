"""frozen 번들의 ``--selfcheck`` 국면이 해석한 web artifact identity 를 대조한다(R5-03).

**이 판별기가 재는 국면을 정확히 적는다.** ``--selfcheck`` 는 제품 ``main()`` 을 부르지 않는다
— ``packaging/hwpx_filler_web_entry.py`` 가 그 인자 하나만 가로채 헤드리스 스모크
(``_selfcheck``)로 보낸다. 즉 여기서 얻는 것은 「정상 실행의 증거」가 아니라 **창을 열지 않는
별개 프로세스가 같은 sealed 산출물을 fail-closed 로 해석했다**는 증거다.

제품 진입점(``main()``)이 해석한 identity 는 이미 다른 자리가 대조한다 — ``--selftest`` 실행이
``main()`` 을 지나고, 그 증거의 ``runtime.artifact_id`` 를 패키징 게이트가 번들 사본과 맞춘다.
정상/시험 창의 capability 차는 source 실창 게이트(``tests/test_web_selftest_gate.py``)가 진다.
이 셋은 겹치지 않는 국면이고, 이름으로 서로를 대신하지 않는다.

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


class SelfcheckIdentityError(RuntimeError):
    """``--selfcheck`` 국면의 identity 를 확인하지 못했다."""


def parse_identity(text: str) -> dict[str, str]:
    """selfcheck stdout 에서 identity 를 읽는다. 없음은 통과가 아니라 실패다."""
    matches = IDENTITY_RE.findall(text)
    if not matches:
        raise SelfcheckIdentityError(
            "selfcheck 가 자기 web artifact identity 를 말하지 않았습니다: "
            + (text.strip() or "<빈 출력>")
        )
    if len(set(matches)) != 1:
        raise SelfcheckIdentityError(
            f"selfcheck 출력에 서로 다른 identity 가 {len(matches)}개 있습니다: {matches}"
        )
    artifact_id, tree_sha256 = matches[0]
    return {"artifact_id": artifact_id, "tree_sha256": tree_sha256}


def compare(actual: dict[str, str], expected: dict[str, str]) -> dict[str, object]:
    drift = [
        f"{field}: selfcheck={actual[field]!r} bundled={expected.get(field)!r}"
        for field in ("artifact_id", "tree_sha256")
        if actual[field] != expected.get(field)
    ]
    if drift:
        raise SelfcheckIdentityError(
            "selfcheck 가 해석한 web artifact 가 번들 사본과 다릅니다 — " + " · ".join(drift)
        )
    return {
        "selfcheck_artifact_id": actual["artifact_id"],
        "selfcheck_tree_sha256": actual["tree_sha256"],
        "selfcheck_matches_bundled": True,
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
            raise SelfcheckIdentityError(
                f"selfcheck 출력이 없습니다: {args.selfcheck_output}"
            )
        text = args.selfcheck_output.read_text(encoding="utf-8", errors="replace")
        expected = json.loads(args.expect_identity.read_text(encoding="utf-8-sig"))
        evidence = compare(parse_identity(text), expected)
    except (OSError, json.JSONDecodeError, SelfcheckIdentityError) as exc:
        print(f"selfcheck identity check failed: {exc}", file=sys.stderr)
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
