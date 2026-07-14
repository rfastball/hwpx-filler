# -*- coding: utf-8 -*-
"""hwpx-filler-web.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 pywebview GUI(main). ``--selfcheck`` 만 예외로, 프리즈 번들에서 브리지·화면 컨트롤러·
링1 VM·번들 web/ 가 실제로 도는지 **헤드리스로**(창 없이) 검증한다 — 빌드 산출물 스모크
테스트용(CI·수동 공용). WebView2 창을 띄우는 부팅 자가검증은 ``app.py --selftest`` 가 담당한다.
"""
from __future__ import annotations

import sys


def _selfcheck() -> int:
    import tempfile
    from pathlib import Path

    from hwpxfiller.core.text_registry import TextTemplateRegistry
    from hwpxfiller.webapp.app import web_dir
    from hwpxfiller.webapp.screens import TxtController

    tmp = Path(tempfile.mkdtemp())
    (tmp / "샘플.txt").write_text("제목: {{공고명}} / 담당: {{담당자}}", encoding="utf-8")

    pushes: list = []
    ctrl = TxtController(TextTemplateRegistry(tmp), lambda s, snap: pushes.append((s, snap)))
    init = ctrl.initial()
    vm_ok = "샘플" in init["templates"] and any(t["name"] == "공고명" for t in init["tokens"])

    web_ok = (web_dir() / "index.html").exists()  # 번들 web/ 확인(동결 시 _MEIPASS/web)

    print(
        f"selfcheck: templates={init['templates']} tokens={len(init['tokens'])} "
        f"web_ok={web_ok} -> {'OK' if vm_ok and web_ok else 'FAIL'}"
    )
    return 0 if (vm_ok and web_ok) else 1


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck())
    from hwpxfiller.webapp.app import main

    raise SystemExit(main())
