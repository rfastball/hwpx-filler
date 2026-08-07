"""프런트 ESM 모듈의 module-native 단위 게이트를 기존 pytest 게이트 안에서 돈다.

N-04에서 잎 넷이 true ESM이 되면서, 정적 소스 검사로는 못 보는 층이 처음 생겼다: export가
**무엇을 돌려주는지**다. 소스 문자열 대조는 `escHtml`이 존재한다는 것만 말하고 `&`를 아직
`&amp;`로 바꾸는지는 말하지 않는다(선언은 살고 결과는 죽는 결함류).

그 층은 Node에서만 실행할 수 있으므로 러너를 하나 붙이되, **별도 게이트로 두지 않는다** —
따로 두면 `test.ps1`과 CI 세 잡 중 아무도 부르지 않는 채 초록일 수 있다. 여기서 pytest가
직접 몰아 실패가 기존 회귀 게이트와 같은 자리에서 시끄럽게 난다.

의존은 늘리지 않는다: Node 24의 내장 ``node:test``만 쓰고 ``package.json``도 건드리지
않는다(제품 script 표면은 build/verify 둘뿐이라는 계약이 따로 있다).

런타임 부재는 조용히 스킵하지 않는다 — Node는 이미 빌드 전제조건이고 CI 세 잡 모두
``.node-version``으로 설치하므로, 없으면 그 자체가 실패다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_TEST_DIR = Path(__file__).resolve().parent / "js"

#: 잎 넷 + 합성 루트 + N-05 서비스 다섯 묶음 + N-06 화면·셸 다섯 묶음 + N-07 브리지·파사드
#: 둘 + N-10 전역 위생. 파일이 사라지면 러너는 여전히 초록이므로 여기서 전수를 센다.
#:
#: **등재 지점 규정**(R2 패킷 §4.3 — #405·#406): 새 단계가 `.test.js` 를 더하며 이 집합에
#: 행을 추가하는 것은 소유 침범이 아니라 **등재**다. 행 추가 + 단계 주석까지가 등재이고,
#: 기존 행의 변경·삭제는 그 행 소유 단계의 몫이다.
EXPECTED_TEST_FILES = {
    "bootstrap.test.js",
    "n10_global_hygiene.test.js",
    "copy.test.js",
    "esc.test.js",
    "guard.test.js",
    "segview.test.js",
    "n05_foundation.test.js",
    "n05_overlay.test.js",
    "n05_services.test.js",
    "n05_data_picker.test.js",
    "n05_editor_entry.test.js",
    "n06_library.test.js",
    "n06_workbench.test.js",
    "n06_editor.test.js",
    "n06_job.test.js",
    "n06_app_shell.test.js",
    # N-07 — 브리지 ESM factory 와 제품 파사드.
    "n07_bridge.test.js",
    "n07_product_api.test.js",
    # N-08 — 제품 그래프에 **닿지 않는** inert 프로브 모듈의 단위 게이트.
    "n08_schema.test.js",
    "n08_runner.test.js",
    "n08_persistence_geometry.test.js",
    "n08_boot_routing_overlay.test.js",
    "n08_editor_workbench_data.test.js",
    "n08_job.test.js",
    "n08_registry.test.js",
    # N-09 — 시험 능력 프로토콜과, 제품·프로브가 만나는 단일 푸시 통로(음성 대조 포함).
    "n09_selftest_api.test.js",
    "n09_push_port.test.js",
    # R2-01 — React root 상태기계(주입 기록자)와 요소 배선. 실 커밋 증거는 live 게이트.
    "react_root.test.js",
    # R2-02 — runtime adapter/typed client 의 오류 변환 셋과 pywebview 접촉 allowlist.
    "runtime_client.test.js",
    "pywebview_allowlist.test.js",
    # R2-03 — 스냅샷 store 계약(구독·해제·당김 가드·격리)과 hook 결속. 실물 증거는 live 게이트.
    "state_store.test.js",
    # R2-04 — selftest 클러스터 R(React 실런타임 마커)의 단위 계약. 실창 증거는 selftest
    # 게이트·packaged 판정이 진다.
    "n08_react_runtime.test.js",
    # R3-01 — 트리-불가지 overlay 엔진(판정 순수층)과 React host(렌더 요소 계약·집행 계약).
    # 실창 증거는 test_react_overlay_live 가 진다.
    "overlay_engine.test.js",
    "overlay_host.test.js",
    # R3-02 — 셸 상태기계(판정 순수층). adapter 결합·부착 실물은 n06, 실창 증거는
    # test_react_shell_live 가 진다.
    "shell_nav.test.js",
    # R4-01 — read surface React controller/runtime/typed handoff 회귀 단위.
    "r4_data_picker.test.js",
    "r4_job_read.test.js",
    "r4_job_relink_flow.test.js",
    "r4_library.test.js",
    "r4_screen_runtime.test.js",
    "r4_service_handoff.test.js",
    # R4-02 — 편집·매핑 표면. reducer 불변식과 이탈 거래는 화면별 파일에 흩지 않고
    # 각각 한 자리에 모은다(같은 규율을 두 초록 사이에 숨기지 않는다).
    "r4_editor.test.js",
    "r4_editor_entry_handoff.test.js",
    "r4_editor_state.test.js",
    "r4_leave_transactions.test.js",
    "r4_sheet_picker.test.js",
    "r4_workbench.test.js",
}

#: Node 24의 러너에 **디렉터리**를 넘기면 모듈 경로로 해석해 MODULE_NOT_FOUND로 죽는다.
#: 글롭 패턴은 Node가 직접 확장하므로 셸에 의존하지 않는다(Windows 포함).
_TEST_GLOB = "tests/js/*.test.js"


def _node() -> str:
    node = shutil.which("node")
    assert node is not None, (
        "Node가 PATH에 없습니다 — 프런트 모듈 단위 게이트를 돌 수 없습니다. "
        "Node는 이 저장소의 빌드 전제조건이라 부재는 스킵 사유가 아닙니다."
    )
    return node


def test_module_test_files_are_all_present() -> None:
    """단위 테스트 파일 전수 — 파일이 지워지면 러너는 조용히 초록이 된다."""
    on_disk = {path.name for path in MODULE_TEST_DIR.glob("*.test.js")}

    assert on_disk == EXPECTED_TEST_FILES, (
        "프런트 모듈 단위 테스트 전수가 어긋납니다.\n"
        f"  디스크: {sorted(on_disk)}\n"
        f"  기대:   {sorted(EXPECTED_TEST_FILES)}"
    )


def test_frontend_module_units_pass() -> None:
    """``node --test``로 잎 ESM과 compat의 실제 산출을 확인한다."""
    result = subprocess.run(
        [_node(), "--test", "--test-reporter=tap", _TEST_GLOB],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    report = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    assert result.returncode == 0, f"프런트 모듈 단위 테스트가 실패했습니다.\n{report}"

    counts = {
        key: int(value)
        for key, value in re.findall(
            r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$",
            result.stdout,
        )
    }

    assert counts, f"TAP 요약을 읽지 못했습니다 — 러너 출력 형식이 바뀌었습니다.\n{report}"
    assert counts.get("fail") == 0, f"실패한 모듈 단위 테스트가 있습니다.\n{report}"
    assert counts.get("skipped") == 0, f"조용히 스킵된 모듈 단위 테스트가 있습니다.\n{report}"
    assert counts.get("todo") == 0, f"todo로 유예된 모듈 단위 테스트가 있습니다.\n{report}"
    assert counts.get("cancelled") == 0, f"취소된 모듈 단위 테스트가 있습니다.\n{report}"
    # 하한 600 은 실측(R2-04 시점 649)의 보수 하한이다 — 종전 220 은 실제치의 1/3 수준이라
    # 파일 몇 개가 수집을 잃어도 초록이었다(선언 살고 결과 죽는 자리). 수는 늘기만 하므로
    # 하한 상향은 미래 마찰이 아니다.
    assert counts.get("pass", 0) >= 600, (
        "통과 수가 기대보다 적습니다 — 파일은 있는데 테스트가 수집되지 않았을 수 있습니다.\n"
        f"{report}"
    )
