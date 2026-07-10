# -*- coding: utf-8 -*-
"""hwpx-diff.ico 생성 — 구판/신판 문서 두 장이 겹친 배지(리포트의 removed/added 팔레트).

빌드 시 1회 실행: python packaging/make_icon.py
(아이콘은 커밋하지 않고 빌드 산출물로 취급 — .spec 이 부재 시 자동 생성한다.)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).parent / "hwpx-diff.ico"

# core.diff CATEGORY_COLORS 계열(removed 빨강 / added 초록)과 같은 인상.
OLD_DOC = QColor("#c0392b")
NEW_DOC = QColor("#1e8449")
PAPER = QColor("#ffffff")


def _doc_path(x: float, y: float, w: float, h: float, fold: float) -> QPainterPath:
    """모서리 접힌 문서 실루엣."""
    p = QPainterPath()
    p.moveTo(x, y)
    p.lineTo(x + w - fold, y)
    p.lineTo(x + w, y + fold)
    p.lineTo(x + w, y + h)
    p.lineTo(x, y + h)
    p.closeSubpath()
    return p


def main() -> int:
    QApplication.instance() or QApplication(sys.argv)
    size = 256
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    # 뒤 문서(구판, 빨강 테두리) / 앞 문서(신판, 초록 테두리)
    for dx, dy, edge in ((30, 22, OLD_DOC), (86, 66, NEW_DOC)):
        path = _doc_path(dx, dy, 140, 168, 34)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawPath(path.translated(4, 5))  # 그림자
        p.setBrush(PAPER)
        pen = p.pen()
        p.setPen(edge)
        pen = p.pen()
        pen.setWidth(10)
        p.setPen(pen)
        p.drawPath(path)
        # 본문 줄 표식
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(edge.red(), edge.green(), edge.blue(), 90))
        for i in range(4):
            p.drawRoundedRect(QRectF(dx + 24, dy + 52 + i * 26, 92 - i * 14, 10), 5, 5)

    # 중앙 '±' 배지 — 추가/삭제의 diff 인상.
    p.setBrush(QColor("#2874a6"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(88, 92, 84, 84))
    f = QFont("Segoe UI", 44, QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(88, 88, 84, 84), Qt.AlignCenter, "±")
    p.end()

    ok = img.save(str(OUT), "ICO")
    print(("saved " if ok else "FAILED ") + str(OUT))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
