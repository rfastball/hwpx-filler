# AGENTS.md

문서나르미는 HWPX·TXT 반복 문서 생성을 위한 Windows 데스크톱 앱이다.
이 파일은 Codex·Claude Code의 공통 작업 진입점이다. 저장소의 에이전트 지침은 이 파일 하나로
유지하며 `CLAUDE.md`, 연결 파일, 도구별 지침 복제본을 만들지 않는다.

## 시작과 작업 범위

- `git status --short`로 기존 변경을 확인하고, 요청 밖 변경이나 사용자 작업을 덮어쓰지 않는다.
- [기여 절차](CONTRIBUTING.md)에서 작업에 해당하는 절을 읽는다.
  [문서 지도](docs/README.md)로 필요한 제품 계약을 찾는다. 상세 절차·제품 계약은 이곳에 복제하지 않는다.
- 문서·계약 변경 전 `uv run python scripts/docs_contract.py --route`로 기존 소유 절을 찾는다.
  같은 목적의 새 정본을 만들지 않는다. 동작과 문서가 다르면 코드·테스트로 확인해 불일치를 보고한다.

## 환경과 검증

명령은 저장소 루트의 PowerShell에서 실행한다. Python 환경은 `uv`로 관리하며 수동 venv를 만들지 않는다.
버전·의존성은 `.python-version`, `.node-version`, `pyproject.toml`, `uv.lock`, `package.json`을 따른다.

```powershell
# 최초 환경 준비. 잠금 파일을 임의로 갱신하지 않는다.
uv python install
uv sync --locked --all-extras --group dev --group build
# 앱 실행이 필요한 작업
.\run-filler.ps1
# 코드 변경 검증. 추가 인자는 pytest에만 전달된다.
.\test.ps1
# 문서·계약 변경 검증. 앱 전체 테스트를 대체하지 않는다.
uv run python scripts/docs_contract.py --check
```

- `test.ps1`는 web build → Node 테스트 → Ruff → Pyright → pytest·coverage를 실행한다.
  예: `.\test.ps1 tests\test_engine.py -x`도 pytest 이전의 공통 검사를 실행한다.
- `scripts/` 변경 시 `uv run ruff check scripts`, `packaging/` 변경 시
  `uv run ruff check packaging`을 확인한다. 변경에 맞는 추가 검증은 기여 절차를 따른다.
- Windows·WebView2 검증을 Linux 정적 검사로 대체하지 않는다. 자원이 없으면 기여 절차의
  명시적 opt-out만 사용하고 미검증 범위를 보고한다. 조용한 skip이나 coverage 하한 완화로 숨기지 않는다.

## 변경 시 지킬 경계

- 형식·계층 변경 전 [아키텍처](docs/architecture.md)를 확인한다. 의존은 `hwpxfiller` → `hwpxcore`다.
  `hwpxcore`에 제품 규칙이나 파일 시스템·창·시계 등 환경 효과를 넣지 않는다.
- 화면·브리지 변경은 [변경과 리뷰](CONTRIBUTING.md#changes)의 교차 계약을 함께 갱신한다.
  프런트엔드에서 의미·권한·최신성·실행 가능 여부를 다시 판정하지 않는다.
- 실패·손상·최신성 불명을 성공 fallback으로 낮추지 않는다. 사용자 문서·데이터의 손실을 숨기지 않는다.
- [지원 경계](docs/product.md#product-scope)의 동결·비노출 자산을 임의로 삭제하거나 UI에 재연결하지 않는다.
  코드의 존재만으로 제공·출하된 기능이라고 설명하지 않는다. API 테스트는 비밀키·실 서비스 대신 fixture를 쓴다.
- 새 사용자 문장은 기본 0이다. 필요한 문장의 전문과 이유를 변경 범위에 먼저 명시한다.

## 위임과 병렬 작업

- 사용 가능한 도구와 역할만 사용한다. 특정 모델·플러그인의 존재를 전제하지 않는다.
  Codex의 모델·역할 설정은 [.codex/config.toml](.codex/config.toml)과 연결된 역할 파일이 소유한다.
- 위임은 독립 작업이고 이득이 있을 때 사용한다. 변경 범위·파일·산출물·검증·정지 조건을 명시한다.
  사소하거나 분리 불가능한 작업, 위임 도구가 없는 환경에서는 직접 수행하고 같은 검증 기준을 적용한다.
- 같은 파일의 동시 수정을 피하고 `src/hwpxfiller/viewmodel/run_state.py`는 단일 소유자로 둔다.
  domain과 관련 viewmodel 변경은 함께 맡기고 `hwpxcore` 변경은 직렬 처리한다. 불확실하면 직렬로 수행한다.
- 위임자는 반환된 변경과 검증 근거를 확인한다. 동일 구현·검사를 이유 없이 반복하지 않되,
  후속 변경·실패·미해결 우려 또는 필수 최종 검사가 있으면 재검증한다.

## 문서 갱신과 완료 보고

- 문서의 이름·역할·예산·검토 범위는 [문서 작성 절차](CONTRIBUTING.md#documentation)와
  `docs/manifest.toml`을 따른다. 생성 문서는 원천을 수정한 뒤 `--write`로 갱신한다.
- `--write`는 검토 승인이 아니다. 본문과 근거를 실제 대조한 항목만 `--review`하고 다시 `--check`한다.
  검토 해시를 수동 작성하거나 일괄 재승인하지 않는다. 계획·진행·완료 이력은 이슈·PR에 둔다.
- 완료 시 변경 내용, 실행한 명령과 결과, 미실행 범위·이유, 남은 위험을 보고한다.
  문서 검사·부분 테스트 성공을 전체 품질 통과로 표현하지 않는다. 병합 판정은 CI `quality-gate`를 따른다.
- 커밋 시 기여 절차의 한국어 Conventional Commits·PR 번호 규칙을 따른다.
  비밀값·사용자 문서·로컬 설정·빌드 및 테스트 산출물을 커밋하지 않는다.
- 이 파일에는 빠졌을 때 구체적인 실수를 유발하는 지침만 남긴다.
  모델명·버전 목록·변경 이력·상세 매뉴얼을 누적하지 않고 기존 설정과 정본을 참조한다.
