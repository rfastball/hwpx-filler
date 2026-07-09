"""얇은 CLI — 자동화·수동 검증용.

    python -m hwpxfiller.cli --template T.hwpx --data data.xlsx --out ./out \
        --pattern "공고서-{{계약명}}"
    python -m hwpxfiller.cli --template T.hwpx --fields   # 요구 필드만 출력
    python -m hwpxfiller.cli diff OLD.hwpx NEW.hwpx [--html out.html]  # 개정 비교
"""

from __future__ import annotations

import argparse
import sys

from .batch import generate_batch
from .core.engine import HwpxEngine
from .core.validate import validate
from .data.excel import ExcelDataSource


def _diff_main(argv: "list[str]") -> int:
    """``diff`` 하위명령 — 두 HWPX 를 비교해 요약 출력, 선택적 HTML 저장."""
    from .core.diff import diff_files, render_html, render_summary

    ap = argparse.ArgumentParser(prog="hwpxfiller diff")
    ap.add_argument("old", help="이전 판본 HWPX 경로")
    ap.add_argument("new", help="새 판본 HWPX 경로")
    ap.add_argument("--html", default=None, help="HTML 리포트 저장 경로")
    args = ap.parse_args(argv)

    result = diff_files(args.old, args.new)
    print(render_summary(result), end="")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(result))
        print(f"\nHTML 리포트 저장: {args.html}", file=sys.stderr)
    return 0


def main(argv: "list[str] | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff":
        return _diff_main(argv[1:])

    ap = argparse.ArgumentParser(prog="hwpxfiller")
    ap.add_argument("--template", required=True, help="HWPX 템플릿 경로")
    ap.add_argument("--data", help="엑셀/CSV 데이터 경로")
    ap.add_argument("--out", default="./out", help="결과 저장 폴더")
    ap.add_argument("--pattern", default="output-{{ID}}", help="파일명 패턴({{키}})")
    ap.add_argument("--sheet", default=None, help="엑셀 시트명(기본: 첫 시트)")
    ap.add_argument("--fields", action="store_true", help="템플릿 요구 필드만 출력")
    args = ap.parse_args(argv)

    engine = HwpxEngine()

    if args.fields:
        for f in engine.required_fields(args.template):
            print(f)
        return 0

    if not args.data:
        ap.error("--data 가 필요합니다 (또는 --fields 사용)")

    src = ExcelDataSource(args.data, sheet=args.sheet)
    records = src.records()

    report = validate(engine.required_fields(args.template), records)
    if report.missing_columns:
        print(f"[경고] 데이터에 없는 필드(빈칸 생성): {', '.join(report.missing_columns)}",
              file=sys.stderr)
    if report.empty_valued:
        print(f"[경고] 값이 비어있는 필드: {', '.join(report.empty_valued)}", file=sys.stderr)

    batch = generate_batch(args.template, records, args.out, args.pattern, engine)
    print(f"완료: {batch.succeeded}/{batch.total} 성공 -> {args.out}")
    for res in batch.results:
        if not res.ok:
            print(f"  [실패] {res.output_path}: {res.error}", file=sys.stderr)
    return 0 if batch.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
