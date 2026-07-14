# 라운드 1 리뷰 발견 박제 — 근본 원인 이슈 36건

> **출처**: docs/REVIEW_ORCHESTRATOR.md §9 라운드 1 실행 (2026-07-12).
> 병렬 리뷰 37에이전트(패키지 5개 × UI Auditor/Coupling/Failure + Naming 전역 1패스
> → Cross-Surface Correlator → 이슈별 적대적 Verifier). 원발견 140건을 근본 원인 36건으로
> 병합, 심각도순 상위 20건을 재현+반증 검증에 투입해 **전건 confirmed(기각 0건)**.
>
> **이 문서가 원본이다.** 재현 스크립트·캡처·로그 원물은 세션 스크래치패드에 있었으나
> 세션 소멸과 함께 휘발됐다. 이슈별 상세(재현 절 포함)는 문서 정리(2026-07-14)로
> git 히스토리에 이관됐다 — 하단 "이슈별 상세" 포인터 참조. 파일:라인 인용은
> 2026-07-12 워킹트리 기준이었다(트림 이후 코드는 계속 진화).

## 통계와 판정 범례

- 원발견 140건 → 병합 이슈 36건 (기각 6계열)
- 검증 투입 20건: confirmed 20 / refuted 0 / investigation_needed 0
- 검증 생략 수용(code_smell·convention 중심) 12건, 검증 정원 초과 미검증 4건: RC-21, RC-30, RC-31, RC-33
- 판정: **확정** = 독립 Verifier가 재현 스크립트 실행 + 반증 공격을 통과. **수용** = 정적 교차확증만. **미검증** = 신뢰도 높으나 재현 검증 미실시.

## 패치 추적 표

유닛 배정은 2026-07-12 조치 계획(직교 고립단위 U1~U12; 스테이지 1=U1~U5, 2=U6~U8, 3=U9~U11, 4=U12 — 계획서의 직렬 머지 순서 준수) 기준(변경 시 이 표만 갱신). 상태: `대기` → `착지(<commit>)`.

| ID | 심각도 | 유형 | 판정 | 유닛 | 상태 | 제목 |
|---|---|---|---|---|---|---|
| RC-01 | 치명 | defect | confirmed | U1 | 착지(219f7f2) | 쓰기 경로 전반이 truncate-then-write 비원자 — 저장 실패가 기존 파일(사용자 편집본·저작 원본·작업 JSON·리포트)을 파괴 |
| RC-02 | 치명 | defect | confirmed | U1 | 착지(219f7f2) | 산출물·증거 파일의 디스크 기존 파일 무확인 덮어쓰기 — 충돌 개념이 '배치 내 유일성'으로만 정의됨 |
| RC-03 | 치명 | defect | confirmed | U6 | 착지(bce35ef) | GUI/CLI 흐름 접착층 이중화 — 검증·정책(드리프트 경계 게이트·빈값 표식·원장 조립·나라 취득 검증)이 표면별 병렬 구현이라 공유 프리미티브와 CLI가 게이트 밖 |
| RC-04 | 치명 | defect | confirmed | U2 | 착지(2113cae) | [확정] 템플릿 관리 워크숍 GUI 완전 도달 불가 — hasattr 전방호환 배선이 홈에 없는 시그널을 기다리는 침묵 no-op, 테스트 우회·문서 오기로 3중 은폐 |
| RC-05 | 치명 | defect | confirmed | U2 | 착지(2113cae) | 손상 .job.json 1개가 홈·앱 시작을 통째로 벽돌화 — list_jobs에 파일 단위 격리 없음 |
| RC-06 | 높음 | defect | confirmed | U6 | 착지(bce35ef) | 배치 실행 중 취소 수단 전무 — generate_batch 완주형 루프·워커 무중단·GUI 취소 UI 부재 |
| RC-07 | 높음 | defect | confirmed | U6 | 착지(bce35ef) | 생성 요청이 불변 계획(GenerationPlan)으로 캡슐화되지 않음 — 완료 핸들러가 라이브 위젯/VM 상태를 재읽어 원장이 생성물과 다른 데이터·폴더를 '증거'로 기록, 완료 시 UI 프리즈·실패 경로 상태 미정리 동반 |
| RC-08 | 높음 | defect | confirmed | U3 | 착지(1cf696c) | '전부 비움' 저장 가드가 술어 오류로 dead code — 아무 값도 채우지 않는 작업이 무경고 저장(3자 독립 런타임 실증) |
| RC-09 | 높음 | defect | confirmed | U3 | 착지(1cf696c) | 위저드 세션 상태의 이중 사본 + 내용 불감 캐시 키 — 같은 파일 재선택·소스 토글 후 매핑 스텝이 화면 요약과 모순되는 옛 데이터로 조용히 구동 |
| RC-10 | 높음 | defect | confirmed | U3 | 착지(1cf696c) | 미지 transform의 3중 실패 — 직렬화 경계 무검증 주입, 뷰 미처리 크래시(통지 0), 런타임 조용한 join 폴백으로 서식 미적용 값 무경고 주입 |
| RC-11 | 높음 | defect | confirmed | U5 | 착지(877d50c) | hwpxdiff 변경 그룹 리스트가 문서상 최대 65행 떨어진 독립 변경들을 '연속 N건'으로 거짓 병합 — seq는 변경 방출 서수일 뿐 문서 인접이 아님 |
| RC-12 | 높음 | defect | confirmed | U6 | 착지(bce35ef) | 나라장터 취득·연결시험이 UI 스레드 동기 네트워크 — 이벤트 루프 완전 동결(취소 의도가 fetch 종료까지 전달 불가, 기본 timeout 20s), 생성 경로 QThread와 비대칭 |
| RC-13 | 높음 | defect | confirmed | U4 | 착지(b676d6b) | 취득 성공 후 기간·건수 위젯 편집이 OK 게이트를 무효화하지 않음 — 미검증 기간이 풀에 등록되어 이후 모든 실행이 실패하는 죽은 참조를 조용히 생성 |
| RC-14 | 높음 | defect | confirmed | U2 | 착지(2113cae) | 템플릿 워크숍 패널이 실사용 강도 미달 — library_dir 공급 계약 부재로 백지, 액션 핸들러 4종 예외 무방비(확정 클릭 직후 실패도 통지 0), 스테일 단일 결과 라벨 |
| RC-15 | 중간 | defect | confirmed | U7 | 착지(f0c748f) | 파괴적 확인 정책이 두 계열로 분열 — ADR-E 강화 패턴은 _ack_partial 1곳뿐, 덮어쓰기·삭제 3곳은 기본버튼 미지정 영어 Yes/No라 Enter 반사로 파괴 확정(런타임 실증), 충돌 사실 재진술도 거짓·부재 |
| RC-16 | 중간 | defect | confirmed | U8 | 착지(cf56119) | 예외→사용자 메시지 번역 층 부재 — 3개 CLI가 일상 실패를 원시 traceback으로 노출하고 exit 1이 게이트/부분실패/크래시를 구분 못하며, GUI 오류 문구도 원인 파일·다음 행동을 지목 못함 |
| RC-17 | 중간 | defect | confirmed | U5 | 착지(877d50c) | hwpxdiff 성형·렌더 로직의 뷰 상주(링1 부재) — 같은 DiffResult가 GUI와 CLI HTML에서 다른 낱말 강조로 렌더(8/85행 실측), 사본·라벨 재파싱·팔레트 이원 동반 |
| RC-18 | 중간 | defect | confirmed | U5 | 착지(877d50c) | 섹션 0개 빈 컨테이너 HWPX 쌍을 '변경 없음'으로 단언 — 추출 완전성 신호를 diff 표면 어느 층도 실패로 승격하지 않음 |
| RC-19 | 중간 | defect | confirmed | U5 | 착지(877d50c) | 대규모 전량 개정 문서에서 hwpxdiff 비교가 UI 스레드를 수십 초 동결 — 전쌍 SequenceMatcher.ratio O(N²) + 동기 핸들러(취소·진행 없음) |
| RC-20 | 중간 | defect | confirmed | U8 | 착지(cf56119) | 출력 파일명 패턴 계약 부실 — 기본값 2종이 3링 4곳 산재, 빈 입력 시 화면에 없던 값으로 조용한 폴백, 미치환 {{토큰}}이 무경고로 실파일명이 됨 |
| RC-21 | 중간 | defect | unverified | U8 | 착지(cf56119) | hwpxfiller 최상위 --help가 서브커맨드 6종을 전혀 표기하지 않음 — pre-argparse 수동 디스패치로 도움말이 실제 CLI 표면을 오표현 |
| RC-22 | 중간 | code_smell | accepted | U9 | 착지(216cbd2) | run_view↔matrix_view 사본 8종(QThread 배선·완료/실패 핸들러·teardown·open_folder·나라/풀 데이터 겨눔 3종) — _teardown_thread는 이미 의미가 갈라진 사본 부패 개시 상태 |
| RC-23 | 중간 | convention_deviation | accepted | U9 | 착지(216cbd2) | 게이트 상태의 표시 결정이 VM과 위젯에 쪼개져 모순 신호 — 드리프트 차단 중에도 상단 '사전검증 통과' 녹색 유지, 상태 리프레시 1회당 템플릿 zip 5회 재파싱 |
| RC-24 | 중간 | code_smell | accepted | U4 | 착지(b676d6b) | 취득 결과 스냅샷의 소유가 링2 뷰 — 실패 시 records만 리셋되어 datasource/fields/label에 이전 성공값 잔존, 수용성 판정·위젯 관통도 뷰에 산재 |
| RC-25 | 중간 | code_smell | accepted | U10 | 착지(4403d94) | 미선언 덕타이핑 이음새 — 위저드 주입 2속성(secret_store/nara_fetcher)이 호스트에 정의조차 없어 주입 실수가 조용히 실 자격증명 저장소·실 네트워크로 폴백, 문자열 타입명 검사·미선언 인스턴스 속성 동반 |
| RC-26 | 중간 | convention_deviation | accepted | U12 | 착지(b733c76) | 사용자 용어 체계의 전역 미정렬 — 1개념 다이름(공유 베이스 4이름·fieldize/컴파일), 1단어 다개념('어휘' 3개념, 비움/공란/빈칸 어휘 침범), 라벨↔창 제목 짝 불일치 |
| RC-27 | 중간 | convention_deviation | accepted | U11 | 착지(979ccc0) | 전 한국어 제품에 Qt 표준 문자열이 영어로 잔존 — QTranslator 미설치로 위저드 Back/Next/Cancel·파괴적 확인 &Yes/&No가 영어 |
| RC-30 | 중간 | defect | unverified | U9 | 착지(216cbd2) | 부분 실패 배치의 완료 모달이 실패를 무언급 — succeeded>0만으로 '완료' 서사(run/matrix 동일 사본), 실패 사유는 원시 errno 관통 |
| RC-28 | 낮음 | code_smell | accepted | U10 | 착지(4403d94) | 저작 화면의 링1 연기 잔여 비용 — accept() 5책임 fat handler, _compile_here 인라인 컴파일·IO, 레지스트리 질의·베이스 저장이 뷰 상주, 안내문이 절차 순서의 부수효과 |
| RC-29 | 낮음 | code_smell | accepted | U10 | 착지(4403d94) | CompileState→시각 심각도 매핑이 링2(home)와 링1(template_manager_state)에 상이한 어휘로 이중 존재 + fb 셀렉터 값 어휘가 원 의미와 다른 뜻으로 재전용 |
| RC-31 | 낮음 | defect | unverified | U5 | 착지(877d50c) | hwpxdiff 첫 비교 실패 시 인라인 실패 문구 미설정 — _invalidate_result 조기 반환이 '지울 결과 없음'과 '표시할 메시지 없음'을 동일시 |
| RC-32 | 낮음 | polish | accepted | U5 | 착지(877d50c) | hwpxdiff 세 표면(GUI/CLI/HTML)의 요약·빈 상태 카피가 각자 하드코딩 — GUI만 '변경 없음' 확정 문장 부재, HTML만 번호변경 KPI 부재 |
| RC-33 | 낮음 | defect | unverified | U8 | 착지(cf56119) | CLI lint --vocab이 UTF-8 BOM 파일의 첫 필드명을 오염 — Windows 표준 도구로 만든 어휘 파일이 오탐 off_vocabulary + exit 1 게이트 실패 |
| RC-34 | 낮음 | code_smell | accepted | U11 | 착지(979ccc0) | 파일 다이얼로그 필터 문자열 하드코딩 10곳 — 지원 확장자 단일 출처(data/factory.py)와 드리프트 대기 상태 |
| RC-35 | 낮음 | convention_deviation | accepted | U11 | 착지(979ccc0) | 언더스코어 사명 클래스(_AppController·_JobCard·_TemplateCard)가 사실상 공용 API — 테스트 4파일·docs 4곳이 크로스모듈 임포트/인용 |
| RC-36 | 낮음 | polish | accepted | U11 | 착지(979ccc0) | 매핑 테이블에서 말줄임된 긴 필드명·소스 콤보의 전체 이름 확인 수단(툴팁) 부재 — 유사 접두 필드 오인 확정 위험 |

### 스테이지 1 착지 기록 (2026-07-12) — 리그레션 증거

유닛별 독립 검증 에이전트가 **수리 전 master에서 결함을 런타임 재현 → 수리 커밋에서 동일 절차
전건 비재현**을 확인한 뒤 머지했다(적용 지점 전수 대조 + 회귀 반박 포함, 5유닛 전부 pass·반려 0회).

- **U1** `219f7f2` (RC-01·02): master 6/6 재현(save 직렬화 실패로 111,322B→0B 파괴, ENOSPC 절단,
  HTML 리포트 truncate, 무경고 덮어쓰기, 배치 간 동일 이름 재발급, 원장 무조건 교체) → 전건 비재현.
  truncate-write 잔존 grep 0건. CLI 기본 차단은 의도된 breaking(`--overwrite` 옵트인).
- **U2** `2113cae` (RC-05·04·14): master 15/15 재현 → 전건 비재현. 워크숍 라우트 소생(시그널 직결),
  손상 job 격리 배지, 패널 예외 경계.
- **U3** `1cf696c` (RC-08·10·09): master 3/3 재현 → 비재현. 잔여 보류 1건: wizard `_save_profile`/
  `_save_base`의 동종 술어(공란 커버 계약 가능성) — 라운드 2 검토 소재.
- **U4** `b676d6b` (RC-13·24): master 4증상 재현 → 비재현. 대화상자 산출물 4종을 VM 스냅샷 파생으로
  전환해 부분 잔존을 구조적으로 차단.
- **U5** `877d50c`+`e707837` (RC-17·11·18·19·31·32): master 6/6 재현 → 비재현. RC-19는 재현 기준
  39.3s→4.0s(~10x, 적대 합성 최악 케이스의 O(N²)는 잔존 — 중기 워커 스레드화 과제 유효).
  RC-31(미검증분)은 착수 시 재현 확인 후 수리. 골든 테스트 무변경.

머지 후 전체 게이트(ruff→pyright→pytest) green: 최종 654 passed. 머지 게이트에서 pyright 1건
검출·정합(`e707837` — worktree 자체 검증에 pyright 부재가 원인; 스테이지 2부터 유닛 자체 검증에
pyright 포함).

### 스테이지 2 착지 기록 (2026-07-12) — 리그레션 증거

3유닛 전부 적대 검증 pass(반려 0회). 유닛 자체 검증에 pyright 포함(스테이지 1 교훈 반영).

- **U6** `bce35ef` (RC-03·07·06·12): 게이트 경계 하강(드리프트 재검사·빈값 CLI 이식
  `--ack-empty`·원장 빌더 단일화·나라 resultCode/기간 fail-closed), frozen GenerationPlan,
  협조적 취소, 나라 취득 QThread화(스테일 결과 seq 폐기). 검증자 실 CLI e2e 포함, 679 green.
  잔여 노트: 단일 배치 '루프 도중' 템플릿 교체 창은 매트릭스와 동일 수준(권고 문언 충족),
  matrix_view._pick_from_pool 동기 잔존 — U9에서 흡수 예정.
- **U7** `f0c748f` (RC-15): confirm_destructive 공용 헬퍼(기본=취소·한국어 라벨), 지침 3곳
  + 확장 5곳 + U1 확인 3곳 정렬. Enter 반사 파괴를 런타임 차등 실증(재현→비재현).
- **U8** `cf56119` (RC-16·20·21·33): 오류 번역 경계(crash exit 2), DEFAULT_FILENAME_PATTERN
  단일화('공고서-{{ID}}' — 의도된 breaking), --help 서브커맨드, lint --vocab BOM.
  미검증 2건(RC-21·33)은 검증자가 master에서 최초 재현 확인 후 수리 판정.

머지 통합(메인 세션, U8이 U6 착지 전 베이스라 충돌 8파일 수동 해소): 출력 충돌을
OutputCollisionError 로 분리해 RC-02 차단(exit 1+안내)과 환경성 FileExistsError(exit 2)의
거짓 안내를 차단, 나라 취득 실패는 U6 데이터 경계 게이트(exit 1)로 확정, hwpxdiff 빈 추출
게이트를 diff_documents 로 하강(분리 로드 경로도 게이트 통과). 최종 게이트 707 passed.

### 스테이지 3 착지 기록 (2026-07-12) — 리그레션 증거

3유닛 전부 적대 검증 pass. U9는 반려 1회(WinError 지역화 문자열 미발화 → 실 재현 형태 겨냥
테스트로 박제) 후 pass.

- **U9** `216cbd2` (RC-22·23·30): gui/batch_run.py 공용 실행 계층(BatchRunController·
  DataAcquireController — matrix 풀 복원도 TaskWorker 비동기 파리티), vm.gate_state 단일
  산출(드리프트 차단 중 '통과' 녹색 모순 해소, 리프레시당 재파싱 5→1회), 부분 실패 모달
  발화 + describe_result_error(WinError 5/32/112 코드·한국어 메시지 양면, 원문 보존). 실
  파일 잠금으로 master 재현 → 비재현.
- **U10** `4403d94` (RC-25·28·29): 위저드 secret_store/nara_fetcher 주입 계약 선언(조용한
  실 자격증명·실 네트워크 폴백 → TypeError), 저작 게이트 링1 하강(job_editor_state), 배지
  매핑 링1 단일화(compile_badge.py). source_pointer 타입명 검사 → 선언 프로토콜(개명 내성).
- **U11** `979ccc0` (RC-27·34·35·36): qtbase_ko 번역기 설치(위저드 버튼 한국어), 파일 필터
  상수 단일화(EXCEL_EXTS→file_filters, 하드코딩 9곳 + 재유입 grep 게이트), 언더스코어 클래스
  공개화(무파괴 별칭), 매핑 테이블 툴팁 전체 이름.
  **주의(프로세스)**: U11 구현 worktree가 스테이지 1·2·3 착지 이전 스냅샷에서 출발해 U9가
  옮긴 파일 다이얼로그·U10이 제거한 배지 헬퍼와 의미가 갈라져 머지 4파일 충돌 → 머지를 무손상
  되돌리고(트리 4403d94 복원) 최신 master 위에서 **재구현**(충돌 0으로 fast-forward). 이후
  스테이지의 worktree 베이스 확인을 착수 전 필수로.

최종 게이트 755 passed. 스테이지 3 완료 시점 누적 착지 35/36건 — 남은 것은 U12(RC-26 전역 용어 정렬).

### 스테이지 4 착지 기록 (2026-07-12) — 라운드 1 조치 완주

- **U12** `b733c76` (RC-26): 6개 용어축 전역 정렬 — 사용자 승인 정준 용어(매핑 프로파일 /
  누름틀 변환 / 구판·신판 / 활성·보관) + 비움·빈 값 상태축 분리 + join 라벨·홈 라벨↔창 제목
  정렬. 사용자-가시 문구만 치환, 코드 식별자 무접촉(하위호환 별칭 불요). 24파일 148/-99.
  보류: 데이터셋 3상태(활성/보관/은퇴) 라벨 병합은 별개 액션·버튼 desync 위험으로 경보 위계
  역전만 수리(라벨 병합은 상태머신 축소 선행 필요 — 후속 소재).
  단독 유닛(convention_deviation, 검증 생략 수용 이슈)이라 게이트+grep 정합으로 검증.
  구현 worktree가 구 베이스에서 출발해 최초 1회 중지됐으나(사용자 개입) 최신 master 재기반 후
  재구현 — 충돌 0으로 착지.

## 완주 감사 (36/36 착지)

라운드 1 근본 원인 36건 전량이 12 고립단위·4 스테이지로 착지 완료. critical 5건(RC-01~05)
포함 전 스테이지가 적대 검증(수리 전 재현 → 수리 후 비재현)을 통과했고, 각 유닛 머지 후
전체 게이트(ruff → pyright → pytest+coverage) green을 확인했다. 최종 스위트 **757 passed**.

- 착지 커밋: U1 219f7f2 · U2 2113cae · U3 1cf696c · U4 b676d6b · U5 877d50c(+e707837)
  · U6 bce35ef · U7 f0c748f · U8 cf56119 · U9 216cbd2 · U10 4403d94 · U11 979ccc0 · U12 b733c76.
- 반려 1회(U9 RC-30 WinError 지역화 문자열 미발화 → 실 재현 형태 테스트로 박제 후 pass).
- 머지 중재 3건(U8): OutputCollisionError 분리, 나라 취득 exit 1 확정, 빈 추출 게이트 하강.
- 미검증 4건(RC-21·30·31·33)은 담당 유닛이 수리 전 재현 확인 후 수리(재현 불가 없음).

의도된 breaking(자동화 영향 가능): (1) 산출물 덮어쓰기 기본 차단 + `--overwrite` 옵트인(RC-02),
(2) 빈값 기본 차단 + `--ack-empty`(RC-03), (3) 기본 파일명 패턴 `공고서-{{ID}}`(RC-20),
(4) 데이터에 없는 파일명 토큰 생성 전 오류(RC-20).

후속 소재(라운드 2 검토): wizard `_save_profile`/`_save_base` 동종 술어(U3 보류), 데이터셋
3상태 라벨 병합(U12 보류), hwpxdiff GUI 모달 판본 미지목(U8 노트), hwpxdiff 대형 문서 비교
워커 스레드화(U5 중기 과제). 라운드 2(F3/F5/F6/F8/F9/F11)·라운드 3(F14 패키징)은 설계서 §6 유효.

## 이슈별 상세 (재현·코드증거) — git 히스토리로 이관

RC-01~36의 이슈별 상세(근본 원인·사용자 영향·코드 증거·병합 증상·재현·권고)는
문서 팽창 정리(2026-07-14)로 이 문서에서 걷어냈다. 앵커(ID·심각도·판정·유닛·착지
커밋)는 위 **패치 추적 표**에, 검증·회귀 증거는 **스테이지 착지 기록**·**완주 감사**에
온전히 남는다. 전문이 필요하면 `git log -p --follow docs/REVIEW_ROUND1_FINDINGS.md`
또는 트림 커밋의 부모 리비전에서 복원한다. 코드·테스트가 인용하는 것은 RC-번호 앵커뿐이므로
(예: test_atomic.py `(RC-01)`) 추적 표만으로 추적성이 유지된다.

## 기각 계열 (Correlator 판단 — 사유 보존)

- failure:F4 '[반증·양호 확인] 키 마스킹 전 실패 경로 견고' — 결함이 아니라 반증 시도의 긍정 기록(GUI 라벨·연결시험·CLI traceback·원장 전부 키 원문 무노출, 특수문자 키 포함). 이슈 목록에서 제외하되 Verifier에게 '비밀 취급 축은 재검증 불요'라는 정보로 전달할 가치만 있음.
- ui:F12 'KPI 타일 4장이 창 전폭으로 늘어나 여백 과다' — 기능 무영향 순수 심미로 취향-결함 경계에 있고 confidence 0.7로 증거 기준에 미달(리뷰어 스스로 픽셀성 유보). addStretch 1줄 개선은 RC-32류 F12 폴리시 수선 시 부수 반영 가능하나 독립 이슈로는 기각.
- failure:F12 '파일 2개 동시 투입 시 구판/신판 역할을 투입 순서로 추측' — 두 경로가 읽기전용 입력칸에 항상 표시되어 완전한 침묵이 아니고, 동작이 코드 주석으로 문서화된 관례이며 파일 다이얼로그·개별 드롭 등 정상 경로가 주류. 실피해 시나리오(반전 오독)의 개연성 대비 근거가 얇아 기각 — 원하면 RC-32 문구 개선에 '배정 결과 1줄 고지'로 흡수 가능.
- ui:F1 '작업 덮어쓰기 확인 기본 버튼 미지정 — Enter 반사 확인 가능성(investigation_needed, conf 0.6)' — 기각이 아닌 해소로 제외: failure:F1 P1이 QTest Return 키 주입으로 '&Yes' 클릭을 런타임 확정하여 RC-15에 확정 증상으로 병합됨(별도 조사 항목 불요).
- 리뷰어 간 중복 발견 전량(동일 대상의 2~4중 보고: 드리프트 경계 비대칭 3건, 원장 이중화 3건, 덮어쓰기 2건, 취소 2건, dead guard 3건, F7 도달 불가 3건, 파일명 기본값 4건, _snippet 3건, 그룹 거짓 병합 2건, coalesce 갈림 3건, resultCode 미검증 3건, 동기 네트워크 4건, 부분 실패 모달 2건, 테스트 우회·문서 오기 각 2건 등) — 기각이 아니라 각 RC 이슈로 병합(교차 확증은 해당 이슈 confidence에 반영).
- 기능별 명명 지적(ui:F1 wizard.py 명명 잔재, coupling:F1 mapping_state docstring 스테일, F4/F12 용어 소항목) — Naming 전역 패스 우선 규칙에 따라 RC-26 하위 증상으로 흡수(독립 이슈 기각).

