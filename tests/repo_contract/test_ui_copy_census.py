"""사용자 문안 census — 화면 문장 수를 allowlist 로 못박는다.

새 문장은 기본 0 이다(`docs/COPY_STYLE_GUIDE.md` §1·§8). 이 게이트가 없던 동안 화면에
설계 산문이 계속 쌓였다("바꿀 것이 없어도 지금 연결을 확정해야 문서를 만들 수 있습니다",
"'{}' 을(를) 편집합니다. 저장된 매핑 N행을 불러왔습니다"). 규칙의 존재가 아니라 **결과**를
세는 층이라 스캐너를 그대로 부르고 다중집합으로 맞춘다.
"""

from __future__ import annotations

import ui_copy_census as census


def test_census_matches_allowlist() -> None:
    """실 스캔 다중집합 == `docs/ui_copy_census.toml` 다중집합."""
    problems = census.diff_report()
    assert not problems, "사용자 문안 census 불일치:\n" + "\n".join(problems)


def test_new_sentences_are_not_narration() -> None:
    """낭독 패턴에 걸리는 항목은 전부 `legacy = true` 여야 한다(새 문장은 통과해야 한다)."""
    offenders: list[str] = []
    for entry in census.load_allowlist():
        hits = census.narration_hits(entry["text"])
        if not hits or entry.get("legacy"):
            continue
        why = " / ".join(f"낭독 패턴 {number}: {reason}" for number, reason in hits)
        offenders.append(f"  {entry['file']}  {entry['text']}\n      {why}")
    assert not offenders, (
        "새 문장이 낭독 패턴에 걸린다(COPY_STYLE_GUIDE §8):\n"
        + "\n".join(offenders)
        + "\n\n낭독은 걷는 것이 답이다. `legacy = true` 는 이 PR 이전부터 서 있던 문장에만 붙고,"
        " 그 수는 늘지 않는다(줄이기만)."
    )


def test_legacy_flag_only_on_narration() -> None:
    """`legacy = true` 인데 어떤 낭독 패턴에도 안 걸리면 플래그 남용이다."""
    entries = census.load_allowlist()
    legacy = [entry for entry in entries if entry.get("legacy")]
    abusers = [
        f"  {entry['file']}  {entry['text']}"
        for entry in legacy
        if not census.narration_hits(entry["text"])
    ]
    assert not abusers, (
        f"`legacy = true` 가 낭독이 아닌 문장에 붙었다(현재 legacy {len(legacy)}건):\n"
        + "\n".join(abusers)
        + "\n\n플래그는 낭독 패턴에 걸린 기존 문장의 유예이지 일반 면제가 아니다."
    )
