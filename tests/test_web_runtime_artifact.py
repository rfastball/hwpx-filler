"""N-03 제품 runtime이 sealed build/web 하나만 소비하는 중앙 seam 계약."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from _web_source import source_text
from hwpxfiller.web_artifact import VerifiedWebArtifact, WebArtifactViolation
from hwpxfiller.webapp import app as app_mod

ROOT = Path(__file__).resolve().parents[1]


def test_source_product_resolves_fresh_build_web() -> None:
    artifact = app_mod.web_artifact()

    assert artifact.root.parent == (ROOT / "build").resolve()
    assert artifact.root.name == "web"
    assert artifact.index_path == artifact.root / "index.html"
    assert len(artifact.artifact_id) == 64
    assert len(artifact.tree_sha256) == 64


def test_artifact_failure_is_loud_before_webview_window_creation(
    monkeypatch,
) -> None:
    messages: list[str] = []

    def reject_artifact():
        raise WebArtifactViolation("seal missing")

    def reject_window(*_args, **_kwargs):
        raise AssertionError("artifact 검증 실패 뒤 창을 생성했습니다")

    monkeypatch.setattr(app_mod, "web_artifact", reject_artifact)
    monkeypatch.setattr(app_mod, "_alarm", lambda message, window=None: messages.append(message))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=reject_window),
    )

    assert app_mod.main() == 2
    assert messages and "창을 열지 않습니다" in messages[0]
    assert "seal missing" in messages[0]


def test_main_and_selftest_share_the_single_resolver() -> None:
    """해석기는 하나이고, 정체 재확인은 **자가검증 쪽**이 진다.

    N-09 이전에는 ``_runtime_selftest_evidence`` 와 ``_selftest_drive`` 사이를 문자열로 잘라
    읽었다. 두 함수가 사라지면 이 테스트는 단언이 아니라 :class:`ValueError` 로 죽어 사유가
    보이지 않는다 — 그래서 후계는 **함수 자체를 지목**한다(:func:`inspect.getsource`).
    옮겨도 살아남고, 사라지면 이름을 대며 죽는다.

    지키는 것 셋은 그대로다:
      ① ``main()`` 은 ``webview`` 를 들이기 **전에** 산출물을 해석한다(봉인 실패가 GUI·서버
         부작용보다 먼저 부팅을 끊는다).
      ② 창 생성 **이후**의 정체 교체 판정은 자가검증 산출자가 진다 — ``main()`` 이 대신
         지면 "창이 뜬 뒤 바뀌었는가"를 아무도 묻지 않게 된다.
      ③ 두 번째 해석기는 어디에도 없다(D-02).
    """
    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    main_region = source[source.index("def main(") :]
    identity_region = inspect.getsource(app_mod._selftest_artifact_identity)

    assert main_region.index("artifact = web_artifact()") < main_region.index("import webview")
    assert "str(artifact.index_path)" in main_region
    # 산출물은 라이브 실행의 봉투에도 실린다 — 드라이버가 정체를 물을 수 있는 유일한 통로다.
    # (종전에는 `"(window, artifact)"` 라는 **위치 인자 튜플**을 문자열로 단언했다. 그 튜플이
    #  바로 #423 이 없앤 결함 원인이라 후계는 봉투 조립을 지목한다.)
    assert "artifact=artifact" in main_region

    assert "current_artifact = web_artifact()" in identity_region
    assert "current_artifact.artifact_id != launched_artifact.artifact_id" in identity_region
    # 판정의 **자리**가 계약이다 — main() 으로 옮기면 위 두 문자열은 여전히 소스 어딘가에
    # 있지만 "창이 뜬 뒤"를 묻는 성질은 사라진다.
    assert "current_artifact = web_artifact()" not in main_region

    # 그리고 그 산출자가 실제로 호스트 연산에 물려 있어야 한다(선언만 살고 결과가 죽지 않게).
    assert "artifact_identity=lambda: _selftest_artifact_identity(" in inspect.getsource(
        app_mod._selftest_host_operations
    )

    assert "HWPXFILLER_WEB_DIR" not in source
    assert '_repo_root() / "web"' not in source
    assert '_repo_root() / "frontend"' not in source


def test_selftest_rejects_artifact_swap_after_window_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    launched = VerifiedWebArtifact(
        root=tmp_path,
        index_path=tmp_path / "index.html",
        artifact_id="a" * 64,
        tree_sha256="b" * 64,
    )
    swapped = VerifiedWebArtifact(
        root=tmp_path,
        index_path=tmp_path / "index.html",
        artifact_id="c" * 64,
        tree_sha256="d" * 64,
    )
    monkeypatch.setattr(app_mod, "web_artifact", lambda: swapped)

    # 후계는 `artifact_identity` 호스트 연산의 산출자다. **예외**로 올라야 한다 — 구조화된
    # 거절로 접으면 "정체가 바뀌었다"가 프로브 실패 하나로 뭉개진다.
    with pytest.raises(WebArtifactViolation, match="changed after"):
        app_mod._selftest_artifact_identity(launched)


def test_artifact_identity_returns_the_launched_pair_when_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """양성 대조 — 바뀌지 않았으면 **띄울 때의** 정체를 그대로 돌려준다.

    음성만 있으면 "언제나 던진다"도 통과한다(부재판별력 리트머스).
    """
    launched = VerifiedWebArtifact(
        root=tmp_path,
        index_path=tmp_path / "index.html",
        artifact_id="a" * 64,
        tree_sha256="b" * 64,
    )
    monkeypatch.setattr(app_mod, "web_artifact", lambda: launched)

    assert app_mod._selftest_artifact_identity(launched) == {
        "artifact_id": "a" * 64,
        "tree_sha256": "b" * 64,
    }


def test_offline_probe_responsibility_moved_to_the_frontend_runtime_probe() -> None:
    """오프라인 대조 셋(성공·차단·시한초과)의 **후계 위치**를 못박는다.

    N-09 이전에는 이 파일이 ``_runtime_selftest_evidence`` 를 직접 몰아 세 갈래를 각각
    단언했다. 그 책임은 프런트 ``runtime`` 프로브로 통째 넘어갔고, 세 갈래는
    ``tests/js/n08_persistence_geometry.test.js`` 가 값-수준으로 진다(가상 시계 포함).

    그래서 여기서 같은 단언을 다시 쓰지 않는다 — 같은 판정을 두 곳이 지면 둘은 반드시
    갈라진다. 대신 **이관이 실제로 일어났는지**만 센다: 후계 파일이 있고, 릴리스 빌드가
    읽는 표식 문자열 둘을 그 파일이 들고 있고, 파이썬 쪽에는 남아 있지 않다.

    이 문자열 둘은 ``packaging/build.ps1`` 의 양성·음성 대조가 **정확히 일치**로 읽는다
    (:func:`test_packaging_requires_artifact_parity_node_free_boot_and_offline_probe`).
    하나라도 바뀌면 릴리스 빌드가 조용히 대조를 잃는다.
    """
    probe_js = source_text("src", "selftest", "probes", "persistence_geometry.js")
    app_source = Path(app_mod.__file__).read_text(encoding="utf-8")

    assert "external fetch succeeded" in probe_js
    assert "offline probe timed out" in probe_js
    # 스킴을 문자열로 적지 않는 난독화도 함께 옮겨갔다(정적 스캐너가 외부 URL 로 읽지 않게).
    assert "String.fromCharCode(104, 116, 116, 112)" in probe_js

    # 레거시 엔진은 남아 있지 않다 — 두 엔진이 동시에 사는 최종 상태를 금지한다.
    assert not hasattr(app_mod, "_runtime_selftest_evidence")
    assert not hasattr(app_mod, "_probe_late")
    assert "__n03OfflineProbe" not in app_source


def test_live_run_is_the_only_way_the_product_hands_its_window_over() -> None:
    """창을 남에게 넘기는 통로는 :mod:`~hwpxfiller.webapp.live_run` **하나**다.

    종전 이 자리는 ``_selftest_drive`` 가 **모듈 전역 이름으로 남아 있는지**를 물었다. 캡처
    하니스가 그 자리를 갈아끼워 창을 빌렸기 때문인데, 그 단언은 이름만 보고 **호출 계약을 못
    봤다**: #375 가 pywebview 로 넘기는 위치 인자를 하나에서 둘로 늘렸을 때 하니스의
    ``drive(window)`` 는 그대로였고, 그 뒤로 캡처는 워커 스레드 ``TypeError`` 로 한 줄도 돌지
    않은 채 GUI 루프에 매달렸다 — 그동안 이 테스트는 초록이었다(선언은 살고 결과는 죽는다).

    후계는 실제 계약을 지목한다. 계약 자체의 양성·음성 대조는
    ``tests/test_live_run_contract.py`` 가 지고, 여기서는 ``main()`` 이 **다른 통로를 열지
    않았는지**만 센다.
    """
    assert callable(app_mod._write_selftest_output)
    assert callable(app_mod._selftest_drive)
    # 합친 이름은 사라졌다 — 101 이 호스트 연산 허용목록을 비껴가던 유일한 구멍이었다.
    assert not hasattr(app_mod, "_finish_selftest")

    main_source = inspect.getsource(app_mod.main)
    assert "webview.start(" in main_source
    # 드라이버는 봉투 하나를 받는 0-arity 진입점으로만 넘어간다. 위치 인자를 다시 실으면
    # 이 단언이 아니라 계약 시험이 먼저 붉어지지만, 여기서도 통로의 이름을 못박아 둔다.
    assert "live_run.entrypoint(" in main_source
    assert "_selftest_drive," not in main_source


def test_packaging_requires_artifact_parity_node_free_boot_and_offline_probe() -> None:
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    # 외부 fetch 대조를 실제로 쏘는 자리는 N-09 에서 프런트 `runtime` 프로브로 옮겨갔다.
    # 릴리스 빌드가 읽는 것은 그 프로브가 낸 값이므로, 대조 문자열의 대상도 함께 옮긴다.
    probe_js = source_text("src", "selftest", "probes", "persistence_geometry.js")
    entry = (ROOT / "packaging" / "hwpx_filler_web_entry.py").read_text(
        encoding="utf-8"
    )
    proxy = (ROOT / "scripts" / "selftest_http_proxy.py").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "scripts" / "verify_packaged_web.py").read_text(
        encoding="utf-8"
    )

    assert "scripts\\verify_packaged_web.py" in build
    assert build.index("scripts\\verify_packaged_web.py") < build.index("--selfcheck")
    assert "Node-free packaged gate PATH" in build
    assert "HWPX_SELFTEST_OFFLINE_PROBE" in build
    assert "--proxy-server=127.0.0.1:$proxyPort --disable-background-networking" in build
    assert "--proxy-server=127.0.0.1:9" not in build
    assert "scripts\\selftest_http_proxy.py" in build
    assert "network-control-proxy-hit.json" in build
    assert "proxyHit.target -ne 'http://example.com/__n03_network_control__'" in build
    assert "packaged-network-control.json" in build
    assert "network_control_external_fetch_succeeded" in build
    assert "network_control_external_fetch_completed" in build
    assert "network_control_proxy_observed" in build
    assert "network_isolation_mechanism" in build
    diagnostic_marker = "network_control_diagnostics="
    assert diagnostic_marker in build
    assert build.index(diagnostic_marker) < build.index(
        "control proxy를 통한 packaged WebView2 외부 HTTP probe"
    )
    for diagnostic_field in (
        "environment_browser_arguments",
        "policy_browser_arguments",
        "control_elapsed_ms",
        "evidence_error_present",
        "evidence_error = $networkEvidence.error",
        "external_fetch_error",
        "proxy_observed",
        "proxy_hit_parse_failed",
        "proxy_process_exited",
    ):
        assert diagnostic_field in build
    assert "AdditionalBrowserArguments" in build
    assert "HKEY_LOCAL_MACHINE" not in build
    assert "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Edge\\WebView2\\" in build
    assert "$webViewPolicyName = [System.IO.Path]::GetFileName($exe)" in build
    assert "기존 WebView2 AdditionalBrowserArguments machine policy" in build
    assert "Remove-ItemProperty -LiteralPath $webViewPolicyPath" in build
    assert "machine policy value cleanup을 확인하지 못했습니다" in build
    assert "machine policy key cleanup을 확인하지 못했습니다" in build
    assert "$policyKey.GetValueNames().Count -eq 0" in build
    assert "'hklm-app-policy'" in build
    assert "'process-environment'" in build
    assert "responsibilities.Count -ne 43" in build
    assert "responsibilities.Count -ne 42" not in build
    assert "falseResponsibilities.Count -ne 0" in build
    # React 실런타임 형상 단언(R2-04 · #408)이 packaged 판정에 실재한다.
    assert "react_runtime 증거가 없습니다" in build
    assert "$reactRuntime.roots -ne 1" in build
    assert "resources_same_origin" in build
    assert "external_fetch_blocked" in build
    # 난독화된 스킴은 프런트 프로브로 옮겨갔다(N-09) — 표식이 사라지지 않았는지는
    # test_offline_probe_responsibility_moved_to_the_frontend_runtime_probe 가 진다.
    assert "String.fromCharCode(104, 116, 116, 112)" in probe_js
    assert '["example", "com"].join(".")' in probe_js
    assert "ThreadingHTTPServer" in proxy and "self.send_response(204)" in proxy
    assert "artifact = web_artifact()" in entry
    assert "artifact.artifact_id" in entry and "artifact.tree_sha256" in entry
    assert "resolve_web_artifact(repo_root=args.repo_root)" in verifier
    assert "resolve_web_artifact(frozen_root=args.bundle_root)" in verifier


def test_the_packaged_gate_listens_to_the_selfcheck_identity() -> None:
    """``--selfcheck`` 국면이 **자기 입으로** 말한 identity 를 게이트가 듣는가(R5-03).

    이 국면의 이름을 정확히 적는다: ``--selfcheck`` 는 제품 ``main()`` 을 부르지 않는다 —
    엔트리 래퍼가 그 인자만 가로채 헤드리스 스모크로 보낸다(아래에서 함께 못박는다). 그래서
    여기서 얻는 것은 「정상 실행의 증거」가 아니라 **창을 열지 않는 별개 프로세스가 같은
    sealed 산출물을 fail-closed 로 해석했다**는 증거다. 제품 진입점(``main()``)이 해석한
    identity 는 ``--selftest`` 증거의 ``runtime.artifact_id`` 가 이미 대조한다.

    종전 게이트는 ``ExitCode`` 만 읽어 이 프로세스가 무엇을 실었는지 아무도 묻지 않았다.
    창 앱이라 stdout 은 리디렉션해야 잡힌다.
    """
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    entry = (ROOT / "packaging" / "hwpx_filler_web_entry.py").read_text(encoding="utf-8")

    # 제품이 그 줄을 실제로 낸다 — 게이트가 읽을 것이 없는데 읽는 척하지 않게.
    assert "artifact_id={artifact.artifact_id}" in entry
    assert "tree_sha256={artifact.tree_sha256}" in entry

    assert "-RedirectStandardOutput $selfcheckOut" in build
    # 판정은 Python 판별기가 진다 — 인라인 정규식으로 되돌아가면 음성 대조가 붙을 자리가
    # 사라진다(`classify_webview_evidence.py` 와 같은 규율).
    assert r"scripts\assert_selfcheck_identity.py" in build
    assert "--selfcheck-output $selfcheckOut" in build
    assert "selfcheck_artifact_id" in build
    # 이 국면이 제품 main() **밖**이라는 사실을 엔트리에서 직접 센다 — 그 사실이 바뀌면
    # 위 docstring 의 주장도 증거 키 이름도 함께 틀린 것이 된다.
    assert 'sys.argv[1] == "--selfcheck"' in entry
    assert entry.index('sys.argv[1] == "--selfcheck"') < entry.index("import main")
    # 실행이 먼저, 판정이 나중 — 순서가 뒤집히면 앞 실행의 잔재를 읽는다.
    assert build.index("-RedirectStandardOutput $selfcheckOut") < build.index(
        r"scripts\assert_selfcheck_identity.py"
    )


def test_the_packaged_gate_verifies_the_portable_copy_every_run() -> None:
    r"""사용자가 여는 것은 dist\ 가 아니라 zip 을 푼 결과다(R5-03).

    종전에 이 왕복은 태그 push 에서만 검증됐다 — 압축·해제가 트리를 바꿔도 병합 시점엔
    아무도 몰랐다. 순서가 계약이다: 검증은 **왕복 뒤**에 선다.
    """
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")

    assert "Compress-Archive" in build
    assert "Expand-Archive" in build
    assert "portable-parity.json" in build
    assert build.index("Expand-Archive") < build.index("portable-parity.json")
    assert build.index("Compress-Archive") < build.index("Expand-Archive")


def test_shipped_copies_are_reconciled_by_one_owner_with_a_declared_set() -> None:
    """사본 대조 판정은 스크립트 하나가 지고, 호출자는 **집합을 선언**한다(R5-03).

    선언이 없으면 사본 하나가 조용히 빠진 채 "남은 것끼리 같다"로 초록이 난다. 릴리스는 넷,
    패키징 게이트는 셋(설치본은 태그 소유) — 두 선언이 서로 다른 것이 이 계약의 요점이다.
    """
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert r"scripts\reconcile_shipped_copies.py" in build
    assert "'--expect', $expectedCopies" in build
    assert "$expectedCopies = 'source,dist,portable'" in build
    assert "$expectedCopies = 'source,dist,installed,portable'" in build

    assert r"scripts\reconcile_shipped_copies.py" in release
    assert "--expect source,dist,installed,portable" in release
    # 설치본 사본은 두 곳에서 만들어진다(릴리스 태그 · `-IncludeInstaller`). 순서 계약
    # 「제거 앞에 검증」은 릴리스 쪽만 못박혀 있었다 — 러너 쪽도 같은 강도로 센다.
    installed = build[build.index("function Invoke-InstalledCopy"):]
    installed = installed[: installed.index("function Test-BundleBoundary")]
    assert installed.index("verify_packaged_web.py") < installed.index("unins000.exe"), (
        "설치본 검증이 제거 뒤로 밀렸습니다"
    )
    assert "--selfcheck" in installed, "릴리스 쪽 설치본 스모크와 강도가 다릅니다"
    assert "_is1" in installed, "출하 AppId 충돌 가드가 없습니다"
    # 인라인 재조립으로 되돌아가지 않는다 — 같은 판정이 두 곳에 살면 하나가 낡는다.
    assert "Sort-Object -Unique).Count -ne 1" not in release


def test_the_node_free_phase_has_one_definition_and_both_targets_run_inside_it() -> None:
    """Node-free 국면의 정의가 하나이고 filler·CLI 둘 다 그 안에서 도는가(R5-03).

    종전에는 PATH 스크럽이 filler 분기 안에만 있었다. CI 에서 CLI 스모크가 Node 없이 돈 것은
    그 잡이 ``setup-node`` 를 안 하기 때문이지 이 게이트가 그것을 세서가 아니었다 —
    우연한 참은 계약이 아니다.
    """
    build = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")

    assert build.count("function Set-NodeFreePath") == 1
    assert build.count("Node-free packaged gate PATH에서 node.exe가 발견됐습니다.") == 1
    # 정의 1 + 호출 2(filler·CLI). 호출이 하나면 한 타깃이 국면 밖에서 도는 것이다.
    assert build.count("Set-NodeFreePath") == 3
    # CLI 분기가 자기 PATH 를 저장·복원한다 — 국면이 그 분기를 넘어 새지 않게.
    assert "$savedCliPath = $env:Path" in build
    assert build.index("$savedCliPath = $env:Path") < build.index("$exe schema $template")
