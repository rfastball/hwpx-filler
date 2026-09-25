# 개발·검증·출하

환경은 `uv`가 소유한다. Python·Node·npm과 의존성의 정확한 선언은
[생성 참조](reference/runtime.md)에 있다. 이 문서에 버전 사본을 두지 않는다.
제품은 Windows에서 실행·검증하며 Linux의 정적 검사를 실 WebView2 검증으로 대체하지 않는다.

## 설치와 실행

```powershell
uv python install
uv sync --locked --all-extras --group dev --group build
.\run-filler.ps1
.\run-filler.ps1 -Cli --help
```

Python은 `.python-version`, 의존성은 `pyproject.toml`과 `uv.lock`을 따른다.
시스템 Python이나 별도의 수동 venv를 만들지 않는다. Node는 `.node-version`, npm은
`package.json`의 pin에 맞춰 설치한다. `build-web.ps1`가 frontend 도구의 pin을 검증한다.
의존성을 바꾸면 `uv lock`과 `uv sync` 후 잠금 파일도 커밋한다. CI는 `--locked`로 검사한다.

## 로컬 게이트

```powershell
.\test.ps1
.\test.ps1 tests\test_engine.py -x
uv run python scripts/docs_contract.py --check
uv run ruff check scripts
```

`test.ps1`는 웹 build, Node 테스트, Ruff, Pyright, pytest와 coverage를 실행한다.
pytest 인자는 러너 뒤에 전달한다. scripts 변경은 `ruff check scripts`를 명시 실행한다.
packaging을 고쳤다면 일반 Ruff 범위 밖이므로 `uv run ruff check packaging`도 실행한다.
문서 검사만 통과한 것을 전체 품질 게이트 통과라고 보고하지 않는다.

## CI의 책임

[quality.yml](../.github/workflows/quality.yml)이 실제 job 구성과 순서를 소유한다.
`sealed-web`이 프런트를 한 번 build·seal·verify하고 Node 단위·산출물 계약을 검사한다.
실제 산출물 소비자는 같은 artifact를 받아 `build-web.ps1 -Mode VerifyExisting`으로 검증한다.
이 검증은 `setup-node`보다 먼저 실행되어 빌드 도구 없이 봉인된 산출물을 확인해야 한다.

정적 계약, 순수 Python 행동·coverage, 실 Win32, 브라우저 기하, 실 WebView2, 배포 실행은
별도 책임이다. 정확한 job 목록과 aggregate 의존은 [생성 참조](reference/runtime.md)에 있다.
`quality-gate`는 필요한 job의 **success만** 허용하는 집계다. docs 변경도 repo-contract를
거치므로 검사 경로에서 제외하지 않는다. 저장소 ruleset의 필수 검사에 `quality-gate`를
지정해야 실패한 PR의 병합도 차단된다. YAML만으로 저장소 관리자 설정을 대신할 수는 없다.

coverage 하한은 [package_coverage_floors.toml](package_coverage_floors.toml)의 패키지별
line/branch 값이다. 별도 문서 수치를 유지하지 않는다. 새 서브패키지도 등록·검사한다.
네이티브 경계의 별도 양성 테스트를 coverage 수치로 대체하지 않는다.

## 자원별 테스트

`native`, `browser`, `live` marker는 필요한 자원의 경계이며 등록되지 않은 marker는 실패한다.
런타임 부재를 자동 감지해 조용히 skip하지 않는다. 자원이 없는 로컬 환경에서만
`HWPX_SKIP_NATIVE_TESTS`, `HWPX_SKIP_MOTION_TESTS`, `HWPX_SKIP_GUI_TESTS`를 명시적으로 쓴다.
CI는 이 opt-out 없이 검증한다. 결과 보고에는 무엇을 제외했는지 쓴다.

실앱 단언은 기존 창·fixture를 재사용한다. 새로운 cold boot가 필요하면 비용과 이유를
검토한다. 눌림 기하는 실제 브라우저에서 reduced-motion의 두 경로를 검사한다.
테스트는 앱 홈을 임시 폴더에 격리하며 개발자의 설정·데이터를 읽거나 쓰지 않는다.

## 패키징과 릴리스

```powershell
.\packaging\build.ps1 -Target all
.\packaging\build.ps1 -Target all -IncludeInstaller
.\build.ps1
.\package-installer.ps1
```

canonical 빌더는 `packaging/build.ps1`이며 filler/CLI 빌드와 selfcheck를 수행한다.
루트 `build.ps1`는 GUI 위임 러너다. 설치본 빌드에는 Inno Setup이 필요하다.
릴리스는 `pyproject.toml`의 버전과 일치하는 `vX.Y.Z` 태그 push로만 시작한다.
[release.yml](../.github/workflows/release.yml)이 출하 절차의 실행 정의다.

source·dist·portable 사본은 병합 게이트에서, installed까지 포함한 사본은 릴리스에서
프런트 identity를 대조한다. 판정은
[reconcile_shipped_copies.py](../scripts/reconcile_shipped_copies.py)가 소유하며 호출자가
`--expect`로 사본 집합을 선언한다. `build-metadata.json`에는 프런트 identity와 출하
런타임 근거를 담는다. 성공한 빌드 파일의 존재만으로 동일 산출물 검증을 대신하지 않는다.

실습·튜토리얼의 동봉 여부는 [지원 경계](FEATURE_SCOPE.md)를 따른다.

## 생성물 갱신

디자인 토큰, 브리지 TypeScript 계약, 문안 census는 각각의 원천을 수정한 뒤 생성기를
실행한다. 문서의 코드 참조와 인덱스는 `docs_contract.py --write`로 갱신한다.
이 명령은 사람 문서의 검토 증명을 갱신하지 않는다. 자세한 절차는
[문서 유지 규칙](MAINTENANCE.md)을 따른다.
