"""Quickstart 101 라이브 실행 하니스 — driver · surface · scenario · capture · report.

종전에는 이 다섯이 ``scripts/capture_101_screenshots.py`` 한 파일(764줄)에 겹쳐 있었다.
그 겹침은 편의가 아니라 비용이었다: 대본 한 줄을 고치려면 종료 정책과 Win32 캡처를 함께
읽어야 했고, 호출 계약이 조용히 깨진 채 몇 달을 살 수 있었다(#423).

경계는 이렇다.

- :mod:`.driver` — 앱 시작·준비·전체 시한·증거·종료·실습 홈 수명주기. **두 모드**의 주인.
- :mod:`.surface` — 실 DOM 위의 대기·클릭. 부재와 미성립을 가르는 자리.
- :mod:`.scenario` — 사용자 행동 순서와 결과 판정. 캡처는 **이름으로만** 지목한다.
- :mod:`.capture` — HWND·``PrintWindow``·PNG·정착 정책.
- :mod:`.report` — 사실 봉투와 순수 판정(앱 없이 음성 대조가 선다).

``scripts/capture_101_screenshots.py`` 는 이 조각을 조립하는 얇은 CLI 다.
"""
