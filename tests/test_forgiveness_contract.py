from _web_source import (
    SOURCE_JS_DIR,
    app_css,
    reaches_product_graph,
    source_text,
)


def _read(relative: str) -> str:
    return source_text(relative)


def test_forgiveness_surface_contracts_are_wired() -> None:
    index = _read("index.html")
    modal = _read("js/modal.js")
    editor = _read("src/screens/editor.ts")
    job = _read("js/screens/job.js")
    home = _read("src/screens/library.ts")
    # (screens/draft.js 소비자 삭제 — 「기안」 화면 사망, F6 PR-B. validate 소비는 라이브러리가 잇는다.)

    # 되돌리기 토스트가 앱 그래프에 실제로 닿는가 — R3-01(#410)에서 토스트 골격은 React
    # host 렌더 소유로 이전됐다. 정적 index.html 은 **부재**가 계약(재도입=중복 id·두 세계
    # 분열)이고, 파사드 undo_toast.js 는 여전히 제품 그래프에 닿아야 한다(렌더 존재 쪽
    # 절반은 node overlay_host.test.js + live 게이트가 진다).
    host = source_text("src", "overlay", "host.ts")
    assert 'id="undoToast"' not in index and 'id: "undoToast"' in host
    assert reaches_product_graph("undo_toast.js")
    assert 'id="jobGenCancel"' in index and '"cancel_generation"' in job
    assert '"data-act": "restore-confirmed"' in editor and '"restore_confirmed"' in editor
    # TXT 저작 모달 dirty 가드 — 소유가 편집기로 이주(F8, tpl 화면 사망). R4-02 뒤에도
    # 「닫힘을 막고 묻는다」의 거처는 그대로 `beforeClose` 다.
    assert "beforeClose" in modal and "beforeClose:" in editor
    assert "validate: opts.validate" in modal
    assert "validate: async" in home


def test_soft_delete_replaces_preconfirmation_on_recoverable_surfaces() -> None:
    library = _read("src/screens/library.ts")
    editor = _read("src/screens/editor.ts")
    # 복구 가능한 삭제 자체는 사전 확인 없음 — 라이브러리의 confirm 은 백엔드 needs_confirm
    # (타 화면 무장 세션 소실 = 파일 복원으로 못 돌아오는 파괴, #268 리뷰)이 돌려줄
    # 때만 발화한다. 무조건 confirm 재유입은 이 순서 검사가 잡는다.
    lib_block = library[library.index("async function removeJob"):
                        library.index("async function runPrimary")]
    assert "needs_confirm" in lib_block
    assert lib_block.index("needs_confirm") < lib_block.index("deps.modal.confirm")
    # 템플릿 삭제(30일 휴지통) — 거처가 편집기 「템플릿」 탭 ⋮ 로 이주(F8). 계약 불변:
    # 복구 가능한 삭제는 사전 확인 대신 UndoToast.
    start = editor.index("async function deleteLibTemplate")
    delete_block = editor[start:editor.index("deps.undo.show", start)]
    assert "modal.confirm" not in delete_block
    assert "deps.undo.show" in library and "deps.undo.show" in editor


def test_undo_toast_receives_pointer_events() -> None:
    """#269 리뷰 — 토스트는 #overlayRoot(pointer-events:none) 자식이라 auto 를 명시
    복구하지 않으면 「되돌리기」 버튼이 실클릭을 못 받는다(확인 없는 삭제의 유일한
    즉시 복구 경로 사망). 모달·ctx-menu·colpanel 과 같은 복구 규약."""
    css = "".join(app_css().split())
    assert "#overlayRoot{" in css and "pointer-events:none" in css
    toast_rule = css[css.index(".undo-toast{"):]
    toast_rule = toast_rule[:toast_rule.index("}")]
    assert "pointer-events:auto" in toast_rule


# (test_copy_fork_uses_one_composed_confirmation 삭제 — 대상(draftsession.js 「사본으로
#  편집」 fork_guard)이 「기안」 화면과 함께 사망, F6 PR-B.)


def test_confirm_inventory_is_net_lower_than_audit_ledger() -> None:
    # 원장 기준 38 미만에서 +1: 홈 삭제의 타 화면 무장 세션 가드(#268 리뷰) — 파일 복원으로
    # 못 돌아오는 세션 소실만 백엔드 needs_confirm 으로 묻는, 작업/기안 삭제 가드의 홈 패리티.
    # 새 무조건 사전 확인은 여전히 금지(위 test_soft_delete_* 가 홈 경로의 게이팅을 검사).
    #
    # +3(재작성 F6): 작업대의 ①복사 전 결손 확인 ②이탈 시 복사 진행 소실 확인 ③직접 입력
    # 값을 열 결속으로 덮을 때의 확인. 셋 다 **조건부**다 — 결손이 있을 때만, 가드가
    # 무장했을 때만, 지울 수기 값이 있을 때만 뜬다. 그리고 셋 다 「기안」 세션이 이미 갖고
    # 있던 확인의 작업대 판이라(③은 3R 에서 공용 동사를 채택하며 함께 따라왔다 — 그전엔
    # 작업대가 수기 값을 **무확인으로 덮었다**), PR-B 에서 그 화면이 죽으면 draftsession.js
    # 의 같은 확인이 걷혀 **원장은 다시 내려간다**(순증이 아니라 이사다).
    count = sum(
        path.read_text(encoding="utf-8").count("Modal.confirm({")
        for path in SOURCE_JS_DIR.rglob("*.js")
    )
    assert count < 42
