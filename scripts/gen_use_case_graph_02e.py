"""P1-02E use-case·test responsibility 원장 생성기 CLI — 4단 규약(02A 생성기와 동형)의 입구.

기본 실행은 재생성(rewrite), ``--check`` 는 드리프트 검사만 한다. 판정 본문은
``scripts/factgraph/use_case_graph.py`` 가 소유하고 게이트 테스트가 같은 함수를 직접 부른다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factgraph import use_case_graph  # noqa: E402 — sys.path 정비 뒤에 import 한다


def main(argv: "list[str] | None" = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="P1-02E use-case 원장 생성/검사")
    parser.add_argument("--check", action="store_true", help="재생성 없이 드리프트만 검사한다")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    if args.check:
        problems = use_case_graph.check(repo_root)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print(f"{use_case_graph.LEDGER_REL_PATH}: 드리프트 없음")
        return 0
    target = use_case_graph.rewrite(repo_root)
    print(f"재생성: {target.relative_to(repo_root).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
