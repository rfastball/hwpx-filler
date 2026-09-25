# 제품

<a id="product-purpose"></a>
## 목적과 사용자

### Platform

web

### Users

한국어 Windows 환경에서 HWPX 서식과 표 데이터로 반복 문서를 만드는 사용자다.
우선 직군과 개인·조직 사용 범위는 미확정이다.

### Product Purpose

문서나르미는 반복 입력을 재사용 가능한 작업으로 묶는다. 사용자는 HWPX를 생성한 뒤
결과 문서의 값과 파일명을 확인하거나 TXT 내용을 검토·복사한다.

### Positioning

한글 프로그램이나 COM 자동화 없이 ZIP/XML로 HWPX를 직접 다룬다.
자동 연결 결과와 빈 값을 감추지 않는다. 시장 우월성·성능·인증을 추정하지 않는다.

### Operating Context

Windows pywebview/WebView2 안에서 실행하는 웹 UI다. 브라우저 SaaS나 모바일 제품이 아니다.
문서 만들기와 문서 작업에서 템플릿·연결·파일명을 구성한다. 구체적인 개체와 저장·실행
규칙은 [작업 흐름](workflow.md)이 소유한다.

### Capabilities and Constraints

입력은 `.xlsx`, `.xlsm`, `.csv`와 계약 목록 SQLite다. 기준 환경은 Windows 11 x64와
WebView2 Runtime이다. 생성에는 한글 프로그램이 필요 없지만 결과 파일을 열려면 HWPX
지원 앱이 필요하다. 한국어 UI의 표현은 [화면 규칙](ui-style.md)을 따른다.

### Brand Commitments

제품명은 문서나르미다. 제품 마크는 [narmi-mark.svg](../frontend/img/narmi-mark.svg),
원천 브랜드 자산은 [assets/branding](../assets/branding)이 소유한다.

### Evidence on Hand

[사용자 소개](../README.md), [실습](../examples/quickstart-101/README.md),
[연결 화면](../assets/readme/proof-mapping.png)이 사용 흐름의 근거다.
출하 여부·고객 사례·추가 제품 요구사항은 이 문서에서 만들어 내지 않는다.

### Product Principles

자동 제안과 누락은 사람이 확인할 수 있게 드러낸다. 반복 입력은 작업으로 재사용하고,
사용자 문서·데이터를 임의로 바꾸거나 잃지 않게 한다. 결과의 실패·불확실성을 숨기지 않는다.

### Accessibility & Inclusion

키보드·초점·ARIA, reduced motion과 대비 계약을 보존한다. 접근성 인증이나 추가 요구사항을
확정한 것으로 설명하지 않는다. 구체적인 검수는 [화면 규칙](ui-style.md#ui-visual)을 따른다.

<a id="product-scope"></a>
## 지원 경계

코드와 테스트가 존재한다는 사실은 UI에 노출되거나 배포된 기능이라는 뜻이 아니다.

| 범위 | 현재 제공 | 유지하는 것과 재개 조건 |
|---|---|---|
| 작업·템플릿 태그와 그룹 | 웹 UI 비노출 | 모델·판정·영속 보존. 수요 확인 후 투영·동사·게이트·실주행을 함께 복구 |
| 온보딩 튜토리얼 | 웹 진입·마운트 없음, 배포 자산 비동봉 | 모델·컨트롤러·설정·예제·부품 보존. 교육 설계와 설치·제거·실주행·패키징 재검증 |
| 나라장터 API | 웹 UI 비노출 | 어댑터·CLI 접합부 보존. 운영 환경·인증·응답 계약과 수요 확인 |

[packaging/verify_specs.py](../packaging/verify_specs.py)는 동결 자산의 비동봉을 검사한다.
[온보딩 예제](../examples/onboarding)는 유지 자산이며 [실습](../examples/quickstart-101/README.md)과
배포 튜토리얼은 다르다. 기존 데이터 풀의 나라장터 항목은 숨기지 않고 미지원 사유를 알린다.
API 테스트는 키나 실 서비스 대신 fixture를 사용한다.

로컬 SQLite의 계약 목록(pclm)은 동결 대상이 아니다. 제공 가능한 면은 `PCLM_DOC_VIEWS`와
제품 게이트가 소유한다. 등록 목록·버전은 [생성 참조](reference/runtime.md)에만 둔다.

임의 조건식의 자동 섹션 조립, 문서 수준 서식 조립, N레코드의 단일 문서 병합을 지원한다고
설명하지 않는다. 작성자가 선언한 항목·선택을 사용자가 고르는 구성 기능과 다른 범위다.
조판 수준 HWPX→PDF 내보내기를 제공하지 않는다. 산출물 구조 관찰은 조판 엔진이 아니다.

<a id="product-direction"></a>
## 재개 조건

| 방향 | 착수 전에 필요한 근거 |
|---|---|
| HWPX 반복 행·라인아이템 | 문서 수요, 부모/하위 레코드 모델, 병합 셀·행 좌표·ID 재작성 실험과 한글 round-trip |
| TXT 가변 반복 행 | 실제 수요와 라인아이템 데이터 형태 |
| 값 표본을 활용한 유형 추천 | 실사용 오추천 사례·회귀 fixture, 제안과 자동 적용의 분리 |
| PDF 내보내기 | 수요, 조판 엔진·변환기, 설치·배포·실패 처리 경계 |
| ERP 연동 | 인증·엔드포인트·응답 스키마와 테스트 가능한 fixture |
| 여러 레코드의 단일 문서 병합 | N파일 흐름으로 풀리지 않는 수요와 제품 범위 재결정 |

조건은 기능 약속이나 착수 순서가 아니다. 진행·담당자·일정·완료는
[이슈](https://github.com/rfastball/hwpx-filler/issues)에서 관리한다.
[표현 권위 연구](research/document-authority.md)는 미채택 모델이며 현재 구현의 보증이 아니다.
채택분은 해당 현재 계약과 행동 테스트를 함께 변경한 뒤에만 제품 동작으로 설명한다.
