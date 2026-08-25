"""GUI 기본 위치 해석기 — 사용자 홈 아래 durable 자산 루트의 Host 조립(P2-17, #565).

레지스트리 *클래스* 들은 위치-불가지다(생성자가 디렉터리를 받는다) — "어느 디렉터리인가"라는
기본값 해석은 실행 환경(``HWPXFILLER_HOME``)을 읽는 Host 책임이라 Domain 모듈이 아니라
여기 산다(:mod:`hwpxfiller.host.boot_budget` 선례). 홈 해석도 이 모듈이 단일 출처로 소유한다.

템플릿 기본 루트(:func:`default_templates_dir`)와 Job 직렬화의 「이식성의 경첩」
(:func:`library_root_for`)은 P2-21(#569)에서 core 영속 경계와 함께 여기로 승계됐다.
"""

from __future__ import annotations

import os
from pathlib import Path

from hwpxfiller.domain.job import template_media

#: 홈 재지정 환경변수 이름 — 테스트 격리·CI·다중 프로필.
HOME_ENV_VAR = "HWPXFILLER_HOME"

#: 재지정이 없을 때의 기본 홈 폴더 이름.
DEFAULT_HOME_NAME = ".hwpxfiller"


def home_dir() -> Path:
    """앱 홈 — ``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``."""
    root = os.environ.get(HOME_ENV_VAR) or (Path.home() / DEFAULT_HOME_NAME)
    return Path(root)


def default_jobs_dir() -> Path:
    """GUI 기본 작업 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/jobs``).

    작업은 작업 디렉터리·repo 체크아웃을 가로질러 살아남아야 하는 개인 durable 자산이라
    프로젝트-로컬이 아니라 홈에 둔다(패키징된 exe 엔 쓰기 가능한 프로젝트 폴더도 없다).
    ``HWPXFILLER_HOME`` 환경변수로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.host.locations.home_dir`).
    """
    return home_dir() / "jobs"


def default_templates_dir() -> Path:
    """GUI 기본 템플릿 라이브러리 위치 — 사용자 홈(``~/.hwpxfiller/templates``).

    작업·베이스·txt·데이터셋 기본 루트 4종(:func:`~hwpxfiller.host.locations.default_jobs_dir`
    미러)과 동일 홈 관례 — 템플릿 라이브러리만 기본 루트가 없어 관리 워크숍이 백지로
    떴다(RC-14). ``HWPXFILLER_HOME`` 로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.host.locations.home_dir`). 관리 뷰모델 *클래스* 자체는 위치-불가지
    (생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    return home_dir() / "templates"


def default_dataset_pool_dir() -> Path:
    """GUI 기본 데이터셋 풀 레지스트리 위치 — 사용자 홈(``~/.hwpxfiller/datasets``).

    작업·txt 템플릿과 동일 홈 관례(:func:`default_jobs_dir` 미러).
    ``HWPXFILLER_HOME`` 로 재지정 가능(해석은 :func:`~hwpxfiller.host.locations.home_dir`).
    레지스트리 *클래스* 는 위치-불가지(생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값
    해석기일 뿐이다(P2-22 #570 에서 dataset persistence 경계로부터 이동, P2-17 동형).
    """
    return home_dir() / "datasets"


def default_preset_dir() -> Path:
    """Selection Preset 레지스트리 기본 위치 — 사용자 홈(``~/.hwpxfiller/presets``).

    작업·데이터셋·txt 템플릿과 동일 홈 관례(:func:`default_dataset_pool_dir` 미러).
    ``HWPXFILLER_HOME`` 로 재지정 가능(해석은 :func:`home_dir`). 레지스트리 *클래스*
    (:class:`~hwpxfiller.external.preset_store.PresetRegistry`)는 위치-불가지(생성자가
    디렉터리를 받는다) — 이 함수는 기본값 해석기일 뿐이다(S9-01 #827).
    """
    return home_dir() / "presets"


def default_template_authority_dir() -> Path:
    """S3 template 권위 영속 루트 — 사용자 홈(``~/.hwpxfiller/template_authority``).

    Work aggregate·Candidate object·Qualification object 스토어(S3-09 #659)가 이 아래
    ``works``/``candidates``/``qualification`` 을 각자 받는다. 다른 durable 자산과 동일 홈
    관례이고 ``HWPXFILLER_HOME`` 을 존중한다(해석은 :func:`home_dir`).
    """
    return home_dir() / "template_authority"


def default_text_templates_dir() -> Path:
    """txt 기안 템플릿 기본 루트 — 사용자 홈 아래 ``text_templates``."""
    return home_dir() / "text_templates"


def default_example_data_dir() -> Path:
    """동봉 예제 데이터(CSV)의 착지 자리 — 사용자 홈 아래 ``example_data``.

    템플릿은 매체별 라이브러리 루트로 가지만(:func:`library_root_for`) 데이터는 **경로 참조**
    로만 고정되므로(``external/dataset_store``: 풀은 파일을 품지 않고 다시 여는 법만 안다)
    실물이 앉을 durable 자리가 따로 필요하다. 다른 홈 자산과 같은 관례이고
    ``HWPXFILLER_HOME`` 을 존중한다(해석은 :func:`home_dir`). **설치 전에는 만들지 않는다**
    — 폴더 생성은 예제 설치(:func:`hwpxfiller.external.example_pack.install`)의 몫이고,
    누르기 전에 홈을 건드리지 않는 것이 온보딩 D1 의 계약이다(#891).
    """
    return home_dir() / "example_data"


def library_root_for(template_path: str) -> "Path | None":
    """매체별 라이브러리 루트(hwpx=``templates``/txt=``text_templates``) — 확장자에서만 고른다.

    I/O 없음. 미상 확장자·빈 경로는 ``None``(승격도 해석도 하지 않는다 — 모르는 것을 추측하지
    않는다는 :func:`~hwpxfiller.domain.job.work_mode` 와 같은 fail-closed). 두 루트 모두
    ``HWPXFILLER_HOME`` 을 존중하는 기본 해석기라 **홈을 옮기면 같은 키가 새 홈의 파일로
    해석된다** — 이 함수가 이식성의 경첩이다.
    """
    media = template_media(template_path)
    if media == "hwpx":
        return default_templates_dir()
    if media == "txt":
        return default_text_templates_dir()
    return None
