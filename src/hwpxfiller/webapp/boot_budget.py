"""부팅 폴백 예산 판정 — 첫 실행(WebView2 콜드 부트스트랩)에만 예산을 넓힌다(#77).

FOUC 은닉 부팅은 창을 숨긴 채 띄우고 ``loaded`` 에서 테마를 주입한 뒤 show 한다. ``loaded``
가 끝내 안 오면 창이 영영 숨겨지므로 폴백 타이머가 강제 show + 경보한다. 그런데 Evergreen
WebView2 런타임을 **처음 부트스트랩**하는 머신(설치 직후·AV 동반)에선 콜드스타트가 30~60s
까지 걸릴 수 있어, 고정 20s 예산은 정상 부팅에서 선발화한다 → 테마 미주입 창(라이트 FOUC)
+ 거짓 경보. 설치 후 첫 실행이 정확히 예산이 빠듯한 때다.

**왜 '진행 중이면 연장'이 아닌가.** 후보였던 관찰 기반 안(프로필 폴더 쓰기를 진행 증거로
보고 연장)은 통제 실험에서 폐기됐다: 응답하지 않는 서버로 ``loaded`` 미발화를 재현했을 때
프로필 쓰기가 정상 부팅과 **구분되지 않았다**(파일 수·바이트·재쓰기 주기 동일 — 페이지가
매달려도 런타임 자체는 정상 동작하므로). 부재 판별력이 없는 증거를 쓰면 모든 매달림을
'진행 중'으로 오판해 예산이 무조건 넓어진다.

그래서 감지는 **선언적**이다: 이 홈에서 이 런타임 버전으로 부팅을 완주한 적이 있는가.
완주 기록은 ``loaded`` 가 실제로 발화한 뒤에만 남으므로(:func:`~hwpxfiller.webapp.settings.
save_boot_completed`), 한 번도 끝까지 못 간 머신은 넓은 예산을 유지한다.
"""

from __future__ import annotations

import sys

#: 완주 이력이 있는 부팅의 폴백 상한 — 매달림을 빨리 잡는다(기존 값 유지).
WARM_BUDGET_SECONDS = 20.0

#: 첫 부트스트랩(또는 런타임 교체) 의심 시의 상한. 관측된 콜드스타트 상단(30~60s)을 덮는다 —
#: 진짜 매달림의 대기도 함께 길어지는 대가는 '설치 후 첫 실행 1회'로 국한된다.
COLD_BUDGET_SECONDS = 60.0

# Evergreen WebView2 런타임의 EdgeUpdate 클라이언트 GUID(고정) — ``pv`` 값이 설치 버전.
_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# per-machine(x86 노드·네이티브)·per-user 설치를 모두 훑는다 — 한 자리만 보면 설치 형태에
# 따라 조용히 '미검출'이 되고, 미검출은 아래 판정에서 다른 갈래를 탄다.
_RUNTIME_KEYS = (
    ("HKLM", "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + _RUNTIME_GUID),
    ("HKLM", "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + _RUNTIME_GUID),
    ("HKCU", "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + _RUNTIME_GUID),
    ("HKCU", "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + _RUNTIME_GUID),
)


def detect_runtime_version() -> str:
    """설치된 WebView2 런타임 버전, 못 읽으면 ``""`` — **절대 던지지 않는다**.

    부팅 예산 판정용 힌트라 실패가 부팅을 막으면 안 된다. 미검출(``""``)은 '런타임 없음'이
    아니라 '알 수 없음'이며, 그 구분은 :func:`decide` 가 진다.
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:  # pragma: no cover — win32 인데 winreg 부재는 사실상 없다
        return ""
    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for root_name, sub in _RUNTIME_KEYS:
        try:
            with winreg.OpenKey(roots[root_name], sub) as key:
                value = winreg.QueryValueEx(key, "pv")[0]
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def decide(seen: str, current: str) -> "tuple[float, str]":
    """폴백 예산 ``(초, 사유)`` — 사유는 경보 문안이 어느 예산이었는지 말하기 위한 것.

    - 완주 이력 없음 → 콜드. 첫 실행이 가장 느린 순간이다.
    - 이력의 버전과 지금 버전이 다름 → 런타임이 교체됐다. 업데이트 직후 첫 실행도 콜드에
      준한다(새 런타임을 다시 펼친다).
    - 버전 미검출인데 완주 이력은 있음 → **웜으로 본다**. 미검출을 콜드로 접으면 버전을 못
      읽는 머신은 영구히 넓은 예산이 되어 매달림 대기가 상시 3배가 된다. 대가는 정직하게
      적어 둔다: 그런 머신에선 런타임 교체를 감지하지 못한다(이력 자체는 참이므로 한 번은
      완주했던 환경이다).
    """
    if not seen:
        return COLD_BUDGET_SECONDS, "첫 실행"
    if current and current != seen:
        return COLD_BUDGET_SECONDS, f"런타임 교체({seen} → {current})"
    return WARM_BUDGET_SECONDS, "정상 부팅 이력 있음"
