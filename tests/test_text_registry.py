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


def test_recursive_scan_finds_subfolder_templates(tmp_path):
    """R-info 2부 결정 5 — 하위폴더에 떨군 템플릿도 재귀로 찾아 올린다(조용한 누락 금지).

    이름 = 상대경로(확장자 제외)라 하위폴더 파일은 ``하위폴더/이름`` 으로 구분된다(#136 F1)."""
    d = _seed(tmp_path)
    sub = d / "탐색기묶음"
    sub.mkdir()
    (sub / "협조전.txt").write_text("수신: {{부서}}", encoding="utf-8")
    reg = TextTemplateRegistry(d)
    assert reg.count() == 3
    assert "탐색기묶음/협조전" in reg.names()  # 비재귀 glob 이던 시절엔 조용히 빠졌다


def test_recursive_scan_excludes_trash_subtrees(tmp_path):
    d = _seed(tmp_path)
    trash = d / ".trash" / "nested"
    trash.mkdir(parents=True)
    (trash / "삭제됨.txt").write_text("{{노출금지}}", encoding="utf-8")
    assert "삭제됨" not in TextTemplateRegistry(d).names()
    assert not any(".trash" in name for name in TextTemplateRegistry(d).names())


def test_load_resolves_subfolder_path(tmp_path):
    """list→load 왕복 정합 — 하위폴더 파일도 실제 경로로 열어야(루트 경로 재구성 금지)."""
    d = _seed(tmp_path)
    sub = d / "탐색기묶음"
    sub.mkdir()
    (sub / "협조전.txt").write_text("수신: {{부서}}", encoding="utf-8")
    reg = TextTemplateRegistry(d)
    t = reg.load("탐색기묶음/협조전")
    assert t.path == sub / "협조전.txt"  # 루트가 아니라 하위폴더 실경로
    assert t.fields() == ["부서"]


def test_same_stem_in_different_subfolders_are_distinct(tmp_path):
    """#136 리뷰 F1 — 동명 stem 이 두 하위폴더에 있어도 상대경로 이름으로 각각 유일하게 로드된다
    (stem 단독 이름이면 select→load 가 조용히 첫 파일만 열던 결함)."""
    d = _seed(tmp_path)
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "동명.txt").write_text("A: {{가}}", encoding="utf-8")
    (d / "b" / "동명.txt").write_text("B: {{나}}", encoding="utf-8")
    reg = TextTemplateRegistry(d)
    assert {"a/동명", "b/동명"} <= set(reg.names())
    assert reg.load("a/동명").content().startswith("A:")
    assert reg.load("b/동명").content().startswith("B:")  # 조용한 첫-파일 오픈 아님


def test_load_unknown_name_falls_back_to_root_path(tmp_path):
    """미발견 이름은 루트 경로로 구성(하위호환) — 아직 없는 파일 겨눔 등."""
    d = _seed(tmp_path)
    t = TextTemplateRegistry(d).load("없는이름")
    assert t.path == d / "없는이름.txt"
