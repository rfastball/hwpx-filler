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
    assert 'Modal.confirm({' not in home[home.index("async function deleteJob"):home.index("function onJobsClick")]
    start = template.index("async function deleteTemplate")
    delete_block = template[start:template.index("async function doCompile", start)]
    assert "Modal.confirm" not in delete_block
    assert "UndoToast.show" in home and "UndoToast.show" in template


def test_copy_fork_uses_one_composed_confirmation() -> None:
    source = _read("web/js/draftsession.js")
    start = source.index('$(id.srcFork).addEventListener')
    block = source[start:source.index('$(id.pickBtn)', start)]
    assert block.count("Modal.confirm({") == 1
    assert '"fork_guard"' in block


def test_confirm_inventory_is_net_lower_than_audit_ledger() -> None:
    count = sum(
        path.read_text(encoding="utf-8").count("Modal.confirm({")
        for path in (ROOT / "web" / "js").rglob("*.js")
    )
    assert count < 38
