"""frozen 번들의 ``--selfcheck`` 국면이 해석한 web artifact identity 를 대조한다(R5-03).

**이 판별기가 재는 국면을 정확히 적는다.** ``--selfcheck`` 는 제품 ``main()`` 을 부르지 않는다
— ``packaging/hwpx_filler_web_entry.py`` 가 그 인자 하나만 가로채 헤드리스 스모크
(``_selfcheck``)로 보낸다. 즉 여기서 얻는 것은 「정상 실행의 증거」가 아니라 **창을 열지 않는
별개 프로세스가 같은 sealed 산출물을 fail-closed 로 해석했다**는 증거다.

제품 진입점(``main()``)이 해석한 identity 는 이미 다른 자리가 대조한다 — ``--selftest`` 실행이
``main()`` 을 지나고, 그 증거의 ``runtime.artifact_id`` 를 패키징 게이트가 번들 사본과 맞춘다.
정상/시험 창의 capability 차는 source 실창 게이트(``tests/test_web_selftest_gate.py``)가 진다.
이 셋은 겹치지 않는 국면이고, 이름으로 서로를 대신하지 않는다.

입력은 **제품이 쓴 파일**이지 stdout 이 아니다. 이 exe 는 ``console=False`` 라 stdout 이 붙는
자리가 환경마다 다르고, 초판이 쓰던 ``Start-Process -RedirectStandardOutput`` 은 로컬에서 즉시
끝나면서 CI 에서 13분 매달렸다 — 같은 축을 selftest 는 이미 파일(``HWPX_SELFTEST_OUT``)로
피해 가고 있었다. 판별기가 stdout 을 안 읽으면 그 축이 통째로 사라진다.

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

#: identity 두 필드의 형태. 있기만 하면 통과시키면 빈 문자열 아닌 무엇이든 identity 가 된다.
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

IDENTITY_FIELDS = ("artifact_id", "tree_sha256")


class SelfcheckIdentityError(RuntimeError):
    """``--selfcheck`` 국면의 identity 를 확인하지 못했다."""


def _load(path: Path, *, role: str) -> dict:
    if not path.is_file():
        raise SelfcheckIdentityError(f"{role} 증거가 없습니다: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelfcheckIdentityError(f"{role} 증거를 읽을 수 없습니다: {path} ({exc})") from exc
    if not isinstance(value, dict):
        raise SelfcheckIdentityError(f"{role} 증거가 JSON object 가 아닙니다: {path}")
    return value


def read_identity(document: dict, *, role: str) -> dict[str, str]:
    """증거에서 identity 를 읽는다. 없음·형태 불일치는 통과가 아니라 실패다."""
    missing = [field for field in IDENTITY_FIELDS if not document.get(field)]
    if missing:
        raise SelfcheckIdentityError(
            f"{role} 증거에 identity 필드가 없습니다: {', '.join(missing)}"
        )
    identity = {field: str(document[field]) for field in IDENTITY_FIELDS}
    malformed = [field for field, value in identity.items() if not _DIGEST_RE.match(value)]
    if malformed:
        raise SelfcheckIdentityError(
            f"{role} 증거의 identity 형태가 sha256 이 아닙니다: "
            + ", ".join(f"{field}={identity[field]!r}" for field in malformed)
        )
    return identity


def compare(actual: dict[str, str], expected: dict[str, str]) -> dict[str, object]:
    drift = [
        f"{field}: selfcheck={actual[field]!r} bundled={expected.get(field)!r}"
        for field in IDENTITY_FIELDS
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
    parser.add_argument(
        "--selfcheck-evidence",
        type=Path,
        required=True,
        help="frozen --selfcheck 가 HWPX_SELFCHECK_OUT 으로 쓴 JSON",
    )
    parser.add_argument(
        "--expect-identity",
        type=Path,
        required=True,
        help="verify_packaged_web.py 가 낸 번들 사본 증거 JSON",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    try:
        actual = read_identity(
            _load(args.selfcheck_evidence, role="selfcheck"), role="selfcheck"
        )
        expected = read_identity(
            _load(args.expect_identity, role="bundled"), role="bundled"
        )
        evidence = compare(actual, expected)
    except SelfcheckIdentityError as exc:
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
