"""릴리스 메타데이터가 **무엇을 실었는지** 말하는가(N-11 · #383). [봉인 산출물 계약]

``build-metadata.json`` 은 릴리스와 함께 나가는 유일한 서술 자산이다. 종전에는
version/commit/python/pyinstaller 넷뿐이라, 받은 사람이 이 릴리스가 어떤 프런트 산출물을
실었는지 물을 방법이 없었다. 이제 잠금과 sealed web artifact identity 를 함께 싣는다.

여기서 세는 것은 두 가지다: 실린 값이 **seal 과 같은가**(같은 출처에서 왔는가)와,
요구했는데 없을 때 **시끄럽게 실패하는가**(조용히 빈 키로 새지 않는가).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hwpxfiller.web_artifact import SEAL_FILENAME, resolve_web_artifact

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_build_metadata.py"


def _sealed_web_document() -> dict:
    """검증된 산출물의 seal 을 중앙 resolver 를 거쳐 읽는다.

    물리 경로를 여기서 다시 조립하지 않는다(``test_web_source_role`` 계약). 그리고 sealed
    산출물은 이 suite 의 **전제**다 — ``test.ps1`` 과 CI 의 ``pytest-contract`` 가 둘 다
    pytest 앞에서 그것을 만들거나 내려받는다. 부재를 감지해 조용히 건너뛰지 않는다.
    """
    artifact = resolve_web_artifact(repo_root=ROOT)
    return json.loads((artifact.root / SEAL_FILENAME).read_text(encoding="utf-8"))


def _generator():
    spec = importlib.util.spec_from_file_location(
        "hwpx_build_metadata_contract", GENERATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generate(out: Path, *extra: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(out), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((out / "build-metadata.json").read_text(encoding="utf-8"))


def test_metadata_reports_the_sealed_frontend_it_shipped(tmp_path: Path) -> None:
    metadata = _generate(tmp_path / "version", "--require-web")
    seal = _sealed_web_document()

    assert metadata["web"]["present"] is True
    assert metadata["web"]["artifact_id"] == seal["artifact_id"]
    assert metadata["web"]["tree_sha256"] == seal["output"]["tree_sha256"]
    assert metadata["web"]["source_commit"] == seal["source"]["commit"]
    assert metadata["web"]["package_lock_sha256"] == seal["package_lock"]["sha256"]
    assert metadata["web"]["toolchain"] == seal["toolchain"]


def test_metadata_pins_the_python_lock_it_was_built_from(tmp_path: Path) -> None:
    """잠금 digest 는 실제 ``uv.lock`` 에서 온다 — 상수로 굳지 않는다."""
    import hashlib

    metadata = _generate(tmp_path / "version", "--require-web")
    expected = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()

    assert metadata["uv_lock_sha256"] == expected


def test_version_resources_still_come_from_the_single_version(tmp_path: Path) -> None:
    """버전 단일 출처(pyproject) 계약은 그대로다 — 확장이 그것을 흔들지 않았다."""
    out = tmp_path / "version"
    metadata = _generate(out, "--require-web")

    assert (out / "hwpx_filler_version.txt").is_file()
    issue = (out / "version.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{metadata["version"]}"' in issue


def test_missing_sealed_artifact_fails_loudly_when_required(tmp_path: Path) -> None:
    """음성 대조 — 요구했는데 없으면 빈 키가 아니라 실패다.

    이 게이트가 없으면 seal 이 사라진 빌드가 ``web`` 없는 메타데이터를 조용히 내고,
    받는 사람은 그것을 "프런트를 안 실은 빌드"와 구별하지 못한다.
    """
    module = _generator()
    empty_repo = tmp_path / "repo"
    (empty_repo / "build").mkdir(parents=True)

    with pytest.raises(SystemExit) as excinfo:
        module._web_metadata(empty_repo, skip_reason=None)
    assert "sealed web artifact" in str(excinfo.value)


def test_a_cli_build_records_absence_even_with_a_valid_artifact_on_disk() -> None:
    """**핵심 음성 대조** — 프런트를 싣는지는 디스크가 아니라 빌드 계획이 정한다.

    ``-Target cli`` 는 흔히 앞선 filler 빌드가 남긴 유효한 ``build/web`` 이 그대로 있는
    작업 폴더에서 돈다. 생성기가 그것을 발견해 기록하면 ``datas=[]`` 인 CLI 번들이 프런트를
    실었다고 메타데이터가 **거짓을 말한다**. 그래서 이 테스트는 산출물이 **실재하는**
    저장소 루트를 주고도 부재가 기록되는지 본다 — 빈 폴더로 물으면 이 결함을 못 잡는다.
    """
    module = _generator()
    resolve_web_artifact(repo_root=ROOT)  # 전제: 지금 이 루트에는 유효한 산출물이 있다

    web = module._web_metadata(ROOT, skip_reason="cli-only build")

    assert web["present"] is False, "CLI 빌드가 디스크의 산출물을 실었다고 주장합니다"
    assert web["reason"] == "cli-only build"
    assert "artifact_id" not in web


def test_the_build_plan_must_be_stated_not_guessed() -> None:
    """호출자가 계획을 말하지 않으면 거절한다 — 기본값은 곧 추측이다."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(ROOT / "build" / "version")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert result.returncode != 0
    assert "--require-web" in result.stderr and "--no-web" in result.stderr

    both = subprocess.run(
        [sys.executable, str(GENERATOR), "--require-web", "--no-web", "x"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert both.returncode != 0, "서로 배타적인 두 계획을 동시에 받았습니다"


def test_absence_without_a_reason_is_refused() -> None:
    """부재는 사유와 함께만 기록된다 — 빈 사유는 조용한 공백과 같다."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--no-web", "   "],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    assert result.returncode != 0
    assert "사유" in result.stderr


def test_cli_build_path_states_absence_with_a_reason() -> None:
    """`packaging/build.ps1` 의 cli 경로가 실제로 `--no-web` 을 사유와 함께 넘긴다.

    생성기만 고치고 호출부가 옛 형태로 남으면, 계약은 생겼는데 아무도 지키지 않는다.
    """
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")

    assert "'--no-web', 'cli-only build" in build
    assert "'--require-web'" in build
    assert build.index("if ($Target -eq 'cli')") < build.index("'--no-web'")


def test_metadata_names_the_runtime_it_shipped_not_only_the_tools(tmp_path: Path) -> None:
    """빌드 도구가 아니라 **출하 런타임**을 이름으로 말하는가(R5-03).

    ``toolchain`` 은 node·npm·vite — 만든 도구다. R5 이후 제품 UI 런타임은 React 이고,
    그것을 이름으로 말하지 않으면 "무엇을 실었는지 말할 수 있어야 한다"가 반만 참이다
    (해시 ``package_lock_sha256`` 는 결속하지만 이름을 말하지 않는다).

    이름은 계약 파일이 아니라 **산출물에서 유도**돼야 한다 — 그래서 여기서도 lock 과 정적
    폐포 계약 양쪽에 대조해, 셋이 어긋나면 어느 쪽이 낡았든 빨강이 되게 한다.
    """
    metadata = _generate(tmp_path / "version", "--require-web")
    shipped = metadata["web"]["runtime_packages"]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (ROOT / "tests" / "static_closure_contract.json").read_text(encoding="utf-8")
    )
    generator = _generator()
    expected_names = sorted(
        {
            generator._vendor_package_name(region.split("node_modules/", 1)[1])
            for region in contract["module_closure"]["vendor_bundle_regions"]
        }
    )

    assert sorted(shipped) == expected_names, (
        "메타데이터가 보고한 출하 런타임과 정적 폐포 계약이 다릅니다 — 둘 다 산출물에서 "
        "유도되므로 어긋났다면 한쪽이 실물을 앞질렀습니다."
    )
    assert "react" in shipped, "React 가 제품 UI 런타임이라는 사실이 서술 자산에 없습니다."
    for name, version in shipped.items():
        assert lock["packages"][f"node_modules/{name}"]["version"] == version


def test_a_shipped_runtime_package_missing_from_the_lock_is_loud(tmp_path: Path) -> None:
    """음성 대조 — lock 에 없는 이름이 출하 바이트에 있으면 조용히 넘기지 않는다."""
    generator = _generator()
    artifact_root = tmp_path / "sealed-output"
    (artifact_root / "assets").mkdir(parents=True)
    (artifact_root / "assets" / "index.js").write_text(
        "//#region node_modules/ghost-lib/index.js\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="lock 항목을 찾지 못했습니다: ghost-lib"):
        generator._shipped_runtime_packages(ROOT, artifact_root)


def test_a_bundle_without_any_runtime_boundary_is_loud(tmp_path: Path) -> None:
    """음성 대조 — 경계 주석이 사라지면(minify 유입 등) 빈 보고 대신 빨강이다.

    빈 dict 를 실어 보내면 "런타임을 안 실었다"와 "경계를 못 읽었다"가 같은 모양이 된다.
    """
    generator = _generator()
    artifact_root = tmp_path / "sealed-output"
    (artifact_root / "assets").mkdir(parents=True)
    (artifact_root / "assets" / "index.js").write_text("const a=1;\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="런타임 패키지 경계를 하나도 찾지 못했습니다"):
        generator._shipped_runtime_packages(ROOT, artifact_root)


def test_runtime_packages_are_collected_from_every_shipped_chunk(tmp_path: Path) -> None:
    """entry 하나만 읽으면 lazy 청크의 런타임이 보고에서 사라진다."""
    generator = _generator()
    artifact_root = tmp_path / "sealed-output"
    (artifact_root / "assets").mkdir(parents=True)
    (artifact_root / "assets" / "index.js").write_text(
        "//#region node_modules/react/index.js\n", encoding="utf-8"
    )
    (artifact_root / "assets" / "lazy.js").write_text(
        "//#region node_modules/scheduler/index.js\n", encoding="utf-8"
    )

    assert sorted(generator._shipped_runtime_packages(ROOT, artifact_root)) == [
        "react",
        "scheduler",
    ]


def test_the_two_region_scrapers_agree_on_crlf_and_nested_installs() -> None:
    """Python 과 JS 두 수집기가 **같은 입력에 같은 답**을 내는가(L16 반증).

    독립적으로 유도한다는 주장은 두 그물이 실제로 일치할 때만 값이 있다. 실측으로 갈렸던
    두 자리를 고정한다: ``$`` 가 ``\r`` 앞에서 안 멈추던 CRLF 산출물과, 중첩 설치를 앞의
    ``node_modules/`` 로 읽어 이름표를 잘못 달던 자리.
    """
    generator = _generator()

    crlf = "//#region node_modules/react/index.js\r\n"
    assert [
        match.group("path") for match in generator._VENDOR_REGION_RE.finditer(crlf)
    ] == ["react/index.js"], "CRLF 산출물에서 수집이 조용히 0건이 됩니다"

    assert generator._vendor_package_name(
        "react-dom/node_modules/scheduler/index.js"
    ) == "scheduler"
    assert generator._vendor_package_name("@scope/pkg/index.js") == "@scope/pkg"
    assert generator._vendor_package_name(
        "react-dom/node_modules/@scope/pkg/index.js"
    ) == "@scope/pkg"
