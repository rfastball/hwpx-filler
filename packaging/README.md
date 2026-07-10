# 패키징 — hwpx-diff.exe (앱 A, 단독 배포)

diff 리뷰어를 **의존성 0의 단일 exe**로 패키징한다. 받는 사람은 파이썬도 한컴도
필요 없다 — `hwpx-diff.exe` 하나 복사해서 더블클릭(또는 .hwpx 두 개 드래그&드롭).

## 빌드

```powershell
.venv\Scripts\pip install pyinstaller        # 최초 1회 (또는: pip install -e .[package])
.venv\Scripts\pyinstaller packaging\hwpx_diff.spec --noconfirm
```

산출: `dist\hwpx-diff.exe` (onefile·창 모드, ~50 MB — PySide6 포함 비용).
아이콘(`hwpx-diff.ico`)은 부재 시 spec 이 `make_icon.py` 로 자동 생성한다(커밋 안 함).

## 빌드 검증(패키징 스모크)

```powershell
dist\hwpx-diff.exe --selfcheck tests\corpus\real\spec_revision_2025.hwpx tests\corpus\real\spec_revision_2026.hwpx
# exit 0 + "selfcheck: change_items=N ... OK" 면 통과
```

`--selfcheck` 는 엔트리 래퍼(`hwpx_diff_entry.py`)에만 있는 패키징 검증 플래그다 —
앱 코드는 무변경이고, 패키징된 환경에서 zip 읽기→lxml 파싱→HTML 렌더 전 경로를 돌린다.

## 구성 파일

| 파일 | 역할 |
|---|---|
| `hwpx_diff.spec` | PyInstaller 스펙 — 진입점·excludes(앱 B 의존 차단)·아이콘·버전 리소스 |
| `hwpx_diff_entry.py` | exe 진입점 — 기본 GUI, `--selfcheck` 헤드리스 검증 |
| `hwpx_diff_version.txt` | exe 속성(제품명 "HWPX Diff"·버전) — pyproject 버전과 수동 동기 |
| `make_icon.py` | 아이콘 생성기(QPainter, 커밋 대상 아님) |

## 경계(계약)

- diff exe 의 실의존 = `hwpxdiff` + `hwpxcore` + PySide6(QtCore/Gui/Widgets) + lxml.
  **`hwpxfiller`(주입 제품) 통째와 openpyxl 은 excludes 로 못박았다** — 후일 누가
  경계를 넘는 임포트를 추가해도 diff exe 가 조용히 비대해지지 않는다.
- 앱 B(`hwpx-filler` 주입)의 패키징은 별도 spec 으로(이 spec 재사용 금지 —
  excludes 가 정반대다).
