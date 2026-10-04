# Product

<!-- impeccable:product-schema 1 -->

> Generated from [docs/product.md](docs/product.md). Edit that source, then run `uv run python scripts/docs_contract.py --write`.

## 목적과 사용자

## Platform

web

## Users

한국어 Windows 환경에서 HWPX 서식과 표 데이터로 반복 문서를 만드는 사용자다.
우선 직군과 개인·조직 사용 범위는 미확정이다.

## Product Purpose

문서나르미는 반복 입력을 재사용 가능한 작업으로 묶는다. 사용자는 HWPX를 생성한 뒤
결과 문서의 값과 파일명을 확인하거나 TXT 내용을 검토·복사한다.

## Positioning

한글 프로그램이나 COM 자동화 없이 ZIP/XML로 HWPX를 직접 다룬다.
자동 연결 결과와 빈 값을 감추지 않는다. 시장 우월성·성능·인증을 추정하지 않는다.

## Operating Context

Windows pywebview/WebView2 안에서 실행하는 웹 UI다. 브라우저 SaaS나 모바일 제품이 아니다.
문서 만들기와 문서 작업에서 템플릿·연결·파일명을 구성한다. 구체적인 개체와 저장·실행
규칙은 [작업 흐름](docs/workflow.md)이 소유한다. 자동화용 CLI(`hwpxfiller`)는 같은 생성 경로를
창 없이 실행하며 `--ledger` 원장은 화면과 같은 `managed-delivery/v1` 형식이다.

## Capabilities and Constraints

입력은 `.xlsx`, `.xlsm`, `.csv`와 계약 목록 SQLite다. 기준 환경은 Windows 11 x64와
WebView2 Runtime이다. 생성에는 한글 프로그램이 필요 없지만 결과 파일을 열려면 HWPX
지원 앱이 필요하다. 한국어 UI의 표현은 [화면 규칙](docs/ui-style.md)을 따른다.

## Brand Commitments

제품명은 문서나르미다. 제품 마크는 [narmi-mark.svg](frontend/img/narmi-mark.svg),
원천 브랜드 자산은 [assets/branding](assets/branding)이 소유한다.

## Evidence on Hand

[사용자 소개](README.md), [실습](examples/quickstart-101/README.md),
[연결 화면](assets/readme/proof-mapping.png)이 사용 흐름의 근거다.
출하 여부·고객 사례·추가 제품 요구사항은 이 문서에서 만들어 내지 않는다.

## Product Principles

자동 제안과 누락은 사람이 확인할 수 있게 드러낸다. 반복 입력은 작업으로 재사용하고,
사용자 문서·데이터를 임의로 바꾸거나 잃지 않게 한다. 결과의 실패·불확실성을 숨기지 않는다.

## Accessibility & Inclusion

키보드·초점·ARIA, reduced motion과 대비 계약을 보존한다. 접근성 인증이나 추가 요구사항을
확정한 것으로 설명하지 않는다. 구체적인 검수는 [화면 규칙](docs/ui-style.md#ui-visual)을 따른다.


## 지원 경계

코드와 테스트가 존재한다는 사실은 UI에 노출되거나 배포된 기능이라는 뜻이 아니다.

| 범위 | 현재 제공 | 유지하는 것과 재개 조건 |
|---|---|---|
| 작업·템플릿 태그와 그룹 | 웹 UI 비노출 | 모델·판정·영속 보존. 수요 확인 후 투영·동사·게이트·실주행을 함께 복구 |
| 온보딩 튜토리얼 | 상단 진입·첫 사용자 초대, 같은 앱 안의 집중 연습 8개 과정 | 원본 4개만 GUI에 동봉. 연습 환경·실제 조작으로 진행하고 종료 시 기존 작업으로 복귀. 안내·파일·학습 기록 초기화는 분리 |
| 나라장터 API | 웹 UI 비노출 | 어댑터·CLI 접합부 보존. 운영 환경·인증·응답 계약과 수요 확인 |

[packaging/verify_specs.py](packaging/verify_specs.py)는 [튜토리얼 원본](examples/tutorial)의
정확한 동봉 범위를 검사한다. 과거 [온보딩 예제](examples/onboarding)는 비동봉 유지 자산이며,
[별도 실습](examples/quickstart-101/README.md)과 배포 튜토리얼도 다르다. 기존 데이터 풀의
나라장터 항목은 숨기지 않고 미지원 사유를 알린다.
API 테스트는 키나 실 서비스 대신 fixture를 사용한다.

로컬 SQLite의 계약 목록(pclm)은 동결 대상이 아니다. 고정 허용목록 없이 DB의 뷰·표를 시트로
나열하고, 그 DB에 없는 시트는 등록·읽기에서 거절한다.
등록 목록·버전은 [생성 참조](docs/reference/runtime.md)에만 둔다.

임의 조건식의 자동 섹션 조립, 문서 수준 서식 조립, N레코드의 단일 문서 병합을 지원한다고
설명하지 않는다. 작성자가 선언한 항목·선택을 사용자가 고르는 구성 기능과 다른 범위다.
조판 수준 HWPX→PDF 내보내기를 제공하지 않는다. 산출물 구조 관찰은 조판 엔진이 아니다.
템플릿 저작 작업대는 HWPX·TXT만 열며 HWP 가져오기와 macOS 지원은 제공하지 않는다.

HWPX 입력은 엔트리 payload를 읽기 전에 ZIP central directory 선언값으로 자원 한도를 잰다
([`HwpxPackageLimits`](src/hwpxcore/package.py)). 파일 1 GiB, ZIP 엔트리 4,096개,
엔트리당 비압축 256 MiB, 비압축 합계 1 GiB, 비압축 1 MiB를 넘는 엔트리의 압축률 500:1이 상한이다.
넘으면 `HWPX 자원 한도 초과:` 뒤에 관측값과 한도를 붙여 열기를 거절하며 일부만 읽어 쓰지 않는다.
선언보다 짧은 엔트리, 암호화·패치 데이터 플래그, STORED·DEFLATED 밖의 압축 방식도 거절한다.
테스트 corpus와 예제의 실측은 모든 한도의 1% 미만이다. Excel·CSV 입력에는 아직 규모 한도가 없다.

