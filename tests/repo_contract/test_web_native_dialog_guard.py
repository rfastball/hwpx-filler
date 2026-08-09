"""파괴 확인이 브라우저 네이티브 다이얼로그로 우회되지 않게 한다."""

from __future__ import annotations

import json
import re

from _web_source import REPO_ROOT, SOURCE_ROOT


def _without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", text)


def test_frontend_uses_the_shared_modal_instead_of_native_confirm_or_prompt() -> None:
    excluded = set(
        json.loads(
            (REPO_ROOT / "tests" / "static_closure_contract.json").read_text(encoding="utf-8")
        )["non_code_suffixes"]
    )
    banned = ("window.confirm", "window.prompt")
    offenders: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix in excluded:
            continue
        body = _without_comments(path.read_text(encoding="utf-8"))
        for term in banned:
            offenders.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}:{body.count(chr(10), 0, match.start()) + 1}: {term}"
                for match in re.finditer(re.escape(term), body)
            )
    assert not offenders, (
        "브라우저 네이티브 확인 UI 재유입; Modal.confirm/Modal.prompt를 사용하세요:\n"
        + "\n".join(offenders)
    )
