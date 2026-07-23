"""JobRegistry 프로세스 topology 계약(#192).

지원 topology는 한 작업 디렉터리당 writer 프로세스 하나다. 앱은 홈 단일 인스턴스 가드를
먼저 잡고, CLI는 JobRegistry를 사용하지 않는다. 같은 프로세스 안의 여러 registry instance는
경로 공유 RLock을 쓰며, 다른 프로세스의 두 번째 writer는 파일 변경 전에 loud 실패한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from hwpxfiller.core.job import Job, JobRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_same_directory_instances_share_read_modify_write_boundary(tmp_path) -> None:
    """두 registry instance의 stale read가 서로의 필드를 되돌리지 않는다."""
    first = JobRegistry(tmp_path / "jobs")
    second = JobRegistry(tmp_path / "jobs")
    first.save(Job(name="공고서", template_path="t.hwpx", filename_pattern="원래"))

    held = threading.Event()
    release = threading.Event()
    entered = threading.Event()

    def stamp() -> None:
        with first.write_lock():
            job = first.load("공고서")
            held.set()
            release.wait(3)
            job.last_run_at = "2026-07-22T12:00:00"
            first.save(job, allow_overwrite=True)

    def edit() -> None:
        with second.write_lock():
            job = second.load("공고서")
            job.filename_pattern = "동시 편집"
            second.save(job, allow_overwrite=True)
            entered.set()

    one = threading.Thread(target=stamp)
    two = threading.Thread(target=edit)
    one.start()
    assert held.wait(3)
    two.start()
    assert not entered.wait(0.2), "다른 registry instance가 공유 임계구역을 우회했습니다."
    release.set()
    one.join(3)
    two.join(3)
    assert not one.is_alive() and not two.is_alive()

    saved = first.load("공고서")
    assert saved.last_run_at == "2026-07-22T12:00:00"
    assert saved.filename_pattern == "동시 편집"


def test_second_process_writer_fails_before_touching_job_files(tmp_path) -> None:
    """다른 프로세스 writer는 고유 파일 생성도 기존 파일 변경도 하지 못한다."""
    directory = tmp_path / "jobs"
    owner = JobRegistry(directory)
    owner.save(Job(name="기존", template_path="owner.hwpx"))
    before = owner.path_for("기존").read_bytes()

    code = r"""
import sys
from pathlib import Path
from hwpxfiller.core.job import Job, JobRegistry, JobRegistryOwnershipError

registry = JobRegistry(Path(sys.argv[1]))
try:
    registry.save(Job(name="침입", template_path="intruder.hwpx"))
except JobRegistryOwnershipError as exc:
    print(type(exc).__name__ + ": " + str(exc))
    raise SystemExit(0)
raise SystemExit(9)
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", code, str(directory)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "JobRegistryOwnershipError" in result.stdout
    assert "다른 HWPX Filler 프로세스" in result.stdout
    assert owner.path_for("기존").read_bytes() == before
    assert not owner.path_for("침입").exists()


def test_write_state_ownership_is_per_process_not_inherited(monkeypatch) -> None:
    """#234 리뷰 — POSIX fork 자식은 ``_owner``(핸들/스트림)를 그대로 상속하는데, 조기
    반환이 그걸 신뢰하면 부모·자식이 무경보 동시 writer 가 된다(RLock 은 프로세스-로컬).
    소유권 판정은 획득 PID 와 묶여야 하고, PID 가 다르면 재획득을 시도해야 한다."""
    from hwpxfiller.core.job import _RegistryWriteState

    state = _RegistryWriteState("test-key")
    claims: list[str] = []
    monkeypatch.setattr(state, "_claim_windows_mutex", lambda: claims.append("claim"))
    monkeypatch.setattr(state, "_claim_posix_lock", lambda: claims.append("claim"))

    state.claim_process_ownership()          # 최초 획득
    assert claims == ["claim"] and state._owner_pid == os.getpid()
    state._owner = object()
    state.claim_process_ownership()          # 같은 프로세스 재호출 = no-op
    assert claims == ["claim"]

    state._owner_pid = os.getpid() + 1       # fork 자식 시뮬레이션(상속 owner + 남의 PID)
    state.claim_process_ownership()
    assert claims == ["claim", "claim"], "상속 소유를 신뢰하지 말고 재획득해야 한다"
    assert state._owner_pid == os.getpid()
    assert state._owner is None              # 상속분 참조는 끊되(부모 락 보존) 닫지 않는다


def test_product_entrypoints_match_documented_single_writer_topology() -> None:
    """웹앱은 registry 생성 전에 단일 인스턴스를 잡고 CLI는 registry를 열지 않는다."""
    app = (ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    main = app[app.index("def main() -> int:"):]
    assert main.index("single_instance.acquire(") < main.index("frontend = WebFrontend(")

    cli = (ROOT / "src" / "hwpxfiller" / "cli.py").read_text(encoding="utf-8")
    assert "JobRegistry" not in cli

    policy = (ROOT / "docs" / "PROCESS_TOPOLOGY.md").read_text(encoding="utf-8")
    assert "한 디렉터리당 writer 프로세스 하나" in policy
    assert "JobRegistryOwnershipError" in policy
