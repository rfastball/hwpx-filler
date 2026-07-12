# UI 디자인 리뷰 발견 박제 — UD 이슈 45건

> **출처**: docs/REVIEW_UI_ORCHESTRATOR.md §10 실행 (2026-07-12~13).
> 리뷰어 20에이전트(화면 6 × 렌즈 5) → Cross-Surface Correlator → 이슈별 적대적
> Verifier 20 → Editor. 원발견 97건을 46건으로 병합(상관 단계 기각 1), 검증 투입
> 20건 중 19건 확정·1건 반증 → **최종 45건**.
>
> **이 문서가 원본이다.** 캡처 뱅크(34+α 시나리오 PNG)는 세션 스크래치패드에
> 있었으나 세션 소멸과 함께 휘발된다 — 각 이슈의 시나리오 ID가 설계서 §5
> 레지스트리의 재현 경로다. 파일:라인 인용은 2026-07-13 워킹트리(라운드 1 조치
> 36/36 전량 착지 이후) 기준(패치 진행에 따라 어긋날 수 있음).
> **이 라운드는 보고 전용이다 — 조치는 별도 계획에서 유닛을 편성한다.**

## 통계와 판정 범례

- 원발견 97건 → 병합 이슈 46건(상관 단계 기각 1) → 적대 검증 반증 1건 제외 → **최종 45건**
- 판정 분포: 확정 25 / 수용 18 / 기각-제품무결 2 (V1 확증 반영 2026-07-13 — 미검증 8건 중 6건 확정 승격, UD-32·40 제품 무결 종결)
- 심각도 분포: 치명 0 / 높음 10 / 중간 20 / 낮음 15
- 스크린샷 없는 defect 0건 (defect 전건 캡처 뱅크 시각 증거 확보 상태에서 판정)
- 판정: **확정** = 독립 Verifier가 반증 4축(문서 의도·목업 권위·태스크 마찰·캡처 재확인)
  공격을 통과. **수용** = 정적 교차확증만(주로 code_smell·convention 계열).
  **미검증** = 캡처 미확보 등으로 investigation_needed(V1 확증 후 잔여 0). **기각-제품무결** = V1 확증 결과 제품 결함 아님(UD-32 하네스 부채, UD-40 RC-27 비회귀).

## 조치 계획 — 직교 고립단위 V1~V15 · 6스테이지 직렬 머지 (2026-07-13)

라운드 1(U1~U12) 선례를 승계하되 이번 라운드 특유의 두 축 — **style.py 병목**(12개 UD 접촉)과
**미검증 8건의 확증 선행** — 을 스테이지 구조로 흡수했다. 유닛 접두사 V는 U(라운드 1)·
W(캡처 시나리오)와의 충돌 회피. 파일은 `src/hwpxfiller/` 기준.

### 유닛 표

| 유닛 | 스코프 파일 | 배정 UD | 성격 | 선행 의존 |
|---|---|---|---|---|
| **V1** 확증·캡처 하네스 | 캡처 하네스(repo `scripts/ui_capture/` 이관 권고 — src 무접촉) | 32, 40 | 하네스 2결함 수리(유령 칩 sendPostedEvents / 한국어 번역기 설치) + 오염 캡처 재발행 + **미검증 6건(UD-10·26·28·29·30·43) 확증 캡처·판정** | 없음(최우선) |
| **V2** 스타일 셀렉터·토큰 기반 | style.py, design_tokens.json, 셀렉터 계약 테스트 신설 + 소비측 mark 1~2줄(home/app/pool/vocab/tm/compile_badge/run_view/txt_view 등) | 12, 13, 16, 23, 31 | danger 버튼 규칙(죽은 mark 소생)·배지 1계열 통합+`[level="muted"]`·fb `:disabled`+drift 정체성·primary:disabled 수렴·진행바 대비. **뷰 diff는 프로퍼티 마킹 한정(무행동변경)** | 없음 |
| **V3** 위저드·매핑 게이트 | wizard.py, mapping_state.py, mapping_table.py, core/mapping.py | 5, 8, 14, 15, 21, 27, 38 | 모두 확정 승격 게이트·데이터 스텝 전이 파기 확인·카운터 위계·퍼지 신호·RAW warn 합류·요약 미매핑 항·상태색 밴드 | 없음 |
| **V4** 나라장터 다이얼로그 | nara_view.py | 9, 35 | 잠금 사유 상시 발화 + BASE_QSS 자기 적용(+UD-12 삭제 버튼 mark 위탁 수령) | 없음 |
| **V5** 파이프라인 빌더 | pipeline_builder.py(+_state) | 1, 45 | 미리보기 무효화(RC-13 패턴 이식) + 닫기 더티 확인 | 없음 |
| **V6** 실행·결과 표면 수명주기 | run_state.py, run_view.py, batch_run.py, template_manager.py(+_state), dataset_pool_panel.py | 6, 7, 10, 19, 24 | 전제조건 게이트 _compose_gate 흡수(모달 강등)·tm 라벨 (text,level) seam·결과 라벨 수명주기 리셋·ack 토글화(링1 unacknowledge API)·컴파일 모달→인라인 | V1(UD-10 확증), V2 |
| **V7** 홈 진입 게이트·카드 | core/job.py, app.py, home.py (run_view는 참조 전용 — 수정 필요 시 V6 위탁) | 3, 36, 44 | 더블클릭·CTA를 badge_level 단일 술어에 연결+exists() 가드·보조 텍스트 위계·손상 카드 해소 동선. UD-40 회귀 확정 시 app.py 수리 수령처 | V1(UD-40 판정), V2 |
| **V8** txt 완료 서사·정체성 | txt_view.py, style.py(muted/ok 순서 — V2 위에서) | 2, 39 | _copy/_save report 분기 + _render 리셋 + 배타 프로퍼티·heading 제목 | V2(style.py 직렬) |
| **V9** 나라장터 후속 | nara_view.py | 29 | 중지 문구에 잔존 스냅샷 요약 병기 | V1(확증), V4(파일 직렬) |
| **V10** 매트릭스 파리티 | batch.py, matrix_state.py, matrix_view.py, run_view.py, run_state.py | 4, 42 | ADR-B 3상태 배지·ADR-E 게이트 매트릭스 이식(링1 집계 API)·세로 예산 | V6(파일 겹침·공용층), V2 |
| **V11** 위저드 후속 | wizard.py, mapping_state.py, mapping_table.py, style.py(read-only:focus) | 28, 37 | 데이터 스킵 중립색+안내 배너(확증 후)·읽기전용 포커스 정책 | V1(UD-28 확증), V3·V8(파일 직렬) |
| **V12** txt 데이터 겨눔 대칭화 | txt_view.py, batch_run.py, data/factory.py | 25 | txt에 풀 겨눔 경로 — V6가 정비한 공용층 소비 | V6, V8(파일 직렬) |
| **V13** 공용 패턴 이식 스윕 | home/pool/vocab/tm/matrix/txt/run/pipeline 뷰 + 공용 헬퍼 신설(style.py 무접촉 선언) | 11, 17, 26, 30 | sizeHint 지연 재동기·빈 상태 뷰 헬퍼·빈 값 명시 재진술 3표면·elidedText+툴팁 4표면 + 기하 단언 스모크 | V1(26·30 확증), 스테이지 1~3 전체 |
| **V14** 스타일 위계·토큰 2차 | style.py, design_tokens.json + 소비 뷰 + 재유입 가드 테스트 | 22, 33, 43 | 카드 보조 시각 등급·primary 화면당 1개 규율·raw hex/radius/인라인 토큰화+가드·fb radius 통일(확증 후) | V1(UD-43 확증), V13 |
| **V15** 전역 용어·단위·배치 마감 | 전 뷰·상태 파일 + 용어표 문서 | 18, 20, 34, 41 | RC-26 잔여 치환·상태 어휘 3정의·수량 분류사 규약·폼 배치 규약 — 기계적 전파일 스윕(라운드 1 U12 선례) | 전 유닛 최후단 |

### 스테이지 직렬 순서

```text
스테이지 1: V1 → V2 → V3 → V4 → V5   (기반·확증 — 병렬 개발, 표기 순 직렬 머지)
스테이지 2: V6 → V7 → V8 → V9        (고심각 뷰 클러스터 — 상호 무겹침)
스테이지 3: V10 → V11 → V12          (파생·확증 의존 후속)
스테이지 4: V13 / 5: V14 / 6: V15    (횡단 스윕 3연쇄 — 단독 스테이지 직렬)
```

순서 논리: **V1 최우선** — 미검증 6건의 확증 판정이 후속 유닛 스코프의 확정 조건이고,
하네스 수리 전 캡처는 오염 상태(유령 칩·영어 라벨)라 "수리 전후 캡처 쌍"의 기준선이 못 된다.
**V2가 기반** — 스테이지 2 이후 뷰 유닛들이 신설 셀렉터를 소비. style.py는
**V2→V8→V11→V14 스테이지당 1소유자 직렬 사슬**로 관리. run_view.py는 V2(마킹)→V6(본체)→
V10(파리티)→V13→V15 순환 — 스테이지 내 겹침 0 전수 확인됨. UD-04(높음)가 스테이지 3인
유일한 이유는 V6 공용층 의존 + run_view/run_state 파일 겹침(직교성 우선 원칙).
횡단 스윕 순서는 헬퍼 이식(V13) 후 토큰 스윕(V14), 문자열 치환(V15)은 전 diff 착지 후 최후단.

### 유닛 검증 프로토콜 (라운드 1 승계 + 이번 라운드 고유)

1. **worktree 베이스**: 착수 전 최신 master 스냅샷 확인(U11 재구현 사고 교훈), 스테이지 경계마다 재확인.
2. **독립 검증 에이전트**: 수리 전 master에서 결함 런타임/캡처 재현 → 수리 커밋에서 전건 비재현 + 적용 지점 전수 대조.
3. 유닛 자체 검증에 **pyright 포함**, 머지 후 전체 게이트 `.\test.ps1` green.
4. **캡처 쌍(이번 라운드 고유)**: 수리 전(master)·후(유닛 커밋) 동일 시나리오 캡처를 나란히 —
   하네스는 V1이 수리·재발행한 판 사용(그 전 뱅크의 C2~C5·W3·E2·E3은 유령 칩 오염, B군·C6은 영어 라벨).
   V1 신설 확증 시나리오: C7(완료 후 재겨눔)·D9(등록 후 삭제)[UD-10], D6c·E7·F5(빈 값 3표면)[UD-26],
   B8(데이터 스킵 매핑)[UD-28], D10(성공→재취득→중지)[UD-29], A4/C8/E6/F4+W5(긴 이름 밀도)[UD-30].
5. **확증 실패 처리**: V1 확증에서 재현 불가로 판정된 미검증 UD는 해당 유닛 스코프에서 기각하고
   이 문서 판정을 refuted 준용으로 갱신(부록 B에 기록).

특수 처리: UD-32(V1)는 제품 결함 아닌 하네스 부채 — 제품 방어 1줄은 실앱 확인 결과에 따라 V6 라이더로 위탁.
UD-40(V1)은 검증 공백 — RC-27 회귀 확정 시 수리는 V7(app.py)·V6(batch_run 한국어 버튼)로 라우팅.
UD-01은 investigation_needed이나 Verifier가 D6b로 확정 — V5 정상 배정.

## 추적 표

유닛 배정은 2026-07-13 조치 계획(위 절 — 직교 고립단위 V1~V15, 6스테이지 직렬 머지) 기준(변경 시 이 표만 갱신). 상태: `대기` → `착지(<commit>)`.

| ID | 심각도 | 유형 | 판정 | 렌즈 | 화면 | 유닛 | 상태 | 제목 |
|---|---|---|---|---|---|---|---|---|
| UD-01 | 높음 | investigation_needed | 확정 | L3 | D | V5 | 착지(ba538e3) | 파이프라인 빌더 — 소스·스텝 편집 후에도 이전 미리보기 표가 무표시 잔존('실행 결과가 이 표다' 단언과 모순), 저장은 미리보기 신선도 무검사 (RC-13 무효화 패턴 미이식) |
| UD-02 | 높음 | defect | 확정 | L3·L4 | E | V8 | 착지(1f615fc) | txt 완료 동작(복사·저장)이 RenderReport를 폐기하고 단일 안내 라벨을 영구 잠식 — 미입력 잔존에도 무조건 성공 신호 + 레코드 전환 후 '✓ 복사 완료' 스테일 + muted가 ok 색을 이기는 QSS 함정 |
| UD-03 | 높음 | defect | 확정 | L3·L4 | A | V7 | 착지(bbe6167) | 홈 실행 진입 판정이 카드 상태 모델과 미연결 — 더블클릭은 무게이트(손상 카드 조용한 no-op 크래시), 실행 CTA는 template_missing만 참조해 경고 배지와 모순 신호 |
| UD-04 | 높음 | defect | 확정 | L3·L4 | D | V10 | 대기 | 매트릭스 일괄 실행에 ADR-B 필드 3상태 배지·ADR-E 확인 게이트가 통째로 부재 — 단일 실행의 하드스톱이 매트릭스 우회로 조용히 소멸 |
| UD-05 | 높음 | defect | 확정 | L4 | B | V3 | 착지(89bbbbf) | '모두 확정' 1클릭이 미매칭 행 전부를 '의도적 비움' 확정으로 무경고 승격 — 행별 명시 확정 원칙의 대량 우회(인접 '모두 해제'는 무확인 작업 파기) |
| UD-06 | 높음 | defect | 확정 | L3·L4 | C | V6 | 착지(3e48c51) | 실행 화면 게이트 표현 이원화 — 필드 차단은 인라인·비활성인데 전제조건(데이터·폴더·레코드) 차단은 활성 primary + 클릭 후 모달(ADR-E가 강등한 차단 모달 재유입, 초기 상태는 전면 침묵) |
| UD-07 | 높음 | defect | 확정 | L1·L3 | F | V6 | 착지(3e48c51) | 템플릿 관리 결과 라벨이 심각도 불문 muted 고정 — lint 경고·실패 잔존 문구가 화면 최저 시각 위계의 회색으로 렌더(타 4개 화면은 전부 성과별 level 마킹) |
| UD-08 | 높음 | defect | 확정 | L3·L4 | B | V3 | 착지(89bbbbf) | 데이터 스텝(ADR-J 선택화) 전이 설계 미완 — 빈 데이터 '진행할 수 없습니다' 문구 vs 활성 Next 모순, 소스 라디오 토글은 로드된 파일·나라 스냅샷을 무확인·무고지 즉시 파기 |
| UD-09 | 높음 | defect | 확정 | L3·L4 | D | V4 | 착지(c08e54c) | 나라장터 대화상자 게이트의 잠금 사유 무발화 — 초기 상태에서 OK 비활성·다시 시도·중지의 이유를 화면 어디도 말하지 않음(사유는 사용자가 행동한 뒤에만 출현) |
| UD-10 | 높음 | investigation_needed | 확정 | L3 | C·D | V6 | 착지(3e48c51) | 결과 라벨의 수명주기가 서술 대상의 변경 이벤트와 미결합 — 실행 화면은 데이터 재겨눔 후 이전 '완료' 요약·진행바 잔존, 데이터 풀은 삭제 후에도 '등록 완료: X' 잔존 (RC-14 계열 새 표면) |
| UD-11 | 중간 | defect | 확정 | L1 | D·F | V13 | 대기 | QListWidget 카드 패턴의 item sizeHint 조기 박제(미폴리시 시점) — 풀·프로파일·템플릿 관리 카드의 액션 버튼이 세로 압착되어 라벨 판독 불가(보관/은퇴/삭제·마저 변환/검토 등) |
| UD-12 | 중간 | defect | 확정 | L4 | A·D | V2 | 착지(b2a11ce) | 파괴(삭제) 버튼의 시각 등급이 스타일 시스템에 정의된 적 없음 — 홈 카드는 무마크로 안전 버튼과 동일, 풀·프로파일은 죽은 mark(level,'danger')(QPushButton 셀렉터 부재) |
| UD-13 | 중간 | defect | 확정 | L1·L2·L3·L4 | F·A·D·global | V2 | 착지(b2a11ce) | 상태 배지 시각 어휘 분열 — 같은 badge_level이 홈=pill(알약)·템플릿 관리=level(맨 텍스트)·실행=fb(대형 필) 3계열로 렌더되고, QLabel[level="muted"] 셀렉터 부재로 RAW·보관 배지는 완전 무스타일(조용한 상태 소실) |
| UD-14 | 중간 | defect | 확정 | L1·L3 | B | V3 | 착지(89bbbbf) | 매핑 게이트 진행 카운터의 강조 역전 — 차단 중일수록 muted 회색(좌하단 구석), 해소되면 ok 초록 강조 (같은 위저드 스텝1의 warn 차단 신호와 자기 모순) |
| UD-15 | 중간 | defect | 확정 | L3 | B | V3 | 착지(89bbbbf) | 퍼지(모호) 자동 제안과 정확 일치 제안이 테이블에서 시각 동일 — ADR-D의 2등급 분류가 hover 툴팁에만 존재 |
| UD-16 | 중간 | defect | 확정 | L3·L4 | C·E | V2 | 착지(b2a11ce) | fb 필드 배지의 의미 축 미인코딩 — 동일 pill 시각에 정적 QLabel·클릭 필수 버튼·비활성 버튼 3종 혼재(:disabled 변형 전무), drift는 missing 색 차용으로 4번째 상태의 시각 정체성 부재 |
| UD-17 | 중간 | defect | 확정 | L1·L3 | A·D | V13 | 대기 | 빈 상태 패턴(스택 교체+중앙 안내+CTA)의 미이식 — txt 트랙(홈 우측)·데이터 풀·매핑 프로파일·매트릭스 작업 목록이 안내문 없는 백지 또는 푸터 잔글씨 |
| UD-18 | 중간 | convention_deviation | 수용 | L5 | A·B·D·F·global | V15 | 대기 | RC-26 용어 정렬의 치환 범위 누락 — 오류 다이얼로그('베이스' 4곳)·모달 제목('fieldize')·지시문('소스')·로그/메타(겨눔·정준)·액션 라벨 짝·'풀 항목'이 옛/내부 어휘로 잔존 (RC-26 회귀) |
| UD-19 | 중간 | defect | 확정 | L4 | C | V6 | 착지(3e48c51) | 미입력 확인(ack)이 원클릭 즉시 확정·비가역 — 해제 API 부재 + ack 칩 비활성화로 철회 상호작용 표면 자체가 제거됨 |
| UD-20 | 중간 | convention_deviation | 수용 | L5 | C·E | V15 | 대기 | 상태 어휘 경계 미정의 — 같은 필드가 한 화면에서 '값이 비어 있는 필드'(사전검증)이자 '미입력'(배지·게이트), '미입력' 1단어가 트랙마다 다른 개념(실행=출력값 빔, txt=열 부재) |
| UD-21 | 중간 | defect | 확정 | L3 | B | V3 | 착지(89bbbbf) | RAW 템플릿 차단 사유가 게이트 UI 경로 밖 조기 return으로 처리 — warn 레벨 없이 본문 요약 라벨로 렌더(같은 페이지 PARTIAL 차단은 warn 주황)되고 문구 원천이 VM·위젯에 이중화 |
| UD-22 | 중간 | convention_deviation | 수용 | L1·L4 | A·B·D·F | V14 | 대기 | primary '주 액션' 위계 규율 부재 — 홈은 한 뷰포트에 11개(카드 곱셈), 위저드 4스텝은 0개, 파이프라인 빌더는 2개 경쟁, 프로파일 관리는 0개, 템플릿 카드 내 위치는 좌/우 반전 |
| UD-23 | 중간 | convention_deviation | 수용 | L2 | A·global | V2 | 착지(b2a11ce) | MUTED(부차 텍스트) 토큰이 primary:disabled의 채움 배경으로 재전용 — 비활성 주 버튼(진회색 채움+흰 글자)이 활성 보조 버튼보다 시각적으로 강한 위계 역전 + 비활성 문법 이원화 |
| UD-24 | 중간 | convention_deviation | 수용 | L4 | F | V6 | 착지(3e48c51) | 컴파일 '변환 가능 토큰 없음' 결과만 차단 모달로 전달 — 같은 화면 액션 결과 5종 중 4종은 인라인 lbl_result, 이 1종만 모달이며 닫으면 흔적 0 |
| UD-25 | 중간 | convention_deviation | 수용 | L4 | E | V12 | 대기 | txt 즉시 기안의 데이터 겨눔 어포던스가 파일 다이얼로그 1종뿐 — 실행 표면(풀/파일/나라 3종)과 비대칭, ADR-J 1단계가 지목한 '스프레드시트 강제' 증상 잔존 |
| UD-26 | 중간 | investigation_needed | 확정 | L3 | D·E·F | V13 | 대기 | 미리보기·검수 표면 3곳에서 빈 값/결측이 무표시 빈 공간으로 렌더 — 파이프라인 left 조인 결측, txt 기안 blank 위치, FILLED 템플릿 미리보기 빈 값 (ADR-B '빈 공간으로 보이면 안 됨' 위반 후보) |
| UD-27 | 중간 | convention_deviation | 수용 | L3 | B | V3 | 착지(89bbbbf) | 매핑 미리보기 요약이 '채움/빈 값' 2상태만 집계 — 미매핑 잔존 10필드가 무집계라 합계(12)가 필드 수(22)와 불일치, 공란 규모 과소 진술 |
| UD-28 | 중간 | investigation_needed | 확정 | L3 | B | V11 | 대기 | 데이터 건너뛰기(ADR-J 공식 플로우) 시 매핑 스텝 전 행이 '미매칭' 빨강 경보로 렌더 추정 — '데이터 미연결'과 '미매칭'이 같은 신호, 레코드 0/0 빈 상태 안내 부재 |
| UD-29 | 중간 | investigation_needed | 확정 | L3 | D | V9 | 착지(b9a15cb) | 나라장터 취득 중지 후 신호 모순 — '중지했습니다' 경고만 남긴 채 OK 게이트는 이전 스냅샷 기준으로 재개방(무엇이 수용되는지 화면에 없음) |
| UD-30 | 중간 | investigation_needed | 확정 | L1 | A·C·E·F | V13 | 대기 | 가변 길이 사용자 문자열 라벨의 말줄임·최대폭 계약 부재 — KPI '최근 실행'·카드 제목(A), 실행 요약 헤딩(C), txt 토큰 배지(E), 템플릿 파일명(F)에서 현실 밀도 잘림/압착/가로 스크롤 가능 (RC-36 처치의 미이식 부위) |
| UD-31 | 낮음 | defect | 확정 | L1·L3 | C | V2 | 착지(b2a11ce) | 진행바 퍼센트 텍스트가 청크 위에서 대비 붕괴 — QSS가 텍스트를 MUTED 단색 고정(#7a7f87 on PRIMARY #2874a6 ≈ 1.3:1)해 Qt 기본 반전을 덮음, 실행 후반부 내내 수치 판독 불가 |
| UD-32 | 낮음 | investigation_needed | 기각(제품 무결) | L1·L3 | C·E | V1 | 착지(V1) | [캡처 뱅크 오염] deleteLater 유령 칩 — 하네스 processEvents가 DeferredDelete를 처리하지 않아 C2~C5·W3·E2·E3에 구세대 배지가 640px 색 블록으로 박제(제품 결함 아님 확증, 실앱 순간 노출 창만 저강도 확인 필요) |
| UD-33 | 낮음 | convention_deviation | 수용 | L2·L1 | global·A·E | V14 | 대기 | 디자인 토큰 '단일 출처' 규율의 사각지대 — 수작성 QSS 중성 회색 raw hex 12종, 예약 metric 스케일 밖 리터럴 산포(radius 7종·간격 ±1px·타입 3종), 인라인 setStyleSheet 예외 2곳(카드 제목 타이포 분열·DANGER 재타이핑), 투명 전경 이디엄 6회 복제 — 공통 원인: 생성기·가드가 상수 블록만 커버 |
| UD-34 | 낮음 | convention_deviation | 수용 | L5 | global | V15 | 대기 | 수량 단위 분류사 혼재 — 레코드가 '건'/'행', 필드가 'N개'/'N필드', 목록 헤더 카운트가 '건'/'개'·무단위 병존(같은 매트릭스 화면 안에서도 로그 '3행' vs 게이트 '1건 이상') |
| UD-35 | 낮음 | convention_deviation | 수용 | L1·L4 | D | V4 | 착지(c08e54c) | NaraAcquireDialog만 BASE_QSS 자기 적용 누락(최상위 표면 10곳 중 유일) — 부모 상속 의존이라 무부모/비스타일 문맥에서 primary 위계·danger 실패색·카드 룩 통째 소실 |
| UD-36 | 낮음 | convention_deviation | 수용 | L1 | A | V7 | 착지(bbe6167) | 홈 보조 텍스트의 배치·위계 규율 부재 — 부제 '내 작업 보관함'이 헤더 버튼 3개 뒤 최우단으로 표류, 패널 부연 2건만 muted 미적용 |
| UD-37 | 낮음 | convention_deviation | 수용 | L1·L4 | B | V11 | 대기 | 읽기전용 경로 필드가 포커스 체인에 남아 스텝1 첫 포커스 착지 — :focus 파랑 테두리+전체 선택이 :read-only 회색 룩을 덮어 '편집하라'와 '편집 불가' 신호 동시 발신(스텝2 동일 필드는 회색 렌더로 자기 모순) |
| UD-38 | 낮음 | convention_deviation | 수용 | L1 | B | V3 | 착지(89bbbbf) | 매핑 행 상태색 밴드 단절 — 상태색을 QTableWidgetItem 배경으로 구현해 cellWidget 4열(데이터 항목·변환·표시형·구분자)에 닿지 않음, 미매칭 빨강이 좌우 파편으로 찢김 |
| UD-39 | 낮음 | convention_deviation | 수용 | L1 | E | V8 | 착지(1f615fc) | txt 즉시 기안 화면만 heading(15px) 화면 제목 부재 — 최상위 표면 6곳의 위계 시작점 관례에서 유일 이탈 |
| UD-40 | 낮음 | investigation_needed | 기각(비회귀) | L5·L4 | B·C·global | V1 | 착지(V1) | [검증 공백] 캡처 뱅크가 Qt 한국어 번역기 미설치로 촬영 — 위저드 Back/Next/Cancel·완료 모달 Yes/No 영어는 RC-27 회귀 판정 불가, 번역 설치 상태의 '다음' 라벨 2개 공존(레코드 스텝퍼 vs NextButton)도 미확인 |
| UD-41 | 낮음 | polish | 수용 | L1 | B·C·D | V15 | 대기 | 폼·섹션 배치 규약 부재 — 위저드 스텝1·2는 비정렬 HBox(스텝4만 그리드), 실행 화면 두 경로 행의 입력 시작선 불일치, 매트릭스는 '작업 선택'만 카드 프레이밍(동급 섹션 맨몸) |
| UD-42 | 낮음 | polish | 수용 | L1 | D | V10 | 대기 | 매트릭스 세로 공간 예산 자기 모순 — 내부 대부분이 공백인 리스트 2단이 무제한 선호높이를 고집해 표준 크기에서도 페이지 스크롤 발생, 좁은 폭에선 결과 라벨·로그가 접힘 아래(빌더는 setMaximumHeight로 예방한 내부 대조) |
| UD-43 | 낮음 | investigation_needed | 확정 | L1·L3 | C·E | V14 | 대기 | fb 배지 radius(11px)가 칩 자연 높이(21~24px)의 절반 경계에 걸림 — 글리프 메트릭에 따라 같은 배지 계열이 라운드 필/직각 사각형 두 형태로 분열(missing 칩만 직각·3px 낮음) |
| UD-44 | 낮음 | polish | 수용 | L4 | A | V7 | 착지(bbe6167) | 손상 작업 카드가 앱 내 해소 수단 없이 상주 — 같은 목록의 정상 카드는 [삭제] 제공, 손상 카드는 경로 텍스트뿐(해소 불가 상시 경보의 습관화 위험) |
| UD-45 | 낮음 | polish | 수용 | L4 | D | V5 | 착지(ba538e3) | 파이프라인 빌더 '닫기'가 조립 중 작업물을 무확인 폐기 — 같은 다이얼로그가 덮어쓰기에는 confirm_destructive를 요구하는 비대칭 |

## 높음 (high) — 10건

### UD-01 · 파이프라인 빌더 — 소스·스텝 편집 후에도 이전 미리보기 표가 무표시 잔존('실행 결과가 이 표다' 단언과 모순), 저장은 미리보기 신선도 무검사 (RC-13 무효화 패턴 미이식)

**높음/investigation_needed** · **확정** · **신뢰도 0.95** · **화면 D / 렌즈 L3** · **시나리오 D6**

**관찰**: 코드 확정: pipeline_builder.py:183-249(소스/스텝 변경)가 미리보기 무효화 없음, :273-292(_on_save) 신선도 무검사, :116 헤더가 '저장 후 실행 결과가 이 표다' 단언. 나라 대화상자는 동일 구조(검증된 스냅샷)에 편집 즉시 무효화+재취득 안내(RC-13 착지)가 있는 내부 대조 패턴.

**기대**: 소스·스텝 변경 시 표/총행 라벨을 비우고 warn '조립이 변경됨 — 다시 미리보기하세요' 표시 — 단언 문구는 신선한 미리보기에서만 성립.

**사용자 영향**: inner로 미리보기해 만족한 뒤 how를 바꾸거나 스텝을 추가하고 저장하면, 사용자가 신뢰한 표와 실제 저장·실행 파이프라인이 조용히 달라짐 — 스테일 상태가 강한 단언 문구 아래 잔존(§7 high '스테일 상태 잔존 표시').

**디자인 근거**:

- 확인-또는-경보 — 스테일 결과의 조용한 잔존
- 내부 패턴 자기 모순 — nara_view는 편집 무효화(RC-13), 빌더는 무반응
- 모듈 자체 선언(pipeline_builder.py:6-8 'divergence 0')과 표시 상태의 불일치

**코드 증거**:

- src/hwpxfiller/gui/pipeline_builder.py:251-271 (표 갱신 단일 경로)
- src/hwpxfiller/gui/pipeline_builder.py:183-249 (변경 핸들러 무효화 없음)
- src/hwpxfiller/gui/pipeline_builder.py:273-292 (_on_save 신선도 무검사)

**관련 RC**:

- RC-13 부분 겹침(편집→결과 무효화 패턴이 나라 표면에만 착지)
- RC-14 부분 겹침(스테일 결과의 새 표면)

**근본 원인**: '검증된 스냅샷' 무효화 규율(RC-13)이 동일 구조의 빌더 미리보기에 이식되지 않음.

**권고**: 변경 핸들러에 미리보기 무효화+warn 라벨 추가. 캡처 하네스에 '미리보기 후 스텝 추가' 시나리오 추가해 시각 확증.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. ADR-C(인앱 미리보기 없음)는 HWPX 문서 렌더 트랙 한정이며, 파이프라인 빌더의 지배 결정은 ADR-K로 'WYSIWYG 미리보기' + UnivContractor #3 '표시/생성 divergence 없음'을 명시적으로 요구한다(docs/UI_DESIGN_DECISIONS.md ADR-K). 스테일 표 잔존을 의도한 결정 조항은 ADR·HANDOFF 어디에도 없음 — 오히려 문서가 발견을 강화.
- (ii) 권위 반증 — 실패. 주장 어디에도 목업 대조 없음. 근거 = 코드 확정 + ADR-K + 확인-또는-경보 원칙 + 내부 자기 모순: nara_view.py:82-87이 편집 시그널을 _on_query_edited(:311-325, RC-13: 스냅샷 폐기+OK 잠금+warn '입력이 변경됨 — 다시 가져오세요')에 배선하는데, 동일 구조의 빌더는 배선 0. 목업 참조 제거해도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립(강등 불가). 구체 워크스루 재현: 소스 2개+inner merge → 미리보기(3행/'총 3행') → 실제 핸들러(_on_add_step)로 append 스텝 추가 → ':116 저장 후 실행 결과가 이 표다' 헤더 아래 1스텝 결과가 무경고 잔존 → vm.save() 2스텝 정의로 무검사 저장 성공. 추가 악화: vm.save()는 build_source()를 아예 호출하지 않아 신선도만이 아니라 조립 유효성도 저장 시 무검증(pipeline_builder_state.py:229-253). 단, 원발견 user_impact의 'how를 바꾸거나'는 부정확 — cmb_how 단독 변경은 vm 무변경(corrected_evidence 참조), 성립 트리거는 소스/스텝 추가·제거.
- (iv) 캡처 재확인 — 수행·격상. D6.png 직접 열어 신선 상태 확인(INDEX 일치). 코드 앵커 4곳 전부 성립(:116 헤더, :183-249 핸들러 _render()만, :251-271 표 갱신 단일 경로, :273-292 신선도 무검사). §5 단건 재실행 규칙에 따라 동일 하네스 env로 verify_d6b_stale.py 실행 → bank/D6b.png 확보: 스텝 리스트 2건(merge+append)과 1스텝 시점 표(3행)가 단언 헤더 아래 공존, 경고 라벨 미표시. 런타임 출력 rows=3/총 3행/경고=False/vm.steps=2/저장 성공. 상태 수준 결함으로 offscreen 아티팩트 아님 → investigation_needed에서 confirmed로 격상.

**Verifier 비고**: 기각 시도 전부 실패, 캡처 공백까지 메워 확정. 심각도 high 유지: §7 high 예시 '스테일 상태 잔존 표시' 그 자체이고, 단언 헤더(:116)가 스테일 상태를 능동적으로 참이라 주장하는 점 + 저장 게이트 부재가 악화 요인이나, critical 기준(법적 문서 데이터 오류·손실로 직접 오도)에는 못 미침 — 저장된 레시피 자체는 실행 시 올바르게 재실행되므로 괴리는 '사용자가 검증한 것'과 '실행되는 것' 사이(데이터 손상 아님). 상향 규칙 중복 적용은 하지 않음(high 예시가 이미 확인-또는-경보 위반 시각형을 내포). RC-13 부분 겹침 연결 타당 — 신규 UD로 등재하되 related_rc 유지 권고. 권고 사항 검증: nara_view의 _on_query_edited 패턴(무효화+warn 라벨)이 그대로 이식 가능하며, 재현 스크립트(ui-review/verify_d6b_stale.py)가 캡처 하네스 시나리오 추가의 원형으로 재사용 가능. 핵심 파일: C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/pipeline_builder.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/pipeline_builder_state.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/nara_view.py.

**증거 정정**: 1) 'divergence 0' 자기 선언 위치는 pipeline_builder.py:6-8이 아니라 :7-8(6은 빈 줄) + pipeline_builder_state.py:7-10에도 동일 선언. 2) user_impact의 'how를 바꾸거나 …' 는 부분 부정확 — cmb_how 콤보 단독 변경은 vm.steps를 변경하지 않음(향후 add_step의 입력일 뿐); 스테일을 만드는 실제 액션은 소스 추가/제거·스텝 추가/제거(pipeline_builder.py:183-249). 3) 악화 사실 추가: vm.save()(pipeline_builder_state.py:229-253)는 이름·소스 비어있음만 검사하고 build_source()를 호출하지 않음 — 미리보기 신선도뿐 아니라 조립 가능성 자체도 저장 시 무검증(깨진 조립도 저장되어 실행 시점에야 실패). 4) 시각 확증 확보: bank/D6b.png(Verifier 단건 재실행, ui-review/verify_d6b_stale.py) — 스텝 2건 리스트와 1스텝 미리보기 표(3행/'총 3행')가 ':116 단언 헤더' 아래 무경고 공존, 이후 무검사 저장 성공. type은 investigation_needed → defect(confirmed)로 격상 가능.

</details>

### UD-02 · txt 완료 동작(복사·저장)이 RenderReport를 폐기하고 단일 안내 라벨을 영구 잠식 — 미입력 잔존에도 무조건 성공 신호 + 레코드 전환 후 '✓ 복사 완료' 스테일 + muted가 ok 색을 이기는 QSS 함정

**높음/defect** · **확정** · **신뢰도 0.93** · **화면 E / 렌즈 L3·L4** · **시나리오 E3·E2 (병합 2건)**

**관찰**: 런타임 재현 확증: (1) 미입력 토큰 잔존(E3) 상태 복사에도 '✓ 복사 완료' — 미입력 재진술 0. (2) 유일한 상시 경고('미입력 토큰은 그대로 표시됩니다')가 성공 문구로 교체·세션 내 소실. (3) _render가 lbl_note 미리셋 — 레코드 ▶ 이동 후에도 '✓ 복사 완료' 잔존, 클립보드엔 이전 레코드. (4) init의 muted='true' 미해제 + style.py:110-111 선언 순서로 level=ok 녹색이 MUTED 회색에 패배(픽셀 실측 #7a7f87). (5) _save도 report 폐기 무조건 성공 모달.

**기대**: 완료 동작이 report.missing_fields/empty_fields를 재진술(잔존 시 warn '미입력 N건(이름…) 포함 복사됨', 전량 채움 시에만 ok), _render 진입 시 lbl_note를 기본 안내+muted로 리셋, muted↔level 배타 프로퍼티 정리.

**사용자 영향**: 다레코드 기안 루프(복사→붙여넣기→다음 레코드)의 핵심 흐름에서 이전 레코드 내용을 새 레코드 것으로 오인해 공문 시스템에 붙여넣을 위험 — 문서 데이터 오류 직결 오전달. txt 트랙은 이 라벨이 사실상 유일한 완료 게이트 표면.

**디자인 근거**:

- ADR-E 최종 게이트는 미충족 필드 이름 재진술 — 완료 신호가 미입력 무언급(명시 위반 상향 근거)
- text_render.py:26 RenderReport docstring '표현 계층이 사용자에게 알린다' 계약을 표현 계층이 폐기
- 확인-또는-경보 시각형 — 스테일 성공 신호 잔존(§7 high 직격)
- ADR-C/H txt 트랙 실시간 view=진실과 상태 신호 불일치

**코드 증거**:

- src/hwpxfiller/gui/txt_view.py:192-196 (_copy가 report 폐기 + 무조건 ok)
- src/hwpxfiller/gui/txt_view.py:198-208 (_save 동일)
- src/hwpxfiller/gui/txt_view.py:165-190 (_render가 lbl_note 미리셋)
- src/hwpxfiller/gui/style.py:110-111 (muted 셀렉터가 level=ok 후순위 승리)

**관련 RC**:

- RC-30 부분 겹침(완료 서사 실패 무언급 — 착지는 batch_run 한정)
- RC-14 부분 겹침(스테일 결과 라벨의 새 표면)
- RC-13 부분 겹침(상태 변경이 기존 ok 신호 미무효화)

**근본 원인**: 단일 가변 슬롯(lbl_note)의 수명 관리 부재 + 성공 판정에 RenderReport 미반영 + muted/level 이중 프로퍼티의 QSS 선언 순서 함정 결합.

**권고**: _copy/_save에서 report 검사 후 warn/ok 분기, _render 진입부 리셋, mark 시 배타 프로퍼티 정리 또는 style.py 순서 조정. 뱅크에 '복사 직후/레코드 전환 후' 시나리오 추가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(부분 성립). ADR-H(UI_DESIGN_DECISIONS.md:201-216)는 txt 트랙 복사를 게이트 없는 commit으로, 누락 표면화를 view의 빨간 {{토큰}} 잔존으로 의도했으므로 '미입력 잔존에도 복사 자체가 됨'은 의도다. 그러나 이슈의 요구는 차단이 아니라 완료 피드백의 재진술·비스테일이며, 성공 라벨의 레코드/템플릿 전환 후 잔존, 유일 상시 경고문의 영구 소실, muted가 ok를 이기는 색 함정은 어떤 문서도 의도하지 않았다. 오히려 ADR-E(:123-126 미충족 이름 재진술)와 text_render.py:26-33 RenderReport 계약('표현 계층이 사용자에게 알린다')이 반대 방향을 명시 — txt_view.py:173·193이 report를 버린다.
- (ii) 권위 반증 — 실패. 주장 전체가 목업 대조에 전혀 기대지 않음. 근거는 ADR 조항·코어 docstring 계약·QSS 캐스케이드 순서·런타임 재현. 목업 참조 제거 후에도 완전히 선다.
- (iii) 태스크 마찰 입증 — 성립(강등 불가). 다레코드 기안 루프에서 오프스크린 독립 재현: 레코드1 복사 → ▶ 레코드2 이동 후에도 lbl_note='✓ 복사 완료' 잔존, 클립보드==레코드1 텍스트(view는 레코드2). 공문 시스템에 이전 레코드 데이터를 붙여넣는 구체 오전달 경로. polish 아님.
- (iv) 캡처·코드 재확인 — 성립. E3.png/E2.png 직접 열람: INDEX.md 기술과 일치(E3=담당자 빨간 토큰 잔존+muted 안내문, E2=전량 치환). 복사 후/전환 후 상태는 뱅크에 없어 독립 스크립트로 재실행: 5개 관찰 전부 재현 — (1) missing=['담당자'] 상태 복사에도 '✓ 복사 완료'·재진술 0, (2)(3) _step·select_template 후에도 성공 문구 잔존+클립보드 스테일, (4) muted+level=ok 실효색 #7a7f87(MUTED), 대조군 level=ok 단독은 #1e8449(OK) — style.py:110-111 순서 함정 확증, QSS 캐스케이드는 오프스크린 아티팩트 아님, (5) _save(txt_view.py:198-208) report 폐기 무조건 성공 모달. 인용 라인 전부 성립: txt_view.py:192-196·198-208·165-190, style.py:110-111 정확.

**Verifier 비고**: 확정(재확인+반증 통과). 5개 관찰 전부를 오프스크린 독립 스크립트로 재현했고 코드 근거 4건 전부 인용 라인 그대로 성립. 심각도는 §7 high 행 직격('스테일 상태 잔존 표시'·확인-또는-경보 시각형)으로 high 유지 — ADR-E 위반 상향(→critical)은 기각: ADR-H가 txt 트랙 표면화를 view의 빨간 토큰 잔존으로 의도해 재진술 요구를 부분 충족하고, 진실 표면(view)은 항상 정확해 critical 기준(빈칸이 채움처럼 보임 급)에 못 미침. 단 스테일 클립보드+성공 라벨 조합은 high 상단. 수정 방향은 이슈 recommendation 그대로 타당하되 한 가지 추가: muted/level 배타 정리 없이 warn 분기만 넣으면 style.py:111 함정에 warn 색도 동일하게 패배하므로 mark 시 반대 프로퍼티 해제가 선행 조건. related_rc(RC-14/13/30 부분 겹침) 분류도 타당 — 착지 표면이 달라 신규 UD 성립(§9 규칙 2).

**증거 정정**: 인용 라인 번호 전부 정확 — 정정 불요. 보강: report 폐기 지점은 _copy의 193뿐 아니라 _render의 173(`text, _report = self.vm.render()`)에도 있어 렌더 시점 경고 표면화 기회도 함께 버려짐. QSS 함정의 정확 기전 = 동일 특이도 속성 셀렉터에서 후순위 규칙 승리(level=warn/danger/ok가 style.py:108-110, muted="true"가 :111 — muted가 세 level 모두를 이기므로 warn 분기 구현 시에도 동일 함정 재발). 런타임 실측으로 select_template(외부 라우팅 재진입) 후에도 잔존 확인 — 원발견의 '레코드 전환' 범위보다 넓음.

</details>

### UD-03 · 홈 실행 진입 판정이 카드 상태 모델과 미연결 — 더블클릭은 무게이트(손상 카드 조용한 no-op 크래시), 실행 CTA는 template_missing만 참조해 경고 배지와 모순 신호

**높음/defect** · **확정** · **신뢰도 0.92** · **화면 A / 렌즈 L3·L4** · **시나리오 A2 (병합 2건)**

**관찰**: 증상 1(L4): itemDoubleClicked가 아이템 종류 무관 무조건 run_job_requested로 배선 — 손상 .job.json 카드('결단작업.job.json') 더블클릭 시 FileNotFoundError가 stderr로만 새고 GUI는 무반응, '템플릿 없음' 작업은 비활성 [실행] 버튼(선고지)을 더블클릭으로 우회해 RunView 도달. 증상 2(L3): '원문·누름틀 변환 필요' 배지 카드의 [실행]이 '실행 준비' 카드와 동일한 활성 primary — 활성 판정이 template_missing 단일 술어라 RAW/PARTIAL/오류 상태도 전부 활성(A2 캡처 실증). 증상 3: 손상 카드도 선택 하이라이트를 받아 실행 대상처럼 보임.

**기대**: 더블클릭 경로가 버튼 경로와 같은 게이트를 공유하고, 실행 CTA 활성 판정이 배지 레벨 어휘(compile_badge, RC-29 단일화)를 재사용해 danger(부재·오류)는 비활성+사유, RAW/warn은 최소 primary 강등. 실패는 절대 stderr로만 새지 않는다.

**사용자 영향**: 손상 카드 더블클릭이 조용한 무반응('앱 고장' 오인), 템플릿 없는 작업이 홈이 금지 선고한 실행 화면에 도달(표면 간 신호 모순), 경고 배지 카드의 파란 실행 클릭이 필드 0개 생성 시도로 직행.

**디자인 근거**:

- 저장소 자기 규율 '확인-또는-경보' — 조용한 실패(stderr only)·조용한 통과 금지
- 내부 자기 모순 — 같은 화면이 같은 액션을 버튼 경로는 게이트, 더블클릭 경로는 무게이트; _CorruptJobCard docstring '액션 없음' 선언과 배선의 모순
- ADR-E 계열 게이트 사유 가시성

**코드 증거**:

- src/hwpxfiller/gui/home.py:235-237 (itemDoubleClicked 무조건 배선)
- src/hwpxfiller/gui/home.py:75 (setEnabled(not template_missing) — compile_state 미참조)
- src/hwpxfiller/gui/app.py:99-105 (exists() 없이 registry.load 직행)
- src/hwpxfiller/core/job.py:160-161 (read_text 직행 → FileNotFoundError)
- src/hwpxfiller/gui/run_view.py:286-289 (하류도 로그 경고뿐)

**관련 RC**:

- RC-05 부분 겹침(손상 행 노출은 착지, 그 카드의 상호작용 게이트는 신규 증상)
- RC-23 부분 겹침(게이트 모순 신호 패턴의 홈 카드판)

**근본 원인**: 실행 가능 판정이 카드 상태 스냅샷과 분리된 두 부분 술어(버튼=template_missing만, 더블클릭=무검사)로 구현 — RC-29로 단일화된 배지 레벨 어휘가 CTA·제스처 판정에 이관되지 않음.

**권고**: 더블클릭 핸들러에서 손상/template_missing 행은 방출 중단+사유 고지, app._open_run 진입부에 exists() 가드+시끄러운 실패 다이얼로그, badge_level을 CTA 활성 판정에 연결. 손상 아이템 ItemIsSelectable 해제 검토.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패: UI_DESIGN_DECISIONS.md(ADR-E·I)·UI_DESIGN_HANDOFF.md 전수 검색에서 더블클릭 무게이트를 의도한 결정 없음. 오히려 HANDOFF §2 시그널 계약이 run_job_requested(str)=작업 이름을 선언하는데 손상 행 더블클릭은 파일명('결단작업.job.json')을 방출해 문서 계약을 추가로 위반. _CorruptJobCard docstring(home.py:93-97) '액션 없음(파싱 불가라 실행/편집 대상이 아님)' 선언과 235-237 배선의 자기 모순도 성립. HANDOFF '무거운 게이트는 에디터에만' 조항으로 홈 무게이트를 옹호하려 해도, 홈이 이미 버튼 경로를 게이트(home.py:75, '선고지' 주석)하므로 같은 액션의 두 경로 비대칭이라는 자기 모순은 문서로 구제 불가.
- (ii) 권위 반증 — 실패: 주장은 목업 대조에 전혀 기대지 않음. 근거가 코드 실증(배선·게이트 술어) + 저장소 자기 규율(확인-또는-경보) + 내부 자기 모순(§7 성립요건 ③)이며, A2 캡처는 상태 실재 증명용. 목업 참조를 전부 제거해도 주장 전체가 그대로 섬.
- (iii) 태스크 마찰 입증 — 성공(강등 불가): 헤드리스 재현으로 실증 — (a) 손상 카드 더블클릭 → FileNotFoundError가 stderr 트레이스백으로만 새고 GUI 무반응·무다이얼로그(사용자는 '앱 고장' 오인, 재시도 루프), (b) 템플릿 없는 작업 더블클릭 → 비활성 [실행]이 선고한 금지를 우회해 RunView 도달, 데이터 겨눔까지 진행한 뒤에야 danger 게이트에 차단(모순 신호 + 재작업), (c) A2의 RAW+매핑 0개 구성은 _compose_gate가 드리프트도 missing도 없다고 판정해 게이트 개방 — 미치환 원문 토큰 문서 생성까지 직행 가능. polish 아님.
- (iv) 캡처·코드 재확인 — 동일 관찰: A2.png 직접 열람 — 4카드 관찰 일치(❌ 부재=회색 비활성 실행, ✏ RAW=✅ 실행 준비와 동일한 파란 활성 primary, ⚠ 손상됨 카드=액션 없음+선택 가능). 인용 앵커 전건 성립: home.py:235-237(무조건 배선)·home.py:75(setEnabled(not template_missing))·app.py:99-105(load 직행, 정확히는 :102)·job.py:160-161(read_text 직행)·run_view.py:286-289(로그 경고뿐). 행동 주장은 offscreen 렌더 아티팩트와 무관한 로직 층 — 헤드리스 스크립트로 두 증상 모두 재현(투기 아닌 실증). investigation_needed 강등 사유 없음.

**Verifier 비고**: 확정(재확인+반증 4축 통과). 심각도 high 유지가 적정: §7 표의 high 기준 '에러 조용히 지나감'(손상 카드 FileNotFoundError stderr-only)에 정면 해당하고 확인-또는-경보 위반 상향분이 이미 반영된 수준. critical 비상향 근거 — 최빈 경로(template_missing·드리프트 N≥1)는 run_state의 fail-closed danger 게이트가 최종 차단해 법적 문서 데이터 오류로 직결되지 않으며, 조용한 오출력이 실제 성립하는 RAW+매핑 0개 구성은 위저드가 RAW 저작을 차단하므로 사후 템플릿 드리프트로만 도달하는 엣지. 핵심 확정 사실: (a) home.py:235-237 더블클릭이 아이템 종류·상태 무관 무조건 run_job_requested 방출(버튼 경로 게이트 home.py:75와 비대칭 — 같은 화면 같은 액션의 두 경로가 다른 판정), (b) 손상 카드 더블클릭은 stderr 트레이스백만 남기고 GUI 무반응(헤드리스 재현), (c) 비활성 [실행] 선고를 더블클릭이 우회해 RunView 개창(헤드리스 재현: 'HWPX Filler — 실행: missjob'), (d) CTA 활성 판정이 template_missing 단일 술어라 RAW/PARTIAL/ERROR 배지 카드도 '실행 준비'와 동일한 활성 primary(A2.png 픽셀 확인). merged_count=2·related_rc(RC-05 부분 겹침·RC-23 패턴 재현) 타당. 권고 방향(더블클릭 게이트 공유 + app._open_run 진입 가드 + badge_level→CTA 연결)도 RC-29 단일화 어휘 재사용이라 저장소 규율과 정합.

**증거 정정**: 1) 손상 카드 더블클릭의 실패 기전 정밀화: 더블클릭은 아이템 text=파일명을 방출 → JobRegistry.path_for가 이름에 '.job.json'을 재부착(_slug는 점 보존, job.py:75-77·177-178) → '<파일명>.job.json.job.json' 조회 → FileNotFoundError (경험 재현 완료; JSONDecodeError가 아님). 2) app.py:99-105 중 실제 load 호출은 app.py:102. 3) '하류도 로그 경고뿐'(run_view.py:286-289)은 진입 로그에 한해 정확하나 하류 전체를 과소 진술: run_state.py:442-444(validate_generate 템플릿 부재 danger GateError)와 run_state.py:379-381(read_error fail-closed danger 게이트)가 생성 시점엔 시끄럽게 차단 — 따라서 template_missing 우회의 종착은 조용한 오출력이 아니라 '모순 신호+낭비된 탐색 후 차단'. 단 RAW+매핑 0개(A2의 '원문 템플릿 작업' 카드 구성 그대로)는 드리프트·missing 모두 부재로 게이트가 열려(run_state.py:375-394) 미치환 토큰 문서 생성까지 통과 — '필드 0개 생성 직행' 주장은 이 구성에서 성립, 매핑 N≥1 드리프트 구성에선 danger 차단. 4) 추가 증거(신규): UI_DESIGN_HANDOFF.md §2가 run_job_requested(str)=작업 이름 계약을 선언 — 손상 행 더블클릭의 파일명 방출은 문서화된 seam 계약 위반. 5) 손상 아이템 ItemIsSelectable 플래그 보유 실증(증상 3 확정).

</details>

### UD-04 · 매트릭스 일괄 실행에 ADR-B 필드 3상태 배지·ADR-E 확인 게이트가 통째로 부재 — 단일 실행의 하드스톱이 매트릭스 우회로 조용히 소멸

**높음/defect** · **확정** · **신뢰도 0.87** · **화면 D / 렌즈 L3·L4** · **시나리오 D7 (병합 2건)**

**관찰**: D7 캡처: 매트릭스 화면에 필드 상태 배지·게이트 표면 없음(작업 목록·데이터·레코드·저장 폴더뿐). matrix_state.validate()는 blank/missing 무검사, 코드 주석이 '매트릭스엔 인라인 게이트가 없다'고 자인(matrix_view.py:171). 생성물엔 MISSING_MARKER만 박히고 완료 요약은 '문서 N/N 성공' — 미입력 존재를 실행 전·후 어느 시점에도 무언급.

**기대**: 선택 작업×겨눈 데이터의 preflight 요약(작업별 missing/blank 건수)을 생성 전 인라인 노출하고, missing>0이면 ADR-E형 이름 재진술 확인을 요구. 최소선: 완료 요약·모달에 '미입력 표식 포함 문서 n건' 병기.

**사용자 영향**: 같은 데이터가 단일 실행에선 하드스톱인데 매트릭스로 우회하면 확인 절차가 조용히 사라짐 — 미입력 표식이 박힌 법적 효력 문서가 무경고로 대량 생성되고 열어보기 전까지 알 수 없다.

**디자인 근거**:

- ADR-B '필드는 모든 표면에서 3상태를 각기 다른 배지로 — 빈 공간으로 보이면 안 됨'
- ADR-E 누락 상시 인라인 배지 + 최종 게이트 이름 재진술·강제 상호작용, ADR-J '게이트 보존' 조건 착지와의 괴리
- 내부 다수 패턴 자기 모순 — 동일 연산이 run_view=배지+게이트, matrix_view=무신호

**코드 증거**:

- src/hwpxfiller/gui/matrix_view.py:171 ('매트릭스엔 인라인 게이트가 없다' 주석)
- src/hwpxfiller/gui/matrix_state.py:118-149 (validate에 blank/missing 검사 0)
- src/hwpxfiller/batch.py:195-206 (MISSING_MARKER — 문서 안에서만 시끄러움)
- src/hwpxfiller/gui/run_view.py:418-426 (단일 실행의 대조 게이트)

**관련 RC**:

- RC-22 부분 겹침(run/matrix 공용화가 QThread·데이터 겨눔만 이식, ADR-E 게이트는 run_view 전용 잔존)

**근본 원인**: RC-22의 run/matrix 이원화 해소가 실행 인프라만 공용화하고, ADR-E 게이트(필드 상태 스냅샷·ack 상호작용)는 '매핑은 저작 시점 확정'이라는 확장 해석 아래 매트릭스 표면에서 생략됨.

**권고**: run_view의 필드 상태 스냅샷을 작업별로 집계해 매트릭스 작업 목록 행에 배지로 노출하고 missing>0 시 재진술 확인 단계 삽입. 최소 수리는 완료 요약·모달의 미입력 병기.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. 매트릭스의 게이트 생략을 의도로 결정한 조항 부재. UI_DESIGN_HANDOFF.md §0 '무거운 명시성 게이트(매핑 확정)는 셋업에만, 실행은 사전검증만'은 ADR-D 매핑 확정 게이트 한정이며, 같은 '실행' 표면인 run_view는 ADR-E 값 게이트를 실행 시점에 보유. UI_DESIGN_DECISIONS.md ADR-L §축 확정이 '값 수준 공란(레코드별 빈 값)은 ADR E ack 유지(강제 상호작용 후 진행 — 레코드마다 정당)'를 매트릭스 예외 없이 명시하고, ADR-J 결정 원장 행은 매트릭스 실행에 '(게이트 보존)'을 직접 부기. matrix_view.py 독스트링 '매핑 재확정 없음'은 D-게이트 면제를 E-게이트까지 확장 해석한 것 — 이슈의 root_cause 서술 그대로.
- (ii) 권위 반증 — 실패(주장 성립). 목업 대조 근거 0건. ADR-B/E 조항 + 내부 다수 패턴 자기모순(동일 생성 연산이 run_view=배지 4종+강제 ack 게이트, matrix_view=무신호)에 접지 — 목업 참조를 전부 제거해도 주장이 그대로 선다.
- (iii) 태스크 마찰 입증 — 성공(polish 강등 불가). 워크스루: 작업 3개 × 공유 CSV, 한 작업의 매핑 소스가 데이터에 부분 부재(코퍼스 실증 형상 — ADR-J 기록 '22필드 중 12개 자동초안, 10개 소스 부재'). 단일 실행은 missing 배지+버튼 비활성+필드별 ack 강제(run_view.py:360-398,418-426). 매트릭스는 matrix_state.validate(118-149)가 소스⊖매핑·레코드 공란을 전혀 안 보고 통과 → 완료 요약 '완료 — 작업 3개, 문서 9/9 성공'(matrix_view.py:314-318) + 완료 모달 ask_open_result_folder(succeeded, failed, out_dir)에 missing 파라미터 자체가 없음(matrix_view.py:333). 발견 경로가 M×N 문서 전건을 한글로 열기뿐 — 법적 효력 문서의 재작업·오신뢰라는 실마찰.
- (iv) 캡처·코드 재확인 — 전부 성립. D7.png 직접 열람: 작업 체크리스트·데이터 행·레코드 선택·저장 폴더·일괄 생성/취소·진행바·로그만 존재, 필드 배지·게이트 라벨 0(C2/C3 대비). 위젯의 구조적 부재라 offscreen 아티팩트 의심 불성립(픽셀성 주장 아님). matrix_view.py:171 주석 축자 일치('매트릭스엔 인라인 게이트가 없다 — teardown 후 생성 버튼 단순 재활성.'), matrix_state.py:118-149·run_view.py:418-426·batch.py mark_missing 기본 MISSING_MARKER(202-206) 전부 인용대로 성립.

**Verifier 비고**: 확정(재확인+반증 통과). 심각도는 high 유지 — §7 high 행('상태 신호 부재, 에러 조용히 지나감') 정확 부합. ADR-E 명시 조항 위반 상향 규칙을 검토했으나 critical 미도달로 판단: 생성물 자체는 MISSING_MARKER로 시끄럽고(ADR-B 출력측 준수, '의도된 소음') 한글이 ADR-C 검증 표면으로 남아, 은폐가 앱 표면에 국한되고 critical 예시('빈칸이 채움처럼 보임' = 오표현)에는 못 미침 — 단, 완료 요약이 표식 포함 문서를 '성공'으로 집계하는 낙관 서사는 RC-30 계열의 잔여 구멍(RC-30은 실패 무언급만 봉합, missing 무언급은 미봉합)이라 high 상단. related_rc는 RC-22 부분 겹침 + RC-30 후속으로 표기 권장. 권고의 최소 수리(완료 요약·모달에 '미입력 표식 포함 문서 n건' 병기)는 MatrixResult에 missing 집계 추가만으로 가능해 비용 대비 타당.

**증거 정정**: run_view 대조 게이트는 인용된 418-426보다 넓다: 인라인 배지 표면 = run_view.py:360-383(_refresh_field_panel, fill/blank/drift/ack/missing 5분기), ack 강제 상호작용 = 385-388, 게이트 렌더 = 390-398. batch.py 인용 195-206은 실제로 독스트링 194-198(mark_missing '누락을 시끄럽게') + 기본값 적용 202-206(MISSING_MARKER import·대입). '실행 후 무언급' 주장의 직접 앵커 추가: matrix_view.py:314-318(완료 요약 succeeded/failed만 집계) 및 :333(ask_open_result_folder — missing 인자 부재). 보강 근거 추가 가능: ADR-J 결정 원장 행의 '매트릭스 실행…(게이트 보존)' 부기와 ADR-L '값 수준 공란은 ADR E ack 유지(레코드마다 정당)' 조항이 매트릭스 무예외임을 문서로 확정.

</details>

### UD-05 · '모두 확정' 1클릭이 미매칭 행 전부를 '의도적 비움' 확정으로 무경고 승격 — 행별 명시 확정 원칙의 대량 우회(인접 '모두 해제'는 무확인 작업 파기)

**높음/defect** · **확정** · **신뢰도 0.85** · **화면 B / 렌즈 L4** · **시나리오 B5**

**관찰**: B5: 미매칭 빨강 행 15개가 '(비움)' 표시 상태에서 '모두 확정'이 confirm_all()을 무조건 호출 — 미매칭 전부가 '의도적 빈칸'으로 재해석되고 빨강 경고 소멸, Next 게이트 개방. 인접 동일 스타일 '모두 해제'는 최대 22행 수작업 확정을 무확인 1클릭 파기(상호 오클릭 위험).

**기대**: 대량 확정은 내용 없는 미매칭 행을 제외하거나, _ack_partial(ADR-E 원형)처럼 값이 주입되지 않는 필드를 이름으로 재진술하고 기본버튼=취소 확인 경유. '모두 해제'도 확정 n>0이면 확인 요구.

**사용자 영향**: 습관적 '모두 확정' 1클릭으로 미매칭 필드들이 의도적 비움으로 통과 → 실행 화면에서 비차단 blank 배지로 강등 → 법적 효력 문서에 빈 값 주입. 하류 blank 배지가 잔존 신호를 주므로 critical 미상향, high 유지.

**디자인 근거**:

- ADR-D 미매칭 loud hard-stop — 대량 확정이 재진술 없이 해제
- ADR-E 이름 재진술+강제 상호작용과 정면 배치
- 내부 자기 모순 — _ack_partial·confirm_destructive는 재진술+기본 취소 강제, 가장 무거운 게이트의 대량 우회만 무가드; mapping_state.py 독스트링 스스로 '사람이 행별로 확정' 선언

**코드 증거**:

- src/hwpxfiller/gui/mapping_table.py:482-494 (_on_confirm_all/_on_unconfirm_all 무확인)
- src/hwpxfiller/gui/mapping_state.py:191-197 (전 행 무조건 boolean 플립)
- src/hwpxfiller/gui/mapping_state.py:187-189 ('빈 행 확정=의도적 비움' 독스트링)

**관련 RC**:

- RC-08 부분 겹침(저장 가드는 '전부' 비움만 잡음 — 부분 비움 대량 확정은 통과, 같은 부위 새 증상)

**근본 원인**: 행별 명시 확정 원칙 위에 뒤늦게 얹힌 편의 대량 액션이 게이트 의미론(미매칭/제안/확정)을 구분하지 않는 boolean 일괄 플립으로 구현됨.

**권고**: confirm_all에서 has_content()==False 행 제외(비움 일괄은 이름 재진술 다이얼로그 경유), unconfirm_all은 confirm_destructive 경유, 두 버튼 시각·위치 분리.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(오히려 강화). UI_DESIGN_DECISIONS.md ADR-D는 일괄 수락을 명시적으로 의도하되 범위를 못박는다: "고신뢰(정확 일치) 매칭은 '일괄 수락'으로 확정 부담을 낮추고, 모호·미매칭 필드만 시끄럽게 hard-stop으로 개별 확정을 강제한다", "계보 패턴은 자동 *제안*이지 자동 *확정*이 아니므로". 현행 confirm_all은 미매칭 행까지 무조건 포함 — 버튼의 존재는 ADR 승인이나 무범위 구현은 ADR-D 자기 문장과 정면 배치. 게다가 B5 캡처의 스텝 자체 마이크로카피("모든 행을 검토해 확정해야 다음으로 진행합니다")와도 모순 — 문서·자체 카피 양쪽에서 의도된 결정이 아님이 확인됨.
- (ii) 권위 반증 — 실패. 주장 어디에도 목업 대조 없음. 근거는 ADR-D/E 조항 + 저장소 자기 규율(confirm.py:6 "여기 한 곳이 ADR-E 강화 패턴(원형: wizard _ack_partial)을 소유한다" — 파괴 확인의 단일 소유 선언) + 내부 다수 패턴(confirm_destructive 호출 지점 11곳 실측: app/job_editor/matrix/dataset_pool/nara/pipeline/run_view/template_manager/vocab×2/wizard×2 — 유독 unconfirm_all만 무가드). 목업 참조 제거 후에도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립(polish 강등 기각). 구체 워크스루: 22필드 입찰공고서에서 자동매칭이 제안 ~9~13건·미매칭 ~9~13건을 남긴 상태(B5, 확정 0/22)에서 사용자가 ADR-D가 의도한 '고신뢰 제안 일괄 수락'을 하려면 유일한 대량 어포던스가 '모두 확정'뿐 — 클릭 즉시 미매칭 전부가 '의도적 비움'(mapping_state.py:188 독스트링 의미론)으로 재해석되고 빨강 hard-stop 소멸·Next 개방. 저장 가드 emits_any_value(mapping_state.py:204-212)는 '전부 비움'만 잡아 부분 비움 대량 확정은 통과(RC-08 부분 겹침 주장 성립). 인접 동일 스타일 '모두 해제'(mapping_table.py:159-164, 같은 QHBoxLayout에 연달아 addWidget)는 최대 22행 수작업 확정을 무확인 파기. 오인+재작업+법적 문서 빈 값 위험 — 명백한 태스크 손상.
- (iv) 캡처·코드 재확인 — 성립. B5.png 직접 재열람: 좌하단 '모두 확정'·'모두 해제' 인접·동일 스타일 확인, (비움) 콤보의 빨강 행 다수·제안 노랑 행 공존, '확정 0/22', Next 비활성 — 관찰 동일. 구조적 관찰이라 offscreen 아티팩트(글꼴·안티앨리어싱) 무관. code_evidence 전건 성립: mapping_table.py:482-494 무확인 핸들러 ✓, mapping_state.py:191-197 무조건 boolean 플립 ✓, :187-189 독스트링 ✓. 미세 정정 1건은 corrected_evidence 참조(빨강 행 '15개' 수치).

**Verifier 비고**: 확정(재확인+반증 4축 통과). 심각도 재판정: high 유지가 정확. 근거 — §7 high 기준("상태 신호 오전달·부재, 확인-또는-경보의 시각적 위반")에 정합: ADR-D loud hard-stop이 1클릭으로 소멸하는 게이트 우회. critical 상향은 기각: (a) 상향 규칙은 ADR-B/E 명시 조항·조용한 상태 은폐인데 본건 1차 위반은 ADR-D이고, (b) 하류 신호가 완전히 침묵하지 않음 — 확정된 비움은 실행 화면에서 ADR-B blank 배지로 잔존 표시(원발견 스스로 이 이유로 critical 미상향 판단, 타당). (c) 사용자의 능동 클릭이 개입하므로 '조용한 추측'이 아니라 '과도하게 넓은 확정' — 은폐보다 한 단계 약함. 단 low/medium 강등도 기각: ADR-D 문서 자신이 일괄 수락의 범위를 '고신뢰 매칭만'으로 명시했으므로 취향·polish가 아닌 문서 접지 defect이며, mapping_state.py 독스트링('사람의 행별 확정')·confirm.py 단일 소유 선언·11곳 confirm_destructive 관례와의 3중 자기 모순이 문서 없이도 결함을 성립시킴. 권고(confirm_all에서 has_content()==False 행 제외 + unconfirm_all의 confirm_destructive 경유)는 기존 이음새 재사용이라 타당. related_rc RC-08 부분 겹침 관계도 코드로 확증(emits_any_value는 전부-비움만 가드). confidence 0.7→0.85 상향: 반증 4축 전패 + 코드·문서·캡처 3원 증거 일치.

**증거 정정**: observed의 "미매칭 빨강 행 15개"는 B5.png 단일 프레임에서 정확히 검증 불가 — 가시 영역 18행 중 (비움) 빨강 행 9개 + 스크롤 아래 4행 미확인(총 22행, 확정 0/22). 실제 미매칭은 9~13개 범위로 추정. 결함 성립에는 무영향(confirm_all은 개수 무관 전 행 플립). 나머지 code_evidence 라인 번호(mapping_table.py:482-494·159-164, mapping_state.py:187-197)는 전부 현행 워킹트리와 일치. 보강 증거: confirm.py:6이 ADR-E 강화 패턴의 단일 소유를 선언하고 confirm_destructive 호출 지점이 11곳인데 unconfirm_all만 미경유(내부 다수 패턴 위반의 정량 근거).

</details>

### UD-06 · 실행 화면 게이트 표현 이원화 — 필드 차단은 인라인·비활성인데 전제조건(데이터·폴더·레코드) 차단은 활성 primary + 클릭 후 모달(ADR-E가 강등한 차단 모달 재유입, 초기 상태는 전면 침묵)

**높음/defect** · **확정** · **신뢰도 0.85** · **화면 C / 렌즈 L3·L4** · **시나리오 C1 (병합 2건)**

**관찰**: C1: btn_generate 활성 primary, lbl_gate·lbl_preflight 빈 문자열, 배지 영역·레코드 리스트는 안내문 없는 공백. 클릭 시 validate_generate의 전제 4종(데이터 미선택·이어채우기 문서·저장 폴더·레코드 0건)이 모달로 차단. 대조: 미입력·드리프트 차단(C2/C3/C4)은 버튼 비활성+인라인 warn/danger 사유.

**기대**: 무데이터 스냅샷을 닫힌 인라인 게이트(GateState(False,'warn','먼저 데이터를 선택하세요'))로 바꾸고 배지·레코드 영역에 빈 상태 안내문 렌더. 모달은 danger급 예외만 유지.

**사용자 영향**: 신규 사용자가 활성으로 보이는 주 행동 버튼을 눌러 차단 모달을 반복 경험(습관화로 무력화되는 ADR-E 강등 패턴 재유입), 화면만 봐서는 실행 선행 조건 학습 불가 — '버튼 비활성=사유 인라인'이라는 화면 자체 게이트 문법 신뢰 붕괴.

**디자인 근거**:

- ADR-E 차단 모달 강등 — 게이트는 상시 인라인
- 내부 다수 패턴 자기 모순 — 같은 화면에 차단 표현 두 언어
- ADR-B 관통 원리 '빈 공간으로 보이면 안 됨'(배지 패널·게이트 라벨 통째 공백)
- 확인-또는-경보 시각형 — 생성 불가 상태가 '가능'으로 보임

**코드 증거**:

- src/hwpxfiller/gui/run_state.py:319-323 (datasource None이면 GateState(True,'','') — 주석으로 의도 명시)
- src/hwpxfiller/gui/run_state.py:435-461 (validate_generate 전제 4종 GateError)
- src/hwpxfiller/gui/run_view.py:406-416 (GateError를 모달로 표출)
- src/hwpxfiller/gui/run_view.py:392 (필드 게이트는 비활성+인라인 — 대조)

**관련 RC**:

- RC-23 부분 겹침(게이트 단일 스냅샷이 필드 상태만 흡수, 실행 전제조건은 모달 경로 잔존)

**근본 원인**: RC-23의 GateState 단일 스냅샷 커버리지가 부분적 — 전제조건 검증(validate_generate)이 '기존 동작 보존' 주석과 함께 클릭 후 모달 경로로 남음.

**권고**: validate_generate의 warn급 전제 4종을 _compose_gate로 흡수해 버튼 비활성+인라인 사유로 통일, 배지·레코드 영역에 빈 상태 안내문 추가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md ADR-E는 차단 모달을 강등하고 상시 인라인을 명령하며, 전제조건(데이터·폴더·레코드)을 모달로 표출하라는 결정은 ADR·HANDOFF 어디에도 없음. '기존 동작 보존'은 run_state.py:319-320 코드 docstring일 뿐 설계 결정이 아님. 단 뉘앙스: ADR-E가 강등한 것은 '빈칸 N필드' 모달이고 전제조건 모달은 강등된 적 없이 잔존한 경로 — 제목의 '재유입'은 수사적 과장(원발견 root_cause 자체는 '잔존'으로 정확).
- (ii) 권위 반증 — 실패. 근거가 내부 자기모순(같은 화면 C3/C4는 비활성+인라인 warn/danger, 전제조건은 활성 primary+모달)·ADR-E·확인-또는-경보 시각형으로 구성되며 목업 대조 의존 전무. 목업 참조 제거해도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립(polish 강등 불가). validate_generate(run_state.py:436)가 '첫 차단 사유만 반환'하므로 다중 전제 미충족 사용자는 클릭→모달을 직렬 반복하며 조건을 하나씩 학습. 완화 요인 확인: 저장 폴더 프리필(run_view.py:168-169)·레코드 전체선택 기본이라 통상 모달 1회로 수렴 — 그러나 화면 자체 게이트 문법(비활성=차단) 하에서 활성 primary가 '생성 가능'을 오전달하는 상태 신호 위반은 빈도와 무관하게 성립. §7 high 예시 '게이트 차단 사유 비가시'에 직접 부합.
- (iv) 캡처 재확인 — 성립. C1.png 직접 열람: 파란 활성 primary '문서 생성'+게이트 라벨 공백+배지 0개+레코드 리스트 공백('선택 0/0'). C3.png 대조: 회색 비활성 버튼+인라인 warn '미입력 2필드를 확인해야…: 추정가격, 담당자'. 활성/비활성·채움색은 구조적 상태라 offscreen 아티팩트 아님. code_evidence 4건 전부 현행 코드에서 성립(미세 정정은 corrected_evidence).
- (추가) 심각도 재판정 — base medium(태스크 마찰·게이트 어휘 이중화) → §7 상향 규칙(조용히 안 보이는 상태 + ADR-E 명시 조항)으로 high 확정, §7 high 행 예시에도 독립 부합. critical 불가: 모달이 하드 차단하므로 법적 문서 데이터 오류·손실 오도 없음.
- (추가) 스코프 반증 시도 — 실패. 권고 착지점이 링1(run_state.py)이나, 결함 자체는 링2 표면(C 화면의 상태 표현)에서 관찰되는 L3/L4 결함이고 이 라운드는 보고 전용이라 수리 위치는 성립 여부와 무관.

**Verifier 비고**: 확정(재확인+반증 통과). 핵심 성립 구조: RunViewModel.refresh(run_state.py:322-323)가 datasource None에서 GateState(True,'','')를 반환 → _apply_gate(run_view.py:392)가 btn_generate를 활성으로 렌더 + lbl_gate 공백 → 실제 차단은 _on_generate(run_view.py:406-416)의 QMessageBox 경로에서만 발생. 같은 화면의 미입력·드리프트 차단(C3/C4)은 비활성+인라인 warn/danger — 한 화면에 게이트 언어 두 개 공존은 §7 성립요건 ③(내부 다수 패턴 위반) 단독으로도 결함 성립. RC-23 부분 겹침(단일 스냅샷이 필드 상태만 흡수) 연결 타당 — §9 규칙 2(부분 겹침 → 신규 UD + related_rc). 신뢰도 0.75→0.85 상향: 관찰·코드·대조 캡처 전부 독립 재확인됨. 편집자 참고: 제목의 'ADR-E가 강등한 차단 모달 재유입'은 '강등이 커버하지 못한 잔존 모달 경로'로 표현 교정 권장(사실관계는 root_cause가 이미 정확).

**증거 정정**: 1) run_state.py validate_generate 범위는 435-462(반환문 462, 원발견 435-461은 1줄 미달 — 미세). 2) '배지 영역 통째 공백·전면 침묵'은 부정확: 게이트 박스에 정적 muted 안내문 존재(run_view.py:145-147 "필드 상태를 확인하세요. 미입력 필드는 직접 확인해야 문서를 생성할 수 있습니다") — 단 이 문구는 표시되지도 않은 필드 상태를 확인하라고 지시하고 '데이터 선택'은 언급하지 않아 오도를 오히려 강화(관찰 정정이지 반증 아님). 레코드 영역도 '선택 0/0' 카운트는 존재. 3) design_basis 중 ADR-B 인용은 약함: ADR-B는 필드 3상태 배지 규정이고 데이터 미겨눔 시 필드 상태 자체가 미계산 — 빈 상태 근거는 §4 L3 체크리스트('빈 상태 화면 전수 — 안내문+다음 행동 제안')와 내부 다수 패턴(③)이 더 정확. 4) 보강 증거: GateError dataclass 자체가 모달 계약을 명문화(run_state.py:49-54 "위젯이 message/level 로 대화상자를 띄운다") — 이원화가 우발이 아니라 타입 수준 계약으로 고착돼 있음.

</details>

### UD-07 · 템플릿 관리 결과 라벨이 심각도 불문 muted 고정 — lint 경고·실패 잔존 문구가 화면 최저 시각 위계의 회색으로 렌더(타 4개 화면은 전부 성과별 level 마킹)

**높음/defect** · **확정** · **신뢰도 0.85** · **화면 F / 렌즈 L1·L3** · **시나리오 F3 (병합 2건)**

**관찰**: F3: '[경고] 미치환 토큰(fieldize 가능): {{미컴파일필드}}'가 800px 창 최하단 muted 소형 텍스트, 대상 카드와 ~500px 분리. 실패 시에도 같은 muted 라벨에 '실패: …' 잔존(모달은 일회성). 대조: run_view·matrix_view·batch_run·nara_view는 결과 라벨을 warn/ok/danger로 마킹.

**기대**: lint 경고 포함 시 level=warn, 실패 danger, 정상 muted/ok — VM이 이미 심각도를 알고 있으므로(_SEVERITY_KO) 레벨 파생을 링1에 두고 위젯이 마킹.

**사용자 영향**: 미치환 토큰이 남은 템플릿의 위생 경고를 지나쳐 작업을 만들면 법적 문서에 {{토큰}} 잔존 실수로 직결. 실패 흔적이 '조용한 회색 메모'로 읽힘 — 확인-또는-경보 시각 위반(상향 적용: medium→high).

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — 결과 라벨 보유 4개 화면 전부 성과별 level, 템플릿 관리만 muted 고정
- style.py:20-21 색 의미 계약(WARN=경고·MUTED=부차) 위반
- 상향 규칙 — 경고·실패의 조용한 부차화

**코드 증거**:

- src/hwpxfiller/gui/template_manager.py:134-137 (muted 고정, level 재마킹 없음)
- src/hwpxfiller/gui/template_manager.py:221-222 (실패 잔존도 muted)
- src/hwpxfiller/gui/run_view.py:485-507 · batch_run.py:194 (대조 패턴)

**관련 RC**:

- RC-14 부분 겹침(문구 성형·스테일 무효화는 착지 — 심각도 시각 채널 부재가 신규 증상)

**근본 원인**: RC-14 착지가 결과 문구의 내용만 링1로 성형하고 심각도 레벨을 seam에 포함하지 않아 위젯이 생성 시점 muted를 영구 유지.

**권고**: format_* 결과를 (text, level) 쌍으로 확장하고 위젯이 mark(lbl_result,'level',…) 반영.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 어디에도 결과 라벨을 muted로 두기로 한 결정 없음. 오히려 반대 방향 규범만 존재: HANDOFF §6 '누락은 시끄럽게', template_status.py:12-14 'PARTIAL을 시끄럽게 구분', style.py:113-114 RC-29 '같은 상태에 같은 심각도 신호'. 결정적으로 template_manager.py:207-213 자기 docstring이 '실패는 모달 + 실패:… 라벨로 시끄럽게 남긴다(확인-또는-경보)'라고 선언하는데 그 라벨이 muted — 코드의 명시 의도가 시각 채널에서 자기모순. 의도 반증이 기각은커녕 발견을 강화.
- (ii) 권위 반증 — 실패. design_basis는 내부 다수 패턴(run_view.py:485/491/507, batch_run.py:194, nara_view.py:281/291/308/324/388, matrix_view.py:312/318 전부 level 재마킹 실측 확인) + style.py:20-21 색 의미 계약(WARN=비차단 경고·MUTED=부차) + 상향 규칙에만 접지. 목업 참조 전무 — 목업 제거해도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립하나 원발견의 impact 경로 일부 과장. 과장분: '작업을 만들면 법적 문서에 {{토큰}} 잔존 직결'은 약함 — stray/skip 토큰은 state를 PARTIAL로 만들고(template_status.py:176-178) PARTIAL 카드엔 [작업 만들기]가 아예 없으며 위저드 B3 하드게이트(ack 재진술)가 하류에서 재차단. 그러나 polish 강등은 불가: ① 실패 잔존 기록이 muted — batch_run.py:191-192가 명시하듯 라벨의 존재 이유가 '모달 닫는 순간 실패 증거 증발' 방지인데, 그 잔존 증거가 카드 메타데이터와 동일한 부차 회색이라 중립 메모로 오독됨(§7 high '에러 조용히 지나감'의 시각형). ② lint 경고는 모달조차 없어 muted 라벨이 유일 채널 — F3 실측에서 경고가 화면 최하단 회색으로 카드 메타라인과 시각적으로 무구별. 구체 태스크(PARTIAL 템플릿 [검토] 클릭 → 경고 확인)에서 심각도 신호 전달 실패 = 실마찰.
- (iv) 캡처 재확인 — 성립. F3.png 직접 개봉: '검토 결과 — 부분_계약서.hwpx: [경고] 미치환 토큰(fieldize 가능): {{미컴파일필드}}'가 800px 창 최하단(y≈771) muted 소형 텍스트로 렌더, 대상 카드(y≈59)와 ~700px 분리(원발견 ~500px는 과소 — 방향 동일). 한글 정상 렌더(tofu 아님), muted 색은 코드 결정적 프로퍼티(template_manager.py:136)라 offscreen 아티팩트 불가 — investigation_needed 불필요. code_evidence 전건 개봉 검증: template_manager.py:134-137 ✓ (mark muted 후 재마킹 없음), :215-222 ✓ (실패 문구도 동일 muted 라벨), run_view.py:485-507 ✓, batch_run.py:194 ✓. VM 심각도 보유 확인: template_manager_state.py:37 _SEVERITY_KO, :291-301 format_lint_result가 심각도를 텍스트로만 방출.

**Verifier 비고**: 확정(재확인+반증 통과). 반증 4축 전부 발견을 못 꺾음 — 축(i)은 오히려 강화(RC-14 착지 주석과 docstring이 '시끄럽게'를 선언하나 시각 채널이 muted로 자기모순). 근본 원인 진단 정확: format_* seam이 text만 반환하고 level을 미포함(template_manager_state.py:287-318), 위젯은 생성 시 muted를 영구 유지(template_manager.py:136). 권고(format_* → (text, level) 쌍)도 링 계약과 정합 — 단 실패 danger는 VM format이 아니라 _run_action 예외 경로에서 mark하면 됨. 심각도 high 유지: §7 표의 high 행('상태 신호 오전달·부재 — 에러 조용히 지나감')에 직접 해당 + 상향 규칙 이중 근거. user_impact 문구는 corrected_evidence ④대로 재접지 후 원장 박제 권장. confidence 0.85 (원발견 0.8에서 상향 — 캡처·코드 전건 실측 재확인, 유일 감점은 impact 경로 과장과 dataset_pool 제5 표면의 한정 필요).

**증거 정정**: ① '결과 라벨 보유 타 4개 화면 전부 level 마킹, 템플릿 관리만 muted 고정' — 4개 화면(run/matrix/batch/nara)의 level 마킹은 정확하나, dataset_pool_panel.py:127-129도 lbl_result를 muted 고정하는 제5의 표면(단, 그 라벨은 '등록 완료: …' 성공 문구만 실어 심각도 불일치가 현재 발현 안 함 — '템플릿 관리만'은 '심각도 정보를 싣는 결과 라벨 중 유일'로 한정해야 정확). ② F3 실측 분리 거리 ~500px → ~700px(카드 y≈59, 라벨 y≈771). ③ _SEVERITY_KO는 error→오류 포함하나 core lint는 warning|info만 방출(lint.py:52) — 실패 danger 판정 근거는 lint 심각도가 아니라 _run_action 예외 경로(template_manager.py:218-222)로 잡아야 정확. ④ user_impact의 '법적 문서 {{토큰}} 잔존 직결'은 과장 — stray 토큰은 PARTIAL 상태를 강제해(template_status.py:176-178) [작업 만들기] 비노출 + 위저드 B3 하드게이트가 하류 차단. high 유지 근거는 이 경로가 아니라 §7 기준 '에러 조용히 지나감'(실패 잔존 기록의 muted화 + 경고 유일 채널의 무심각도) + 상향 규칙('조용한 부차화') + 코드 자기 docstring('시끄럽게 남긴다', template_manager.py:207-213)과의 시각 자기모순.

</details>

### UD-08 · 데이터 스텝(ADR-J 선택화) 전이 설계 미완 — 빈 데이터 '진행할 수 없습니다' 문구 vs 활성 Next 모순, 소스 라디오 토글은 로드된 파일·나라 스냅샷을 무확인·무고지 즉시 파기

**높음/defect** · **확정** · **신뢰도 0.85** · **화면 B / 렌즈 L3·L4** · **시나리오 B4 (병합 2건)**

**관찰**: 증상 1(코드 파생, 캡처 없음): 빈 데이터 파일 선택 시 '빈 데이터로는 진행할 수 없습니다' 표시 + isComplete()=True로 Next 활성, ed_path는 검사 전 갱신되어 새 경로 표시 아래 옛 세션 잔존. 증상 2: 라디오 전환(_on_source_toggle)이 즉시 reset_data_session — 취득해 둔 나라장터 스냅샷(네트워크 왕복 산출물)이 탐색적 클릭 한 번에 조용히 소실, 복귀 후 빈 경로칸으로만 발견.

**기대**: 빈 파일/실패 시 문구를 선택-스텝 사실에 맞게 교체하고 뷰·세션 정렬(reset 호출), 이전 선택 존재 시 소스 전환은 확인 경유 또는 warn 재진술('이전 데이터 선택이 지워졌습니다').

**사용자 영향**: 화면은 '진행 불가'인데 Next는 눌리는 모순으로 게이트 신뢰 붕괴 + 재취득(다이얼로그+네트워크) 강요 — 조용한 파기와 조용한 잔존이 같은 스텝에 공존.

**디자인 근거**:

- 확인-또는-경보 — 파기 전이는 확정요구 또는 시끄러운 표시 둘뿐
- ADR-J 강등 이후 문구·실패 경로 미갱신
- 내부 패턴 — 사용자 산출물 파기는 confirm_destructive 경유가 11곳 관례, 세션 파기만 무확인; RC-23형 모순 신호

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:426-432 (검사 전 ed_path 갱신 + 모순 문구)
- src/hwpxfiller/gui/wizard.py:443-447 (isComplete 무조건 True)
- src/hwpxfiller/gui/wizard.py:335-358 (_on_source_toggle 즉시 reset, 확인·고지 없음)

**관련 RC**:

- RC-09 부분 겹침(스테일 잔존 수리가 '조용한 파기'라는 반대 증상을 남김 + 실패 경로 잔존)
- RC-23 부분 겹침(문구-게이트 모순 신호)

**근본 원인**: ADR-J 강등·RC-09 원자 리셋이 각각 좁게 착지하며 데이터 스텝 전이의 확인/고지/정리 설계가 미완으로 남음.

**권고**: 빈 파일/실패 시 reset_data_session+문구 교체, 전환 전 확인 또는 전환 후 warn 재진술. 시나리오 레지스트리에 '빈 데이터 선택' 상태 추가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md ADR-J는 데이터 스텝을 '선택적 미리보기로 강등, 필수 아님'으로 명시 착지(§J 결정 1)했고, DataPage 자신의 제목·부제(wizard.py:281-285 '2단계 — 데이터 선택 (선택)', '선택 단계입니다 — …건너뛰세요')도 같은 사실을 말한다 — 즉 '빈 데이터로는 진행할 수 없습니다'(wizard.py:429)는 같은 페이지 안에서 자기 부제와 모순되는 미갱신 문구다(문서가 이슈를 반박하지 않고 오히려 지지). 증상 2의 원자 리셋 자체는 RC-09 착지 권고('_on_source_toggle에서 세션 속성도 원자 초기화(reset_data_session 메서드로 집약)', REVIEW_ROUND1_FINDINGS.md RC-09 권고)가 결정한 형태라 '리셋한다'는 사실은 의도된 수리다 — 그러나 그 권고는 파기의 원자성만 결정했지 무확인·무고지는 결정하지 않았고, 확인-또는-경보 원칙과 confirm_destructive 12개 호출처 관례가 커뮤니케이션 층에 그대로 적용된다. 부분 완화일 뿐 기각 불가.
- (ii) 권위 반증 — 실패(주장 성립). 이슈는 목업 대조에 전혀 기대지 않는다 — 근거가 코드 SoT 문구(429행) vs 코드 게이트(isComplete 무조건 True, 443-447행)의 자기 모순, 같은 페이지 부제와의 자기 모순, 내부 다수 패턴(confirm_destructive 12곳) 위반이다. 목업 참조를 제거해도 전부 그대로 선다. UI_CONTRACT '문구=코드 SoT'상 오히려 코드 문구끼리의 모순이라 가장 강한 형태의 근거.
- (iii) 태스크 마찰 입증 — 성공(polish 강등 불가). 워크스루 (a): B4 상태(조달_한글.csv 로드, 22컬럼 3건)에서 '나라장터' 라디오를 탐색적으로 1클릭 → 런타임 실측에서 세션·경로칸·요약 즉시 전소, confirm_destructive 호출 0회, 화면 고지 텍스트 0, 라디오 복귀해도 미복원 — 파일 재탐색(엑셀) 또는 다이얼로그+네트워크 재취득(나라) 재작업 강요. (b): 유효 파일 로드 후 빈 CSV 선택 → 화면은 '진행할 수 없습니다'인데 Next 활성 — 게이트 문구를 믿으면 오도, 누르면 새 경로(empty.csv) 표시 아래 옛 파일(good.csv) 데이터로 매핑 미리보기가 구동되는 오인. 둘 다 구체 마찰(재작업·오인)이라 polish가 아니다.
- (iv) 캡처 재확인 — 통과(강등 불요). bank/B4.png 직접 열어 확인: 스텝2 '(선택)' 제목·부제, 라디오 2종, 조달_한글.csv 경로, '컬럼 22개, 레코드 3건 로드.', Next 활성 — INDEX B4와 동일, 한글 정상 렌더(tofu 아님). 두 증상 상태는 레지스트리에 없어 캡처 부재이나(원발견도 '코드 파생, 캡처 없음' 자진 표기), 주장이 픽셀이 아니라 문구·게이트 로직이라 offscreen 아티팩트 무관 — 독립 헤드리스 런타임 재현으로 대체 검증했고 전건 재현됨: [빈 파일] ed_path=empty.csv로 갱신, summary='…빈 데이터로는 진행할 수 없습니다…', isComplete()=True, 세션 data_path=good.csv·records=1·source_fields 잔존(뷰↔세션 발산 실증); [토글] reset_data_session 즉시 발동, 확인 0회·고지 0, 복귀 후 미복원. code_evidence 4곳 전건 현행 소스에서 성립(426 조기 setText, 427-432 모순 문구, 443-447 무조건 True, 335-341+343-358 무확인 리셋).

**Verifier 비고**: 판정: 확정(재현+반증 통과). 심각도는 원발견 medium → high로 1단계 상향 — 근거: §7 상향 규칙('조용한 상태 은폐'와 확인-또는-경보의 시각적 위반은 1단계 상향)이 두 증상 모두에 정면 적용된다. 증상 1은 §7 high 예시 '스테일 상태 잔존 표시'·'게이트 차단 사유 오전달' 그 자체이고(화면 문구는 차단을 주장, 게이트는 통과, 세션은 화면과 다른 옛 데이터 — RC-09가 high로 판정된 것과 동일한 '조용한 스테일' 패턴의 실패-경로 잔존), 증상 2는 확인-또는-경보 원칙상 파기 전이가 확정요구도 시끄러운 표시도 없이 발생(고지 텍스트 0 실측). critical은 아님 — Job은 데이터를 저장하지 않고 실행 데이터는 실행 시점에 재선택되므로 최종 산출 문서의 데이터 오류로 직결되지는 않는다(피해 상한 = 매핑 저작 오인 + 재취득 재작업). related_rc 연결(RC-09 부분 겹침·RC-23 모순 신호 유비)은 §9 규칙 2(같은 부위, 새 증상 → 신규 UD + related_rc)에 부합. 권고안 중 '전환 전 확인 또는 전환 후 warn 재진술'은 ADR-E 모달 강등과 충돌하지 않음(비차단 warn 재진술 경로가 존재). 시나리오 레지스트리에 '빈 데이터 선택'·'토글 직후' 상태 추가 권고 타당. 재현 스크립트: 스크래치패드 ui-review/verify_ud_data_step.py.

**증거 정정**: 미세 정정 3건: (1) confirm_destructive 관례는 11곳이 아니라 12개 호출처(app.py:233, dataset_pool_panel.py:154, job_editor.py:116, pipeline_builder.py:278, matrix_view.py:276, nara_view.py:235, run_view.py:440, template_manager.py:237, vocab_workbench.py:145·155, wizard.py:205·762). (2) 인용 범위 wizard.py:335-358 중 _on_source_toggle 본체는 335-341이고 343-358은 reset_data_session — 범위는 유효하나 심볼 분리 명기 필요. (3) '실패 경로에서 뷰·세션이 어긋난다'는 빈 데이터 분기(427-433)에만 성립 — 예외 분기(420-424)는 ed_path·세션 모두 옛 값으로 서로 일관(요약만 소거되는 사소한 고지 공백일 뿐 발산 아님). 추가 실측: 빈 파일 선택 시 세션에 옛 파일의 source_fields까지 잔존해 매핑 캐시 키(data_path)가 불변이므로 매핑 스텝이 옛 데이터 미리보기를 그대로 구동함을 런타임으로 확인.

</details>

### UD-09 · 나라장터 대화상자 게이트의 잠금 사유 무발화 — 초기 상태에서 OK 비활성·다시 시도·중지의 이유를 화면 어디도 말하지 않음(사유는 사용자가 행동한 뒤에만 출현)

**높음/defect** · **확정** · **신뢰도 0.82** · **화면 D / 렌즈 L3·L4** · **시나리오 D3 (병합 2건)**

**관찰**: D3: OK 비활성 + lbl_result 빈 문자열, 다시 시도·중지도 취득 전부터 비활성 상시 노출·사유 전달 수단 없음. 대조: 편집 무효화는 '입력이 변경됨 — 다시 가져오세요' 발화(nara_view.py:325), 키 그룹 비활성은 '상태: 미등록' 라벨이 사유 전달.

**기대**: lbl_result 초기값(muted)으로 게이트 규칙 상시 표기('기간을 정해 가져오기를 실행하면 확인이 열립니다') + OK/다시 시도 비활성 툴팁(RC-36 툴팁 착지 패턴 재사용).

**사용자 영향**: 풀 등록 목적으로 연 사용자가 키 등록·기간 설정 후 죽은 비활성 확인 버튼을 만나 이유를 추측 — '취득이 등록의 전제'라는 계약이 화면에 없어 시행착오 마찰. 게이트 차단 사유 비가시는 §7 high 명시 예시.

**디자인 근거**:

- §7 high 예시 '게이트 차단 사유 비가시' + 확인-또는-경보의 시각형(조용히 안 보이는 상태)
- 내부 패턴 자기 모순 — 같은 대화상자의 편집 무효화·키 그룹은 사유 발화, 초기 잠금만 무발화
- ADR-E 게이트 사유 가시성

**코드 증거**:

- src/hwpxfiller/gui/nara_view.py:79 (무언 잠금)
- src/hwpxfiller/gui/nara_view.py:70-72 (lbl_result 초기 빈 문자열)
- src/hwpxfiller/gui/nara_view.py:193-199 (retry/stop 툴팁 부재)
- src/hwpxfiller/gui/nara_view.py:324-325 · 211-218 (대조 패턴)

**관련 RC**:

- RC-13 부분 겹침(게이트 무효화 로직은 착지 — '잠긴 이유를 언제 말할지'가 사후 이벤트에만 배선된 신규 증상)

**근본 원인**: RC-12/13 착지가 게이트의 정확성(스테일 방지)에 집중하고 게이트의 가시성(초기 사유 안내)은 설계 범위 밖에 남김.

**권고**: lbl_result 초기 텍스트로 게이트 규칙 상시 안내 + 비활성 버튼 툴팁 부여, 취득 성공 시 요약으로 교체.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 어디에도 '초기 잠금 무발화'를 의도한 결정 없음(HANDOFF는 이 대화상자 스캐폴드 자체를 다루지 않음). 게이트 존재는 코드 docstring(nara_view.py:48)만의 결정이고 침묵은 어떤 문서도 결정한 바 없음. 단 원발견의 'ADR-E' 인용은 과장 — ADR-E 문면은 필드 누락/빈칸 배지 영역. 제거해도 §7 high 문면 예시('게이트 차단 사유 비가시') + §2 저장소 자기규율(확인-또는-경보의 시각형) + 내부 다수 패턴 위반(성립요건 ①③)으로 자립.
- (ii) 권위 반증 — 실패. 목업 참조 전무: 캡처(D3) + 코드 + 같은 대화상자 내부 자기모순(lbl_status '상태: 미등록'은 사유 발화, :325 편집 무효화도 발화, 초기 잠금만 무발화)이 근거. 목업을 제거해도 온전히 성립.
- (iii) 태스크 마찰 입증 — 성공(polish 강등 불가). 풀 등록 경로(dataset_pool_panel.py:204-215)에서 취득 데이터는 버려지고 쿼리 참조만 저장되므로(:207-208 docstring) '취득이 등록의 전제'는 반직관적 계약인데 화면 어디에도 없고 코드 주석에만 존재. 최강 반론 '폼 유효 전 OK 비활성은 통상 패턴'도 기각 — 이 폼은 기간·건수·페이지가 전부 기본값으로 채워져 유효해 보이는데 OK만 죽어 있어 가리킬 무효 필드가 없음. primary 마크된 가져오기(:191)는 위저드 취득 경로의 완화책일 뿐 잠금 사유를 설명하지 않음.
- (iv) 캡처 재확인 — 동일 관찰. D3.png 직접 열람: OK 회색, 다시 시도·중지 회색으로 취득 전부터 노출, lbl_result 영역 공백, 키 그룹 '상태: 미등록' 발화 대조 확인. 비활성 상태·빈 라벨은 구조 관찰이라 offscreen 글꼴/AA 아티팩트 여지 없음 — investigation_needed 강등 사유 부재. 인용 라인 전건 성립(:79, :70-72, :193-199, :324-325, :211-218), 파일 전체에 setToolTip 0건 재확인.

**Verifier 비고**: 확정(재확인+반증 통과). 심각도 high 유지 — §7 표의 high 예시 문면('게이트 차단 사유 비가시')과 직접 일치하고, 상향 규칙(조용히 안 보이는 상태)은 이미 high에 흡수되며 critical 요건(법적 문서 데이터 오류·손실 오도)은 불충족. medium 강등도 불가 — 사유 전달 수단이 라벨·툴팁·인접 텍스트 전무(파일 전체 setToolTip 0건)이고, 폼이 유효해 보이는 상태에서 OK만 죽어 있어 사용자가 가리킬 무효 지점이 없음. related_rc(RC-13 부분 겹침) 판정 타당: RC-13(b676d6b 착지)은 게이트 정확성이고 본 건은 게이트 가시성 — §9 규칙 2(부분 겹침, 신규 UD + related_rc) 해당. 권고안(lbl_result 초기 muted 안내 + 비활성 툴팁, RC-36 패턴 재사용)은 원장 RC-36(U11 979ccc0 착지) 대조로 실재 패턴임을 확인. 원발견 confidence 0.6 → 0.82 상향: 4축 전부 반증 실패 + 풀 등록 경로에서 마찰이 원발견 기술보다 강함(취득 데이터 폐기형 등록이라 취득 전제가 더 반직관적).

**증거 정정**: design_basis 정정: 'ADR-E 게이트 사유 가시성' 인용은 과장(ADR-E 문면은 필드 누락/빈칸 인라인 배지·최종 게이트 재진술 영역) — §7 high 문면 예시 '게이트 차단 사유 비가시' + §2 저장소 자기규율(확인-또는-경보의 시각형: 조용히 안 보이는 상태=위반) + 내부 다수 패턴 위반(같은 대화상자의 lbl_status·:325 발화 vs 초기 잠금 무발화)으로 교체 권고. 증거 보강: nara_view.py:342 (_set_busy가 idle 복원 시마다 last_result 기준으로 OK를 무언 재잠금 — 침묵이 초기화 1회가 아니라 시스템적), nara_view.py:279 (_retry_available은 첫 취득 후에만 True — '다시 시도'는 열림 직후부터 죽은 채 노출 확인), dataset_pool_panel.py:204-215·:207-208 ('취득=등록의 전제' 계약이 코드 docstring에만 존재하는 직접 증거, user_impact의 풀 등록 시나리오 실증). 세부: :193-199 범위는 retry :193-195 / stop :197-199로 분리 표기가 정확.

</details>

### UD-10 · 결과 라벨의 수명주기가 서술 대상의 변경 이벤트와 미결합 — 실행 화면은 데이터 재겨눔 후 이전 '완료' 요약·진행바 잔존, 데이터 풀은 삭제 후에도 '등록 완료: X' 잔존 (RC-14 계열 새 표면)

**높음/investigation_needed** · **확정** · **신뢰도 0.60** · **화면 C·D / 렌즈 L3** · **시나리오 C7·D9 (병합 2건)**

**관찰**: 코드 확정: (C) _after_data_loaded가 lbl_result·progress 미초기화 — 완료 후 새 데이터 겨눔 시 초록 '완료 — 성공 N/M'과 진행바 최대치가 다음 start()까지 잔존. (D) dataset_pool의 lbl_result는 등록 3경로에서만 설정되고 _dispatch(삭제·보관)·_render는 미갱신 — 'X 등록→X 삭제' 후에도 '등록 완료: X' 잔존.

**기대**: 서술 대상 변경 시 결과 표면을 비우거나 '이전 실행: …' muted로 강등 — 스테일 결과가 현재 상태처럼 보이면 안 됨(§7 high 예시이나 시각 미확증으로 medium 등재).

**사용자 영향**: 새 데이터를 겨눈 사용자가 이전 결과를 현재 상태로 오독 — 법적 문서 생성 흐름에서 결과 서사의 대상이 바뀌었는데 신호는 그대로.

**디자인 근거**:

- 확인-또는-경보 시각형 — 스테일 상태 잔존 표시
- 내부 패턴 자기 모순 — 배지·게이트는 데이터 전환 시 즉시 재계산(RC-23)되는데 결과 요약만 제외

**코드 증거**:

- src/hwpxfiller/gui/run_view.py:329-336 (_after_data_loaded 미초기화)
- src/hwpxfiller/gui/batch_run.py:150-154 (start()에서만 리셋)
- src/hwpxfiller/gui/dataset_pool_panel.py:152-163,184,201,235 (_dispatch 미갱신)

**관련 RC**:

- RC-14 부분 겹침(스테일 결과 라벨 패턴의 새 표면 2곳 — 착지 부위 회귀 아님)

**근본 원인**: 결과 라벨이 이벤트별 일회성 쓰기로만 사용되고 렌더 주기·대상 변경과 미결합.

**권고**: _after_data_loaded와 _dispatch/_render에서 결과 표면 리셋 또는 강등. 뱅크에 '완료 후 재겨눔'·'등록 후 삭제' 시나리오 추가해 시각 확증.

## 중간 (medium) — 20건

### UD-11 · QListWidget 카드 패턴의 item sizeHint 조기 박제(미폴리시 시점) — 풀·프로파일·템플릿 관리 카드의 액션 버튼이 세로 압착되어 라벨 판독 불가(보관/은퇴/삭제·마저 변환/검토 등)

**중간/defect** · **확정** · **신뢰도 0.95** · **화면 D·F / 렌즈 L1** · **시나리오 D2·D8·F1 (병합 2건)**

**관찰**: D2: 데이터 풀 카드 3장의 보관/은퇴/삭제·활성화 버튼 높이 ~13px로 글자 상단 획만 렌더(판독 불가). D8: 매핑 프로파일 편집/이름변경/삭제 동일. F1·F2·F3: 2버튼 카드([마저 변환][검토]·[미리보기][작업 만들기])만 버튼 실기하 17px vs sizeHint 25~27px(런타임 실측, 수직 결손 8~10px) — 1버튼 RAW 카드는 정상(동일 화면 내 동일 시맨틱 버튼 두 크기). 같은 환경 홈 카드(A2)는 정상 — 렌더 환경 아티팩트 아님.

**기대**: setItemWidget 이후 폴리시 완료 시점의 card.sizeHint()로 item sizeHint 재계산 — 모든 카드 액션 버튼이 온전한 높이로 라벨 판독 가능.

**사용자 영향**: 상태 전이(보관/은퇴/활성화)와 파괴 액션(삭제)이 문구로 구별되지 않아 위치 암기 클릭 강요 — 오클릭 유도. 게이트가 버튼 라벨(상태별 액션 축소)로 표현되는 F 화면에서는 핵심 상호작용 신호 자체가 판독 불가.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — home.py:383-398이 '높이 동기화는 레이아웃 후로 미룬다' 주석과 함께 지연 재동기를 이미 구현(저장소가 함정을 알고 홈에만 보정)
- 정량 임계 — 버튼 높이 13~17px vs 필요 25~28px, 라벨 식별 불가

**코드 증거**:

- src/hwpxfiller/gui/dataset_pool_panel.py:148 (setItemWidget 이전 sizeHint 박제)
- src/hwpxfiller/gui/vocab_workbench.py:125 (동일)
- src/hwpxfiller/gui/template_manager.py:179-181 (동일)
- src/hwpxfiller/gui/home.py:383-398 (QTimer.singleShot(0)+resizeEvent 재동기 — 대조 패턴)

**근본 원인**: 미폴리시 sizeHint 박제 함정의 보정(홈의 지연 재동기)이 이후 추가된 카드 리스트 3종(dataset_pool_panel·vocab_workbench·template_manager)에 공용 헬퍼로 추출되지 않고 홈 로컬 구현으로 남음.

**권고**: home.py의 지연 재동기 패턴을 공용 헬퍼로 추출해 3개 패널 적용. 스모크에 '버튼 height ≥ sizeHint height' 기하 단언 추가(헤드리스 가드 가능).

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 전문 grep: 카드 버튼 압착·컴팩트 액션을 의도한 조항 부재. HANDOFF는 오히려 '레이아웃·버튼 배치·스타일'을 '디자인이 채울 것'(§2, 73행)으로 명시 — 고정 스캐폴드가 아니어서 의도 방어 불가. 같은 카드 문법의 홈(A2)이 온전한 버튼 높이를 렌더하므로 저장소의 의도된 형태는 명백히 전체 높이.
- (ii) 권위 반증 — 실패. 주장은 목업 대조에 전혀 기대지 않음. design_basis가 ① 내부 다수 패턴 자기 모순(home.py:383-398 지연 재동기 주석 실재 확인 — '폭/높이 동기화는 레이아웃이 자리잡은 뒤로 미룬다') ② 정량 임계(라벨 판독 불가) — §7 성립 요건 ③·④ 충족. 목업 참조 제거해도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립, polish 강등 기각. 구체 태스크 '데이터셋 하나를 보관으로 전이': D2에서 [보관][은퇴][삭제] 3버튼 모두 글자 상단 획만 보여 문구 구별 불가. 가중 사실 발견: style.py에 QPushButton[level=...] 셀렉터가 없어(QLabel[level=danger]만 존재, style.py:109) dataset_pool_panel.py:68의 mark(btn,'level','danger')는 QSS no-op — 삭제 버튼이 색으로도 구별되지 않아 압착 상태에서 파괴 액션의 시각 신호가 0. F 화면은 INDEX F2 비고대로 게이트가 '상태별 액션 축소'(버튼 라벨 집합)로 표현되므로 라벨 판독 불가 = 게이트 신호 자체의 은폐 — §7 high('상태 신호 부재') 정면 해당.
- (iv) 캡처 재확인 + 코드 재확인 + 독립 런타임 재현 — 성립. PNG 직접 개봉: D2 카드 3장 전부 버튼 행이 글자 상단 획만 렌더(판독 불가), D8 2장 동일, F1은 2버튼 카드(부분·컴파일)만 압착이고 1버튼 RAW 카드([누락분 변환])는 온전 — '동일 화면 내 동일 시맨틱 버튼 두 크기' 관찰 일치. 대조군 A2(홈)는 [실행][작업 수정][삭제] 전부 판독 가능 — 동일 offscreen 환경이므로 렌더 아티팩트 반증 기각. 코드 4앵커 전건 성립: dataset_pool_panel.py:148, vocab_workbench.py:125, template_manager.py:179-181 모두 미폴리시 card.sizeHint()를 item에 박제 후 재동기 없음, home.py:383-398은 QTimer.singleShot(0)+resizeEvent 재동기 존재. 독립 재현 스크립트(scratchpad/verify_sizehint.py, offscreen)로 메커니즘 확증: 박제 시점 hint 높이 69px vs 폴리시 후 필요 104px, 버튼 실기하 18px vs sizeHint 27px — QSS padding(6px 13px, style.py:69)이 폴리시에서 반영되며 결손을 버튼 행이 흡수.

**Verifier 비고**: 확정(재확인+반증 4축 통과). 심각도 high 유지가 §7 표에 정합: F 화면에서 게이트가 버튼 라벨 집합으로 표현되는데(INDEX F2 명기) 라벨 판독 불가 = '상태 신호 부재·조용한 은폐'로 high 직접 해당(상향 규칙 불요, 이미 high). critical 상향은 부적합 — critical은 '법적 문서의 데이터 오류·손실 오도' 요건인데 본 건은 판독 마찰이며 삭제는 confirm_destructive 다이얼로그가 최종 방어(dataset_pool_panel.py:153-157). 근본 원인·권고 타당: home.py의 지연 재동기(_sync_item_widths)를 공용 헬퍼로 추출해 3패널 이식 + '버튼 height ≥ sizeHint height' 기하 스모크 단언은 offscreen에서 가드 가능함을 본 검증 스크립트가 입증. 재현물: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\3df8cf8d-7a19-4d0b-a764-aca2d990be34\scratchpad\verify_sizehint.py

**증거 정정**: ① 수치 미세 정정: 독립 재현(고립 QListWidget)에서 버튼 실기하 18px/필요 27px(결손 9px) — 원발견의 '13~17px'는 패널 루트 레이아웃 여백까지 낀 실캡처 문맥값으로 방향·규모 일치(결손 8~10px 주장과 정합). ② 표현 정정: 함정의 본질은 'setItemWidget 이전'이라는 호출 순서가 아니라 '미폴리시(QSS 미적용·미레이아웃) 시점의 sizeHint'라는 시점 — setItemWidget 직후라도 폴리시 전이면 동일 결함, 수리는 폴리시 후 재동기(홈 패턴)가 맞음. ③ 검증 중 부수 발견(별도 등재 후보): style.py에 QPushButton[level] 셀렉터 부재로 dataset_pool_panel.py:68의 삭제 버튼 danger 마킹이 QSS no-op — 압착이 수리되어도 파괴 버튼 시각 구별은 별도 결함으로 남음.

</details>

### UD-12 · 파괴(삭제) 버튼의 시각 등급이 스타일 시스템에 정의된 적 없음 — 홈 카드는 무마크로 안전 버튼과 동일, 풀·프로파일은 죽은 mark(level,'danger')(QPushButton 셀렉터 부재)

**중간/defect** · **확정** · **신뢰도 0.90** · **화면 A·D / 렌즈 L4** · **시나리오 A2·D2·D8 (병합 2건)**

**관찰**: A2/A3: 홈 카드 [삭제]가 [작업 수정]과 동일 기본 룩(무마크, 직접 인접). D2/D8: 풀·프로파일 카드 삭제 버튼에 mark(btn,'level','danger') 설정되어 있으나 QPushButton[level=…] 규칙이 저장소 전체 0건이라 렌더 무효(죽은 의도). nara 서비스키 삭제는 표식 시도조차 없음.

**기대**: style.py에 QPushButton[danger/level='danger'] 규칙(DANGER 텍스트+외곽선, hover MISSING_BG 계열) 추가 후 전 파괴 버튼 적용 — 확인 다이얼로그는 마지막 방어선이지 첫 신호가 아님.

**사용자 영향**: 빠르게 훑는 사용자의 오클릭 유도 배치(인접·동일 룩) — confirm_destructive(RC-15 착지, 행동층 정상)가 손실은 막지만 매 오클릭마다 모달 왕복 마찰. §7 critical 예시('파괴 액션이 안전 액션과 시각 동일')에 해당하나 확인 백스톱 존재로 medium 유지.

**디자인 근거**:

- style.py:20-21 'DANGER=치명' 계약 + confirm.py 파괴 액션 특수 클래스 규율의 시각적 반쪽 부재
- 내부 자기 모순 — 코드가 danger 표식을 설정하나 QSS 소비 규칙 부재(의도와 렌더의 괴리)

**코드 증거**:

- src/hwpxfiller/gui/home.py:77-83 (무마크 인접 배치)
- src/hwpxfiller/gui/dataset_pool_panel.py:68 · vocab_workbench.py:60 (죽은 표식)
- src/hwpxfiller/gui/style.py:67-73,108-110 (QPushButton 위험 변형·level 셀렉터 부재)
- src/hwpxfiller/gui/app.py:229-239 (confirm_destructive — RC-15 비회귀 확인)

**관련 RC**:

- RC-15 부분 겹침(확인 정책은 착지 유지 — 버튼 시각 등급이 신규 증상)

**근본 원인**: 파괴 액션 규율이 행동층(확인 모달)에만 구현되고 스타일 시스템에 파괴 버튼 등급이 정의된 적 없음 — QSS 무매칭 조용 통과가 죽은 표식을 은폐.

**권고**: QPushButton danger 규칙 추가 + 홈·풀·프로파일·nara 삭제 버튼 일괄 적용(셀렉터 계약 테스트와 함께).

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패: UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 전문 grep(삭제/파괴/danger/destruct) 결과 파괴 버튼을 무구별로 두기로 한 ADR 부재. ADR-I는 카드 액션(실행/편집/삭제) 존재만 규정, 시각 등급 미결정. 오히려 style.py:20-21이 DANGER=치명 계약을 선언하고 코드가 2개 표면에서 버튼에 danger 표식을 시도(죽은 마크) — 현 상태는 의도가 아니라 의도의 조용한 실패임이 코드로 입증됨.
- (ii) 권위 반증 — 실패: design_basis가 저장소 자기 규율(style.py 의미 계약)② + 내부 자기 모순(표식 설정 vs QSS 소비 규칙 부재)③으로, 목업 대조 의존 0. 목업 참조 제거해도 주장 완전 성립.
- (iii) 태스크 마찰 입증 — 성립(강등 없음): 홈 카드에서 [작업 수정] 의도 클릭 시 픽셀 동일·직접 인접(home.py:81-83 동일 foot 레이아웃)한 [삭제] 오클릭 → 확인 모달 왕복이 매회 발생. D2/D8은 편집·이름변경·삭제 3버튼 완전 동일로 사전주의(pre-attentive) 위험 신호 전무. §7 medium '위계 혼란 오클릭 유도'에 정확히 부합 — polish 아님.
- (iv) 캡처·코드 재확인 — 확정: A2.png 직접 열람 — [실행] 파랑 primary, [작업 수정]/[삭제] 동일 룩 인접 확인. D2/D8.png — 전 푸터 버튼 동일 회색, 삭제 버튼 어디에도 적색 없음. offscreen 아티팩트 배제: 동일 캡처에서 danger 배지(빨강 pill)·primary 버튼(파랑)은 정상 렌더 — QSS 프로퍼티 셀렉터 자체는 작동. 코드: QPushButton[level 저장소 전체 0건 독립 재grep 확인, dataset_pool_panel.py:66-68·vocab_workbench.py:58-60 죽은 표식 실재, style.py:108-110 QLabel 한정 규칙, app.py:229-239 confirm_destructive 비회귀, nara_view.py:150-151 무표식 확인. 테스트는 라벨 property 값만 단언 — 버튼 셀렉터 소비 여부 무가드(조용 통과 은폐 입증).
- 심각도 재판정 — medium 유지: §7 critical 예시 문구와 표면 일치하나 판정 기준은 '데이터 오류·손실 오도'이고 confirm_destructive(기본=취소·명시 동사 라벨)가 손실을 차단 → 실 영향은 태스크 마찰. 1단계 상향 규칙 부적용: 조용히 은폐된 것은 개발자 의도(죽은 QSS 마크)이지 ADR-B/E의 사용자 대면 데이터 상태가 아니며, 파괴 결과는 행동층에서 시끄럽게 고지됨.

**Verifier 비고**: 4축 전부에서 기각 실패 — 확정. 핵심은 내부 자기 모순의 정적 입증 가능성: 코드가 QPushButton에 mark(btn,'level','danger')를 설정(2개 표면)하나 style.py의 level 셀렉터는 QLabel 한정(108-110)이고 QPushButton[level는 저장소 전체 0건이라 렌더 무효 — Qt QSS의 무매칭 조용 통과가 이를 은폐하며 어떤 테스트도 셀렉터 소비를 가드하지 않는다. 캡처(A2/D2/D8)는 정적 사실을 시각 확증하고, 동일 캡처 내 danger 배지·primary 버튼의 정상 착색이 offscreen 아티팩트 가설을 배제한다. 파괴 표면 4곳 전수: 홈(무표식)·풀(죽은 표식)·프로파일(죽은 표식)·nara 키(무표식) — 전부 confirm_destructive 경유(행동층 정상, RC-15 비회귀)이나 시각 첫 신호는 0/4. 권고(QPushButton danger 규칙 + 4표면 일괄 적용 + 셀렉터 계약 테스트) 타당. related_rc의 RC-15 부분 겹침 분류 적절 — §9 규칙 2(같은 부위, 새 디자인 증상).

**증거 정정**: home.py 삭제 버튼 정확 라인은 79-80(btn_del 생성·연결), 인접 배치 증거는 81-83(foot.addWidget 3연속) — 원발견 77-83 인용은 btn_edit 포함 범위로 성립. style.py QLabel 레벨 규칙은 108-110(warn/danger/ok) 정확. 죽은 표식 정확 라인: dataset_pool_panel.py:68·vocab_workbench.py:60 성립(주변 66-72·58-64 문맥 확인). 추가 증거: nara_view.py:150-151(btn_delete '삭제' — 표식 시도조차 없음, 원발견의 무라인 언급에 라인 부여). 가드 부재 보강: tests/test_batch_run.py:153 등은 property 값만 단언하고 QSS 셀렉터 소비를 검증하지 않음 — 권고의 '셀렉터 계약 테스트' 필요성 뒷받침.

</details>

### UD-13 · 상태 배지 시각 어휘 분열 — 같은 badge_level이 홈=pill(알약)·템플릿 관리=level(맨 텍스트)·실행=fb(대형 필) 3계열로 렌더되고, QLabel[level="muted"] 셀렉터 부재로 RAW·보관 배지는 완전 무스타일(조용한 상태 소실)

**중간/defect** · **확정** · **신뢰도 0.85** · **화면 F·A·D·global / 렌즈 L1·L2·L3·L4** · **시나리오 F1·A2·D2·D8 (병합 5건)**

**관찰**: 화면별 증상: (F1) '원문' 배지가 level='muted' 무매칭으로 기본 INK 검정 평문 — 파일명과 구별 불가, '부분 변환'·'변환됨'은 배경 없는 색글자. (A2 대조) 홈은 같은 badge_level을 pill(배경+테두리+radius 9)로 정상 렌더. (D2/D8) 데이터 풀 '보관' 배지·매핑 프로파일 배지도 level=muted 무매칭 무스타일. (L2 전역) pill(r9·p1x8) vs fb(r11·p3x10) vs level(무배경) 3계열 병립 + 배지 테두리 hex(#e6c98f·#bfe0cb·#e6a49c)가 pill/fb 블록에 리터럴 중복(style.py:19 '색 리터럴 중복 금지' 위반).

**기대**: 상태 배지는 단일 컨테이너(pill 권장 — style.py:113-114 주석이 스스로 RC-29 파리티를 선언)로 수렴, level 계열에 muted 변형 보강 또는 배지 용도 폐기, 테두리색 토큰 승격, mark() 발화 어휘 전수와 QSS 셀렉터를 대조하는 계약 테스트 신설.

**사용자 영향**: RAW 템플릿·보관 데이터셋의 '할 일' 상태 신호가 본문 텍스트로 위장되어 조용히 죽고(확인-또는-경보 시각 위반 — 상향 근거), 홈에서 학습한 배지 시각 언어가 화면마다 재학습 필요.

**디자인 근거**:

- 저장소 자기 규율 — style.py:113-114 '홈 카드·템플릿 관리가 같은 상태에 같은 심각도 신호(RC-29)' 선언과 렌더의 모순, style.py:19 색 리터럴 중복 금지 위반
- 내부 다수 패턴 자기 모순 — 같은 badge_level 값이 필/평문/무스타일 3렌더
- 상향 규칙 — level='muted' 무매칭은 조용히 안 보이는 상태

**코드 증거**:

- src/hwpxfiller/gui/style.py:108-111 (QLabel[level=…] warn/danger/ok만 — muted 부재)
- src/hwpxfiller/gui/template_manager.py:59-61 (mark(badge,'level',…))
- src/hwpxfiller/gui/home.py:56-58 (mark(…,'pill',…) 대조)
- src/hwpxfiller/gui/compile_badge.py:30-39 (RAW→'muted')
- src/hwpxfiller/gui/dataset_pool_state.py:129 · vocab_workbench.py:46 (muted 발화)
- src/hwpxfiller/gui/style.py:116,120,128,142,146,150,154 (테두리 hex 중복)

**관련 RC**:

- RC-29 부분 겹침/후속(어휘 단일화는 착지·회귀 아님 — 시각 컨테이너 이원화와 셀렉터 커버리지 구멍이 신규 증상)

**근본 원인**: Qt QSS가 무매칭 셀렉터를 조용히 무시하는 특성 위에서, RC-29 착지가 어휘만 단일화하고 시각 컨테이너 선택·셀렉터 커버리지에 소유자와 가드를 두지 않음.

**권고**: template_manager 배지를 mark(badge,'pill',…)로 전환(1줄), 배지 셀렉터를 1계열로 통합+테두리색 design_tokens 승격, 발화 어휘×셀렉터 계약 테스트를 test_design_tokens 계열에 추가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(핵심부): UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 어디에도 화면별 배지 컨테이너 분기를 결정한 조항 없음. ADR-B(§B, 61-66행)는 필드 채움 3상태(fb 계열) 전용이라 이 이슈를 의도로 커버하지 못함. 오히려 style.py:113-114 주석('홈 카드·템플릿 관리가 같은 상태에 같은 심각도 신호 — RC-29')과 compile_badge.py:13-14('두 화면이 같은 상태에 다른 심각도 신호를 내지 않도록')가 저장소 스스로 선언한 파리티 의도이고, 관찰된 렌더(홈=회색 pill vs 템플릿 관리=INK 검정 평문)가 그 자기 선언을 정면 위반 — 반증 불성립. 단 'RAW=텍스트만 의도' 선해도 기각됨: muted 의도색은 회색(#7a7f87)인데 무매칭 결과는 본문 INK 검정으로 의도의 정반대. 부분 성공: fb 계열은 home.py:55 주석('실행 화면 필드 상태 셀렉터(fb)를 다른 뜻으로 재전용하지 않는다')이 의도적 분리 선언 — fb 축은 의도된 별개 시맨틱(→ corrected_evidence).
- (ii) 권위 반증 — 실패: 주장 근거가 목업 대조가 아니라 ① 내부 다수 패턴 자기모순(같은 badge_level의 이형 렌더) ② 저장소 자기 규율(style.py 주석·토큰 단일출처) ③ 뱅크 캡처. 목업 참조를 전부 제거해도 주장이 온전히 섬. UI_CONTRACT상 시각·레이아웃 권위=Qt 위젯이며 캡처가 바로 그 위젯 렌더 — 권위 규칙 충족.
- (iii) 태스크 마찰 입증 — 부분 성공(심각도 강등): 마찰 실재 — 홈에서 학습한 pill 시각 언어가 템플릿 관리에서 무효, F1 카드2는 파일명 '원문_계약서.hwpx' 직후 배지 '원문'이 동일 INK 검정 평문으로 이어져 파일명 연장으로 오독 가능(파일명에 '원문'이 실제 포함된 케이스), D2 '보관'은 인접 종류 라벨('엑셀/CSV')과 동형 평문. 그러나 '상태 신호가 조용히 죽는다'는 과장: 상태 단어 자체는 항상 표시되고, F1 RAW 카드는 primary '누름틀 변환' 게이트 버튼이, D2 보관 카드는 상이한 액션 행이 상태를 중복 발신 — 경보 소실이 아니라 스캔 비용·재학습·오독 유도 = §7 표의 medium 정의('태스크 마찰 … 배지 어휘 이중화'가 medium 예시로 명기). 상향 규칙 불발동: 상태 텍스트가 가시적이라 '조용한 은폐' 아님, ADR-B/E는 필드 채움 상태 조항이라 부적용. high→medium 강등.
- (iv) 캡처 재확인 — 실패(관찰 전건 성립): F1.png 직접 열람 — '부분 변환' 주황 평문·'변환됨' 초록 평문·RAW 배지 검정 평문, 배경/테두리/radius 전무 확인. A2.png — 같은 badge_level 어휘가 배경+테두리 pill로 정상 렌더('실행 준비' 초록 pill·'원문·누름틀 변환 필요' 회색 pill·'템플릿 없음' 적색 pill). D2.png — '활성' 초록 평문 vs '보관' 검정 평문. D8.png — '참조 작업 없음' 검정 평문 vs '작업 1개 참조' 주황 평문. offscreen 아티팩트 배제: 동일 하네스의 A2가 pill 배경을 정상 렌더하므로 배경 소실은 렌더러가 아니라 셀렉터 기인. 코드 대조 전건 성립: style.py:108-110에 QLabel[level=warn/danger/ok]만 존재하고 level=muted 부재(111행은 별개 프로퍼티 QLabel[muted="true"]), 123-126행 pill=muted는 존재; template_manager.py:60 mark(badge,'level',row.badge_level)·home.py:58 mark(…,'pill',badge_level(...))·compile_badge.py:31 RAW→'muted'·dataset_pool_state.py:36-40(_BADGE_LEVELS: ARCHIVED/RETIRED→muted)+129(기본값 muted)·vocab_workbench.py:46 전부 인용대로. 테두리 hex 중복 116(#e6c98f)/120(#bfe0cb)/128(#e6a49c)/142/146/150/154 전건 리터럴 확인.

**Verifier 비고**: 판정: 확정(confirmed), 단 심각도 high→medium 강등 + 증거 3건 정정. 결함 실체는 견고함 — (a) 같은 CompileState badge_level이 홈=pill(배경+테두리)·템플릿 관리=맨 텍스트 2계열로 렌더되어 저장소 자신의 RC-29 파리티 선언(style.py:113-114·compile_badge.py:13-14)과 모순, (b) QLabel[level=\"muted\"] 셀렉터 부재로 RAW(템플릿 관리)·보관/은퇴(데이터 풀)·무참조(어휘 워크벤치) 배지가 의도색(회색 저채도)의 정반대인 본문 INK 검정 평문으로 렌더, (c) Qt QSS의 무매칭 조용 통과 특성상 가드 없는 발화 어휘×셀렉터 매트릭스가 구조적 구멍(QPushButton level=danger 무매칭이 독립 확증). 강등 사유: §7 표가 '배지 어휘 이중화'를 medium 예시로 명기하고, 상향 규칙의 '조용한 상태 은폐'는 불성립(상태 단어는 항상 가시, 게이트/액션 버튼이 상태를 중복 발신해 경보 소실 없음), ADR-B/E는 필드 채움 상태 조항이라 본 건에 부적용. 권고(template_manager.py:60을 pill로 전환+테두리색 토큰 승격+어휘×셀렉터 계약 테스트)는 타당하며, 계약 테스트는 QPushButton[level] 무매칭 별건까지 함께 봉합함. related_rc 'RC-29 부분 겹침(회귀 아님, 신규 증상)' 판단도 타당 — RC-29는 레벨 어휘 단일화만 착지했고 시각 컨테이너·셀렉터 커버리지는 미소유 영역이었음.

**증거 정정**: 1) 제목의 '실행=fb(대형 필) 3계열' 축은 사실 오류 — fb는 badge_level/CompileState를 한 번도 받지 않음(run_view.py:364-379는 fill/blank/missing/ack 필드 채움 상태 전용, txt_view.py:170 동일). home.py:52-55 주석이 fb 재전용 금지를 명시한 의도적 별개 시맨틱. 따라서 '같은 badge_level'의 분열은 pill vs level 2계열이 정확하다. pill(r9·p1x8) vs fb(r11·p3x10)의 시각 이중화는 별개 시맨틱 간 L2 토큰 드리프트 관찰로만 유효(별도 low/polish 감). 2) style.py:19 '색 리터럴 중복 금지'는 mapping_table의 상태색 임포트에 스코프된 문장이라 BASE_QSS 내부 hex 일반 금지 근거로는 약함 — 더 강한 근거는 <gen:tokens> 단일 출처 규율(style.py:14-17)+내부 다수 패턴. 테두리 hex 7곳 중복 자체는 전건 실측 성립. 3) 'F1 원문 배지가 파일명과 구별 불가'는 과장 — 파일명은 heading(굵게 15px), 배지는 일반 굵기라 굵기 차는 있음. 정확한 표현: '본문 평문과 동형이라 파일명 후행 텍스트로 오독 가능(F1 카드2는 파일명에 원문이 포함돼 실오독 케이스)'. 4) 근본 원인(발화 어휘×셀렉터 계약 부재)의 추가 확증: dataset_pool_panel.py:68·vocab_workbench.py:60의 mark(btn,'level','danger')도 무매칭 — QSS는 QLabel[level=…]만 정의(QPushButton[level=…] 부재)해 삭제 버튼이 파괴 시각 구별을 조용히 상실(D2/D8 캡처에서 삭제 버튼이 일반 버튼과 동형임을 실측). 이는 본 이슈 스코프 밖의 잠재 별건(§7 critical 예시 '파괴 액션이 안전 액션과 시각 동일' 접점)이나 셀렉터 커버리지 가드 부재라는 동일 근본 원인의 독립 증거.

</details>

### UD-14 · 매핑 게이트 진행 카운터의 강조 역전 — 차단 중일수록 muted 회색(좌하단 구석), 해소되면 ok 초록 강조 (같은 위저드 스텝1의 warn 차단 신호와 자기 모순)

**중간/defect** · **확정** · **신뢰도 0.85** · **화면 B / 렌즈 L1·L3** · **시나리오 B5·B6·B7 (병합 2건)**

**관찰**: B5/B7(차단 중): '확정 0/22' 좌하단 muted 회색. B6(게이트 열림): '확정 22/22' ok 초록 강조. 대조: 스텝1의 동일 시맨틱(진행 차단 사유)은 lbl_warn(level=warn)으로 착색(B3).

**기대**: 미완료 시 muted 해제+level=warn(잔여 재진술 '22개 남음'), 완료 시 ok 유지 — 스텝1 warn 패턴과 시각 언어 정렬.

**사용자 영향**: 22필드 밀도에서 스크롤 밖 미확정 행이 있으면 카운터가 사실상 유일한 전체 집계인데 그것이 muted — 사용자가 '왜 못 넘어가는지'를 테이블 전수 스캔으로 찾는 마찰.

**디자인 근거**:

- ADR-D 미확정 잔존은 loud hard-stop — 차단 신호 저강조는 배치
- 내부 다수 패턴 자기 모순 — 같은 위저드 스텝1 차단=warn, 스텝3 차단 집계=muted
- style.py:20-21 MUTED=부차 계약 — 게이트 잔여는 부차가 아님

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:485-487 (생성 시 muted)
- src/hwpxfiller/gui/wizard.py:557-567 (미완=muted / 완료=ok — 역전)
- src/hwpxfiller/gui/wizard.py:83 (스텝1 warn 대조)

**근본 원인**: 카운터를 '진행 보조 정보'로 분류하고 완료 축하만 레벨 배선 — 차단 중에는 차단 사유 요약이라는 상태 의존적 위계 미반영.

**권고**: 미완료 시 mark(level='warn')+잔여 재진술, 완료 시 ok.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(이슈 생존): UI_DESIGN_DECISIONS.md ADR-D(75-84행)는 '모호·미매칭 필드만 시끄럽게 hard-stop'으로 필드 단위 신호를 규정할 뿐 집계 카운터의 시각 형태를 결정한 조항이 없고, UI_DESIGN_HANDOFF.md:81은 '명시성 게이트는 MappingPage에 그대로'라는 게이트 소재만 규정. muted 스타일이 의도된 결정이라는 근거 부재. 오히려 wizard.py:558 코드 자체 docstring이 '게이트까지 얼마나 남았는지 상시 노출'을 선언 — muted는 자기 선언 목적과도 어긋남.
- (ii) 권위 반증 — 실패(이슈 생존): 주장은 코드(wizard.py:485-486, 557-567, 83; style.py:20-21)와 캡처(B3/B5/B6/B7) + 내부 패턴 대조에만 접지. 목업 참조 0건 — 목업 제거해도 완전히 섬. 기각 불가.
- (iii) 태스크 마찰 입증 — 최강 반격 시도 후 이슈 생존: mapping_table.py:49-50의 노랑(UNCONFIRMED_BG)/빨강(UNMATCHED_BG) 행 배경이 1차 loud 신호라 카운터는 정당한 부차 정보라는 반론을 세웠으나, B7 실측상 22행 중 ~18행만 가시(스크롤바 존재) — '확정 20/22'에서 미확정 2행이 스크롤 밖이면 가시 신호는 흰 확정 행들 + 사유 없는 비활성 Next + 구석 muted 회색 카운터뿐. 카운터가 유일 집계인 바로 그 상태에서 가장 약함 = 구체 마찰(테이블 전수 재스캔). '모두 확정' 일괄 버튼은 ADR-D의 개별 검토 의도상 우회책이 못 됨. polish 강등 기각.
- (iv) 캡처 재확인 — 동일 관찰: B5.png·B7.png 좌하단 '확정 0/22' muted 회색, B6.png '확정 22/22' 초록(ok), B3.png 스텝1 차단 사유 warn 주황 텍스트 — 이슈 관찰과 전부 일치. code_evidence 3건 전부 성립(wizard.py:485-486 생성 시 muted, 557-567 _sync_progress 역전 배선, 83 스텝1 warn, style.py:20-21 MUTED=부차 계약). 회색/초록/주황 색 구별은 offscreen 가는 글꼴·안티앨리어싱 아티팩트와 무관 — investigation_needed 불요.
- 심각도 재판정 — medium 유지: §7 medium '태스크 마찰·위계 혼란' 정합. 상향 규칙 불발동 — ADR-B/E 조항 위반 아님(스텝3는 ADR-D 관할, ADR-E는 실행 뷰 인라인 배지·최종 게이트 조항)이고 상태가 '조용히 안 보임'도 아님(텍스트 자체는 상시 표시, 행 배경은 가시 범위에서 loud) — 저강조이지 은폐가 아님.

**Verifier 비고**: 확정(재확인+반증 통과). 관찰·역전 배선·자기 모순 전부 코드와 캡처 4장으로 재확증. 핵심 마찰 시나리오는 부분 확정+스크롤 아웃 상태(캡처 뱅크에 직접 캡처는 없으나 B7의 가시 행수/스크롤바 실측 + _sync_progress 배선으로 기계적 도출 — 별도 시나리오 추가 불요). 권고안(미완료 시 level=warn + 잔여 재진술, 완료 시 ok 유지)은 스텝1 warn 패턴 및 style.py 레벨 어휘와 정합적이며 신규 시각 언어 발명 없음. confidence 0.75→0.85 상향: 반증 4축 전부 통과 + code_evidence 전건 성립 + 캡처 동일 관찰. 관련 파일: C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/wizard.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/style.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/mapping_table.py.

**증거 정정**: 라인 미세 정정: 생성 시 muted는 wizard.py:485-486(485 QLabel 생성, 486 mark(muted,True)) — 원발견의 485-487은 1행 과대. _sync_progress는 557-567 정확(566 muted 토글, 567 level ok/'' 토글), 스텝1 warn은 wizard.py:83 정확. design_basis 정정: 'ADR-D 미확정 잔존은 loud hard-stop'은 과대 인용 — ADR-D 원문(docs/UI_DESIGN_DECISIONS.md:78-79)은 '모호·미매칭 필드만 시끄럽게 hard-stop'으로 필드 단위 조항이며 행 배경(mapping_table.py:49-50 UNCONFIRMED_BG/UNMATCHED_BG)+Next 비활성으로 충족됨 — 카운터에 직접 적용 불가하므로 보조 맥락으로 강등. 주 성립 근거 = §7 근거③ 내부 다수 패턴 자기 모순(같은 위저드에서 동일 시맨틱 '진행 차단 사유'를 스텝1은 level=warn(wizard.py:83, B3.png), 스텝3은 muted(wizard.py:566, B5/B7.png)로 이중 렌더 — 문서 없이도 결함 성립) + style.py:20-21 MUTED=부차 의미 계약 위반 + wizard.py:558 자기 docstring('게이트까지 얼마나 남았는지 상시 노출')과 스타일의 자기 모순.

</details>

### UD-15 · 퍼지(모호) 자동 제안과 정확 일치 제안이 테이블에서 시각 동일 — ADR-D의 2등급 분류가 hover 툴팁에만 존재

**중간/defect** · **확정** · **신뢰도 0.85** · **화면 B / 렌즈 L3** · **시나리오 B5**

**관찰**: B5: 정확 일치(입찰공고번호←bidNtceNo)와 퍼지(입찰개시일시←bidBeginDate '입찰개시일자' 등 3건)가 시각 무구별. 신뢰도는 combo.setToolTip에만.

**기대**: ADR-D 2등급(고신뢰=일괄 수락 후보 / 모호=개별 확정 강제)이 상시 시각 신호로 구별 — score<1.0 행에 인라인 '유사 N%' 배지 또는 별도 행 색.

**사용자 영향**: 퍼지 제안을 정확 일치로 믿고 확정 → 유사 이름 오바인딩 값이 법적 문서에 진입 가능. '모두 확정' 존재 하에서 모호 제안의 개별 검토를 유도할 시각 근거 부재.

**디자인 근거**:

- ADR-D 고신뢰/모호 2등급 분류가 결정 본문 — 시각 표현 부재
- 내부 패턴 — 같은 테이블이 다른 상태는 상시 색·텍스트로 구별하면서 제안 신뢰도만 hover 전용

**코드 증거**:

- src/hwpxfiller/gui/mapping_table.py:323-330 (툴팁에만)
- src/hwpxfiller/core/mapping.py:197,213 (threshold=0.6)
- src/hwpxfiller/gui/mapping_state.py:118-123 (suggestion_score 모델 존재·뷰 미사용)

**근본 원인**: ADR-D의 2등급 분류가 상호작용(개별 확정)에는 있되 시각 표현에는 배선되지 않음.

**권고**: 퍼지 제안 행에 상시 인라인 신뢰도 신호 추가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(기각 불가): UI_DESIGN_DECISIONS.md:75-86 ADR-D 결정 본문이 명시적으로 2등급을 요구 — '고신뢰(정확 일치) 매칭은 일괄 수락으로 확정 부담을 낮추고, 모호·미매칭 필드만 시끄럽게 hard-stop으로 개별 확정을 강제'(77-79행), 트레이드오프(86행)로 '2등급 분류 구현 비용'을 수용까지 함. hover 전용 툴팁은 '시끄럽게'가 아니다. UI_DESIGN_HANDOFF.md §3(79-89행)은 명시성 게이트 스캐폴드만 고정하고 'MappingPage 폴리시는 디자인이 채울 것'으로 열어둠 — 툴팁 전용이 의도된 착지라는 문서 근거 전무. REVIEW_ROUND1_FINDINGS.md에도 저신뢰 툴팁을 최종 결정으로 박제한 RC 없음(mapping_table.py:322 주석의 RC-36은 콤보 잘림 툴팁 건이며 신뢰도 경고는 '병기 유지' 언급뿐).
- (ii) 권위 반증 — 실패(기각 불가): 이슈의 근거는 ADR-D 본문 + 코드 + 캡처뿐, 목업 참조 0건. UI_CONTRACT상 시각·레이아웃 권위 = Qt 위젯이고 B5.png이 바로 Qt 위젯 grab이므로 권위 규칙 위반 없음. 목업을 제거해도 주장 전체가 그대로 선다.
- (iii) 태스크 마찰 입증 — 성립(polish 강등 불가): B5 상태에서 제안 9건 중 정확 일치 6건(입찰공고번호·수요기관·공고명·계약방법·추정가격·낙찰자결정방법)과 퍼지 3건(입찰개시일시·입찰마감일시·개찰일시 ← '~일자' alias, 유사도 약 0.83)이 공존 — 검토가 필요한 3건을 식별하려면 콤보 9개를 하나씩 hover하는 것이 유일한 채널이고, '모두 확정'(mapping_table.py:159)은 22행 전건을 1클릭 확정한다. 단 완화 요인 실측: 위저드 서브타이틀(wizard.py:457)이 '자동 제안은 초안일 뿐입니다. 모든 행을 검토해 확정해야…'를 상시 고지하고, 퍼지 행도 정확 행도 노랑 미확정(보수적 신호)으로 시작하므로 '거짓 안전' 신호 역전은 아님 — high 상향은 기각, medium(태스크 마찰) 유지.
- (iv) 캡처·코드 재확인 — 성립: B5.png 직접 열람 — 정확 일치 행과 퍼지 행이 동일 노랑 배경·동일 콤보·배지 0으로 렌더, 하단 '확정 0/22 · 제안 9 · 빈 값 3' 집계에도 신뢰도 차원 부재. 구조적 부재 주장이라 offscreen 아티팩트(글꼴·안티앨리어싱) 무관 — investigation_needed 불필요. 코드 전건 성립: mapping_table.py:61 _LOW_CONFIDENCE=1.0, :322-330 툴팁 전용 고지, :64-72 _row_brush가 confirmed/has_content만 보고 suggestion_score 무시(행 색 결정식이 점수 맹목임을 직접 확인), mapping.py:197 threshold=0.6·:213 적용, mapping_state.py:120-123 점수 산출 + :45 독스트링이 '뷰가 신뢰도 툴팁에 쓴다'로 툴팁 전용을 자인.

**Verifier 비고**: 판정: 확정(재확인+반증 통과). 반증 4축 전부 기각 실패 — ADR-D 결정 본문이 직접 근거이고 목업 무관, 태스크 마찰 구체 지목 가능, 캡처·코드 전건 재확인 성립. 심각도는 medium 유지: 상향 규칙(ADR-B/E 위반·조용한 상태 은폐 +1) 적용을 검토했으나 ADR-D는 상향 목록(B/E) 밖이고, 기본 렌더가 '노랑 미확정=검토 필요'라는 보수적 진실 신호여서 스테일·거짓 안전 류의 '조용한 은폐'와 성격이 다름 — 은폐된 것은 안전 상태가 아니라 분류(triage) 신호. §7 medium 예시('태스크 마찰·배지 어휘/신호 부재로 오클릭 유도')에 정확히 부합. 신뢰도 0.85(원발견 0.7에서 상향 — 전 증거 라인 실측 성립 + 상호작용층 부재라는 강화 증거 추가). 권고 보강: 시각 신호(score<1.0 행 인라인 '유사 N%' 배지)에 더해, ADR-D 완전 이행이면 '모두 확정'의 score-blind 동작(고신뢰만 일괄 수락으로 제한할지)도 같은 수리에서 함께 판단할 것.

**증거 정정**: 원발견의 root_cause('2등급 분류가 상호작용(개별 확정)에는 있되 시각 표현에는 미배선')는 절반만 맞음 — 상호작용층도 2등급을 구현하지 않는다: mapping_state.py:191-193 confirm_all()이 suggestion_score 무관하게 전 행 confirmed=True, mapping_table.py:482-487 '모두 확정' 버튼이 이를 그대로 호출 → ADR-D의 '모호는 개별 확정 강제'가 시각·상호작용 양층 모두 부재(발견을 강화하는 정정). 라인 미세 정정: 툴팁 블록은 322-330(주석 322-323, 조건 325), _LOW_CONFIDENCE=1.0은 61행, 행 색 결정식은 _row_brush 64-72(점수 미참조). mapping_state.py 인용은 118-123 중 점수 산출 핵심은 120-123. 완화 맥락 기록: wizard.py:457 서브타이틀이 전 제안을 초안으로 일괄 고지(단 등급 무구별이라 ADR-D 2등급 표현은 여전히 0).

</details>

### UD-16 · fb 필드 배지의 의미 축 미인코딩 — 동일 pill 시각에 정적 QLabel·클릭 필수 버튼·비활성 버튼 3종 혼재(:disabled 변형 전무), drift는 missing 색 차용으로 4번째 상태의 시각 정체성 부재

**중간/defect** · **확정** · **신뢰도 0.85** · **화면 C·E / 렌즈 L3·L4** · **시나리오 C4·C2·E3 (병합 3건)**

**관찰**: C4: 같은 빨간 missing 스타일이 클릭 버튼('● 담당자 — 미입력 확인')과 정적 라벨('⚠ 신규필드 — 매핑 재확정 필요')에 동시 사용, ack 비활성 버튼은 :disabled 변형 부재로 활성과 동일 렌더(C2/C5). 도움말·게이트 문구 어디에도 '배지를 클릭하라' 지시 없음(단서는 hover뿐). E3: txt 화면의 동일 fb=missing 시각은 정적 QLabel — 실행 화면에서 '빨간 칩=눌러서 확인'을 학습한 사용자에게 이중 의미. drift는 전용 fb 값 없이 missing 재사용(값 문제와 구조 문제의 조치가 완전히 다른데 동일 색).

**기대**: 클릭형 fb 배지에 정지 상태에서도 식별되는 컨트롤 신호(버튼 시그니처·'클릭해 확인' 문구), [fb]:disabled 변형 추가, drift 전용 fb 스타일 신설.

**사용자 영향**: 게이트 해제 방법의 발견 실패(어떤 칩을 눌러야 하는지 화면만으로 알 수 없음 — 막힘·시행착오), 비활성 ack·drift 라벨 클릭 무반응이 고장으로 오인, drift를 '클릭으로 풀리는 미입력'으로 오독.

**디자인 근거**:

- ADR-E 강제 상호작용의 유일 해제 경로 어포던스가 정적 배지와 시각 동일
- ADR-B 상태별 배지 구별 — drift만 missing 차용
- 내부 다수 패턴 자기 모순 — 동일 fb 시각에 상호작용 3종 + 트랙 간 이중 의미

**코드 증거**:

- src/hwpxfiller/gui/run_view.py:361-382 (QLabel/QPushButton/비활성 혼재, drift가 fb=missing 재사용)
- src/hwpxfiller/gui/style.py:141-161 (fb 어휘에 drift·:disabled 변형 부재, QLabel/QPushButton 동일 룩)
- src/hwpxfiller/gui/txt_view.py:169-171 (txt는 전부 정적 QLabel)

**관련 RC**:

- RC-29 부분 겹침(fb 셀렉터 어휘 재전용은 착지 — 위젯 타입·활성 상태·drift 무구별 렌더가 신규 증상)

**근본 원인**: FieldState 확장(drift·ack)과 상호작용 의미가 스타일 계층에 인코딩되지 않음 — fb는 색만 말하고 '눌 수 있는가'는 침묵.

**권고**: QPushButton[fb='missing']에 버튼 시그니처 부여 + [fb]:disabled 변형 + fb='drift' 전용 스타일 + 게이트 문구에 '배지를 클릭해 확인' 명문화.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(이슈 생존). ADR-E(UI_DESIGN_DECISIONS.md:121-143)는 '이름 재진술 + 직접 건드리는 강제 상호작용'을 결정했을 뿐 클릭형 배지가 정적 배지와 동일 시각이어도 된다는 결정은 어디에도 없음. ADR-B(:61-66)는 '3상태를 각기 다른 배지로'를 명시. 드리프트 축 확정(:396-424)은 'drift ≠ ack 대상, 계약 수리'로 의미를 명시 분리했고 run_state.py:308 주석도 'drift로 별도 표시해 오라벨 방지'라 선언하는데 style.py는 fb='drift' 없이 missing 색을 차용 — 재사용을 승인한 문서 없음. 단 부분 완화 확인: drift 칩 문구('매핑 재확정 필요')와 preflight danger 문구(run_state.py:404 '[치명] 템플릿 구조가 확정 매핑과 다릅니다')가 텍스트 채널에서는 drift를 구별해줌 — '클릭으로 풀리는 미입력으로 오독' 임팩트는 문구로 부분 완화되나 색·형태 채널의 융합은 잔존.
- (ii) 권위 반증 — 실패(이슈 생존). 주장 근거가 목업 대조가 아니라 ADR-B/E 조항 + 내부 다수 패턴 자기 모순(§7 성립요건 ①③) + 코드 실측(style.py fb 어휘). 목업 참조 제로 — 제거해도 그대로 성립. UI_CONTRACT '시각=Qt 위젯이 진실' 권위와도 정합(Qt 렌더 자체를 검증함).
- (iii) 태스크 마찰 입증 — 성립(polish 강등 불가). 구체 태스크: missing 필드가 있는 상태에서 문서 생성 시도 → 게이트 문구(run_state.py:392 '미입력 N필드를 확인해야 문서 생성이 가능합니다')와 도움말(run_view.py:146 '직접 확인해야')이 방법(칩 클릭)을 어디서도 명명하지 않고, 칩에 툴팁 없음, 유일 단서는 hover 커서(run_view.py:380) — 정지 화면만으로는 해제 경로 발견 불가, ADR-E 유일 해제 경로의 발견성 마찰 실재. 추가 마찰: 비활성 ack 버튼·비활성 drift 라벨이 QSS 특이성상 :disabled 일반 규칙(style.py:73)을 [fb] 규칙이 덮어 완전 채도로 렌더 → 클릭 무반응이 고장으로 오인 가능(네이티브 재현 캡처로 무디밍 확인). §7 표의 medium 예시('배지 어휘 이중화·위계 혼란') 정합.
- (iv) 캡처 재확인 — 관찰 성립하되 중대 단서 발견. C4.png/C2.png/E3.png 직접 개봉: 위젯 3종 혼재·drift의 missing 색 차용·ack 무디밍 모두 관찰됨. 단, 뱅크 캡처에는 하네스 아티팩트 존재 — 활성 fb='missing' 칩(C4·C2 버튼, E3 QLabel)이 radius-11 pill이 아닌 직각 사각으로 렌더되고 칩 플로우 뒤에 유색 밴드 잔존. 최소 재현(repro_fb_corners.py)을 offscreen·native windows 두 플랫폼 + 프로젝트 FlowLayout로 실행한 결과 전 칩이 동일 라운드 pill로 렌더(사각·밴드 미재현) → 사각 코너는 뱅크 하네스의 grab 타이밍/지연 삭제 아티팩트이고, 실 UI에서는 클릭 버튼·정적 라벨·비활성 칩이 동일 pill 시그니처로 렌더됨을 네이티브 플랫폼에서 독립 확증. 즉 '구별 불가' 주장은 아티팩트 낀 캡처가 아니라 네이티브 재현으로 성립 — investigation_needed 불요. 인용 code_evidence 3건(run_view.py:361-382, style.py:141-161, txt_view.py:169-171) 전건 현행 코드와 일치 확인.
- 심각도 재판정 — medium 유지(상향 불채택). 상향 규칙 검토: 상태 자체는 시끄럽게 표시되고 게이트 차단 사유(필드명)도 문구로 가시 — '조용한 상태 은폐' 아님. ADR-B 문언은 3상태(채움/빈칸/미입력) 구별을 요구하고 그 3상태 구별은 성립 — drift 4번째 상태는 원리 확장 위반이지 문언 정면 위반이 아니며, ADR-E 강제 상호작용도 존재하되 발견성이 낮은 것. §7 medium('태스크 마찰·배지 어휘 이중화') 정확 부합.

**Verifier 비고**: 확정(재확인+반증 통과). 핵심 성립 구조: (a) 스타일 어휘 실측 — style.py:141-161의 fb 어휘는 fill/blank/missing(QLabel)·missing/ack(QPushButton)뿐, fb='drift' 및 :disabled 변형 전무; (b) run_view.py:361-382 — 동일 fb 시각군에 정적 QLabel(fill/blank)·클릭 필수 QPushButton(missing)·비활성 QPushButton(ack)·비활성 QLabel(drift가 fb='missing' 차용) 4종 혼재; (c) txt_view.py:168-171 — txt 트랙은 동일 fb 어휘를 전부 정적 QLabel로 사용 → 트랙 간 이중 의미; (d) 네이티브 플랫폼 재현으로 전 칩 동일 pill 시그니처·비활성 무디밍 확증. run_state.py:308 주석('drift로 별도 표시해 오라벨 방지')과 스타일 계층의 missing 차용이 코드 내 자기 모순을 이룸 — §7 성립요건 ①(ADR-B/E)·③(내부 다수 패턴) 동시 충족. 완화 요인으로 drift·preflight의 텍스트 채널 구별이 있어 user_impact 중 'drift 오독'은 원발견 서술보다 약함(문구가 조치를 명시). 권고안 4항(버튼 시그니처·:disabled 변형·drift 전용 스타일·게이트 문구 명문화) 모두 코드 실측과 정합. RC-29 관계는 원발견대로 부분 겹침(레벨 어휘 단일화는 착지, 위젯 타입·활성 축 미인코딩은 신규 증상). 부수 관찰: 캡처 뱅크 하네스의 fb='missing' 사각 렌더 + 유색 밴드 아티팩트는 뱅크 전반 신뢰도에 영향 가능 — 다른 이슈 검증자에게 전파 권장.

**증거 정정**: 1) observed의 'ack 비활성 버튼은 :disabled 변형 부재로 활성과 동일 렌더' — 부정확: 활성 ack 버튼은 존재한 적 없음(run_view.py:373-376에서 생성 즉시 setEnabled(False)). 정확한 진술: QPushButton[fb='ack']/[fb='missing'] 규칙이 일반 QPushButton:disabled(style.py:73)를 덮고 QLabel[fb=*]에는 :disabled 변형이 없어, 비활성 ack 버튼·비활성 drift 라벨이 완전 채도의 상호작용 가능해 보이는 pill로 렌더(네이티브 재현으로 무디밍 확인). 2) 뱅크 캡처 C2/C4/E3에는 하네스 아티팩트 존재: 활성 fb='missing' 칩이 사각 코너로 렌더 + 칩 플로우 배후 유색 밴드(E3 분홍·C2/C4 크림) — offscreen/native 양 플랫폼 최소 재현(FlowLayout 포함)에서 미재현, 실 UI는 전 칩 동일 라운드 pill. 원발견의 '동일 시각' 주장은 캡처가 아닌 네이티브 재현(scratchpad ui-review/bank/_repro_windows_flow.png, repro_fb_corners.py)이 확증 근거이며, 해당 캡처 3건은 다른 발견의 픽셀 근거로 재사용 시 주의 필요(캡처 뱅크 하네스의 grab 타이밍 이슈로 별도 조사 가치). 3) style.py fb 블록은 140-161(140 주석 포함) — 인용 141-161 실질 정확. 4) 게이트 문구 원천은 run_state.py:392, 도움말은 run_view.py:146 — 둘 다 '확인해야'만 말하고 클릭 메커니즘 미명명 확인.

</details>

### UD-17 · 빈 상태 패턴(스택 교체+중앙 안내+CTA)의 미이식 — txt 트랙(홈 우측)·데이터 풀·매핑 프로파일·매트릭스 작업 목록이 안내문 없는 백지 또는 푸터 잔글씨

**중간/defect** · **확정** · **신뢰도 0.85** · **화면 A·D / 렌즈 L1·L3** · **시나리오 A1·D1 (병합 4건)**

**관찰**: 표면별 증상: (A1) 홈 우측 '즉시 기안' txt 목록이 0건 시 테두리만 있는 빈 흰 사각형 — 같은 화면 좌측 HWPX 트랙은 안내문+CTA 빈 상태 뷰. (D1) 데이터 풀은 뷰포트 대부분(~700px)이 빈 QListWidget이고 안내문은 최하단 muted 소형 텍스트, CTA 부재 — vocab_workbench 동일 구조. (코드 파생) 매트릭스 작업 0건 시 '작업 선택' 그룹이 무안내 백지(빈 상태 분기 전무).

**기대**: 전 목록 표면이 QStackedWidget 빈 상태 패턴(상태 재진술 안내문+다음 행동 CTA)으로 통일 — ADR-A(i) '빈 상태는 첫 작업 만들기 단일 CTA로 온보딩'.

**사용자 영향**: 신규 사용자가 txt 트랙 시작 방법을 화면에서 알 수 없고(투트랙 허브의 우측 절반이 고장으로 오인), 풀 첫 진입 시 거대한 공백을 로딩/고장으로 오인 — 온보딩 마찰.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — home/template_manager=스택 교체+CTA vs txt목록/pool/vocab/matrix=공백·푸터 라벨
- ADR-A(i) 빈 상태 온보딩 원리
- 확인-또는-경보의 시각형 — 0건 상태가 조용한 공백으로 렌더

**코드 증거**:

- src/hwpxfiller/gui/home.py:254-258,366 (txt_list 빈 상태 부재 vs :231-240 HWPX 스택)
- src/hwpxfiller/gui/dataset_pool_panel.py:114-125 · vocab_workbench.py:95-107 (리스트 잔존+하단 라벨)
- src/hwpxfiller/gui/matrix_view.py:203-211 (빈 목록 분기 없음)
- src/hwpxfiller/gui/template_manager.py:131,143-166 ('홈 패턴 미러' — 대조)

**관련 RC**:

- RC-14 부분 겹침(백지 빈 상태 수리가 템플릿 워크숍에만 착지 — 새 표면들 미적용)

**근본 원인**: 빈 상태 뷰가 공용 컴포넌트가 아니라 화면별 1회성 구현이라 신규 표면 추가 시 패턴이 자동 이식되지 않음.

**권고**: 빈 상태 뷰를 공용 헬퍼로 추출해 txt_list·pool·vocab·matrix에 적용(각 표면의 개념 안내 한 줄+CTA 포함).

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(부분 정정). UI_DESIGN_DECISIONS.md ADR-A(i)(155-157행)는 '최초/빈 상태는 "첫 작업 만들기" 단일 CTA로 온보딩'을 명시하나 이는 홈 Job 진입 모델 조항 — 풀·프로파일·매트릭스에 직접 확장 적용은 과대 인용이다. 그러나 어떤 ADR/HANDOFF 조항도 '푸터 잔글씨형 빈 상태'를 의도된 결정으로 승인하지 않으며, HANDOFF §2(72행)는 빈 상태를 '디자인이 채울 것'(미고정)으로 분류한다. 홈 우측 txt 트랙은 홈 화면의 일부이므로 ADR-A(i)·ADR-I(투트랙 허브) 사정권. 비홈 표면들의 성립 근거는 §7 근거 ③ '내부 다수 패턴 자기 모순'(home+template_manager=스택 교체+중앙 CTA vs pool/vocab/txt=푸터 라벨·공백)이며 이는 문서 없이도 성립 — 기각 불가.
- (ii) 권위 반증 — 실패. 주장 전체가 내부 표면 간 교차 비교 + 캡처 + 코드 구조에 접지하며 목업 참조가 전무하다. 목업을 제거해도 자기 모순 근거가 그대로 선다.
- (iii) 태스크 마찰 입증 — 성립하나 원발견보다 좁음. 풀 첫 진입: D1 실측상 뷰포트 ~700px가 테두리 있는 순백 사각형이고 안내는 최하단 muted 잔글씨 2줄 — 로딩/고장 오인 마찰 구체적. 단 (a) txt 트랙: 패널 헤더에 primary '＋ 새 기안' CTA가 상시 노출(home.py:247-248)되어 '시작 방법을 알 수 없다'는 과장 — 실제 마찰은 좌측 완성형 빈 상태와 나란한 백지 사각형이 우측 절반 고장으로 읽히는 비대칭. (b) 풀: 헤더에 primary '엑셀/CSV 등록…' 상시 존재(dataset_pool_panel.py:102-108) — 'CTA 부재'는 빈 상태 영역 한정으로만 참. (c) 매트릭스: '선택 0개' 라벨+전체선택/해제 버튼 존재(matrix_view.py:85-94)라 '무안내 백지'는 과장 — 진짜 결함은 '저장된 작업 0건'과 '선택 0건'이 시각적으로 구별 불가한 점(app.py:144-152 무가드 라우팅으로 0건 상태 도달 가능 확인). polish 강등 기각: 풀 단독으로도 첫 진입 오인 마찰이 구체적이고 캡처로 입증됨 — §7 medium(태스크 마찰) 유지.
- (iv) 캡처 재확인 — 성립. A1.png 직접 개봉: 좌 HWPX 트랙 중앙 '저장된 작업이 없습니다'+부연+primary CTA vs 우 '즉시 기안' 트랙 빈 흰 사각형+푸터 '기안 템플릿 보관함' — 원관찰과 동일. D1.png 직접 개봉: 거대 공백 리스트+최하단 muted 2줄 안내 — 동일. 레이아웃 구조 관찰이라 offscreen 글꼴 아티팩트 무관. code_evidence 전건 개봉 검증: home.py:231-240(스택+빈 상태)·254-258(txt_list 스택 없음)·366(HWPX만 스택 전환) 성립, dataset_pool_panel.py:114-125+139-141 성립, vocab_workbench.py:95-107+116-118 성립, matrix_view.py:203-211(_populate_jobs 빈 분기 전무) 성립, template_manager.py:131 '홈 패턴 미러' 주석+143-166 성립. 단 매트릭스 0건 표면은 캡처 부재(D7은 채움 상태) — 코드 파생임을 원발견이 자인했고 구조적 주장이라 수용하되, 시각 주장으로는 미입증임을 원장에 명기 권고.
- (심각도 상향 반증 — 성공) design_basis의 '확인-또는-경보 시각형' 상향 트리거는 기각: 0건 사실 자체는 홈 KPI('데이터 풀 · 활성 0')·풀 헤더 count 라벨로 공시되므로 '조용한 상태 은폐'가 아니라 온보딩 마찰이다. ADR-B/E(필드 3상태·인라인 게이트)도 목록 빈 상태에 부적용. 상향 없이 §7 medium 확정.

**Verifier 비고**: 확정(재확인+반증 통과). 핵심 골격 — '스택 교체+중앙 안내+CTA' 빈 상태 패턴이 home HWPX 트랙과 template_manager('홈 패턴 미러' 주석이 이식 의도를 자증)에만 존재하고 이후 표면 4곳에 미이식되어 한 앱에 두 빈 상태 체계가 공존한다 — 는 캡처 2건(A1·D1)과 코드 5파일 전건 개봉으로 성립. root_cause(공용 컴포넌트 부재로 화면별 1회성 구현)도 코드 구조와 일치: home._build_empty_state와 template_manager._build_empty_state가 사실상 복제 코드임을 확인. 다만 user_impact 문구는 corrected_evidence대로 완화 필요(txt 트랙 헤더 CTA 존재, 매트릭스 '선택 0개' 라벨 존재). 매트릭스 leg는 캡처 부재 — 원장 박제 시 해당 표면만 '코드 파생(시각 미캡처)' 표기 유지 권고. 심각도 medium(§7 태스크 마찰) — 상향 트리거(ADR-B/E·조용한 은폐) 불성립으로 상향 없음. RC-14 부분 겹침 연결은 타당(RC-14 수리가 템플릿 워크숍에만 착지, 신규 표면 미전파 — §9 규칙 2 유형).

**증거 정정**: 1) home.py: txt 목록 빈 분기 부재의 정확한 앵커는 _render의 373-385행(366행은 HWPX 스택 전환 지점 — 대조용으로만 인용). 2) 'CTA 부재' 표현 정정: 풀은 헤더에 primary '엑셀/CSV 등록…'(dataset_pool_panel.py:102-108), txt 트랙은 헤더에 primary '＋ 새 기안'(home.py:247-248)이 상시 존재 — 부재한 것은 '빈 캔버스 내 상태 재진술+CTA' 패턴이지 CTA 일반이 아님. 3) 매트릭스 정정: '무안내 백지'가 아니라 '선택 0개' muted 라벨+전체선택/해제 버튼은 존재(matrix_view.py:85-94) — 결함의 정확한 형태는 '작업 0건'과 '선택 0건'의 시각 무구별 + 0건 시 다음 행동 안내 부재이며, app.py:144-152 라우팅에 0건 가드가 없어 도달 가능. 캡처는 없음(코드 파생 명기 유지). 4) vocab 권고 제약: 프로파일 생성은 작업 편집기 매핑 단계에서만 가능(자체 빈 라벨 문안이 명시) — 빈 상태 CTA는 신규 생성 버튼 발명이 아니라 기존 경로 안내/이동이어야 ADR 관통 원리(function→UX→UI, 없던 기능 발명 금지)와 충돌하지 않음. 5) ADR-A(i) 인용 범위 축소: 홈(txt 트랙 포함)에만 직접 적용, 풀·프로파일·매트릭스는 근거 ③(내부 다수 패턴 자기 모순)으로 성립.

</details>

### UD-18 · RC-26 용어 정렬의 치환 범위 누락 — 오류 다이얼로그('베이스' 4곳)·모달 제목('fieldize')·지시문('소스')·로그/메타(겨눔·정준)·액션 라벨 짝·'풀 항목'이 옛/내부 어휘로 잔존 (RC-26 회귀)

**중간/convention_deviation** · **수용** · **신뢰도 0.85** · **화면 A·B·D·F·global / 렌즈 L5** · **시나리오 F1·F3·B5·D7·D8·A1 (병합 6건)**

**관찰**: 잔존 증거(캡처+코드): (F) '누름틀 변환' 버튼을 누르면 'fieldize 미리보기' 영어 제목 모달, 카드 메타 '미컴파일 N', 결과 '컴파일 완료', F3 검토 결과에 '(fieldize 가능)' 렌더 실증 — 한 화면 삼중 어휘. (global) 실패 다이얼로그만 '베이스'(wizard.py:713,772 · app.py:214-215 · vocab_workbench_state.py:96) + 같은 산출물의 '매핑 프로파일로 저장'/'매핑 파일 저장' 버튼 병립(B5 실증). (B) 3단계 지시문의 '소스'가 화면에 없는 열 이름(실제 열 제목 '데이터 항목', 2단계 '데이터 소스'와 동음 충돌). (D7/D8) 로그 '데이터 겨눔'·카드 메타 '정준 필드' 내부 어휘 노출, 빌더만 '풀 항목'(관리·픽커는 '데이터셋'). (A1) 같은 액션 두 이름 — 헤더 '＋ 새 문서 작업' vs 빈 상태 '＋ 새 작업 만들기' 동시 노출, '작업 수정' 버튼↔'작업 편집' 창 제목, txt 저장 버튼↔다이얼로그 제목 불일치.

**기대**: 사용자 개념명 1개 원칙의 전 표면 관철 — 오류 문구·모달 제목·지시문·로그 포함. '누름틀 변환' 계열 통일, '베이스'→'매핑 프로파일', 지시문 '소스'→'데이터 항목', '풀 항목'→'데이터셋', 액션당 라벨 1개.

**사용자 영향**: 실패 순간에 미학습 개념('베이스')이 등장해 무엇이 실패했는지 매칭 불가, 같은 조작이 요소마다 세 이름이라 학습 불성립, 빈 상태의 두 파란 버튼이 서로 다른 기능처럼 읽혀 첫 경로 선택 지연 — 법적 문서 도구에서 내부 영어 명령 노출은 신뢰 훼손.

**디자인 근거**:

- RC-26 원장 열거 사례(fieldize 모달 제목·베이스 다이름·데이터 풀/데이터셋 혼용)의 잔존 확인 — 회귀
- 내부 다수 패턴 위반 — 같은 시맨틱을 한 화면이 3어휘로 동시 렌더, 다수파 어휘 대비 소수 표면 이탈

**코드 증거**:

- src/hwpxfiller/gui/template_manager.py:199,233-238 · template_manager_state.py:95,127,289 (fieldize/컴파일/변환 삼중)
- src/hwpxfiller/gui/wizard.py:713,772 · app.py:213-216 · vocab_workbench_state.py:96 ('베이스' 오류 문구)
- src/hwpxfiller/gui/wizard.py:455-458 vs mapping_table.py:44 ('소스' 지시문 vs '데이터 항목' 열)
- src/hwpxfiller/gui/matrix_view.py:255 · vocab_workbench.py:51 (겨눔·정준)
- src/hwpxfiller/gui/pipeline_builder.py:139,279-281 ('풀 항목')
- src/hwpxfiller/gui/home.py:221,291,77 · job_editor.py:59-61 · txt_view.py:105,200 (액션 라벨 짝)

**관련 RC**:

- RC-26 회귀(잔존 증거 확인 — 캡처 F3·B5·D7·D8·A1 + 코드 전거)
- RC-04 부분(화면 실도달로 잠복 해제)

**근본 원인**: RC-26 치환이 정상 경로 라벨·창 제목 위주로 수행되고 예외 핸들러·모달 제목·지시문·로그성 문구·파일 IO 버튼·코어 lint 문구가 범위에서 누락 — 용어표에 정준형 대비 검수 대상 표면 목록이 없었음.

**권고**: 치환 잔여 목록(위 코드 전거)을 일괄 정리하고, 용어표에 '오류 문구·모달 제목·로그 포함' 검수 범위를 명기. 코드 심볼(fieldize·base_*)은 유지 가능.

### UD-19 · 미입력 확인(ack)이 원클릭 즉시 확정·비가역 — 해제 API 부재 + ack 칩 비활성화로 철회 상호작용 표면 자체가 제거됨

**중간/defect** · **확정** · **신뢰도 0.80** · **화면 C / 렌즈 L4** · **시나리오 C2**

**관찰**: C2: ack 칩('✓ 담당자 — 미입력 표시 예정')이 비활성 확정 상태. FlowLayout 인접 칩 사이 오클릭 1회가 '미입력 표시로 내보낸다' 결정으로 즉시 승격되고 게이트 개방 — 정정하려면 데이터 재겨눔(전체 ack 소실)뿐.

**기대**: ack 칩을 활성 토글로 전환(재클릭=철회, unacknowledge 추가) 후 게이트 재평가, 툴팁에 취소 가능 명시.

**사용자 영향**: 법적 문서에 미입력 표식이 들어가는 결정이 오클릭 한 번으로 확정되고 재고 수단이 없음 — ADR-E 강제 상호작용의 취지(의도적 확인) 훼손.

**디자인 근거**:

- ADR-E 강제 상호작용 취지 = 의도적 확인 — 무취소는 오클릭도 확정으로 승격
- 확인-또는-경보 — 확정 상호작용이 정정 불가면 확정의 의미가 흔들림

**코드 증거**:

- src/hwpxfiller/gui/run_view.py:385-388 (_ack_field 즉시 확정)
- src/hwpxfiller/gui/run_view.py:373-376 (ack 칩 setEnabled(False))
- src/hwpxfiller/gui/run_state.py:419-425 (add 전용, 해제는 reset_acks 전체 초기화뿐)

**근본 원인**: ack 상태를 단방향 set으로 설계하고 ack 칩을 비활성화해 철회 경로를 원천 제거.

**권고**: ack 토글화 + unacknowledge API + 게이트 재평가.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패(이슈 생존). UI_DESIGN_DECISIONS.md §E(121-151행)는 강제 상호작용(이름 재진술+직접 건드림)만 규정하고 철회/비가역성에 대해 침묵; UI_DESIGN_HANDOFF.md에는 run view ack 스펙 자체가 없음. '비가역 원클릭 확정'이 의도된 결정이라는 문서 근거 부재. 단, 원클릭 칩은 필드명을 재진술하고 해당 항목을 직접 건드리게 하므로 ADR-E의 문면(letter)은 충족 — 위반은 취지(의도적 확인) 층위라 'ADR-E 위반 1단계 상향'은 부적용.
- (ii) 권위 반증 — 실패(이슈 생존). 주장은 목업 대조에 전혀 기대지 않음. 코드 실체(run_view.py:376 setEnabled(False), run_state.py:421 add 전용)+ADR-E 근거 문헌(반사적 클릭 저항)+confirm-or-alarm 원칙만으로 성립.
- (iii) 태스크 마찰 입증 — 성립, polish 강등 기각. 구체 태스크: C3 상태(missing 2건: 추정가격·담당자)에서 인접한 두 missing 칩 중 오클릭으로 담당자를 ack → 즉시 '표시 예정' 확정, 제자리 철회 불가. 유일 복구는 데이터 재겨눔(파일 선택 재실행)인데 UI 어디에도 이것이 철회 경로라는 단서가 없고 전체 ack가 소실됨. 단 완화 2건 확인: (a) ack는 최종 커밋이 아님 — 문서 생성 버튼 클릭이 별도로 남아 있고(run_view.py:406-447) ack 상태는 칩으로 가시적이라 조용한 은폐 아님(1단계 상향 부적용), (b) filled/blank 칩은 QLabel(비클릭)이라 오클릭 표면은 missing 칩 자체로 한정 — '인접 칩 사이 오클릭'은 missing 칩이 2개 이상일 때만 성립.
- (iv) 캡처 재확인 — 성립. C2.png 직접 열람: fill(공고명)/missing(추정가격, 빨강)/ack(담당자 — 미입력 표시 예정)/blank(비고) 4종 칩이 FlowLayout 한 줄에 인접 배치, ack 칩 비활성 스타일 확인, 게이트 문구('미입력 1필드를 확인해야…: 추정가격')도 코드 경로와 일치. 칩 활성/비활성은 코드 레벨 사실이라 offscreen 아티팩트 의심 없음. 인용 code_evidence 3건 라인 전부 정확(run_view.py:385-388, 373-376, run_state.py:419-425).

**Verifier 비고**: 확정(medium 유지). 근거: 코드 3건 전부 성립(원클릭 즉시 ack, ack 칩 비활성화로 철회 표면 제거, add 전용 API), 캡처 C2와 일치, 문서에 비가역 의도 부재, 구체 마찰(오클릭 ack의 제자리 정정 불가 + 복구 경로 비발견적) 성립. 상향 기각 사유: ack 상태가 칩으로 가시적(조용한 은폐 아님)이고 문서 생성이라는 별도 커밋 지점이 남아 있으며 ADR-E 문면(이름 재진술+직접 건드림)은 충족 — 피해 상한이 '잘못된 게이트 개방 상태에서 사용자가 생성을 추가 클릭'으로 한정됨. 강등 기각 사유: 법적 문서 표식 주입 결정의 확인 상호작용에서 정정 수단 부재는 confirm-or-alarm 원칙('확정'의 의미 보전)에 실질 저촉이고, 권장 수정(ack 토글화+unacknowledge+게이트 재평가)은 저비용·저위험. 관련 파일: C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/run_view.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/src/hwpxfiller/gui/run_state.py, C:/Users/rfast/Desktop/PYTHON_Projects/hwpx-filler/docs/UI_DESIGN_DECISIONS.md(§E).

**증거 정정**: '비가역' 표현은 과장 — 복구 경로가 존재함(데이터 재겨눔 시 reset_acks, run_state.py:236/260/272). 정확한 결함은 '제자리 철회 부재 + 복구 경로가 비발견적(undiscoverable)·조대(全 ack 소실)'. 또한 오클릭 표면 한정: filled/blank 칩은 QLabel(run_view.py:363-367)이라 클릭 불가 — 오클릭 확정은 missing 칩 위에 착지할 때만 성립. 추가 강화 증거: 같은 코드베이스의 wizard.py:235-259 _ack_partial은 ADR-E를 기본버튼=취소 다이얼로그로 구현 — run view의 무확인·무철회 원클릭은 자체 ADR-E 패턴 대비 내부 비일관.

</details>

### UD-20 · 상태 어휘 경계 미정의 — 같은 필드가 한 화면에서 '값이 비어 있는 필드'(사전검증)이자 '미입력'(배지·게이트), '미입력' 1단어가 트랙마다 다른 개념(실행=출력값 빔, txt=열 부재)

**중간/convention_deviation** · **수용** · **신뢰도 0.80** · **화면 C·E / 렌즈 L5** · **시나리오 C2**

**관찰**: C2: 추정가격·담당자가 '[경고] 값이 비어 있는 필드: …'와 '● 추정가격 — 미입력 확인'·'미입력 1필드를 확인해야…'로 동시 렌더(같은 상태 2이름). 교차: txt의 '◦ 빈 값'=열 있고 값 빔, '● 미입력'=열 부재 — 실행 화면의 '미입력'(출력값 빔)과 같은 단어 다른 개념.

**기대**: 용어표에 3정의 고정 — '미입력'(출력값 빔, ack 대상)·'빈 값'(원천 데이터 값 빔)·'(비움)'(의도 선언). 사전검증 경고를 '미입력 필드: …'로, txt의 열 부재를 '항목 없음' 계열로 치환.

**사용자 영향**: '값이 비어 있다' 경고와 '미입력 확인' 버튼이 같은 대상임을 사용자가 추론해야 하고, 두 트랙 왕복 사용자에게 오개념 형성.

**디자인 근거**:

- ADR-E 게이트는 미충족 필드를 이름으로 재진술 — 재진술이 어휘 불일치로 약화
- 내부 다수 패턴 위반 — 같은 상태 2이름 동일 화면, 1단어 2개념 트랙 교차

**코드 증거**:

- src/hwpxfiller/gui/run_state.py:392,406 (2이름 동시)
- src/hwpxfiller/gui/txt_view.py:39 · txt_state.py:79 (같은 단어 다른 개념)

**관련 RC**:

- RC-26 부분 겹침(상태축 어휘 침범 축의 잔존/신규 사례)

**근본 원인**: 사전검증과 인라인 게이트의 병렬 저작 + 용어표의 상태축 경계 미정의.

**권고**: 용어표 3정의 확정 후 run_state 경고·txt missing 라벨 치환.

### UD-21 · RAW 템플릿 차단 사유가 게이트 UI 경로 밖 조기 return으로 처리 — warn 레벨 없이 본문 요약 라벨로 렌더(같은 페이지 PARTIAL 차단은 warn 주황)되고 문구 원천이 VM·위젯에 이중화

**중간/defect** · **확정** · **신뢰도 0.75** · **화면 B / 렌즈 L3** · **시나리오 B2·B3**

**관찰**: B2(RAW): '누름틀 필드가 없습니다 — 진행할 수 없습니다'가 본문 검정으로, Next만 조용히 비활성. B3(PARTIAL): 동일 시맨틱이 warn 주황. 문구가 mapping_state.py:341-345(미사용)와 wizard.py:139-142(하드코딩)에 이중 존재.

**기대**: RAW 문구를 PartialGate.message() 단일 원천으로 되돌리고 lbl_warn(level=warn)으로 렌더 — lbl_summary는 성공 요약 전용.

**사용자 영향**: RAW 차단 사유가 정보성 요약과 동일한 룩이라 경고로 인지되지 못하고 스캔에서 지나침 — 'Next가 왜 안 눌리는지' 발견 지연.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — 같은 페이지 차단 3경로 중 RAW만 무마크
- style.py:20-21 색 의미 계약
- ADR-E 인접 — 게이트 차단 사유는 시끄럽게

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:137-143 (조기 return + 무마크 lbl_summary)
- src/hwpxfiller/gui/wizard.py:81-83,162-165 (lbl_warn 대조 경로)
- src/hwpxfiller/gui/mapping_state.py:341-345 (죽은 문구 원천)

**관련 RC**:

- RC-23 부분 겹침(표시 결정이 VM·위젯에 쪼개진 패턴이 위저드 1단계에 잔존)

**근본 원인**: RAW 거부가 게이트 UI 경로(_refresh_gate_ui/lbl_warn) 합류 전 조기 return 분기로 처리되어 렌더 레벨과 문구 원천이 게이트 계열과 분리.

**권고**: RAW 분기를 게이트 경로에 합류시켜 문구 단일 원천화+warn 렌더.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md·UI_DESIGN_HANDOFF.md 어디에도 'RAW 차단 사유는 무마크 요약 라벨로'라는 결정 없음(HANDOFF는 위저드 스텝1 시각 레벨 무언급, DECISIONS의 C3 관련 조항은 PARTIAL 게이트만 다룸). wizard.py:138 주석 '(종전 동작 유지)'는 레거시 보존 표기이지 문서화된 디자인 결정이 아님. 가장 강한 반증 후보 = compile_badge.py(RC-29 착지)의 RAW→muted('원문·할 일, 심각도 아님') 매핑이나, 이는 목록 표면(홈·템플릿 관리)의 상태 배지 어휘이지 게이트 차단 메시지 레벨이 아니며, 그 기준을 적용해도 현재의 무마크 본문 검정은 muted도 warn도 아니어서 어느 해석으로도 현행이 의도로 성립하지 않음.
- (ii) 권위 반증 — 실패(주장 성립). 주장은 목업 대조에 전혀 기대지 않음 — 근거가 페이지 내부 다수 패턴(차단 경로 4개 중 RAW만 무마크: PARTIAL wizard.py:184, 게이트 계산 실패 162-165, 저장 템플릿 부재 109-112 모두 lbl_warn), 캡처 B2/B3, 코드 실측. 목업 참조 제거 후에도 온전히 섬. UI_CONTRACT '문구=코드 SoT'와도 무충돌(문구 변경 요구 아닌 렌더 레벨·원천 단일화 요구).
- (iii) 태스크 마찰 입증 — polish 강등 시도 실패, 단 high 아님 확인. 강등 논거: B2 페이지가 희소해 차단 문구가 화면 유일 텍스트라 발견 가능성이 낮지 않음. 그러나 마찰은 실재: (a) B1 정상 흐름에서 같은 위치·같은 스타일 라벨이 '필드 N개: …' 성공 요약이라 사용자는 그 자리를 정보성으로 학습 — RAW에서 동일 룩이 차단 사유로 재사용되면 스캔에서 시맨틱 전환을 놓침, (b) B3와 교차 사용 시 동일 '진행 차단' 시맨틱이 페이지마다 다른 심각도 신호 — §7 medium 예시 '배지 어휘 이중화'와 정확히 동형. 역으로 high('게이트 차단 사유 비가시') 승격도 불가 — 사유 텍스트는 표시되고 있어 '조용히 안 보이는 상태'가 아님.
- (iv) 캡처 재확인 — 동일 관찰. B2.png 직접 열람: RAW 문구가 본문 검정(무마크), 게이트 버튼 없음, Next 비활성. B3.png: '진행 차단…' warn 주황 + [여기서 누름틀 변환]/[비움 확인…] 버튼. 주황vs검정은 색상 차라 offscreen 아티팩트(가는 글꼴·안티앨리어싱) 소지 없음. code_evidence 전건 성립(미세 라인 정정은 corrected_evidence). message() RAW 분기의 사(死)경로 주장 독립 확인: 제품 코드 유일 호출부 wizard.py:184는 needs_gate()==True(PARTIAL 전용, mapping_state.py:314-316) 경유로만 도달 — RAW 분기 도달 불가. 문구 이중화도 축자 확인(첫 문장 동일).

**Verifier 비고**: 확정(재확인+반증 통과), medium 유지. 상향 규칙 미발동: 사유 텍스트가 표시되므로 '조용한 상태 은폐' 아님, ADR-B/E는 원발견 스스로 '인접'으로만 인용(직접 조항 위반 아님 — ADR-E는 누락·빈칸 인라인 표면화 조항). §7 medium('배지 어휘 이중화' — 동일 시맨틱 이중 시각 렌더)에 정합. 신뢰도 0.75: 관찰·코드·죽은 경로·이중화 전건 확증이나, (a) B2 화면 희소성으로 실마찰 강도가 상한 아님, (b) RAW→muted(compile_badge, RC-29)와 warn 렌더 권고 간 어휘 긴장이 남아 권고 형태(warn이 정답인지, muted 계열 차단 표기인지)는 착지 시 재론 여지. 권고 보강: RAW 분기를 게이트 경로 합류 시 needs_gate()가 PARTIAL 전용(mapping_state.py:314-316)인 것도 함께 손봐야 하며(현재 RAW gate는 needs_gate()=False라 합류만으로는 lbl_warn이 비워짐), 문구 단일 원천화는 mapping_state.py:342-345 부활 + wizard.py:139-141 삭제로 RC-23 동형 패턴 해소. related_rc(RC-23 부분 겹침) 타당.

**증거 정정**: wizard.py RAW 조기 return 블록은 137-144(원발견 137-143 — 144의 return False 포함이 정확). lbl_warn 조성은 81-84(mark는 83). mapping_state.py의 죽은 RAW 문구 분기는 342-345(message() 정의는 339; 원발견 341-345는 분기 진입 st 대입 341 포함 — 실질 동일). 추가 보강 증거: initializePage의 저장 템플릿 부재 경고(wizard.py:109-112)도 lbl_warn 사용 — 페이지 내 차단성 통지 4경로 중 RAW만 무마크로, '3경로'보다 패턴 위반이 더 강함. 단 design_basis의 style.py:20-21 인용은 양날: 해당 계약은 'WARN=비차단 경고'라 차단 사유의 warn 렌더 자체가 문언상 계약 밖이며, 페이지는 이미 PARTIAL·게이트 실패에서 warn을 차단에 쓰고 있어 실질 규범은 '내부 다수 패턴'임 — 착지 시 style.py 주석 갱신(또는 warn 의미 재정의)을 권고에 병기해야 함.

</details>

### UD-22 · primary '주 액션' 위계 규율 부재 — 홈은 한 뷰포트에 11개(카드 곱셈), 위저드 4스텝은 0개, 파이프라인 빌더는 2개 경쟁, 프로파일 관리는 0개, 템플릿 카드 내 위치는 좌/우 반전

**중간/convention_deviation** · **수용** · **신뢰도 0.75** · **화면 A·B·D·F / 렌즈 L1·L4** · **시나리오 A3·B6·D6·D8·F1 (병합 6건)**

**관찰**: 화면별 증상: (A3) 홈에 primary 11개 동시 노출(카드 [실행]·[기안 작성] 곱셈+헤더 3개) — 타 화면은 표면당 1개. (B1/B6) 위저드 전 스텝 primary 0개 — Next/'작업 저장'이 Cancel과 동일 룩(QWizard 자체 생성 버튼에 마킹 관례 미적용). (D6) 빌더 '스텝 추가'·'풀에 저장' 2개 경쟁. (D8) 프로파일 워크벤치 primary 0개+목록이 차면 생성 경로 안내 소멸. (F1) PARTIAL 카드는 primary 좌측·COMPILED 카드는 우측 — 같은 목록 안에서 반전(_STATE_ACTIONS 선언 순서 그대로 화면화).

**기대**: 화면당 primary 정확히 1개(반복 카드 액션은 보조 등급으로 강등), QWizard 내비 버튼에 mark(primary) 적용, 카드 액션 행의 primary 위치 고정.

**사용자 영향**: 가장 큰 저작 표면(위저드)에서 주 행동 탐색 비용·Cancel 오클릭 위험, 홈에서는 PRIMARY 신호 희석으로 시선 유도 소실, 카드 목록 스캔 시 반사 클릭이 보조 버튼을 누름.

**디자인 근거**:

- style.py:20-21 'PRIMARY=주 액션' 의미 계약 — 0개면 주 행동 불명, 11개면 계약 성립 불가
- 내부 다수 패턴 자기 모순 — run/matrix/nara/txt/pool 등은 표면당 1개, 문제 화면군만 이탈
- 정량 — 1280×800 단일 뷰포트 primary 11개(A3)

**코드 증거**:

- src/hwpxfiller/gui/home.py:74,140,222,248,292 (5곳 마킹×카드 반복)
- src/hwpxfiller/gui/job_editor.py:62-66 (위저드 마킹 전무)
- src/hwpxfiller/gui/pipeline_builder.py:103,141-143 (2개)
- src/hwpxfiller/gui/vocab_workbench.py:83-93 (0개)
- src/hwpxfiller/gui/template_manager_state.py:57-68 + template_manager.py:72-79 (위치 반전)

**근본 원인**: '카드 기준 주 액션'과 '화면 기준 주 행동'이 같은 primary 프로퍼티 하나로 표현되고, 화면당 1개·위치 규칙이 문서·가드 어디에도 없어 위젯별 우연에 위임됨.

**권고**: 카드 반복 버튼용 보조 시각 등급을 style.py에 추가하고 primary는 화면/트랙당 1개로 제한, JobEditorWizard 생성자에서 Next/Finish 버튼 마킹, 카드 렌더 시 primary 고정 끝 정렬.

### UD-23 · MUTED(부차 텍스트) 토큰이 primary:disabled의 채움 배경으로 재전용 — 비활성 주 버튼(진회색 채움+흰 글자)이 활성 보조 버튼보다 시각적으로 강한 위계 역전 + 비활성 문법 이원화

**중간/convention_deviation** · **수용** · **신뢰도 0.75** · **화면 A·global / 렌즈 L2** · **시나리오 A2**

**관찰**: A2: '부재 템플릿 작업' 카드의 비활성 [실행]이 진회색 채움+흰 글자로 인접 활성 [작업 수정]·[삭제](흰 배경·회색 테두리)보다 시각 무게가 큼.

**기대**: primary:disabled를 일반 버튼 disabled 문법으로 수렴(채도·대비 하강) 또는 전용 disabled 토큰 쌍 정의 — 비활성은 활성보다 항상 약하게.

**사용자 영향**: 실행 불가 작업의 [실행]이 화면에서 가장 눌러 보여 오클릭 유도 + '왜 안 눌리지' 혼란, 두 비활성 문법 병존으로 상태 학습 분열.

**디자인 근거**:

- style.py:20-21 색 의미 계약(MUTED=부차) — 배경 재전용은 계약 밖
- 내부 자기 모순 — 같은 :disabled 상태 두 문법(A2 시각 확인)

**코드 증거**:

- src/hwpxfiller/gui/style.py:106 (primary:disabled background MUTED)
- src/hwpxfiller/gui/style.py:73 (일반 버튼 disabled 대조 문법)

**근본 원인**: 비활성 시각 문법의 단일 정의(채움 해제 vs 색 하강) 부재 — primary 룩을 유지한 채 색만 치환한 손쉬운 선택.

**권고**: primary:disabled를 일반 disabled 문법으로 수렴 + MUTED 계약 주석 정리.

### UD-24 · 컴파일 '변환 가능 토큰 없음' 결과만 차단 모달로 전달 — 같은 화면 액션 결과 5종 중 4종은 인라인 lbl_result, 이 1종만 모달이며 닫으면 흔적 0

**중간/convention_deviation** · **수용** · **신뢰도 0.70** · **화면 F / 렌즈 L4** · **시나리오 F3**

**관찰**: template_manager.py:232-235가 no-compilable 분기를 information 모달로 처리 — 검토·미리보기·드리프트·컴파일 성공은 전부 인라인(F3 실증). :215가 액션 시작 시 라벨 소거.

**기대**: no-compilable 분기를 lbl_result 인라인 문구로 전환('컴파일 — {이름}: 변환 가능 토큰 없음 (건너뜀 N개: …)') — 모달은 파괴 확정에만.

**사용자 영향**: 조각·복합 런 토큰만 가진 템플릿에서 모달이 흐름을 끊고, 건너뜀 사유를 다시 보려면 같은 버튼 재클릭으로 모달 재소환 — 다른 액션과 비대칭 학습 비용.

**디자인 근거**:

- ADR-E 차단 모달 강등 — 모달은 비가역·파괴 작업에만 정당
- 내부 다수 패턴 자기 모순 — 동일 화면 결과 5종 중 4종 인라인·1종 모달

**코드 증거**:

- src/hwpxfiller/gui/template_manager.py:232-235 (모달 채널)
- src/hwpxfiller/gui/template_manager.py:215 (시작 시 라벨 소거 → 잔존 표시 0)
- src/hwpxfiller/gui/template_manager.py:242-264 (인라인 대조 4종)

**관련 RC**:

- RC-14 부분 겹침(결과 문구 성형은 착지 — 채널 이원화는 미해소)

**근본 원인**: 컴파일 액션의 확인 모달 플로우 안에 '진행 불가' 결과 통지가 섞여 인라인 채널 대신 모달 계열로 처리됨.

**권고**: VM에 format_scan_empty_result 성형 추가 후 인라인 전환.

### UD-25 · txt 즉시 기안의 데이터 겨눔 어포던스가 파일 다이얼로그 1종뿐 — 실행 표면(풀/파일/나라 3종)과 비대칭, ADR-J 1단계가 지목한 '스프레드시트 강제' 증상 잔존

**중간/convention_deviation** · **수용** · **신뢰도 0.65** · **화면 E / 렌즈 L4** · **시나리오 E1**

**관찰**: E1: 데이터 입력 수단이 '데이터 선택…' 버튼 하나(_pick_data → 파일 다이얼로그만). 대조: 실행 표면은 풀/파일/나라 3종(batch_run.py:232-315). 풀에도 수기 1건 kind 부재(factory.py:46-52).

**기대**: txt 컨트롤 줄에 최소 '데이터 풀에서…' 진입 추가(DataPickers 재사용) + ADR-J가 서술한 수기 1건 인라인 입력 경로.

**사용자 영향**: 값 몇 개 넣고 바로 복사한다는 즉시 기안의 핵심 가치 훼손 — 엑셀 파일 제작 강요, 풀에 등록한 데이터셋(나라 쿼리·파이프라인)의 txt 트랙 재사용 불가('풀에 등록했는데 왜 여기선 못 쓰지' 학습 비용).

**디자인 근거**:

- ADR-J §문제·§단계1 — txt_view._pick_data 파일 강제를 명시 지목·착지 선언(J1)과 표면 실태의 괴리
- 내부 다수 패턴 자기 모순 — 동일 시맨틱(데이터 겨눔)이 실행=3어포던스, txt=1어포던스

**코드 증거**:

- src/hwpxfiller/gui/txt_view.py:137-152 (단일 경로)
- src/hwpxfiller/gui/batch_run.py:232-315 (3종 겨눔 계층)
- src/hwpxfiller/data/factory.py:46-52 (인라인 kind 부재)

**근본 원인**: ADR-J 1단계 구현이 HWPX 실행 표면에만 랜딩(문서상 착지 선언과 표면 실태의 괴리 — J1 커밋 범위는 Verifier 실측 필요).

**권고**: txt에 풀 겨눔 버튼 추가(최소 수리) + 수기 1건 입력 경로 제공.

### UD-26 · 미리보기·검수 표면 3곳에서 빈 값/결측이 무표시 빈 공간으로 렌더 — 파이프라인 left 조인 결측, txt 기안 blank 위치, FILLED 템플릿 미리보기 빈 값 (ADR-B '빈 공간으로 보이면 안 됨' 위반 후보)

**중간/investigation_needed** · **확정** · **신뢰도 0.60** · **화면 D·E·F / 렌즈 L3** · **시나리오 D6c·E7·F5 (병합 3건)**

**관찰**: 코드 확정 3표면: (D) 파이프라인 미리보기 셀이 rec.get(f,'')로 left 조인 무매칭 결측과 원본 빈 문자열을 동일 무표시 렌더 — '실행 결과와 동일'을 자처하는 검수 표면. (E) txt 미리보기에서 blank 토큰이 ''로 치환·소멸 — missing은 빨간 span으로 위치까지 표시되는데 blank는 흔적 0(런타임 재현: 본문이 '담당: '로 끝남). (F) format_preview_result가 f'{k} = {v}' 성형 — 빈 값 필드가 '필드명 = ' 맨 빈 공간(마커는 선택적이라 의도적 빈칸과 구별 불가).

**기대**: 세 표면 모두 빈 값/결측을 명시 재진술 — '(없음)'/'(빈칸)' muted 표기 또는 클립보드 무영향 HTML 마커(missing 하이라이트와 동형).

**사용자 영향**: left 조인 검수에서 무매칭 행을 놓치고 저장, 기안 미리보기에서 어느 자리가 빈 채 나가는지 특정 불가, FILLED 검수에서 의도적 공란과 채우다 만 것을 판별 불가 — 법적 문서 검수 표면의 상태 오독 위험.

**디자인 근거**:

- ADR-B '빈 공간으로 보이면 안 됨' — 3상태 시각 구별의 파생 표면 미이식(확정 시 상향)
- 내부 다수 패턴 자기 모순 — mapping_table은 DATA_EMPTY_FG 구별, txt는 missing만 위치 표시·blank 무표시(같은 미충족 상태를 다른 성실도로 렌더)

**코드 증거**:

- src/hwpxfiller/gui/pipeline_builder.py:267 (결측·빈값 동일 렌더)
- src/hwpxfiller/gui/txt_view.py:176-181 (_hl이 잔존 토큰만 하이라이트, empty_fields 미반영)
- src/hwpxfiller/gui/template_manager_state.py:303-310 (빈 v 무처리 성형)
- src/hwpxfiller/gui/style.py:35 (DATA_EMPTY_FG — 기존 규율 원천)

**근본 원인**: 빈 값 구별 렌더가 mapping_table 로컬 구현으로 남아 검수 성격의 파생 표면들(문자열 덤프형 미리보기)에 규율로 전파되지 않음.

**권고**: 캡처 레지스트리에 left 조인 무매칭·blank 레코드·FILLED 빈 값 시나리오 추가해 확정 후, 3표면에 명시 재진술 렌더 적용(확정 시 high 상향).

### UD-27 · 매핑 미리보기 요약이 '채움/빈 값' 2상태만 집계 — 미매핑 잔존 10필드가 무집계라 합계(12)가 필드 수(22)와 불일치, 공란 규모 과소 진술

**중간/convention_deviation** · **수용** · **신뢰도 0.60** · **화면 B / 렌즈 L3** · **시나리오 B5**

**관찰**: B5: '채움 9 · 빈 값 3' — 나머지 미매핑 10개(이 레코드 출력에서 역시 비게 될 필드)는 요약 어디에도 없음.

**기대**: '채움 9 · 빈 값 3 · 미매핑 10' 3상태 전량 재진술 또는 확정 카운터와 병합.

**사용자 영향**: '빈 값 3'만 보고 공란 규모 오판 가능 — 행 색이 보정하므로 비차단.

**디자인 근거**:

- ADR-B 3상태가 모든 표면에서 — 요약 표면은 2상태
- 정량 — 표시 합계 12 ≠ 전체 22

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:593-604
- src/hwpxfiller/gui/mapping_state.py:218-225 (has_content 행만 순회)

**근본 원인**: 요약이 매핑된 행의 부분집합만 다루도록 설계.

**권고**: '미매핑 N' 항 추가.

### UD-28 · 데이터 건너뛰기(ADR-J 공식 플로우) 시 매핑 스텝 전 행이 '미매칭' 빨강 경보로 렌더 추정 — '데이터 미연결'과 '미매칭'이 같은 신호, 레코드 0/0 빈 상태 안내 부재

**중간/investigation_needed** · **확정** · **신뢰도 0.55** · **화면 B / 렌즈 L3** · **시나리오 B8**

**관찰**: 코드 파생: 스킵 시 source_fields=[] → 전 행 sources=[] → _row_brush가 전부 UNMATCHED 빨강. 콤보 선택지는 '(비움)'뿐, 스텝퍼 '레코드 0/0'+비활성, 안내문 없음 — 데이터 없이 무엇을 할 수 있는지(상수·비움 확정·프로파일) 무안내.

**기대**: source_fields 빈 세션이면 행 색 중립 강등 + 인라인 안내 배너(스키마-온리 모드 설명·다음 행동 제안).

**사용자 영향**: 공식 플로우 사용자가 전면 빨강을 오류로 오인 — 스텝 되돌아가기·중단 등 불필요한 재작업 유도.

**디자인 근거**:

- ADR-J 매핑은 스키마만으로 확정 가능 — 그 경로의 상태 표현이 오류 신호와 동일
- ADR-B 상태 구별
- 내부 패턴 — 타 화면 빈 상태는 안내문+CTA

**코드 증거**:

- src/hwpxfiller/gui/mapping_table.py:64-72 (_row_brush 원인 무구별)
- src/hwpxfiller/gui/mapping_state.py:104-125 (source_fields=[] → 전 행 sources=[])
- src/hwpxfiller/gui/wizard.py:578-584 (0건 시 무안내)

**근본 원인**: ADR-J 강등이 만든 신규 상태(데이터 미연결 세션)가 시각 계층에 미배선.

**권고**: 시나리오 레지스트리에 '데이터 스킵 매핑' 상태 추가 캡처 후, 빈 세션 시 중립 색+안내 배너 적용.

### UD-29 · 나라장터 취득 중지 후 신호 모순 — '중지했습니다' 경고만 남긴 채 OK 게이트는 이전 스냅샷 기준으로 재개방(무엇이 수용되는지 화면에 없음)

**중간/investigation_needed** · **확정** · **신뢰도 0.55** · **화면 D / 렌즈 L3** · **시나리오 D10**

**관찰**: 코드 확정: 재취득 시작이 lbl_result를 '가져오는 중…'으로 덮어 이전 성공 요약 소실 → 중지 시 warn '요청을 중지했습니다 — 도착하는 결과는 무시됩니다'만 잔존 → _set_busy(False)가 vm.last_result 존재 기준으로 OK 재활성 — 라벨과 게이트가 다른 상태를 말함.

**기대**: 중지 문구가 잔존 스냅샷을 재진술('이전 취득(6/5~6/12, 100건)이 그대로 유효합니다') 또는 res.summary()를 warn 접두와 함께 복원.

**사용자 영향**: 중지 직후 OK를 누르면 이전 취득 내용이 풀에 등록되는데 마지막 발화는 '중지'뿐 — 무엇이 등록되는지 오인.

**디자인 근거**:

- 확인-또는-경보 — 수용 대상 상태가 조용히 안 보임
- 내부 패턴 — 같은 대화상자의 편집 경로는 게이트 잠금과 발화를 동기화하는데 중지 경로만 어긋남

**코드 증거**:

- src/hwpxfiller/gui/nara_view.py:297-309 (_on_stop_fetch 요약 소실)
- src/hwpxfiller/gui/nara_view.py:337-342 (_set_busy가 last_result 기준 재활성)

**관련 RC**:

- RC-24 부분 겹침(스냅샷 잔존 자체는 계약상 유효 — '무엇이 잔존·수용되는지' 표시가 새 증상)

**근본 원인**: 중지 경로의 발화와 게이트 복원이 분리 구현되어 동기화 규율 부재.

**권고**: 중지 문구에 잔존 스냅샷 요약 병기. 캡처 하네스에 '성공→재취득→중지' 시나리오 추가.

### UD-30 · 가변 길이 사용자 문자열 라벨의 말줄임·최대폭 계약 부재 — KPI '최근 실행'·카드 제목(A), 실행 요약 헤딩(C), txt 토큰 배지(E), 템플릿 파일명(F)에서 현실 밀도 잘림/압착/가로 스크롤 가능 (RC-36 처치의 미이식 부위)

**중간/investigation_needed** · **확정** · **신뢰도 0.50** · **화면 A·C·E·F / 렌즈 L1** · **시나리오 A4·W5·C8·E6·F4 (병합 4건)**

**관찰**: 코드 확정 4표면: (A) KPI 값 22px 라벨이 날짜+작업명 연결 문자열을 무제한 렌더 — 현실 공고명 길이에서 KPI 행 최소폭이 창 폭 초과해 우측 타일 압착 가능, 카드 제목도 배지를 밀어낼 수 있음. (C) 실행 요약 lbl_job(작업명·템플릿명·패턴 연결)만 형제 4개 라벨과 달리 wordWrap 미적용 — widgetResizable QScrollArea라 폼 전체 가로 스크롤 유발 가능. (E) 고정폭 280px 토큰 패널의 배지가 elide·툴팁 없음. (F) 템플릿 파일명 라벨 무처리 + 가로 스크롤바 Always Off — 유사 파일명 판본 구별 실패 가능.

**기대**: 긴 이름에서도 상태 배지·KPI 타일이 온전히 보이고, 잘리면 말줄임+전체 이름 툴팁(RC-36 동형 처치).

**사용자 영향**: 발생 시 마지막 KPI 타일·카드 배지가 조용히 화면 밖으로 밀려 상태 정보 소실('조용히 안 보이는 상태'로 상향 여지), 미입력 토큰의 이름 식별 불가는 ADR-E 재진술 취지 무력화.

**디자인 근거**:

- §4 L1 체크리스트 '현실 밀도에서 잘림/스크롤/말줄임'
- 내부 패턴 자기 모순 — run_view 형제 라벨 4곳은 wordWrap, 가장 긴 문자열 라벨만 미적용
- RC-36 처치가 매핑 테이블 한정

**코드 증거**:

- src/hwpxfiller/gui/home.py:310-311,334,49-51 (KPI·카드 제목 무처리)
- src/hwpxfiller/gui/run_view.py:89-94,209-213 (lbl_job + QScrollArea 전파)
- src/hwpxfiller/gui/txt_view.py:90,169-171 (고정폭+무처리 배지)
- src/hwpxfiller/gui/template_manager.py:56-58,129 (파일명 무처리+스크롤바 Off)

**관련 RC**:

- RC-36 부분 겹침(같은 성격의 밀도 처치가 매핑 테이블에만 착지)

**근본 원인**: 가변 길이 실데이터를 고정 위계 라벨에 무가공 주입 — 길이 상한·말줄임 계약이 표면 공통 규율로 존재하지 않음.

**권고**: 시나리오 레지스트리에 긴 작업명(40자+)·긴 토큰명·긴 파일명 밀도 상태를 추가해 1280·980 양폭 재캡처로 실증 후, QFontMetrics.elidedText+setToolTip 일괄 적용.

## 낮음 (low) — 15건

### UD-31 · 진행바 퍼센트 텍스트가 청크 위에서 대비 붕괴 — QSS가 텍스트를 MUTED 단색 고정(#7a7f87 on PRIMARY #2874a6 ≈ 1.3:1)해 Qt 기본 반전을 덮음, 실행 후반부 내내 수치 판독 불가

**낮음/defect** · **확정** · **신뢰도 0.90** · **화면 C / 렌즈 L1·L3** · **시나리오 C5 (병합 2건)**

**관찰**: C5(50%): 청크 경계에 걸린 '50' 부분이 사실상 비가시, '%'만 밝은 배경 위에서 판독.

**기대**: 청크 위 텍스트 고대비 분리(QSS color 제거로 팔레트 자동 반전 복원, 또는 텍스트 외부 라벨 이동) — 대비 4.5:1 이상.

**사용자 영향**: 배치 실행의 유일한 정량 진행 신호가 후반부에 읽히지 않음 — 막대 길이가 대략을 전달하므로 비차단 마찰.

**디자인 근거**:

- 정량 임계 — 대비 ≈1.3:1(두 토큰 값으로 확정 계산, offscreen 무관) vs 기준 4.5:1
- style.py:20-21 MUTED=부차 계약의 청크 위 텍스트 재사용 이탈

**코드 증거**:

- src/hwpxfiller/gui/style.py:75-79 (color MUTED 단색 고정 + chunk PRIMARY)
- src/hwpxfiller/gui/run_view.py:199-201 (해당 QSS 사용)

**근본 원인**: QSS 단색 지정이 Qt의 청크 통과 시 자동 대비 전환을 덮어씀.

**권고**: QProgressBar color 지정 제거 또는 고대비 색 조정/외부 라벨화.

<details><summary>반증 4축 · Verifier 비고</summary>

- (i) 문서 의도 반증 — 실패. UI_DESIGN_DECISIONS.md에 진행바/퍼센트 텍스트 색을 다루는 ADR 없음(grep '진행|progress|퍼센트' — 무관 매치 2건뿐). UI_DESIGN_HANDOFF.md:118·136은 '진행/로그 표현'을 '디자인이 채울 것'(자유 영역)으로 명시 — MUTED-on-chunk가 의도된 결정이라는 근거 부재.
- (ii) 권위 반증 — 실패. 주장은 목업 대조에 전혀 기대지 않음: 근거는 style.py 토큰 값 기반 정량 대비(WCAG 상대휘도 재계산: MUTED #7a7f87 on PRIMARY #2874a6 = 1.26:1, 원발견 '≈1.3:1' 일치)와 캡처 픽셀. 목업 참조 제거해도 완전히 성립.
- (iii) 태스크 마찰 입증 — 성립(비차단, low 유지). 배치 실행 감시 태스크에서 퍼센트 라벨이 유일한 한눈 정량 신호임을 확인: BatchRunController._on_progress(batch_run.py:181-182)는 setValue만 하고 로그는 레코드명 나열('생성 중: <이름>')일 뿐 i/N 러닝 카운터 없음 — 후반부 정확 진행률을 알려면 로그 줄을 세어야 함(재작업 마찰). 단 막대 길이가 근사치를 전달하므로 차단 아님 — polish 강등은 부적절(§7 design_basis ④ 정량 임계 1.26:1 vs 4.5:1 충족), low defect 유지.
- (iv) 캡처 재확인 — 성립. C5.png 직접 개봉+픽셀 샘플링: 진행바 y=691-711, 청크 우단 x≈624, '50%' 텍스트가 정확히 경계에 걸림 — 청크 위 숫자 픽셀은 #547a95/#3e779d/#6399bd(MUTED가 파랑 위 안티앨리어싱된 블렌드)로 8배 확대에서도 간신히 식별, 1:1에서 사실상 비가시. 렌더 색이 토큰 값 그대로(#2874a6·#eef0f3 verbatim)라 offscreen 아티팩트 아님 — 대비는 토큰 산술이라 렌더 경로 무관. code_evidence 재확인: style.py:75-79(77행 color:{MUTED}, 79행 chunk {PRIMARY}) 성립, run_view.py:199-201 progress 생성 + 83행 setStyleSheet(BASE_QSS) 적용 확인 — 라인 인용 정확.

**Verifier 비고**: 확정(재확인+반증 통과). 심각도 low 유지 — §7 상향 규칙 비적용: 진행 '상태' 자체는 막대 길이로 계속 가시적이라 '조용한 상태 은폐'가 아니고(수치 정밀도만 소실), ADR-B/E(필드 3상태 배지) 무관. merged_count=2 타당(같은 QProgressBar QSS가 run_view와 matrix_view의 BatchRunController 공유 표면 양쪽에 적용됨 — batch_run.py:119 RC-22 공용 계층). 재현 경로: 시나리오 C5, 검증 크롭은 스크래치패드 ui-review/c5_progress_zoom.png. 권고는 '외부 라벨화 또는 2색 커스텀 페인트'로 좁혀 박제할 것 — color 제거 단독은 수리가 아님.

**증거 정정**: 두 가지 기술 정정: (1) root_cause의 'Qt 자동 반전을 color 지정이 덮음'은 부정확 — QSS로 ::chunk를 스타일하는 순간 QStyleSheetStyle이 텍스트를 단일색 1패스로 그려 네이티브 스타일의 청크-클리핑 2패스 반전 자체가 소실됨. 따라서 권고 1안('QSS color 제거로 팔레트 자동 반전 복원')은 무효: color 제거 시 텍스트는 INK #1c2126 단색이 되고 청크 위 대비 3.2:1로 여전히 4.5:1 미달. (2) 추가 관찰(결함 강화): MUTED는 청크 밖 groove #eef0f3 위에서도 3.53:1로 4.5:1 미달 — 퍼센트 텍스트는 전 구간 AA 미달이며 청크 위(1.26:1)는 극단 사례. 어떤 단일 텍스트색도 PRIMARY(휘도 0.157)와 groove(≈0.89) 양쪽에서 4.5:1을 동시 충족할 수 없으므로(산술적으로 불가능) 유효 수리는 외부 라벨화 또는 청크-클리핑 2색 커스텀 페인트뿐. 미세 정정: 겹침 시작은 약 45%가 아니라 ≈48-49%('50%' 텍스트 폭 ~30px, 바 ~1240px 기준).

</details>

### UD-32 · [캡처 뱅크 오염] deleteLater 유령 칩 — 하네스 processEvents가 DeferredDelete를 처리하지 않아 C2~C5·W3·E2·E3에 구세대 배지가 640px 색 블록으로 박제(제품 결함 아님 확증, 실앱 순간 노출 창만 저강도 확인 필요)

**낮음/investigation_needed** · **기각(제품 무결)** · **신뢰도 0.90** · **화면 C·E / 렌즈 L1·L3** · **시나리오 C2·E2·E3 (병합 4건)**

**관찰**: C2~C5·W3: 배지 행 뒤 폭 ~640px BLANK_BG(#f6ecdb) 스트립. E2·E3: MISSING_BG(#fbe6e3) 솔리드 블록 — '전 토큰 채움' 화면이 위험색 바탕 위에 뜬 것으로 보임(E1 동일 좌표 흰색으로 재렌더 시에만 발생 확증).

**기대**: 재렌더 시 구세대 칩 즉시 비가시화(deleteLater 전 hide() 또는 setParent(None)) — 어떤 페인트 타이밍에도 잔존물 0. 뱅크는 pump()에 sendPostedEvents(DeferredDelete) 추가 후 재캡처.

**사용자 영향**: 제품 UX 영향 미확증(최대 1프레임 플리커 추정). 확정 영향은 리뷰 파이프라인: 공용 뱅크 오염으로 타 리뷰어가 이 띠를 ADR-B 위반 배지로 오판할 위험 — 본 상관 단계에서 해당 오판 발견은 0건이었음.

**디자인 근거**:

- §8-4 offscreen/하네스 아티팩트 의심 시 investigation_needed 강등·원장 기록
- 구조적 취약(방어적 코딩) — 삭제 지연 경로에서 유령 페인트 가능한 구현

**코드 증거**:

- src/hwpxfiller/gui/run_view.py:343-348 · txt_view.py:158-163 (takeAt+deleteLater만)
- scratchpad/ui-review/capture_bank.py:174-189 (pump가 DeferredDelete 미발송)
- src/hwpxfiller/gui/style.py:39 (MISSING_BG=#fbe6e3 — 블록 픽셀 실측 일치)

**근본 원인**: 칩 교체가 deleteLater 지연 삭제에만 의존 + 하네스가 exec 루프 없이 processEvents만 구동.

**권고**: 제품: hide()/setParent(None) 선행(1줄 방어). 하네스: sendPostedEvents 추가 후 C군·E군 재캡처(뱅크 오염 해소). 실기기 창모드에서 중첩 루프 노출 여부 저강도 확인.

### UD-33 · 디자인 토큰 '단일 출처' 규율의 사각지대 — 수작성 QSS 중성 회색 raw hex 12종, 예약 metric 스케일 밖 리터럴 산포(radius 7종·간격 ±1px·타입 3종), 인라인 setStyleSheet 예외 2곳(카드 제목 타이포 분열·DANGER 재타이핑), 투명 전경 이디엄 6회 복제 — 공통 원인: 생성기·가드가 상수 블록만 커버

**낮음/convention_deviation** · **수용** · **신뢰도 0.85** · **화면 global·A·E / 렌즈 L2·L1** · **시나리오 A2·E3 (병합 6건)**

**관찰**: 4증상: (1) BASE_QSS에 중성 회색 raw hex 12종(#f3f4f6·#5c626b·#2b3038 등 — MUTED/BORDER/INK 근사 6+쌍, #f6f7f9는 WINDOW_BG 상수와 리터럴 이중 존재). (2) 예약 metric 선언(radius{4,6,9}·space·type) 밖 값 축적 — radius 7종 혼재(3·5·7·11 스케일 밖), 같은 card='true' 인접 카드 여백 (14,12) vs (13,11), 카드 행간 3/2/1 산포(A2에서 카드 밀도 차 관찰), 타입 22/11/14px. (3) 인라인 예외 — _TxtCard 제목 setStyleSheet('font-weight:600')로 인접 heading(15px/700) 카드와 제목 타이포 분열(A2 육안 확인), txt_view 미치환 span의 #c0392b(DANGER 재타이핑)·#fde2dd(MISSING_BG와 다른 제3의 미입력색 — E3에서 칩과 프리뷰 색 상이). (4) QColor(0,0,0,0) 아이템 텍스트 숨김 이디엄 4파일 6회 복제(주석까지 3중 복사).

**기대**: neutral 스케일 토큰 승격+QSS f-string 참조, radius·카드 패딩 상수 수렴, 인라인 2곳 토큰 참조 치환, 이디엄 공용 헬퍼 승격 — 'BASE_QSS·gui/*.py에 raw hex/setStyleSheet 직접 등장 금지' 정규식 가드 테스트.

**사용자 영향**: 카드 제목 위계 어긋남·미입력색 칩/프리뷰 미세 상이가 이미 발생, 팔레트 조정 시 절반만 바뀌는 드리프트 예약, 신규 카드 리스트에서 마법 호출 누락 시 조용한 회귀 가능.

**디자인 근거**:

- 저장소 자기 규율 명시 위반 — style.py:3 '인라인 setStyleSheet 산재 금지', style.py:19 '색 리터럴 중복 금지', design_tokens.json '단일 출처' 선언
- 내부 다수 패턴 자기 모순 — 같은 카드 제목 시맨틱 두 타이포, 같은 미입력 시맨틱 두 배경색, 같은 card 시맨틱 두 여백

**코드 증거**:

- src/hwpxfiller/gui/style.py:64-91,124,157 (raw hex 12종)
- src/hwpxfiller/gui/style.py:50,59,76,79,91,97,143 (radius 7종)
- src/hwpxfiller/gui/home.py:132 vs 107 (인라인 제목)
- src/hwpxfiller/gui/txt_view.py:178-183 (#c0392b·#fde2dd·14px 인라인)
- src/hwpxfiller/gui/home.py:275 vs 308 (카드 여백 ±1px)
- src/hwpxfiller/gui/home.py:348,362,378 · dataset_pool_panel.py:146 · template_manager.py:178 · vocab_workbench.py:123 (이디엄 6회)

**근본 원인**: 토큰 파이프라인이 상수 생성까지만 책임지고 소비측(QSS 본문·위젯 리터럴·인라인 탈출구·공용 이디엄)에 소유자·가드가 없음.

**권고**: 우선순위: 인라인 2곳 즉시 치환(시각 분열 해소) → neutral·radius·카드 패딩 토큰화 → 정규식 가드 테스트 → 이디엄 헬퍼 승격.

### UD-34 · 수량 단위 분류사 혼재 — 레코드가 '건'/'행', 필드가 'N개'/'N필드', 목록 헤더 카운트가 '건'/'개'·무단위 병존(같은 매트릭스 화면 안에서도 로그 '3행' vs 게이트 '1건 이상')

**낮음/convention_deviation** · **수용** · **신뢰도 0.85** · **화면 global / 렌즈 L5** · **시나리오 D7·C2·D8**

**관찰**: D7: 로그 '데이터 겨눔: … — 3행' vs 같은 화면 게이트 '레코드를 1건 이상 선택하세요'. C2: '미입력 1필드' vs 다수파 '필드 N개'. D8: 헤더 '매핑 프로파일 2개' vs 홈·템플릿·풀 'N건'. B5: '채움 9 · 빈 값 3' 무단위.

**기대**: 단위 규약 1벌 — 레코드=건, 필드=개('필드 N개' 어순), 목록 카운트 분류사 통일.

**사용자 영향**: 같은 축인지 재해석 비용·일관성 신뢰 저하 — 비차단 마찰.

**디자인 근거**:

- 내부 다수 패턴 위반 — 같은 수량 축 복수 표기

**코드 증거**:

- src/hwpxfiller/gui/matrix_view.py:255 · matrix_state.py:127
- src/hwpxfiller/gui/run_state.py:392 · run_view.py:490
- src/hwpxfiller/gui/vocab_workbench_state.py:76 · home_state.py:197

**관련 RC**:

- RC-26 부분 겹침(용어표의 단위 축 누락)

**근본 원인**: 수량 분류사 규약 부재.

**권고**: 용어표에 단위 행 추가 후 일괄 치환.

### UD-35 · NaraAcquireDialog만 BASE_QSS 자기 적용 누락(최상위 표면 10곳 중 유일) — 부모 상속 의존이라 무부모/비스타일 문맥에서 primary 위계·danger 실패색·카드 룩 통째 소실

**낮음/convention_deviation** · **수용** · **신뢰도 0.75** · **화면 D / 렌즈 L1·L4** · **시나리오 D3·D5 (병합 2건)**

**관찰**: D3~D5(무부모 인스턴스): 네이티브 회색 룩 — '가져오기' primary 마크 무효(죽은 마크), D5 취득 실패 문구가 danger 적색 없이 무채색.

**기대**: 생성자에 self.setStyleSheet(BASE_QSS) 1줄(형제 pipeline_builder.py:49 미러).

**사용자 영향**: 현 앱 흐름에선 가려짐 — 잠재 마찰+창 자립 규율 이탈. 부수로 캡처 뱅크 D3~D5의 실앱 대표성 훼손.

**디자인 근거**:

- 저장소 자기 규율 — style.py:5-6 창 자립 선언
- 내부 다수 패턴 — BASE_QSS 자기 적용 9/10 중 유일 예외

**코드 증거**:

- src/hwpxfiller/gui/nara_view.py:51-89 (setStyleSheet 부재·BASE_QSS 미임포트)
- src/hwpxfiller/gui/pipeline_builder.py:49 (대조)

**근본 원인**: 스타일된 부모 아래서만 열린다는 암묵 전제.

**권고**: 1줄 추가 후 D3~D5 재캡처(대표성 회복).

### UD-36 · 홈 보조 텍스트의 배치·위계 규율 부재 — 부제 '내 작업 보관함'이 헤더 버튼 3개 뒤 최우단으로 표류, 패널 부연 2건만 muted 미적용

**낮음/convention_deviation** · **수용** · **신뢰도 0.75** · **화면 A / 렌즈 L1** · **시나리오 A1·A2**

**관찰**: A1·A2·W1: 부제가 화면 최우단 표류(무엇의 라벨인지 불명), '누름틀 템플릿 + 매핑 → .hwpx 생성' 등 부연 2건은 본문색(같은 화면 다른 보조 텍스트는 전부 muted).

**기대**: 부제는 제목 인접, 같은 관계의 부연 라벨은 화면 전체 동일 muted 위계.

**사용자 영향**: 보조 텍스트 위계가 오락가락해 본문/부연 구분 학습 비용 — 비차단 마찰.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — 카드 메타·최근 실행 등 다수 패턴(muted+인접)에서 3건 이탈

**코드 증거**:

- src/hwpxfiller/gui/home.py:192-193,205 (부제가 버튼 뒤)
- src/hwpxfiller/gui/home.py:226,250 (mark 미적용 부연 2건)

**근본 원인**: 보조 텍스트 배치·위계 규율 부재로 라벨마다 개별 판단.

**권고**: sub를 title 직후로 이동, 부연 2건 muted 적용.

### UD-37 · 읽기전용 경로 필드가 포커스 체인에 남아 스텝1 첫 포커스 착지 — :focus 파랑 테두리+전체 선택이 :read-only 회색 룩을 덮어 '편집하라'와 '편집 불가' 신호 동시 발신(스텝2 동일 필드는 회색 렌더로 자기 모순)

**낮음/convention_deviation** · **수용** · **신뢰도 0.70** · **화면 B / 렌즈 L1·L4** · **시나리오 B1·B4 (병합 2건)**

**관찰**: B1·B2·B3: 템플릿 경로 필드가 PRIMARY 포커스 테두리+SELECT_BG 전체 선택으로 렌더(유일한 실행동 '찾아보기…'는 비포커스). B4 대조: 같은 시맨틱의 데이터 경로 필드는 비포커스라 read-only 회색.

**기대**: ed_path.setFocusPolicy(ClickFocus/NoFocus)로 첫 포커스를 찾아보기 버튼에, QSS에 QLineEdit:read-only:focus 규칙 추가로 read-only 룩이 포커스보다 우선.

**사용자 영향**: 경로 직접 타이핑 시도(무반응)·키보드 탭 1회 낭비 — 매 저작 세션 첫 화면에서 반복되는 소소한 마찰.

**디자인 근거**:

- 내부 자기 모순 — style.py:63(:focus 편집 활성 신호) vs :64(:read-only 비활성 신호)가 같은 위젯에 동시 적용, 같은 위저드 내 동일 시맨틱 두 렌더

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:69-75,309-310 (읽기전용+포커스 정책 미조정)
- src/hwpxfiller/gui/style.py:63-64 (신호 충돌)

**근본 원인**: 읽기전용 표시 필드를 포커스 사슬에 남긴 채 공용 :focus 스타일 상속.

**권고**: 포커스 정책 조정 + read-only:focus QSS 규칙 + 페이지 표시 시 찾아보기 버튼 setFocus.

### UD-38 · 매핑 행 상태색 밴드 단절 — 상태색을 QTableWidgetItem 배경으로 구현해 cellWidget 4열(데이터 항목·변환·표시형·구분자)에 닿지 않음, 미매칭 빨강이 좌우 파편으로 찢김

**낮음/convention_deviation** · **수용** · **신뢰도 0.70** · **화면 B / 렌즈 L1** · **시나리오 B5**

**관찰**: B5·W2: 미확정/미매칭 행 색이 확정·필드·미리보기 3열에만 칠해지고 가운데 ~500px 위젯 열은 무색 — 색 밴드가 좌우로 갈라짐.

**기대**: 행 상태가 연속 색 밴드로 읽히거나 최소한 소스 콤보에 상태 신호 — 위젯 열 동적 프로퍼티+QSS 셀렉터 또는 셀 컨테이너 브러시.

**사용자 영향**: 가로 스캔 중 행 상태를 콤보 열에서 놓침 — 신호 자체는 존재해 비차단 마찰(ADR-D loud 강도 약화).

**디자인 근거**:

- 내부 자기 모순 — mapping_table.py:4의 행 단위 계약 선언 vs 3/7열 적용
- ADR-D 미매칭 loud — 신호 파편화

**코드 증거**:

- src/hwpxfiller/gui/mapping_table.py:392-394 (3열만 setBackground)
- src/hwpxfiller/gui/mapping_table.py:253-278 (cellWidget 열 브러시 무력)

**근본 원인**: 구현 수단(아이템 vs 위젯)이 상태 표현 범위를 결정.

**권고**: 위젯 열에 rowstate 동적 프로퍼티+QSS 배경으로 밴드 연결.

### UD-39 · txt 즉시 기안 화면만 heading(15px) 화면 제목 부재 — 최상위 표면 6곳의 위계 시작점 관례에서 유일 이탈

**낮음/convention_deviation** · **수용** · **신뢰도 0.65** · **화면 E / 렌즈 L1** · **시나리오 E1**

**관찰**: E1~E3: 창 내용이 '템플릿' 콤보 줄로 곧바로 시작, 파일 전체 heading 마크 0회.

**기대**: 최상단에 heading 제목('즉시 기안')+부제(muted) — kpi/heading/body 위계 체계의 화면 단위 적용.

**사용자 영향**: 라우팅 진입 사용자의 순간적 방향 상실·타 화면과 위계 리듬 이질감 — 비차단.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — 최상위 표면 6곳 heading 시작, txt_view만 부재

**코드 증거**:

- src/hwpxfiller/gui/txt_view.py:57-80 (첫 요소가 컨트롤 줄)
- src/hwpxfiller/gui/style.py:112 (heading 토큰 존재)

**근본 원인**: 화면 정체성을 setWindowTitle에만 위임하고 본문 heading 관례 생략.

**권고**: 타 표면 동형의 heading+부제 추가.

### UD-40 · [검증 공백] 캡처 뱅크가 Qt 한국어 번역기 미설치로 촬영 — 위저드 Back/Next/Cancel·완료 모달 Yes/No 영어는 RC-27 회귀 판정 불가, 번역 설치 상태의 '다음' 라벨 2개 공존(레코드 스텝퍼 vs NextButton)도 미확인

**낮음/investigation_needed** · **기각(비회귀)** · **신뢰도 0.60** · **화면 B·C·global / 렌즈 L5·L4** · **시나리오 C6·B5 (병합 2건)**

**관찰**: B1~B7 위저드 하단 '< Back / Next > / Cancel', C6 완료 모달 'Yes/No' 영어 렌더(캡처 실증) — capture_bank.py에 번역기 설치 호출 없음, 실앱은 app.py:258에서 설치.

**기대**: 하네스가 앱 부트스트랩과 동일하게 번역기 설치 후 촬영 — RC-27 회귀 검증 가능화. 라벨 충돌 확인 시 스텝퍼를 '이전/다음 레코드'로 구체화.

**사용자 영향**: 직접 영향 아님(리뷰 인프라 공백) — 단 RC-27 회귀가 실재해도 현 뱅크로는 탐지 불가. 완료 모달은 앱 유일의 Qt 표준 Yes/No 의존 확인이라 번역 실패 시 영어 잔존 표면.

**디자인 근거**:

- §8-4 하네스 아티팩트 의심 시 investigation_needed 강등

**코드 증거**:

- src/hwpxfiller/gui/app.py:21-44,252-258 (번역기 설치)
- src/hwpxfiller/gui/wizard.py:471-473 (스텝퍼 '다음 ▶')
- src/hwpxfiller/gui/batch_run.py:70-73 (표준 Yes/No 의존 모달)

**관련 RC**:

- RC-27 부분(회귀 단정 불가 — 검증 공백)
- RC-30 부분(완료 모달 표면)

**근본 원인**: 캡처 하네스가 main() 부트스트랩을 우회해 위젯 직접 기동.

**권고**: capture_bank.py에 install_korean_translator 추가 후 위저드·모달 재촬영. 완료 모달을 명시 한국어 버튼('폴더 열기'/'닫기')으로 바꾸면 번역기 의존 자체 소거.

### UD-41 · 폼·섹션 배치 규약 부재 — 위저드 스텝1·2는 비정렬 HBox(스텝4만 그리드), 실행 화면 두 경로 행의 입력 시작선 불일치, 매트릭스는 '작업 선택'만 카드 프레이밍(동급 섹션 맨몸)

**낮음/polish** · **수용** · **신뢰도 0.60** · **화면 B·C·D / 렌즈 L1** · **시나리오 B4·C1·D7 (병합 3건)**

**관찰**: B4: 스텝2 라디오 행과 경로 행의 시작 x 상이(HBox), 스텝4는 QGridLayout 정렬(내부 대조). C1: '데이터' 행 x≈38 vs '저장 폴더' 행 x≈55 + 카드/맨몸 섹션 혼재. D7: '작업 선택'만 QGroupBox, '생성 대상 레코드'·데이터·저장 폴더는 맨몸 — 동일 시맨틱 헤더 행(선택 N+전체 선택/해제)이 카드 안/밖 두 렌더.

**기대**: 폼 행은 라벨 열 공유 그리드(QGridLayout/QFormLayout), 동급 섹션은 동일 프레이밍으로 통일.

**사용자 영향**: 시선 기준선이 행마다 흔들리고 섹션 위계가 비대칭으로 읽히는 미세 스캔 마찰 — 비차단.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — §4 L1 '동일 화면 내 동일 관계의 간격/정렬 불일치' 해당(스텝4 그리드가 내부 기준 패턴)

**코드 증거**:

- src/hwpxfiller/gui/wizard.py:68-76,291-316 vs job_editor.py:154-160
- src/hwpxfiller/gui/run_view.py:121-135,166-174
- src/hwpxfiller/gui/matrix_view.py:82-100,121-123

**근본 원인**: 화면·행별 편의 레이아웃 선택 — 공용 폼/섹션 배치 규약 부재.

**권고**: 라벨 열 공유 그리드로 통일, 매트릭스 레코드 섹션 그룹박스 정렬(RC-22 공용층과 조율).

### UD-42 · 매트릭스 세로 공간 예산 자기 모순 — 내부 대부분이 공백인 리스트 2단이 무제한 선호높이를 고집해 표준 크기에서도 페이지 스크롤 발생, 좁은 폭에선 결과 라벨·로그가 접힘 아래(빌더는 setMaximumHeight로 예방한 내부 대조)

**낮음/polish** · **수용** · **신뢰도 0.60** · **화면 D / 렌즈 L1** · **시나리오 W4·D7**

**관찰**: D7(1280×800): 리스트 내부 큰 공백에도 세로 스크롤바로 로그 하단 잘림. W4(980×700): 결과 라벨·로그 전체가 접힘 아래. 기본 크기 resize(780,720)은 더 심함.

**기대**: 주 흐름이 표준 크기에서 스크롤 없이 성립 — job_list 최대높이 캡, 결과·진행을 고정 푸터로.

**사용자 영향**: 생성 완료 후 요약·개별 실패 사유 확인에 스크롤 추가 조작 — 비차단 마찰.

**디자인 근거**:

- 정량 — 표준 뷰포트 스크롤 발생+리스트 내부 공백 각 ~100px+
- 내부 다수 패턴 — pipeline_builder는 보조 리스트 setMaximumHeight(90) 적용(대조)

**코드 증거**:

- src/hwpxfiller/gui/matrix_view.py:96-99,159-163,70
- src/hwpxfiller/gui/pipeline_builder.py:69 (대조)

**근본 원인**: 세로 배분 설계 없이 스크롤 영역으로 초과분 전가.

**권고**: 리스트 높이 캡+결과/진행 고정 푸터 또는 stretch 재배분.

### UD-43 · fb 배지 radius(11px)가 칩 자연 높이(21~24px)의 절반 경계에 걸림 — 글리프 메트릭에 따라 같은 배지 계열이 라운드 필/직각 사각형 두 형태로 분열(missing 칩만 직각·3px 낮음)

**낮음/investigation_needed** · **확정** · **신뢰도 0.55** · **화면 C·E / 렌즈 L1·L3** · **시나리오 C2·E3·E1 (병합 2건)**

**관찰**: C2/C3/C4: '● … — 미입력 확인' 버튼 칩만 직각·높이 21px(이웃 24px, 오프스크린 실측). E1/E3: 미입력 QLabel 칩 전부 직각(코너 픽셀맵 라운딩 전무), 채움 칩은 24px 라운드 필.

**기대**: 같은 fb 배지 계열은 상태 무관 동일 필 형태 — min-height 고정(24px) 또는 radius 하향(9px 이하)으로 어떤 폰트에서도 클램프 미발동.

**사용자 영향**: ADR-E 핵심 컨트롤(미입력 확인 칩)만 형태가 달라 '사각형=다른 종류 문제'라는 거짓 시맨틱 신호 가능 — 실사용 영향은 경미.

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — QSS 선언(radius 11 전 칩)과 실렌더 분열
- 정량 — 높이 21px < 2×radius 22px 클램프 경계 실측

**코드 증거**:

- src/hwpxfiller/gui/style.py:141-161 (fb 전종 radius 11 — 경계 취약 설계)
- src/hwpxfiller/gui/txt_view.py:169-171 (높이가 글리프 메트릭 종속)

**근본 원인**: 배지 radius가 QLabel/QPushButton 자연 높이의 절반과 사실상 같은 값으로 선언되어 Qt의 radius 클램프 동작을 상태별로 다르게 촉발.

**권고**: 실기기 폰트로 재캡처 확인 후 min-height 고정 또는 radius 안전 마진 하향으로 통일.

### UD-44 · 손상 작업 카드가 앱 내 해소 수단 없이 상주 — 같은 목록의 정상 카드는 [삭제] 제공, 손상 카드는 경로 텍스트뿐(해소 불가 상시 경보의 습관화 위험)

**낮음/polish** · **수용** · **신뢰도 0.50** · **화면 A / 렌즈 L4** · **시나리오 A2**

**관찰**: A2: '결단작업.job.json' 손상 카드는 오류문+심경로만 표시, 액션 전무(docstring은 '직접 복구/삭제' 의도 명시). 정상 카드는 [삭제] 보유.

**기대**: 최소 [폴더 열기] 또는 confirm_destructive 경유 [손상 파일 삭제] — 삭제는 이 목록의 기존 어휘.

**사용자 영향**: 비개발자가 임시폴더 경로를 수동 탐색해야 하는 큰 마찰 + 해소 불가 상시 경보의 습관화(danger 신호 전반 잠식).

**디자인 근거**:

- 내부 다수 패턴 자기 모순 — 같은 목록·같은 제거 니즈에 두 상호작용 어휘

**코드 증거**:

- src/hwpxfiller/gui/home.py:92-119 (액션 전무)
- src/hwpxfiller/gui/home.py:79-80 (정상 카드 btn_del)

**관련 RC**:

- RC-05 부분 겹침(노출 착지의 후속 — 해소 동선 부재)

**근본 원인**: 경보의 해소 동선이 설계 범위 밖.

**권고**: [폴더 열기] 최소 추가, 가능하면 확인 경유 파일 삭제.

### UD-45 · 파이프라인 빌더 '닫기'가 조립 중 작업물을 무확인 폐기 — 같은 다이얼로그가 덮어쓰기에는 confirm_destructive를 요구하는 비대칭

**낮음/polish** · **수용** · **신뢰도 0.50** · **화면 D / 렌즈 L4** · **시나리오 D6**

**관찰**: D6 상태(merge 스텝+미리보기 조립)에서 '닫기'(reject 직결)·Esc가 확인 없이 조립 소실. 대조: 이름 충돌 덮어쓰기는 confirm_destructive 경유(:277-285).

**기대**: 더티 상태 닫기에 확인('조립 중인 파이프라인을 버릴까요?') 또는 폐기 재진술 라벨.

**사용자 영향**: 반사적 Esc 한 번에 수 클릭 분량 재작업 — 확인-또는-경보의 조용한 예외.

**디자인 근거**:

- 확인-또는-경보의 상호작용 형태
- 내부 자기 모순 — 같은 다이얼로그의 덮어쓰기만 확인

**코드 증거**:

- src/hwpxfiller/gui/pipeline_builder.py:145-147 (reject 직결)
- src/hwpxfiller/gui/pipeline_builder.py:277-285 (대조)

**관련 RC**:

- RC-15 부분 겹침(확인 정책의 이탈 경로 미포괄)

**근본 원인**: 이탈 경로의 더티 검사 부재.

**권고**: reject 오버라이드에서 더티 시 confirm_destructive 경유(nara_view reject 오버라이드 패턴 재사용).

## 스테이지 착지 기록

### 스테이지 1 · V1(확증·캡처 하네스) 완료 (2026-07-13) — 제품 src 무접촉

캡처 하네스 2결함을 scratchpad 하네스에서 수리(제품 코드 무접촉)하고, 미검증 8건을
신설 확증 시나리오로 재현·판정했다. **미검증 6건 전건 confirmed(refuted 0)**, UD-32·40은
제품 무결로 종결.

- **하네스 수리**: ① 유령 칩 — `grab` 직전 `QApplication.sendPostedEvents(None, DeferredDelete)`
  플러시 추가로 C2~C5·W3·E2·E3의 640px 색 블록 소멸. ② 한국어 번역기 — 하네스가
  실앱 부트스트랩(`gui/app.py:257-258` `install_korean_translator`)을 우회해 위젯을 직접
  기동했던 탓에 영어로 촬영됨. 하네스에 `qtbase_ko` 설치 미러링 → B·C·E 재발행(한국어 확인).
- **UD-40 (기각·비회귀)**: 실앱은 `main()`에서 번역기를 설치하고 실패 시 stderr로 시끄럽게
  경고한다(조용한 폴백 없음). **RC-27 회귀 아님** — 뱅크 오염일 뿐. 부차 관찰(위저드 푸터
  '다음(N)'과 레코드 스텝퍼 '다음 ▶' 공존)은 confirmed — 스텝퍼 라벨 구체화를 **V11**에 경미
  폴리시로 라우팅.
- **UD-32 (기각·제품 무결)**: `_clear_badges`의 `takeAt`+`deleteLater`는 실앱 exec 루프에서
  repaint 전 DeferredDelete가 처리되어 노출 위험이 최대 sub-frame. 제품 방어 1줄
  (`hide()`/`setParent(None)` 선행)은 load-bearing 아님 — V6 라이더 위탁은 트리비얼할 때만.
  실질 피해였던 리뷰 뱅크 오염은 하네스 수리로 해소.
- **확증 6건**(미검증→확정): UD-10(C7 실행 완료 후 재겨눔 시 완료 요약·진행바 잔존, D9 풀
  삭제 후 '등록 완료' 잔존) / UD-26(D6c·E7·F5 — 빈 값 3표면 무표시 흔적 소멸) / UD-28(B8 —
  데이터 스킵 시 22행 전부 미매칭 빨강, 레코드 0/0 안내 부재) / UD-29(D10 — 중지 후 OK 게이트가
  이전 스냅샷 기준 재개방) / UD-30(A4·W5·C8·E6·F4 — KPI·헤딩·배지·파일명 말줄임 계약 부재) /
  UD-43(C2 픽셀 프로브 — missing 칩 21px 직각 vs fill/blank 24px 라운드, radius 11px 클램프
  임계 하회; offscreen 한계 caveat 무효화되어 confirmed 승격).
- **후속 영향**: refuted 0건이라 후속 유닛(V6·V9·V11·V13·V14) 스코프 전건 유지. V2~V5는 수리된
  하네스 판으로 "수리 전후 캡처 쌍" 촬영 가능(이전 뱅크의 C2~C5·W3·E2·E3·B군·C6은 비교 기준 금지).
- 신설 확증 캡처 12종(C7·D9·D6c·E7·F5·B8·D10·A4·W5·C8·E6·F4) + 판정 로그 `_verdicts_V1.txt`,
  수리 하네스(`capture_bank.py`·`v1_scenarios.py`)는 세션 스크래치패드에 보존(휘발 — 재현 경로는
  설계서 §5 레지스트리 + 이 기록).

### 스테이지 1 · V2~V5(코드 수리 4유닛) 착지 (2026-07-13) — 통합 게이트 770 passed

접촉 파일이 완전 직교(테스트 포함 겹침 0)한 4유닛을 병렬 워크트리에서 각자 개발·검증한 뒤
`b2a11ce`(V2)→`89bbbbf`(V3)→`c08e54c`(V4)→`ba538e3`(V5) 순으로 충돌 없이 선형 착지. 통합 후
전체 게이트 재실행 결과 ruff·pyright 통과, pytest **770 passed**(대량 PermissionError는 stale
`.pytest-tmp` 잠금 플레이크 — 깨끗한 basetemp에서 전건 통과 확인, 코드 무관).

- **V2 `b2a11ce`** (UD-12·13·16·23·31): style.py에 `QPushButton[level="danger"]`·`QLabel[level="muted"]`·
  `QLabel[fb="drift"]`·fb `:disabled`·`primary:disabled` 수렴 셀렉터 신설 + 2색 대비 진행바
  (`ContrastProgressBar`). 소비측은 마킹 1~2줄 무행동변경. **셀렉터 계약 테스트 6건 신설**(발화
  (property,value)가 전부 QSS에 매칭되는지 — 무매칭 조용 통과 차단). 리그레션 증거: 계약 테스트가
  수리 전 상태(셀렉터 제거)에서 무매칭 검출 확인.
- **V3 `89bbbbf`** (UD-05·08·14·15·21·27·38): '모두 확정' 1클릭의 미매칭 빈 행 무경고 승격을
  `confirm_destructive`(이름 재진술) 게이트로 차단 — master 재현(확인 0회·is_complete=True) →
  수리 후 비재현(확인 1회·거부 시 미완). 데이터 전이 파기 확인·카운터 위계·퍼지 `제안 NN%` 배지·
  RAW warn 채널·요약 3상태·상태색 밴드 연속화. 링1(mapping_state) Qt-free 유지.
- **V4 `c08e54c`** (UD-09·35): 나라 게이트 잠금 사유 상시 발화(취득 전부터 사유 표시)·삭제 버튼
  danger 마킹(V2 셀렉터로 소생)·`setStyleSheet(BASE_QSS)` 자기 적용. 워크트리 초기 HEAD가 stale이라
  최신 master에서 재분기(라운드 1 U11 교훈 적용).
- **V5 `ba538e3`** (UD-01·45): 소스·스텝 편집 시 미리보기 무효화(nara `_on_query_edited` 패턴
  이식)·저장 유효성 게이트(깨진 조립 loud 거부)·닫기 더티 확인. master 재현(스테일 표 잔존·무검증
  저장) → 수리 후 비재현(표 비움+warn·저장 거부).

후속: 스테이지 2(V6→V7→V8→V9)는 V2 셀렉터·V1 확증 캡처 위에서 진행.

### 스테이지 2 · V6~V9(고심각 뷰 클러스터) 착지 (2026-07-13) — 통합 게이트 ruff·pyright·781 passed

스테이지 1 착지본 위에서 4유닛을 병렬 워크트리 개발, 파일 겹침 0(테스트 포함) 확인 후
`3e48c51`(V6)→`bbe6167`(V7)→`1f615fc`(V8)→`b9a15cb`(V9) 선형 착지. 통합 게이트 ruff 청정·
pyright 0 errors·pytest **781 passed**(basetemp 플레이크는 깨끗한 basetemp로 우회).

- **V6 `3e48c51`** (UD-06·07·10·19·24): 실행 화면 전제조건(데이터·폴더·레코드) 게이트를 인라인
  `_compose_gate`로 흡수(활성 primary+클릭 후 모달의 ADR-E 위반 해소, 초기 상태 사유 발화)·결과
  라벨 수명주기 리셋(C7 완료 후 재겨눔·D9 풀 삭제 후 CONFIRMED→REFUTED)·ack 칩 토글화+
  `unacknowledge`(링1)·컴파일 무토큰 모달→인라인·템플릿 결과 `(text,level)` seam. UD-32 제품 방어
  1줄 라이더(run_view `_clear_badges` hide/setParent). **프롬프트-원장 불일치(UD-07)를 원장 권위로
  올바르게 해소.**
- **V7 `bbe6167`** (UD-03·36·44): 홈 더블클릭·CTA를 `is_runnable()`(badge_level 단일 술어, 링1)에
  연결·손상 카드 더블클릭 크래시(`.job.json.job.json` FileNotFoundError) master 재현→`exists()`
  가드로 비재현·보조 텍스트 위계·손상 카드 해소 동선([폴더 열기]·[삭제]). run_view 무수정(홈·app·
  core 링에서 완결).
- **V8 `1f615fc`** (UD-02·39): txt 완료 동작이 RenderReport 재진술(미입력 N건 병기 warn/전량 ok
  분기)·`_render` 진입부 라벨 리셋(스테일 '✓ 복사 완료' 제거)·muted↔level 배타화+style.py muted/ok
  선언 순서(실효색 #7a7f87→#1e8449 픽셀 확인)·heading 제목. ADR-C/H 준수(차단 미도입).
- **V9 `b9a15cb`** (UD-29): 나라 중지 후 게이트-라벨 정합(D10 재현→비재현) — 잔존 스냅샷 요약 병기.
  V4의 `_set_busy`/`_set_result` 패턴 위에 얹음.

후속: 스테이지 3(V10→V11→V12)은 V6 공용층·V1 확증(UD-28) 위에서 진행.

## 부록 A — RC 라운드 1 대조

related_rc 를 가진 UD 목록. '관계'는 병합·검증 단계가 기록한 원문 그대로다
(회귀 = 라운드 1 착지의 재발/역행, 부분 겹침 = 같은 패턴의 미이식 표면).

| UD | 관련 RC | 관계 |
|---|---|---|
| UD-01 | RC-13 | 부분 겹침(편집→결과 무효화 패턴이 나라 표면에만 착지) |
| UD-01 | RC-14 | 부분 겹침(스테일 결과의 새 표면) |
| UD-02 | RC-30 | 부분 겹침(완료 서사 실패 무언급 — 착지는 batch_run 한정) |
| UD-02 | RC-14 | 부분 겹침(스테일 결과 라벨의 새 표면) |
| UD-02 | RC-13 | 부분 겹침(상태 변경이 기존 ok 신호 미무효화) |
| UD-03 | RC-05 | 부분 겹침(손상 행 노출은 착지, 그 카드의 상호작용 게이트는 신규 증상) |
| UD-03 | RC-23 | 부분 겹침(게이트 모순 신호 패턴의 홈 카드판) |
| UD-04 | RC-22 | 부분 겹침(run/matrix 공용화가 QThread·데이터 겨눔만 이식, ADR-E 게이트는 run_view 전용 잔존) |
| UD-05 | RC-08 | 부분 겹침(저장 가드는 '전부' 비움만 잡음 — 부분 비움 대량 확정은 통과, 같은 부위 새 증상) |
| UD-06 | RC-23 | 부분 겹침(게이트 단일 스냅샷이 필드 상태만 흡수, 실행 전제조건은 모달 경로 잔존) |
| UD-07 | RC-14 | 부분 겹침(문구 성형·스테일 무효화는 착지 — 심각도 시각 채널 부재가 신규 증상) |
| UD-08 | RC-09 | 부분 겹침(스테일 잔존 수리가 '조용한 파기'라는 반대 증상을 남김 + 실패 경로 잔존) |
| UD-08 | RC-23 | 부분 겹침(문구-게이트 모순 신호) |
| UD-09 | RC-13 | 부분 겹침(게이트 무효화 로직은 착지 — '잠긴 이유를 언제 말할지'가 사후 이벤트에만 배선된 신규 증상) |
| UD-10 | RC-14 | 부분 겹침(스테일 결과 라벨 패턴의 새 표면 2곳 — 착지 부위 회귀 아님) |
| UD-12 | RC-15 | 부분 겹침(확인 정책은 착지 유지 — 버튼 시각 등급이 신규 증상) |
| UD-13 | RC-29 | 부분 겹침/후속(어휘 단일화는 착지·회귀 아님 — 시각 컨테이너 이원화와 셀렉터 커버리지 구멍이 신규 증상) |
| UD-16 | RC-29 | 부분 겹침(fb 셀렉터 어휘 재전용은 착지 — 위젯 타입·활성 상태·drift 무구별 렌더가 신규 증상) |
| UD-17 | RC-14 | 부분 겹침(백지 빈 상태 수리가 템플릿 워크숍에만 착지 — 새 표면들 미적용) |
| UD-18 | RC-26 | 회귀(잔존 증거 확인 — 캡처 F3·B5·D7·D8·A1 + 코드 전거) |
| UD-18 | RC-04 | 부분(화면 실도달로 잠복 해제) |
| UD-20 | RC-26 | 부분 겹침(상태축 어휘 침범 축의 잔존/신규 사례) |
| UD-21 | RC-23 | 부분 겹침(표시 결정이 VM·위젯에 쪼개진 패턴이 위저드 1단계에 잔존) |
| UD-24 | RC-14 | 부분 겹침(결과 문구 성형은 착지 — 채널 이원화는 미해소) |
| UD-29 | RC-24 | 부분 겹침(스냅샷 잔존 자체는 계약상 유효 — '무엇이 잔존·수용되는지' 표시가 새 증상) |
| UD-30 | RC-36 | 부분 겹침(같은 성격의 밀도 처치가 매핑 테이블에만 착지) |
| UD-34 | RC-26 | 부분 겹침(용어표의 단위 축 누락) |
| UD-40 | RC-27 | 부분(회귀 단정 불가 — 검증 공백) |
| UD-40 | RC-30 | 부분(완료 모달 표면) |
| UD-44 | RC-05 | 부분 겹침(노출 착지의 후속 — 해소 동선 부재) |
| UD-45 | RC-15 | 부분 겹침(확인 정책의 이탈 경로 미포괄) |

## 부록 B — 기각 기록

### 상관 단계 기각 — 1건

**위저드 2단계 제목 '데이터 선택 (선택)' — '선택' 1단어 2의미 충돌 (B, L5, polish)**

순수 취향 경계 — 원발견 스스로 '취향 경계로 polish 한정'을 자인(confidence 0.55)하고, §8-3 태스크 마찰 입증(오인·재작업·학습 비용의 구체 워크스루)이 '순간적 재독' 수준을 넘지 못함. 내부 다수 패턴 위반도 아니며(다른 화면에 대조 패턴 없음) RC-26 관통 원칙의 확대 적용일 뿐 명시 조항 위반이 아님 — §7 성립 요건상 기각. 수리 자체는 1줄('(선택 사항)')이므로 RC-26 잔존 치환 이슈 작업 시 함께 처리해도 무방하나 독립 결함으로는 불성립.

### 적대 검증 반증 — 1건

**매핑 저작에서 '미매칭(미해결)'과 '의도적 비움 선택'이 같은 '(비움)' 값 — 구별이 일시적 행 배경색뿐이고 확정 순간 두 상태의 흔적 차이가 소멸(ADR-B 3상태 어휘 붕괴)**

기각 판정 근거 요약: 이슈의 high 심각도는 (a) ADR-B 3상태 붕괴, (b) 확정 순간 구별 소멸, (c) 미해결의 조용한 승격 세 기둥에 섰는데 — (a)는 체크박스+콤보+미리보기+행색 조합으로 3상태가 상시 구별돼 불성립, (b)는 캡처 자체(B5/B6 체크박스 열)가 반증, (c)는 행별 확정이 문서화된 명시 선언 행위라 '조용한' 전이가 아니며(confirm-or-alarm의 '묻고 확정하게 하라' 쪽 구현) 진짜 조용한 대량 경로는 별도 '모두 확정' 이슈의 소관. ADR-D hard-stop(빨강+게이트+Next 비활성)은 B5에서 실증돼 '법적 문서에서 빈 채 나갈 위험'은 이 표면 단독으로는 게이트에 막힌다. 살아남는 것은 두 가지 polish급: ① 동일 '(비움)' 문자열의 이중 역할(미선택 기본값 vs 선택된 라벨) — 색·체크박스 부가 채널이 있어 마찰 입증 실패, §8-(iii)에 따라 polish, '(미선택)' 분리 표기는 결함 수리가 아니라 개선 제안. ② 확정-비움 미리보기 순수 빈 공간 — 코드상 참이나 캡처 부재 + HANDOFF:117의 조용한-공란 결정과의 긴장 재해석 필요, 재등재하려면 신규 시나리오 캡처 필수(investigation_needed 경로). 관련 이슈 처리 권고: '모두 확정' 이슈(confirm_all이 미매칭 행 일괄 확정 — ADR-D '개별 확정 강제'와의 긴장)가 이 발견이 겨눈 실위험의 진짜 서식지이므로 그쪽 검증에 본 반증 기록을 교차 참조로 지급할 것.
