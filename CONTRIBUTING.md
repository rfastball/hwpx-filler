# 기여와 검증

<a id="development"></a>
## 환경·검증·출하

환경은 `uv`가 소유한다. 정확한 Python·Node·npm 선언은 [생성 참조](docs/reference/runtime.md)에
있다. 제품은 Windows에서 실행·검증하며 Linux 정적 검사를 실 WebView2 검증으로 대신하지 않는다.

```powershell
uv python install
uv sync --locked --all-extras --group dev --group build
.\run-filler.ps1
.\run-filler.ps1 -Cli --help
.\test.ps1
.\test.ps1 tests\test_engine.py -x
uv run ruff check scripts
```

Python은 `.python-version`, 의존성은 `pyproject.toml`·`uv.lock`을 따른다. 시스템 Python이나
별도의 수동 venv를 만들지 않는다. Node는 `.node-version`, npm은 `package.json`의 pin에 맞춘다.
`build-web.ps1`가 frontend 도구 pin을 검사한다. 의존성을 변경하면 `uv lock`·`uv sync`와 잠금
파일을 함께 커밋한다. CI는 `--locked`로 검사한다.

`test.ps1`는 web build → Node 테스트 → Ruff → Pyright → pytest·coverage를 실행하며 인자는
pytest에 전달한다. scripts 변경은 `ruff check scripts`, packaging 변경은 일반 Ruff 범위 밖이므로
`uv run ruff check packaging`도 명시 실행한다. 문서 검사 성공을 전체 품질 성공으로 보고하지 않는다.

[quality.yml](.github/workflows/quality.yml)이 job 구성·순서를 소유한다. `sealed-web`이 한번
build·seal·verify하고 Node 단위·산출물 계약을 검사한다. 소비자는 같은 artifact를 받아
`VerifyExisting`을 **setup-node보다 먼저** 실행해 빌드 도구 없이 검증해야 한다.
정적 계약·순수 Python와 coverage·Win32·브라우저·WebView2·배포의 책임은 분리한다.
job 목록·집계 의존은 생성 참조에만 둔다. `quality-gate`는 필요한 job의 success만 허용하며
문서 변경도 repo-contract에서 제외하지 않는다. 기본 브랜치 ruleset도 이를 필수 검사로 요구한다.

coverage 하한은 [원장](tests/contracts/package-coverage-floors.toml)의 패키지별 line·branch 값이다.
새 서브패키지도 등록한다. 네이티브 양성 테스트를 coverage 수치로 대체하지 않는다.
`native`·`browser`·`live`는 자원 경계 marker이며 미등록 marker는 실패한다.
자원 부재를 조용한 skip으로 만들지 않는다. 자원이 없는 로컬에서만 `HWPX_SKIP_NATIVE_TESTS`·
`HWPX_SKIP_MOTION_TESTS`·`HWPX_SKIP_GUI_TESTS`를 명시하고 결과에 제외 범위를 적는다.
CI는 이 opt-out 없이 검사한다. 기존 창·fixture를 재사용하고 새 cold boot의 이유·비용을 검토한다.
테스트의 autouse 앱 홈 격리를 우회하지 않는다.

```powershell
.\packaging\build.ps1 -Target all
.\packaging\build.ps1 -Target all -IncludeInstaller
.\build.ps1
.\package-installer.ps1
```

canonical 빌더는 `packaging/build.ps1`이며 filler·CLI와 selfcheck를 담당한다. 루트 빌더는 GUI
위임 러너다. 설치본에는 Inno Setup이 필요하다. 릴리스는 프로젝트 버전과 일치하는 `vX.Y.Z`
태그 push로만 시작한다. [release.yml](.github/workflows/release.yml)이 실행 정의다.
source·dist·portable은 병합 게이트에서, installed를 포함한 네 사본은 릴리스에서 frontend
identity를 대조한다. [reconcile_shipped_copies.py](scripts/reconcile_shipped_copies.py)가 판정하고
호출자는 `--expect`로 집합을 선언한다. `build-metadata.json`은 frontend identity와 출하
런타임 근거를 담는다. 파일 존재를 동일 산출물 검증으로 대신하지 않는다.
동봉 자산의 범위는 [제품](docs/product.md#product-scope)을 따른다.

GUI와 CLI는 독립 onedir 번들이며 exe 하나가 아닌 폴더 전체를 배포한다. 출력은
`dist/hwpx-filler-web/hwpx-filler-web.exe`·`dist/hwpx-cli/hwpx-cli.exe`다. GUI 아이콘은
`packaging/hwpx-filler.ico`를 쓴다. 빌더는 격리 wheel import·entrypoint·cp949 CLI 도움말,
퇴역 모듈 부재·필수 모듈 포함, Node 없는 PATH의 seal selfcheck, 실제 WebView2·same-origin·
외부망 차단을 검사한다. CLI의 schema·fieldize·lint·drift도 실행한다. lint의 발견 exit 1은
정상 결과다. 함수 내 import는 CLI spec에 명시한다. GUI 런타임은 CLI에서 제외하고 Qt·Node·
node_modules·frontend 소스는 번들하지 않는다. 설치·제거·서명은 release workflow의 책임이며
PR distribution 게이트에 포함됐다고 설명하지 않는다.

<a id="changes"></a>
## 변경과 리뷰

제품 계약은 [목적](docs/product.md), [아키텍처](docs/architecture.md),
[작업 흐름](docs/workflow.md), [화면 규칙](docs/ui-style.md)이 각각 소유한다.
실패·불확실성·손실을 숨기거나 의미 판정을 여러 계층에서 다시 조립하지 않는다.

링1 공개 API는 소비 컨트롤러와 행동 테스트를 함께 변경한다. 화면 추가·삭제·개명은 컨트롤러·
registry·프런트 라우팅·DOM 루트·blocker 복구·selftest·live101·실렌더를 한 변경으로 다룬다.
직접 호출은 메서드 입력 검증과 생성 브리지·독립 오라클을 함께 대조한다.
동결 모델·자산은 실제 소비자를 확인하지 않고 삭제하거나 표면에 재연결하지 않는다.

리뷰는 계획 일치뿐 아니라 기존 busy/disabled 열거, 트리거↔액션 양방향 존재, 공유 팩토리·
상수·헬퍼의 중복 구현, docstring에 명시한 seam·접근 경계 우회를 확인한다.
사용자 새 문장은 기본 0이며 필요한 전문과 사유를 변경 범위에 먼저 열거한다.
열거 밖 문장과 화면이 이미 보이는 결과의 낭독은 넣지 않는다.

커밋은 한국어 Conventional Commits와 PR 번호를 사용한다. 빌드·venv·비밀값·coverage·pytest
보고서·로컬 에이전트 설정은 커밋하지 않는다. 봇 리뷰는 자문이며 고칠 것은 고치고 독립 작업은
이슈로 남긴다. 필수 품질 판정은 `quality-gate`다. 테스트하지 못한 자원·범위를 결과에 명시한다.
문서 경로 수정은 설명 링크와 실제 파일 입력을 구분한다. 목업의 테스트 입력은 먼저 최소
fixture로 보존하고 소비자를 전환한다. 동작 변경 없이 관측 근거를 잃지 않는다.

<a id="documentation"></a>
## 문서 작성과 라우팅

먼저 `uv run python scripts/docs_contract.py --route`로 목적지를 고른다.
[문서 지도](docs/README.md)는 manifest에서 생성하는 읽기·작성 안내다. 같은 목적의 문서를
새로 만들지 않고 소유 절을 갱신한다. 역할·주제·경로의 목록을 이 문서에 따로 복제하지 않는다.

```powershell
uv run python scripts/docs_contract.py --route workflow
uv run python scripts/docs_contract.py --route src/hwpxfiller/webapp/screen_job.py
uv run python scripts/docs_contract.py --write
uv run python scripts/docs_contract.py --check
# 관련 본문과 근거를 대조한 뒤, 한 절만 확인한다.
uv run python scripts/docs_contract.py --review docs/workflow.md#workflow-generation
uv run python scripts/docs_contract.py --check
```

`--route`는 고정 역할·주제 ID·변경 경로로 목적지를 알려준다. 여러 책임에 걸치면 모두 표시하며
소유자가 없으면 실패한다. 사람의 의미 분류를 대신하지 않는다. 계획·진행·담당·완료·리뷰 지적은
GitHub 이슈·PR에 둔다. 작은 제안도 먼저 이슈로 기록하고, 독립 장문 연구만 연구 문서로 둔다.
자동 추출 가능한 목록은 코드·설정을 수정한 뒤 생성한다. 재현 입력은 테스트 fixture로 보존한다.

일반 문서는 영문 소문자 kebab-case다. `README.md`·`CONTRIBUTING.md`·`AGENTS.md`·`CLAUDE.md`와
생성 호환 파일 `PRODUCT.md`만 루트/진입 이름의 예외다. 회차·단계·날짜·버전·final·new·completion을
정본 이름에 넣지 않는다. 원관측의 날짜·환경·한계는 내용에서 보존한다. 현재 정본은 현재 규칙·
경계·실패 처리·검증 근거와 필요한 이유만 담는다. 리뷰 라운드·착지 원장·폐기 논쟁을 누적하지 않는다.

핵심 정본은 다섯 역할로 고정한다. 본문은 `<a id="주제-id"></a>`부터 다음 주제 전까지가 한 검토
단위다. 주제 ID는 유일하며 manifest의 문서·근거 코드·테스트와 연결한다. 절을 합치거나 나눌 때
본문뿐 아니라 소유 관계도 함께 바꾼다. 대형 문서 전체의 형식적 재승인을 요구하지 않는다.

`--write`는 지도·런타임 참조·PRODUCT 호환 출력만 갱신하고 검토 해시는 건드리지 않는다.
`--review`는 실제 대조한 주제 하나만 확인한다. 핵심 문서 전체나 모든 문서의 일괄 승인은 없다.
해시는 날짜 도장이 아니라 소유 절·검토 범위 선언·경로·내용·본문의 확인이다. 수동 계산하거나 복사해 넣지 않는다.
검토한 의미 변화 또는 본문이 불변인 이유를 PR에 쓴다. CRLF/LF 차이는 정규화한다.

CI는 문서 전수 등록·이름·역할/경로·주제 유일성·링크/앵커·빈 소스 패턴·없는 테스트·생성 불일치·
미검토 변경·파일별/핵심 총량 예산을 검사한다. `docs/` 밖의 추적 문서와 새 비무시 문서도 검사한다.
예제 설명·코퍼스 설명·테스트 HTML·제품 HTML은 정확한 경로와 소비 용도를 등록한다.
문서를 다른 폴더로 옮기거나 role 설명을 바꿔 두 번째 정본을 만드는 것은 통과하지 않는다.

독립 파일 신설은 독자·목적·검증 근거가 독립적인 경우만 검토한다. 먼저 중복·생성 가능한 목록을
제거한다. 신규 증거·연구는 분리 이유를 명시하고 문서 수/본문 예산 변경도 계약 리뷰로 다룬다.
기계 원장은 `tests/contracts/`, 브랜드 자산은 `assets/branding/`이며 수를 줄이려고 원장을 합치지 않는다.

검사는 구조와 연결된 입력의 드리프트를 탐지한다. 자연어의 진실·의미 중복이나 외부 URL의
생존을 증명하지는 않는다. 의미 정확성은 행동 테스트와 리뷰가 맡는다. 검사 범위를 줄이거나
skip·일괄 재서명으로 이를 숨기지 않는다.
