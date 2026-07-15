# -*- coding: utf-8 -*-
"""hwpx-diff.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 pywebview GUI(main). ``--selfcheck 구판 신판`` 만 예외로, 프리즈 번들에서 브리지·
컨트롤러·비교 엔진·번들 web-diff/ 가 실제로 도는지 **헤드리스로**(창 없이) 검증한다 —
빌드 산출물 스모크 테스트용(CI·수동 공용). WebView2 창을 띄우는 부팅 자가검증은
``hwpxdiff.webapp.app --selftest`` 가 담당한다.
"""
from __future__ import annotations

import sys


def _selfcheck(old: str, new: str) -> int:
    from hwpxdiff.webapp.app import web_dir
    from hwpxdiff.webapp.screen_diff import DiffController

    pushes: list = []
    ctrl = DiffController(lambda s, snap: pushes.append(snap))
    ctrl.load_old_path(old)
    ctrl.load_new_path(new)
    ctrl.compare_sync()  # 워커 우회 동기 비교 → 마지막 push 가 결과 스냅샷
    snap = pushes[-1]
    vm_ok = (
        snap.get("has_result")
        and snap.get("change_count", 0) > 0
        and len(snap.get("rows", [])) > snap["change_count"]  # equal 포함 전문 스트림
        and snap.get("groups")
        and snap["groups"][0].get("seq") is not None          # 앵커 표적
    )
    web_ok = (web_dir() / "index.html").exists()  # 번들 web-diff/ 확인(동결 시 _MEIPASS/web-diff)

    print(
        f"selfcheck: change_count={snap.get('change_count')} rows={len(snap.get('rows', []))} "
        f"groups={len(snap.get('groups', []))} web_ok={web_ok} "
        f"-> {'OK' if vm_ok and web_ok else 'FAIL'}"
    )
    return 0 if (vm_ok and web_ok) else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck(sys.argv[2], sys.argv[3]))
    from hwpxdiff.webapp.app import main

    raise SystemExit(main())
