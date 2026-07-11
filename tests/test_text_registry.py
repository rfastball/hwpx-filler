"""txt 기안 템플릿 레지스트리 — Qt 불필요(헤드리스). 루트 나열·로드·필드 추출.

HWPX Job 레지스트리와 별도 루트(ADR A) — 저장 Job 없는 경량 재사용 템플릿 목록.
"""
from __future__ import annotations

from hwpxfiller.core.text_registry import TextTemplateRegistry, default_text_templates_dir


def _seed(tmp_path):
    d = tmp_path / "text_templates"
    d.mkdir()
    (d / "온나라_기안.txt").write_text(
        "제목: {{공고명}}\n담당: {{담당자}}", encoding="utf-8"
    )
    (d / "회의결과보고.txt").write_text("안건: {{공고명}}", encoding="utf-8")
    return d


def test_lists_sorted_and_counts(tmp_path):
    reg = TextTemplateRegistry(_seed(tmp_path))
    assert reg.count() == 2
    assert reg.names() == sorted(["온나라_기안", "회의결과보고"])  # 파일명 정렬


def test_load_content_and_fields(tmp_path):
    reg = TextTemplateRegistry(_seed(tmp_path))
    t = reg.load("온나라_기안")
    assert "제목:" in t.content()
    assert t.fields() == ["공고명", "담당자"]


def test_empty_or_missing_dir(tmp_path):
    reg = TextTemplateRegistry(tmp_path / "nope")
    assert reg.names() == [] and reg.count() == 0


def test_default_dir_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_text_templates_dir() == tmp_path / "text_templates"
