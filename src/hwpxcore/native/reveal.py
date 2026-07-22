"""OS 파일 로케이트 — 탐색기에서 표시 / 기본 앱으로 열기(외부 의존 0).

추적성 UI(#53-B)의 '폴더에서 보기'·'열기' 동선이 여기 산다. ``explorer /select`` 는
:mod:`hwpxfiller.webapp.app` 의 ``reveal_corrupt_job`` 이 인라인으로 쓰던 패턴을 이 공용
계층으로 승격한 것(두 제품이 공유, 복제 금지 — :mod:`hwpxcore.native` 규약).

경로 화이트리스트 검증은 **호출측(브리지)** 책임이다 — 여기선 OS 글루만 담당하고 임의
경로 방어는 하지 않는다(제품 로직 없음). 비-Windows 는 조용히 무시하지 않고 시끄럽게
실패한다(confirm-or-alarm).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _launch_explorer(path: Path) -> None:
    subprocess.Popen(["explorer", "/select,", str(path)])


def _start_file(path: Path) -> None:
    import os

    os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606 — Windows 전용 기본앱 열기


def _launch_error(action: str, path: Path, exc: OSError) -> OSError:
    detail = f"{action}할 수 없습니다: {path}"
    if exc.strerror:
        detail += f" ({exc.strerror})"
    return OSError(exc.errno, detail, str(path))


def reveal_in_explorer(path: "str | Path") -> bool:
    """탐색기에서 ``path`` 를 **선택한 채** 폴더를 연다(파일·폴더 모두). Windows 전용.

    파일이면 그 파일이 선택된 상태로 부모 폴더가, 폴더면 그 폴더가 상위에서 선택된 채
    열린다. 존재하지 않는 경로는 시끄럽게 실패한다(죽은 참조를 조용히 무시하지 않음).
    OS 호출을 시작했으면 ``True``를 반환하고, 시작 오류에는 대상·동작 문맥을 붙인다.
    """
    if sys.platform != "win32":  # confirm-or-alarm: 조용히 무시하지 않는다.
        raise OSError("탐색기에서 보기는 Windows 에서만 지원됩니다.")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"경로를 찾을 수 없습니다: {path}")
    # explorer /select,<path> = 파일/폴더를 선택한 채 부모 폴더 열기. explorer 는 종료
    # 코드가 0이 아닐 수 있어(정상이어도) check 하지 않는다 — Popen fire-and-forget.
    try:
        _launch_explorer(p)
    except OSError as exc:
        raise _launch_error("탐색기에서 표시", p, exc) from exc
    return True


def open_path(path: "str | Path") -> bool:
    """``path`` 를 OS 기본 연결 앱으로 연다(HWPX→한글, xlsx→엑셀 등). Windows 전용.

    존재하지 않는 경로는 시끄럽게 실패한다. 연결 앱이 없으면 OS 오류에 대상·동작 문맥을
    붙여 전파한다(조용한 무반응 금지). OS 호출을 시작했으면 ``True``.
    """
    if sys.platform != "win32":  # confirm-or-alarm: 조용히 무시하지 않는다.
        raise OSError("파일 열기는 Windows 에서만 지원됩니다.")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"경로를 찾을 수 없습니다: {path}")
    try:
        _start_file(p)
    except OSError as exc:
        raise _launch_error("기본 앱으로 열기", p, exc) from exc
    return True
