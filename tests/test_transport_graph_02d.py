"""P1-02D transport 원장의 드리프트·독립 분모·판별력 게이트(#516).

실물에서 양성을 세고, **파싱한 원장의 변형 사본**으로 음성을 각각 센다 — endpoint 추가·
payload key drift·consumer ghost·snapshot producer 미분류·채널 유실이 각각 다른 문제
문자열로 무는지를 확인한다(전역 치환 금지 — 변형은 파싱된 문서의 한 좌표만 건드린다).

기반 사실 digest 는 02A 원장의 핀과 **교차 단언**한다: digest↔저장소 재검증은 02A 게이트의
단독 소유라 여기서 재계측하지 않는다(같은 판정을 두 곳에 두지 않는다).
"""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path

import pytest
from _web_source import SOURCE_ROOT
from factgraph.static_graph import LEDGER_REL_PATH as STATIC_LEDGER_REL_PATH
from factgraph.transport_graph import (
    LEDGER_REL_PATH,
    REGEN_COMMAND,
    DispatchEndpoint,
    PushChannel,
    SnapshotField,
    _controller_classes,
    _dispatch_pair_oracle,
    _runtime_snapshot_fields,
    channel_problems,
    check,
    dispatch_pair_evidence,
    endpoint_problems,
    host_method_problems,
    parse_ledger,
    snapshot_oracle_inventory,
    snapshot_problems,
    vocabulary_problems,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = SOURCE_ROOT.relative_to(ROOT)


@pytest.fixture(scope="module")
def document() -> "dict[str, object]":
    return tomllib.loads((ROOT / LEDGER_REL_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def inventory(document: "dict[str, object]"):
    return parse_ledger(document)


@pytest.fixture(scope="module")
def controllers() -> "dict[str, type]":
    return _controller_classes(ROOT)


@pytest.fixture(scope="module")
def runtime_fields() -> "dict[str, tuple[str, ...]]":
    return _runtime_snapshot_fields(ROOT)


@pytest.fixture(scope="module")
def snapshot_oracle(controllers):
    """같은 source checkout 을 겨누는 원장 mutation들이 독립 분모 측정을 공유한다."""
    return snapshot_oracle_inventory(ROOT, controllers=controllers)


# ---------------------------------------------------------------- 양성 — 실물


def test_committed_ledger_has_no_drift() -> None:
    assert check(ROOT) == [], f"`{REGEN_COMMAND}` 로 원장을 재생성해야 한다"


def test_base_digest_cross_anchors_the_02a_ledger(document: "dict[str, object]") -> None:
    """02A 와 02D 가 **같은 baseline src/ 측정** 위에 서 있다 — 두 원장의 핀 일치.

    digest 가 실제 저장소와 같은지는 02A 게이트가 단독으로 재계측한다. 여기서 그것을
    한 번 더 돌리면 같은 판정이 두 곳에 살고, 둘이 갈리는 날 어느 쪽이 정본인지부터
    싸우게 된다 — 이 게이트는 연결(같은 값인가)만 진다.
    """
    static_doc = tomllib.loads((ROOT / STATIC_LEDGER_REL_PATH).read_text(encoding="utf-8"))
    digests = document["digests"]
    assert isinstance(digests, dict)
    assert digests["base_facts_02a"] == static_doc["digests"]["base_facts"]
    assert document["baseline"]["git_sha"] == static_doc["baseline"]["git_sha"]  # type: ignore[index]


def test_endpoint_rows_close_against_the_registry(inventory, controllers) -> None:
    assert endpoint_problems(ROOT, inventory.endpoints, controllers=controllers) == []


def test_host_method_rows_close_against_webfrontend_and_bridge(inventory) -> None:
    assert (
        host_method_problems(
            ROOT,
            inventory.host_methods,
            inventory.bridge_consumed_product,
            inventory.bridge_consumed_selftest,
        )
        == []
    )


def test_snapshot_rows_close_with_zero_unattributed_fields(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    assert (
        snapshot_problems(
            ROOT,
            inventory.snapshot_fields,
            controllers=controllers,
            runtime_fields=runtime_fields,
            oracle_inventory=snapshot_oracle,
        )
        == []
    )


def test_channel_rows_close(inventory, controllers) -> None:
    assert channel_problems(ROOT, inventory.channels, controllers=controllers) == []


def test_vocabulary_and_input_anchors_close(inventory) -> None:
    assert vocabulary_problems(ROOT, inventory) == []


def test_registry_enables_exactly_the_prefix_dispatch_closure(
    inventory, document: "dict[str, object]"
) -> None:
    """02A 인계의 사실화 — 복원 폐포(``_do_*``)와 registry 가 켜는 부분집합이 **일치**한다.

    dead handler(등록 안 된 ``_do_``)와 handler 없는 registry 액션이 각각 0 이고, 02A 원장의
    prefix dispatch 복원 edge 총수가 이 폐포의 합과 같다 — 두 원장이 같은 세계를 세고 있다.
    """
    for row in inventory.enablement:
        assert row.dead_handlers == (), row
        assert row.actions_without_handler == (), row
        assert row.handlers == row.actions == row.enabled, row
    static_doc = tomllib.loads((ROOT / STATIC_LEDGER_REL_PATH).read_text(encoding="utf-8"))
    prefix_restored = sum(
        row["restored"] for row in static_doc.get("dispatch", []) if row["kind"] == "prefix"
    )
    assert prefix_restored == sum(row.enabled for row in inventory.enablement)


def test_counts_section_restates_the_rows(inventory, document: "dict[str, object]") -> None:
    """[counts] 는 행의 재진술이다 — 요약이 본문과 갈리면 요약을 믿은 소비자가 틀린다."""
    counts = document["counts"]
    assert isinstance(counts, dict)
    assert counts["actions"] == len(inventory.endpoints)
    assert counts["screens"] == len(inventory.enablement)
    assert counts["host_methods_public"] == len(inventory.host_methods)
    internal = [m for m in inventory.host_methods if m.consumer == "host_internal"]
    assert counts["host_methods_internal"] == len(internal)
    assert counts["host_methods_product"] == len(inventory.host_methods) - len(internal)
    assert counts["snapshot_fields"] == len(inventory.snapshot_fields)
    assert counts["snapshot_fields_runtime_observed"] == sum(
        1 for f in inventory.snapshot_fields if f.runtime_observed
    )
    assert counts["snapshot_fields_conditional"] == sum(
        1 for f in inventory.snapshot_fields if not f.runtime_observed
    )
    for consumer in ("product", "selftest_only", "none_found"):
        assert counts[f"snapshot_fields_{consumer}"] == sum(
            1 for field in inventory.snapshot_fields if field.consumer == consumer
        )
    assert sum(
        counts[f"snapshot_fields_{consumer}"]
        for consumer in ("product", "selftest_only", "none_found")
    ) == counts["snapshot_fields"]
    for kind in ("product_event", "partial_push", "selftest_host_op"):
        assert counts[f"channels_{kind}"] == sum(1 for c in inventory.channels if c.kind == kind)
    product_events = [c for c in inventory.channels if c.kind == "product_event"]
    assert counts["product_event_fields"] == sum(len(c.fields) for c in product_events)
    assert counts["product_event_fields_conditional"] == sum(
        field.endswith("?") for c in product_events for field in c.fields
    )
    assert counts["product_event_consumer_zero"] == sum(
        not c.consumer_evidence for c in product_events
    )
    assert counts["consumer_zero_actions"] == sum(
        1 for e in inventory.endpoints if e.consumer == "none_found"
    )
    assert counts["selftest_only_actions"] == sum(
        1 for e in inventory.endpoints if e.consumer == "selftest_only"
    )
    zero = document["consumer_zero"]
    assert isinstance(zero, dict)
    assert list(zero["actions"]) == [
        f"{e.screen}/{e.action}" for e in inventory.endpoints if e.consumer == "none_found"
    ]
    assert list(zero["snapshot_fields"]) == [
        f"{f.screen}.{f.field}"
        for f in inventory.snapshot_fields
        if f.consumer == "none_found"
    ]
    assert list(zero["host_internal_methods"]) == [m.name for m in internal]


def test_conditional_emission_is_captured_not_silently_dropped(inventory) -> None:
    """빈 상태 실측만 들면 조용히 빠졌을 조건부 필드가 원장에 **선언으로** 서 있다.

    표본은 작업대 열림 상태에서만 방출되는 ``fmt_options`` — 소스에서 손으로 확인한 실물이다
    (닫힘 골격 update 에는 없고 열림 update 에만 있다). 이 단언이 죽으면 정적 합집합 추출기가
    조건부 방출을 놓치기 시작한 것이다.
    """
    rows = {(f.screen, f.field): f for f in inventory.snapshot_fields}
    sample = rows.get(("workbench", "fmt_options"))
    assert sample is not None and not sample.runtime_observed
    always = rows.get(("workbench", "open"))
    assert always is not None and always.runtime_observed


def test_dispatch_consumer_evidence_is_bound_to_the_screen_action_pair(inventory) -> None:
    """동명 action 토큰은 다른 화면 endpoint 의 소비 증거가 될 수 없다(#528 P1)."""
    rows = {(row.screen, row.action): row for row in inventory.endpoints}

    library = rows[("library", "toggle_group")]
    assert library.consumer == "product", library
    assert "frontend/src/screens/library.ts" in library.js_evidence, library

    transitional = rows[("tpl", "toggle_group")]
    assert transitional.consumer == "none_found", transitional
    assert transitional.js_evidence == (), transitional

    dynamic_product = {
        ("job", "load_pool"),
        ("job", "relink_template"),
        ("library", "relink_template"),
        ("pool", "activate"),
        ("pool", "archive"),
        ("pool", "register_excel"),
    }
    for pair in dynamic_product:
        assert rows[pair].consumer == "product", rows[pair]
        assert rows[pair].js_evidence, rows[pair]
    assert {
        pair for pair, row in rows.items() if row.consumer == "none_found"
    } == {("tpl", "toggle_group")}


@pytest.mark.parametrize(
    "enumerate_pairs", [dispatch_pair_evidence, _dispatch_pair_oracle], ids=["collector", "oracle"]
)
def test_restricted_dynamic_dispatch_domains_recover_product_pairs(enumerate_pairs) -> None:
    """제품 port와 producer가 제한한 값-domain만 동적 dispatch 양성으로 복원한다."""
    evidence = enumerate_pairs(ROOT)
    expected = {
        ("job", "load_pool"): "frontend/src/screens/data_picker.ts",
        ("job", "relink_template"): "frontend/src/screens/job_relink.ts",
        ("library", "relink_template"): "frontend/src/screens/job_relink.ts",
        ("pool", "activate"): "frontend/src/screens/data_picker.ts",
        ("pool", "archive"): "frontend/src/screens/data_picker.ts",
        ("pool", "register_excel"): "frontend/src/screens/data_picker.ts",
    }
    for pair, sender in expected.items():
        assert sender in evidence[pair], (pair, evidence.get(pair))
    assert ("tpl", "toggle_group") not in evidence


@pytest.mark.parametrize(
    "enumerate_pairs", [dispatch_pair_evidence, _dispatch_pair_oracle], ids=["collector", "oracle"]
)
def test_dynamic_dispatch_does_not_inherit_lexical_noise(enumerate_pairs) -> None:
    """파일 문자열과 주석·문자열 속 call-shaped 산문은 값-domain이 아니다(#528 음성)."""
    rel = "frontend/src/screens/synthetic.ts"
    corpus = {
        rel: """
        function axis(action: string): void { dispatch("tpl", action, {}); }
        const screen = "tpl";
        const unrelated = "toggle_group";
        const prose = 'dispatch("tpl", "toggle_group", {})';
        const templateProse = `dispatch("tpl", "toggle_group", {})`;
        const pattern = /dispatch("tpl", "toggle_group", {})/;
        function patternFactory() { return /dispatch("tpl", "toggle_group", {})/; }
        const arrowPattern = () => /dispatch("tpl", "toggle_group", {})/;
        // dispatch("tpl", "toggle_group", {});
        /* axis("toggle_group"); */
        const liveTemplate = `${axis("refresh")}`;
        """
    }
    evidence = enumerate_pairs(ROOT, corpus)
    assert evidence[("tpl", "refresh")] == (rel,)
    assert ("tpl", "toggle_group") not in evidence


def test_snapshot_fields_record_screen_bound_consumer_evidence(inventory) -> None:
    """snapshot 128필드는 producer뿐 아니라 화면별 consumer 절반도 모두 기록한다(#528 P1)."""
    rows = {(row.screen, row.field): row for row in inventory.snapshot_fields}
    for row in rows.values():
        assert row.consumer in {"product", "selftest_only", "none_found"}, row
        assert isinstance(row.js_evidence, tuple), row

    assert rows[("editor", "name")].consumer == "product"
    assert "frontend/src/screens/editor_state.ts" in rows[("editor", "name")].js_evidence
    assert rows[("job", "rules_key")].consumer == "product"
    assert "frontend/src/screens/job_run_state.ts" in rows[("job", "rules_key")].js_evidence
    assert "frontend/src/screens/job_preview.ts" in rows[("job", "preview")].js_evidence
    assert "frontend/src/screens/job_result.ts" in rows[("job", "last_run_job")].js_evidence
    assert rows[("pool", "rows")].consumer == "product"
    assert "frontend/src/screens/data_picker.ts" in rows[("pool", "rows")].js_evidence
    assert rows[("editor", "template_media")].consumer == "selftest_only"
    assert rows[("editor", "template_media")].js_evidence == (
        "frontend/src/selftest/probes/boot_routing_overlay.js",
    )
    assert "frontend/src/screens/runtime.ts" not in rows[("workbench", "revision")].js_evidence
    assert "frontend/src/screens/editor_state.ts" not in rows[("workbench", "rows")].js_evidence
    assert rows[("job", "template_name")].consumer == "none_found"
    assert rows[("job", "template_name")].js_evidence == ()
    assert rows[("tpl", "hwpx")].consumer == "none_found"
    assert rows[("tpl", "hwpx")].js_evidence == ()


def test_snapshot_gate_has_an_independent_destructuring_denominator(tmp_path: Path) -> None:
    """수집기가 새 access 형식을 놓쳐도 별 구조 오라클은 함께 눈멀지 않는다."""
    from factgraph.transport_graph import (
        _frontend_corpus,
        _screen_consumer_modules,
        _snapshot_selftest_evidence,
        _snapshot_field_evidence,
        _snapshot_oracle_evidence,
    )

    frontend_root = tmp_path / SOURCE_RELATIVE
    js_root = frontend_root / "js"
    src_root = frontend_root / "src"
    js_root.mkdir(parents=True)
    src_root.mkdir(parents=True)
    (src_root / "root.ts").write_text(
        'const model = runtime.model("job");\n'
        "const snapshot = model.getSnapshot();\n"
        'const prose = "snapshot.preview";\n'
        'const moduleLikeProse = "./snapshot.preview";\n'
        'const templateProse = `snapshot.preview`;\n'
        'const liveTemplate = `${snapshot.rules_key}`;\n'
        'function pattern() { return /snapshot.preview/; }\n'
        'function guarded(ok) { if (ok) /snapshot.preview/.test("x"); }\n'
        "export function useJobSnapshot() { return model.getSnapshot(); }\n",
        encoding="utf-8",
    )
    (src_root / "view.ts").write_text(
        'import { useJobSnapshot as useAlias } from "./root.ts";\n'
        "const { preview } = useAlias();\n",
        encoding="utf-8",
    )
    (src_root / "noise.ts").write_text(
        'const prose = \'runtime.model("job"); snapshot.preview\';\n',
        encoding="utf-8",
    )
    corpus = _frontend_corpus(tmp_path)
    closures = _screen_consumer_modules(corpus, {"job"})
    assert _snapshot_field_evidence(corpus, closures, "job", "preview") == ()
    assert _snapshot_field_evidence(corpus, closures, "job", "rules_key") == (
        "frontend/src/root.ts",
    )
    assert _snapshot_oracle_evidence(tmp_path, "job", "preview") == (
        "frontend/src/view.ts",
    )
    assert _snapshot_oracle_evidence(tmp_path, "job", "rules_key") == (
        "frontend/src/root.ts",
    )

    selftest_root = src_root / "selftest"
    selftest_root.mkdir()
    (selftest_root / "probe.js").write_text(
        'const snap = await bridge.initial("job");\nvoid snap.preview;\n',
        encoding="utf-8",
    )
    corpus = _frontend_corpus(tmp_path)
    assert _snapshot_selftest_evidence(corpus, "job", "preview") == (
        "frontend/src/selftest/probe.js",
    )
    assert _snapshot_oracle_evidence(tmp_path, "job", "preview") == (
        "frontend/src/selftest/probe.js",
        "frontend/src/view.ts",
    )


def test_product_snapshot_alias_does_not_escape_its_lexical_scope(tmp_path: Path) -> None:
    """한 함수의 snapshot alias는 다른 함수의 동명 인자를 소비자로 만들 수 없다."""
    from factgraph.transport_graph import (
        _frontend_corpus,
        _screen_consumer_modules,
        _snapshot_field_evidence,
        _snapshot_oracle_evidence,
    )

    frontend_root = tmp_path / SOURCE_RELATIVE
    (frontend_root / "js").mkdir(parents=True)
    src_root = frontend_root / "src"
    src_root.mkdir(parents=True)
    (src_root / "root.ts").write_text(
        'const model = runtime.model("job");\n'
        "function bind() { const snap = model.getSnapshot(); return 1; }\n"
        "function unrelated(snap) { return snap.preview; }\n",
        encoding="utf-8",
    )

    corpus = _frontend_corpus(tmp_path)
    closures = _screen_consumer_modules(corpus, {"job"})
    assert _snapshot_field_evidence(corpus, closures, "job", "preview") == ()
    assert _snapshot_oracle_evidence(tmp_path, "job", "preview") == ()


def test_selftest_finite_domain_snapshot_store_is_screen_bound(inventory) -> None:
    """``initial(scr) -> snaps[scr] -> snaps.editor``가 editor 필드에만 귀속된다."""
    from factgraph.transport_graph import (
        _frontend_corpus,
        _snapshot_oracle_evidence,
        _snapshot_selftest_evidence,
    )

    expected = ("frontend/src/selftest/probes/boot_routing_overlay.js",)
    corpus = _frontend_corpus(ROOT)
    assert _snapshot_selftest_evidence(corpus, "editor", "template_media") == expected
    assert _snapshot_oracle_evidence(ROOT, "editor", "template_media") == expected
    row = next(
        field
        for field in inventory.snapshot_fields
        if (field.screen, field.field) == ("editor", "template_media")
    )
    assert row.consumer == "selftest_only"
    assert row.js_evidence == expected


def test_selftest_snapshot_aliases_do_not_cross_function_scope(tmp_path: Path) -> None:
    """다른 함수의 동명 ``snap`` access는 editor binding을 빌려 쓸 수 없다."""
    from factgraph.transport_graph import (
        _frontend_corpus,
        _snapshot_oracle_evidence,
        _snapshot_selftest_evidence,
    )

    frontend_root = tmp_path / SOURCE_RELATIVE
    (frontend_root / "js").mkdir(parents=True)
    selftest = frontend_root / "src" / "selftest"
    selftest.mkdir(parents=True)
    (selftest / "scope.js").write_text(
        "async function bindEditor() {\n"
        '  const snap = await bridge.initial("editor");\n'
        "  return snap.name;\n"
        "}\n"
        "async function readJob() {\n"
        '  const snap = await bridge.initial("job");\n'
        "  return snap.template_media;\n"
        "}\n",
        encoding="utf-8",
    )
    corpus = _frontend_corpus(tmp_path)
    rel = ("frontend/src/selftest/scope.js",)
    assert _snapshot_selftest_evidence(corpus, "editor", "name") == rel
    assert _snapshot_oracle_evidence(tmp_path, "editor", "name") == rel
    assert _snapshot_selftest_evidence(corpus, "job", "template_media") == rel
    assert _snapshot_oracle_evidence(tmp_path, "job", "template_media") == rel
    assert _snapshot_selftest_evidence(corpus, "editor", "template_media") == ()
    assert _snapshot_oracle_evidence(tmp_path, "editor", "template_media") == ()


def test_snapshot_graph_uses_lexical_imports_and_helper_calls(tmp_path: Path) -> None:
    """template/comment fake import와 문자열 helper call은 graph edge가 아니다."""
    from factgraph.transport_graph import (
        _frontend_corpus,
        _screen_consumer_modules,
        _snapshot_field_evidence,
        _snapshot_oracle_evidence,
    )

    frontend_root = tmp_path / SOURCE_RELATIVE
    (frontend_root / "js").mkdir(parents=True)
    src = frontend_root / "src"
    src.mkdir(parents=True)
    (src / "root.ts").write_text(
        'import { live } from "./helper.ts";\n'
        "const fakeImport = `\n"
        'import { ghost } from "./ghost.ts";\n'
        "`;\n"
        "/*\n"
        'import { ghost } from "./ghost.ts";\n'
        "*/\n"
        'const model = runtime.model("job");\n'
        "const snapshot = model.getSnapshot();\n"
        "export function consume() { return live(snapshot); }\n"
        'export function guarded(ok) { if (ok) /snapshot.preview/.test("x"); }\n',
        encoding="utf-8",
    )
    (src / "helper.ts").write_text(
        "export function live(snapshot) {\n"
        '  const fakeCall = "dead(snapshot)";\n'
        "  // dead(snapshot);\n"
        "  return `${snapshot.rules_key}`;\n"
        "}\n"
        "export function dead(snapshot) { return snapshot.preview; }\n",
        encoding="utf-8",
    )
    (src / "ghost.ts").write_text(
        "export function ghost(snapshot) { return snapshot.preview; }\n",
        encoding="utf-8",
    )
    corpus = _frontend_corpus(tmp_path)
    closures = _screen_consumer_modules(corpus, {"job"})
    assert closures["job"] == (
        "frontend/src/helper.ts",
        "frontend/src/root.ts",
    )
    assert _snapshot_field_evidence(corpus, closures, "job", "rules_key") == (
        "frontend/src/helper.ts",
    )
    assert _snapshot_oracle_evidence(tmp_path, "job", "rules_key") == (
        "frontend/src/helper.ts",
    )
    assert _snapshot_field_evidence(corpus, closures, "job", "preview") == ()
    assert _snapshot_oracle_evidence(tmp_path, "job", "preview") == ()


def test_product_event_payload_fields_are_derived_from_python_builders(inventory) -> None:
    """product event DTO를 빈 튜플로 접지 않고 조건부 키까지 실형상으로 보존한다(#528 P1)."""
    fields = {
        row.name: row.fields for row in inventory.channels if row.kind == "product_event"
    }
    assert fields == {
        "snapshot": ("screen", "snapshot"),
        "close-request": ("state",),
        "preferences": ("personalization", "theme?"),
        "notice": ("message",),
    }


def test_product_event_consumers_include_unquoted_handler_keys(inventory) -> None:
    """bootstrap의 ``preferences:``·``notice:`` 무따옴표 키도 활성 소비 증거다(#528 P2)."""
    rows = {row.name: row for row in inventory.channels if row.kind == "product_event"}
    for name in ("snapshot", "close-request", "preferences", "notice"):
        assert "frontend/src/product_api.js" in rows[name].consumer_evidence, rows[name]
        assert "frontend/src/bootstrap.js" in rows[name].consumer_evidence, rows[name]

    from factgraph.transport_graph import event_route_problems

    assert event_route_problems(ROOT, inventory.channels) == []


# ------------------------------------------------- 음성 — 변형 사본의 판별력


def _replace_endpoint(inventory, index: int, **changes):
    endpoints = list(inventory.endpoints)
    endpoints[index] = dataclasses.replace(endpoints[index], **changes)
    return tuple(endpoints)


def test_n1_a_ghost_endpoint_is_caught(inventory, controllers) -> None:
    """원장에만 있는 endpoint(등록 안 된 액션) — endpoint 추가 드리프트의 한쪽 면."""
    ghost = DispatchEndpoint(
        screen="job",
        action="ghost_action",
        required=(),
        optional=(),
        zone_mutation=False,
        handler="",
        consumer="none_found",
        js_evidence=(),
    )
    problems = endpoint_problems(ROOT, (*inventory.endpoints, ghost), controllers=controllers)
    assert any("유령 endpoint" in p and "ghost_action" in p for p in problems), problems


def test_n2_a_dropped_endpoint_row_is_caught(inventory, controllers) -> None:
    """registry 액션이 원장에서 빠지면 — endpoint 추가 드리프트의 다른 면(전수성)."""
    dropped = inventory.endpoints[0]
    problems = endpoint_problems(ROOT, inventory.endpoints[1:], controllers=controllers)
    assert any(
        "원장에 없다" in p and f"{dropped.screen}/{dropped.action}" in p for p in problems
    ), problems


def test_n3_payload_key_drift_is_caught(inventory, controllers) -> None:
    """required/optional 키 집합이 정본과 어긋나면 각각의 문자열로 문다."""
    index = next(i for i, e in enumerate(inventory.endpoints) if e.action == "toggle_record")
    tampered = _replace_endpoint(
        inventory, index, required=(*inventory.endpoints[index].required, "epoch")
    )
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("required 키 드리프트" in p and "toggle_record" in p for p in problems), problems

    tampered = _replace_endpoint(inventory, index, optional=())
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("optional 키 드리프트" in p and "toggle_record" in p for p in problems), problems


def test_n4_zone_mutation_flag_flip_is_caught(inventory, controllers) -> None:
    index = next(i for i, e in enumerate(inventory.endpoints) if e.action == "toggle_record")
    tampered = _replace_endpoint(
        inventory, index, zone_mutation=not inventory.endpoints[index].zone_mutation
    )
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("zone_mutation" in p and "toggle_record" in p for p in problems), problems


def test_n5_handler_misattribution_is_caught(inventory, controllers) -> None:
    """handler 를 다른 클래스 symbol 로 위조하면 MRO 실측이 문다 — producer 연결의 판별력."""
    index = next(i for i, e in enumerate(inventory.endpoints) if e.handler)
    tampered = _replace_endpoint(
        inventory,
        index,
        handler="hwpxfiller.webapp.screens:Ghost._do_nothing#method",
    )
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("handler 귀속 불일치" in p for p in problems), problems


def test_n6_a_consumer_ghost_is_caught_in_both_directions(inventory, controllers) -> None:
    """consumer ghost — 없는 증거 파일 주장과, 증거와 어긋나는 분류를 각각 문다."""
    index = 0
    tampered = _replace_endpoint(
        inventory,
        index,
        js_evidence=("frontend/src/this_file_does_not_exist.ts",),
        consumer="product",
    )
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("증거 파일이 없다" in p for p in problems), problems

    victim = inventory.endpoints[index]
    assert victim.js_evidence, "표본 endpoint 에 증거가 있어야 이 대조가 판별력을 가진다"
    tampered = _replace_endpoint(inventory, index, consumer="none_found")
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("consumer 분류가 증거와 어긋난다" in p for p in problems), problems


def test_n6b_same_action_evidence_from_another_screen_is_caught(
    inventory, controllers
) -> None:
    """실재 파일이어도 다른 화면의 동명 action 발신이면 증거 위조다(#528 P1 음성)."""
    index = next(
        i
        for i, row in enumerate(inventory.endpoints)
        if (row.screen, row.action) == ("tpl", "toggle_group")
    )
    tampered = _replace_endpoint(
        inventory,
        index,
        consumer="product",
        js_evidence=("frontend/src/screens/library.ts",),
    )
    problems = endpoint_problems(ROOT, tampered, controllers=controllers)
    assert any("소비자 증거 드리프트" in p and "tpl/toggle_group" in p for p in problems), problems


def test_n7_host_method_consumer_ghost_is_caught(inventory) -> None:
    """host-internal 표면을 「제품이 소비한다」로 위조하면 bridge.js 실측이 문다."""
    methods = list(inventory.host_methods)
    index = next(i for i, m in enumerate(methods) if m.name == "close_guard_state")
    methods[index] = dataclasses.replace(methods[index], consumer="product", python_consumer="")
    problems = host_method_problems(
        ROOT,
        tuple(methods),
        inventory.bridge_consumed_product,
        inventory.bridge_consumed_selftest,
    )
    assert any("close_guard_state" in p and "소비 분류 드리프트" in p for p in problems), problems


def test_n8_bridge_consumption_drift_is_caught(inventory) -> None:
    problems = host_method_problems(
        ROOT,
        inventory.host_methods,
        inventory.bridge_consumed_product[1:],
        inventory.bridge_consumed_selftest,
    )
    assert any("bridge 제품 소비 드리프트" in p for p in problems), problems


def test_n9_an_unattributed_snapshot_field_is_caught(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    """필드 행 하나를 빼면 「producer 미분류」가 정확히 그 필드 이름으로 운다."""
    dropped = inventory.snapshot_fields[0]
    problems = snapshot_problems(
        ROOT,
        inventory.snapshot_fields[1:],
        controllers=controllers,
        runtime_fields=runtime_fields,
        oracle_inventory=snapshot_oracle,
    )
    assert any("producer 미분류" in p and dropped.field in p for p in problems), problems


def test_n10_a_ghost_snapshot_field_is_caught(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    ghost = SnapshotField(
        screen="job",
        field="ghost_field",
        producer="hwpxfiller.webapp.screen_job:JobController.snapshot#method",
        runtime_observed=False,
        consumer="none_found",
        js_evidence=(),
    )
    problems = snapshot_problems(
        ROOT,
        (*inventory.snapshot_fields, ghost),
        controllers=controllers,
        runtime_fields=runtime_fields,
        oracle_inventory=snapshot_oracle,
    )
    assert any("유령 필드" in p and "ghost_field" in p for p in problems), problems


def test_n11_a_flipped_runtime_observation_is_caught(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    fields = list(inventory.snapshot_fields)
    index = next(i for i, f in enumerate(fields) if f.runtime_observed)
    fields[index] = dataclasses.replace(fields[index], runtime_observed=False)
    problems = snapshot_problems(
        ROOT,
        tuple(fields),
        controllers=controllers,
        runtime_fields=runtime_fields,
        oracle_inventory=snapshot_oracle,
    )
    assert any("실측 표지가 실측과 다르다" in p for p in problems), problems


def test_n11b_snapshot_consumer_evidence_from_another_screen_is_caught(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    """tpl 필드를 editor 토큰으로 소비됨 처리하면 화면 결속 오라클이 문다(#528 P1 음성)."""
    fields = list(inventory.snapshot_fields)
    index = next(
        i for i, row in enumerate(fields) if (row.screen, row.field) == ("tpl", "hwpx")
    )
    fields[index] = dataclasses.replace(
        fields[index],
        consumer="product",
        js_evidence=("frontend/src/screens/editor.ts",),
    )
    problems = snapshot_problems(
        ROOT,
        tuple(fields),
        controllers=controllers,
        runtime_fields=runtime_fields,
        oracle_inventory=snapshot_oracle,
    )
    assert any("소비자 증거 드리프트" in p and "tpl.hwpx" in p for p in problems), problems


def test_n11c_an_incomplete_reused_snapshot_oracle_is_caught(
    inventory, controllers, runtime_fields, snapshot_oracle
) -> None:
    """재사용 seam 이 source 측정을 조용히 누락하면 빈 증거로 오인하지 않고 문다."""
    screen, field, _evidence = snapshot_oracle.rows[0]
    incomplete = dataclasses.replace(snapshot_oracle, rows=snapshot_oracle.rows[1:])
    problems = snapshot_problems(
        ROOT,
        inventory.snapshot_fields,
        controllers=controllers,
        runtime_fields=runtime_fields,
        oracle_inventory=incomplete,
    )
    assert any(
        "독립 분모에 없다" in problem and f"{screen}.{field}" in problem
        for problem in problems
    ), problems


def test_n12_a_dropped_channel_is_caught(inventory, controllers) -> None:
    """progress delta 채널 행을 빼면 부분 push 전수 스캔이 문다 — 채널이 조용히 못 는다의 짝."""
    remaining = tuple(c for c in inventory.channels if c.kind != "partial_push")
    problems = channel_problems(ROOT, remaining, controllers=controllers)
    assert any("채널이 원장에 없다" in p and "_push_progress" in p for p in problems), problems


def test_n13_a_ghost_channel_is_caught(inventory, controllers) -> None:
    ghost = PushChannel(
        kind="product_event",
        name="ghost-event",
        producer="hwpxfiller.webapp.product_api:ProductApiClient.push#method",
        fields=(),
        consumer_evidence=(),
    )
    problems = channel_problems(ROOT, (*inventory.channels, ghost), controllers=controllers)
    assert any("유령 채널" in p and "ghost-event" in p for p in problems), problems


def test_n13b_product_event_payload_omission_is_caught(inventory, controllers) -> None:
    """payload 빌더에 실키가 있는데 원장을 빈 DTO로 위조하면 문다(#528 P1 음성)."""
    channels = list(inventory.channels)
    index = next(i for i, row in enumerate(channels) if row.name == "preferences")
    assert channels[index].fields == ("personalization", "theme?")
    channels[index] = dataclasses.replace(channels[index], fields=())
    problems = channel_problems(ROOT, tuple(channels), controllers=controllers)
    assert any("채널 내용 드리프트" in p and "preferences" in p for p in problems), problems


def test_n13c_independent_route_oracle_catches_a_blind_consumer_collector(inventory) -> None:
    """수집기가 무따옴표 키를 놓쳐도 ROUTES 독립 분모가 활성 채널의 빈 증거를 문다."""
    from factgraph.transport_graph import event_route_problems

    channels = tuple(
        dataclasses.replace(row, consumer_evidence=())
        if row.kind == "product_event" and row.name == "preferences"
        else row
        for row in inventory.channels
    )
    problems = event_route_problems(ROOT, channels)
    assert any("활성 라우트인데 원장 소비 증거가 비었다" in p and "preferences" in p for p in problems), problems


def test_n14_vocabulary_and_anchor_drift_are_caught(inventory) -> None:
    tampered = dataclasses.replace(inventory, python_error_codes=inventory.python_error_codes[1:])
    problems = vocabulary_problems(ROOT, tampered)
    assert any("python 오류 어휘" in p for p in problems), problems

    rel, _digest = inventory.input_sha256[0]
    tampered = dataclasses.replace(
        inventory, input_sha256=((rel, "0" * 64), *inventory.input_sha256[1:])
    )
    problems = vocabulary_problems(ROOT, tampered)
    assert any("입력 앵커 불일치" in p and rel in p for p in problems), problems
