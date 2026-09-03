# -*- coding: utf-8 -*-
"""hwpx-filler-web.exe 엔트리 — 패키징 전용 래퍼(앱 코드 무변경).

기본은 pywebview GUI(main). ``--selfcheck`` 만 예외로, 프리즈 번들에서 브리지·화면 컨트롤러·
링1 VM·sealed web artifact가 실제로 도는지 **헤드리스로**(창 없이) 검증한다 — 빌드 산출물 스모크
테스트용(CI·수동 공용). WebView2 창을 띄우는 부팅 자가검증은 ``app.py --selftest`` 가 담당한다.
"""
from __future__ import annotations

import sys


def viewmodel_smoke(tmp) -> "tuple[bool, list[str], int]":
    """번들에서 **화면 컨트롤러 두 개와 링1 VM 이 실제로 도는가** — 창 없이 한 바퀴.

    ``(vm_ok, txt_names, field_count)`` 을 돌려준다. 순수 파이썬이라 `--selfcheck` 밖에서도
    부를 수 있고, 그것이 요점이다: 이 스모크가 읽는 **스냅샷 계약**이 갈리면
    ``tests/repo_contract`` 가 순수 레인에서 먼저 빨강이 된다. 종전에는 이 함수가 `--selfcheck`
    안에만 살아서, U6-B 가 편집기 스냅샷의 ``library`` 존을 퇴역시켰을 때 **아무 게이트도
    보지 못했다** — Ruff·pytest 는 `packaging/` 을 안 보고(CLAUDE.md), 실제로 그 KeyError 는
    창 없는 exe 의 예외 대화상자로 나타나 CI 잡을 30분 상한까지 매달았다.

    목록의 정본은 U6-B 이후 ``tpl`` 채널이고, 그 채널 안의 자리는 **고르기 열 존**
    (``column``) 하나다 — 매체별 밴드(``hwpx``/``txt``)는 웹 소비자 0 으로 걷혔다. 그래서
    여기서도 그 존을 읽는다(제품이 읽는 자리를 그대로 읽는다).
    """
    from datetime import datetime

    from hwpxfiller.external.dataset_store import DatasetPoolRegistry
    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.external.template_files import TemplateFileStore
    from hwpxfiller.external.template_root import TemplateRoot
    from hwpxfiller.external.text_registry import TextTemplateRegistry
    from hwpxfiller.webapp.screen_editor import EditorController
    from hwpxfiller.webapp.screen_template import TemplateController

    tmp.mkdir(parents=True, exist_ok=True)   # 호출자가 만든 자리든 아니든 여기서 선다
    (tmp / "샘플.txt").write_text("제목: {{공고명}} / 담당: {{담당자}}", encoding="utf-8")

    root = TemplateRoot(default_root=tmp)
    registry = TextTemplateRegistry(root.path)
    # 좌 열 목록의 정본(U6-B #976) — 링1 행 성형(`TemplateRow.from_text`)까지 여기서 돈다.
    tpl = TemplateController(
        registry,
        lambda screen, snap: None,
        file_store=TemplateFileStore(root.path, registry),
        template_root=root,
        pool_registry=DatasetPoolRegistry(tmp / "datasets"),
    )
    txt_names = [
        row["name"] for row in tpl.snapshot()["column"]["rows"] if row["icon"] == "txt"
    ]

    # 편집기 TXT 매체 분기(F6 PR-B — 구 「기안」 스모크의 승계처): 브리지 없는 컨트롤러 +
    # 링1 VM(스키마 동형 성형)이 실제로 도는지를 TXT 로드 한 바퀴로 본다.
    ctrl = EditorController(
        JobRegistry(tmp / "jobs"),
        lambda screen, snap: None,
        clock=datetime.now,
        # 라이브러리 소속 관문은 `tpl` 채널 하나다(U6-E #979) — 편집기는 자기 VM 도 자기 TXT
        # 레지스트리도 들지 않는다. 제품 조립(app.py)이 넘기는 것과 **같은 메서드**를 준다.
        is_library_path=tpl.is_live_path,
        template_root=root,
    )
    ctrl.dispatch("use_library_template", {"path": str(tmp / "샘플.txt")})
    snap = ctrl.snapshot()
    vm_ok = (
        "샘플" in txt_names
        # TXT 도 3단계다(U6-D #978) — 셋째가 「이름·저장」이 되면서 매체가 정하는 것은
        # 단계가 아니라 그 안의 문서 파일 이름 행 하나로 좁아졌다.
        and snap["sections"] == ["template", "binding", "filename"]
        and any(f["name"] == "공고명" for f in snap["fields"])
        # 고르기 단계의 연결 카드(U6-B) — 템플릿만 골랐으니 짝은 아직 서지 않고, 사유는
        # 링1 문안 그대로다. 존이 사라지거나 모양이 갈리면 여기서 잡힌다. 이름은
        # **표시명**이다(U6-D): 루트 상대·확장자 없음 — 좌 열 목록이 부르는 그 이름.
        and snap["pairing"]["template_name"] == "샘플"
        and snap["pairing"]["ready"] is False
        # 이름 기본값 도출(U6-D) — 데이터가 아직 없으니 템플릿 표시명 하나다.
        and snap["name"] == "샘플"
        and snap["job_name_is_derived"] is True
    )
    return vm_ok, txt_names, len(snap["fields"])


def _selfcheck() -> int:
    import os
    import tempfile
    from pathlib import Path

    from hwpxfiller.webapp.app import web_artifact

    tmp = Path(tempfile.mkdtemp())
    vm_ok, txt_names, field_count = viewmodel_smoke(tmp)

    # ``web_artifact()`` 는 fail-closed 다 — seal 과 전체 트리 검증에 실패하면 값을 돌려주는
    # 대신 예외를 던진다. 그래서 여기 도달했다는 것 자체가 판정이고, 별도 boolean 을 두면
    # 선언만 살고 결과가 죽는다(#383: 종전 ``web_ok = True`` 는 아무것도 재지 않았다).
    # 검증된 identity 를 그대로 실어 무엇이 번들에 실렸는지 로그가 말하게 한다.
    artifact = web_artifact()

    # 게이트가 읽는 것은 **파일**이지 stdout 이 아니다. 이 exe 는 `console=False` 라 stdout 이
    # 붙는 자리가 환경마다 다르고, 실제로 CI 에서 `Start-Process -RedirectStandardOutput` 이
    # 13분 매달렸다(로컬은 같은 호출이 즉시 끝났다 — 이 축은 기기마다 다르게 틀린다).
    # selftest 가 `HWPX_SELFTEST_OUT` 으로 증거를 내는 것과 같은 형태로 맞춘다.
    # print 는 사람이 읽는 자리로 남긴다 — 판정 입력이 아니다.
    evidence_path = os.environ.get("HWPX_SELFCHECK_OUT")
    if evidence_path:
        import json

        target = Path(evidence_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "artifact_id": artifact.artifact_id,
                    "tree_sha256": artifact.tree_sha256,
                    "viewmodel_ok": vm_ok,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        f"selfcheck: txt_templates={txt_names} fields={field_count} "
        f"artifact_id={artifact.artifact_id} "
        f"tree_sha256={artifact.tree_sha256} -> {'OK' if vm_ok else 'FAIL'}"
    )
    return 0 if vm_ok else 1


def _selfcheck_guarded() -> int:
    """스모크의 **예외를 유한한 실패로** 바꾼다 — 창 없는 exe 는 매달리면 안 된다.

    이 exe 는 ``console=False`` 라 처리되지 않은 예외가 PyInstaller 의 traceback **대화상자**로
    뜬다. 아무도 누를 수 없는 그 창은 프로세스를 영영 붙들고, 호출자(`packaging/build.ps1` 의
    ``Start-Process -Wait``)에는 시한이 없어 CI 잡 상한(30분)이 유일한 그물이 된다 — 실측으로
    한 번 그렇게 취소됐다(KeyError 하나가 29분 침묵으로 나타났다).

    사유는 증거 파일과 stderr **둘 다**에 남긴다: 파일은 게이트가 읽고 stderr 는 사람이 읽는다.
    """
    import os
    import traceback

    try:
        return _selfcheck()
    except BaseException:  # noqa: BLE001 — 창 없는 프로세스의 마지막 그물(대화상자 금지)
        detail = traceback.format_exc()
        evidence_path = os.environ.get("HWPX_SELFCHECK_OUT")
        if evidence_path:
            import json
            from pathlib import Path

            try:
                target = Path(evidence_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(
                        {"error": detail, "viewmodel_ok": False},
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001 — 증거를 못 써도 종료는 해야 한다
                pass
        sys.stderr.write(detail)
        sys.stderr.flush()
        return 2


if __name__ == "__main__":
    # 포터블 zip self-unblock — webview(pythonnet/.NET) 임포트 전에 번들 MOTW 를 지운다.
    from hwpxfiller.host.motw import unblock_bundle

    unblock_bundle()

    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        raise SystemExit(_selfcheck_guarded())
    from hwpxfiller.webapp.app import main

    raise SystemExit(main())
