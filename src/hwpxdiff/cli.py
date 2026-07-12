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
    """CLI 진입점 — 일상 실패(부재·손상 파일)를 traceback 대신 한국어 1줄로 번역(RC-16).

    판본을 **분리 로드**해 실패 시 구판/신판 어느 쪽이 문제인지 지목한다. 크래시성
    실패는 exit 2 — 빈 추출 게이트(exit 1)·정상 비교(exit 0)와 종료코드로 구분한다.
    """
    from zipfile import BadZipFile

    from hwpxcore.text_extract import extract_document

    from .diff import EmptyExtractionError, diff_documents, render_html, render_summary

    ap = argparse.ArgumentParser(prog="hwpxdiff")
    ap.add_argument("old", help="구판 HWPX 경로")
    ap.add_argument("new", help="신판 HWPX 경로")
    ap.add_argument("--html", default=None, help="HTML 리포트 저장 경로")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    docs = []
    for label, path in (("구판", args.old), ("신판", args.new)):
        try:
            docs.append(extract_document(path))
        except (OSError, BadZipFile) as exc:
            print(f"[오류] {label} 파일을 열 수 없습니다: {path} — {exc}", file=sys.stderr)
            return 2

    try:
        result = diff_documents(docs[0], docs[1])
    except EmptyExtractionError as exc:
        # 빈 컨테이너 쌍을 '(변경 없음)' + exit 0 으로 삼키지 않는다(거짓 음성 게이트).
        print(f"오류: {exc} ({args.old} ↔ {args.new})", file=sys.stderr)
        return 1
    print(render_summary(result), end="")
    if args.html:
        from hwpxcore.atomic import write_text_atomic

        try:
            # 렌더를 **저장 전에 선평가**하고 원자 쓰기로 교체한다(RC-01) — 실패가
            # 기존 리포트를 truncate 로 파괴하지 않고, 쓰기 실패는 번역한다(RC-16).
            write_text_atomic(args.html, render_html(result))
        except OSError as exc:
            print(f"[오류] HTML 리포트를 쓸 수 없습니다: {args.html} — {exc}", file=sys.stderr)
            return 2
        print(f"\nHTML 리포트 저장: {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
