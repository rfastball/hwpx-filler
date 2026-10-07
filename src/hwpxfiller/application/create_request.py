"""Generate-request capability when execution preparation can happen in the request."""

from __future__ import annotations

from .automatic_seal_orchestration import CHECKING
from .document_creation_workbench import (
    DocumentCreationWorkbenchObservation,
    EXECUTION_NO_EVIDENCE,
    EXECUTION_STALE,
    REVIEW_DELIVERY,
)


def can_request_create(observation: DocumentCreationWorkbenchObservation) -> bool:
    if observation.create_documents_enabled:
        return True
    blockers = set(observation.blockers)
    return (
        observation.orchestration.state != CHECKING
        and bool(blockers & {EXECUTION_NO_EVIDENCE, EXECUTION_STALE})
        and blockers <= {EXECUTION_NO_EVIDENCE, EXECUTION_STALE, REVIEW_DELIVERY}
    )
