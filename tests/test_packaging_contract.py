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
import shutil
import sys
from pathlib import Path

import pytest

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
        declared = module.declared_hidden_imports(
            (PACKAGING / name).read_text(encoding="utf-8")
        )
        assert declared, f"{name}: hiddenimports 가 비어 있습니다"
        assert not module.unresolvable_imports(declared), (
            f"{name}: 해소되지 않는 hidden import"
        )
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
