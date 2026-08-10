"""GUI 기본 위치 해석기 — 사용자 홈 아래 durable 자산 루트의 Host 조립(P2-17, #565).

레지스트리 *클래스* 들은 위치-불가지다(생성자가 디렉터리를 받는다) — "어느 디렉터리인가"라는
기본값 해석은 실행 환경(``HWPXFILLER_HOME``)을 읽는 Host 책임이라 Domain 모듈이 아니라
여기 산다(:mod:`hwpxfiller.host.boot_budget` 선례). 홈 해석 자체는
:func:`hwpxfiller.core.paths.home_dir` 단일 출처(#76)를 그대로 위임한다.

나머지 기본 루트(templates·text_templates·datasets)의 이관은 Job 직렬화의 「이식성의 경첩」
(:func:`hwpxfiller.core.job.library_root_for`)이 core 영속 경계와 함께 떠나는 #569 가 소유한다.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.paths import home_dir


def default_jobs_dir() -> Path:
    """GUI 기본 작업 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/jobs``).

    작업은 작업 디렉터리·repo 체크아웃을 가로질러 살아남아야 하는 개인 durable 자산이라
    프로젝트-로컬이 아니라 홈에 둔다(패키징된 exe 엔 쓰기 가능한 프로젝트 폴더도 없다).
    ``HWPXFILLER_HOME`` 환경변수로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.core.paths.home_dir`).
    """
    return home_dir() / "jobs"
