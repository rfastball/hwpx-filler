<img src="docs/branding/document-narmi-mark-final.svg" alt="" width="48" align="left">

# 문서나르미

**같은 서식에 값만 바꿔 수십·수백 건 — 그 반복을 대신하는 한글(HWPX) 문서 자동화 데스크톱 앱.**

엑셀·CSV 데이터로 누름틀 `.hwpx` 템플릿을 채워 완성 문서를 일괄 생성하고, 평문 기안문도
같은 데이터로 채워 바로 복사한다. **한글 프로그램(HWP) 설치가 필요 없다** — COM 자동화
없이 `zipfile` + `lxml` 로 HWPX 를 직접 다룬다.

![작업 화면 — 작업을 고르면 데이터가 연결되고 문서가 생성된다](examples/quickstart-101/img/05-session-panel.png)

## 무엇을 해결하나

행정·조달 실무에서 같은 서식(공고서·계약서·발주요청서…)에 값만 바꿔 반복 생산하는 일은
흔하다. 한글을 띄워 손으로 치거나 취약한 HWP 매크로에 의존하던 그 일을, 문서나르미는
**작업(Job)** 하나로 바꾼다 — 템플릿·매핑·파일명을 한 번 저장해 두면, 다음부터는
데이터만 갈아 끼워 문서를 쏟아낸다.

- **작업 중심** — `{템플릿 + 매핑 + 파일명 패턴}` 을 작업으로 저장, 골라서 재사용.
  데이터는 작업에 저장하지 않고 생성할 때마다 그 순간의 파일을 읽는다.
- **누름틀 정확 주입** — 템플릿의 누름틀(필드) XML 을 DOM 수준에서 안전하게 채운다.
- **두 가지 산출** — 완성 HWPX 문서 일괄 생성(작업)과, 평문 기안문 채워 즉시
  복사(기안). 같은 데이터 한 벌로 둘 다.
- **조용한 실패 금지** — 미매핑 필드·빈값·미치환 토큰을 삼키지 않는다. 생성 전에
  화면으로 드러내고 확인을 받는다.

## 설치 및 실행

**Windows 10/11 전용.** 한글 설치가 필요 없고, 필요한 WebView2 런타임은 Win11 기본
탑재(Win10 도 Edge 업데이트로 대개 설치돼 있다).

- **설치본** — [Releases](../../releases)에서 `HWPX-Filler-*-Setup.exe` 를 받아 설치.
- **포터블** — 같은 곳의 `HWPX-Filler-*-portable.zip` 을 풀고 `hwpx-filler-web.exe` 실행.
- **소스에서** — 아래 [개발·테스트·빌드](#개발테스트빌드) 참고.

## 5분 Quick Start

앱을 띄우면 **「작업」 화면**이 열린다. 첫 문서까지 세 걸음:

1. **작업 만들기** — **[＋ 첫 작업 만들기]** → ① 라이브러리에서 누름틀 템플릿 선택
   ② 데이터(엑셀/CSV) 골라 필드 매핑 **[모두 확정]** ③ 작업 이름·파일명 패턴 입력
   후 **[작업 저장]**.
2. **생성** — 목록에서 작업을 고르면 함께 등록한 기본 데이터가 자동 연결된다.
   **[이 작업으로 문서 생성]** → 저장 폴더에 완성 HWPX 가 건수만큼 생긴다.
3. **다음부터는** — 작업만 고르고 생성. 데이터가 바뀌면 **[파일 선택…]** 으로 그때의
   파일을 겨눈다.

처음이라면 예제 템플릿·데이터가 갖춰진
**[101 사용설명서](examples/quickstart-101/README.md)** 를 따라가는 것이 가장 빠르다
(소요 15~20분, 스크린샷 포함 · 저장소 체크아웃 필요).

## 주요 기능

- **작업(HWPX 일괄 생성)** — 템플릿 필드 자동 추출, CSV/엑셀 헤더 직접 매칭 자동 제안,
  매핑 확정 게이트, 파일명 패턴(`발주요청서-{{공고번호}}`), 생성 전 본문 거울 확인,
  생성 원장(JSON) 기록.
- **기안(TXT 즉시 채움)** — 평문 `{{토큰}}` 초안에 데이터를 채워 미리보고 클립보드로
  복사. 여러 행을 큐로 넘기며 연달아 처리, 쓸 만한 조합은 기안 작업·템플릿으로 승격.
- **템플릿 관리** — HWPX·TXT 라이브러리, 위생 점검(유사 필드명·미치환 토큰), 평문
  초안 → 누름틀 컴파일(저작 보조), 그룹 정리.
- **데이터 관리** — 자주 쓰는 데이터 파일을 참조로 등록해 재사용(경로만 저장, 생성 때
  다시 읽는다).

## 안전성과 제약

원칙은 **"묻고 확정하게 하라, 아니면 시끄럽게 알려라"** — 애매하면 조용히 진행하지 않는다.

- 빈 값이 있으면 생성이 잠기고, 확인한 빈 값은 `〘미입력·필드명〙` 표식으로 남는다.
- 같은 이름 파일이 있으면 덮어쓰기 확인이 먼저 선다.
- 데이터에 없는 토큰은 기안 미리보기에 빨갛게 그대로 남는다 — 빈칸으로 새지 않는다.
- **Windows 전용**(WebView2 — Win11 기본 탑재). 한글 프로그램은 결과 확인에만 있으면 된다.
- 지원 데이터: `.xlsx`/`.csv`(utf-8-sig 권장). 나라장터(조달청 API) 연동은 어댑터·CLI
  수준으로만 유지 중이며 앱 화면에는 아직 노출되지 않는다.

## 문서

- **[101 사용설명서](examples/quickstart-101/README.md)** — 화면만 보고 첫 문서 만들기
  (+ [102 실전 조합](examples/quickstart-101/PATTERNS.md))
- [개발·빌드·배포 환경](docs/DEVELOPMENT_ENVIRONMENT.md) — 온보딩·품질 검사·릴리스 정책
- [문서 지도](docs/README.md) — 정본·결정 기록·역사 시안의 권위와 탐색 순서

---

## 개발·테스트·빌드

Python·의존성은 [`uv`](https://docs.astral.sh/uv/)로 관리한다. 저장소가 고정한
Python 3.13 도 `uv` 가 설치하므로 시스템 Python 이나 수동 venv 가 필요 없다.

```powershell
# 최초 1회 — uv 설치 후
uv python install 3.13
uv sync --locked --all-extras --group dev --group build

.\run-filler.ps1        # 앱 실행(= python -m hwpxfiller.webapp)
.\test.ps1              # 품질·타입 검사 + 전체 테스트 + coverage
```

```powershell
.\build.ps1                 # PyInstaller onedir 포터블 빌드 + self-check
.\package-installer.ps1     # Inno Setup 6 설치 후 설치 EXE 생성
```

산출물은 `dist\hwpx-filler-web\hwpx-filler-web.exe` 와
`installer-dist\HWPX-Filler-*-Setup.exe`.
`pyproject.toml` 버전과 같은 `vX.Y.Z` 태그를 push 하면 GitHub Actions 가 테스트·빌드·
설치/제거 스모크·SHA-256 생성을 거쳐 릴리스를 게시한다. 저장소 secret
`WINDOWS_CERTIFICATE_BASE64`·`WINDOWS_CERTIFICATE_PASSWORD` 가 있으면 Authenticode 서명한다.

### 자동화용 CLI (서브)

앱과 같은 엔진을 얇게 감싼 CLI. 자동화 파이프라인이나 수동 검증에 쓴다 — 일상 사용은 앱으로 한다.

```bash
python -m hwpxfiller.cli --template T.hwpx --fields              # 요구 필드 출력
python -m hwpxfiller.cli --template T.hwpx --data data.xlsx \    # 엑셀 일괄 생성
    --out ./out --pattern "공고서-{{계약명}}" [--ledger]
python -m hwpxfiller.cli schema T.hwpx --out schema.json         # 스키마 추출
python -m hwpxfiller.cli lint T.hwpx        # 위생 점검 / drift·fieldize·render 하위명령 등
```

전체 하위명령·나라장터 키 우선순위 등은 `python -m hwpxfiller.cli --help` 참고.

## 프로젝트 구조와 기술 식별자

사용자 노출 제품명은 **문서나르미**, 저장소·패키지·실행 파일 등 기술 식별자는
`hwpx-filler`(`hwpxfiller`) 계열을 유지한다.

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
| `data/nara.py` | 나라장터 조달청 API 취득 소스(stdlib urllib) — 동결(앱 미노출) |
| `data/pipeline.py` | 소스 조립 파이프라인: 여러 DataSource → 하나 |
| `data/secret_store.py` | 비밀 저장소 포트(OS 자격증명) + ServiceKey 마스킹 |
| `webapp/` · `gui/` | pywebview 웹 UI(작업·기안·템플릿 관리·데이터 관리·홈) |

> 사내 UnivContractor VBA 매크로(조달 공고서 생성)를 Python 으로 포팅하며 출발해,
> 원본이 갖지 못했던 것들 — 일급 작업(Job) 개념, 데이터 소스 플러그인, 생성 원장,
> 템플릿 위생 점검 — 을 더해 다시 세운 프로젝트다.

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
