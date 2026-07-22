# 개발·빌드·배포 환경

> **문서 상태:** 현재 정본
> **권위 범위:** Python·의존성·품질 게이트·패키징·릴리스 절차
> **후속 정본:** 없음
> **편집 정책:** 계속 갱신

이 문서는 HWPX Tools의 로컬 개발환경, 품질 검사, Windows 패키징과 GitHub 릴리스
구성을 기록한다. 환경 설정의 기준 파일은 `pyproject.toml`, `.python-version`,
`uv.lock`이며 Python과 패키지를 개별적으로 수동 설치하지 않는다.

## 1. 기준 환경

| 항목 | 기준 |
|---|---|
| 운영체제 | Windows 11, GitHub Actions `windows-latest` |
| Python | CPython 3.13 계열 (`.python-version`) |
| 환경·의존성 관리 | uv 0.11.28, `uv.lock` |
| GUI | pywebview 6.x + Windows EdgeChromium(WebView2 Runtime) |
| 테스트 | pytest, pytest-cov |
| 정적 검사 | Ruff, Pyright basic |
| portable 패키징 | PyInstaller onedir |
| 설치 패키징 | Inno Setup 6, 제품별 사용자 설치 |
| 공식 배포 | GitHub Release |

`pyproject.toml`의 `project.version`이 유일한 제품 버전 원천이다. PyInstaller 버전
리소스, Inno Setup 버전과 릴리스 메타데이터는 빌드 시 여기서 생성된다.

## 2. 최초 온보딩

### uv 설치

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

설치 직후 현재 셸에서 `uv`가 발견되지 않으면 터미널을 다시 열거나 사용자 PATH에
`%USERPROFILE%\.local\bin`을 추가한다.

### Python과 전체 의존성 설치

저장소 루트에서 실행한다.

```powershell
uv python install 3.13
uv sync --locked --all-extras --group dev --group build
```

이 명령은 프로젝트의 `.venv`를 만들고 다음 환경을 함께 설치한다.

- 런타임: lxml, openpyxl
- GUI: pywebview(Windows EdgeChromium 백엔드)
- 개발: pytest, coverage, Ruff, Pyright, pre-commit
- 빌드: PyInstaller

기존 `.venv`가 삭제된 Python 경로를 참조해 손상된 경우 다음과 같이 재생성한다.

```powershell
uv venv --clear --python 3.13
uv sync --locked --all-extras --group dev --group build
```

## 3. 일상 개발 명령

```powershell
# Ruff → Pyright → pytest → coverage
.\test.ps1

# 특정 테스트 또는 pytest 옵션 전달
.\test.ps1 -q
.\test.ps1 tests\test_engine.py -x

# 소스 GUI 실행
.\run-filler.ps1
.\run-diff.ps1

# CLI 실행
.\run-filler.ps1 -Cli --help
.\run-diff.ps1 -Cli --help
```

PowerShell 실행 정책으로 `.ps1` 실행이 차단된 PC에서는 다음처럼 호출한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test.ps1
```

의존성을 변경했으면 `pyproject.toml` 수정 후 `uv lock`과 `uv sync`를 실행하고
`uv.lock`을 함께 커밋한다. CI는 `uv sync --locked`를 사용하므로 잠금 파일과 선언이
다르면 실패한다.

### 품질 정책

- Ruff는 문법 오류, 미정의 이름과 버그 가능성이 높은 규칙을 CI에서 차단한다.
- Pyright는 basic 모드다. 웹 브리지와 동적 payload 경계의 일부 진단은 점진 도입을
  위해 완화되어 있다.
- 전체 포맷 마이그레이션은 기존 UI 작업과 충돌하지 않도록 별도 작업으로 분리한다.
- coverage는 XML과 터미널 보고서를 만들고 `docs/package_coverage_floors.toml`의
  패키지별 line/branch 하한을 차단 조건으로 적용한다. 각 경로의 직접 소속 Python 파일만
  집계하므로 하위 runtime 패키지의 낮은 수치가 상위 평균에 숨지 않는다.
- `hwpxcore.native`는 낮은 coverage 하한을 두지 않고 `tests/test_native_positive.py`의
  Windows 양성 시나리오를 별도 CI 단계로 필수 실행한다. JS/CSS, 별도 WebView2 프로세스,
  frozen 번들, installer/signing은 Python coverage 수치에 포함하지 않는다.
- `tests/test_architecture.py`는 두 제품이 서로 직접 import하지 않는지 확인한다.

pre-commit을 사용할 개발자는 한 번만 다음을 실행한다.

```powershell
uv run pre-commit install
```

## 4. Windows 패키징

### portable EXE

```powershell
.\build.ps1                 # 두 제품
.\build.ps1 -App filler
.\build.ps1 -App diff
```

빌드는 `scripts/generate_build_metadata.py`로 다음 파일을 `build/version/`에 생성한 후
PyInstaller를 실행한다.

- 제품별 Windows version resource
- Inno Setup용 `version.iss`
- 버전, Git 커밋, Python, PyInstaller가 기록된 `build-metadata.json`

산출물은 `dist\hwpx-filler-web\hwpx-filler-web.exe`,
`dist\hwpx-diff\hwpx-diff.exe`, `dist\hwpx-cli\hwpx-cli.exe`(onedir 폴더)이며
canonical `packaging/build.ps1 -Target all`이 세 번들과 각각의 selfcheck를 검증한다.
루트 `build.ps1`은 GUI 두 제품을 canonical 스크립트로 위임하는 호환 러너다.

### 제품별 설치파일

로컬 PC에 Inno Setup 6을 설치한 뒤 실행한다.

```powershell
.\package-installer.ps1
.\package-installer.ps1 -App filler
.\package-installer.ps1 -App diff
```

기존 EXE를 재사용하려면 `-SkipExe`를 지정한다. 설치본은 사용자 권한으로
`%LOCALAPPDATA%\Programs` 아래에 설치되며 두 제품은 서로 다른 AppId를 사용하므로
독립적으로 설치, 업그레이드, 제거된다. 결과는 `installer-dist/`에 생성된다.

## 5. CI와 공식 릴리스

`.github/workflows/quality.yml`은 PR과 `master`/`main` push에서 서로 의존하지 않는 세 작업을
병렬 실행한다. 브랜치 보호의 필수 상태도 이 세 이름으로 설정한다.

1. `static`: Ruff와 Pyright
2. `pytest + package coverage floor`: Windows native 양성 시나리오, 전체 pytest, 패키지별
   line/branch floor와 누락 위치 보고
3. `distribution (filler + diff + CLI)`: 세 portable onedir 빌드와 selfcheck

Inno Setup installer 생성·설치/제거 스모크·Authenticode 서명은 느리고 비밀값을 사용하는
release-only 정책이다. PR quality workflow에서는 실행하지 않는다.

공식 릴리스는 먼저 `pyproject.toml`의 버전을 변경하고 같은 버전의 태그를 push한다.

```powershell
git tag v0.2.0
git push origin v0.2.0
```

`.github/workflows/release.yml`은 태그와 프로젝트 버전이 다르면 중단한다. 일치하면 전체
검사, 두 GUI portable EXE 빌드, self-check, 제품별 설치본 빌드, 설치·제거 스모크,
SHA-256 생성을 거쳐 GitHub Release에 게시한다.

### 선택형 Windows 코드 서명

저장소에 다음 GitHub Actions secrets를 모두 설정하면 portable EXE와 설치본을
Authenticode 서명한다.

- `WINDOWS_CERTIFICATE_BASE64`: PFX 파일의 Base64 문자열
- `WINDOWS_CERTIFICATE_PASSWORD`: PFX 암호

PFX를 Base64로 변환하는 예시는 다음과 같다. 결과를 파일이나 저장소에 커밋하지 않는다.

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('codesign.pfx'))
```

두 secret이 모두 없으면 무서명 릴리스를 허용하고 릴리스 설명에 이를 표시한다. 하나만
설정된 경우 구성 오류로 릴리스를 실패시킨다.

## 6. 파일 및 비밀값 관리

다음 항목은 Git에 커밋하지 않는다.

- `.venv/`, uv 로컬 캐시와 관리 Python
- `.secrets/`, `.env*`, PFX 인증서와 API 키
- `build/`, `dist/`, `installer-dist/`
- coverage와 pytest 보고서
- `.claude/settings.local.json` 등 개인 로컬 설정

나라장터 연동 테스트는 실제 API나 서비스 키 대신 `tests/fixtures`의 응답을 사용한다.
로컬 비밀값을 테스트 및 CI의 필수 입력으로 만들지 않는다.

## 7. 문제 해결

### `uv` 명령을 찾지 못함

터미널을 다시 시작하고 `%USERPROFILE%\.local\bin\uv.exe` 존재 여부와 사용자 PATH를
확인한다.

### 존재하지 않는 Python을 가리키는 `.venv`

`uv venv --clear --python 3.13` 후 잠금 환경을 다시 동기화한다.

### WebView2 실창 테스트가 화면 환경 때문에 실패

Windows 데스크톱 세션과 WebView2 Runtime 설치 여부를 확인한다. 일반 Python 코드와 달리
별도 WebView2 프로세스의 실행 내용은 coverage 수치에 잡히지 않지만, `test.ps1`과 Windows
quality CI의 전체 pytest는 subprocess 실창 게이트를 실행한다. 화면 없는 환경에서
의도적으로 건너뛸 때만 해당 테스트가 문서화한 `HWPX_SKIP_GUI_TESTS=1`을 명시한다.

### 빌드는 성공했지만 설치파일을 만들지 못함

Inno Setup 6의 `ISCC.exe`가 PATH 또는 기본 설치 경로에 있는지 확인한다. EXE가 아직
없다면 `package-installer.ps1`에서 `-SkipExe`를 제거한다.

### 릴리스 태그가 거부됨

태그가 `v` + `pyproject.toml` 버전과 정확히 같은지 확인한다. 예를 들어 프로젝트 버전이
`0.2.0`이면 허용되는 태그는 `v0.2.0`이다.
