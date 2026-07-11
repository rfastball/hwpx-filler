# -*- coding: utf-8 -*-
"""hwpx-filler.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 GUI(main) 그대로. ``--selfcheck`` 만 예외로, 패키징된 환경에서 앱 B 의 핵심
의존(PySide6 + openpyxl + hwpxcore)과 매핑 엔진 경로가 실제로 도는지 헤드리스로 검증한다
— 빌드 산출물 스모크 테스트용(CI·수동 공용). 인자 없이 돈다(템플릿 불필요).
"""
from __future__ import annotations

import os
import sys


def _selfcheck() -> int:
    import tempfile
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # Qt 번들 확인

    QApplication.instance() or QApplication([])

    import openpyxl  # 데이터 레이어(엑셀) 번들 확인

    from hwpxfiller.core.job import Job, RunRequest
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile
    from hwpxfiller.data.excel import ExcelDataSource

    tmp = Path(tempfile.mkdtemp())
    xlsx = tmp / "sc.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["공고명", "추정가격"])
    ws.append(["전산장비 구매", "1000"])
    wb.save(xlsx)

    src = ExcelDataSource(str(xlsx))
    recs = src.records()
    job = Job(
        name="selfcheck",
        template_path="",
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", sources=["공고명"]),
        ]),
    )
    mapped = RunRequest(job, src, [0]).mapped_records()
    ok = (
        recs == [{"공고명": "전산장비 구매", "추정가격": "1000"}]
        and bool(mapped) and mapped[0].get("공고명") == "전산장비 구매"
    )

    # txt 트랙(대시보드·즉시 기안)이 프리즈 번들에 실제로 들어갔는지 + 렌더 경로 확인.
    from hwpxfiller.core.text_render import render_record
    from hwpxfiller.core.text_registry import TextTemplateRegistry  # noqa: F401
    from hwpxfiller.gui.txt_view import TxtDraftView  # noqa: F401  (번들 확인)

    txt, _report = render_record("제목: {{공고명}} / 담당: {{담당자}}", {"공고명": "전산장비 구매"})
    txt_ok = "전산장비 구매" in txt and "{{담당자}}" in txt  # 값 치환 + 미입력 토큰 유지
    ok = ok and txt_ok

    print(
        f"selfcheck: records={len(recs)} mapped={mapped[0] if mapped else None} "
        f"txt_ok={txt_ok} -> {'OK' if ok else 'FAIL'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck())
    from hwpxfiller.gui.app import main

    raise SystemExit(main())
