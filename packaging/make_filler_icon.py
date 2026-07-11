# -*- coding: utf-8 -*-
"""hwpx-filler.ico 생성 — 누름틀 필드가 채워지는 문서(앱 B 팔레트: PRIMARY·OK·WARN).

빌드 시 1회 실행: python packaging/make_filler_icon.py
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

OUT = Path(__file__).parent / "hwpx-filler.ico"

# gui/style.py 팔레트 계열: 채움=OK(초록)·빈칸=WARN(호박)·배지=PRIMARY(파랑).
PRIMARY = QColor("#2874a6")
OK = QColor("#1e8449")
WARN = QColor("#a05a00")
PAPER = QColor("#ffffff")
BORDER = QColor("#2874a6")


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

    # 문서 한 장(누름틀 채우기의 산출물).
    path = _doc_path(52, 26, 150, 196, 38)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 40))
    p.drawPath(path.translated(5, 6))  # 그림자
    p.setBrush(PAPER)
    pen = p.pen()
    p.setPen(BORDER)
    pen = p.pen()
    pen.setWidth(10)
    p.setPen(pen)
    p.drawPath(path)

    # 필드 슬롯: 위 2개 채움(초록), 아래 1개 빈칸(호박 점선 인상) — ADR-B 3상태의 요약.
    p.setPen(Qt.NoPen)
    slots = [(OK, 1.0), (OK, 0.78), (WARN, 0.6)]
    for i, (color, frac) in enumerate(slots):
        y = 74 + i * 40
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 55))
        p.drawRoundedRect(QRectF(76, y, 100 * frac, 22), 6, 6)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(76, y, 8, 22), 3, 3)  # 필드 왼쪽 배지 바

    # 우하단 '＋' 배지 — 값 주입(채움)의 인상.
    p.setBrush(PRIMARY)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(150, 150, 82, 82))
    f = QFont("Segoe UI", 46, QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(150, 146, 82, 82), Qt.AlignCenter, "＋")
    p.end()

    ok = img.save(str(OUT), "ICO")
    print(("saved " if ok else "FAILED ") + str(OUT))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
