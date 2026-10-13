"""현재 생성의 세션별 저장 위치와 충돌 정책 입력."""

import pytest

from hwpxfiller.application.document_creation_vocabulary import (
    COLLISION_POLICIES,
    DEFAULT_COLLISION_POLICY,
)
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent


def test_default_delivery_intent_uses_the_current_collision_policy():
    intent = RunDeliveryIntent(output_directory="C:/out")
    assert intent.collision_policy == DEFAULT_COLLISION_POLICY
    assert intent.collision_policy in COLLISION_POLICIES


@pytest.mark.parametrize("directory,policy", [("", DEFAULT_COLLISION_POLICY), ("C:/out", "NOPE")])
def test_invalid_delivery_intent_is_rejected(directory: str, policy: str):
    with pytest.raises(ValueError):
        RunDeliveryIntent(output_directory=directory, collision_policy=policy)
