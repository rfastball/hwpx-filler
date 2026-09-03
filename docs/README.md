# 문서 지도와 생명주기

> **문서 상태:** 현재 정본
> **권위 범위:** `docs/` 문서의 역할, 권위, 편집·폐기 기준
> **후속 정본:** 없음
> **편집 정책:** 계속 갱신

현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 문서는 그 사실을 설명하거나, 왜 그런
결정을 내렸는지 보존하거나, 당시 검토한 시안을 동결한다. 현재 사실을 찾을 때는 아래
**현재 정본**부터 읽고, 결정 배경이 필요할 때만 결정·역사 기록으로 내려간다.

## 상태 정의

| 상태 | 의미 | 편집 원칙 |
|---|---|---|
| **현재 정본** | 지금 따라야 할 계약·규약·운영 절차 | 코드·CI와 함께 계속 갱신 |
| **유효 결정** | 현재 구조를 지탱하는 결정과 트레이드오프 | 결정이 바뀔 때만 갱신 |
| **부분 대체** | 일부 결정은 유효하지만 구현·후속 결정이 일부를 대체 | 유효 범위와 후속 정본만 정정 |
| **역사 기록** | 완료된 조사·리뷰·착지 근거 | 동결하고 현재 정본으로 연결 |
| **동결 시안** | 특정 시점의 목업·실험안 | 편집하지 않고 채택 결과로 연결 |

## 현재 정본

| 문서 | 권위 |
|---|---|
| [개발·빌드·배포 환경](DEVELOPMENT_ENVIRONMENT.md) | Python·의존성·품질 게이트·패키징·릴리스 절차 |
| [UI 계약](UI_CONTRACT.md) | 현재 웹 UI의 계층, 화면 소유권, 계약 테스트 |
| [화면 문안 스타일](COPY_STYLE_GUIDE.md) | 사용자 대면 문장의 문형·길이·금지 표현 |
| [UI 용어 규약](UI_VOCABULARY.md) | 사용자 가시 용어·단위·폼 배치의 단일 출처 |
| [로드맵](ROADMAP.md) | 열린 방향·동결 항목·재개 신호 |
| [UI 갤러리](UI_GALLERY.html) | 실제 CSS를 사용하는 현재 시각 표면 |
| `package_coverage_floors.toml` | 패키지별 coverage 하한의 기계 판독 원장 |
| `ui_copy_census.toml` | 화면 문장의 allowlist(기계 판독). 규범 정본은 [화면 문안 스타일](COPY_STYLE_GUIDE.md) §8, 짝 게이트는 `tests/repo_contract/test_ui_copy_census.py` |
| `module_rings.toml` | 모듈별 ring 좌표(목표 권위)·source write set·behavior oracle. 안쪽→바깥쪽 의존 금지선의 **유일한** 정본이라 물리 이관 완료까지 영속(#542 H-2). 유래한 P1 계측 서사는 Git 이력이, 미이행 obligation 은 이슈 #582 가 소유 |
| `tests/architecture_contract.toml` | P3-07(#587)의 **영속 architecture 계약** — root 공개 표면, module-key 제품 vendor 정책, frontend vendor 배치·lifecycle owner를 정본화한다. 짝 게이트는 `tests/repo_contract/test_p3_forbidden_edges.py` |

## 결정 기록

| 문서 | 상태 | 유효 범위·후속 정본 |
|---|---|---|
| [핵심 워크플로 계약](core-workflow.md) | 부분 대체 | v4~v6 상태·전이·불변식의 계약 원문. 확정된 개정분은 [봉합 지도](archive/DATA_FIRST_INTEGRATION_MAP.md) §7·§8.2가 우선 |
| [UI/백엔드 분리](ARCH_UI_SEPARATION.md) | 부분 대체 | 링0·링1 분리는 유효, Qt 링2는 [UI 계약](UI_CONTRACT.md)이 대체 |
| [시각 디자인 언어](DESIGN_LANGUAGE.md) | 유효 결정 | 시각 문법의 이유; 실제 값은 UI 갤러리·토큰이 소유 |
| [UI 표면 ADR](UI_DESIGN_DECISIONS.md) | 부분 대체 | 상호작용 결정과 뒤집힘의 원장; 현재 표면은 UI 계약이 소유 |
| [웹 재렌더 보존](WEB_RENDER_PRESERVATION.md) | 부분 대체 | 전체 스냅샷·서브트리 재구성 결정은 완료된 React 전환이 대체. 포커스·캐럿·스크롤 보존 **책임**과 재고 술어의 틀은 유효하다. 근거 1·「현재 실효 범위」·검증 절은 오늘 거짓이니 배경으로만 읽는다 |
| [U2 실사용 피드백 라운드](UX_FEEDBACK_U2.md) | 유효 결정 | v6 착지 후 첫 외부 실측의 트리아지·판정. 그 라운드 미결 항목의 정본이기도 하다 |
| [U3 실사용 피드백 라운드](UX_FEEDBACK_U3.md) | 유효 결정 | S 로드맵 완주(v0.4.0) 후 「문서 만들기」 표면 6건의 트리아지·판정. 조치 추적은 #873 |
| [U4 실사용 피드백 라운드](UX_FEEDBACK_U4.md) | 유효 결정 | v0.5.0 출하 직후 34항의 판정과 재판정 기록(승인 뒤 확인 면 닫힘 · 이름 충돌은 blocker 아님 · **작업↔데이터 durable 강결합** — U2 §5.3 판정 D 폐기). 34항 트리아지·충돌 지점·라운드 분할은 우산 #932 |
| [U5 실사용 피드백 라운드](UX_FEEDBACK_U5.md) | 유효 결정 | 간소화 라운드 17항의 판정(중복 발화·상수 알림·거짓 동선·stale 어휘 감량, 설정 모달 신설, 저장 폴더 전역화). 착지 PR #963~#969, 회수 #965·#970 |
| [U6 실사용 피드백 라운드](UX_FEEDBACK_U6.md) | 유효 결정 | 작업 조합 재편 — 템플릿 풀·데이터 풀 조합 한 화면, 서식 폴더 풀(단일 루트·제자리 변환 유지), 연결 표 4열, 문서 작업 상세 패널. 리서치 근거·사용자 확정 5건. 우산 #974, 슬라이스 #975~#980 → PR #983~#990(완주 2026-09-03), 회수 #984·#986·#991. **새 실사용 판정은 여기** |
| [제어면 범위](CONTROL_PLANE_SCOPE.md) | 유효 결정 | SG-03(#735) v1 제어면 축소의 정본 — production consumer census + 네 scope 결정(shipping Profile 1개·backend-only semantic authority·신규 ledger allowlist·HMAC threat model). 짝 게이트는 `tests/repo_contract/test_control_surface_reduction.py`·`test_bridge_contract.py`·`tests/test_slot_configuration_product.py`·`tests/test_control_plane_evidence.py` |
| [온보딩 튜토리얼](ONBOARDING_TUTORIAL.md) | 유효 결정 | 배포본 동봉 예제 세트(#284 승계)와 진행 감지 체크리스트의 설계 — 자산 명세·루프 커리큘럼(기본/응용/고급+선택 심화 티어, 기존 UX 루프 문서 역참조)·순간 카드·단계 판정·설치/제거 경로. #284 결정 ②(범용 중립)를 조달 실문서 각색으로 뒤집는 재판정 포함. 구현 추적은 슬라이스 이슈 |
| [문서 표현과 변경 권위 계층 이론](DOCUMENT_AUTHORITY_LAYERS.md) | 유효 결정 | 저작·구성 투영·산출물 관찰 계층과 그 사이 경계 사건의 판정 기준. **미래 제품 모델이라 P 로드맵(#433·#511)의 입력이 아니다**(§0.0). 명사·불변식의 구체 적용은 [핵심 워크플로 계약](core-workflow.md)이, 현재 표면은 UI 계약이 소유. 적용 우산 = #530 |
| [HWPX structural range S0 관찰](HWPX_STRUCTURAL_RANGE_S0.md) | 유효 결정 | native R0~R5·T0~T7 증거와 `hwpxcore.bookmark_region` production 계약. R5(§19)·F계열(§22)·G계열(§23)이 proper nesting 의 표현·제거·경계 겹침을 증명했고 S1.6(§23.6)이 생성·unwrap·MetaTag mutation과 겹친 경계의 안전한 안쪽 제거를 승격했다 — crossing 은 §24 에서 **한글이 저장하지 못함**이 확인돼 거부를 유지한다 |
| [HWPX native MetaTag S1 spike](HWPX_METATAG_S1_SPIKE.md) | 유효 결정 | metadata carrier 3종의 wire format 과 한글 round-trip 보존성. 판정 **PASS-A (semantic)** — 모델이 아는 carrier 만 미지 payload 를 보존하고, 한글이 compact 로 재직렬화하므로 동등성은 byte 가 아니라 파싱 결과로 판정한다(§12.1 편차 기재) |

## 역사·동결 자료

| 문서군 | 상태 | 보존 이유 |
|---|---|---|
| `design_language_*.html` | 동결 시안 | 시각 언어 결정 당시 비교안 |
| `r-flow-mockups/` | 동결 시안 | 합의문이 참조하는 결정 시점 목업 |
| `u6-mockups/` | 동결 시안 | U6 조합 재편 4장면(1·2·3단계 + 문서 작업 상세 패널) — `UX_FEEDBACK_U6.md` 가 참조 |
| `archive/UI_CONTRACT_QT.md` (#225에서 분리) | 역사 기록 | 웹 이관 전 목업↔ViewModel↔Qt 계약 |
| [`archive/DATA_FIRST_INTEGRATION_MAP.md`](archive/DATA_FIRST_INTEGRATION_MAP.md) | 역사 기록 | v6 표면 전면 재작성(R1·F1~F8) 완주로 동결(2026-07-29). 대조표·슬라이싱은 정산됐고 **왜 그런 표면이 됐는지**의 근거 원장으로 남는다 — §7·§8.2·§10.x 판정은 계속 인용 대상. **그 「데이터-우선」 전제는 U4 §2.4(#932 U4-C)가 뒤집었다** — 동결 문서는 고치지 않고 승계 진술은 [UI 계약](UI_CONTRACT.md)의 세션·결속 절이 진다 |
| [`archive/REACT_MIGRATION_COMPLETION.md`](archive/REACT_MIGRATION_COMPLETION.md) | 역사 기록 | React/TypeScript 전환 완료 범위와 장기 계약 소유자. 단계별 계측·좌표는 Git 이력이 보존 |

## 유지·아카이브·폐기 기준

문서의 **현재 활용성**과 **고유 정보**를 각각 판정한다.

| 현재 활용 | 고유 정보 | 처리 |
|---|---|---|
| 높음 | 높음 | 현재 정본으로 유지·정비 |
| 낮음 | 높음 | 역사/동결 상태로 보존하고 후속 정본 연결 |
| 높음 | 낮음 | 정본에 병합한 뒤 원문 폐기 |
| 낮음 | 낮음 | 참조를 확인한 뒤 폐기 |

완료된 React 전환과 P1의 임시 계측 원장, 시점 고정 테스트 포트폴리오 생성물은 장기 계약과
P2 handoff로 필요한 내용만 옮긴 뒤 폐기했다. 그 밖의 문서를 폐기하려면 다음을 모두 충족해야 한다.

1. 저장소의 코드·테스트·문서에서 참조가 없다.
2. 후속 정본에 없는 고유 결정·근거·원관측이 없다.
3. 필요한 내용과 링크를 후속 정본에 먼저 흡수했다.
4. 생성물이라면 재생성 원천과 명령이 남아 있다.

Git 이력은 복구 수단이지 현재 문서의 탐색 경로를 대신하지 않는다.
