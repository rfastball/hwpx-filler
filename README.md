# hwpx-filler

**HWPX 누름틀(필드)에 데이터를 주입해 한글 문서를 일괄 생성하는 도구.**
엑셀·CSV나 나라장터 조달청 API에서 데이터를 받아, 누름틀이 심어진 `.hwpx`
템플릿을 채워 문서를 대량으로 찍어낸다. 한글 프로그램(HWP) 설치도, COM 자동화도,
PowerShell/MSXML/FSO도 필요 없다 — `zipfile` + `lxml` 만으로 HWPX를 직접 다룬다.

> 사내 UnivContractor VBA 매크로(조달 공고서 생성)를 Python 으로 포팅하며 출발해,
> 원본이 갖지 못했던 것들 — 일급 작업(Job) 개념, 데이터 소스 플러그인, 생성 원장,
> 템플릿 위생 점검 — 을 더해 다시 세운 프로젝트다.

---

## 무엇을 해결하나

행정·조달 실무에서 같은 서식(공고서·계약서 등)에 값만 바꿔 수십·수백 건을 만드는 일은
흔하다. 기존 방식은 한글을 띄워 놓고 손으로 치거나, HWP COM 을 붙든 취약한 매크로에
의존했다. hwpx-filler 는 그 반복을 **파일 대 파일 변환**으로 바꾼다.

- **누름틀 정확 주입** — 템플릿의 누름틀(필드) XML 을 DOM 수준에서 안전하게 채운다.
- **데이터 소스 플러그인** — 엑셀/CSV, 나라장터(조달청 표준 API). 구조상 ERP 등으로 확장 가능.
- **조용한 실패 금지** — 매핑되지 않은 필드·빈값·미치환 토큰을 삼키지 않고 드러낸다
  (사전검증 + 생성 원장).
- **의존성 최소** — 순수 Python + `lxml`. 한글/오피스 설치 불요, CI 에서 그대로 돈다.
- **OCF 정확 준수** — `mimetype` 무압축·최상단 규칙 등 HWPX(OCF ZIP) 포맷 규약을 재현.

## 설치

Python·의존성은 [`uv`](https://docs.astral.sh/uv/)로 관리한다. 저장소가 고정한
Python 3.13 도 `uv` 가 설치하므로 시스템 Python 이나 수동 venv 가 필요 없다.

```powershell
# 최초 1회 — uv 설치 후
uv python install 3.13
uv sync --locked --all-extras --group dev --group build

# 소스에서 실행
.\run-filler.ps1        # GUI
.\test.ps1              # 품질·타입 검사 + 전체 테스트 + coverage
```

## 사용

### GUI

```bash
python -m hwpxfiller.webapp
```

작업 홈 → 에디터 → 실행으로 이어지는 4단계 마법사. 템플릿과 데이터 소스를 고르고,
필드 매핑을 확정한 뒤, 작업 단위로 문서를 생성한다. 실행 직전 강제 확인 게이트가
매핑·파일명·출력 폴더를 다시 보여준다.

### CLI

자동화·수동 검증용의 얇은 CLI.

```bash
# 템플릿이 요구하는 필드 확인
python -m hwpxfiller.cli --template template.hwpx --fields

# 엑셀 데이터로 일괄 생성 (--ledger: 생성 원장 JSON 사이드카를 out 폴더에 저장)
python -m hwpxfiller.cli --template template.hwpx --data data.xlsx \
    --out ./out --pattern "공고서-{{계약명}}" [--ledger]

# 나라장터(조달청 표준 API)에서 취득 → 매핑 프로파일로 템플릿 채우기
#   키 우선순위: --service-key-file(권장) > DATA_GO_KR_KEY 환경변수
#   > --service-key(인라인·노출 위험) > OS 자격증명 저장 키
python -m hwpxfiller.cli --template template.hwpx --source nara \
    --service-key-file .secrets/nara_service_key --bgn 202606010000 --end 202606302359 \
    --profile mapping.json --out ./out --pattern "공고서-{{입찰공고번호}}"
```

템플릿 저작·관리 보조 명령:

```bash
# 스키마 추출(필드·타입·표 영역·라벨 → JSON)
python -m hwpxfiller.cli schema template.hwpx --out schema.json

# 저작 보조: 평문 {{토큰}} → 누름틀 컴파일 (--out 없으면 미리보기)
python -m hwpxfiller.cli fieldize draft.hwpx --out template.hwpx

# 템플릿 위생 점검(유사 필드명·미치환 토큰) / 판본 간 필드 드리프트
python -m hwpxfiller.cli lint template.hwpx [--vocab words.txt]
python -m hwpxfiller.cli drift v2025.hwpx v2026.hwpx

# 텍스트 기안 치환(온나라 등): 데이터 1건 → 평문 {{토큰}} 템플릿 렌더
python -m hwpxfiller.cli render draft.txt --data data.xlsx [--record N] [--clip]
```

## 구조

공통 파서 `hwpxcore` 위에 제품 `hwpxfiller` 가 선다. 의존은 아래로만 흐른다.

**hwpxcore — 공통 파서** (제품 로직 없음)

| 모듈 | 역할 |
|------|------|
| `package.py` | HWPX OCF ZIP 열기/저장 |
| `text_extract.py` | 본문 텍스트 추출(섹션/문단/표/셀) + 커버리지 원장 |
| `validate.py` | 사전검증(누락/빈값) |

**hwpxfiller — 누름틀 주입** (`hwpxcore` 에만 의존)

| 모듈 | 역할 |
|------|------|
| `core/fields.py` | 누름틀 XML DOM 주입 |
| `core/schema.py` | 템플릿 스키마 추출(필드·타입·표 영역·라벨) |
| `core/authoring.py` | 저작 보조: 평문 `{{토큰}}` → 누름틀 컴파일 |
| `core/lint.py` | 템플릿 위생 lint + 판본 간 필드 드리프트 |
| `core/mapping.py` | 소스 레코드 → 템플릿 필드 매핑(alias·N→1 합성·변환) |
| `core/engine.py` | 단일 문서 생성 조율 |
| `core/job.py` | 작업(Job) 앵커 — durable {템플릿·매핑·파일명} + 레지스트리 |
| `core/dataset_pool.py` | 데이터셋 풀: durable 데이터 *참조* 레지스트리, 실행 시 재읽기 |
| `core/fill_ledger.py` | 생성 원장: 매핑 전건 커버 + 템플릿 구조 드리프트(순수 파생) |
| `naming.py` / `batch.py` | 파일명 패턴 치환 / 일괄 생성 |
| `data/excel.py` | 엑셀·CSV 데이터 소스 |
| `data/nara.py` | 나라장터 조달청 API 취득 소스(stdlib urllib) |
| `data/pipeline.py` | 소스 조립 파이프라인: 여러 DataSource → 하나 |
| `data/secret_store.py` | 비밀 저장소 포트(OS 자격증명) + ServiceKey 마스킹 |
| `webapp/` · `gui/` | pywebview 웹 UI(작업 홈·에디터·실행·매트릭스·템플릿 관리) |

## Windows 빌드와 배포

```powershell
.\build.ps1                 # PyInstaller onedir 포터블 빌드 + self-check
.\package-installer.ps1     # Inno Setup 6 설치 후 설치 EXE 생성
```

산출물은 `dist\hwpx-filler\hwpx-filler.exe` 와 `installer-dist\HWPX-*-Setup.exe`.
`pyproject.toml` 버전과 같은 `vX.Y.Z` 태그를 push 하면 GitHub Actions 가 테스트·빌드·
설치/제거 스모크·SHA-256 생성을 거쳐 릴리스를 게시한다. 저장소 secret
`WINDOWS_CERTIFICATE_BASE64`·`WINDOWS_CERTIFICATE_PASSWORD` 가 있으면 Authenticode 서명한다.

자세한 온보딩·품질 검사·릴리스 정책은
[개발·빌드·배포 환경 문서](docs/DEVELOPMENT_ENVIRONMENT.md)를 기준으로 한다.

---

## 함께 있는 자매 도구 — hwpxdiff (규격서 개정 비교)

같은 저장소에는 공통 파서 `hwpxcore` 를 공유하는 **읽기 쪽 자매 도구**가 하나 더 있다.
`hwpxdiff` 는 규격서·공고서 두 판본을 의미 기반으로 비교해, 원문 전체를 좌우 대조
(신구대비표)로 렌더하고 변경 그룹을 짚어 준다. filler 가 문서를 *쓰는* 도구라면
diff 는 문서를 *읽고 견주는* 도구다 — 관심 없으면 무시해도 filler 사용에는 지장 없다.

```bash
python -m hwpxdiff.webapp                                  # GUI 리뷰어
python -m hwpxdiff.cli v2025.hwpx v2026.hwpx [--html report.html]
```

의존 방향은 아래로만: `hwpxfiller → hwpxcore ← hwpxdiff` (두 제품 간 상호 임포트 금지).
