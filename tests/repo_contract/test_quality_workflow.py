"""품질 CI 의 **의미 계약** — 누가 무엇을 만들고 누가 무엇을 검증하는가(N-11B · #424). [저장소 형상 계약]

종전 이 파일은 문자열 횟수를 셌다(`text.count("npm.cmd run build") == 3`). 그 형태는 "세
표면이 같은 산출물을 쓴다"를 지키려던 것이었지만 실제로 지킨 것은 **같은 명령을 세 번
쓴다**였다 — 서로 다른 세 산출물을 만들어도 초록이었고, 실제로 그렇게 돌고 있었다.

그래서 검사를 옮긴다: 횟수가 아니라 **생산자·소비자 관계**와 **책임의 유일성**을 본다.
비교 대상은 파싱된 job 구조다(YAML 주석은 계약을 만족시킬 수 없다 — 파서가 걷어낸다).
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
QUALITY = ROOT / ".github" / "workflows" / "quality.yml"
AXES = {
    "native": "HWPX_SKIP_NATIVE_TESTS",
    "browser": "HWPX_SKIP_MOTION_TESTS",
    "live": "HWPX_SKIP_GUI_TESTS",
}
CONTRACT_EXPR = " and ".join(f"not {axis}" for axis in AXES)

#: 프런트를 **만드는·봉인하는** 흔적. 소비자 job 에 하나라도 있으면 그 job 은 소비자가 아니다.
#:
#: `npm ci` 는 여기 없다 — 의존성 설치는 산출물 생산이 아니다. Node 단위 검사는 생산자가
#: 빌드에 쓴 같은 설치를 재사용한다. 두 필요를 뭉뚱그리면 이 계약이 엉뚱한 것을 막는다.
#: "산출물 검증은 빌드 도구를 안 쓴다"는 주장은 아래 **단계 순서** 계약이 대신 진다.
BUILD_TOKENS = ("npm run build", "npm.cmd run build", "-Mode Build")

#: 생산자가 올리고 소비자가 내려받는 산출물 이름.
SEALED = "sealed-web"

#: 브랜치 보호가 겨누는 단 하나의 이름.
GATE = "quality-gate"


def _workflow() -> tuple[str, dict]:
    text = QUALITY.read_text(encoding="utf-8")
    loaded = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return text, loaded


def _jobs() -> dict[str, dict]:
    _, workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict) and jobs
    return jobs


def _job_text(job: dict) -> str:
    """job 을 통째로 문자열화 — 주석이 아닌 **실제로 도는 것**만 남는다."""
    return json.dumps(job, ensure_ascii=False)


def _run_commands(job: dict) -> list[str]:
    return [
        str(step["run"])
        for step in job.get("steps", [])
        if isinstance(step, dict) and "run" in step
    ]


def _logical_lines(command: str) -> list[str]:
    """줄잇기(PowerShell 백틱 · sh 백슬래시)를 이어 붙여 **한 명령이 한 줄**이 되게 한다.

    이걸 안 하면 `uv run …` 과 그 인자가 다른 줄에 놓이는 순간 두 조각 어느 쪽도 안 걸린다 —
    규칙은 초록인데 실제로는 그대로 통과한다. `quality.yml` 은 이미 백틱 줄잇기를 쓰므로
    (커버리지 하한 호출) 이건 가상의 형상이 아니다.
    """
    return re.sub(r"[`\\]\r?\n\s*", " ", command).splitlines()


def _runs_axis(job: dict, axis: str) -> bool:
    """그 job 이 `-m <축>` 으로 pytest 를 도는가(축 이름의 부분일치가 아니라 낱말로)."""
    return any(re.search(rf"-m {axis}\b", command) for command in _run_commands(job))


def _needs(job: dict) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _uses_action(job: dict, action: str) -> list[dict]:
    return [
        step
        for step in job.get("steps", [])
        if isinstance(step, dict) and str(step.get("uses", "")).startswith(action)
    ]


def _downloads_sealed_web(job: dict) -> bool:
    return any(
        step.get("with", {}).get("name") == SEALED
        for step in _uses_action(job, "actions/download-artifact")
    )


# ─────────────────────────── 집계·운영 계약 ───────────────────────────


def test_the_aggregate_gate_enumerates_every_other_job() -> None:
    """`quality-gate` 는 나머지 **전부**를 열거한다 — 빠진 job 은 아무도 안 본다.

    브랜치 보호가 겨누는 이름이 하나라는 것은 편의지만, 그 하나가 무엇을 대표하는지 목록으로
    적혀 있지 않으면 job 을 추가할 때 조용히 대표에서 빠진다. 그 상태의 초록은 "다 통과했다"가
    아니라 "우리가 보기로 한 것만 통과했다"이고, 둘의 차이는 보이지 않는다.
    """
    jobs = _jobs()
    assert GATE in jobs, "집계 job 이 없습니다"

    assert _needs(jobs[GATE]) == set(jobs) - {GATE}, (
        f"열거 누락 {sorted(set(jobs) - {GATE} - _needs(jobs[GATE]))} · "
        f"없는 job 열거 {sorted(_needs(jobs[GATE]) - set(jobs))}"
    )


def test_the_aggregate_gate_only_accepts_success() -> None:
    """집계는 `success` 만 통과시킨다 — `if: always()` 와 느슨한 조건의 조합이 함정이다.

    `always()` 로 도는 job 이 결과를 제대로 안 보면 **모든 실패를 초록으로 덮는다**. 그래서
    판정 줄을 직접 센다: 성공이 아닌 것을 모아 이름을 대며 죽는가.
    """
    gate = _job_text(_jobs()[GATE])

    assert "always()" in gate, "집계가 안 돌면 실패한 run 에서 판정 자체가 사라진다"
    assert '.value.result != \\"success\\"' in gate or '.result != "success"' in gate, (
        "집계가 성공 이외를 거르는 줄이 없습니다"
    )
    assert "exit 1" in gate, "거절이 종료 코드로 나오지 않으면 초록으로 읽힌다"


def test_only_pull_request_runs_are_cancelled_by_a_newer_push() -> None:
    """연속 push 는 앞선 **PR** run 만 취소한다 — master·merge queue 이력은 남는다.

    `cancel-in-progress: false` 는 그 약속의 절반만 진다. 같은 그룹에 대기 중인 run 이
    있으면 GitHub 이 그것을 **밀어내므로**, 그룹 키가 commit 마다 달라야 가운데 commit 의
    검증이 완주하지 못한 채 사라지는 일이 없다(코덱스 리뷰 P1).
    """
    text, workflow = _workflow()
    concurrency = workflow["concurrency"]

    assert "pull_request.number" in concurrency["group"], "PR 단위로 묶이지 않습니다"
    assert "github.sha" in concurrency["group"], (
        "PR 이 아닌 run 이 commit 마다 자기 그룹을 갖지 않으면, 대기 중이던 run 이 다음 "
        "push 에 밀려 검증 없이 사라진다"
    )
    assert "github.event_name == 'pull_request'" in concurrency["cancel-in-progress"], (
        "master push 나 merge queue run 까지 취소하면 초록이었는지 모르는 commit 이 남는다"
    )
    assert "merge_group" in workflow["on"], "merge queue 진입 계약이 없습니다"


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    """action 은 태그가 아니라 **full commit SHA** 로 고정한다.

    태그는 움직이는 이름이다 — 같은 워크플로가 어제와 다른 코드를 돌릴 수 있고, 그때 무엇이
    바뀌었는지 이 저장소는 말해 주지 못한다. 사람이 읽을 버전은 주석으로 함께 남긴다.
    """
    text, _ = _workflow()
    uses = re.findall(r"uses: (\S+)(.*)", text)

    assert uses, "action 을 하나도 안 쓰면 이 계약이 아무것도 안 지킨다"
    for reference, trailer in uses:
        _, _, version = reference.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", version), f"{reference} 가 SHA 로 고정되지 않았습니다"
        assert re.search(r"#\s*v\d", trailer), f"{reference} 에 사람이 읽을 버전 주석이 없습니다"


def test_exactly_one_job_may_save_the_uv_cache() -> None:
    """캐시는 모두가 쓰되 **하나만 저장한다** — 동시 예약은 매 run 경고를 남긴다.

    설명 없는 경고가 상시로 붙어 있으면 다음 사람이 워크플로를 읽을 때마다 지나칠 것이
    하나 늘고, 그 습관이 진짜 경고를 지나치게 만든다.
    """
    savers = {
        str(step["with"]["save-cache"])
        for job in _jobs().values()
        for step in _uses_action(job, "astral-sh/setup-uv")
        if "save-cache" in step.get("with", {})
    }

    assert savers, "저장 정책이 없으면 일곱 잡이 같은 키를 두고 경합한다"
    assert len(savers) == 1 and "github.job ==" in savers.pop(), (
        "저장 잡을 조건 하나로 고르지 않으면 어느 잡이 저장하는지 읽어 낼 수 없다"
    )


def test_downloads_refuse_a_digest_mismatch() -> None:
    """산출물 전송이 어긋나면 **받는 쪽에서** 죽는다 — 조용히 다른 바이트를 쓰지 않는다."""
    downloads = [
        step
        for job in _jobs().values()
        for step in _uses_action(job, "actions/download-artifact")
    ]

    assert downloads, "다운로드가 0건이면 이 계약이 아무것도 안 지킨다"
    for step in downloads:
        assert step["with"].get("digest-mismatch") == "error", step["with"]


def test_live_and_distribution_evidence_survive_a_failed_run() -> None:
    """실주행·패키징 증거는 **실패해도** 회수된다 — 증거는 그때 가장 필요하다.

    종전에는 101 보고서가 pytest 임시 폴더로, 패키징 증거 6종이 러너 작업디렉터리로 가서
    잡과 함께 사라졌다. 남은 것은 빨간 체크 하나뿐이라 "무엇을 봤길래 빨간가"를 다시 돌려서만
    물을 수 있었다.
    """
    for name in ("live-webview2", "distribution-webview2"):
        uploads = _uses_action(_jobs()[name], "actions/upload-artifact")
        assert uploads, f"{name} 이 증거를 하나도 올리지 않습니다"
        for step in uploads:
            assert step.get("if") == "always()", (
                f"{name} 의 업로드가 성공 경로에만 붙어 있습니다 — 실패하면 사라집니다"
            )


def test_product_assertions_are_never_retried() -> None:
    """제품 단언에 재시도를 걸지 않는다 — 두 번째 초록이 첫 번째 빨강을 지운다."""
    text, _ = _workflow()

    for retry_token in ("nick-fields/retry", "continue-on-error: true", "--reruns"):
        assert retry_token not in text, f"재시도 흔적: {retry_token}"

    live = _jobs()["live-webview2"]
    assert live["timeout-minutes"] == "45"
    assert "--maxfail=1" in _job_text(live), "첫 하드스톱 뒤 형제 live 부팅을 계속 태웁니다"


# ───────────────────────── 생산자 하나 · 소비자 N ─────────────────────────


def test_exactly_one_job_produces_the_frontend() -> None:
    """한 run 의 프런트 생산자는 **정확히 하나**다.

    종전에는 넷이었다(static · pytest · distribution · 그 안의 packaging/build.ps1). 넷이
    각자 만든 산출물은 서로 같다는 보장이 없었고, 어느 job 이 무엇을 검증했는지 말할 수 없었다.
    """
    builders = {
        name for name, job in _jobs().items()
        if any(token in _job_text(job) for token in BUILD_TOKENS)
    }

    assert builders == {SEALED}, f"프런트 생산자가 {sorted(builders)} 입니다 — 하나여야 합니다."


def test_the_producer_uploads_the_tree_with_its_identity() -> None:
    """생산자는 트리와 **정체성**을 함께 올린다 — 그래야 소비자가 되짚을 수 있다.

    `include-hidden-files` 가 없으면 sealed 트리의 `.vite/manifest.json` 이 조용히 빠져
    소비자가 엉뚱한 자리를 가리키며 죽는다(upload-artifact 4.4+ 기본값).
    """
    producer = _jobs()[SEALED]
    uploads = _uses_action(producer, "actions/upload-artifact")

    assert len(uploads) == 1, "생산자의 업로드는 하나여야 합니다"
    options = uploads[0]["with"]
    assert options["name"] == SEALED
    assert "build/web" in options["path"]
    assert "web-artifact-identity.json" in options["path"]
    assert options["include-hidden-files"] == "true", "hidden 제외로 Vite manifest 가 샙니다"
    assert options["if-no-files-found"] == "error", "빈 업로드가 성공으로 보이면 안 됩니다"


def test_every_consumer_needs_the_producer_and_verifies_instead_of_rebuilding() -> None:
    """소비자는 생산자를 기다려 **내려받아 검증**한다 — 다시 만들지 않는다.

    stale 로컬 산출물 fallback 도 여기서 닫힌다: 검증은 다운로드한 트리를 이 checkout 의
    commit·frontend 바이트와 대조하고, identity 대조가 "혹시 자기가 다시 만들었는가"를 잡는다.
    """
    consumers = {name: job for name, job in _jobs().items() if _downloads_sealed_web(job)}

    assert consumers, "산출물 소비자가 0개면 생산자는 아무에게도 쓰이지 않습니다"
    for name, job in consumers.items():
        text = _job_text(job)
        assert SEALED in _needs(job), f"{name} 이 생산자를 needs 하지 않습니다"
        assert "VerifyExisting" in text, f"{name} 이 검증 모드로 돌지 않습니다"
        assert "web-artifact-identity.json" in text, f"{name} 이 정체성을 되짚지 않습니다"
        assert not any(token in text for token in BUILD_TOKENS), f"{name} 이 다시 만듭니다"

    # 집계 job 은 예외다 — 그것은 산출물이 아니라 **결과**를 기다린다(모든 job 을 열거하는
    # 것이 그 job 의 계약이고, 위 계약이 따로 센다).
    orphans = {
        name for name, job in _jobs().items()
        if SEALED in _needs(job) and name not in consumers and name != GATE
    }
    assert not orphans, f"{sorted(orphans)} 는 생산자를 기다리기만 하고 쓰지 않습니다"


def test_the_artifact_is_verified_before_any_node_appears_in_the_job() -> None:
    """소비자의 산출물 검증은 **Node 가 그 job 에 들어오기 전에** 끝난다.

    "봉인 검증에 빌드 도구가 필요 없다"는 말은 문장으로 두면 언제든 거짓이 될 수 있다. 단계
    순서로 두면 그 자체가 증거다 — 검증이 `setup-node` 앞에 있는 한, 그 단계는 Node 없이
    통과한 것이다.
    """
    for name, job in _jobs().items():
        steps = job.get("steps", [])
        if not any("VerifyExisting" in str(step.get("run", "")) for step in steps):
            continue
        verify_at = next(
            index for index, step in enumerate(steps)
            if "VerifyExisting" in str(step.get("run", ""))
        )
        node_at = [
            index for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/setup-node")
        ]
        assert all(verify_at < index for index in node_at), (
            f"{name}: 산출물 검증이 Node 설치 **뒤**에 있습니다 — 그 순서로는 검증이 Node "
            "없이 통과한다는 것을 아무도 확인하지 않습니다."
        )


def test_no_step_conjures_a_dependency_the_lockfile_never_saw() -> None:
    """CI 는 **선언한 환경**으로만 돈다 — `uv run --with` 로 얹지 않는다(#779).

    `uv sync --locked` 가 재현성의 계약인데 실행 줄에서 `--with X` 를 얹으면 그 X 는 매번
    PyPI 에서 새로 받는 잠금 밖 의존이 된다. 어느 버전으로 초록이었는지 기록이 없고, 같은
    커밋이 CI 에선 통과하고 `test.ps1` 에선 죽는다 — 실측으로 Pillow 가 그렇게 몇 달을 살았다.

    고칠 자리는 실행 줄이 아니라 `pyproject.toml` 의 의존 그룹이다. 그래야 CI 와 개발 기기가
    같은 환경을 본다.
    """
    # `--with` 만 보면 안 된다: uv 는 `-w` 를 **같은 뜻의 별칭**으로 받고(`uv run --help`:
    # ``-w, --with <WITH>``), `--with-editable`·`--with-requirements` 도 같은 식구다. 하나라도
    # 빠뜨리면 계약은 초록인 채 잠금 밖 의존이 그대로 얹힌다.
    conjured = re.compile(r"\buv run\b[^\n]*\s(?:--with|-w)\b")
    offenders = [
        f"{name}: {line.strip()}"
        for name, job in _jobs().items()
        for command in _run_commands(job)
        for line in _logical_lines(command)
        if conjured.search(line)
    ]

    assert not offenders, (
        "잠금 밖 의존을 실행 줄에서 얹는 단계가 있습니다 — 선언으로 옮기세요:\n"
        + "\n".join(offenders)
    )

    def _caught(command: str) -> bool:
        return any(conjured.search(line) for line in _logical_lines(command))

    # 음성 대조 — 형상을 실제로 거절하는가(항상 참인 검사가 아니다).
    assert _caught("uv run --no-sync --with pillow pytest -q")
    assert _caught("uv run -w pillow pytest -q")  # 같은 뜻의 짧은 별칭
    assert _caught("uv run --with-editable . pytest -q")  # 같은 식구
    assert _caught("uv run --no-sync `\n            --with pillow pytest -q")  # 줄잇기로 쪼갠 것도
    assert not _caught("uv run --no-sync pytest -q")
    assert not _caught("uv run --no-sync pytest --workers 2")  # `-w` 로 시작하는 다른 낱말
    # 다른 명령의 `--with` 를 앞 줄의 `uv run` 에 붙여 읽지 않는다(거짓 양성 금지).
    assert not _caught("uv run --no-sync pytest -q\nsome-tool --with foo")


def test_packaging_consumes_the_same_artifact_instead_of_building_its_own() -> None:
    """패키징도 소비자다 — 자기 안에서 프런트를 또 만들지 않는다(종전 4회째 빌드의 자리)."""
    commands = _run_commands(_jobs()["distribution-webview2"])
    packaging = [command for command in commands if "packaging" in command]

    assert len(packaging) == 1, f"패키징 호출이 {len(packaging)} 개입니다"
    assert "-Target all" in packaging[0], packaging[0]
    assert "-WebMode VerifyExisting" in packaging[0], "패키징이 프런트를 다시 만듭니다"


# ─────────────────────────── 책임의 유일성 ───────────────────────────


def test_each_resource_axis_runs_in_exactly_one_job() -> None:
    """자원 축은 각각 **한 job** 에서만 돈다 — 같은 책임을 두 번 태우지 않는다.

    종전 `tests/test_native_positive.py` 는 전용 단계와 무필터 전체 pytest 에서 두 번 돌았다.
    축으로 고르면 그 중복이 구조적으로 불가능해진다.
    """
    jobs = _jobs()
    for axis in AXES:
        owners = {name for name, job in jobs.items() if _runs_axis(job, axis)}
        assert len(owners) == 1, f"`{axis}` 축을 도는 job 이 {sorted(owners)} 입니다"

    contract_owners = {
        name for name, job in jobs.items() if CONTRACT_EXPR in _job_text(job)
    }
    assert len(contract_owners) == 1, f"contract 식을 도는 job 이 {sorted(contract_owners)} 입니다"


def test_python_suites_are_routed_by_responsibility() -> None:
    """형상·산출물·제품 거동이 각자 한 실행 경로에 있고 coverage는 제품 거동만 잰다."""
    jobs = _jobs()
    static = next(command for command in _run_commands(jobs["static"]) if "pytest" in command)
    sealed_commands = _run_commands(jobs[SEALED])
    artifact = next(command for command in sealed_commands if "pytest" in command)
    product = next(
        command for command in _run_commands(jobs["pytest-contract"]) if "pytest" in command
    )

    assert "tests/repo_contract" in static
    assert "--cov=" not in static and " -m " not in static
    assert "tests/artifact_contract" in artifact
    assert "--cov=" not in artifact and " -m " not in artifact
    assert "--ignore=tests/repo_contract" in product
    assert "--ignore=tests/artifact_contract" in product
    assert CONTRACT_EXPR in product
    assert "--cov=hwpxfiller" in product

    producer_text = _job_text(jobs[SEALED])
    assert producer_text.index("-Mode Build") < producer_text.index("npm.cmd test")
    assert producer_text.index("npm.cmd test") < producer_text.index("tests/artifact_contract")

    contract_job = jobs["pytest-contract"]
    assert SEALED not in _needs(contract_job)
    assert not _downloads_sealed_web(contract_job)
    assert not _uses_action(contract_job, "actions/setup-node")


def test_the_package_coverage_floor_has_exactly_one_owner() -> None:
    """커버리지와 하한은 한 job 이 소유한다 — 두 곳에서 재면 수치의 뜻이 흐려진다."""
    owners = {
        name for name, job in _jobs().items()
        if "check_package_coverage.py" in _job_text(job)
    }

    assert owners == {"pytest-contract"}, f"하한 소유자가 {sorted(owners)} 입니다"
    assert "--cov=hwpxfiller" in _job_text(_jobs()["pytest-contract"])


def test_chrome_evidence_is_not_presented_as_webview2_evidence() -> None:
    """설치 Chrome 판정과 실 WebView2 판정은 **다른 job·다른 이름**으로 산다.

    둘을 한 자리에 두면 "브라우저에서 됐다"가 "제품에서 됐다"로 읽힌다 — 그 혼동이 이
    저장소가 겪은 결함류(규칙은 초록인데 사용자는 틀린 것을 본다)의 입구다.
    """
    jobs = _jobs()
    chrome_job = next(name for name, job in jobs.items() if _runs_axis(job, "browser"))
    live_job = next(name for name, job in jobs.items() if _runs_axis(job, "live"))

    assert chrome_job != live_job
    assert "Chrome" in jobs[chrome_job]["name"]
    assert "WebView2" in jobs[live_job]["name"]
    assert "WebView2" not in _job_text(jobs[chrome_job])
    assert "chrome" not in _job_text(jobs[live_job]).lower()


# ─────────────────────────── 게이트 전제·경계 ───────────────────────────


def test_press_geometry_browser_precondition_is_its_own_visible_step() -> None:
    """눌림 기하 게이트(U2 §2.11)의 전제인 **설치 Chrome** 을 별 단계로 확인한다.

    부재가 테스트 안쪽 오류로 번역돼 나오면 원인 판독이 늦고, 조용한 스킵으로 새면 이
    결함류(규칙은 있는데 결과가 틀림)가 또 세 슬라이스를 통과한다. 옵트아웃 변수도 CI 에서
    명시로 걷어 「러너에서만 조용히 꺼져 있는」 상태를 만들지 않는다.
    """
    text, _ = _workflow()
    assert "Press-geometry browser precondition" in text
    assert "HWPX_SKIP_MOTION_TESTS" in text
    assert "channel='chrome'" in text


def test_quickstart_101_live_precondition_is_its_own_visible_step() -> None:
    """101 실주행 게이트(#423)의 전제를 별 단계로 확인하고, 옵트아웃을 CI 에서 걷는다.

    press-geometry 와 같은 이유다. 다만 여기엔 축이 하나 더 있다 — 이 게이트는 **실행 산출물**
    (실 HWPX 3건)을 판정하므로, 전제 부재가 조용한 스킵으로 새면 「101 이 도는지 아무도 안 보는」
    상태로 돌아간다. 그 상태가 정확히 #423 의 출발점이었다(캡처 하니스가 몇 달 깨져 있었고
    이름을 보는 정적 단언들은 그동안 초록이었다).
    """
    text, _ = _workflow()
    assert "Quickstart 101 live precondition" in text
    assert "scripts/capture_101_screenshots.py check --preflight" in text
    assert "HWPX_SKIP_GUI_TESTS" in text


def test_no_gate_opt_out_is_switched_on_inside_the_workflow() -> None:
    """옵트아웃 변수를 **켜는** 줄은 워크플로 어디에도 없다.

    CI 는 셋 다 걷고 돈다(CLAUDE.md). 그런데 "걷는다"는 `Remove-Item` 단계로만 보이고, 어딘가
    한 줄이 그것을 다시 켜면 그 단계는 선언만 남고 결과가 죽는다 — 이 저장소가 반복해 만난
    결함류다. 그래서 부재를 직접 센다.
    """
    text, _ = _workflow()
    for variable in AXES.values():
        assert f"{variable}:" not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"
        assert f"{variable}=1" not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"
        assert f'{variable} = "1"' not in text, f"{variable} 를 켜는 줄이 워크플로에 있습니다"


def test_release_builds_the_exact_frontend_before_tests_and_packaging() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert release.count("actions/setup-node@v4") == 1
    assert "node-version-file: .node-version" in release
    assert "Verify exact Node and npm" in release
    assert "'v24.18.1'" in release and "'11.16.0'" in release
    assert release.index("npm.cmd ci") < release.index("npm.cmd run build")
    assert release.index("npm.cmd run verify:web") < release.index(".\\test.ps1")
    assert release.index("npm.cmd run verify:web") < release.index(".\\build.ps1")


def _release_steps() -> list[dict]:
    document = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    return document["jobs"]["build-release"]["steps"]


def _release_step(fragment: str) -> dict:
    matches = [
        step for step in _release_steps() if fragment in (step.get("name") or "")
    ]
    assert len(matches) == 1, f"release 단계 이름 '{fragment}' 이 {len(matches)}개입니다"
    return matches[0]


def test_release_reconciles_the_web_artifact_across_every_shipped_copy() -> None:
    """source·dist·installed·portable 네 사본을 **한자리에서** 대조한다(#383).

    사본마다 따로 통과시키는 것으로는 "어느 하나만 다른" 경우가 드러나지 않는다. 그래서
    네 identity 를 모으는 단계가 있는지, 그리고 그 단계가 넷을 실제로 요구하는지를 센다.

    판정 자체는 R5-03 에서 ``scripts/reconcile_shipped_copies.py`` 로 올라갔다(같은 판정이
    패키징 게이트에도 필요해졌고, 인라인으로 두면 둘 중 하나가 낡는다). 그래서 여기서 세는
    것은 **그 소유자를 이 순서로 부르는가**와 **넷을 선언하는가**로 바뀐다 — 계약의 대상이
    바뀌는 것이지 계약이 사라지는 것이 아니다.
    """
    reconcile = _release_step("Reconcile web artifact identity")["run"]

    assert "reconcile_shipped_copies.py" in reconcile, "사본 대조 소유자를 부르지 않습니다"
    assert "--expect source,dist,installed,portable" in reconcile, (
        "대조 대상 사본 집합을 넷으로 선언하지 않습니다"
    )
    assert "--build-metadata build\\version\\build-metadata.json" in reconcile, (
        "source 사본은 검증된 seal 에서 온다"
    )
    for name in ("dist", "installed", "portable"):
        assert f"--copy ('{name}=" in reconcile, f"{name} 사본 증거를 넘기지 않습니다"
    assert "throw" in reconcile, "identity 불일치가 실패로 이어지지 않습니다"
    assert "release-evidence.json" in reconcile
    # 인라인 재조립으로 되돌아가면 판정이 둘이 된다.
    assert "Sort-Object -Unique" not in reconcile


def test_installed_copy_is_verified_before_it_is_uninstalled() -> None:
    """순서가 계약이다 — 제거한 뒤에는 설치본에 무엇이 실렸는지 물을 수 없다.

    이 단언이 없으면 검증 줄이 uninstall 뒤로 밀려도 "검증한다"는 선언은 그대로 남는다.
    """
    smoke = _release_step("Smoke test install and uninstall")["run"]

    verify_at = smoke.index("verify_packaged_web.py")
    uninstall_at = smoke.index("Uninstall-Product $fillerDir")
    assert verify_at < uninstall_at, "설치본 검증이 제거 뒤로 밀렸습니다"
    assert "installed.json" in smoke


def test_portable_zip_is_verified_after_the_round_trip() -> None:
    """사용자가 여는 것은 dist\\ 가 아니라 zip 을 푼 결과다."""
    package = _release_step("Package portable bundles")["run"]

    assert package.index("Compress-Archive") < package.index("Expand-Archive")
    assert package.index("Expand-Archive") < package.index("verify_packaged_web.py")
    assert "portable.json" in package


def test_checksums_cover_the_descriptive_assets_too() -> None:
    """메타데이터·증거 JSON 도 SHA256SUMS 대상이다 — 검증 못 할 것은 함께 싣지 않는다."""
    checksums = _release_step("Create checksums")["run"]

    for pattern in ("*.exe", "*.zip", "*.json"):
        assert f"installer-dist\\{pattern}" in checksums, f"{pattern} 이 해시 대상이 아닙니다"


def test_build_metadata_carries_the_frontend_identity() -> None:
    """릴리스 자산 목록과 생성기가 같은 계약을 본다.

    자산 목록에만 넣고 생성기가 안 만들면 publish 가 조용히 그 파일을 빠뜨린다 —
    두 끝을 함께 센다.
    """
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    generator = (ROOT / "scripts" / "generate_build_metadata.py").read_text(
        encoding="utf-8"
    )

    assert "installer-dist/release-evidence.json" in release
    assert "installer-dist/build-metadata.json" in release
    for key in (
        "uv_lock_sha256",
        '"web"',
        "artifact_id",
        "tree_sha256",
        "toolchain",
        # 만든 도구(toolchain)와 **실은 런타임**(runtime_packages)은 다른 사실이다(R5-03).
        # 후자가 없으면 받은 사람이 "이 릴리스가 어떤 React 를 실었나"를 물을 방법이 없다.
        "runtime_packages",
    ):
        assert key in generator, f"build metadata 에 {key} 가 없습니다"
    assert "--require-web" in generator
    assert "runtime_packages" in release, (
        "출하 런타임이 release-evidence 로 이어지지 않습니다"
    )


def test_release_ships_the_filler_only_and_says_so() -> None:
    """CLI 는 출하 제품이 아니다 — 조용한 누락이 아니라 **의도**임을 못박는다.

    코어 CLI 는 헤드리스 테스터이자 기반이고(cli-role 결정), 품질 CI 는 그 역할 때문에
    ``-Target all`` 로 함께 빌드해 검증한다. 그러나 릴리스는 filler 만 낸다. 두 표면이
    다른 것이 결정이라는 사실을 여기에 적어두지 않으면, 다음 사람이 "빠뜨렸다"고 읽고
    조용히 늘리거나 거꾸로 품질 CI 쪽을 줄인다.
    """
    quality, _ = _workflow()
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    installer = (ROOT / "package-installer.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "build.ps1").read_text(encoding="utf-8")

    assert "-Target all" in quality, "품질 CI 는 cli 까지 빌드해 검증한다"
    assert "hwpx-cli" not in release, "릴리스가 CLI 산출물을 싣고 있습니다"
    assert "-Target all" not in release
    assert "[ValidateSet('all', 'filler')]" in installer
    assert "[ValidateSet('all', 'filler')]" in runner


def test_installer_and_signing_remain_release_only() -> None:
    quality, _ = _workflow()
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for release_only in (
        "package-installer.ps1",
        "WINDOWS_CERTIFICATE_BASE64",
        "Install Inno Setup",
    ):
        assert release_only not in quality
        assert release_only in release


def test_cli_forces_utf8_for_redirected_windows_output(monkeypatch) -> None:
    from hwpxfiller import cli

    class RedirectedStream(io.StringIO):
        options: dict[str, str] | None = None

        def reconfigure(self, **kwargs: str) -> None:
            self.options = kwargs

    stdout = RedirectedStream()
    stderr = RedirectedStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as stopped:
        cli.main(["--help"])

    expected = {"encoding": "utf-8", "errors": "backslashreplace"}
    assert stopped.value.code == 0
    assert stdout.options == expected
    assert stderr.options == expected
