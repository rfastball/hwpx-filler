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

#: 잎 넷 + 중앙 compat + N-05 서비스 다섯 묶음 + N-06 화면·셸 다섯 묶음. 파일이 사라지면
#: 러너는 여전히 초록이므로 여기서 전수를 센다.
EXPECTED_TEST_FILES = {
    "compat.test.js",
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
    # N-08 — 제품 그래프에 **닿지 않는** inert 프로브 모듈의 단위 게이트.
    "n08_schema.test.js",
    "n08_runner.test.js",
    "n08_persistence_geometry.test.js",
    "n08_boot_routing_overlay.test.js",
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
    assert counts.get("pass", 0) >= 220, (
        "통과 수가 기대보다 적습니다 — 파일은 있는데 테스트가 수집되지 않았을 수 있습니다.\n"
        f"{report}"
    )
