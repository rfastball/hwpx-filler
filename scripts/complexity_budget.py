"""복잡도 예산 원장 — 판정 규칙과 작성기(writer)의 단일 출처.

상한(`complexity_measure.CEILINGS`)은 목표 품질 값이다. 오늘 그것을 넘는 단위만
`tests/contracts/complexity-budget.toml` 에 **실측값으로 동결**되고, 원장은 내려가기만 한다.

판정(계약 테스트 `tests/repo_contract/test_complexity_budget.py` 가 이 함수들을 부른다):

1. 초과 금지 — 원장 밖 단위는 등급 상한 이하, 원장 단위는 동결값 이하.
2. 닫힌 원장 — `origin/master` 와의 merge-base 원장보다 항목을 늘리거나 값을 올리면 실패.
   그 항목에 **새** `override = "#이슈"` 와 `reason` 이 있을 때만 허용한다(탈출구).
   merge-base 에 원장이 없으면(도입 커밋) 모든 항목이 실측과 정확히 같아야 한다.
3. 뒤처진 래칫 — 실측이 동결값×0.9 보다 작으면 `--tighten` 으로 내리라고 실패한다
   (10% 여유는 병렬 브랜치끼리 원장 충돌을 줄인다).
4. 낡은 항목 — 단위가 사라졌거나(삭제·개명) 등급 상한 안으로 들어왔으면 항목 삭제.

    uv run python scripts/complexity_budget.py --check         # 계약 테스트와 같은 판정을 출력
    uv run python scripts/complexity_budget.py --tighten       # 내리기·지우기만(올리지 않는다)
    uv run python scripts/complexity_budget.py --write-initial # 기준에 원장이 없을 때만
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import complexity_measure as measure

ROOT = Path(__file__).resolve().parents[1]
LEDGER = "tests/contracts/complexity-budget.toml"
SCHEMA = "complexity-budget/v1"
BASE_REF = "origin/master"
RATCHET = 0.9
REMEDY = "처방: 원장 상향이 아니라 책임 분리."

Key = tuple[str, str]


class LedgerError(RuntimeError):
    """원장·기준을 읽을 수 없다 — 판정 근거가 없으므로 실패다."""


@dataclass(frozen=True)
class Entry:
    value: int
    override: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Reading:
    unit: measure.Unit
    metric: str
    value: int

    @property
    def ceiling(self) -> int:
        return measure.CEILINGS[self.unit.tier][self.metric]


# ───────────────────────── 원장 입출력 ─────────────────────────


def _entry(ident: str, metric: str, raw: object) -> Entry:
    if metric not in measure.METRICS:
        raise LedgerError(f"{ident}: 모르는 축 `{metric}` — {measure.METRICS} 중 하나여야 합니다")
    if isinstance(raw, int):
        return Entry(raw)
    if isinstance(raw, dict) and isinstance(raw.get("value"), int):
        return Entry(raw["value"], raw.get("override"), raw.get("reason"))
    raise LedgerError(f"{ident}.{metric}: 정수 또는 {{ value, override, reason }} 표여야 합니다")


def parse_ledger(text: str) -> dict[Key, Entry]:
    data = tomllib.loads(text)
    if data.get("schema") != SCHEMA:
        raise LedgerError(f"원장 schema 가 {SCHEMA!r} 가 아닙니다: {data.get('schema')!r}")
    entries: dict[Key, Entry] = {}
    for ident, metrics in data.get("budget", {}).items():
        for metric, raw in metrics.items():
            entries[(ident, metric)] = _entry(ident, metric, raw)
    return entries


def read_ledger(root: Path = ROOT) -> dict[Key, Entry]:
    path = root / LEDGER
    if not path.is_file():
        raise LedgerError(f"{LEDGER} 가 없습니다 — 도입 시에만 `--write-initial` 로 만듭니다")
    return parse_ledger(path.read_text(encoding="utf-8"))


_HEADER = """\
# 복잡도 예산 동결 원장 — 상한을 넘는 단위만, 실측값을 동결 상한으로 적는다.
#
# 이 파일은 **내려가기만** 한다. 실패를 고치는 길은 원장 상향이 아니라 책임 분리다.
# 상한·측정 규칙: scripts/complexity_measure.py · 판정·작성기: scripts/complexity_budget.py
#   uv run python scripts/complexity_budget.py --tighten   # 줄어든 값 내리기·낡은 항목 지우기
# 불가피한 상향·신규 항목은 그 항목을 표로 쓰고 새 이슈를 단다(탈출구):
#   function_complexity = { value = 14, override = "#1234", reason = "왜 지금 쪼갤 수 없는가" }
"""


def _toml_value(entry: Entry) -> str:
    if entry.override is None and entry.reason is None:
        return str(entry.value)
    parts = [f"value = {entry.value}"]
    if entry.override is not None:
        parts.append(f"override = {json.dumps(entry.override, ensure_ascii=False)}")
    if entry.reason is not None:
        parts.append(f"reason = {json.dumps(entry.reason, ensure_ascii=False)}")
    return "{ " + ", ".join(parts) + " }"


def dump_ledger(entries: dict[Key, Entry]) -> str:
    lines = [_HEADER, f'schema = "{SCHEMA}"']
    for ident in sorted({ident for ident, _ in entries}):
        lines += ["", f"[budget.{json.dumps(ident, ensure_ascii=False)}]"]
        for metric in measure.METRICS:
            if (ident, metric) in entries:
                lines.append(f"{metric} = {_toml_value(entries[(ident, metric)])}")
    return "\n".join(lines) + "\n"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              encoding="utf-8", check=False)
    except FileNotFoundError as error:
        raise LedgerError("git 을 찾지 못했습니다 — 닫힌 원장 판정은 merge-base 원장이 필요합니다") from error


def base_ledger(root: Path = ROOT) -> dict[Key, Entry] | None:
    """`origin/master` 와의 merge-base 원장. 그 커밋에 원장이 없으면 None(도입 커밋)."""
    found = _git(root, "merge-base", "HEAD", BASE_REF)
    if found.returncode != 0:
        raise LedgerError(
            f"`git merge-base HEAD {BASE_REF}` 실패 — 기준을 모르면 닫힌 원장을 판정할 수 없습니다. "
            f"`git fetch origin master` 로 기준을 받으세요(CI 는 checkout `fetch-depth: 0`).\n"
            + found.stderr.strip()
        )
    spec = f"{found.stdout.strip()}:{LEDGER}"
    if _git(root, "cat-file", "-e", spec).returncode != 0:
        return None
    return parse_ledger(_git(root, "show", spec).stdout)


# ───────────────────────── 측정 → 판독 ─────────────────────────


def readings(units: dict[str, measure.Unit]) -> dict[Key, Reading]:
    return {
        (ident, metric): Reading(unit, metric, value)
        for ident, unit in units.items()
        for metric, value in unit.metrics.items()
    }


def over_ceiling(found: dict[Key, Reading]) -> dict[Key, Entry]:
    return {key: Entry(r.value) for key, r in found.items() if r.value > r.ceiling}


# ───────────────────────── 처방 ─────────────────────────

_PREFIX = re.compile(r"^(?:[a-z0-9]+(?=_)|[a-z0-9]+(?=[A-Z])|[A-Z][a-z0-9]*|[a-z0-9]+)")


def _prefix(name: str) -> str:
    bare = name.lstrip("_#")
    match = _PREFIX.match(bare)
    if not match:
        return name
    token = match.group(0)
    rest = bare[len(token):]
    if not rest:
        return bare
    return f"{token}_*" if rest.startswith("_") else f"{token}*"


def _class_hint(methods: list[str]) -> str:
    groups = Counter(_prefix(name) for name in methods).most_common(6)
    listed = " ".join(f"{label}({count})" for label, count in groups)
    return f"메서드 접두 묶음: {listed} — 묶음마다 협력 객체·별도 모듈로 옮기세요."


def _module_hint(tops: list) -> str:
    biggest = sorted(tops, key=lambda top: -top[1])[:5]
    listed = " ".join(f"{name}({size})" for name, size in biggest)
    return f"가장 큰 최상위 정의(문장 수): {listed} — 응집 단위별로 모듈을 나누세요."


def _function_hint(blocks: list, metric: str) -> str:
    column = 3 if metric == "function_complexity" else 2
    biggest = sorted(blocks, key=lambda block: -block[column])[:3]
    if not biggest or biggest[0][column] == 0:
        return "분기·문장을 이름 있는 보조 함수로 추출하세요."
    listed = " ".join(f"L{line} {kind}({stmts}문장/분기 {branches})"
                      for line, kind, stmts, branches in biggest)
    return f"가장 큰 몸체 블록: {listed} — 블록을 이름 있는 함수로 추출하세요."


def prescription(reading: Reading) -> str:
    detail = reading.unit.detail
    if reading.metric == "class_methods":
        return _class_hint(detail)
    if reading.metric == "module_statements":
        return _module_hint(detail)
    return _function_hint(detail, reading.metric)


def overflow_message(reading: Reading, entry: Entry | None) -> str:
    unit, ceiling = reading.unit, reading.ceiling
    limit = (f"상한 {ceiling}({unit.tier} 등급)" if entry is None
             else f"동결값 {entry.value}(원장 · {unit.tier} 상한 {ceiling})")
    return (f"[복잡도 예산] {unit.ident} — {reading.metric} {reading.value} > {limit}\n"
            f"  {REMEDY} {prescription(reading)}")


# ───────────────────────── 판정 ─────────────────────────


def exceedances(found: dict[Key, Reading], ledger: dict[Key, Entry]) -> list[str]:
    messages = []
    for key, reading in sorted(found.items()):
        entry = ledger.get(key)
        limit = reading.ceiling if entry is None else entry.value
        if reading.value > limit:
            messages.append(overflow_message(reading, entry))
    return messages


def stale_entries(found: dict[Key, Reading], ledger: dict[Key, Entry]) -> list[str]:
    messages = []
    for ident, metric in sorted(ledger):
        reading = found.get((ident, metric))
        if reading is None:
            messages.append(f"[복잡도 예산] {ident} — {metric}: 단위가 사라졌습니다(삭제·개명). "
                            "원장 항목을 지우세요(`--tighten`).")
        elif reading.value <= reading.ceiling:
            messages.append(f"[복잡도 예산] {ident} — {metric} {reading.value} ≤ 상한 "
                            f"{reading.ceiling}: 상한 안으로 들어왔습니다. 원장 항목을 지우세요(`--tighten`).")
    return messages


def lagging_entries(found: dict[Key, Reading], ledger: dict[Key, Entry]) -> list[str]:
    messages = []
    for key, entry in sorted(ledger.items()):
        reading = found.get(key)
        if reading and reading.ceiling < reading.value < entry.value * RATCHET:
            messages.append(f"[복잡도 예산] {key[0]} — {key[1]} 실측 {reading.value} < 동결값 "
                            f"{entry.value}×{RATCHET}: 래칫이 뒤처졌습니다. "
                            "`uv run python scripts/complexity_budget.py --tighten` 으로 내리세요.")
    return messages


def _fresh_override(entry: Entry, before: Entry | None) -> bool:
    if not (entry.override and entry.reason and re.fullmatch(r"#\d+", entry.override)):
        return False
    return before is None or before.override != entry.override


def closed_violations(ledger: dict[Key, Entry], base: dict[Key, Entry] | None,
                      found: dict[Key, Reading]) -> list[str]:
    if base is None:
        return _bootstrap_violations(ledger, found)
    messages = []
    for key, entry in sorted(ledger.items()):
        before = base.get(key)
        if before is not None and entry.value <= before.value:
            continue
        if _fresh_override(entry, before):
            continue
        change = "새 항목" if before is None else f"{before.value} → {entry.value} 상향"
        messages.append(
            f"[복잡도 예산] {key[0]} — {key[1]}: 원장 {change}은 닫혀 있습니다. {REMEDY} "
            "개명·이동이라도 상한을 넘는 채로 옮기면 새 항목입니다. 정말 불가피하면 그 항목에 "
            '새 override = "#이슈번호" 와 reason 을 적으세요.'
        )
    return messages


def _bootstrap_violations(ledger: dict[Key, Entry], found: dict[Key, Reading]) -> list[str]:
    messages = []
    for key, entry in sorted(ledger.items()):
        reading = found.get(key)
        if reading is None or entry.value != reading.value or entry.override is not None:
            messages.append(f"[복잡도 예산] {key[0]} — {key[1]}: 기준에 원장이 없는 도입 커밋은 "
                            "모든 항목이 실측과 정확히 같아야 합니다(`--write-initial` 산출 그대로).")
    return messages


def tightened(ledger: dict[Key, Entry], found: dict[Key, Reading]) -> dict[Key, Entry]:
    """내리기·지우기만 한다 — 올리지도 더하지도 않는다."""
    kept = {}
    for key, entry in ledger.items():
        reading = found.get(key)
        if reading is None or reading.value <= reading.ceiling:
            continue
        kept[key] = Entry(min(entry.value, reading.value), entry.override, entry.reason)
    return kept


# ───────────────────────── CLI ─────────────────────────


def _check(root: Path, found: dict[Key, Reading]) -> int:
    ledger = read_ledger(root)
    messages = (exceedances(found, ledger) + closed_violations(ledger, base_ledger(root), found)
                + lagging_entries(found, ledger) + stale_entries(found, ledger))
    print("\n".join(messages) or f"복잡도 예산 통과 — 원장 항목 {len(ledger)}개")
    return 1 if messages else 0


def _write_initial(root: Path, found: dict[Key, Reading]) -> int:
    if (root / LEDGER).is_file() and base_ledger(root) is not None:
        print("기준(merge-base)에 원장이 이미 있습니다 — 상향은 닫혀 있으니 `--tighten` 을 쓰세요.")
        return 1
    entries = over_ceiling(found)
    (root / LEDGER).write_text(dump_ledger(entries), encoding="utf-8", newline="\n")
    print(f"{LEDGER}: 항목 {len(entries)}개를 실측값으로 동결했습니다.")
    return 0


def _tighten(root: Path, found: dict[Key, Reading]) -> int:
    ledger = read_ledger(root)
    kept = tightened(ledger, found)
    (root / LEDGER).write_text(dump_ledger(kept), encoding="utf-8", newline="\n")
    lowered = sum(1 for key, entry in kept.items() if entry.value < ledger[key].value)
    print(f"{LEDGER}: 지움 {len(ledger) - len(kept)} · 내림 {lowered} · 남음 {len(kept)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="복잡도 예산 원장 판정·작성기")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="계약 테스트와 같은 판정을 출력")
    mode.add_argument("--tighten", action="store_true", help="줄어든 값 내리기·낡은 항목 지우기")
    mode.add_argument("--write-initial", action="store_true", help="기준에 원장이 없을 때 생성")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # 콘솔 코드페이지와 무관하게 한글·기호를 그대로 낸다
            reconfigure(encoding="utf-8", errors="backslashreplace")
    units, _ = measure.measure_repository(ROOT)
    found = readings(units)
    if args.check:
        return _check(ROOT, found)
    if args.tighten:
        return _tighten(ROOT, found)
    return _write_initial(ROOT, found)


if __name__ == "__main__":
    sys.exit(main())
