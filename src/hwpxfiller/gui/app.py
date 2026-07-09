"""GUI 진입점 — 매핑 위저드를 기동한다.

    python -m hwpxfiller.gui.app

단순 창(main_window.MainWindow)은 매핑 없는 직결 흐름용으로 유지된다.
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .wizard import MappingWizard

    app = QApplication(sys.argv)
    wiz = MappingWizard()
    wiz.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
