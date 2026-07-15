"""웹 프론트엔드(pywebview) — diff GUI 의 Qt 셸(app.py/style.py) 웹 대체.

filler webapp(:mod:`hwpxfiller.webapp`)의 패턴을 그대로 복제한다: 비교 엔진
(:mod:`hwpxdiff.diff`, Qt-free)은 **그대로 임포트**해 구동만 하고, 교체 대상은 뷰 계층뿐.

구성:
- :mod:`~hwpxdiff.webapp.screen_diff` — 화면 컨트롤러(webview 비의존, 헤드리스 테스트 가능).
  엔진을 소유·위임하는 얇은 어댑터. 결과 dataclass 를 snapshot 으로 직렬화(엔진 무변경).
- :mod:`~hwpxdiff.webapp.app` — pywebview 창·브리지·엔트리(``main``). webview 를 여기서만 임포트.

네이티브 표면(파일 다이얼로그)은 :mod:`hwpxcore.native` 공용 계층에서 온다(filler 와 공유).
정적 자산은 저장소 루트 ``web-diff/``. 동결(PyInstaller) 시 ``sys._MEIPASS/web-diff`` 에서 해석.
"""
