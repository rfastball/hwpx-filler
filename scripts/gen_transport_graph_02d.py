"""P1-02D transport 원장 생성기 CLI — 02A 생성기와 같은 4단 규약의 입구(#516).

기본 실행은 재생성(rewrite), ``--check`` 는 드리프트 검사만 한다. 판정 본문은
``scripts/factgraph/transport_graph.py`` 가 소유하고 게이트 테스트가 같은 함수를 직접 부른다.

런타임 프로브(``WebFrontend`` 헤드리스 인스턴스)의 홈 격리는 transport_graph 자신이
``HWPXFILLER_HOME`` 임시 폴더로 진다 — 이 CLI 는 경로 정비만 한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))  # 계측 대상 = 이 저장소의 src (설치본 아님)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factgraph import transport_graph  # noqa: E402 — sys.path 정비 뒤에 import 한다


def main(argv: "list[str] | None" = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="P1-02D transport 원장 생성/검사")
    parser.add_argument("--check", action="store_true", help="재생성 없이 드리프트만 검사한다")
    args = parser.parse_args(argv)
    if args.check:
        problems = transport_graph.check(_REPO_ROOT)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print(f"{transport_graph.LEDGER_REL_PATH}: 드리프트 없음")
        return 0
    target = transport_graph.rewrite(_REPO_ROOT)
    print(f"재생성: {target.relative_to(_REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
