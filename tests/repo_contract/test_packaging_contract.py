"""패키징 spec 계약 — 선언한 hidden import 가 **실제로 해소되는가**(N-11 · #383). [저장소 형상 계약]

``packaging/verify_specs.py`` 는 빌드 전에 도는 스크립트라 빌드를 돌리지 않는 개발 루프와
``pytest-contract`` 잡에서는 아무도 부르지 않았다. 그 사이 웹 spec 은 이미 삭제된
``hwpxfiller.gui.txt_state`` 를 hiddenimport 로 계속 선언했고, PyInstaller 는 없는 이름을
**경고로만** 넘기므로 빌드는 계속 초록이었다 — 선언은 살고 결과는 죽는 표본이다.

그래서 이 파일은 두 방향을 함께 센다: 현 저장소가 통과하는가(양성)와, 유령 이름을 심으면
실제로 거절하는가(음성). 음성 대조가 없으면 게이트가 죽어도 영영 초록이다.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

import assert_selfcheck_identity
import reconcile_shipped_copies

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
WEB_ENTRY = PACKAGING / "hwpx_filler_web_entry.py"


def _verify_specs():
    spec = importlib.util.spec_from_file_location(
        "hwpx_verify_specs_contract", PACKAGING / "verify_specs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec_sandbox(tmp_path: Path) -> Path:
    """spec 두 개와 아이콘만 옮긴 검사용 사본 — 원본을 건드리지 않고 변형한다."""
    sandbox = tmp_path / "packaging"
    sandbox.mkdir()
    for name in (*_verify_specs().SPEC_NAMES, "hwpx-filler.ico"):
        shutil.copy2(PACKAGING / name, sandbox / name)
    return sandbox


def test_spec_contract_passes_on_this_checkout() -> None:
    assert _verify_specs().main() == 0


def test_every_declared_hidden_import_resolves() -> None:
    """두 spec 의 hiddenimports 를 이름 하나씩 직접 해소해 본다.

    ``main()`` 만 보면 어떤 이름이 몇 개 검사됐는지 알 수 없다 — 목록이 비어도 통과하는
    형태였다면 초록의 의미가 달라진다. 여기서는 센 개수를 단언에 함께 싣는다.
    """
    module = _verify_specs()
    checked = 0
    for name in module.SPEC_NAMES:
        declared = module.declared_hidden_imports((PACKAGING / name).read_text(encoding="utf-8"))
        assert declared, f"{name}: hiddenimports 가 비어 있습니다"
        assert not module.unresolvable_imports(declared), f"{name}: 해소되지 않는 hidden import"
        checked += len(declared)
    assert checked >= 15, f"검사한 hidden import 가 너무 적습니다: {checked}"


def test_retired_ring1_module_is_not_declared_anywhere() -> None:
    """삭제된 링1 모듈 이름이 spec 에도 없고 임포트 그래프에도 없다(양쪽을 함께 센다)."""
    retired = "hwpxfiller.gui." + "txt_state"
    assert importlib.util.find_spec(retired) is None, (
        "이 단언의 전제가 깨졌습니다 — 모듈이 되살아났다면 spec 계약을 다시 정합니다"
    )
    for name in _verify_specs().SPEC_NAMES:
        assert retired not in (PACKAGING / name).read_text(encoding="utf-8")


def test_ghost_hidden_import_is_rejected(tmp_path: Path) -> None:
    """음성 대조 — 없는 모듈 이름을 심으면 거절한다."""
    module = _verify_specs()
    sandbox = _spec_sandbox(tmp_path)
    target = sandbox / "hwpx_filler_web.spec"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '        "openpyxl",',
            '        "hwpxfiller.gui.definitely_not_a_module",\n        "openpyxl",',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.SpecContractError) as excinfo:
        module.main(spec_dir=sandbox)
    assert "definitely_not_a_module" in str(excinfo.value)


def test_non_literal_hidden_import_is_rejected(tmp_path: Path) -> None:
    """음성 대조 — 계산된 이름은 조용히 건너뛰지 않고 거절한다.

    건너뛰면 게이트가 무엇을 셌는지 말할 수 없게 되고, 그 자리로 유령이 다시 들어온다.
    """
    module = _verify_specs()
    sandbox = _spec_sandbox(tmp_path)
    target = sandbox / "hwpx_cli.spec"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '        "openpyxl",', '        "open" + "pyxl",', 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.SpecContractError):
        module.main(spec_dir=sandbox)


def test_selfcheck_has_no_constant_verdict_variable() -> None:
    """``--selfcheck`` 의 판정은 리터럴 대입으로 만들어지지 않는다.

    ``web_ok = True`` 는 아무것도 재지 않으면서 출력·종료코드에 섞여 검증된 것처럼 보였다.
    실제 판정은 fail-closed 인 ``web_artifact()`` 가 진다 — 그 호출이 여전히 있는지도
    함께 센다(한쪽만 보면 "가짜 boolean 은 지웠는데 검증도 같이 사라진" 상태가 초록이다).
    """
    source = WEB_ENTRY.read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_selfcheck"
    )

    constants = [
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, bool)
    ]
    assert not constants, f"리터럴 boolean 으로 만든 판정 변수: {constants}"

    called = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "web_artifact" in called, "sealed artifact 검증 호출이 사라졌습니다"


def test_verify_specs_runs_as_a_script() -> None:
    """빌드 스크립트가 부르는 진입 형태(`python packaging/verify_specs.py`)도 산다."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(PACKAGING / "verify_specs.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "resolved-hidden-imports=" in result.stdout


# ---------------------------------------------------------------------------
# 환경/제품 실패 판별기(#477) — 콜드 부팅 재시도 허가의 유일한 술어
# ---------------------------------------------------------------------------


def _classifier():
    spec = importlib.util.spec_from_file_location(
        "hwpx_classify_webview_evidence_contract",
        ROOT / "scripts" / "classify_webview_evidence.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: #479 CI 실증 표본 그대로 — 자가검증 안정 코드 + 창 런타임의 부팅 실패 문장.
#: (표면 어휘 주의: 이 파일은 ⑷-전용 피해자라 ⑴⑵⑶ 낱말을 산문에 들이면 n11 대조가 죽는다.)
_BOOT_FLAKE_ERROR = (
    "자가검증 full 실패 [evaluate-failed] readiness 평가 실패: "
    "WebViewException('Main window failed to start')"
)


def test_a_cold_boot_failure_is_classified_environmental() -> None:
    """양성 — 창이 아예 안 선 실패만 재시도가 허용된다(#479 표본)."""
    environmental, reason = _classifier().classify({"error": _BOOT_FLAKE_ERROR, "runtime": {}})
    assert environmental is True, reason


def test_product_evidence_always_beats_the_boot_signature() -> None:
    """음성 대조 — 제품 결함을 환경으로 오분류하면 진짜 회귀가 재시도로 지워진다(#477).

    외부 fetch 판정·금지 자원은 창이 떠서 판정 지점까지 갔다는 제품 증거다. error 문장이
    부팅 실패와 글자까지 같아도 제품 증거가 이겨야 한다 — 이 방향의 오분류가 위험한
    방향이라, 이 대조가 판별기의 존재 이유다.
    """
    module = _classifier()
    for runtime in (
        {"external_fetch_blocked": True},
        {"external_fetch_completed": True},
        {"external_fetch_succeeded": True},
        {"forbidden_resources": ["https://example.com/x.js"]},
    ):
        environmental, reason = module.classify({"error": _BOOT_FLAKE_ERROR, "runtime": runtime})
        assert environmental is False, (runtime, reason)


def test_failures_outside_the_boot_signature_stay_product() -> None:
    """음성 대조 — 서명 밖 실패·무오류 증거는 환경이 아니다(좁게 무는 것이 계약이다)."""
    module = _classifier()
    for evidence in (
        {"error": "자가검증 full 실패 [refused] 다른 이유"},
        {"error": "readiness 평가 실패: WebViewException('Main window failed to start')"},
        {"runtime": {"external_fetch_succeeded": True}},
        {},
    ):
        environmental, reason = module.classify(evidence)
        assert environmental is False, (evidence, reason)


def test_the_classifier_cli_exit_codes_match_the_retry_contract(tmp_path) -> None:
    """build.ps1 은 exit 0 만 재시도 허가로 읽는다 — 그 경계를 CLI 층에서 고정한다.

    판정 불능(증거 부재)은 조용한 재시도 허가(0)도 제품(1)도 아니고 사유를 들고 2 로
    오른다 — 읽기 실패를 초록의 어느 쪽으로도 접지 않는다.
    """
    import json as json_mod
    import subprocess

    script = ROOT / "scripts" / "classify_webview_evidence.py"
    flake = tmp_path / "flake.json"
    flake.write_text(json_mod.dumps({"error": _BOOT_FLAKE_ERROR}), encoding="utf-8")
    product = tmp_path / "product.json"
    product.write_text(
        json_mod.dumps({"error": _BOOT_FLAKE_ERROR, "runtime": {"external_fetch_blocked": True}}),
        encoding="utf-8",
    )

    def _run(target) -> "subprocess.CompletedProcess":
        return subprocess.run(
            [sys.executable, str(script), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        )

    assert _run(flake).returncode == 0
    assert _run(product).returncode == 1
    refused = _run(tmp_path / "absent.json")
    assert refused.returncode == 2
    assert "판정 불능" in refused.stderr


def test_the_build_runner_wires_the_classifier_before_retry() -> None:
    """배선 정적 앵커 — 판별기 없는 재시도(무조건 재실행)로 퇴행하지 않는다.

    판별력 자체는 위 합성 표본이 지고, 여기는 build.ps1 이 그 판별기를 실제로 부르며
    시도 수를 유한으로 못박고 시도·오류를 진단에 계상하는지만 본다. quality.yml 층의
    「재시도 흔적 금지」는 test_quality_workflow 가 계속 지킨다 — 재시도는 이 분류 뒤에만,
    이 자리에만 산다.
    """
    build = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
    assert r"scripts\classify_webview_evidence.py" in build
    assert "$bootRetryLimit = 3" in build
    assert "webview_boot_flake" in build
    assert "boot_flake_attempts" in build
    assert "boot_flake_errors" in build
    assert build.index("classify_webview_evidence.py") < build.index("webview_boot_flake")


# --- 출하 사본 대조 (R5-03) -------------------------------------------------
#
# 종전에 이 판정은 release.yml 안의 인라인 PowerShell 이었고 태그 push 에서만 돌았다. 같은
# 판정이 패키징 게이트에도 필요해지면서 "같은 상태를 두 곳이 판정한다"가 될 자리였다 — 판정을
# 스크립트 하나로 올리고, 워크플로·러너는 호출만 한다. 그래서 검출력은 여기서 센다.


def _identity_file(path: Path, artifact_id: str, tree: str) -> Path:
    path.write_text(
        json.dumps({"artifact_id": artifact_id, "tree_sha256": tree, "same_artifact": True}),
        encoding="utf-8",
    )
    return path


def _metadata_file(path: Path, artifact_id: str, tree: str, *, present: bool = True) -> Path:
    web = {"present": present}
    if present:
        web |= {"artifact_id": artifact_id, "tree_sha256": tree}
    path.write_text(json.dumps({"version": "0.0.0", "web": web}), encoding="utf-8")
    return path


def test_reconciler_passes_when_every_shipped_copy_is_the_same(tmp_path: Path) -> None:
    identity = ("a" * 64, "b" * 64)
    evidence = reconcile_shipped_copies.reconcile(
        reconcile_shipped_copies.collect(
            copies=[
                ("dist", _identity_file(tmp_path / "dist.json", *identity)),
                ("portable", _identity_file(tmp_path / "portable.json", *identity)),
            ],
            build_metadata=_metadata_file(tmp_path / "meta.json", *identity),
        ),
        expected=("source", "dist", "portable"),
    )

    assert evidence["copies"] == ["dist", "portable", "source"]
    assert evidence["artifact_id"] == identity[0]
    assert evidence["same_artifact"] is True


def test_reconciler_names_the_copy_that_differs(tmp_path: Path) -> None:
    """사본마다 따로 통과시키는 것으로는 "하나만 다른" 경우가 안 드러난다."""
    identity = ("a" * 64, "b" * 64)
    collected = reconcile_shipped_copies.collect(
        copies=[
            ("dist", _identity_file(tmp_path / "dist.json", *identity)),
            ("portable", _identity_file(tmp_path / "portable.json", "c" * 64, identity[1])),
        ],
        build_metadata=_metadata_file(tmp_path / "meta.json", *identity),
    )

    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="artifact_id 가 다릅니다"):
        reconcile_shipped_copies.reconcile(collected, expected=("source", "dist", "portable"))


def test_a_silently_missing_copy_is_refused_not_ignored(tmp_path: Path) -> None:
    """사본 하나가 사라지면 "남은 것끼리 같다"가 아니라 빨강이어야 한다.

    이 자리가 이 스크립트의 존재 이유다 — 대조는 집합이 선언과 같을 때만 의미가 있다.
    """
    identity = ("a" * 64, "b" * 64)
    collected = reconcile_shipped_copies.collect(
        copies=[("dist", _identity_file(tmp_path / "dist.json", *identity))],
        build_metadata=_metadata_file(tmp_path / "meta.json", *identity),
    )

    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="선언과 다릅니다"):
        reconcile_shipped_copies.reconcile(collected, expected=("source", "dist", "portable"))


def test_a_repeated_copy_name_cannot_silently_replace_the_first(tmp_path: Path) -> None:
    """음성 대조 — 같은 이름의 둘째 ``--copy`` 가 첫째를 덮으면 대조가 공허해진다(L16 반증).

    호출부가 ``dict(args.copy)`` 로 접으면 서로 다른 artifact 를 가리키는 증거가 **버려지고도**
    선언 집합은 그대로 맞아 초록이 났다. 중복은 접는 것이 아니라 거절이다.
    """
    identity = ("a" * 64, "b" * 64)
    rogue = _identity_file(tmp_path / "rogue.json", "c" * 64, identity[1])
    good = _identity_file(tmp_path / "dist.json", *identity)

    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="중복됐습니다: dist"):
        reconcile_shipped_copies.collect(
            copies=[("dist", rogue), ("dist", good)],
            build_metadata=_metadata_file(tmp_path / "meta.json", *identity),
        )

    assert reconcile_shipped_copies.main(
        [
            "--copy", f"dist={rogue}",
            "--copy", f"dist={good}",
            "--build-metadata", str(tmp_path / "meta.json"),
            "--expect", "source,dist",
        ]
    ) == 2


def test_an_identity_that_is_not_a_sha256_is_refused(tmp_path: Path) -> None:
    """음성 대조 — 형태를 안 보면 두 사본이 나란히 같은 쓰레기를 들고 "일치"가 된다."""
    junk = tmp_path / "junk.json"
    junk.write_text(
        json.dumps({"artifact_id": "not-a-digest", "tree_sha256": "b" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="sha256 이 아닙니다"):
        reconcile_shipped_copies.collect(copies=[("dist", junk)], build_metadata=None)


def test_metadata_without_a_sealed_frontend_cannot_stand_in_for_source(tmp_path: Path) -> None:
    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="identity 가 없습니다"):
        reconcile_shipped_copies.collect(
            copies=[],
            build_metadata=_metadata_file(
                tmp_path / "meta.json", "a" * 64, "b" * 64, present=False
            ),
        )


def test_reconciler_cli_reports_failure_with_a_nonzero_exit(tmp_path: Path) -> None:
    identity = ("a" * 64, "b" * 64)
    _identity_file(tmp_path / "dist.json", *identity)
    _identity_file(tmp_path / "portable.json", "c" * 64, identity[1])
    _metadata_file(tmp_path / "meta.json", *identity)
    out = tmp_path / "evidence.json"

    def _run(*copies: str) -> int:
        return reconcile_shipped_copies.main(
            [
                *[argument for copy in copies for argument in ("--copy", copy)],
                "--build-metadata",
                str(tmp_path / "meta.json"),
                "--expect",
                "source,dist,portable",
                "--json-out",
                str(out),
            ]
        )

    assert _run(f"dist={tmp_path / 'dist.json'}", f"portable={tmp_path / 'portable.json'}") == 2
    assert not out.exists(), "실패한 대조가 증거 파일을 남기면 다음 단계가 그것을 읽는다"

    _identity_file(tmp_path / "portable.json", *identity)
    assert _run(f"dist={tmp_path / 'dist.json'}", f"portable={tmp_path / 'portable.json'}") == 0
    assert json.loads(out.read_text(encoding="utf-8"))["artifact_id"] == identity[0]


# --- --selfcheck 국면의 identity 판별 (R5-03) -------------------------------
#
# 판정을 PowerShell 인라인이 아니라 Python 에 둔 이유는 음성 대조가 붙을 자리를 만들기
# 위해서다. 그래서 여기가 그 검출력을 세는 자리다 — 배선은 test_web_runtime_artifact 가 진다.
#
# 입력은 **제품이 쓴 파일**이다. 초판은 stdout 을 리디렉션해 읽었는데, `console=False` exe 의
# stdout 이 붙는 자리는 환경마다 달라서 로컬에서 즉시 끝난 호출이 CI 에서 13분 매달렸다.


def _selfcheck_evidence(path: Path, artifact_id: str, tree: str) -> Path:
    path.write_text(
        json.dumps(
            {"artifact_id": artifact_id, "tree_sha256": tree, "viewmodel_ok": True}
        ),
        encoding="utf-8",
    )
    return path


def test_selfcheck_identity_reads_what_the_product_writes(tmp_path: Path) -> None:
    """양성 — 제품이 실제로 내는 형태를 읽는다.

    형태는 ``hwpx_filler_web_entry._selfcheck`` 가 정본이라, 그 키가 바뀌면 이 대조가
    먼저 죽어야 한다.
    """
    artifact_id, tree = "a" * 64, "b" * 64
    document = json.loads(
        _selfcheck_evidence(tmp_path / "selfcheck.json", artifact_id, tree).read_text(
            encoding="utf-8"
        )
    )

    assert assert_selfcheck_identity.read_identity(document, role="selfcheck") == {
        "artifact_id": artifact_id,
        "tree_sha256": tree,
    }
    assert assert_selfcheck_identity.compare(
        {"artifact_id": artifact_id, "tree_sha256": tree},
        {"artifact_id": artifact_id, "tree_sha256": tree},
    )["selfcheck_matches_bundled"] is True


def test_a_missing_or_empty_evidence_file_is_not_a_pass(tmp_path: Path) -> None:
    """음성 — 증거가 없거나 비면 통과가 아니라 실패다.

    이 자리가 초판을 태운 곳이다: 창 앱의 stdout 이 안 잡히면 파일이 **0바이트로 존재**했고,
    그 상태가 조용히 초록이면 게이트는 아무것도 재지 않으면서 확인했다고 말하게 된다.
    """
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")

    assert assert_selfcheck_identity.main(
        [
            "--selfcheck-evidence", str(tmp_path / "absent.json"),
            "--expect-identity", str(_identity_file(tmp_path / "p.json", "a" * 64, "b" * 64)),
        ]
    ) == 2
    assert assert_selfcheck_identity.main(
        [
            "--selfcheck-evidence", str(empty),
            "--expect-identity", str(tmp_path / "p.json"),
        ]
    ) == 2

    for document in ({}, {"artifact_id": "a" * 64}):
        with pytest.raises(
            assert_selfcheck_identity.SelfcheckIdentityError,
            match="identity 필드가 없습니다",
        ):
            assert_selfcheck_identity.read_identity(document, role="selfcheck")


def test_a_different_artifact_in_the_selfcheck_phase_is_named() -> None:
    """음성 — selfcheck 국면이 다른 산출물을 해석했으면 무엇이 다른지 이름을 댄다."""
    with pytest.raises(
        assert_selfcheck_identity.SelfcheckIdentityError, match="artifact_id: selfcheck="
    ):
        assert_selfcheck_identity.compare(
            {"artifact_id": "a" * 64, "tree_sha256": "b" * 64},
            {"artifact_id": "c" * 64, "tree_sha256": "b" * 64},
        )
    with pytest.raises(
        assert_selfcheck_identity.SelfcheckIdentityError, match="tree_sha256: selfcheck="
    ):
        assert_selfcheck_identity.compare(
            {"artifact_id": "a" * 64, "tree_sha256": "b" * 64},
            {"artifact_id": "a" * 64, "tree_sha256": "d" * 64},
        )


def test_an_identity_that_is_not_a_sha256_is_refused_by_the_selfcheck_judge(
    tmp_path: Path,
) -> None:
    """음성 — 형태를 안 보면 두 자리가 나란히 같은 쓰레기를 들고 "일치"가 된다."""
    with pytest.raises(
        assert_selfcheck_identity.SelfcheckIdentityError, match="sha256 이 아닙니다"
    ):
        assert_selfcheck_identity.read_identity(
            {"artifact_id": "not-a-digest", "tree_sha256": "b" * 64}, role="selfcheck"
        )


def test_selfcheck_identity_cli_exit_codes(tmp_path: Path) -> None:
    identity = ("a" * 64, "b" * 64)
    evidence = _selfcheck_evidence(tmp_path / "selfcheck.json", *identity)
    expected = _identity_file(tmp_path / "artifact-parity.json", *identity)
    out = tmp_path / "judged.json"

    assert assert_selfcheck_identity.main(
        [
            "--selfcheck-evidence", str(evidence),
            "--expect-identity", str(expected),
            "--json-out", str(out),
        ]
    ) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["selfcheck_artifact_id"] == identity[0]

    _selfcheck_evidence(evidence, "c" * 64, identity[1])
    assert assert_selfcheck_identity.main(
        [
            "--selfcheck-evidence", str(evidence),
            "--expect-identity", str(expected),
        ]
    ) == 2


def test_the_product_writes_the_evidence_the_judge_reads() -> None:
    """두 끝을 함께 센다 — 제품이 쓰는 키와 판별기가 읽는 키가 같은가.

    한쪽만 보면 "쓰는데 아무도 안 읽는" 또는 "읽는데 아무도 안 쓰는" 상태가 초록이다.
    """
    entry = WEB_ENTRY.read_text(encoding="utf-8")

    assert "HWPX_SELFCHECK_OUT" in entry, "제품이 증거 경로를 안 받습니다"
    for field in assert_selfcheck_identity.IDENTITY_FIELDS:
        assert f'"{field}": artifact.' in entry, f"제품이 {field} 를 안 씁니다"
    # stdout 은 사람이 읽는 자리로만 남는다 — 판정 입력으로 되돌아가면 같은 매달림이 돌아온다.
    assert "RedirectStandardOutput" not in (PACKAGING / "build.ps1").read_text(
        encoding="utf-8-sig"
    ), "판정이 창 앱 stdout 포획으로 되돌아갔습니다"


def test_installer_switch_is_refused_when_no_filler_bundle_is_planned() -> None:
    """요청한 사본을 못 낼 조합은 **일 시작 전에** 거절한다(Codex P2).

    ``-Target cli -IncludeInstaller`` 는 설치본이 나올 수 없는 조합인데, 스위치의 유일한
    소비 자리가 filler 분기 안이라 조용히 무시된 채 exit 0 이 났다. 그 조합으로 감사를 돌린
    사람은 **설치본을 세지 않은 초록**을 증거로 들게 된다 — 이 저장소가 금지하는 조용한
    스킵의 정확한 형태다.

    문자열 핀이 아니라 **실제로 돌려서** 센다. 거절이 uv·번들 없이도 즉시 나야 그 거절이
    "일 시작 전"이라는 주장이 성립한다.
    """
    import subprocess

    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-File", str(PACKAGING / "build.ps1"),
            "-Target", "cli", "-IncludeInstaller",
        ],
        capture_output=True,
        cwd=ROOT,
        timeout=120,
    )
    stderr = result.stderr.decode("utf-8", errors="replace")

    assert result.returncode != 0, "설치본을 못 낼 조합이 성공으로 끝났습니다"
    assert "-IncludeInstaller" in stderr, f"거절 사유가 스위치를 지목하지 않습니다: {stderr}"
    assert not (ROOT / "dist" / "hwpx-cli" / "hwpx-cli.exe.tmp").exists()


def test_the_installer_switch_still_reaches_the_filler_plan() -> None:
    """음성 대조의 짝 — 거절이 **모든** 조합을 막아 스위치가 죽지는 않았는가.

    거절만 세우면 "전부 거절"도 초록이다. filler 를 포함하는 계획에서는 스위치가 실제
    설치본 단계로 이어지는지(그 호출이 filler 분기 안에 살아 있는지) 함께 센다.
    """
    build = (PACKAGING / "build.ps1").read_text(encoding="utf-8-sig")

    guard = build.index("$IncludeInstaller -and $Target -eq 'cli'")
    call = build.index("Invoke-InstalledCopy -EvidencePath")
    assert guard < call, "거절이 사용 자리보다 뒤에 서면 일을 하고 나서 거절합니다"
    assert "if ($IncludeInstaller) {" in build, "스위치가 사용되는 자리가 사라졌습니다"


def test_the_inno_compiler_lookup_has_one_owner_and_sees_a_per_user_install() -> None:
    r"""ISCC 탐색은 한 곳이고, 사용자 범위 설치를 본다(R5-03).

    실측: ``winget install JRSoftware.InnoSetup`` 은 관리자 권한 없이
    ``%LOCALAPPDATA%\Programs\Inno Setup 6\`` 에 설치하고 PATH 에도 올리지 않는다. 종전
    탐색(PATH + ``Program Files (x86)``)은 그 기기에서 "도구가 없다"고 말했다 — 있는데 없다고
    하는 실패는 조용한 스킵만큼 나쁘다. 두 러너가 각자 탐색하면 한쪽만 고쳐지므로 소유자를
    하나로 둔다.
    """
    finder = PACKAGING / "Find-Iscc.ps1"
    finder_text = finder.read_text(encoding="utf-8-sig")
    installer = (ROOT / "package-installer.ps1").read_text(encoding="utf-8-sig")
    build = (PACKAGING / "build.ps1").read_text(encoding="utf-8-sig")

    assert "LOCALAPPDATA" in finder_text, "사용자 범위 설치 경로를 보지 않습니다"
    assert "ProgramFiles(x86)" in finder_text
    assert "Get-Command iscc.exe" in finder_text
    for consumer in (installer, build):
        assert "Find-Iscc.ps1" in consumer, "ISCC 탐색을 각자 재조립하고 있습니다"
        assert "Get-Command iscc.exe" not in consumer
