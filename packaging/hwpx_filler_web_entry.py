# -*- coding: utf-8 -*-
"""hwpx-filler-web.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 pywebview GUI(main). ``--selfcheck`` 만 예외로, 프리즈 번들에서 브리지·화면 컨트롤러·
링1 VM·sealed web artifact가 실제로 도는지 **헤드리스로**(창 없이) 검증한다 — 빌드 산출물 스모크
테스트용(CI·수동 공용). WebView2 창을 띄우는 부팅 자가검증은 ``app.py --selftest`` 가 담당한다.
"""
from __future__ import annotations

import sys


def _selfcheck() -> int:
    import tempfile
    from pathlib import Path

    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.core.text_registry import TextTemplateRegistry
    from hwpxfiller.gui.template_manager_state import TemplateManagerViewModel
    from hwpxfiller.webapp.app import web_artifact
    from hwpxfiller.webapp.screen_editor import EditorController

    tmp = Path(tempfile.mkdtemp())
    (tmp / "샘플.txt").write_text("제목: {{공고명}} / 담당: {{담당자}}", encoding="utf-8")

    pushes: list = []
    # 편집기 TXT 매체 분기(F6 PR-B — 구 「기안」 스모크의 승계처)로 스모크한다: 번들에서
    # 브리지 없는 컨트롤러+링1 VM(스키마 동형 성형)이 실제로 도는지를 TXT 로드 한 바퀴로 본다.
    ctrl = EditorController(
        JobRegistry(tmp / "jobs"),
        lambda s, snap: pushes.append((s, snap)),
        template_library=TemplateManagerViewModel(paths=[]),
        text_registry=TextTemplateRegistry(tmp),
    )
    ctrl.dispatch("use_library_template", {"path": str(tmp / "샘플.txt")})
    snap = ctrl.snapshot()
    txt_names = [
        it["name"] for sec in snap["library"]["txt"]["sections"] for it in sec["items"]
    ]
    vm_ok = (
        "샘플" in txt_names
        and snap["sections"] == ["template", "binding"]
        and any(f["name"] == "공고명" for f in snap["fields"])
    )

    # ``web_artifact()`` 는 fail-closed 다 — seal 과 전체 트리 검증에 실패하면 값을 돌려주는
    # 대신 예외를 던진다. 그래서 여기 도달했다는 것 자체가 판정이고, 별도 boolean 을 두면
    # 선언만 살고 결과가 죽는다(#383: 종전 ``web_ok = True`` 는 아무것도 재지 않았다).
    # 검증된 identity 를 그대로 실어 무엇이 번들에 실렸는지 로그가 말하게 한다.
    artifact = web_artifact()

    print(
        f"selfcheck: txt_templates={txt_names} fields={len(snap['fields'])} "
        f"artifact_id={artifact.artifact_id} "
        f"tree_sha256={artifact.tree_sha256} -> {'OK' if vm_ok else 'FAIL'}"
    )
    return 0 if vm_ok else 1


if __name__ == "__main__":
    # 포터블 zip self-unblock — webview(pythonnet/.NET) 임포트 전에 번들 MOTW 를 지운다.
    from hwpxcore.motw import unblock_bundle

    unblock_bundle()

    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck())
    from hwpxfiller.webapp.app import main

    raise SystemExit(main())
