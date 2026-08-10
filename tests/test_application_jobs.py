"""Application job 계약(:mod:`hwpxfiller.application.jobs`)의 owner — in-memory 헤드리스 증명.

새 파일 사유: P2-21 #569 가 세운 **새 durable product boundary**(Application semantic
port + durable mutation use case)의 owner 다(write-lean 예외 조항). concrete
JobRegistry·파일·slug·잠금 **없이** 포트의 구조적(덕타이핑) 구현만으로 전 use case 가
실행됨을 증명한다 — 포트 표면에 물리(lock·``Path``·JSON·suffix)가 새면 이 in-memory
구현이 성립하지 않아 여기가 가장 먼저 부러진다.

concrete 의미(원자성·slug 가드·휴지통 보존·시각 정합·잠금 안 재판정)는 기존 owner
(``tests/test_job.py``·컨트롤러 테스트)가 계속 진다 — 이 파일은 값 단언을 되풀이하지
않고 **경계의 성립**만 잰다.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from hwpxfiller.application.jobs import (
    CORRUPT_PATH_REJECT,
    CorruptJobEntry,
    assign_group,
    clone_job,
    delete_job,
    disband_group,
    remove_corrupt_entry,
    rename_group,
    rename_job,
    restore_job,
    set_favorite,
    soft_delete_job,
    stamp_run_completion,
    update_tags,
)
from hwpxfiller.core.job import Job


class InMemoryJobStore:
    """:class:`~hwpxfiller.application.jobs.JobStorePort` 의 구조적 구현 — dict 기반.

    파일도 slug 도 잠금도 없다. 의미는 concrete(:class:`JobRegistry`)의 문서를 미러하되
    검증하려는 것은 「포트가 semantic 하다」는 사실이지 물리 세부가 아니다.
    """

    def __init__(self) -> None:
        self.jobs: "dict[str, Job]" = {}
        self.trash: "dict[int, Job]" = {}
        self._slot_seq = 0
        self.corrupt: "dict[str, str]" = {}  # token → error

    # ------------------------------------------------------------ port 구현
    def mutate(self, name, change):
        job = self.jobs[name]  # 부재는 KeyError 로 loud(테스트 스토어)
        change(job)
        return job

    def stamp_last_run(self, name, when, *, rules=None):
        def _stamp(job):
            job.last_run_at = when
            if rules is not None:
                job.reviewed_rules = dict(rules)

        return self.mutate(name, _stamp)

    def set_favorite(self, name, favorited, when=None):
        def _set(job):
            if favorited:
                if not job.favorited_at:
                    job.favorited_at = when or "T0"
            else:
                job.favorited_at = ""

        return self.mutate(name, _set)

    def rename(self, name, new_name):
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("이름이 비어 있습니다")
        if new_name != name and new_name in self.jobs:
            raise ValueError(f"이름 '{new_name}' 은(는) 이미 사용 중입니다")
        job = self.jobs.pop(name)
        job.name = new_name
        self.jobs[new_name] = job

    def clone(self, name):
        src = self.jobs[name]
        candidate = f"{name} (복사본)"
        self.jobs[candidate] = replace(
            src, name=candidate, last_run_at="", favorited_at="", reviewed_rules={},
        )
        return candidate

    def delete(self, name):
        self.jobs.pop(name, None)

    def soft_delete(self, name):
        if name not in self.jobs:
            raise ValueError(f"작업을 찾을 수 없습니다: {name}")
        self._slot_seq += 1
        self.trash[self._slot_seq] = self.jobs.pop(name)
        return self._slot_seq  # 불투명 슬롯 — 호출자는 구조를 모른 채 되돌려준다

    def restore_soft_deleted(self, slot):
        job = self.trash.pop(slot)
        self.jobs[job.name] = job
        return job.name

    def set_group(self, name, group):
        def _set(job):
            job.group = group.strip()

        self.mutate(name, _set)

    def rename_group(self, name, new_name):
        members = [j for j in self.jobs.values() if j.group == name]
        for job in members:
            job.group = new_name
        return len(members)

    def disband_group(self, name):
        return self.rename_group(name, "")

    def remove_corrupt_entry(self, token):
        if token not in self.corrupt:
            raise ValueError(CORRUPT_PATH_REJECT)
        del self.corrupt[token]


def test_use_cases_complete_against_in_memory_port():
    """저장→스탬프→즐겨찾기→태그→그룹→rename→clone→soft_delete→restore→delete 전 왕복."""
    store = InMemoryJobStore()
    store.jobs["공고"] = Job(name="공고")

    job = stamp_run_completion(store, "공고", "2026-08-10T09:00:00", rules={"연결": "f1"})
    assert (job.last_run_at, job.reviewed_rules) == ("2026-08-10T09:00:00", {"연결": "f1"})

    assert set_favorite(store, "공고", True, "2026-08-10T09:01:00").favorited_at == (
        "2026-08-10T09:01:00"
    )
    assert set_favorite(store, "공고", False).favorited_at == ""

    tags = {"지역": "본청"}
    assert update_tags(store, "공고", tags).tags == {"지역": "본청"}
    tags["지역"] = "대전"  # use case 는 사본을 싣는다 — 호출자 dict 변이가 durable 로 안 샌다
    assert store.jobs["공고"].tags == {"지역": "본청"}

    assign_group(store, "공고", "2026")
    store.jobs["둘째"] = Job(name="둘째", group="2026")
    assert store.jobs["공고"].group == "2026"
    assert rename_group(store, "2026", "2027") == 2
    assert {j.group for j in store.jobs.values()} == {"2027"}
    assert disband_group(store, "2027") == 2
    assert {j.group for j in store.jobs.values()} == {""}

    rename_job(store, "공고", "공고서")
    assert "공고" not in store.jobs and store.jobs["공고서"].name == "공고서"

    cloned = clone_job(store, "공고서")
    assert cloned == "공고서 (복사본)" and store.jobs[cloned].last_run_at == ""

    slot = soft_delete_job(store, "공고서")
    assert "공고서" not in store.jobs
    assert restore_job(store, slot) == "공고서" and "공고서" in store.jobs

    delete_job(store, cloned)
    assert cloned not in store.jobs


def test_remove_corrupt_entry_round_trips_opaque_tokens():
    """손상 항목 값 객체의 token 왕복 — 목록 밖 token 은 포트 계약 문구로 loud."""
    store = InMemoryJobStore()
    entry = CorruptJobEntry(file_name="깨진.job.json", token="불투명-토큰-1", error="broken")
    store.corrupt[entry.token] = entry.error

    with pytest.raises(ValueError, match="목록에 없는"):
        remove_corrupt_entry(store, "다른-토큰")
    assert store.corrupt  # 거절은 아무것도 지우지 않는다

    remove_corrupt_entry(store, entry.token)
    assert store.corrupt == {}
