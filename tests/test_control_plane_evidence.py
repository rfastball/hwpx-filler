"""SG-03(#735) C9 — historical Profile/Plan/Configuration evidence 의 의미·bytes 불변.

canonical encoder 가 golden vector 를 재현한다는 사실은 이미
``test_canonical_execution_encoding.py::test_golden_vector_reproduced`` 와
``test_slot_selection.py`` 가 (code == golden) 으로 판정한다. 그 두 테스트만으로는 code 와
golden 을 **함께** 다시 쓰면 초록이 유지된다 — golden 자체가 historical 상수에 묶여 있지 않기
때문이다. 이 파일은 나머지 anchor 를 건다: v1 golden 파일 bytes 는 historical 로 고정하고,
current shipping Profile identity·manifest version 은 별도로 pin 한다. 그래서 규칙 개정은 새
identity 를 써야 하며 historical evidence 를 조용히 rewrite 할 수 없다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION as EXECUTION_CANONICAL_VERSION,
)
from hwpxfiller.application.execution_structure import encode_execution_structure
from hwpxfiller.domain.slot_selection import (
    CANONICAL_ENCODING_VERSION as SELECTION_CANONICAL_VERSION,
    SELECTION_SET_SCHEMA_VERSION,
)
from hwpxfiller.external.template_inspection import (
    HWPX_QUALIFICATION_PROFILE,
    hwpx_qualification_manifest,
    inspect_hwpx_qualification,
)

_FIXTURES = Path(__file__).parent / "fixtures"

#: 대표 slot 포함 fixture — build_slot_probe 로 조립된 canonical HWPX(slot 1·option 2).
_QUALIFICATION_FIXTURE = Path(__file__).parent / "corpus" / "slots" / "canonical.hwpx"

#: frozen ``hwpx-template-qualification-v4`` identity 아래 ``inspect_hwpx_qualification`` 의
#: **행동**(structure/diagnostics/composition projection)을 대표 fixture 에서 뽑은 안정 semantic
#: digest. version 문자열만 pin 하고 payload 를 비워 두면 같은 identity 로 판정 규칙이 바뀌어도
#: 초록이 유지되는 창이 열린다 — 이 digest 가 그 창을 닫는다. 규칙 개정이면 identity 버전과 이
#: digest 를 **함께** 올린다.
#:
#: v3→v4(#773)에서 함께 올렸다: 같은 inspection 이 이제 composition-ready execution structure 도
#: 낸다(occurrence·region·envelope·resolver fact). 그래서 digest 는 그 payload 까지 덮는다 —
#: composition fact 가 조용히 달라지면 여기서 RED 다.
_QUALIFICATION_BEHAVIOR_DIGEST = (
    "1534fd3d203a59bdb560d0c74aedf6ffebf87bfdfc2c65d4b9991abdad8187e7"
)

#: v1 로 출하된 golden vector 파일의 정확한 bytes(SHA-256). 재현 판정(code==golden)은 기존
#: 테스트가 지고, 여기서는 golden 자체가 역사값이라 못 바뀐다는 것을 pin 한다.
_GOLDEN_SHA256 = {
    "execution_canonical_v1_golden.json": (
        "253849a93d8c03f7f275ca82a67196ecaa199cf63384f7a86754e029133f0615"
    ),
    "slot_selection_v1_golden.json": (
        "f2ac6b526ece7635a1c907151ba2ffe9026a264ac7a8f00f7792902a249bc023"
    ),
}


def test_historical_golden_bytes_frozen() -> None:
    for name, expected in _GOLDEN_SHA256.items():
        actual = hashlib.sha256((_FIXTURES / name).read_bytes()).hexdigest()
        assert actual == expected, (
            f"{name} 의 bytes 가 바뀌었다 — historical execution/selection evidence 는 불변이다. "
            "규칙 개정이면 새 버전 벡터를 추가하되 v1 golden 은 그대로 두고, 이 상수를 손대는 "
            "것은 의도적 rewrite 임을 이슈로 남긴다."
        )


def test_canonical_encoding_versions_pinned() -> None:
    # 버전 문자열이 바뀌면 같은 wire 를 다른 의미로 재해석하는 문이 열린다 — fail-closed.
    assert EXECUTION_CANONICAL_VERSION == "execution-canonical/v1"
    assert SELECTION_CANONICAL_VERSION == "slot-selection-canonical/v1"
    assert SELECTION_SET_SCHEMA_VERSION == "slot-selection-set/v1"


def test_shipping_profile_identity_and_manifest_versions_pinned() -> None:
    assert HWPX_QUALIFICATION_PROFILE.id == "hwpx-template-qualification-v4"
    manifest = hwpx_qualification_manifest("2020-01-01T00:00:00")
    assert manifest.qualification_profile_id == "hwpx-template-qualification-v4"
    assert manifest.media == "hwpx"
    assert manifest.adapter_contract_version == "hwpx-inspection-v4"
    assert manifest.product_rule_version == "hwpx-qualification-rules-v4"
    assert manifest.operation_alphabet_version == "hwpx-operations-v1"
    assert manifest.projection_schema_version == "hwpx-structure-projection-v4"


def test_shipping_profile_inspection_behavior_frozen() -> None:
    # frozen identity 를 그 **행동**에 묶는다: 대표 fixture 의 inspection 결과 semantic digest 가
    # v4 값이어야 한다. identity 문자열이 그대로여도 판정이 바뀌면 이 digest 가 RED 된다.
    # execution structure 는 canonical encoder 로 편다 — `asdict` 는 frozen mappingproxy 를 못
    # 넘고(deepcopy 불가), 이 encoder 가 애초에 payload/digest 의 정본 seam 이다.
    inspection = inspect_hwpx_qualification(_QUALIFICATION_FIXTURE.read_bytes())
    assert inspection.structure is not None and inspection.diagnostics == ()
    assert inspection.execution_structure is not None
    payload = json.dumps(
        {
            "structure": asdict(inspection.structure),
            "diagnostics": [asdict(d) for d in inspection.diagnostics],
            "execution_structure": encode_execution_structure(
                inspection.execution_structure
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == _QUALIFICATION_BEHAVIOR_DIGEST, (
        "frozen hwpx-template-qualification-v4 identity 아래 inspection 행동이 바뀌었다 — 규칙 "
        "개정이면 profile identity 버전과 이 digest 를 함께 올리고 이슈로 남긴다."
    )
