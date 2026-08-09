"""packaged WebView2 selftest 증거의 환경/제품 실패 분류 — 재시도 허가의 유일한 판별기(#477).

`packaging/build.ps1` 의 외부망 양성 대조에서 창이 아예 안 뜨는 콜드 부팅 실패(#460 의 축,
#479 CI 실증)는 제품에 대해 아무것도 말하지 않는데도 제품 실패와 똑같이 quality-gate 를
막았다. 이 판별기가 그 두 축을 가른다: **환경으로 판정된 실패만** 유한 재시도가 허용되고,
제품 실패는 종전대로 즉시 빨갛다(`quality.yml` 의 「제품 단언은 재시도하지 않는다」 계약 보존).

판별을 prose 파싱이 아니라 **여기서** 하는 이유: PowerShell 인라인 술어는 음성 대조를 붙일
자리가 없다. 제품 결함을 환경으로 오분류하면 진짜 회귀가 재시도로 지워지므로, 그 술어의
판별력은 합성 표본으로 고정돼야 한다(`tests/repo_contract/test_packaging_contract.py`).

판정 규칙 — **제품 증거가 언제나 이긴다**:

1. runtime 에 제품을 판정할 증거가 하나라도 있으면(외부 fetch 가 완료·성공·차단됐거나 금지
   자원이 잡혔으면) 환경이 **아니다**. 창이 떠서 거기까지 갔다는 뜻이고, 그 뒤의 실패는
   제품 판정의 재료다.
2. 그 위에서, `error` 가 selftest 안정 코드 ``[evaluate-failed]`` 와 pywebview 의 부팅 실패
   문장(``Main window failed to start``)을 **둘 다** 들 때만 환경이다. 좁게 무는 것이 의도다
   — 오분류의 위험한 방향(제품→환경)을 좁힘이 막고, 반대 방향(환경→제품)은 재시도가 없을
   뿐 오늘과 같은 시끄러운 빨강이다.

종료 코드: 0 = 환경(재시도 허용) · 1 = 환경 아님(재시도 금지) · 2 = 판정 불능(증거를 읽지
못함 — 조용히 재시도로 접지 않고 시끄럽게 올린다).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: selftest 안정 코드(`selftest_api.CODE_EVALUATE_FAILED`)가 `alarm_text` 에 실리는 형태.
#: 통로 실패 일반이 아니라 아래 부팅 문장과의 **동시 성립**만 환경으로 친다.
_TRANSPORT_TOKEN = "[evaluate-failed]"
#: pywebview 가 창 부팅 실패에 내는 문장. 창이 아예 안 섰다는 유일한 직접 증거다.
_BOOT_FAILURE_TOKEN = "Main window failed to start"

#: 이 필드들이 참이면 창이 떠서 제품 판정 지점까지 갔다는 뜻이다 — 값이 무엇이든(성공이든
#: 차단이든) 그 실행은 제품 증거를 냈고, 환경 분류의 대상이 아니다.
_PRODUCT_EVIDENCE_FLAGS = (
    "external_fetch_completed",
    "external_fetch_succeeded",
    "external_fetch_blocked",
)


def classify(evidence: dict) -> "tuple[bool, str]":
    """``(환경인가, 사유)`` — 순수 함수라 합성 표본으로 음성 대조가 선다."""
    runtime = evidence.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    for flag in _PRODUCT_EVIDENCE_FLAGS:
        if runtime.get(flag) is True:
            return False, f"제품 증거가 있다: runtime.{flag}=true — 창이 떠서 판정 지점까지 갔다"
    if runtime.get("forbidden_resources"):
        return False, "제품 증거가 있다: forbidden_resources 비어 있지 않음"
    error = evidence.get("error")
    if not isinstance(error, str) or not error:
        return False, "error 부재 — 분류할 실패가 없다"
    if _TRANSPORT_TOKEN in error and _BOOT_FAILURE_TOKEN in error:
        return (
            True,
            "콜드 부팅 실패 — 창이 서기 전의 통로 실패라 제품에 대해 아무것도 말하지 않는다",
        )
    return False, "환경 서명 밖의 실패 — 제품 판정으로 남긴다"


def main(argv: "list[str]") -> int:
    # cp949 콘솔에서 판정 사유의 문장 부호가 UnicodeEncodeError 로 죽으면 종료 코드가
    # 인코딩 사고를 판정으로 오보한다 — 출력은 언제나 UTF-8 로, 실패해도 치환으로 산다.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2:
        print("사용법: classify_webview_evidence.py <selftest-evidence.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"증거를 읽지 못해 판정 불능: {path} ({exc})", file=sys.stderr)
        return 2
    if not isinstance(evidence, dict):
        print(f"증거가 객체가 아니라 판정 불능: {path}", file=sys.stderr)
        return 2
    environmental, reason = classify(evidence)
    verdict = "environment-boot-failure" if environmental else "not-environment"
    print(json.dumps({"verdict": verdict, "reason": reason}, ensure_ascii=False))
    return 0 if environmental else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
