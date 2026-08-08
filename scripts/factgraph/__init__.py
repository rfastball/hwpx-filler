"""factgraph — P1 전수 계측의 공용 수집 기반(#512 P1-01).

스키마·폐포·기반 수집기·runtime trace seam·심볼 인벤토리를 든다. P1-02A~E 의 축별
계측기는 이 패키지를 import 해 같은 어휘로 shard 를 만들고, 중앙 합성(P1-03)이
``merge_shards`` 로 재현 가능하게 합친다.
"""

from .closure import Closure, ModuleFile, production_closure, wheel_package_roots
from .collect import collect_facts, collect_symbols
from .inventory import INVENTORY_REL_PATH, REGEN_COMMAND, check, render, rewrite
from .runtime_trace import record_calls
from .schema import (
    GRADES,
    RELATIONS,
    SCHEMA_VERSION,
    SYMBOL_KINDS,
    Evidence,
    Fact,
    FactGraphError,
    MergedGraph,
    Provenance,
    Shard,
    Symbol,
    edge_grades,
    is_symbol_ref,
    make_shard,
    merge_shards,
    parse_symbol_id,
    symbol_id,
)

__all__ = [
    "GRADES",
    "INVENTORY_REL_PATH",
    "REGEN_COMMAND",
    "RELATIONS",
    "SCHEMA_VERSION",
    "SYMBOL_KINDS",
    "Closure",
    "Evidence",
    "Fact",
    "FactGraphError",
    "MergedGraph",
    "ModuleFile",
    "Provenance",
    "Shard",
    "Symbol",
    "check",
    "collect_facts",
    "collect_symbols",
    "edge_grades",
    "is_symbol_ref",
    "make_shard",
    "merge_shards",
    "parse_symbol_id",
    "production_closure",
    "record_calls",
    "render",
    "rewrite",
    "symbol_id",
    "wheel_package_roots",
]
