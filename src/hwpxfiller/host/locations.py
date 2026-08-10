"""GUI 기본 위치 해석기 — 사용자 홈 아래 durable 자산 루트의 Host 조립(P2-17, #565).

레지스트리 *클래스* 들은 위치-불가지다(생성자가 디렉터리를 받는다) — "어느 디렉터리인가"라는
기본값 해석은 실행 환경(``HWPXFILLER_HOME``)을 읽는 Host 책임이라 Domain 모듈이 아니라
여기 산다(:mod:`hwpxfiller.host.boot_budget` 선례). 홈 해석 자체는
:func:`hwpxfiller.core.paths.home_dir` 단일 출처(#76)를 그대로 위임한다.

템플릿 기본 루트(:func:`default_templates_dir`)와 Job 직렬화의 「이식성의 경첩」
(:func:`library_root_for`)은 P2-21(#569)에서 core 영속 경계와 함께 여기로 승계됐다.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.job import template_media
from hwpxfiller.core.paths import home_dir
from hwpxfiller.core.text_registry import default_text_templates_dir


def default_jobs_dir() -> Path:
    """GUI 기본 작업 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/jobs``).

    작업은 작업 디렉터리·repo 체크아웃을 가로질러 살아남아야 하는 개인 durable 자산이라
    프로젝트-로컬이 아니라 홈에 둔다(패키징된 exe 엔 쓰기 가능한 프로젝트 폴더도 없다).
    ``HWPXFILLER_HOME`` 환경변수로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.core.paths.home_dir`).
    """
    return home_dir() / "jobs"


def default_templates_dir() -> Path:
    """GUI 기본 템플릿 라이브러리 위치 — 사용자 홈(``~/.hwpxfiller/templates``).

    작업·베이스·txt·데이터셋 기본 루트 4종(:func:`~hwpxfiller.host.locations.default_jobs_dir`
    미러)과 동일 홈 관례 — 템플릿 라이브러리만 기본 루트가 없어 관리 워크숍이 백지로
    떴다(RC-14). ``HWPXFILLER_HOME`` 로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.core.paths.home_dir`). 관리 뷰모델 *클래스* 자체는 위치-불가지
    (생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    return home_dir() / "templates"


def library_root_for(template_path: str) -> "Path | None":
    """매체별 라이브러리 루트(hwpx=``templates``/txt=``text_templates``) — 확장자에서만 고른다.

    I/O 없음. 미상 확장자·빈 경로는 ``None``(승격도 해석도 하지 않는다 — 모르는 것을 추측하지
    않는다는 :func:`~hwpxfiller.core.job.work_mode` 와 같은 fail-closed). 두 루트 모두
    ``HWPXFILLER_HOME`` 을 존중하는 기본 해석기라 **홈을 옮기면 같은 키가 새 홈의 파일로
    해석된다** — 이 함수가 이식성의 경첩이다.
    """
    media = template_media(template_path)
    if media == "hwpx":
        return default_templates_dir()
    if media == "txt":
        return default_text_templates_dir()
    return None
