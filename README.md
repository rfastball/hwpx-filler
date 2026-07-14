# HWPX Tools

공통 HWPX 파서 위에 선 **독립 제품 둘** — 모노레포(서브프로젝트 구조):

```
src/hwpxcore/     공통 파서 — OCF 패키지(zip)·문서 트리 추출·검증. 제품 로직 없음.
src/hwpxdiff/     ① 규격서 개정 비교(읽기 도구) — 전문 신구대비표 GUI + CLI + 단독 exe
src/hwpxfiller/   ② 누름틀 값 주입(쓰기 도구) — UnivContractor VBA 엔진의 Python 포트
```

의존 방향은 아래로만: `hwpxdiff → hwpxcore ← hwpxfiller` (두 제품 간 상호 임포트 금지).

- **의존성 최소화**: `zipfile` + `lxml` 만으로 HWPX 처리 (PowerShell/MSXML/FSO 불필요)
- **OCF 정확 준수**: `mimetype` 무압축·최상단 규칙을 정확히 재현
- **hwpxfiller** — 데이터 소스 플러그인: Excel/CSV·나라장터 조달청 API, 장기적으로 ERP 확장
- **hwpxdiff** — 두 판본의 본문·조항·표를 의미 기반 비교, 원문 전체를 좌우 대조(신구대비표)로
  렌더. GUI `hwpx-diff`(또는 `python -m hwpxdiff`), CLI `hwpxdiff OLD NEW [--html]`,
  단독 배포는 `packaging/`(PyInstaller onedir)

## 개발 환경

Python과 의존성은 `uv` 및 `uv.lock`으로 관리한다. 저장소가 지정하는 Python 3.13도
`uv`가 설치하므로 시스템 Python이나 수동 venv가 필요 없다.
전체 온보딩·품질 검사·패키징·릴리스 정책은
[개발·빌드·배포 환경](docs/DEVELOPMENT_ENVIRONMENT.md)을 기준으로 한다.

```powershell
# 최초 1회: https://docs.astral.sh/uv/ 의 Windows 설치 방법으로 uv 설치
uv python install 3.13
uv sync --locked --all-extras --group dev --group build

# 품질 검사 + 타입 검사 + 전체 테스트 + coverage
.\test.ps1

# 소스에서 실행
.\run-filler.ps1
.\run-diff.ps1
```

## 사용

### CLI

```bash
# 템플릿이 요구하는 필드 확인
python -m hwpxfiller.cli --template template.hwpx --fields

# 템플릿 스키마 추출(필드·타입·표 영역·라벨 → JSON)
python -m hwpxfiller.cli schema template.hwpx --out schema.json

# 저작 보조: 평문 {{토큰}} → 누름틀 컴파일 (--out 없으면 미리보기만)
python -m hwpxfiller.cli fieldize draft.hwpx            # 미리보기(dry-run)
python -m hwpxfiller.cli fieldize draft.hwpx --out template.hwpx

# 템플릿 관리: 위생 점검(유사 필드명·미치환 토큰), 판본 간 필드 드리프트
python -m hwpxfiller.cli lint template.hwpx [--vocab words.txt]
python -m hwpxfiller.cli drift v2025.hwpx v2026.hwpx

# 규격서 개정 비교(별도 제품 hwpxdiff): 의미 기반 diff (--html 없으면 요약만)
python -m hwpxdiff.cli v2025.hwpx v2026.hwpx [--html report.html]

# 엑셀 데이터로 일괄 생성 (--ledger: 생성 원장 JSON 사이드카를 out 폴더에 저장, opt-in)
python -m hwpxfiller.cli --template template.hwpx --data data.xlsx \
    --out ./out --pattern "공고서-{{계약명}}" [--ledger]

# 텍스트 기안 치환(온나라 등): 데이터 1건을 평문 {{토큰}} 템플릿에 렌더
python -m hwpxfiller.cli render draft.txt --data data.xlsx [--profile mapping.json] [--record N] [--clip]

# 나라장터(조달청 표준 API)에서 취득 → 매핑 프로파일로 템플릿 채우기
#   영문 코드 키(bidNtceNo 등)는 --profile 로 한글 필드에 잇는다(없으면 대부분 빈칸).
#   키 해석 우선순위: --service-key-file(권장) > DATA_GO_KR_KEY 환경변수
#   > --service-key(인라인·노출 위험이라 비권장) > OS 자격증명 저장 키.
python -m hwpxfiller.cli --template template.hwpx --source nara \
    --service-key-file .secrets/nara_service_key --bgn 202606010000 --end 202606302359 \
    --profile mapping.json --out ./out --pattern "공고서-{{입찰공고번호}}"
```

### GUI

```bash
# 앱 B — 문서 생성(작업 홈 → 에디터/실행)
python -m hwpxfiller.webapp

# 앱 A(hwpxdiff) — 규격서 개정 diff 리뷰어(전문 신구대비표 + 변경 그룹 리스트)
python -m hwpxdiff
```

## 구조

**hwpxcore — 공통 파서** (제품 로직 없음)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `hwpxcore/package.py` | HWPX OCF ZIP 열기/저장 | `api_Compression` |
| `hwpxcore/text_extract.py` | 본문 텍스트 추출기(섹션/문단/표/셀)+커버리지 원장 | (신규 — diff/생성/검증 공용 토대) |
| `hwpxcore/validate.py` | 사전검증(누락/빈값) | `modHWPgen` |

**hwpxdiff — 개정 비교** (읽기 도구, `hwpxcore` 에만 의존)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `hwpxdiff/diff.py` | 의미 diff: 문단 정렬·낱말 강조·전문 대조 스트림·변경항목 | (신규 — 트랙 A, VBA선 불가) |
| `hwpxdiff/app.py` | GUI: 전문 신구대비표 + 변경 그룹 네비게이션 | (신규 — VBA선 불가) |
| `hwpxdiff/cli.py` | CLI: 요약 출력·HTML 리포트 저장 | (신규) |

**hwpxfiller — 누름틀 주입** (쓰기 도구, `hwpxcore` 에만 의존)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `core/fields.py` | 누름틀 XML DOM 주입 | `clsHWPXParser` |
| `core/schema.py` | 템플릿 스키마 추출(필드·타입·표 영역·라벨) | (신규 — 매핑/폼 토대) |
| `core/authoring.py` | 저작 보조: 평문 `{{토큰}}` → 누름틀 컴파일 | (신규 — `set_field`의 역연산) |
| `core/lint.py` | 템플릿 관리: 위생 lint + 판본 간 필드 드리프트 | (신규 — `modFuzzyMatch` 아이디어) |
| `core/mapping.py` | 소스 레코드 → 템플릿 필드 매핑(alias·N→1 합성·변환)+프로파일 | `frmErpPreview`+`modFuzzyMatch` |
| `core/engine.py` | 단일 문서 생성 조율 | `modHWPXEngine` |
| `core/job.py` | 작업(Job) 앵커 — durable {템플릿·매핑·파일명} + 레지스트리 + 실행요청 | (신규 — 원본의 일급 Job 부재를 수리) |
| `core/dataset_pool.py` | 데이터셋 풀: durable 데이터 *참조*(스냅샷 아님) 레지스트리, 실행 시 재읽기 | (신규 — ADR J) |
| `core/mapping_base.py` | 공유 베이스 매핑 레지스트리 — 명명 프로파일 1회 선언·다작업 참조 | (신규 — ADR J) |
| `core/format_engine.py` | 표시형 서식 엔진(금액·날짜) — 교체 가능한 어댑터 층 | (신규 — Excel 셀서식의 열화판) |
| `core/fill_ledger.py` | 생성 원장 척추: 매핑 전건 커버 + 템플릿 구조 드리프트(순수 파생) | (신규 — L1) |
| `core/source_profile.py` | 소스 프로파일링: 매핑이 읽을 소스 키의 실제형 관측(샘플+잠정 타입) | (신규 — L2) |
| `core/template_status.py` | 컴파일 수명주기 4-상태 파생 — 저장하지 않는 계산값(호출마다 재산출) | (신규) |
| `core/text_registry.py` | 텍스트 기안 템플릿(`.txt`) 레지스트리 — Job 과 분리된 경량 트랙 | (신규 — txt 트랙) |
| `core/text_render.py` | 텍스트 템플릿 렌더링: 데이터 → `{{필드}}` 순수 치환 | (신규 — txt 트랙) |
| `naming.py` | 파일명 패턴(`{{키}}`) 치환 | (파일명 규칙) |
| `batch.py` | 일괄 생성 | `Process_HWP_Generation` |
| `data/excel.py` | 엑셀/CSV 데이터 소스 | (대시보드 페이로드) |
| `data/nara.py` | 나라장터 조달청 API 취득 소스(stdlib urllib) | (신규 — 웹 취득, VBA선 불가) |
| `data/factory.py` | DataSource 팩토리 — 소스 *종류* 선택을 한 곳에 모음 | (신규) |
| `data/pipeline.py` | 소스 조립 파이프라인: 여러 DataSource → 하나(Power-Query식 저작) | (신규 — ADR K) |
| `data/secret_store.py` | 비밀 저장소 포트(OS 자격증명) + ServiceKey 마스킹 | (신규 — N1) |
| `gui/` | 앱 B: 작업 홈(`home`)·에디터(`job_editor`)·실행(`run_view`) | (대시보드 버튼) |

## 테스트

```powershell
.\test.ps1
# pytest 인자는 그대로 전달된다.
.\test.ps1 -x -q
```

## Windows 빌드와 배포

```powershell
# portable 빌드(PyInstaller onedir) 두 개 + self-check — 루트 build.ps1은 packaging/build.ps1 위임 러너
.\build.ps1

# Inno Setup 6 설치 후, 제품별 설치 EXE까지 생성
.\package-installer.ps1
```

산출물은 `dist\hwpx-filler\hwpx-filler.exe`, `dist\hwpx-diff\hwpx-diff.exe`와
`installer-dist\HWPX-*-Setup.exe`이다. 공식 릴리스는 `pyproject.toml`의 버전과 같은
`vX.Y.Z` 태그를 push하면 GitHub Actions가 테스트, 빌드, 설치·제거 스모크,
SHA-256 생성을 거쳐 게시한다. 저장소 secret `WINDOWS_CERTIFICATE_BASE64`와
`WINDOWS_CERTIFICATE_PASSWORD`가 모두 있으면 EXE와 설치본을 Authenticode 서명한다.
