"""계약목록의 Windows 등록과 업무 홈 포인터를 읽는다. 외부 자료는 쓰지 않는다."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def registered_workfile() -> tuple[str, str] | None:
    """등록된 업무 앱의 config만 읽는다. 사용자 지정 문서나르미 홈도 지원한다."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\Pclm.Workfile\shell\open\command")
    except FileNotFoundError:
        return None
    with key:
        command, _kind = winreg.QueryValueEx(key, "")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("계약 목록의 작업자료 설정을 확인하세요: Pclm.Workfile")
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise ValueError("계약 목록의 작업자료 설정을 확인하세요: LOCALAPPDATA")
    return read_workfile_config(Path(local) / "Pclm" / "config.json")


def read_workfile_config(path: Path) -> tuple[str, str]:
    """Pclm.Core.Storage.HomeConfig v1의 절대 경로와 자료 신원을 그대로 읽는다."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("workfile"), str)
            or not Path(data["workfile"]).is_absolute()
            or not isinstance(data.get("datasetId"), str) or not data["datasetId"]):
        raise ValueError(f"계약 목록의 작업자료 설정을 확인하세요: {path}")
    return data["workfile"], data["datasetId"]
