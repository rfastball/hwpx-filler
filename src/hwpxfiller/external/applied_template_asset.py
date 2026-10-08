"""App-owned editable template file backed by an exact applied Candidate blob."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from ..application.jobs import JobStorePort, load_job
from ..application.slot_configuration_context import resolve_exact_applied_template_input
from .candidate_store import CandidateObjectStore
from .qualification_store import QualificationObjectStore
from .work_template_store import AtomicWorkTemplateStateStore, WorkAggregateNotFound


class _WorkStateReadPort:
    def __init__(self, store: AtomicWorkTemplateStateStore) -> None:
        self._store = store

    def load(self, work_id: str):
        try:
            return self._store.load(work_id)
        except WorkAggregateNotFound:
            return None


class AppliedTemplateAsset:
    def __init__(
        self,
        root: Path,
        registry: JobStorePort,
        works: AtomicWorkTemplateStateStore,
        candidates: CandidateObjectStore,
        qualifications: QualificationObjectStore,
    ) -> None:
        self._root = root
        self._registry = registry
        self._works = works
        self._candidates = candidates
        self._qualifications = qualifications

    def _path(self, work_id: str, template_path: str) -> Path:
        return (
            self._root / "applied" / hashlib.sha256(work_id.encode()).hexdigest()
            / Path(template_path).name
        )

    def _write_blob(self, path: Path, exact) -> None:
        blob = self._candidates.get_blob(exact.exact_content_digest)
        if blob.media != exact.media:
            raise ValueError("적용된 템플릿의 형식을 확인할 수 없습니다")
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            pending.write_bytes(blob.exact_bytes)
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)

    def _materialize(self, job, path: Path, *, replace: bool) -> None:
        work_id = job.authority_id
        aggregate = self._works.load(work_id)
        exact = resolve_exact_applied_template_input(
            _WorkStateReadPort(self._works), self._qualifications, self._candidates,
            work_id, aggregate.work.current_template_application_id,
        )
        if exact.media != job.media:
            raise ValueError("적용된 템플릿의 형식을 확인할 수 없습니다")
        if job.template_path == str(path) and not path.is_file():
            raise FileNotFoundError(f"적용된 템플릿 파일을 찾을 수 없습니다: {path}")
        if (replace and job.template_path != str(path)) or not path.is_file():
            self._write_blob(path, exact)

    def adopt(self, job_name: str, *, replace: bool = False):
        """Retire the old link using applied bytes; keep normal in-app edits intact."""
        job = load_job(self._registry, job_name)
        work_id = job.authority_id
        if not work_id or not self._works.exists(work_id):
            return job
        path = self._path(work_id, job.template_path)
        try:
            self._materialize(job, path, replace=replace)
        except Exception:
            # Applied authority has already committed: never leave its old source linked.
            if job.template_path != str(path):
                self._registry.relink_template(
                    job_name, str(path), expected=(work_id, job.template_path)
                )
            raise
        if job.template_path != str(path):
            job = self._registry.relink_template(
                job_name, str(path), expected=(work_id, job.template_path)
            )
        return job

    def migrate(self) -> None:
        """Existing works are restored from their applied blob, never their old path."""
        for job in self._registry.list_jobs():
            if job.authority_id and self._works.exists(job.authority_id):
                try:
                    self.adopt(job.name)
                except Exception:  # noqa: BLE001 - one corrupt Work must not prevent other jobs opening.
                    # Selecting this Work retries the verified read and fails loudly.
                    current = load_job(self._registry, job.name)
                    if current.template_path != str(
                        self._path(current.authority_id, current.template_path)
                    ):
                        raise
