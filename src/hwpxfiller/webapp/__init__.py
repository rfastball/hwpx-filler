"""웹 프론트엔드(pywebview) — 링2 대체(Qt 위젯 → 웹) 진입.

스파이크(spike/pywebview-instant-draft, SPIKE_FINDINGS.md)에서 판정 `migrate` 후 승격한
본작업 골격이다. 링0(core)·링1(gui/*_state.py, Qt-free)은 **그대로 임포트**해 구동만 한다 —
교체 대상은 링2(Qt 위젯·style.py)뿐(docs/ARCH_UI_SEPARATION.md, 에픽 #20).

구성:
- :mod:`~hwpxfiller.webapp.screens` — 화면별 컨트롤러(webview 비의존, 헤드리스 테스트 가능).
  링1 VM 을 소유·위임하는 얇은 어댑터. VM 로직 재구현 금지.
- :mod:`~hwpxfiller.webapp.app` — pywebview 창·브리지·엔트리(``main``). webview 를 여기서만 임포트.
- :mod:`~hwpxfiller.webapp.clipboard` — Win32 CF_UNICODETEXT 클립보드(QClipboard 상당, 의존성 0).

정적 자산은 저장소 루트 ``web/`` (index.html·css·js). 개발 시 루트에서, 동결(PyInstaller)
시 ``sys._MEIPASS/web`` 에서 해석한다.
"""
