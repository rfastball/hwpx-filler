from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_forgiveness_surface_contracts_are_wired() -> None:
    index = _read("web/index.html")
    modal = _read("web/js/modal.js")
    editor = _read("web/js/screens/editor.js")
    job = _read("web/js/screens/job.js")
    template = _read("web/js/screens/template.js")
    home = _read("web/js/screens/home.js")
    draft = _read("web/js/screens/draft.js")

    assert 'id="undoToast"' in index and 'src="js/undo_toast.js"' in index
    assert 'id="jobGenCancel"' in index and '"cancel_generation"' in job
    assert 'data-act="restore-confirmed"' in editor and '"restore_confirmed"' in editor
    assert "beforeClose" in modal and "beforeClose:" in template
    assert "validate: opts.validate" in modal
    assert "validate: async" in home and "validate: async" in draft


def test_soft_delete_replaces_preconfirmation_on_recoverable_surfaces() -> None:
    home = _read("web/js/screens/home.js")
    template = _read("web/js/screens/template.js")
    # 복구 가능한 삭제 자체는 사전 확인 없음 — 홈의 confirm 은 백엔드 needs_confirm
    # (타 화면 무장 세션 소실 = 파일 복원으로 못 돌아오는 파괴, #268 리뷰)이 돌려줄
    # 때만 발화한다. 무조건 confirm 재유입은 이 순서 검사가 잡는다.
    home_block = home[home.index("async function deleteJob"):home.index("function onJobsClick")]
    assert "needs_confirm" in home_block
    assert home_block.index("needs_confirm") < home_block.index("Modal.confirm")
    start = template.index("async function deleteTemplate")
    delete_block = template[start:template.index("async function doCompile", start)]
    assert "Modal.confirm" not in delete_block
    assert "UndoToast.show" in home and "UndoToast.show" in template


def test_undo_toast_receives_pointer_events() -> None:
    """#269 리뷰 — 토스트는 #overlayRoot(pointer-events:none) 자식이라 auto 를 명시
    복구하지 않으면 「되돌리기」 버튼이 실클릭을 못 받는다(확인 없는 삭제의 유일한
    즉시 복구 경로 사망). 모달·ctx-menu·colpanel 과 같은 복구 규약."""
    css = "".join(_read("web/css/app.css").split())
    assert "#overlayRoot{" in css and "pointer-events:none" in css
    toast_rule = css[css.index(".undo-toast{"):]
    toast_rule = toast_rule[:toast_rule.index("}")]
    assert "pointer-events:auto" in toast_rule


def test_copy_fork_uses_one_composed_confirmation() -> None:
    source = _read("web/js/draftsession.js")
    start = source.index('$(id.srcFork).addEventListener')
    block = source[start:source.index('$(id.pickBtn)', start)]
    assert block.count("Modal.confirm({") == 1
    assert '"fork_guard"' in block


def test_confirm_inventory_is_net_lower_than_audit_ledger() -> None:
    # 원장 기준 38 미만에서 +1: 홈 삭제의 타 화면 무장 세션 가드(#268 리뷰) — 파일 복원으로
    # 못 돌아오는 세션 소실만 백엔드 needs_confirm 으로 묻는, 작업/기안 삭제 가드의 홈 패리티.
    # 새 무조건 사전 확인은 여전히 금지(위 test_soft_delete_* 가 홈 경로의 게이팅을 검사).
    count = sum(
        path.read_text(encoding="utf-8").count("Modal.confirm({")
        for path in (ROOT / "web" / "js").rglob("*.js")
    )
    assert count < 39
