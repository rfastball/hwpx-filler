"""패키징 spec 계약 — 선언한 hidden import 가 **실제로 해소되는가**(N-11 · #383).

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

import assert_normal_run_identity
import reconcile_shipped_copies

ROOT = Path(__file__).resolve().parents[1]
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
            copies={
                "dist": _identity_file(tmp_path / "dist.json", *identity),
                "portable": _identity_file(tmp_path / "portable.json", *identity),
            },
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
        copies={
            "dist": _identity_file(tmp_path / "dist.json", *identity),
            "portable": _identity_file(tmp_path / "portable.json", "c" * 64, identity[1]),
        },
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
        copies={"dist": _identity_file(tmp_path / "dist.json", *identity)},
        build_metadata=_metadata_file(tmp_path / "meta.json", *identity),
    )

    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="선언과 다릅니다"):
        reconcile_shipped_copies.reconcile(collected, expected=("source", "dist", "portable"))


def test_metadata_without_a_sealed_frontend_cannot_stand_in_for_source(tmp_path: Path) -> None:
    with pytest.raises(reconcile_shipped_copies.ReconcileError, match="identity 가 없습니다"):
        reconcile_shipped_copies.collect(
            copies={},
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


# --- 정상 실행 국면의 identity 판별 (R5-03) ---------------------------------
#
# 판정을 PowerShell 인라인이 아니라 Python 에 둔 이유는 음성 대조가 붙을 자리를 만들기
# 위해서다. 그래서 여기가 그 검출력을 세는 자리다 — 배선은 test_web_runtime_artifact 가 진다.


def test_normal_run_identity_accepts_the_real_selfcheck_line() -> None:
    """양성 — 제품이 실제로 내는 형태를 읽는다.

    형태는 ``hwpx_filler_web_entry._selfcheck`` 의 print 문이 정본이라, 그 문자열이 바뀌면
    이 대조가 먼저 죽어야 한다.
    """
    artifact_id, tree = "a" * 64, "b" * 64
    line = (
        f"selfcheck: txt_templates=['샘플'] fields=2 artifact_id={artifact_id} "
        f"tree_sha256={tree} -> OK\n"
    )

    assert assert_normal_run_identity.parse_identity(line) == {
        "artifact_id": artifact_id,
        "tree_sha256": tree,
    }
    assert assert_normal_run_identity.compare(
        {"artifact_id": artifact_id, "tree_sha256": tree},
        {"artifact_id": artifact_id, "tree_sha256": tree},
    )["normal_matches_bundled"] is True


def test_silence_is_not_a_pass() -> None:
    """음성 — 값을 못 읽으면 통과가 아니라 실패다.

    창 앱이라 리디렉션을 빠뜨리면 출력이 통째로 사라진다. 그 상태가 조용히 초록이면 이
    게이트는 아무것도 재지 않으면서 "정상 실행을 확인했다"고 말하게 된다.
    """
    for empty in ("", "   \n", "selfcheck: txt_templates=['샘플'] fields=2 -> OK\n"):
        with pytest.raises(
            assert_normal_run_identity.NormalRunIdentityError,
            match="identity 를 말하지 않았습니다",
        ):
            assert_normal_run_identity.parse_identity(empty)


def test_a_different_artifact_in_the_normal_run_is_named(tmp_path: Path) -> None:
    """음성 — 정상 국면이 다른 산출물을 해석했으면 무엇이 다른지 이름을 댄다."""
    with pytest.raises(
        assert_normal_run_identity.NormalRunIdentityError, match="artifact_id: normal="
    ):
        assert_normal_run_identity.compare(
            {"artifact_id": "a" * 64, "tree_sha256": "b" * 64},
            {"artifact_id": "c" * 64, "tree_sha256": "b" * 64},
        )
    with pytest.raises(
        assert_normal_run_identity.NormalRunIdentityError, match="tree_sha256: normal="
    ):
        assert_normal_run_identity.compare(
            {"artifact_id": "a" * 64, "tree_sha256": "b" * 64},
            {"artifact_id": "a" * 64, "tree_sha256": "d" * 64},
        )


def test_two_different_identities_in_one_output_are_refused() -> None:
    """음성 — 한 출력에 값이 둘이면 어느 실행의 값인지 말할 수 없다.

    앞 시도의 잔재가 남은 파일에 이어 붙는 경우가 실제 형태다. 첫 매치를 조용히 택하면
    이번 실행이 아닌 값이 대조를 통과한다.
    """
    stale = f"artifact_id={'a' * 64} tree_sha256={'b' * 64}\n"
    fresh = f"artifact_id={'c' * 64} tree_sha256={'d' * 64}\n"

    with pytest.raises(
        assert_normal_run_identity.NormalRunIdentityError, match="서로 다른 identity"
    ):
        assert_normal_run_identity.parse_identity(stale + fresh)


def test_normal_run_identity_cli_exit_codes(tmp_path: Path) -> None:
    identity = ("a" * 64, "b" * 64)
    output = tmp_path / "selfcheck.txt"
    output.write_text(
        f"selfcheck: artifact_id={identity[0]} tree_sha256={identity[1]} -> OK\n",
        encoding="utf-8",
    )
    expected = tmp_path / "artifact-parity.json"
    expected.write_text(
        json.dumps({"artifact_id": identity[0], "tree_sha256": identity[1]}),
        encoding="utf-8",
    )
    evidence = tmp_path / "normal.json"

    assert assert_normal_run_identity.main(
        [
            "--selfcheck-output", str(output),
            "--expect-identity", str(expected),
            "--json-out", str(evidence),
        ]
    ) == 0
    assert json.loads(evidence.read_text(encoding="utf-8"))["normal_run_artifact_id"] == identity[0]

    assert assert_normal_run_identity.main(
        [
            "--selfcheck-output", str(tmp_path / "absent.txt"),
            "--expect-identity", str(expected),
        ]
    ) == 2


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
