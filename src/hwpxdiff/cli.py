"""hwpxdiff CLI — 자동화·PR 코멘트용 diff 요약(+선택적 HTML 리포트).

    python -m hwpxdiff.cli OLD.hwpx NEW.hwpx [--html out.html]
    hwpxdiff OLD.hwpx NEW.hwpx          # console-script

GUI 는 :mod:`hwpxdiff.app` (``hwpx-diff``). ``render_html`` 은 이 CLI 전용이다 —
GUI 는 전문 신구대비표를 자체 렌더한다.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: "list[str] | None" = None) -> int:
    from .diff import diff_files, render_html, render_summary

    ap = argparse.ArgumentParser(prog="hwpxdiff")
    ap.add_argument("old", help="이전 판본 HWPX 경로")
    ap.add_argument("new", help="새 판본 HWPX 경로")
    ap.add_argument("--html", default=None, help="HTML 리포트 저장 경로")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    result = diff_files(args.old, args.new)
    print(render_summary(result), end="")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(result))
        print(f"\nHTML 리포트 저장: {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
