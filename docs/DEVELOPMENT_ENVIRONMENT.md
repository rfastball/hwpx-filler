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

# CLI 실행
.\run-filler.ps1 -Cli --help
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
- `tests/test_architecture.py`는 링 경계를 확인한다 — 특히 `hwpxcore`가 제품이나 Qt로
  역의존하지 않는지. 이 계층은 별도 저장소 `hwpx-diff`가 사본을 들고 있어, 제품 색이
  스며들면 두 사본의 대조가 불가능해진다.

pre-commit을 사용할 개발자는 한 번만 다음을 실행한다.

```powershell
uv run pre-commit install
```

## 4. Windows 패키징

### portable EXE

```powershell
.\build.ps1                 # GUI 제품
.\build.ps1 -App filler
```

빌드는 `scripts/generate_build_metadata.py`로 다음 파일을 `build/version/`에 생성한 후
PyInstaller를 실행한다.

- 제품별 Windows version resource
- Inno Setup용 `version.iss`
- 버전, Git 커밋, Python, PyInstaller가 기록된 `build-metadata.json`

산출물은 `dist\hwpx-filler-web\hwpx-filler-web.exe`,
`dist\hwpx-cli\hwpx-cli.exe`(onedir 폴더)이며 canonical
`packaging/build.ps1 -Target all`이 exact frontend build/seal, 두 번들, source/bundled
artifact identity, Node-free GUI selfcheck, 실제 WebView2 loopback/offline selftest와 CLI
selfcheck를 검증한다.
루트 `build.ps1`은 GUI 제품을 canonical 스크립트로 위임하는 호환 러너다.

### 설치파일

로컬 PC에 Inno Setup 6을 설치한 뒤 실행한다.

```powershell
.\package-installer.ps1
.\package-installer.ps1 -App filler
```

기존 EXE를 재사용하려면 `-SkipExe`를 지정한다. 설치본은 사용자 권한으로
`%LOCALAPPDATA%\Programs` 아래에 설치된다. 결과는 `installer-dist/`에 생성된다.

## 5. CI와 공식 릴리스

`.github/workflows/quality.yml`은 PR과 `master`/`main` push에서 **생산자 하나와 소비자 여럿**을
돌린다. 프런트 산출물을 만드는 자리는 한 run 에 하나뿐이고, 나머지는 자원 축(pytest marker)으로
갈려 실패 영역이 곧 원인을 가리킨다.

1. `sealed-web (producer)`: `npm ci` → Vite 빌드 → seal → verify. 산출물(`build/web`)과 그
   정체성(`web-artifact-identity.json` — artifact_id·tree_sha256·source commit)을 업로드한다.
2. `static`: Ruff와 Pyright. 산출물을 읽지 않으므로 생산자를 기다리지 않는다.
3. `pytest-contract (package coverage floor)`: 무표 집합(`-m "not native and not browser and
   not live"`), 커버리지와 패키지별 line/branch floor.
4. `windows-native (real Win32)`: `-m native`. 실 클립보드·실 최상위 창.
5. `browser-render (installed Chrome)`: `-m browser`. 설치 Chrome 기반 CSS·기하·모션 판정.
6. `live-webview2 (real WebView2 session)`: `-m live`. 실앱 selftest 와 Quickstart 101 `check`.
7. `distribution-webview2 (frozen exe)`: portable onedir 2종 빌드와 selfcheck.

산출물 소비자는 3·5·6·7 이다 — 내려받아 `build-web.ps1 -Mode VerifyExisting -ExpectIdentity …`
로 **이 checkout 의 commit·frontend 바이트**와 대조한다. 그 검증은 `actions/setup-node`
**앞에** 서고, 순서가 곧 계약이다: 검증이 Node 없이 통과한다는 것을 단계 순서가 증명한다.

- `windows-native`(4)는 소비자가 아니다 — 실 Win32 자원만 쓰므로 생산자를 기다리지 않는다.
- `pytest-contract`(3)만 검증을 마친 **뒤** 프런트 툴체인을 깐다. 산출물을 만들려는 것이
  아니라 `tests/js/*.test.js` 를 모는 `node --test` 게이트가 vite 의 파서를 실제로 부르기
  때문이다(그 게이트는 부재를 조용히 스킵하지 않는다).

Chrome 렌더링 증거와 실 WebView2 증거는 이름으로도 job 으로도 섞지 않는다.

8. `quality-gate`: 위 일곱을 **명시 열거**해 `success` 만 통과시킨다. 브랜치 보호는 이 하나의
   이름을 겨눈다 — 잡을 늘려도 보호 설정을 따라 고칠 필요가 없고, 대신 열거에서 빠진 job 이
   있으면 `tests/test_quality_workflow.py` 가 멈춘다.

증거는 **실패해도 회수된다**(`if: always()`). `live-webview2` 는 101 보고서·표준출력과 실패한
실주행이 남긴 임시 홈의 진단 파일(`_live101_hang_stacks.txt`·`_live101_result.json`)을,
`distribution-webview2` 는 패키징 증거 6종(산출물 동일성·packaged selftest·외부망 양성/음성
대조·검증 요약)을 올린다. 제품 단언에는 재시도를 걸지 않는다 — 두 번째 초록이 첫 번째 빨강을
지우기 때문이다.

연속 push 는 **앞선 PR run 만** 취소한다(`master` push 와 merge queue 이력은 남긴다). action 은
전부 full commit SHA 로 고정하고 사람이 읽을 버전을 주석으로 단다.

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

### 눌림 기하 테스트가 브라우저 때문에 실패

`tests/test_web_press_geometry.py`(U2 §2.11)는 Playwright 로 **설치된 Chrome** 을
`channel="chrome"` 으로 몰고, `prefers-reduced-motion` 을 두 값(`no-preference`/`reduce`)으로
**명시 강제**해서 눌림 중 기준면 이탈을 잰다. 브라우저 바이너리를 내려받지 않으므로
`playwright install` 은 필요 없고, Chrome 이 없으면 `HWPX_SKIP_MOTION_TESTS=1` 로 명시
옵트아웃한다(자동 감지 스킵은 없다). CI 는 `Press-geometry browser precondition` 단계에서
전제를 먼저 시끄럽게 확인한다.

**강제가 계약인 이유**: 이 층은 `@media (prefers-reduced-motion:reduce)` 에서 통째로 꺼진다.
Windows 「설정 → 접근성 → 시각 효과 → 애니메이션 효과」를 끈 기기에서는 Chromium·WebView2 가
`reduce` 를 보고하므로, 강제 없이 잰 초록은 「안전하다」가 아니라 「이 기기에서 모션이 돌지
않는다」의 증거다. 실앱(WebView2)은 OS 설정을 따르고 테스트는 사용자 OS 설정을 변이하지
않으므로 강제의 매체가 Playwright 다.

### 빌드는 성공했지만 설치파일을 만들지 못함

Inno Setup 6의 `ISCC.exe`가 PATH 또는 기본 설치 경로에 있는지 확인한다. EXE가 아직
없다면 `package-installer.ps1`에서 `-SkipExe`를 제거한다.

### 릴리스 태그가 거부됨

태그가 `v` + `pyproject.toml` 버전과 정확히 같은지 확인한다. 예를 들어 프로젝트 버전이
`0.2.0`이면 허용되는 태그는 `v0.2.0`이다.
