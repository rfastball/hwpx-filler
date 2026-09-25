"""Documentation must fail closed on inventory, generated facts and review drift."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import docs_contract as docs


def _put(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(root: Path, records: list[dict]) -> None:
    lines = ['schema = "docs-contract/v1"']
    for item in records:
        lines.extend(["", "[[document]]"])
        for key, value in item.items():
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    _put(root, docs.MANIFEST, "\n".join(lines) + "\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
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
    _put(tmp_path, "src/hwpxfiller/webapp/action_registry.py", '_COMMON = {"ping": _schema(optional="epoch")}\n'
         '_REGISTRY = {"job": {**_COMMON, "run": _schema("row", "confirm")}}\n')
    _put(tmp_path, ".github/workflows/quality.yml", 'name: quality\njobs:\n'
         '  static:\n    steps: []\n  quality-gate:\n    needs:\n      - static\n    steps: []\n')
    _put(tmp_path, "tests/evidence.py", "def test_behavior(): pass\n")
    _put(tmp_path, "docs/current.md", '# Current\n\n## 상태\n\n[상태](#상태)\n')
    _put(tmp_path, "docs/MAINTENANCE.md", "# Guide\n")
    _put(tmp_path, "frontend/js/bridge.js", "// bridge\n")
    records = [
        {"path": docs.INDEX, "kind": "generated", "role": "navigation", "max_lines": 500},
        {"path": docs.REFERENCE, "kind": "generated", "role": "reference", "max_lines": 500},
        {"path": "docs/current.md", "kind": "current", "role": "behavior", "max_lines": 20,
         "sources": ["src/hwpxfiller/webapp/*.py"], "tests": ["tests/evidence.py"],
         "source_sha256": "0" * 64, "body_sha256": "0" * 64},
    ]
    records.append({"path": "docs/MAINTENANCE.md", "kind": "research",
                    "role": "guide", "max_lines": 30})
    _manifest(tmp_path, records)
    docs.write_generated(tmp_path)
    docs.acknowledge_review(tmp_path, "docs/current.md")
    assert docs.check(tmp_path) == []
    return tmp_path


def test_repository_documentation_contract() -> None:
    assert docs.check(docs.ROOT) == []


def test_version_change_requires_regeneration(repo: Path) -> None:
    p = repo / "pyproject.toml"
    p.write_text(docs.read(p).replace("1.0.0", "1.1.0"))
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)
    docs.write_generated(repo)
    assert "`1.1.0`" in docs.read(repo / docs.REFERENCE)
    assert docs.check(repo) == []


def test_added_bridge_method_is_not_silently_omitted(repo: Path) -> None:
    p = repo / "src/hwpxfiller/webapp/app.py"
    p.write_text(docs.read(p) + "    def new_action(self, value): pass\n")
    errors = docs.check(repo)
    assert f"generated drift: {docs.REFERENCE}" in errors
    assert "review required: docs/current.md" in errors
    docs.write_generated(repo)
    assert "`new_action`" in docs.read(repo / docs.REFERENCE)
    assert "review required: docs/current.md" in docs.check(repo)


def test_registry_expansions_and_optional_keys_are_generated(repo: Path) -> None:
    assert docs.registry(repo) == {"job": {"ping": ("", "epoch"), "run": ("row", "confirm")}}
    p = repo / "src/hwpxfiller/webapp/action_registry.py"
    p.write_text(docs.read(p).replace('"row", "confirm"', '"row token", "confirm"'))
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)


def test_unrecognized_registry_fails_loudly(repo: Path) -> None:
    _put(repo, "src/hwpxfiller/webapp/action_registry.py", "_REGISTRY = dynamic_registry()\n")
    assert any("literal dictionaries" in p for p in docs.check(repo))


def test_changed_ci_dependency_list_is_generated(repo: Path) -> None:
    p = repo / ".github/workflows/quality.yml"
    p.write_text(docs.read(p).replace("  static:", "  extra:\n    steps: []\n  static:")
                 .replace("      - static\n", "      - static\n      - extra\n"))
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)


@pytest.mark.parametrize("name", ["docs/new.md", "docs/new.html", "docs/new.toml"])
def test_unregistered_document_is_rejected(repo: Path, name: str) -> None:
    _put(repo, name, "unregistered")
    assert any("unregistered=" in p and name in p for p in docs.check(repo))


def test_deleted_document_is_rejected(repo: Path) -> None:
    (repo / "docs/current.md").unlink()
    assert any("missing=" in p and "docs/current.md" in p for p in docs.check(repo))


@pytest.mark.parametrize("field,value", [("path", "docs/current.md"), ("role", "behavior")])
def test_duplicate_path_or_role_is_rejected(repo: Path, field: str, value: str) -> None:
    records = docs.documents(repo)
    records[0][field] = value
    _manifest(repo, records)
    assert any("duplicate document" in p for p in docs.check(repo))


@pytest.mark.parametrize("target", ["missing.md", "current.md#없는-절", "../missing.png"])
def test_broken_local_links_and_fragments_are_rejected(repo: Path, target: str) -> None:
    _put(repo, "docs/current.md", f"# Current\n\n[link]({target})\n")
    assert any("broken " in p and target in p for p in docs.check(repo))


def test_reference_style_and_html_links_are_checked(repo: Path) -> None:
    _put(repo, "docs/current.md", '[link][x]\n\n[x]: missing.md\n<img src="missing.png">\n')
    errors = docs.check(repo)
    assert any("missing.md" in p for p in errors)
    assert any("missing.png" in p for p in errors)


def test_fenced_examples_and_external_links_do_not_require_network(repo: Path) -> None:
    _put(repo, "docs/current.md", '# Current\n\n```md\n[example](missing.md)\n```\n'
         '[online](https://example.invalid/does-not-need-network)\n')
    docs.acknowledge_review(repo, "docs/current.md")
    assert docs.check(repo) == []


def test_source_path_rename_requires_review_even_when_bytes_match(repo: Path) -> None:
    source = repo / "src/hwpxfiller/webapp/other.py"
    source.write_text("# source\n")
    docs.acknowledge_review(repo, "docs/current.md")
    source.rename(source.with_name("renamed.py"))
    assert "review required: docs/current.md" in docs.check(repo)


def test_new_file_in_source_glob_requires_review(repo: Path) -> None:
    _put(repo, "src/hwpxfiller/webapp/new.py", "# new\n")
    assert "review required: docs/current.md" in docs.check(repo)


def test_empty_source_glob_fails_instead_of_shrinking_scope(repo: Path) -> None:
    records = docs.documents(repo)
    records[2]["sources"] = ["src/missing/*.py"]
    _manifest(repo, records)
    assert any("empty source glob" in p for p in docs.check(repo))


def test_missing_evidence_test_is_rejected(repo: Path) -> None:
    (repo / "tests/evidence.py").unlink()
    assert any("missing/invalid evidence test" in p for p in docs.check(repo))


def test_prose_edits_require_review_and_write_does_not_acknowledge_them(repo: Path) -> None:
    before = docs.read(repo / docs.MANIFEST)
    _put(repo, "docs/current.md", "# Changed narrative\n")
    docs.write_generated(repo)
    assert docs.read(repo / docs.MANIFEST) == before
    assert "review required: docs/current.md" in docs.check(repo)
    docs.acknowledge_review(repo, "docs/current.md")
    assert docs.check(repo) == []


def test_review_only_updates_the_named_document(repo: Path) -> None:
    records = docs.documents(repo)
    second = dict(records[2], path="docs/other.md", role="other")
    records.append(second)
    _put(repo, "docs/other.md", "# Other\n")
    _manifest(repo, records)
    docs.write_generated(repo)
    docs.acknowledge_review(repo, "docs/other.md")
    other_before = docs.documents(repo)[-1]
    _put(repo, "docs/current.md", "# Updated\n")
    docs.acknowledge_review(repo, "docs/current.md")
    assert docs.documents(repo)[-1] == other_before


def test_review_cannot_relabel_generated_docs_as_reviewed(repo: Path) -> None:
    with pytest.raises(docs.ContractError, match="one current document"):
        docs.acknowledge_review(repo, docs.REFERENCE)


def test_line_endings_do_not_change_review_fingerprints(repo: Path) -> None:
    for path in (repo / "docs/current.md", repo / "src/hwpxfiller/webapp/app.py"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert docs.check(repo) == []


def test_line_budget_fails_even_after_review(repo: Path) -> None:
    _put(repo, "docs/current.md", "# Long\n" + "line\n" * 25)
    docs.acknowledge_review(repo, "docs/current.md")
    assert "line budget exceeded: docs/current.md" in docs.check(repo)


def test_no_current_doc_without_review_inputs(repo: Path) -> None:
    records = docs.documents(repo)
    records[2]["sources"] = []
    _manifest(repo, records)
    assert any("needs sources and tests" in p for p in docs.check(repo))


def test_duplicate_unicode_heading_slugs() -> None:
    assert {"상태", "상태-1", "api-호출"} <= docs.anchors("## 상태\n## 상태\n## `API` 호출\n")


def test_paths_cannot_escape_repository(repo: Path) -> None:
    records = docs.documents(repo)
    records[2]["sources"] = ["../outside.py"]
    _manifest(repo, records)
    assert any("unsafe relative path" in p for p in docs.check(repo))


def test_selftest_surface_is_generated_separately(repo: Path) -> None:
    text = docs.read(repo / docs.REFERENCE)
    assert "## Selftest 전용 공개 메서드" in text
    assert "`selftest_claim`" in text
    p = repo / "src/hwpxfiller/webapp/selftest_api.py"
    p.write_text(docs.read(p) + "    def selftest_extra(self): pass\n")
    assert f"generated drift: {docs.REFERENCE}" in docs.check(repo)
