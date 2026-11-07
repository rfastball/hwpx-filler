# 기여와 검증

<a id="development"></a>
## 환경·검증·출하

앱·CLI와 검증 도구는 Rust(`rust-toolchain.toml`)와 Node(`.node-version`)만 쓴다. 버전은 [생성 참조](docs/reference/runtime.md)에 있다.
제품은 Windows에서 검증하며 Linux 정적 검사는 실 WebView2 검증을 대신하지 않는다.

```powershell
npm ci
.\run-filler.ps1
.\run-filler.ps1 -Cli --help
.\test.ps1
.\test.ps1 -LiveScope auto
.\test-rust.ps1
.\scripts\rust_coverage.ps1
```

Node는 `package.json`·`package-lock.json`, Rust는 `Cargo.toml`·`Cargo.lock`을 따른다.
의존성 변경 시 잠금 파일도 갱신하며 CI는 `npm ci`·`--locked`로 검사한다. 렌더 검사에는 설치된 Chrome이 필요하다.

HWPX 저작용 rhwp는 `vendor/rhwp/source.json`과 `scripts/build_rhwp.ps1`이 준비한다.
첫 빌드는 네트워크가 필요하며 앱은 봉인된 Studio·WASM·폰트만 쓴다.

`test.ps1`는 web build → Cargo 잠금 의존 받기 → TOML 파서 준비 → Node 테스트 → 문구 census → 복잡도 예산 → 문서 계약 →
Rust workspace → 설치 Chrome 렌더·rhwp 왕복 → 실 Win32 → 네이티브 실창을 실행하고 실패한 단계에서 멈춘다.
인자는 `-LiveScope`·`-SkipLive`뿐이며 그 밖의 인자는 거절한다. Rust만은 `.\test-rust.ps1`로 검사한다.
문서 검사 성공을 전체 품질 성공으로 보고하지 않는다.
로컬 `.\test.ps1 -LiveScope auto`는 나머지 검사를 마친 뒤 봉인한 web 자산을 검증하고
Rust GUI를 release profile로 빌드해 격리 자산 폴더에서 해당 WebView2 범위만 실행한다.
실제 출하 속도와 같은 profile을 검사하며 설치 꾸러미 검증을 대신하지 않는다. CI의 실창 판정은
언제나 전체이며 부분 선택을 거절한다.

[quality.yml](.github/workflows/quality.yml)이 job 구성·순서를 소유한다. `sealed-web`의 한 산출물을
소비자가 `VerifyExisting`으로 **setup-node보다 먼저** 검증한다. `quality-gate`는 필수 job의
success만 허용하고 문서 변경은 `static`에서 검사한다. `sealed-web`은 Node의 프런트
계약 검사와 Rust의 봉인 검증을 사용한다.

coverage 하한은 [원장](tests/contracts/package-coverage-floors.toml)의 패키지별 line·branch 값이며
`scripts/rust_coverage.ps1`이 LLVM 계측으로 재고 `rust-coverage` job이 소유한다. 하한은 올리기만 한다.
네이티브 양성 테스트를 수치로 대체하지 않는다. 실 Win32 검사는 `#[ignore]` Rust 테스트이며 이름 목록을
`test.ps1`·`windows-native`가 공유한다. 자원이 없는 로컬에서만 `HWPX_SKIP_NATIVE_TESTS`·`HWPX_SKIP_MOTION_TESTS`·`HWPX_SKIP_GUI_TESTS`를
명시하고 제외 범위를 보고한다. CI에는 opt-out·부분 live가 없다. 기존 창·fixture와 앱 홈 격리를 재사용한다.

```powershell
.\packaging\build_native.ps1 -Target all
.\packaging\build_native.ps1 -Target all -IncludeInstaller
.\build.ps1
.\package-installer.ps1
```

`packaging/build_native.ps1`이 GUI·CLI 독립 번들과 WebView2 selftest·selfcheck를 검증한다.
`packaging/build.ps1`은 공개 인자를 전달한다. 설치본에는 Inno Setup이 필요하다.
릴리스는 버전과 일치하는 `vX.Y.Z` 태그에서 [release.yml](.github/workflows/release.yml)이 실행한다.
[hwpx-artifact](crates/hwpx-artifact/src/reconcile.rs)가 source·dist·portable, 릴리스의 installed까지
frontend identity를 대조한다. `build-metadata.json`은 identity와 런타임 근거를 담는다.
동봉 자산은 [제품 지원 경계](docs/product.md#product-scope)를 따른다.

GUI와 CLI는 독립 폴더 `dist/hwpx-filler-web`·`dist/hwpx-cli`에 배포한다.
각 exe는 `hwpx-filler-web.exe`·`hwpx-cli.exe`다. 빌더는 Node 없는 PATH의 seal selfcheck,
실제 WebView2·same-origin·외부망 차단과 CLI 명령을 검사한다. GUI 런타임은 CLI에서 제외한다.
Node·node_modules·frontend 원천은 싣지 않고, 제3자 고지는 각 번들의 `THIRD_PARTY_NOTICES`·
`licenses/`로 제공한다. 설치·제거·서명은 release workflow의 책임이다.

<a id="changes"></a>
## 변경과 리뷰

제품 계약은 [목적](docs/product.md), [아키텍처](docs/architecture.md),
[작업 흐름](docs/workflow.md), [화면 규칙](docs/ui-style.md)이 각각 소유한다.
실패·불확실성·손실을 숨기거나 의미 판정을 여러 계층에서 다시 조립하지 않는다.

`hwpx-filler` 공개 API는 소비 컨트롤러와 행동 테스트를 함께 변경한다. 화면 추가·삭제·개명은 컨트롤러·
registry·프런트 라우팅·DOM 루트·blocker 복구·selftest·live101·실렌더를 한 변경으로 다룬다.
직접 호출은 메서드 입력 검증과 생성 브리지·독립 오라클을 함께 대조한다.
동결 모델·자산은 실제 소비자를 확인하지 않고 삭제하거나 표면에 재연결하지 않는다.

리뷰는 계획 일치뿐 아니라 기존 busy/disabled 열거, 트리거↔액션 양방향 존재, 공유 팩토리·
상수·헬퍼의 중복 구현, 문서 주석에 명시한 seam·접근 경계 우회를 확인한다.
사용자 새 문장은 [문안 규칙](docs/ui-style.md#ui-copy)대로 기본 0이고 먼저 열거한다.

JavaScript·Rust 모듈·함수의 문장·분기 상한은 [복잡도 게이트](scripts/complexity_budget.mjs)가 검사한다.
[동결 원장](tests/contracts/complexity-budget.toml)의 기존 초과는 내려가기만 하며,
책임을 분리한 뒤 `node scripts/complexity_budget.mjs --tighten`으로 줄인다.
추가·상향은 추적 이슈와 사유를 기록한 임시 `override`만 허용한다.

커밋은 한국어 Conventional Commits와 PR 번호를 사용한다. 빌드·비밀값·coverage
보고서·로컬 에이전트 설정은 커밋하지 않는다. 봇 리뷰는 자문이며 고칠 것은 고치고 독립 작업은
이슈로 남긴다. 필수 품질 판정은 `quality-gate`다. 테스트하지 못한 자원·범위를 결과에 명시한다.
문서 경로 수정은 설명 링크와 실제 파일 입력을 구분한다. 목업의 테스트 입력은 먼저 최소
fixture로 보존하고 소비자를 전환한다. 동작 변경 없이 관측 근거를 잃지 않는다.

<a id="documentation"></a>
## 문서 작성과 라우팅

먼저 `node scripts/docs_contract.mjs --route`로 목적지를 고른다.
[문서 지도](docs/README.md)는 manifest에서 생성하는 읽기·작성 안내다. 같은 목적의 문서를
새로 만들지 않고 소유 절을 갱신한다. 역할·주제·경로의 목록을 이 문서에 따로 복제하지 않는다.

```powershell
node scripts/docs_contract.mjs --route workflow
node scripts/docs_contract.mjs --route crates/hwpx-desktop/src/job_controller.rs
node scripts/docs_contract.mjs --write
node scripts/docs_contract.mjs --check
# 관련 본문과 근거를 대조한 뒤, 한 절만 확인한다.
node scripts/docs_contract.mjs --review docs/workflow.md#workflow-generation
node scripts/docs_contract.mjs --check
```

`--route`는 역할·주제·경로의 소유 절을 표시하고 소유자가 없으면 실패한다.
계획·진행·리뷰는 이슈·PR에 두고, 생성 목록은 원천을 수정한다. 재현 입력은 fixture로 보존한다.

일반 문서는 영문 소문자 kebab-case다. 루트 진입 이름과 생성 `PRODUCT.md`만 예외다.
공통 지침은 `AGENTS.md` 하나에 둔다. 회차·단계·날짜·final·new를 정본 이름에 넣지 않고,
본문에는 현재 규칙·실패 처리·근거를 남긴다. 도구 설정은 문서 목록에서 제외한다.

핵심 정본은 다섯 역할로 고정한다. `<a id="주제-id"></a>`부터 다음 주제 전까지가 검토 단위다.
절을 나누거나 합치면 manifest의 소유 관계도 바꾼다.

`--write`는 생성 출력만 갱신한다. `--review`는 실제 대조한 주제 하나만 확인하며,
해시를 수동 계산하거나 일괄 승인하지 않는다. 검토 근거는 PR에 쓴다.

CI는 문서 등록·경로·링크·근거·생성 출력·검토 해시·예산을 검사한다.
추적 예제·코퍼스·HTML도 소비 용도와 함께 등록한다.

독립 파일은 독자·목적·근거가 독립적일 때만 만든다. 기계 원장은 `tests/contracts/`, 브랜드 자산은
`assets/branding/`에 둔다.

검사는 구조·입력 드리프트를 찾는다. 의미 정확성은 행동 테스트와 리뷰가 맡으며 skip·일괄 재서명으로 숨기지 않는다.
