"""실 나라장터 물품 공고 탐색 테스트셋 재수확 — ``tests/corpus/nara_mulpum/``.

``gen_scenario_fixtures.py`` (하드코딩 진실원 → **결정적**)와 달리 이 스크립트는
**라이브 API 취득이라 결정적이지 않다.** 재실행하면 그 시점의 공고로 *새* 세트를 만든다
(비트 재현 아님). 저장소에 커밋된 ``mulpum.json`` 이 동결본이며, 이 스크립트는 그 동결본을
**갱신·재생성**하는 용도다. 갱신하면 ``README.md`` 의 레코드→목적 매니페스트도 손봐야 한다.

무엇을 하나
-----------
1. ``NaraStdDataSource`` 로 최근 창(기본 14일)의 표준 입찰공고를 실 취득(실 파서·fail-closed
   경계를 실데이터로 태운다 = 수확이 곧 첫 테스트 패스).
2. ``bsnsDivNm=="물품"`` 필터.
3. PII 마스킹 — 공개 데이터이나 공무원 개인정보는 중립화:
   ``*OfclNm``→"담당자", ``*Tel`` 숫자→0, ``*EmailAdrs``→official@example.go.kr.
4. **목적별 명시 선택**(무작위 아님) — 각 레코드가 특정 실패 모드/다양성 축을 대표.
5. ``response.body.items[]`` 봉투로 얼리고 ``parse()`` 왕복 검증.

실행::

    python scripts/build_nara_testset.py                 # 최근 14일
    python scripts/build_nara_testset.py --bgn 202606150000 --end 202607142359
    python scripts/build_nara_testset.py --dry-run       # 파일 안 씀, 매니페스트만

ServiceKey 는 ``.secrets/nara_service_key`` (git-ignored)에서 읽는다. 없으면 시끄럽게 실패.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from hwpxfiller.data.nara import DT_FMT, NaraFetchError, NaraStdDataSource

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글 매니페스트 깨짐 방지

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "tests" / "corpus" / "nara_mulpum"
OUT_JSON = OUT_DIR / "mulpum.json"
KEY_FILE = ROOT / ".secrets" / "nara_service_key"


# ------------------------------------------------------------------ PII 마스킹
def redact(rec: "dict[str, str]") -> "dict[str, str]":
    out: "dict[str, str]" = {}
    for k, v in rec.items():
        if k.endswith("OfclNm"):
            out[k] = "담당자" if v else v
        elif k.endswith("Tel"):
            out[k] = re.sub(r"\d", "0", v)
        elif k.endswith("EmailAdrs"):
            out[k] = "official@example.go.kr" if v else v
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ 목적별 선택
def curate(recs: "list[dict[str, str]]") -> "dict[str, list[str]]":
    """레코드 → 선택 목적 목록. 각 축마다 안 뽑힌 레코드를 우선(세트를 넓게 편다)."""
    picked: "dict[str, list[str]]" = {}

    def take(r, why):
        picked.setdefault(r["bidNtceNo"], [])
        if why not in picked[r["bidNtceNo"]]:
            picked[r["bidNtceNo"]].append(why)

    def take_spread(pred, why):
        matches = [r for r in recs if pred(r)]
        if not matches:
            return
        fresh = [r for r in matches if r["bidNtceNo"] not in picked]
        take((fresh or matches)[0], why)

    def empties(r):
        return sum(1 for v in r.values() if not str(v).strip())

    def amt(r):
        v = r.get("asignBdgtAmt", "0")
        return int(v) if v.isdigit() else 0

    # F1 — 날짜 필드 통째 결측: 일자/시각 서식의 "" 경계
    for r in [x for x in recs if not x.get("bidBeginDate", "").strip()][:2]:
        take(r, "F1: 입찰일자 전체 결측 — 일자/시각 서식의 빈값 경계")

    # F3 — 공고명 중복: filename_pattern 충돌/덮어쓰기(둘 다 넣어야 재현)
    namec = Counter(r["bidNtceNm"] for r in recs)
    dupname = next((n for n, c in namec.items() if c >= 2), None)
    if dupname:
        for r in [x for x in recs if x["bidNtceNm"] == dupname][:2]:
            take(r, "F3: 공고명 중복 — 파일명 충돌/데이터 손실 재현")

    # tour — 공고명 길이 극단 / 최다 결측
    byname = sorted(recs, key=lambda r: len(r["bidNtceNm"]))
    if byname:
        take(byname[0], "tour: 최단 공고명")
        take(byname[-1], "tour: 최장 공고명(영문혼합 가능)")
        take(max(recs, key=empties), "tour: 최다 빈필드 레코드")

    # 계약/입찰 형태·제한 다양성
    take_spread(lambda r: "수의" in r.get("cntrctCnclsMthdNm", "")
                or "수의" in r.get("bidwinrDcsnMthdNm", ""),
                "다양성: 수의계약(경쟁입찰 아님) 흐름")
    take_spread(lambda r: "재입찰" in r.get("bidNtceSttusNm", ""),
                "다양성: 재입찰공고 상태")
    take_spread(lambda r: "단가" in r.get("cntrctCnclsSttusNm", "")
                or "단가" in r.get("bidNtceNm", ""),
                "다양성: 단가계약")
    take_spread(lambda r: bool(r.get("opengPlce", "").strip())
                and "나라장터" not in r["opengPlce"],
                "다양성: 자유서식 개찰장소(방번호 등)")
    take_spread(lambda r: r.get("indstrytyLmtYn") == "Y"
                and bool(r.get("bidprcPsblIndstrytyNm", "").strip()),
                "다양성: 업종제한 Y(투찰가능업종 채워짐)")
    take_spread(lambda r: r.get("rgnLmtYn") == "Y", "다양성: 지역제한 Y")
    take_spread(lambda r: r.get("elctrnBidYn") == "N",
                "다양성: 전자입찰 N(오프라인 투찰)")
    take_spread(lambda r: r.get("cmmnCntrctYn") == "Y", "다양성: 공동계약 가능")

    # 금액 극단(정수 문자열 서식 경계)
    if recs:
        top = max(recs, key=amt)
        take_spread(lambda r, top=top: r["bidNtceNo"] == top["bidNtceNo"],
                    "tour: 최대 배정예산")
        pos = [x for x in recs if amt(x) > 0]
        if pos:
            lo = min(pos, key=amt)
            take_spread(lambda r, lo=lo: r["bidNtceNo"] == lo["bidNtceNo"],
                        "tour: 최소 배정예산")

    # 기준선(happy-path): 결측 최소 + 경쟁입찰 + 날짜 완비 → 회귀 승격 1순위
    clean = sorted(
        [r for r in recs if r.get("bidBeginDate", "").strip()
         and "경쟁" in r.get("cntrctCnclsMthdNm", "")],
        key=empties,
    )
    if clean:
        take(clean[0], "기준선: 필드 완비 happy-path(회귀 승격 1순위)")

    return picked


def build_envelope(items: "list[dict[str, str]]", window: str) -> dict:
    return {
        "_comment": (
            f"실 나라장터 표준서비스 물품 공고 다양성 표본({window} 취득). "
            "PII 마스킹: 담당자명->'담당자', 전화 숫자->0, 이메일->official@example.go.kr. "
            "각 레코드의 선택 목적은 README.md 참조. NaraStdDataSource.parse() 가 소비. "
            "재생성: scripts/build_nara_testset.py (라이브 취득이라 비결정적)."
        ),
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {
                "pageNo": 1,
                "numOfRows": len(items),
                "totalCount": len(items),
                "items": items,
            },
        },
    }


def main() -> int:
    now = datetime.now()
    ap = argparse.ArgumentParser(description="나라장터 물품 탐색 테스트셋 재수확")
    ap.add_argument("--bgn", default=(now - timedelta(days=14)).strftime(DT_FMT),
                    help="시작 일시 YYYYMMDDHHMM (기본: 14일 전)")
    ap.add_argument("--end", default=now.strftime(DT_FMT),
                    help="종료 일시 YYYYMMDDHHMM (기본: 현재)")
    ap.add_argument("--num-rows", type=int, default=100, help="취득 건수(1페이지)")
    ap.add_argument("--dry-run", action="store_true", help="파일 안 씀, 매니페스트만 출력")
    args = ap.parse_args()

    if not KEY_FILE.exists():
        print(f"[중단] ServiceKey 없음: {KEY_FILE}", file=sys.stderr)
        return 2
    key = KEY_FILE.read_text(encoding="utf-8").strip()

    src = NaraStdDataSource(key, args.bgn, args.end, num_rows=args.num_rows)
    print(f"[취득] {src.redacted_url()}")
    try:
        recs = [redact(r) for r in src.records()]  # 실 취득 — 깨지면 첫 finding
    except NaraFetchError as e:
        print(f"[FINDING] 취득 실패: {e}", file=sys.stderr)
        return 1

    div = Counter(r.get("bsnsDivNm", "(없음)") for r in recs)
    mulpum = [r for r in recs if r.get("bsnsDivNm") == "물품"]
    print(f"[취득] 전체 {len(recs)}건 {dict(div)} → 물품 {len(mulpum)}건")

    picked = curate(mulpum)
    by_no = {r["bidNtceNo"]: r for r in mulpum}
    items = [by_no[no] for no in picked]

    envelope = build_envelope(items, f"{args.bgn}~{args.end}")
    blob = json.dumps(envelope, ensure_ascii=False, indent=2)

    # 왕복 검증 — 얼린 봉투가 실 취득 파서를 통과하는가
    parsed = NaraStdDataSource.parse(blob.encode("utf-8"))
    assert len(parsed) == len(items), "parse 왕복 건수 불일치"

    print(f"\n[선택] {len(items)}건 (parse 왕복 OK):")
    for no, whys in picked.items():
        print(f"- {no} | {by_no[no]['bidNtceNm']}")
        for w in whys:
            print(f"    · {w}")

    if args.dry_run:
        print("\n[dry-run] 파일 미기록.")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(blob, encoding="utf-8")
    print(f"\n[기록] {OUT_JSON.relative_to(ROOT)} ({len(blob)}B)")
    print("[알림] README.md 의 레코드→목적 매니페스트를 위 선택과 맞춰 갱신하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
