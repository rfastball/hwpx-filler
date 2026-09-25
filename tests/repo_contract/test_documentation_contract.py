"""Purpose routing must fail closed without treating fingerprints as semantic proof."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import docs_contract as docs


def _put(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _manifest(root: Path, data: dict) -> None:
    lines = ['schema = "docs-contract/v2"']
    for kind in ("document", "topic", "support"):
        if not data[kind]:
            lines.append(f"{kind} = []")
    for kind in ("document", "topic", "support"):
        for item in data[kind]:
            lines += ["", f"[[{kind}]]"]
            lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in item.items()]
    _put(root, docs.MANIFEST, "\n".join(lines) + "\n")


def _data(root: Path) -> dict:
    return docs.tomllib.loads(docs.read(root / docs.MANIFEST))


def _topic(root: Path, ident: str = "workflow-primary") -> dict:
    return next(t for t in _data(root)["topic"] if t["id"] == ident)


def _review(root: Path, ident: str = "workflow-primary") -> None:
    topic = _topic(root, ident)
    docs.acknowledge_review(root, f"{topic['document']}#{ident}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _put(tmp_path, "pyproject.toml", '[project]\nversion="1.0.0"\nrequires-python=">=3.13"\n'
         '[project.scripts]\nexample="example:main"\n')
    _put(tmp_path, ".python-version", "3.13\n")
    _put(tmp_path, ".node-version", "24.18.1\n")
    _put(tmp_path, "package.json", json.dumps({"engines": {"node": "24.18.1", "npm": "11.16.0"},
                                              "packageManager": "npm@11.16.0"}))
    _put(tmp_path, "src/hwpxfiller/webapp/app.py", 'class WebFrontend:\n'
         '    def initial(self, screen: str): pass\n    def direct(self, path: str): pass\n')
    _put(tmp_path, "src/hwpxfiller/webapp/selftest_api.py",
         "class SelftestHostFacade:\n    def selftest_claim(self, token=None): pass\n")
    _put(tmp_path, "src/hwpxfiller/webapp/action_registry.py",
         '_COMMON = {"ping": _schema(optional="epoch")}\n'
         '_REGISTRY = {"job": {**_COMMON, "run": _schema("row", "confirm")}}\n')
    _put(tmp_path, ".github/workflows/quality.yml", 'name: quality\njobs:\n'
         '  static:\n    steps: []\n  quality-gate:\n    needs:\n      - static\n    steps: []\n')
    _put(tmp_path, "tests/evidence.py", "def test_behavior(): pass\n")
    _put(tmp_path, "frontend/js/bridge.js", "// bridge\n")
    _put(tmp_path, "src/entry.py", "# entry\n")
    data: dict = {"document": [], "topic": [], "support": []}
    hashes = dict(source_sha256="0" * 64, body_sha256="0" * 64)
    for role, (kind, name) in docs.SLOTS.items():
        item = dict(path=name, kind=kind, role=role, title=role, max_lines=500)
        text = f"# {role}\n\n"
        if kind == "canonical":
            ident = role + "-primary"
            text += f'<a id="{ident}"></a>\n## 현재 상태\n\noriginal\n'
            if role == "product":
                text += "\n### Platform\n\nweb\n"
            _put(tmp_path, f"src/{role}.py", f"# {role}\n")
            sources = [f"src/{role}.py"]
            if role == "workflow":
                sources = ["src/hwpxfiller/webapp/*.py"]
            data["topic"].append(dict(id=ident, document=name, sources=sources,
                                     tests=["tests/evidence.py"], **hashes))
        elif kind == "current":
            item.update(sources=["src/entry.py"], tests=["tests/evidence.py"], **hashes)
        elif kind == "machine":
            text = "# Machine contract fixture\n"
        data["document"].append(item)
        _put(tmp_path, name, text)
    secondary = dict(id="workflow-secondary", document=docs.CORE["workflow"], sources=["src/secondary.py"],
                     tests=["tests/evidence.py"], **hashes)
    data["topic"].append(secondary)
    _put(tmp_path, "src/secondary.py", "# independent\n")
    path = tmp_path / docs.CORE["workflow"]
    path.write_text(docs.read(path) + '\n<a id="workflow-secondary"></a>\n## 결과\n\nindependent\n',
                    encoding="utf-8", newline="\n")
    _manifest(tmp_path, data)
    docs.write_generated(tmp_path)
    # Synthetic test fixture bootstrap, not an approval of repository prose.
    for topic in data["topic"]:
        docs.acknowledge_review(tmp_path, f"{topic['document']}#{topic['id']}")
    for item in data["document"]:
        if item["kind"] == "current":
            docs.acknowledge_review(tmp_path, item["path"])
    assert docs.check(tmp_path) == []
    return tmp_path


def test_repository_documentation_contract() -> None:
    assert docs.check(docs.ROOT) == []


def test_agents_md_is_the_only_agent_entry(repo: Path) -> None:
    assert docs.SLOTS["agents-entry"] == ("current", "AGENTS.md")
    assert "claude-entry" not in docs.SLOTS
    assert (repo / "AGENTS.md").is_file()
    assert not (repo / "CLAUDE.md").exists()
    assert docs.route(repo, "agents-entry") == ["AGENTS.md"]
    assert "CLAUDE.md" not in docs.render_index(repo, docs.inventory(repo))
    assert docs.check(repo) == []


def test_agents_md_remains_required(repo: Path) -> None:
    (repo / "AGENTS.md").unlink()
    assert any("missing=" in p and "AGENTS.md" in p for p in docs.check(repo))


@pytest.mark.parametrize("name", [
    "CLAUDE.md", ".claude/CLAUDE.md", ".claude/AGENTS.md",
    "subdir/AGENTS.md", "AGENTS.override.md",
])
def test_unregistered_agent_instruction_copies_are_rejected(repo: Path, name: str) -> None:
    _put(repo, name, "# Additional agent guidance\n")
    assert any("unregistered=" in p and name in p for p in docs.check(repo))


def test_version_change_requires_regeneration(repo: Path) -> None:
    p = repo / "pyproject.toml"
    p.write_text(docs.read(p).replace("1.0.0", "1.1.0"), encoding="utf-8")
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)
    docs.write_generated(repo)
    assert "`1.1.0`" in docs.read(repo / docs.REFERENCE)
    assert docs.check(repo) == []


@pytest.mark.parametrize("source,line,method", [
    ("app.py", "    def new_action(self, value): pass\n", "new_action"),
    ("selftest_api.py", "    def selftest_extra(self): pass\n", "selftest_extra"),
])
def test_public_methods_require_generation_and_review(repo: Path, source: str, line: str, method: str) -> None:
    p = repo / "src/hwpxfiller/webapp" / source
    p.write_text(docs.read(p) + line, encoding="utf-8")
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)
    docs.write_generated(repo)
    assert f"`{method}`" in docs.read(repo / docs.REFERENCE)
    assert "review required: docs/workflow.md#workflow-primary" in docs.check(repo)
    assert "Selftest 전용 공개 메서드" in docs.read(repo / docs.REFERENCE)


def test_registry_expansions_and_optional_keys_are_generated(repo: Path) -> None:
    assert docs.registry(repo) == {"job": {"ping": ("", "epoch"), "run": ("row", "confirm")}}
    p = repo / "src/hwpxfiller/webapp/action_registry.py"
    p.write_text(docs.read(p).replace('"row", "confirm"', '"row token", "confirm"'), encoding="utf-8")
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)


def test_unrecognized_registry_fails_loudly(repo: Path) -> None:
    _put(repo, "src/hwpxfiller/webapp/action_registry.py", "_REGISTRY = dynamic_registry()\n")
    assert any("literal dictionaries" in p for p in docs.check(repo))


def test_changed_ci_dependency_list_is_generated(repo: Path) -> None:
    p = repo / ".github/workflows/quality.yml"
    p.write_text(docs.read(p).replace("  static:", "  extra:\n    steps: []\n  static:")
                 .replace("      - static\n", "      - static\n      - extra\n"), encoding="utf-8")
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)


@pytest.mark.parametrize("name", ["docs/new.md", "docs/new.html", "docs/new.toml", "NEW.md",
                                 "notes/extra.md", "tests/side-guide.md", "notes/extra.mdx"])
def test_unregistered_documents_anywhere_are_rejected(repo: Path, name: str) -> None:
    _put(repo, name, "unregistered")
    assert any("unregistered=" in p and name in p for p in docs.check(repo))


def test_tracked_ignored_file_cannot_escape_inventory(repo: Path) -> None:
    _put(repo, ".gitignore", "notes/\n")
    _put(repo, "notes/hidden.md", "# hidden\n")
    subprocess.run(["git", "-C", str(repo), "add", "-f", "notes/hidden.md"], check=True)
    assert any("notes/hidden.md" in p for p in docs.check(repo))


def test_deleted_document_is_rejected(repo: Path) -> None:
    (repo / "README.md").unlink()
    assert any("missing=" in p and "README.md" in p for p in docs.check(repo))


@pytest.mark.parametrize("field,value", [("path", "docs/product.md"), ("role", "product")])
def test_duplicate_path_or_role_is_rejected(repo: Path, field: str, value: str) -> None:
    data = _data(repo)
    item = dict(data["document"][0])
    item[field] = value
    data["document"].append(item)
    _manifest(repo, data)
    assert any("duplicate document" in p for p in docs.check(repo))


def test_rewording_role_does_not_add_another_canonical(repo: Path) -> None:
    data = _data(repo)
    item = dict(data["document"][0], path="docs/another-product.md", role="product-context")
    data["document"].append(item)
    _manifest(repo, data)
    assert any("unknown document role" in p for p in docs.check(repo))


def test_canonical_cannot_move_to_arbitrary_path(repo: Path) -> None:
    data = _data(repo)
    data["document"][0]["path"] = "docs/PRODUCT_SCOPE.md"
    _manifest(repo, data)
    assert any("fixed kind/path" in p for p in docs.check(repo))


@pytest.mark.parametrize("stem", ["Bad_Name", "report-v2", "report-s0", "report-final", "report-20260925"])
def test_independent_document_names_are_purpose_based(repo: Path, stem: str) -> None:
    data = _data(repo)
    data["document"].append(dict(path=f"docs/research/{stem}.md", role=f"research-{stem}", kind="research",
                                 title="Research", max_lines=50, why_separate="Independent model"))
    _manifest(repo, data)
    assert any("independent document" in p for p in docs.check(repo))


def test_manifest_registration_alone_cannot_exceed_doc_count(repo: Path) -> None:
    data = _data(repo)
    for index in range(4):
        stem = f"extra-{index}"
        data["document"].append(dict(path=f"docs/research/{stem}.md", role=f"research-{stem}", kind="research",
                                     title="Research", max_lines=50, why_separate="Independent model"))
    _manifest(repo, data)
    assert any("count budget" in p for p in docs.check(repo))


def test_support_kind_cannot_hide_another_manual(repo: Path) -> None:
    data = _data(repo)
    data["support"].append(dict(path="notes/manual.md", kind="fixture", reason="Not really a fixture"))
    _manifest(repo, data)
    assert any("cannot shelter" in p for p in docs.check(repo))


def test_duplicate_topic_owner_is_rejected(repo: Path) -> None:
    data = _data(repo)
    data["topic"].append(dict(data["topic"][0], document=docs.CORE["workflow"]))
    _manifest(repo, data)
    assert any("duplicate topic owner" in p for p in docs.check(repo))


def test_unregistered_topic_is_rejected(repo: Path) -> None:
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + '\n<a id="hidden-owner"></a>\n## Unregistered\n', encoding="utf-8")
    assert any("topic ownership mismatch" in p for p in docs.check(repo))


@pytest.mark.parametrize("target", ["missing.md", "workflow.md#없는-절", "../missing.png"])
def test_broken_links_and_fragments_are_rejected(repo: Path, target: str) -> None:
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + f"\n[link]({target})\n", encoding="utf-8")
    assert any("broken " in p and target in p for p in docs.check(repo))


def test_reference_style_and_html_links_are_checked(repo: Path) -> None:
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + '\n[link][x]\n\n[x]: missing.md\n<img src="missing.png">\n', encoding="utf-8")
    errors = docs.check(repo)
    assert any("missing.md" in p for p in errors)
    assert any("missing.png" in p for p in errors)


def test_fenced_examples_and_external_links_need_no_network(repo: Path) -> None:
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + '\n```md\n[example](missing.md)\n```\n'
                 '[online](https://example.invalid/no-network)\n', encoding="utf-8")
    _review(repo, "workflow-secondary")
    assert docs.check(repo) == []


def test_source_rename_with_same_bytes_still_requires_review(repo: Path) -> None:
    source = repo / "src/hwpxfiller/webapp/other.py"
    source.write_text("# source\n", encoding="utf-8")
    _review(repo)
    source.rename(source.with_name("renamed.py"))
    assert "review required: docs/workflow.md#workflow-primary" in docs.check(repo)


def test_new_file_in_glob_requires_review(repo: Path) -> None:
    _put(repo, "src/hwpxfiller/webapp/new.py", "# new\n")
    assert "review required: docs/workflow.md#workflow-primary" in docs.check(repo)


def test_empty_glob_fails_instead_of_shrinking_scope(repo: Path) -> None:
    data = _data(repo)
    data["topic"][0]["sources"] = ["src/missing/*.py"]
    _manifest(repo, data)
    assert any("empty source glob" in p for p in docs.check(repo))


def test_missing_evidence_test_is_rejected(repo: Path) -> None:
    (repo / "tests/evidence.py").unlink()
    assert any("missing/invalid evidence test" in p for p in docs.check(repo))


def test_prose_edit_review_is_limited_to_the_affected_topic(repo: Path) -> None:
    before = docs.read(repo / docs.MANIFEST)
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p).replace("original", "updated"), encoding="utf-8")
    docs.write_generated(repo)
    assert docs.read(repo / docs.MANIFEST) == before
    assert docs.check(repo) == ["review required: docs/workflow.md#workflow-primary"]
    sibling = _topic(repo, "workflow-secondary")
    _review(repo)
    assert _topic(repo, "workflow-secondary") == sibling
    assert docs.check(repo) == []


@pytest.mark.parametrize("target", ["docs/workflow.md", "all", docs.REFERENCE, docs.PRODUCT])
def test_review_cannot_bulk_acknowledge_or_approve_generated_docs(repo: Path, target: str) -> None:
    with pytest.raises(docs.ContractError):
        docs.acknowledge_review(repo, target)


def test_line_endings_do_not_change_review_fingerprints(repo: Path) -> None:
    for newline in (b"\r\n", b"\n"):
        for path in (repo / docs.CORE["workflow"], repo / "src/hwpxfiller/webapp/app.py"):
            normalized = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(normalized.replace(b"\n", newline))
        assert docs.check(repo) == []


def test_file_and_global_budgets_cannot_be_bypassed_by_review(repo: Path) -> None:
    data = _data(repo)
    next(d for d in data["document"] if d["role"] == "workflow")["max_lines"] = 20
    _manifest(repo, data)
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + "line\n" * 30, encoding="utf-8")
    _review(repo, "workflow-secondary")
    assert "line budget exceeded: docs/workflow.md" in docs.check(repo)
    data = _data(repo)
    next(d for d in data["document"] if d["role"] == "workflow")["max_lines"] = 2000
    _manifest(repo, data)
    p.write_text(docs.read(p) + "line\n" * docs.MAX_CORE_LINES, encoding="utf-8")
    _review(repo, "workflow-secondary")
    assert any("canonical total budget" in p for p in docs.check(repo))


def test_long_single_line_cannot_bypass_total_budget(repo: Path) -> None:
    p = repo / docs.CORE["workflow"]
    p.write_text(docs.read(p) + "x" * docs.MAX_CORE_BYTES + "\n", encoding="utf-8")
    _review(repo, "workflow-secondary")
    assert any("canonical total budget" in p for p in docs.check(repo))


def test_topic_requires_sources_and_tests(repo: Path) -> None:
    data = _data(repo)
    data["topic"][0]["sources"] = []
    _manifest(repo, data)
    assert any("needs sources and tests" in p for p in docs.check(repo))


def test_paths_cannot_escape_repository(repo: Path) -> None:
    data = _data(repo)
    data["topic"][0]["sources"] = ["../outside.py"]
    _manifest(repo, data)
    assert any("unsafe relative path" in p for p in docs.check(repo))


def test_duplicate_unicode_heading_slugs() -> None:
    assert {"상태", "상태-1", "api-호출"} <= docs.anchors("## 상태\n## 상태\n## `API` 호출\n")


def test_route_uses_the_same_owners_as_review(repo: Path) -> None:
    assert docs.route(repo, "workflow") == ["docs/workflow.md#workflow-primary", "docs/workflow.md#workflow-secondary"]
    assert docs.route(repo, "src/hwpxfiller/webapp/app.py") == ["docs/workflow.md#workflow-primary"]
    assert docs.route(repo, "workflow-secondary") == ["docs/workflow.md#workflow-secondary"]
    with pytest.raises(docs.ContractError, match="no document owner"):
        docs.route(repo, "src/unowned.py")


def test_product_adapter_is_generated_not_independently_editable(repo: Path) -> None:
    output = repo / docs.PRODUCT
    assert "<!-- impeccable:product-schema 1 -->" in docs.read(output)
    assert "## Platform\n\nweb" in docs.read(output)
    output.write_text(docs.read(output) + "manual edit\n", encoding="utf-8")
    assert f"generated drift: {docs.PRODUCT}" in docs.check(repo)
    docs.write_generated(repo)
    assert docs.check(repo) == []


def test_product_source_is_projected_without_acknowledging_review(repo: Path) -> None:
    source = repo / docs.CORE["product"]
    source.write_text(docs.read(source).replace("original", "product change"), encoding="utf-8")
    docs.write_generated(repo)
    assert "product change" in docs.read(repo / docs.PRODUCT)
    assert "review required: docs/product.md#product-primary" in docs.check(repo)


def test_unowned_canonical_preamble_is_rejected(repo: Path) -> None:
    source = repo / docs.CORE["workflow"]
    source.write_text(docs.read(source).replace("# workflow\n\n", "# workflow\n\nUnowned prose\n\n"), encoding="utf-8")
    assert any("unowned canonical preamble" in p for p in docs.check(repo))


def test_route_respects_nonrecursive_source_globs(repo: Path) -> None:
    with pytest.raises(docs.ContractError, match="no document owner"):
        docs.route(repo, "src/hwpxfiller/webapp/nested/new.py")


def test_product_platform_is_required_by_the_compatibility_adapter(repo: Path) -> None:
    p = repo / docs.CORE["product"]
    p.write_text(docs.read(p).replace("### Platform", "### Removed field"), encoding="utf-8")
    assert any("missing/invalid Platform" in p for p in docs.check(repo))


def test_narrowing_a_glob_requires_review_even_with_identical_matches(repo: Path) -> None:
    data = _data(repo)
    topic = next(t for t in data["topic"] if t["id"] == "workflow-primary")
    topic["sources"] = sorted(p.relative_to(repo).as_posix()
                              for p in (repo / "src/hwpxfiller/webapp").glob("*.py"))
    _manifest(repo, data)
    assert "review required: docs/workflow.md#workflow-primary" in docs.check(repo)


def test_branding_manifest_still_identifies_the_same_asset_bytes() -> None:
    import hashlib

    manifest = json.loads(docs.read(docs.ROOT / "assets/branding/branding-manifest.json"))
    assert set(manifest) == {"generator_sha256", "inputs", "files"}
    for group in ("inputs", "files"):
        assert manifest[group]
        for name, digest in manifest[group].items():
            assert hashlib.sha256((docs.ROOT / name).read_bytes()).hexdigest() == digest, name
