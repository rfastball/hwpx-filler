# -*- coding: utf-8 -*-
"""hwpx-diff.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 GUI(main) 그대로. ``--selfcheck 구판 신판`` 만 예외로, 패키징된 환경에서
코어 diff 경로(zip 읽기 → lxml 파싱 → HTML 렌더)가 실제로 도는지 헤드리스로
검증한다 — 빌드 산출물 스모크 테스트용(CI·수동 공용).
"""
from __future__ import annotations

import sys


def _selfcheck(old: str, new: str) -> int:
    from hwpxdiff.app import _render_doc_html
    from hwpxdiff.diff import diff_files

    result = diff_files(old, new)
    html = _render_doc_html(result.rows)
    ok = len(result.change_items) > 0 and len(result.rows) > len(result.changes) \
        and "chg-" in html
    print(f"selfcheck: change_items={len(result.change_items)} "
          f"rows={len(result.rows)} html={len(html)}B -> {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck(sys.argv[2], sys.argv[3]))
    from hwpxdiff.app import main

    raise SystemExit(main())
