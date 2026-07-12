# 라운드 1 리뷰 발견 박제 — 근본 원인 이슈 36건

> **출처**: docs/REVIEW_ORCHESTRATOR.md §9 라운드 1 실행 (2026-07-12).
> 병렬 리뷰 37에이전트(패키지 5개 × UI Auditor/Coupling/Failure + Naming 전역 1패스
> → Cross-Surface Correlator → 이슈별 적대적 Verifier). 원발견 140건을 근본 원인 36건으로
> 병합, 심각도순 상위 20건을 재현+반증 검증에 투입해 **전건 confirmed(기각 0건)**.
>
> **이 문서가 원본이다.** 재현 스크립트·캡처·로그 원물은 세션 스크래치패드
> (`C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1`)에 있었으나 세션 소멸과 함께 휘발된다 —
> 각 이슈의 '재현' 절이 재작성 가능한 수준으로 방법을 보존한다.
> 파일:라인 인용은 2026-07-12 워킹트리 기준(패치 진행에 따라 어긋날 수 있음).

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
| RC-26 | 중간 | convention_deviation | accepted | U12 | 대기 | 사용자 용어 체계의 전역 미정렬 — 1개념 다이름(공유 베이스 4이름·fieldize/컴파일), 1단어 다개념('어휘' 3개념, 비움/공란/빈칸 어휘 침범), 라벨↔창 제목 짝 불일치 |
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

## 치명 (critical) — 5건

### RC-01 · 쓰기 경로 전반이 truncate-then-write 비원자 — 저장 실패가 기존 파일(사용자 편집본·저작 원본·작업 JSON·리포트)을 파괴

- **심각도/유형**: critical/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F2, F10, F1, F7, F13 · **유닛**: U1
- **근본 원인**: core 공용 원자 쓰기 헬퍼(temp+os.replace) 부재로 최소 6개 쓰기 지점이 각자 open('w'/'wb')로 최종 경로에 직접 기록 — 오픈 시점 truncate가 직렬화·쓰기 실패와 무관하게 기존 내용을 선(先)파괴한다. §8-12(LESSONS K/A 기왕 인지)의 전 저장소 확산판.
- **사용자 영향**: 법적 효력 문서의 사용자 수정본·저작 원본 템플릿·durable 작업 자산이 디스크풀·강제종료·네트워크 드라이브 오류 한 번으로 복구 불가 소실되고, 자리에 열리지 않는 손상 파일이 남는다.
- **코드 증거**: hwpxcore/package.py:70-72(본 세션 재확인: open(path,'wb') 직접 기록, temp+replace 없음), core/job.py:122-125, core/mapping.py:171-174, core/fill_ledger.py:371-373, hwpxdiff/cli.py:26-29, gui/template_manager_state.py:256-258(입력과 동일 경로에 pkg.save)
- **병합 증상**:
  - HwpxPackage.save에 ENOSPC 주입 시 사용자 편집본 318B→4096B 불완전 zip 조각으로 파괴, GenerateResult.ok=False만 보고(failure:F2F10 FX2 실증)
  - F7 컴파일(apply_fieldize)이 사용자 저작 원본 템플릿 위에 in-place 저장 — 직렬화 예외 주입 시 원본 375B→0B 소실, 백업 없음(failure:F7 W3)
  - Job.save 재저장 중 실패 시 기존 작업 JSON 22B 절단 → RC-05(앱 벽돌화)로 연쇄(failure:F1 P2 실증)
  - MappingProfile.save 동형 — 공유 베이스·매핑 파일 동일 위험
  - fill-ledger.json 사이드카 write_text 비원자
  - hwpxdiff --html이 truncate-then-render 순서 — 렌더 실패 시 기존 리포트 5000+B→0B 파괴(FX C6) + 요약을 쓰기 전에 stdout 선방출(C4)
- **권고**: core에 원자 쓰기 유틸(같은 볼륨 임시파일 기록 후 os.replace) 1개를 두고 package.save/Job.save/MappingProfile.save/fill_ledger/hwpxdiff --html이 공유. hwpxdiff는 render_html을 open 전에 선평가. apply_fieldize는 추가로 원본 .bak 보전 또는 --out 분리 검토.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 repro_rc01.py + 출력 repro_output.txt (증거 폴더 ...\scratchpad\review-round1\verify\RC-01\, 저장소 무수정·작업 파일은 전부 work/ 사본). 결함 주입은 대상 경로 한정 builtins.open/pathlib.Path.open 래퍼(ENOSPC 부분쓰기)와 HwpxPackage.to_bytes/diff.render_html 예외 패치, finally 복원. 5개 시나리오 전건 재현: [A] engine.generate가 기존 유효 산출물(96,644B, PK헤더 확인) 위에 재생성 중 ENOSPC → 4,096B 불완전 조각으로 파괴, HwpxPackage.open 재오픈 BadZipFile, 보고는 GenerateResult.ok=False('저장 실패: [Errno 28]...')뿐이며 원상복구·정리 없음(src/hwpxfiller/core/engine.py:57-60). [B] 순서 하자 단독 증명 — to_bytes 예외 주입 시 111,322B→0B: src/hwpxcore/package.py:71-72가 open(path,'wb')를 먼저 열고(=truncate) to_bytes()를 나중에 평가. [C] TemplateManagerViewModel.apply_fieldize(src/hwpxfiller/gui/template_manager_state.py:256-258)가 저작 RAW 원본과 같은 경로에 pkg.save → 직렬화 실패 주입 시 원본 375B→0B, .bak 등 동반 파일 전무. [D] Job.save(src/hwpxfiller/core/job.py:122-125, Path.write_text) 재저장 중 ENOSPC → 기존 작업 JSON 577B→24B 절단, Job.load JSONDecodeError. [E] hwpxdiff CLI(src/hwpxdiff/cli.py:26-29) — render_html 실패 주입 시 기존 리포트 9,613B→0B(truncate-then-render), 실패 전에 stdout 요약 186자 선방출(C4)도 관찰. MappingProfile.save(core/mapping.py:171-174)·fill_ledger(core/fill_ledger.py:371-373)는 D와 동일 Path.write_text 관용구로 정적 확인(동형).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 3방향 전부 실패(이슈 생존). ① 인용 파일:라인 6곳 전부 직접 열어 대조 — 전부 실코드와 일치(package.py:70-72, job.py:122-125, mapping.py:171-174, fill_ledger.py:371-373, hwpxdiff/cli.py:26-29, template_manager_state.py:256-258). ② 기존 가드 탐색 — src 전체 grep에서 os.replace/NamedTemporaryFile/mkstemp/atomic/.bak 0건, 원자 쓰기 헬퍼·백업 부재 확정. docs/UNIVCONTRACTOR_LESSONS.md:47,59이 K/A 갭을 '🔧 소형 갭(미반영)'으로 기록 — 인지됐으나 미수정임을 문서가 자인. 부분 완화로 CLI fieldize는 별도 --out에 기록(cli.py:85)하고 scan_preview는 읽기 전용(dry-run 기본)이나, GUI 워크숍 apply_fieldize의 in-place 파괴와는 무관. 오히려 grep에서 이슈가 안 꼽은 동형 지점 추가 발견(core/dataset_pool.py:110, cli.py:46·200, gui/txt_view.py:202, wizard.py:209) — '전 저장소 확산' 서술을 강화. ③ 재현 실패 유도 — 5개 전부 1회에 재현. 유일한 정정 뉘앙스: root_cause의 '직렬화 실패와 무관하게 선파괴'는 package.py·hwpxdiff cli 2곳에만 정확(페이로드를 open 후 평가). Path.write_text 3곳(job/mapping/ledger)은 json.dumps가 truncate 전에 평가되므로 순수 직렬화 예외로는 파괴 안 되고, ENOSPC·강제종료·네트워크 드라이브 등 쓰기 중 I/O 실패로만 파괴된다(D로 실증) — 이슈의 핵심 주장(비원자 쓰기로 기존 durable 자산 파괴)은 그대로 성립. 심각도 critical 유지 근거: 법적 효력 문서·저작 원본·작업 JSON의 복구 불가 소실 + 파괴 자체는 조용한 부수효과(확인-또는-경보 원칙 위반 냄새로 상향 규칙 해당) + 수정은 공용 헬퍼 1개로 저비용.

</details>

<details><summary>Verifier 비고</summary>

code_evidence(전부 직접 확인): src/hwpxcore/package.py:70-72(open('wb') 선truncate 후 to_bytes 평가), src/hwpxfiller/core/engine.py:57-60(save 실패 시 ok=False 보고만·잔해 미정리), src/hwpxfiller/core/job.py:122-125, src/hwpxfiller/core/mapping.py:171-174, src/hwpxfiller/core/fill_ledger.py:371-373, src/hwpxdiff/cli.py:26-29(stdout 선방출+truncate-then-render), src/hwpxfiller/gui/template_manager_state.py:256-258(입력 경로 in-place pkg.save·백업 없음), docs/UNIVCONTRACTOR_LESSONS.md:47(K 갭 기왕 인지). 추가 동형 지점: src/hwpxfiller/core/dataset_pool.py:110, src/hwpxfiller/cli.py:46·200, src/hwpxfiller/gui/txt_view.py:202. runtime_evidence: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-01\repro_rc01.py 및 repro_output.txt(5/5 '확인' 판정). 권고 타당성 검증됨: temp+os.replace 공용 헬퍼 1개면 6+개 지점 전부 커버, hwpxdiff는 render_html을 open 전에 선평가(현재 코드가 정반대 순서임을 B·E로 실증), apply_fieldize는 .bak 보전 또는 --out 분리. 이슈 수치 미세 차이(원문 318B/22B vs 재현 96,644B/24B)는 입력 데이터 차이일 뿐 기제 동일.

</details>

### RC-02 · 산출물·증거 파일의 디스크 기존 파일 무확인 덮어쓰기 — 충돌 개념이 '배치 내 유일성'으로만 정의됨

- **심각도/유형**: critical/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.98 · **기능**: F2, F10, F7 · **유닛**: U1
- **근본 원인**: OutputNamer._dedupe가 self._seen(이번 배치 발급분)만 검사하고 디스크를 조회하지 않으며(§8-2), batch/validate_generate/CLI 어디에도 사전 충돌 검사·--overwrite 계약이 없다. GUI 기본 저장 폴더가 '템플릿 폴더\Results' 고정이라 같은 작업 재실행=같은 폴더 — 덮어쓰기가 예외가 아니라 기본 동선.
- **사용자 영향**: 발송·결재된 공고서의 수기 보정본이 재실행 한 번으로 흔적 없이 소실 — 이 저장소가 자임한 최고 위험 표면(법적 효력 문서 디스크 기록)에서의 무경고 데이터 파괴. RC-01(비원자)과 결합하면 '실패한' 재생성조차 파괴한다.
- **코드 증거**: naming.py:86-87,94-105(본 세션 재확인: self._seen만 검사, 디스크 미조회), batch.py:51-53(target 존재 검사 없음), run_state.py:272-307(validate_generate에 기존 파일 검사 없음), run_view.py:163-164(기본 out=템플릿\Results), fill_ledger.py:371-373, wizard.py:207-209
- **병합 증상**:
  - 같은 폴더 2회 배치 실행 시 사용자 수정본(sentinel 32B)이 96,723B 재생성본으로 무경고 교체 — 모달·로그·stderr 어디에도 흔적 0건, GUI/CLI 동일(ui:F2F10 S3 실증)
  - OutputNamer의 _seq·_seen이 배치마다 리셋 — 날짜/seq 패턴도 같은 날 재실행은 구조적으로 전건 충돌
  - fill-ledger.json이 매 실행 무조건 교체 — 이전 실행의 '증거'가 조용히 소실
  - F1 _compile_here가 기존 .compiled.hwpx 존재 확인 없이 pkg.save — 사람이 손봤을 컴파일본 무경고 덮어쓰기 + x.compiled.compiled.hwpx 증식
- **권고**: OutputNamer 또는 generate_batch에 디스크 존재 검사 주입 → GUI는 실행 전 '기존 N개 파일을 덮어씁니다' 확인, CLI는 --overwrite 없이는 차단. 원장은 실행별 타임스탬프 파일. _compile_here는 존재 시 확인 또는 접미사.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-02\repro_rc02.py (로그: 같은 폴더 repro_log.txt, 산출물: out\). 절차·관찰: (1) CLI 서브프로세스로 tests/corpus/scenario/templates/입찰공고서.hwpx + 조달_한글.csv를 --out 동일 폴더 --ledger로 실행 → 3/3 성공, 공고-2026-001.hwpx 96,723B 생성. (2) 그 파일을 32B sentinel("사용자 수기 보정본" 모사)로 교체. (3) 동일 명령 2회차 실행 → exit 0, sentinel이 96,723B 재생성본으로 교체됨. stdout+stderr 전체에서 '덮' 0건, 'overwrite' 0건 — 무경고·무흔적 파괴 실증. (4) fill-ledger.json sha 12afd963→595112cf로 무조건 교체(이전 실행 증거 소실; fill_ledger.py:371-373 write_text 무조건, cli.py:398 고정 파일명). (5) GUI 링1 게이트 런타임 검증: out 폴더에 산출물이 실존하는 상태에서 RunViewModel.validate_generate([0], out) == [] — 기존 파일 관련 차단·경고 전무(GUI도 동일 generate_batch 경로라 결과 동일). 코드 증거(전부 직접 열어 확인): naming.py:86-87,94-105(self._seen만 검사, 디스크 미조회 — _seq·_seen이 인스턴스 생성마다 리셋), batch.py:47-53(mkdir 후 target 존재 검사 없이 engine.generate), engine.py:57-58(pkg.save 무조건), run_state.py:272-307(validate_generate에 기존 파일 검사 부재), run_view.py:162-164(기본 out=템플릿 폴더\Results 고정 → 재실행=같은 폴더가 기본 동선), cli.py:299-324(argparse 전체에 --overwrite/--force 부재), cli.py:360(무가드 generate_batch), wizard.py:207-209(compiled_path 존재 확인 없이 pkg.save — with_suffix가 마지막 .hwpx만 치환하므로 x.compiled.hwpx 재컴파일 시 x.compiled.compiled.hwpx 산출도 경로 산술상 성립).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 3방향 모두 실패(이슈가 옳음): (1) "다른 곳에서 가드되는가" — src 전체를 overwrite/덮어/--force/exists() grep: 생성 경로에는 전무. 오히려 작업 레지스트리(job_editor.py:99 "덮어쓸까요?" 확인), 파이프라인 풀(pipeline_builder_state.py:244-247 overwrite=True 명시 없으면 ValueError + 테스트 test_pipeline_builder_state.py:219), 어휘 베이스(wizard.py:702 확인 대화상자)에는 confirm-or-alarm 덮어쓰기 게이트가 구현·테스트됨 — 저장소 스스로의 규범이 저위험 표면에는 적용되고 최고 위험 표면(생성 문서)에만 빠져 있어 '의도된 동작' 해석이 성립하지 않음. (2) "문서화된 의도인가" — docs grep: UI_DESIGN_DECISIONS.md:184 및 UI_PROTOTYPE_APPB.html:651이 '조용한 덮어쓰기 방지·경고 승격'을 설계 원리로 명시 — 의도는 오히려 경고 쪽. (3) "테스트가 이 동작을 계약으로 삼는가" — tests grep: test_engine.py:54는 배치 내 _1 접미사 유일화만 검증(디스크 충돌 아님), 디스크 기존 파일 보존을 다루는 테스트 0건. 유일한 한정: fill-ledger는 opt-in(--ledger/체크박스 기본 꺼짐)이고, wizard의 .compiled 덮어쓰기·증식은 코드 판독 확정이나 런타임 재현은 안 함(모달 다중 우회 필요, 라인이 무조건 pkg.save라 판독만으로 충분). 심각도는 critical 유지 — 법적 효력 문서의 무경고 파괴가 기본 동선에서 재현되었고, 저장소 원칙(조용한 동작 1단계 상향)까지 적용하면 하향 근거 없음.

</details>

<details><summary>Verifier 비고</summary>

보강 사실 2건: (a) 날짜/seq 패턴의 구조적 전건 충돌 주장도 성립 — OutputNamer는 batch.py:48에서 호출마다 새로 생성되어 _seq=0·_seen=∅에서 시작(naming.py:86-87)하므로 같은 날 재실행은 동일 이름 전건 재발급. (b) 원장의 generated_at이 초 해상도라 같은 초 내 재실행이면 내용이 우연히 동일해 교체가 해시로도 안 보임 — '증거 소실'의 관측 가능성이 더 낮아지는 부수 정황(재현 스크립트에 1.5s 지연으로 처리). 권고안(디스크 존재 검사 주입 + GUI 확인/CLI --overwrite 계약 + 원장 타임스탬프 파일명)은 기존 pipeline_builder_state.py:244 패턴을 그대로 이식 가능해 최소 책임 경계에 부합. RC-01(비원자 저장 package.py 경유 engine.py:58)과의 결합 악화 주장은 본 검증 범위 밖이나 경로 공유는 확인됨.

</details>

### RC-03 · GUI/CLI 흐름 접착층 이중화 — 검증·정책(드리프트 경계 게이트·빈값 표식·원장 조립·나라 취득 검증)이 표면별 병렬 구현이라 공유 프리미티브와 CLI가 게이트 밖

- **심각도/유형**: critical/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F2, F10, F4 · **유닛**: U6
- **근본 원인**: 오케스트레이션이 cli.py와 run_state.py(RunViewModel)에 각각 존재하고(§2-1), 검증이 실제 경계(생성 프리미티브·데이터층)가 아닌 각 호출자 소유다(§8-5·§8-6 병합). 그래서 검사는 3중화되면서 정작 generate_batch와 NaraStdDataSource.records()는 무방비 — 새 호출측(파이프라인·API·워커)은 자동으로 게이트 밖이 된다.
- **사용자 영향**: 자동화 파이프라인이 미입력 공고서·인증 실패·드리프트 문서를 전부 성공(exit 0)으로 통과시킨다. 원장(감사 증거)은 표면에 따라 다른 사실을 증언한다. 확인-또는-경보 원칙의 가장 큰 계통적 위반.
- **코드 증거**: batch.py:29-59 vs 126-141(본 세션 재확인: generate_batch 무게이트, generate_matrix만 원자 재검사+근거 주석), cli.py:341-349,352-360,371-408, run_state.py:282-297,327-365, run_view.py:447-459, core/job.py:36(MISSING_MARKER), data/nara.py:137-145(records()가 result() 미호출), cli.py:264-268(본 세션 재확인: records() 직호출), nara_state.py:238-244(fail-closed는 여기뿐),167-182, data/factory.py:74-84, data/pipeline.py:182-193, worker.py:26-39
- **병합 증상**:
  - 드리프트 게이트 3곳(cli.py:341 --profile시만 / run_state.py:282 클릭시 / batch.py:130 매트릭스만) 전부 '검증 시점' 게이트 — 단일 실행의 생성 경계(generate_batch)는 무검사. 미드배치 템플릿 교체 시 다른 문서종 2건이 '성공 3/3'으로 보고, CLI는 unmatched 무출력 완전 무음(failure FX1 실증, TOCTOU). 차단 문구 조립도 4곳(run_state/run_view/cli/batch)에 산개해 이미 문구가 갈라짐
  - ADR-E 빈값 게이트·MISSING_MARKER 주입이 GUI(run_view:447-459)에만 — CLI는 stderr 경고 1줄 후 exit 0, 산출 문서에 '{{담당자 전화번호}}' 누름틀 원문 잔존(S2/S6 실증). 동일 입력에서 두 표면의 법적 문서 내용이 다름
  - 원장 export 병렬 구현(cli._export_ledger vs RunViewModel.export_run_ledger) — job명/missing_marker/source 포인터 포맷/profiles 4축 실갈림. CLI 원장은 가장 위험한 미입력 필드의 문서 실상을 미증거(preview=''·injected=null인데 실문서엔 placeholder 잔존), 실패 처리도 GUI만 catch(FX6은 RC-16으로)
  - 나라 취득 검증 스택(resultCode fail-closed·기간 1개월 validate_range·오류 경계)이 링1 VM에만 — CLI --source nara가 인증 실패(resultCode=07)를 '0건 취득+exit 0' 조용한 성공으로 통과하고 --ledger는 그 실패를 정상 실행으로 문서화(failure:F4 C1), 오류 응답에 items가 실리면 오류 데이터로 문서 생성(C2). GUI도 파이프라인 내장 nara sub-ref는 게이트 우회(coupling:F4 A2). 기간 6개월도 무검증 통과. VM은 records()가 resultCode를 안 보기 때문에 _fetch_raw/_union_fields를 사본 재구현(드리프트 결합)
- **권고**: 검증·정책을 경계로 하강: (1) generate_batch에 매트릭스와 대칭인 template_path_drift 재검사(mapping 수용 시그니처), 문구는 TemplateStructureDrift.describe() 단일화 (2) MISSING_MARKER 주입·exit 정책을 RunRequest.mapped_records 공유로 CLI 이식(기본 차단, --ack-empty 옵트인) (3) 원장 문맥 빌더를 core/fill_ledger 곁 단일 함수로 (4) resultCode·기간 검증을 data/nara.py records() 내부로(≠00이면 NaraFetchError) — CLI·파이프라인·풀이 동시에 닫힘.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 3+1종 전건 성공 (스크립트·로그: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-03\repro_rc03.py, repro_output.log, repro_pipeline_bypass.py, repro_pipeline_bypass.log — 실 네트워크·실 ServiceKey 0회, urlopen monkeypatch + 가짜 키, HWPXFILLER_HOME 임시). ① C1: CLI --source nara 에 resultCode=07(인증 실패)+기간 6개월 주입 → exit 0, "[나라장터] 0건 취득", --ledger 는 source='nara:표준입찰공고 …' 정상 포인터·outputs=0 으로 실패 흔적 0인 원장 저장. 동일 바이트를 링1 NaraAcquireViewModel.acquire 에 주입하면 ok=False "API 오류 [07]…", validate_range(6개월)="조회 기간은 최대 1개월…" — CLI(cli.py:264-269)는 records() 직호출이라 두 검증 다 없음(data/nara.py:137-145 records() 는 result() 미호출, 호출처는 nara_state.py:232,261 뿐임을 grep 확증). ② C2: resultCode=07 응답에 items 1건 실림 → CLI "완료: 1/1 성공", exit 0, 오류 데이터로 문서 생성(output-{{ID}}.hwpx), unmatched 22필드는 stdout/stderr 어디에도 미출력(cli.py:361-364 는 실패만 출력). ③ S6: 첫 필드 빈값 CSV → CLI exit 0 + stderr 경고 1줄, 산출 문서 read_fields 되읽기='{{입찰공고번호}}' 누름틀 원문 잔존(템플릿 원문과 동일). GUI 경로(run_view.py:447-459 의 MISSING_MARKER 주입 재현)는 같은 필드='〘미입력·입찰공고번호〙' — 동일 입력에서 두 표면의 문서 내용 상이 확증. ④ FX1: generate_batch(batch.py:29-59, 드리프트 게이트 부재) 진행 콜백에서 레코드1 완료 직후 템플릿을 입찰공고서→구매요청서로 교체 → "성공 3/3", 산출물 doc.hwpx=입찰공고서 필드셋(22), doc_1/doc_2=구매요청서 필드셋(10) 혼재, 전건 ok=True. 매트릭스만 생성 경계 원자 재검사(batch.py:126-141 + 근거 주석). ⑤ 보조: GUI 파이프라인 풀 항목의 nara sub-ref — 동일 07 응답이 kind=nara 직접 항목에선 RuntimeError 차단(run_state.py:75-87), kind=pipeline 내장에선 예외 없이 오류 레코드 1건 통과(run_state.py:89-92→factory.py:74-90→pipeline.py:188). 인용 파일:라인 전건 직접 열어 대조 일치: batch.py:29-59/126-141, cli.py:264-269,338-350,352-360,361-364,371-408, run_state.py:282-297,309-311,327-365, run_view.py:447-461, core/job.py:36, data/nara.py:137-145,188-192, nara_state.py:167-182,194-210,238-244, data/factory.py:74-90, data/pipeline.py:182-193, worker.py:26-39.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 4갈래 전부 실패(=이슈 생존). (1) "resultCode 검증이 데이터층/다른 곳에 이미 있는가" — grep 전수: NaraStdDataSource.result() 호출처는 nara_state.py 2곳뿐. 오히려 tests/test_nara.py:155 가 records() 의 '07→조용한 빈 목록' 동작을 데이터층 계약으로 박제하고 있어(게이트를 VM 소유로 전제), 이슈가 말한 '검증이 경계가 아닌 호출자 소유' 구조를 테스트가 증언한다. (2) "generate_batch 호출자가 전부 사전 게이트하므로 생성 경계 게이트는 불요인가" — CLI 는 --profile 있을 때만 게이트(cli.py:338)이고, GUI validate_generate 도 클릭 시점 검사라 TOCTOU 열림 — FX1 런타임 재현으로 3/3 '성공' 혼종 산출 실증. batch.py:126-128 주석 자체가 "validate 이후 템플릿 교체/우회" 위협을 매트릭스에만 명시적으로 막았다고 자인. (3) "GUI 파이프라인 경로는 VM 게이트를 상속하는가" — 대조군(직접 nara=차단) vs 실험군(pipeline 내장 nara=통과) 런타임 실증으로 반증 실패. factory.py 주석의 '보안 불변식 공짜'는 키 주입만 해당, resultCode 게이트는 미상속. (4) "CLI 는 경고를 내므로 조용하지 않은가" — stderr 경고는 있으나 자동화 계약(exit code)은 0이고, C2 의 unmatched 22필드는 어떤 채널에도 미출력 — 파이프라인 관점에선 완전 무음. 이 저장소의 확인-또는-경보 원칙과 심각도 가중 규칙(§7)상 '법적 문서를 조용한 성공으로 통과'는 critical 유지 타당. 사소한 정정 1건: 원 이슈의 nara_state 인용 중 _fetch_raw 는 238-244가 아닌 194-210(fail-closed 판정은 238-244 맞음), run_view 빈값 게이트는 447-459 가 아니라 447-461 까지가 원장 문맥 포함 범위 — 논지에 영향 없음.

</details>

<details><summary>Verifier 비고</summary>

검증 완료 세부: (a) 원장 이중화 실갈림 실측 — CLI _export_ledger(cli.py:371-408)는 job_name 미전달(원장에 키 부재)·missing_marker 미전달(기본 "")·source 포맷 "nara:표준입찰공고 기간" vs GUI "nara:취득 스냅샷(키 미포함)"(run_state.py:314-325)·profiles 인자 구성 상이 — C1 원장 실물에서 job_name 키 부재 확인. (b) S6 원장 함의: CLI 는 marker="" 라 manifest 의 missing 행 preview 가 비어 verify_output(fill_ledger.py:253-273)이 판정을 건너뜀(injected=None) — 실문서엔 '{{입찰공고번호}}' 잔존인데 원장은 그 실상을 미증거, 이슈 주장 그대로. (c) 문구 산개: 드리프트 차단 문구가 run_state.py:284-297(4분기 상세)·cli.py:343-348(단문)·batch.py:134-139(단문)로 이미 갈라짐 확인. (d) C1 로그의 "ledger 오류 문자열 포함=True"는 generated_at 날짜 "-07-" 부분문자열 오탐 — repro_pipeline_bypass.log 에 정직 기재. 실질은 실패 흔적 0. (e) 권고 방향(경계 하강 4건)은 관찰과 정합 — 특히 (4) records() 내부 resultCode 검증은 CLI·파이프라인·풀·fields() 를 한 번에 닫음. 증거물: 스크래치패드 review-round1\verify\RC-03\ 아래 repro_rc03.py, repro_output.log, repro_pipeline_bypass.py, repro_pipeline_bypass.log, s6_empty.csv.

</details>

### RC-04 · [확정] 템플릿 관리 워크숍 GUI 완전 도달 불가 — hasattr 전방호환 배선이 홈에 없는 시그널을 기다리는 침묵 no-op, 테스트 우회·문서 오기로 3중 은폐

- **심각도/유형**: critical/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F7 · **유닛**: U2
- **근본 원인**: 병렬 유닛(C5↔홈) 이음매를 hasattr 침묵 가드로 흡수한 설계 — 홈 측 시그널 착지가 영영 안 됐는데 코드(조용한 no-op)·테스트(내부 메서드 직접 호출로 우회)·문서(착지 완료 오기)가 모두 실패를 가려 c1ee653 이후 지금까지 게이트를 통과. 같은 '조용한 실패 허용' 습관의 두 번째 사례가 같은 파일의 except Exception: return(_open_editor_from_base). §8-① 확정 발견.
- **사용자 영향**: 템플릿 위생 관리(컴파일 배지·fieldize·lint·드리프트·작업 시드) 전체를 GUI 사용자가 쓸 수 없고 존재도 알 수 없다. 라우팅 계층이 확인-또는-경보 원칙을 스스로 위반한 제도화된 패턴.
- **코드 증거**: gui/app.py:37-49(본 세션 재확인: 가드 4곳+전방호환 주석), gui/home.py(manage_templates_requested grep 0건 — 본 세션 재확인), gui/app.py:105-112,149-161,177-180, tests/test_gui_smoke.py:378-381, docs/UI_DESIGN_HANDOFF.md:24,33-35
- **병합 증상**:
  - app.py:39 hasattr=False(런타임 emit→AttributeError), 홈 시그널 9종·버튼 6종 전수에 템플릿 진입 부재 — 본 세션 grep 재확인 0건. TemplateManagerPanel+VM+테스트 완비된 C5 기능 전체가 GUI 사용자에게 존재하지 않음
  - hasattr 가드 4곳 전수 감사: 1곳 사망·3곳(pool/matrix/vocab)은 시그널이 정적으로 항상 존재해 가드로서 무의미한 채 우연 생존 — 홈 주석이 패턴을 양쪽에서 제도화
  - make_job_requested→_open_editor_from_template 라우트도 연쇄 사장(죽은 코드)
  - tests/test_gui_smoke.py:379가 ctrl._open_template_manager를 직접 호출 + library_dir 수동 주입 — 사용자 경로(시그널 emit)를 어떤 테스트도 검증 안 해 CI가 영구 사각
  - docs/UI_DESIGN_HANDOFF.md:24,33-35가 '착지 커밋 c1ee653' 완료 서술 — 해당 커밋은 home.py 무접촉(git 확인)
  - app.py:177-180 _open_editor_from_base가 베이스 로드 실패를 except Exception: return으로 삼킴 — 워크벤치 '편집' 클릭이 무반응 no-op(failure:F7 W7 실증)
- **권고**: home.py에 manage_templates_requested Signal+헤더 버튼 추가로 라우트 소생. 가드 4곳 전부 직결 connect로 교체(부재 시 기동 즉시 AttributeError). _open_editor_from_base는 QMessageBox.warning+refresh. 라우팅 스모크를 시그널 emit 기점으로 재작성 + 배선 완결성 전수 assert. 핸드오프 문서 동시 정정. RC-14(패널 자체 품질)와 한 패키지로 착지해야 소생 후 백지를 면함.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-04\repro_rc04.py (offscreen, QT_QPA_FONTDIR=C:\Windows\Fonts, 임시 HWPXFILLER_HOME/JobRegistry — 사용자 데이터 비접촉). 관찰 결과: [1] hasattr(home,'manage_templates_requested')=False → app.py:39 가드가 connect를 조용히 스킵. [2] emit 시도 → AttributeError: 'JobListHome' object has no attribute 'manage_templates_requested'. [3] 홈 시그널 인벤토리: 커스텀 시그널 9종(new/edit/run/delete_job, new/open_txt, manage_pool, matrix_run, manage_vocab) — 템플릿 없음. [4] 홈 버튼 전수 6종('데이터 풀 관리','어휘 워크벤치','여러 작업 일괄 실행','＋ 새 문서 작업','＋ 새 작업 만들기','＋ 새 기안') — 템플릿 진입 없음. 시각 증거: 같은 폴더 rc04_home_no_template_entry.png. [5] 가드 4곳 감사: templates=False(사망), pool/matrix/vocab=True(정적 상존 — 가드 무의미). [6] TemplateManagerPanel 직접 인스턴스화는 정상(기능 자체는 완비 — 도달만 불가). [8] _open_editor_from_base('존재하지-않는-베이스') → 창 미개방·경고 없음(침묵 no-op). git 증거: git show --stat c1ee653 = home.py 무접촉(5파일: app.py, template_manager.py, template_manager_state.py, test_gui_smoke.py, test_template_manager.py). code_evidence: src/hwpxfiller/gui/app.py:37-49(가드 4곳+전방호환 주석), app.py:105-112(_open_template_manager — 사장), app.py:149-161(_open_editor_from_template — 연쇄 사장), app.py:177-180(except Exception: return), src/hwpxfiller/gui/home.py:127-139(시그널 9종)·173·175·198(버튼 connect 3곳), tests/test_gui_smoke.py:378-386(내부 메서드 직접 호출 우회), docs/UI_DESIGN_HANDOFF.md:24,33-35(착지 완료 오기).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

4개 축으로 반증을 시도했고 전부 실패했다. (1) 시그널이 다른 곳에 정의됐을 가능성: 저장소 전체 grep — manage_templates_requested 정의는 0건, app.py:39-40 가드와 docs 2곳 언급뿐. 런타임 시그널 인벤토리 전수(JobListHome의 SignalInstance 18개)에도 부재. (2) 다른 GUI 진입 경로(컨텍스트 메뉴·단축키·자체 main) 존재 가능성: TemplateManagerPanel import는 app.py의 사장 라우트뿐이고 template_manager.py에 __main__/main 없음, 홈 버튼 6종 전수(캡처)에 템플릿 진입 없음. (3) 문서 주장('착지 커밋 c1ee653')이 맞을 가능성: git show --stat c1ee653 — app.py/template_manager*/tests만 접촉, home.py 무접촉 확정. 커밋 메시지 자체가 'app.py 는 additive 라우팅만(hasattr 가드 진입 시그널)'이라 홈 측 미착지를 자인. 이후 J1(89e9cd7)·J2(7bbffd1)·J3(cac94c7) 커밋이 pool/matrix/vocab 시그널만 추가해 나머지 가드 3곳은 정적으로 항상 True(가드 무의미) — 이슈의 '우연 생존' 주장도 확인. (4) 테스트가 사용자 경로를 검증할 가능성: tests/test_gui_smoke.py:378-379는 ctrl._open_template_manager(str(tmp_path)) 직접 호출 + library_dir 수동 주입 — 시그널 emit 기점 테스트는 어디에도 없음. 부수 증상 _open_editor_from_base(app.py:177-180 except Exception: return)도 런타임 실증: 부재 베이스명으로 호출 시 children 0→0, 경고 없음.

</details>

<details><summary>Verifier 비고</summary>

이슈 서술 전 항목이 정적+런타임+git 3중으로 확인됨. 심각도 critical 유지 근거: (a) TemplateManagerPanel+VM+테스트 완비된 F7 전 기능이 GUI에서 도달 불가(사용자는 존재조차 모름 — CLI lint/drift만 부분 대체), (b) 코드(침묵 no-op)·테스트(내부 메서드 우회)·문서(착지 완료 오기)의 3중 은폐로 게이트가 영구 통과, (c) 저장소 자체 원칙(확인-또는-경보) 위반 시 심각도 1단계 상향 규칙(REVIEW_ORCHESTRATOR.md §7). 미세 정정 1건: 이슈의 '런타임 emit→AttributeError'는 시그널 자체가 부재하므로 사용자가 emit할 표면조차 없다는 의미 — 실제 사용자 증상은 예외가 아니라 '기능의 완전한 비가시'(가드가 크래시마저 삼켜 어떤 경보도 없음). 권고안(home.py 시그널+버튼 추가, 가드 4곳 직결 connect 교체, _open_editor_from_base 경보화, 시그널 emit 기점 라우팅 스모크, 문서 정정)은 관찰 영향에 비례하며 타당. 증거물: scratchpad\review-round1\verify\RC-04\{repro_rc04.py, rc04_home_no_template_entry.png}.

</details>

### RC-05 · 손상 .job.json 1개가 홈·앱 시작을 통째로 벽돌화 — list_jobs에 파일 단위 격리 없음

- **심각도/유형**: critical/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F1, F2 · **유닛**: U2
- **근본 원인**: core/job.py list_jobs가 Job.load를 파일별 예외 처리 없이 순회하고, home_state(생성자 refresh)→home→app 시작 경로가 전부 무보호 — '예외 전파는 호출측이 표면화'라는 계약을 어느 호출측도 이행하지 않음. RC-01(Job.save 비원자 절단)과 연쇄 시 저장 실패 1회가 앱 재기동 불가로 증폭.
- **사용자 영향**: durable 자산 폴더의 파일 1개 손상으로 제품 전체 사용 불가 — 저장 실패(RC-01)의 2차 피해가 가장 파국적 형태로 발현.
- **코드 증거**: core/job.py:168-170(무보호 Job.load 제너레이터),111-120(dict 전제), gui/home_state.py:137,151, gui/home.py:155, gui/app.py:208
- **병합 증상**:
  - 절단 JSON 1개 추가 → list_jobs·HomeViewModel·JobListHome 연쇄 JSONDecodeError, 앱 시작 불가 상당(failure:F1 P3 실증)
  - 유효 JSON이지만 dict 아닌 파일([1,2,3])도 from_dict AttributeError로 동일 전멸
  - 어느 파일이 문제인지·복구 방법 안내 전무 — 사용자는 ~/.hwpxfiller/jobs를 직접 뒤져야 하는데 그 사실을 알 방법이 없음
- **권고**: list_jobs에서 파일별 try/except로 손상 항목을 (경로, 오류)로 수집, 홈에 '손상됨' 배지 행으로 시끄럽게 표면화하고 나머지 작업은 정상 표시.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-05\repro_rc05.py (전체 로그: 동일 폴더 repro_output.log). 임시 HWPXFILLER_HOME + offscreen. 임시 registry에 정상 Job 1개 + 절단 JSON('{"name": "절단", "template_pa') 1개 조성 후 6개 시나리오 실행 — 실측 결과: P1 JobRegistry.list_jobs() → JSONDecodeError(src/hwpxfiller/core/job.py:170 제너레이터 → :129 json.loads). P2 HomeViewModel 생성 → 동일 예외(gui/home_state.py:137 생성자 refresh → :151 list_jobs). P3 JobListHome 생성 → 동일 예외(gui/home.py:155). P4 _AppController(JobRegistry(default_jobs_dir())) — gui/app.py:208 main() 시작 경로 등가 → 동일 예외로 컨트롤러 생성 자체 실패 = 앱 시작 불가 실증. P5 유효 JSON이지만 dict 아닌 파일([1,2,3]) → AttributeError: 'list' object has no attribute 'get'(job.py:113 from_dict) — 두 번째 증상도 실증. P6 대조군: 손상 파일 제거 후 list_jobs 정상(정상작업 1건) — 손상 파일 1개가 유일 원인임을 귀속 확인. 예외 문구 어디에도 어느 파일이 문제인지·복구 방법 안내 없음(traceback에 손상 파일 경로 자체가 안 나옴 — Path(path).read_text는 성공하고 json.loads에서 터지므로 사용자는 jobs 폴더 존재조차 알 수 없음).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 시도 3방향 모두 실패(이슈가 옳음을 강화). (1) 인용 파일:라인 전수 대조 — 이슈의 core/job.py는 실경로 src/hwpxfiller/core/job.py이나 라인은 전부 일치: :168-170 list_jobs가 무보호 제너레이터로 Job.load 순회, :111-120 from_dict가 d.get으로 dict 전제, :122-124 Job.save는 write_text 직접 기록(비원자 — RC-01 연쇄 전제도 성립), gui/home_state.py:137(생성자 refresh)·:151(list_jobs 호출), gui/home.py:155(HomeViewModel 생성), gui/app.py:208(main→_AppController) 모두 실코드와 일치, 어느 계층에도 try/except 없음. (2) 다른 곳의 가드·의도 탐색 — home_state.py:45-48 _derive_compile은 손상 '템플릿'을 try/except로 잡아 BADGE_ERROR('손상 템플릿이 홈 목록을 죽이지 않도록' 주석 명시)로 시끄럽게 강등하는 정확히 같은 패턴을 이미 구현했으나 손상 '.job.json'에는 미적용 — 저장소가 이 실패 모드를 인지하고도 job 파일에만 빠뜨린 비대칭이라 '의도된 전파' 반증 불성립. list_jobs docstring도 빈 디렉터리만 언급, 호출측 표면화 계약 문서 부재. (3) 테스트 커버리지 탐색 — tests/test_job.py의 list_jobs 테스트는 빈/정렬만 다루고 손상 JSON 케이스 전무(grep JSONDecodeError/corrupt: tests에서 corrupt는 템플릿용 test_home_state.py:231뿐). 추가로 이슈가 언급 안 한 동일 원인 표면 2곳 발견: gui/vocab_workbench_state.py:57,102와 gui/wizard.py:642도 무보호 list_jobs 호출 — 이슈보다 영향 범위가 오히려 넓음. 심각도 critical 유지 타당: durable 폴더 파일 1개 손상 → 제품 전체 재기동 불가 + 원인 파일·복구 경로 무안내(확인-또는-경보 원칙 위반으로 상향 요건도 충족).

</details>

<details><summary>Verifier 비고</summary>

code_evidence(전부 직접 확인): src/hwpxfiller/core/job.py:168-170(무보호 제너레이터 list_jobs), :127-129(Job.load 무보호 json.loads), :111-120(from_dict dict 전제 → 비-dict JSON에 AttributeError), :122-124(Job.save 비원자 write_text — RC-01 연쇄 성립); src/hwpxfiller/gui/home_state.py:137(생성자 refresh), :151(무보호 list_jobs); src/hwpxfiller/gui/home.py:155(HomeViewModel 생성); src/hwpxfiller/gui/app.py:25(JobListHome 생성), :208(main 진입). 대비 패턴: home_state.py:45-48(손상 템플릿은 BADGE_ERROR로 loud 강등 — 권고안의 사내 선례). 이슈 미언급 추가 표면: gui/vocab_workbench_state.py:57,102, gui/wizard.py:642(동일 무보호 list_jobs — 수정 시 list_jobs 계층에서 파일별 격리하면 일괄 해소). 이슈의 verification_hint(P3 JobListHome 예외 전파)와 merged_symptoms 3건 전부 실측 일치. 권고(파일별 try/except + 손상 배지 행) 타당 — 기존 BADGE_ERROR 관례와 정합. 증거물: repro_rc05.py, repro_output.log(스크래치패드 review-round1/verify/RC-05/). 사용자 ~/.hwpxfiller 비접촉·임시 HWPXFILLER_HOME 사용.

</details>

## 높음 (high) — 9건

### RC-06 · 배치 실행 중 취소 수단 전무 — generate_batch 완주형 루프·워커 무중단·GUI 취소 UI 부재

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F2, F10, F3 · **유닛**: U6
- **근본 원인**: VBA 포트 시절 배치 프리미티브에 협조적 취소 개념이 애초 없고(§8-3), GenerateWorker·RunView는 그 위 얇은 중계라 중단 지점을 만들 곳이 없음. 저장소 전체 grep에서 cancel/중단/취소 히트는 무관한 다이얼로그 버튼뿐.
- **사용자 영향**: 수백 건 배치(나라장터 취득 100건+)를 잘못 시작하면 완주를 지켜봐야 하며 그 사이 기존 산출물이 무경고로 덮여 나간다 — 최고 위험 쓰기 경로에서 개입 수단 부재.
- **코드 증거**: batch.py:51-58(본 세션 재확인: for 루프에 중단 지점 없음), worker.py:26-39, run_view.py:179-186,402-404,464-481
- **병합 증상**:
  - batch.py 레코드 루프에 progress 콜백만, cancel 토큰 없음; worker.run 완주만; 실행 중 UI 반응은 btn_generate 비활성이 유일(07_running_no_cancel.png)
  - RC-02와 결합: 잘못 겨눈 배치가 기존 파일들을 덮어쓰는 것을 지켜볼 수밖에 없고, 유일한 개입(프로세스 강제종료)은 RC-01(비원자 저장)과 결합해 파일 파괴
  - CLI도 Ctrl+C 시 부분 결과 요약 부재(관례상 수용 범위이나 승격 여지)
- **권고**: generate_batch 시그니처에 cancelled: Callable[[],bool] 추가(레코드 경계 체크), worker 스레드-세이프 플래그, RunView/MatrixView 취소 버튼 + 부분 결과 요약, BatchResult에 cancelled 상태.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-06\repro_rc06.py (.venv python, offscreen+FONTDIR+임시 HWPXFILLER_HOME, 사용자 홈 비접촉, 합성 템플릿 사용). 관찰 결과 — Part A: 50레코드 배치에서 레코드 1 완료 직후 progress 콜백으로 취소 요청을 흉내냈으나 전달 채널 자체가 없어 배치 완주: total=50 succeeded=50, progress 50회 호출, 디스크에 50파일 전부 기록(취소가 동작했다면 1). Part B: progress에서 예외를 던지는 유일한 탈출구는 BatchResult를 유실시킴 — 부분 파일 3건은 디스크에 잔존하나 호출자에게 부분 요약 불가. Part C(GUI offscreen): RunView 버튼 전수 11개·MatrixRunView 9개 열거, 취소/중단/정지류 0개; _running=True + _sync_generate_enabled() 상태에서 유일한 변화는 btn_generate 비활성(다른 버튼 '데이터 풀에서…' 등은 실행 중에도 활성으로 남는 부수 관찰도 있음). 증거: 같은 폴더의 rc06_repro_log.txt, rc06_runview_running_no_cancel.png, rc06_matrixview_no_cancel.png. code_evidence(직접 열어 확인): src/hwpxfiller/batch.py:29-59(generate_batch 시그니처·루프), batch.py:143-163(generate_matrix도 동일하게 무중단), src/hwpxfiller/gui/worker.py:26-39,61-74, src/hwpxfiller/gui/run_view.py:179-186(액션 영역에 '문서 생성' 단일 버튼),402-404,464-481,518-528, src/hwpxfiller/gui/matrix_view.py:133-136,257-258,299-303, src/hwpxfiller/cli.py:360-368(KeyboardInterrupt 무처리).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

이슈가 틀렸을 가능성을 3방향으로 공격했으나 전부 실패(=이슈 확증). (1) 인용 파일:라인 대조 — src/hwpxfiller/batch.py:51-58 for 루프에 중단 지점 없음(progress·now만 키워드 인자, 시그니처를 inspect로 런타임 확인: cancel 파라미터 0개), src/hwpxfiller/gui/worker.py:26-39 GenerateWorker.run은 generate_batch 완주 후 finished만 emit(MatrixGenerateWorker:61-74 동일), run_view.py:402-404 실행 중 btn_generate 비활성이 유일한 상태 변화, 464-481 스레드 기동부에 취소 배선 없음 — 전부 인용과 일치. (2) 다른 곳의 처리 탐색 — src 전체 grep(cancel|abort|interrupt|중단|취소|멈추, case-insensitive): 히트는 mapping_table/nara_view/pipeline_builder/wizard의 다이얼로그 Cancel 버튼뿐(전부 실행-전 다이얼로그, 배치 실행과 무관). requestInterruption/terminate 0건, thread.quit()은 완료 후 teardown(run_view.py:524, matrix_view.py:299)에서만 호출. closeEvent 핸들러 0건 — 창을 닫아도 워커는 계속 돈다. CLI(cli.py:360-368)는 KeyboardInterrupt/SIGINT 처리 0건 — Ctrl+C 시 부분 요약 없이 트레이스백. (3) 런타임 반증 — 취소를 흉내낼 유일 채널인 progress 콜백으로 시도: 반환값 무시 확인, 예외를 던지면 루프는 멈추나 BatchResult 자체가 유실되고(부분 요약 불가) worker의 except가 문자열만 emit(worker.py:38-39)해 run_view._on_failed(:518-520)가 일반 오류 모달만 띄움 — 우아한 취소 경로가 아니라 파괴적 탈출뿐. GUI 위젯 트리 전수 열거(RunView 버튼 11개, MatrixRunView 9개)에서 취소류 버튼 0개를 런타임으로 확인.

</details>

<details><summary>Verifier 비고</summary>

이슈 원문 인용 전부 실코드와 일치, 과장 없음. 심각도 high 유지 타당: 취소 부재 단독으로는 기능 결핍이지만, 이 저장소의 최고 위험 쓰기 경로(F2/F10, 법적 효력 문서 생성)에서 RC-02(덮어쓰기 무가드)와 결합 시 잘못 겨눈 배치의 파괴를 지켜볼 수밖에 없고 유일한 개입(프로세스 강제종료)은 RC-01(비원자 저장 package.py:70)과 결합해 파일 파괴 위험 — 오케스트레이터 §3도 F2 위험도를 '최고'로 명시. 추가 부수 관찰(별도 이슈 후보): 실행 중 btn_generate 외 버튼들(데이터 풀/파일 선택/나라장터/찾아보기)이 활성 상태로 남아 실행 중 데이터소스·출력폴더 변경이 가능 — 원장 export가 실행 후 ed_out.text()를 다시 읽으므로(run_view.py:500) 경합 여지. 권고안(cancelled Callable 토큰 + 레코드 경계 체크 + BatchResult.cancelled + 부분 요약)은 관찰 영향에 비례하며 타당. CLI Ctrl+C 부분 요약 부재는 관례상 수용 범위라는 원문 평가에 동의(승격은 선택).

</details>

### RC-07 · 생성 요청이 불변 계획(GenerationPlan)으로 캡슐화되지 않음 — 완료 핸들러가 라이브 위젯/VM 상태를 재읽어 원장이 생성물과 다른 데이터·폴더를 '증거'로 기록, 완료 시 UI 프리즈·실패 경로 상태 미정리 동반

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F2 · **유닛**: U6
- **근본 원인**: _on_generate fat handler(§8-8)가 게이트 재확인→표식 결정→스레드 배선까지 한 몸이면서 문맥 일부(_ledger_ctx=indices/marker)만 인스턴스 속성으로 넘기고 out_dir·mapped·template은 완료 시점에 라이브 재파생 — 생성 요청이 값 객체로 모델링되지 않았다. 같은 설계가 원장 export를 완료 시점 위젯 상태 의존으로 만들어 워커로 옮길 수 없는 형태로 고착.
- **사용자 영향**: opt-in 원장을 켠 고위험 사용자일수록 피해가 큼 — 배치 중의 자연스러운 UI 조작만으로 증거 파일이 유실되거나 실제 생성물과 모순되는 거짓 증거가 남는다(법적 문서 증거 사이드카의 침묵 오기록).
- **코드 증거**: run_view.py:431-481,461(문맥 부분 캡처),500-511(본 세션 재확인: ed_out 재읽기·getattr _ledger_ctx·UI 스레드 export),513-520(본 세션 재확인: _on_failed 모달 단발), run_state.py:298-299,344-364(mapped_records 완료 시점 재파생·effective_template 재평가), fill_ledger.py:296-321, batch.py:121-122
- **병합 증상**:
  - 프로브1: 생성 중 사용자가 ed_out 편집 → 문서는 outA에, _on_finished는 ed_out 재읽기로 원장을 outB에 기록 시도(오배치/실패), '폴더 열기'도 outB(coupling 실증)
  - 프로브2: 생성 중 데이터 재로드(데이터 버튼들 실행 중 활성) → 원장이 새 데이터로 행 재구성해 preview='바뀐공고'/injected=False/오소스를 기록 — 생성물과 모순되는 거짓 증거(coupling 실증)
  - 원장 되읽기 검증(전 산출물 zip 재파싱)이 _on_finished UI 스레드에서 동기 수행 — 40건 0.58s 실측, 생성 시간과 같은 자릿수 스케일이라 대배치 완료 순간 무응답(failure FX4)
  - _on_failed는 teardown+모달뿐 — lbl_result 빈 채 progress 잔존·로그 무기록·run_finished 미방출, 모달 닫으면 실패 증거 증발(failure FX3, '경보 휘발')
  - 표식 정책·mapped 구성(문서 내용 결정 도메인 정책)이 위젯에 상주 — 매트릭스는 같은 정책이 batch 안이라 정책 위치도 화면마다 상이, 헤드리스 테스트 seam 부재
  - validate_generate가 out_dir 빈 문자열만 검사 — 경로가 파일인 경우 등 미검증(FX3 원인)
- **권고**: _on_generate에서 (template, mapped, out_dir, marker, indices, source_pointer)를 불변 GenerationPlan으로 캡처해 워커·_on_finished가 그것만 소비. 원장 검증·export는 워커 run() 꼬리로 이동(진행 시그널에 '검증 중' 단계). _on_failed는 _say+lbl_result(danger)+progress 리셋으로 성공 경로와 대칭. 실행 중 입력 컨트롤 비활성(또는 RC-06 취소 제공).

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 rc07_probe.py(증거 폴더 review-round1\verify\RC-07\, 출력 rc07_probe_output.txt, 원장 p2_fill-ledger.json) — offscreen + 임시 HWPXFILLER_HOME + 실제 GenerateWorker/QThread 사용, 4건 전부 재현. 프로브1: outA로 생성 시작 후 실행 중 ed_out을 outB로 편집 → 문서 5건은 outA, fill-ledger.json은 outB에 기록, '폴더 열기'도 outB를 엶(로그: "[원장] ...outB\fill-ledger.json 저장" — 무경보). 프로브2: '원본공고'로 생성 중 datasource 교체('바뀐공고') → 생성물 되읽기는 공고명='원본공고'로 정상인데 원장은 preview_text='바뀐공고'/injected=False/read_back='원본공고'로 '주입 실패' 거짓 증거를 기록. 프로브3: 40건 배치 — 생성(워커) 0.03s vs 원장 export+전 산출물 zip 되읽기(UI 스레드 동기, run_view.py:505) 0.17s(508%). 프로브4: out_dir=기존 파일 경로 → validate_generate 빈 목록(통과) → 워커 기동 후 WinError 183으로 _on_failed → critical 모달 1회뿐, lbl_result=''·progress 잔존(value=0/max=1)·log 실패 기록 0건·run_finished 미방출 — 모달 닫으면 실패 증거 증발.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

공격 4방향 모두 실패(이슈 생존). (1) "실행 중 UI 조작이 실제로 불가능할 것" — run_view.py를 전수 확인: _on_generate는 btn_generate만 비활성(run_view.py:465, _sync_generate_enabled 402-404). ed_out(QLineEdit, 162행)·btn_pool/btn_data/btn_nara(119-124행)·chk_ledger는 실행 중 전부 활성 — 프로브의 조작은 실사용자 동작과 동일 표면. (2) "워커 스냅샷이 이미 보호할 것" — 부분 반증 성립: GenerateWorker(worker.py:19-24)가 template/mapped/out_dir를 생성자에서 캡처하므로 생성물 자체는 안전. 그러나 이슈가 주장하는 지점(완료 핸들러)은 그대로 취약: _on_finished가 ed_out 재읽기(run_view.py:500), _ledger_ctx는 (indices, marker)만(461행), export_run_ledger는 mapped_records·effective_template·source_pointer를 완료 시점 라이브 VM에서 재파생(run_state.py:344,358-359) — 이슈 서술과 정확히 일치. (3) "다른 가드·테스트가 처리할 것" — validate_generate는 out_dir 빈 문자열만 검사(run_state.py:298-299, 프로브4에서 기존 '파일' 경로가 빈 목록으로 통과 실증), 실행 중 컨트롤 잠금·계획 스냅샷·관련 회귀 테스트 부재. (4) "원장 오기록이 시끄러울 것" — 프로브1·2 모두 예외 없이 '[원장] ... 저장' 성공 로그를 남김 — 조용한 오기록이며 확인-또는-경보 원칙 위반으로 심각도 상향 근거 유효. FX4 수치만 이슈 주장(0.58s)과 다르게 0.17s로 실측됐으나 생성(0.03s)의 5배로 '같은 자릿수 이상' 주장은 오히려 강화됨.

</details>

<details><summary>Verifier 비고</summary>

code_evidence(전건 직접 확인): src/hwpxfiller/gui/run_view.py:431-481(_on_generate fat handler; 461 _ledger_ctx=(indices,marker)만 캡처; 465 btn_generate만 비활성), 500-511(_on_finished가 ed_out 재읽기+UI 스레드 export), 513-516(폴더 열기도 재읽은 out_dir), 518-520(_on_failed=teardown+모달 단발); src/hwpxfiller/gui/run_state.py:298-299(validate_generate 빈 문자열만), 344·358-359(export가 mapped_records/effective_template/source_pointer 라이브 재파생); src/hwpxfiller/core/fill_ledger.py:296-321(ledger_outputs 되읽기 검증 — strict zip이라 실행 중 행수 변경 시 export 자체가 예외), 253-273(verify_output); src/hwpxfiller/gui/worker.py:19-24(생성 인자는 스냅샷 — 결합은 완료 핸들러에 국한); src/hwpxfiller/batch.py:47·121-141. 정정 1건: FX4 실측은 40건 0.17s(이슈 주장 0.58s보다 작음)이나 생성 시간의 5배로 스케일 주장은 유지 — 단독으로는 medium감이지만 병합 이슈의 핵심(원장 거짓 증거·오배치는 조용한 오기록, 프로브1·2 실증)이 high를 지탱. 생성물(.hwpx) 자체는 워커 스냅샷 덕에 항상 정확하므로 critical은 아님(원장은 opt-in). 권고안(GenerationPlan 값 객체 캡처)은 관찰과 정합 — 워커가 이미 스냅샷 패턴을 쓰고 있어 확장이 자연스러움.

</details>

### RC-08 · '전부 비움' 저장 가드가 술어 오류로 dead code — 아무 값도 채우지 않는 작업이 무경고 저장(3자 독립 런타임 실증)

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.98 · **기능**: F1 · **유닛**: U3
- **근본 원인**: to_profile이 blank 선언도 mappings에 영속화하도록 바뀐 뒤(L1 명시적 공란 영속화) job_editor.py:89의 'not profile.mappings' 술어가 미갱신 — is_complete 통과 시 mappings는 항상 비지 않아 분기 도달 불가. 도메인 판단('채울 값이 있는가')을 링2가 링0의 올바른 질의(template_fields, blank 제외) 대신 자료구조 내부 표현으로 재구현한 결과. 가드가 존재하되 침묵 무력(조용한 no-op — 원칙상 상향).
- **사용자 영향**: 실행해도 어떤 누름틀에도 값을 주입하지 않는 무의미 작업이 정상처럼 저장된다 — 명시성 게이트의 최종 방어선 무음, 가드 문구가 코드에 있어 개발자도 보호를 오신.
- **코드 증거**: gui/job_editor.py:88-94(본 세션 재확인: if not profile.mappings), gui/mapping_state.py:217-225(blank 포함 방출), core/mapping.py:115-122(template_fields — blank 제외)
- **병합 증상**:
  - 전 행 비움-확정 → 경고 0건, transforms=['blank','blank'] 작업 저장·목록화(ui S3+/coupling §A/failure P7 3중 실증)
  - 런타임 증명: 전부-비움 시 profile.mappings 길이=행수>0, profile.template_fields()=[] — 올바른 술어가 이미 존재
- **권고**: job_editor.py:89를 'if not profile.template_fields():'로 교체(1줄, 경고 문안 그대로 유효화). 근본적으로는 판단을 링1(MappingModel.emits_any_value())로 하강 + 헤드리스 회귀 테스트.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-08\repro_rc08.py (로그 repro_output.log). offscreen+임시 HWPXFILLER_HOME+임시 JobRegistry, QMessageBox 4종 monkeypatch 계측. 시나리오: 소스·상수 없는 행 2개 confirm_all → is_complete=True → JobEditorWizard.accept(). 관찰: len(profile.mappings)=2, transforms=['blank','blank'], profile.template_fields()=[], 현행 술어 `not profile.mappings`=False(가드 불발), QMessageBox 호출 0건, job_saved 방출, '전부비움작업.job.json' 레지스트리에 저장됨(되읽기: transforms=['blank','blank'], template_fields()=[]). 동일 런에서 권고 술어 `not profile.template_fields()`=True 확인 — 1줄 교체로 기존 경고 문안이 그대로 유효화됨을 검증.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

4갈래로 공격, 전부 실패: (1) 인용 파일:라인 대조 — src/hwpxfiller/gui/job_editor.py:81+89, mapping_state.py:199-201/217-225, core/mapping.py:115-122 전부 이슈 서술과 일치; is_complete 통과 시 to_profile은 확정 전 행을 방출(blank 포함)하므로 mappings는 항상 비지 않아 89행 분기 도달 불가가 정적으로 성립. (2) 다른 곳의 가드 탐색 — wizard.py:605/686의 동일 술어는 확정 0행 케이스만 커버(전부-비움 확정도 무경고 통과, 같은 잠복 결함); 실행 시점 게이트(run_state.py:282-297 드리프트, :264-269 unmet_blanks)는 cover_fields=매핑∪blank 비교라 전부-blank 작업이 템플릿과 정확히 일치해 무저지 통과, blank는 미입력 ack 게이트에서도 제외 — 런타임 완화 부재. (3) 테스트/문서화된 의도 탐색 — 경고 문안 '채울 값이 없습니다'는 소스 1곳뿐, 테스트 0건; 오히려 mapping_state.py:43-44 docstring이 'to_profile 제외'라는 구버전 동작을 아직 서술(가드가 원래 유효했다는 방증). (4) git 고고학 — 가드는 e4154a7(트랙 C)에서 작성, to_profile의 blank 영속화는 이후 2188d4d(L1)에서 도입 → 이슈의 root_cause(L1 변경 후 술어 미갱신) 그대로 확인. 반증 전부 실패, 재현 성공.

</details>

<details><summary>Verifier 비고</summary>

경로 정정: code_evidence의 실제 경로는 src/hwpxfiller/gui/job_editor.py(이슈 표기는 gui/ 상대) — 라인 번호는 일치(89행 술어, 88-94 가드 블록). 심각도 high 유지 근거: 명시성 게이트 최종 방어선의 조용한 무력(확인-또는-경보 원칙상 상향 대상) + 실행 시 어떤 게이트도 재차단하지 않아 무의미 작업이 끝까지 정상 흐름. 부수 발견 2건(편집자 참고): ① mapping_state.py:43-44 RowState docstring이 'to_profile 제외'라는 L1 이전 동작을 서술(stale) ② wizard.py:605(_save_profile)/686(_save_base)의 동일 술어도 전부-비움 확정 프로파일/공유 베이스를 무경고 저장 — 권고 수정 시 함께 template_fields() 기준으로 정리 검토. 권고안(job_editor.py:89 → if not profile.template_fields():) 유효성은 런타임에서 반례 없이 확인됨.

</details>

### RC-09 · 위저드 세션 상태의 이중 사본 + 내용 불감 캐시 키 — 같은 파일 재선택·소스 토글 후 매핑 스텝이 화면 요약과 모순되는 옛 데이터로 조용히 구동

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F1 · **유닛**: U3
- **근본 원인**: EditorSession(링1) 연기로 동일 상태의 사본이 위저드 속성↔MappingModel 내부↔뷰 위젯 3곳에 존재하고, MappingPage 캐시 키가 (template_path, data_path) 경로쌍뿐이라 내용 변경·소스 무효화를 감지하지 못함 — 뷰만 갱신하거나 세션만 갱신하는 핸들러들이 조용한 발산을 만든다.
- **사용자 영향**: 명시성 게이트의 심장부인 매핑 저작이 화면상 로드 성공 요약과 모순되는 옛 어휘로 진행 — 사용자는 원인 불명의 '없는 컬럼' 목록과 씨름하고, 지운 데이터가 계속 구동된다. 조용한 스테일이라 원칙상 상향.
- **코드 증거**: wizard.py:472-486(캐시 키),403-406,321-329(_on_source_toggle 뷰만),411-415(isComplete 상시 True),115-165(:132 조기 setText,:133-140 RAW 분기), mapping_state.py:85-87(source_fields 2번째 사본)
- **병합 증상**:
  - 같은 경로의 수정된 파일 재선택: wiz.source_fields는 신규 3컬럼으로 갱신·2단계 요약도 '컬럼 3개 로드' 표시하는데 model.source_fields는 1차분 잔존 — 신규 컬럼 매핑 불가, 삭제 컬럼 계속 제안(coupling §B 실증)
  - 소스 라디오 토글: 뷰(ed_path·요약)만 비우고 세션 data_path/datasource/records/source_fields 잔존 — isComplete 상시 True로 Next 통과, 3단계가 '지웠다고 믿는' 옛 엑셀 데이터로 미리보기 구동(coupling §C 실증) — 핸들러 주석이 막겠다던 바로 그 '소스 혼선'
  - TemplatePage 실패 경로 표시↔세션 발산: RAW 재선택 시 경로칸=새 파일·세션=옛 템플릿(조기 setText), fail-closed라 실피해는 없는 잠복 + RAW 차단 문구만 무스타일 lbl_summary(차단 3종 중 유일하게 warn 위계 없음)
- **권고**: 캐시 키에 소스 필드 집합 포함(또는 model.source_fields 동기화+소실 소스 행만 미확정 강등), _on_source_toggle에서 세션 속성도 원자 초기화(reset_data_session 메서드로 집약), 장기적으로 EditorSession(링1)으로 상태 단일화.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-09\rc09_repro.py (offscreen, 임시 HWPXFILLER_HOME, 실 JobEditorWizard + 실 핸들러 경유 — QFileDialog만 패치). 로그 rc09_run.log, 캡처 4장 동봉. 관찰 결과: [§B] colA,colB CSV 로드→매핑 스텝 진입 후, 같은 경로를 colA,colC,colD로 수정·재선택(_pick 재실행). wiz.source_fields=['colA','colC','colD'], DataPage 요약="컬럼 3개, 레코드 1건 로드"로 갱신됐으나 매핑 스텝 재진입 시 model is 동일 객체=True, model.source_fields=['colA','colB'] 잔존, 행0 콤보 후보=['(비움)','colA','colB','여러 데이터 항목 선택…'] — 신규 colC/colD 매핑 불가, 삭제된 colB 계속 제안 (캡처 B_mapping_stale_combo.png). 원인은 wizard.py:473-474 캐시 키 (template_path,data_path)가 경로쌍만 비교 — 내용 불감. 미리보기 레코드만 wiz.records로 갱신돼(wizard.py:508-509) 어휘는 옛것·데이터는 새것인 혼종 상태까지 확인. [§C] rb_nara.setChecked(True)로 _on_source_toggle 발화 → 뷰만 초기화(ed_path='', summary='')되고 세션은 잔존: wiz.data_path=CSV 경로, datasource is None=False, records 1건, source_fields 3개. DataPage.isComplete()=True로 Next 통과, 3단계가 "레코드 1/1" + 첫 미리보기 레코드={'colA':'n1a','colC':'n1c','colD':'n1d'} — 사용자가 지웠다고 믿는 엑셀 데이터로 미리보기 구동 (캡처 C_datapage_after_toggle.png, C_mapping_runs_on_stale_records.png). 핸들러 주석 "이전 선택을 무효화(소스 혼선 방지)"(wizard.py:322)와 실동작 모순. [§T] 유효 템플릿 로드 후 RAW 파일 재선택: ed_path=raw.hwpx(새 파일) vs wiz.template_path=tpl.hwpx(옛것) 발산 — wizard.py:132 조기 setText가 :133-140 RAW 분기보다 앞. isComplete=False(fail-closed, 실피해 없는 잠복) 확인. RAW 차단 문구는 lbl_summary에만 표시되고 lbl_summary.property('level')=None(무스타일), lbl_warn은 level='warn' 위계 보유 — 차단 3종 중 유일하게 warn 위계 없음 (캡처 T_raw_reselect_divergence.png). code_evidence 전 항목 실측 일치: wizard.py:473-474(캐시 키), :403-406(_pick 세션 기록), :321-329(_on_source_toggle 뷰만), :411-415(isComplete 상시 True), :132·:133-140(조기 setText·RAW 분기), mapping_state.py:86(source_fields 2번째 사본), mapping_table.py:282·379-389(콤보 후보가 model.source_fields에서만 유래).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 3방향 모두 실패(이슈 존속). (1) 다른 곳의 가드 탐색: wizard.py 전수에서 세션 data_path/datasource/records/source_fields를 쓰는 곳은 _pick(:403-406)과 _apply_nara_result(:356-359)뿐 — 토글·재선택 시 세션을 지우는 코드는 어디에도 없음. MappingPage.initializePage의 재초안 조건도 (경로쌍 불일치 or model None)뿐이라 내용 변경·소스 전환을 감지할 이음새 자체가 없다. (2) 의도된 동작 여부: tests/test_nara_view.py:117-126(test_datapage_source_toggle_swaps_input_rows)은 _valid=False와 isComplete=True(ADR J 강등 — 데이터 스텝 선택화)만 단언하고 세션 잔존은 단언하지 않음 — 세션 유지가 문서화된 의도라는 증거 없음. 오히려 _on_source_toggle 주석(:322 "소스 혼선 방지")과 _apply_nara_result 독스트링(:349-353 "data_path는 캐시 키라 조합 변경을 감지해 재초안" — 감지가 성립한다는 전제)이 실동작과 모순 — 코드 자체가 캐시 키 감지를 신뢰하고 있어 내용 불감은 설계 구멍이지 의도가 아님. (3) 실피해 축소 가능성: Job은 샘플 데이터를 저장하지 않고(job_editor.py 독스트링) 실행 시 프리플라이트가 누락열을 잡으므로 최종 문서 오염으로 직결되진 않음 — 그러나 이슈 본문도 그 주장은 하지 않았고(§C는 '미리보기 구동', §T는 '잠복'으로 정확히 한정), §B는 신규 컬럼 매핑이 화면 성공 요약과 모순되게 기능적으로 불가능해지는 저작 차단이라 축소 불가. 조용한 스테일(화면=성공, 내부=옛 상태)이므로 저장소 원칙(확인-또는-경보)상 상향 규정 적용 — severity high 유지 타당. isComplete 상시 True 단독은 의도(ADR J)지만 세션 잔존과 결합해 조용한 통과를 만든다는 이슈의 결합 논지도 정확.

</details>

<details><summary>Verifier 비고</summary>

이슈의 파일:라인 인용 전부 실코드와 일치(직접 열람 확인). 증거 폴더: ...\scratchpad\review-round1\verify\RC-09\ — rc09_repro.py, rc09_run.log, B_mapping_stale_combo.png, C_datapage_after_toggle.png, C_mapping_runs_on_stale_records.png, T_raw_reselect_divergence.png. 검증 중 추가 관찰(이슈 강화): §B에서 미리보기 레코드는 wiz.records(신규)로 갱신되는데 콤보 어휘는 model.source_fields(구)라서 한 화면 안에서도 신구 혼종 — 이중 사본 발산의 직접 증상. 권고안 중 최소수정은 캐시 키에 소스 필드 집합 포함(예: key=(template_path, data_path, tuple(wiz.source_fields))) — 단 사람 확정 보존 의도(:475-476 주석)와 충돌하지 않게 소실 소스 행만 미확정 강등하는 동기화가 더 원칙 부합. _on_source_toggle의 세션 원자 초기화는 별도 필수(캐시 키 수정만으로는 §C의 '옛 records 미리보기'가 남음 — records는 캐시 키 밖).

</details>

### RC-10 · 미지 transform의 3중 실패 — 직렬화 경계 무검증 주입, 뷰 미처리 크래시(통지 0), 런타임 조용한 join 폴백으로 서식 미적용 값 무경고 주입

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F1, F2 · **유닛**: U3
- **근본 원인**: transform 검증이 set_transform 한 곳에만 있고 FieldMapping.from_dict·apply_profile은 직대입으로 우회, apply_transform if-체인이 미지 kind를 join 분기로 fallthrough — 경계 검증 부재 + 조용한 추측(원칙상 상향).
- **사용자 영향**: 감사·수기 편집·버전 혼용 상황에서 금액 서식 등이 조용히 빠진 공고서가 생성될 수 있고, GUI는 크래시조차 통지하지 않는다.
- **코드 증거**: core/mapping.py:96-105(from_dict 무검증),50-62(미지 kind→join fallthrough), gui/mapping_state.py:162-164(유일 검증),239-244(직대입), gui/mapping_table.py:310(미처리 ValueError)
- **병합 증상**:
  - transform='amonut'(오타) 매핑 파일 로드: apply_profile이 검증 우회 주입 → 테이블 refresh에서 미처리 ValueError(TRANSFORMS.index) 크래시, 모달 0건 — 사용자는 반쯤 적용 상태를 정상으로 오인, 그대로 Finish하면 오타 값이 Job에 무경고 영속화(failure P4c 실증)
  - 실행 계층 value_for는 미지 transform을 조용히 join 폴백 — '123456789' 반환(올바른 amount+fmt면 '123,456,789'), 예외·경고 없음(P4b 실증)
  - 버전 스큐(신버전 transform을 구버전이 읽음)·손 편집 프로파일이 법적 문서에 서식 미적용 값을 침묵 주입하는 경로
- **권고**: FieldMapping.from_dict에서 transform ∉ TRANSFORMS∪{'blank'}를 ValueError로 거부(기존 '매핑 파일 로드 실패' critical 경로가 수용). apply_transform 마지막 분기를 명시적 kind=='join' 검사 + else raise로.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-10\rc10_repro.py (offscreen, 임시 HWPXFILLER_HOME, QMessageBox 스파이). 관찰 결과(rc10_repro_output.log): [P4a] transform='amonut' 프로파일이 MappingProfile.load/from_dict를 무검증 통과. [P4b] FieldMapping(transform='amonut', fmt='{:,}').value_for({'presmptPrce':'123456789'}) → 예외·경고 없이 '123456789' 반환(올바른 'amount'면 '123,456,789') — 미지 kind가 join 분기로 조용히 폴백하고, fmt '{:,}'는 join 마스크 코드가 아니라서 그마저 무시됨(format_engine.py:157-161 degrade). [P4c] wizard._load_profile(577-598)과 동일 시퀀스 실행: load 성공(try 보호) → apply_profile이 검증 우회 주입(applied=1, row.transform='amonut', confirmed=True) → table.refresh()가 mapping_table.py:310 TRANSFORMS.index에서 미처리 ValueError. 실제 Qt 슬롯 문맥(버튼 클릭)에서는 PySide6가 예외를 stderr traceback으로만 삼키고 앱은 생존 — 모달 호출 0건(스파이 기록 빈 리스트), src 전체에 excepthook 부재 grep 확인. 크래시 후에도 행은 confirmed=True로 남아 to_profile()이 transform='amonut'을 그대로 영속화(persisted_job_mapping.json) — Finish 시 Job에 무경고 영속. 반쯤 렌더된 테이블 캡처 rc10_table_after_crash.png. 인용 파일:라인 전부 실코드와 일치 확인(core/mapping.py:96-105·50-62, gui/mapping_state.py:163-164·239-244, gui/mapping_table.py:310, wizard.py:586-593).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 4방향 모두 실패 → confirmed. (1) '다른 곳에서 검증되지 않나': src 전체 grep — transform 멤버십 검증은 mapping_state.py:163-164 set_transform 단 한 곳. validate.py·batch·cli·fill_ledger 어디에도 없음. CLI 경로(cli.py:190, 340)도 MappingProfile.load→apply 직행이라 P4b 폴백이 F10에도 동일 적용. (2) 'set_transform이 GUI 편집을 막으니 충분하지 않나': 실행으로 set_transform(0,'amonut')이 ValueError로 거부됨을 확인했으나, apply_profile(wizard.py:491·503·591·669 네 호출 지점 전부)과 from_profile(워크벤치)이 직대입으로 우회 — 검증이 콤보 편집 경로에만 존재. (3) '뷰가 크래시 없이 처리하지 않나': mapping_table.py:310 무가드 확인 + 런타임 ValueError 실증. blank는 from_profile/apply_profile이 join으로 정규화해 index에 안 닿지만 미지 kind는 그대로 도달. (4) '예외가 시끄럽게 표면화되지 않나': Qt 슬롯에서 PySide6가 삼킴(앱 생존, 모달 0), 패키징된 GUI exe에는 콘솔 stderr조차 없음 — 확인-또는-경보 원칙 위반의 '조용한 추측' 정확 사례. 시나리오 현실성도 성립: 프로파일은 손 편집 가능한 JSON 영속 산출물이고 from_dict에 하위호환 주석(mapping.py:104)이 있어 버전 스큐 읽기가 설계된 사용처. 기존 테스트도 미지 transform을 커버하지 않음(tests grep). 심각도 high 유지: 법적 효력 문서에 서식 미적용 값 침묵 주입 + 통지 0 크래시 + 무경고 영속화, 저장소 원칙상 조용한 폴백은 상향 대상.

</details>

<details><summary>Verifier 비고</summary>

권고안 타당성도 확인: from_dict에서 transform ∉ TRANSFORMS∪{'blank'} 거부 시 wizard.py:586-589의 기존 '매핑 파일 로드 실패' critical 경로가 이를 수용(load가 from_dict를 경유). apply_transform 마지막 분기의 명시적 kind=='join' 검사 + else raise는 2차 방어로 유효(단 'blank'/'const'는 앞 분기에서 처리됨 유의). 증거물: scratchpad\review-round1\verify\RC-10\{rc10_repro.py, rc10_repro_output.log, typo_profile.json, persisted_job_mapping.json, rc10_table_after_crash.png}. 사소한 인용 편차: 검증 지점은 162-164가 아니라 163-164(162는 def 라인) — 실질 무영향.

</details>

### RC-11 · hwpxdiff 변경 그룹 리스트가 문서상 최대 65행 떨어진 독립 변경들을 '연속 N건'으로 거짓 병합 — seq는 변경 방출 서수일 뿐 문서 인접이 아님

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.96 · **기능**: F12 · **유닛**: U5
- **근본 원인**: Change.seq는 _emit에서만 증가하고 equal은 seq를 소모하지 않아 changes[i].seq==i가 항상 성립(실측 True) — app.py:144의 'seq+1 인접' 조건은 '변경 목록에서 같은 kind가 연달아 나옴'과 동치로 문서 인접성 정보가 전무하다. 올바른 판정 기준(문서 스트림 위치/location)은 diff.py만 보유하는 계층 오배치(RC-17)가 직접 원인.
- **사용자 영향**: 법적 규격서 개정 검토자가 리스트를 체크리스트로 쓰면 그룹 라벨 위치만 확인하고 20문단 뒤 독립 변경을 놓침 — 변경 누락 유발, 조용한 과소표현(원칙상 상향).
- **코드 증거**: hwpxdiff/app.py:136-152(:144 seq+1 판정),139-141(잘못된 전제 docstring), hwpxdiff/diff.py:345-355(_emit만 seq 증가),357-360(_note_equal 미소모)
- **병합 증상**:
  - spec 2025↔2026 실측: 다중 그룹 33건 중 19건(1차)·8건(2차, 기준 상이)이 사이에 equal 문단(최대 65행)을 두고 병합 — '(연속 6건)' 그룹의 실멤버가 문단 5,7,8,9,26,29
  - 병합된 뒷 변경들은 리스트에 자기 행이 없어 첫 seq 앵커로만 점프 — 위치·발췌가 리스트에서 소실
- **권고**: 그룹 산출을 diff.py로 이관하고 rows 스트림 인덱스(또는 location 구조체)로 인접성 판정 — DiffResult/DocRow에 그룹 키를 실어 GUI·CLI 요약이 같은 그룹화를 공유(RC-17 이관 패키지와 동일 절개).

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-11\repro_rc11.py 를 .venv 파이썬(offscreen, 임시 HWPXFILLER_HOME)으로 실행, 출력을 같은 폴더 repro_output.txt 에 보존. 관찰: (A) spec_revision_2025↔2026(변경 162건)·form_purchase_v1↔v2(3건) 양쪽에서 changes[i].seq==i 불변식 True — src/hwpxdiff/diff.py:355 에서만 _seq 증가, _note_equal(diff.py:357-360)은 seq 미소모(전 파일 grep으로 다른 증가 지점 없음 확인). (B) spec 쌍에서 다중 그룹 33건 중 8건이 사이에 equal 행을 두고 병합됨(rows 스트림 인덱스 기준, '사이 행>0' 기준). 최악 그룹 '본문 1 · 문단 130 … (연속 5건)'의 실멤버는 문단 130,165,233,235,241 — 멤버 간 최대 65행(전부 equal). 이슈가 지목한 '(연속 6건)' 그룹도 정확히 재현: 멤버 문단 5,7,8,9,26,29(최대 간격 12행 equal), 리스트에는 '본문 1 · 문단 5' 라벨 한 행으로만 표기. (C) src/hwpxdiff/app.py:496-506 — 그룹당 리스트 1행, 앵커는 g.seqs[0](첫 seq)뿐, 라벨·발췌도 첫 멤버 것만 → 뒷 멤버(문단 26,29 등)는 리스트에서 위치·발췌 소실 확인. 이슈의 '19건(1차)' 수치는 다른 기준의 선행 계측이고, 본 검증 기준(사이 행>0)으로는 8건 — 이슈 본문에 병기된 2차 수치와 일치.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 3방향 모두 실패(이슈 생존). ① '의도된 동작' 가설: app.py:137-141 docstring 자체가 병합 정당화를 '문단 하나가 여러 조각으로 갈릴 때 인접 seq로 연달아 방출'이라는 전제에 둠 — 실측은 65행 떨어진 별개 문단들(130↔165↔233…)이 병합되므로 문서화된 의도와 실동작이 모순, 의도 방어 불성립. ② '테스트가 이 동작을 핀함' 가설: tests/test_gui_smoke.py:768-784 의 유일한 _group_changes 테스트는 seq 2→4 갭을 합성해 그룹 분리를 검증하는데, 실 diff 출력에서 seq 갭은 불변식상 절대 발생 불가(runtime으로 증명) — 테스트는 존재하지 않는 가드를 전제한 것으로 반증이 아니라 잘못된 전제의 방증. ③ '다른 곳에서 seq가 equal에도 증가해 인접성을 실어나름' 가설: diff.py 전체 grep — _seq 증가는 _emit(:355) 단 한 곳, _note_equal(:357-360)과 셀 equal 경로(:498)는 미소모 → 기각. 잔여 완화 요인(심각도 참작): 병합된 변경이 KPI 카운트와 전문 뷰 인라인 강조에는 여전히 존재해 완전 소실은 아니나, 체크리스트 표면(변경 리스트)에서의 조용한 과소표현이라는 핵심 결함은 그대로 — 확인-또는-경보 원칙상 상향 유지로 high 확정.

</details>

<details><summary>Verifier 비고</summary>

code_evidence 전건 직접 열람 대조 일치: src/hwpxdiff/app.py:136-152(:144 seq+1 판정, :139-141 잘못된 전제 docstring), app.py:496-506(그룹 1행·첫 seq 앵커), src/hwpxdiff/diff.py:345-355(_emit만 seq 증가), :357-360(_note_equal 미소모). 참고: 이슈의 경로 표기 'hwpxdiff/app.py'는 실제 'src/hwpxdiff/app.py'. 증거물: ...\scratchpad\review-round1\verify\RC-11\repro_rc11.py, repro_output.txt. 권고(diff.py로 그룹 산출 이관, rows 스트림 인덱스 기반 인접성 판정)는 RC-17 계층 절개와 정합 — 최소 수정 대안으로는 Change에 rows 인덱스(또는 location 기반 인접성)를 실어 app.py:144 판정만 교체하는 것도 가능.

</details>

### RC-12 · 나라장터 취득·연결시험이 UI 스레드 동기 네트워크 — 이벤트 루프 완전 동결(취소 의도가 fetch 종료까지 전달 불가, 기본 timeout 20s), 생성 경로 QThread와 비대칭

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F4, F2 · **유닛**: U6
- **근본 원인**: 링1 VM API 자체가 동기 함수(urlopen 직호출)라 어떤 링2 뷰가 불러도 블로킹 — 생성 배치는 QThread 워커(worker.py)로 옮겼지만 유일한 네트워크 표면에는 워커 대응물이 없다(§8-4). 다이얼로그 진입점 4곳 + 풀 리졸브 전부가 구조적으로 상속.
- **사용자 영향**: 정부 API 지연/DNS 실패 시 다이얼로그·부모 창 전체가 응답 없음 — 사용자가 앱이 죽었다고 판단해 강제 종료(→RC-01 파일 파괴 경로)할 수 있다.
- **코드 증거**: nara_state.py:194-210(urlopen),212-258,138(timeout 20.0), nara_view.py:202-206, run_view.py:301-304, run_state.py:75-87, matrix_state.py:89 — 대조: gui/worker.py(생성만 QThread)
- **병합 증상**:
  - 3.0s 지연 fetcher: btn_acquire.click() 반환 3.00s, 100ms 타이머 발화 3.00s(이벤트 기아 — 리페인트·입력 전부 동결), btn_test 동일(ui S6)
  - +0.3s 예약한 Cancel 클릭·rejected가 +2.50s(블록 해제 후)에야 처리 — 프리즈 중 취소 불가(failure G3)
  - run_view/matrix 풀 항목 로드도 UI 스레드에서 resolve_pool_source(동기 acquire) — 실행 준비 화면 진입 자체가 동결 가능
  - 진행 표시·취소·버튼 비활성 전무, 기본 timeout 20s면 실 hang 시 최대 20초 '응답 없음'
- **권고**: acquire/test_connection을 기존 worker 패턴의 QThread로 백그라운드화 + 취득 중 버튼 비활성·진행 표시·취소. run_view 풀 재취득도 동일 경로 공유. VM은 순수 유지(뷰가 워커에 위임).

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트·출력: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-12\repro_rc12.py 및 repro_output.txt. offscreen QApplication + MemorySecretStore(가짜 키) + 3.0s 지연 주입 fetcher(fixture tests/fixtures/nara_std_response.json 반환, 실 API 무접촉). 관찰: (a) btn_acquire.click() 반환 3.0027s — UI 스레드 완전 블록; (b) 100ms 반복 QTimer가 블록 중 0회 발화, 최대 공백 3.0034s — 이벤트 루프 기아(리페인트·입력 동결의 프록시); (c) +0.3s에 예약한 Cancel 클릭이 +3.0034s에야 처리, rejected +3.0036s — 프리즈 중 취소 의도 전달 불가; (d) btn_test.click() 반환 3.0003s — 연결시험 동일; (e) resolve_pool_source(nara 풀 항목) 반환 3.0006s — run/matrix 풀 로드 경로 동일; (f) 취득 중 버튼 비활성·진행 표시 부재 확인. 이슈의 merged_symptoms 4건 전부 수치로 재현됨. 기본 timeout 20.0(nara_state.py:138)이므로 실 hang 시 요청당 최대 ~20s '응답 없음'이라는 주장도 코드상 성립(단, urlopen timeout은 소켓 단계 기준 — DNS getaddrinfo 지연은 이보다 길 수 있어 오히려 보수적 추정).

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 시도 3방향 모두 실패(=이슈 성립). ① 인용 라인 전수 대조: nara_state.py:194-210 _fetch_raw가 urllib.request.urlopen 직호출(204행), 기본 timeout 20.0(138행), acquire=212-248, test_connection=250-271 — 전부 인용과 일치. nara_view.py:202-206 _on_acquire가 vm.acquire를 UI 스레드에서 동기 호출, _on_test(190-193)도 동일. run_state.py:75-87 resolve_pool_source nara 분기가 avm.acquire 동기 호출, run_view.py:301-304와 matrix_state.py:87-90이 이를 UI 스레드에서 부름 — 라인 인용 정확. ② 다른 곳의 비동기 처리 탐색: gui 전체 grep 결과 QThread 사용처는 run_view.py:472·matrix_view.py:264(생성 워커)뿐이고 worker.py에는 GenerateWorker/MatrixGenerateWorker만 존재 — acquire/test_connection용 워커 대응물 부재 확정. 다이얼로그 진입점 4곳(run_view.py:317, matrix_view.py:232, wizard.py:340, dataset_pool_panel.py:210) 전부 동일 동기 경로 상속. ③ 뷰 코드에 취득 중 버튼 비활성·진행 표시·취소 토큰 부재를 코드로 확인(nara_view.py 전문 열람 — busy 처리 0줄). 유일한 부정확: 이슈가 nara_view.py:202-206만 인용했으나 _on_test는 190-193(206 아님) — 실질 무영향.

</details>

<details><summary>Verifier 비고</summary>

근본 원인 서술도 정확: 링1 VM(nara_state.py)이 순수 동기 함수라 어떤 링2 뷰가 불러도 블로킹을 구조적으로 상속하며, 생성 경로만 QThread 워커(worker.py)로 옮겨진 비대칭. 권고(기존 worker 패턴으로 acquire/test_connection 백그라운드화 + 취득 중 UI 상태 처리 + run/matrix 풀 재취득 공유, VM 순수 유지)는 관찰 영향에 비례하고 기존 패턴 재사용이라 타당. severity high 유지 근거: 법적 효력 문서 생성 워크플로의 유일한 네트워크 표면이 부모 창까지 동결시키고, 사용자가 '응답 없음'으로 오인해 강제 종료할 수 있는 경로(RC-01 연쇄)가 실재 — 다만 데이터 파괴가 직접 발생하는 것은 아니어서 critical 상향은 부적절. 확인-또는-경보 원칙 관점에서도 '진행 중' 표시 전무는 조용한 상태 은폐에 해당.

</details>

### RC-13 · 취득 성공 후 기간·건수 위젯 편집이 OK 게이트를 무효화하지 않음 — 미검증 기간이 풀에 등록되어 이후 모든 실행이 실패하는 죽은 참조를 조용히 생성

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F4, F5 · **유닛**: U4
- **근본 원인**: OK 게이트가 '마지막 취득 결과'만 보고 현재 입력과 취득 결과의 정합을 보지 않음(dt/spin 변경 시그널 무배선) + 풀 등록이 취득에 쓰인 기간이 아니라 현재 위젯값(datetime_range())을 읽는 이중 소스 + register_nara가 validate_range를 미호출 — 검증이 acquire 내부에만 있어 등록 경로가 우회.
- **사용자 영향**: 매 실행이 실패하는 죽은 풀 참조가 생성되는데 원인(등록 때 기간 변경)과 증상(실행 때 기간 오류)이 시공간 분리 — 진단 난도 높은 함정. '취득 성공에서만 수용' 불변식 파괴.
- **코드 증거**: nara_view.py:202-223(_on_acquire에서만 OK 변경, 위젯 변경 시그널 connect 부재, datetime_range=현재 위젯값), dataset_pool_panel.py:215-225, dataset_pool_state.py:196-208(validate_range 미호출), run_state.py:80-86
- **병합 증상**:
  - 성공 취득 후 dt_bgn을 6개월 전으로 편집해도 OK 활성 유지(라벨은 옛 기간 — 위젯 표시와 불일치), 그대로 풀 등록 통과(bgn_dt 6개월 저장), 이후 resolve_pool_source가 실행 시점마다 '조회 기간은 최대 1개월' 실패 — 등록은 조용히 성공·실패는 사용 시점 이연(failure G1 실증)
  - 위저드/실행뷰 경로에서도 편집된 위젯 기간과 실제 레코드 기간이 불일치한 채 수용 가능
- **권고**: dt/spin 변경 시그널에서 OK 비활성 + '입력이 변경됨 — 다시 가져오세요' 표시. register_nara에 validate_range 추가. 풀 등록은 acquire 시점 캡처된 기간을 저장(RC-24의 last_result 스냅샷과 같은 절개).

<details><summary>재현 (Verifier 기록 원문)</summary>

스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-13\repro_rc13.py (offscreen, MemorySecretStore+fixture fetcher, 임시 HWPXFILLER_HOME — 실 API·실키·사용자 데이터 무접촉, 실 패널 경로 DatasetPoolPanel._register_nara_from_dialog 사용·QInputDialog만 우회). 관찰(로그 repro_rc13_log.txt, 캡처 rc13_stale_edit_ok_enabled.png): ① 기본 7일 기간 취득 성공(2건)→OK 활성, label='나라장터 · 202607051635~202607121635 · 2건'. ② dt_bgn을 6개월 전(202601121635)으로 편집 — 재취득 없음(fetch 횟수 불변)에도 OK 활성 유지, label은 옛 기간 그대로(위젯 표시와 불일치). ③ 패널 등록 경로 통과 — 풀에 opts {'bgn_dt':'202601121635','end_dt':'202607121635',...} 조용히 저장. ④ 같은 기간에 validate_range='조회 기간은 최대 1개월입니다' — 등록 시점엔 이 검증이 호출되지 않음을 직접 입증. ⑤ resolve_pool_source(실행 시점)가 RuntimeError '나라장터 데이터 취득 실패: 조회 기간은 최대 1개월입니다'로 매번 실패 — 원인(등록 때 편집)과 증상(실행 때 오류)의 시공간 분리 실증. 8개 체크 전건 PASS.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 4방향 모두 실패(=이슈 성립). (1) 인용 파일:라인 전건 대조 — src/hwpxfiller/gui/nara_view.py:202-219에서 OK 버튼은 _on_acquire에서만 변경되고, 파일 전체에 dt_bgn/dt_end의 dateTimeChanged·spin의 valueChanged connect가 전무(버튼 clicked와 buttonbox accepted/rejected만 배선). datetime_range()(nara_view.py:221-223)는 현재 위젯값을 반환. dataset_pool_panel.py:215-225는 수용 후 dlg.datetime_range()+spin 현재값을 읽음. dataset_pool_state.py:186-210 register_nara는 이름·비어있음 검사만 하고 validate_range(nara_state.py:167-182) 미호출. run_state.py:75-87 resolve_pool_source는 실행 시점 acquire가 기간 재검증→RuntimeError. 전부 이슈 서술과 일치. (2) 다른 곳의 가드 탐색 — tests/test_dataset_pool_view.py:87-104는 편집 없이 취득 직후 등록만 검증, tests/test_dataset_pool_state.py:39-53은 빈 문자열 거절만 검증: 이 경로를 막는 테스트·가드 없음. (3) 문서화된 의도 탐색 — 오히려 dataset_pool_panel.py:203-206 docstring이 '대화상자는 취득 성공에서만 수용되므로 등록 전에 사실상 연결 검증이 된다'고 주장하는데, 재현이 이 주장을 정확히 반증(수용 게이트는 취득 시점 쿼리를 검증했을 뿐 등록되는 현재 위젯값 쿼리를 검증하지 않음) — 의도된 동작이 아니라 깨진 불변식임을 확정. (4) merged_symptoms 2번(위저드/실행뷰)만 부분 반증: wizard.py:346·run_view.py:324는 dlg.records/dlg.datasource/dlg.label(전부 acquire 시점 스냅샷)을 소비하므로 수용되는 데이터 자체는 내적 정합 — 편집된 위젯 표시와 수용 라벨·데이터의 표시 불일치(혼동 유발)만 남고 죽은 참조는 생기지 않음. 심각한 경로는 풀 등록(F5) 쪽이 유일.

</details>

<details><summary>Verifier 비고</summary>

확정 근거 code_evidence: nara_view.py:202-219(OK 게이트가 _on_acquire에만, 위젯 변경 시그널 무배선), nara_view.py:221-223(datetime_range=현재 위젯값), dataset_pool_panel.py:215-225(수용 후 현재 위젯값 읽기 — 이중 소스), dataset_pool_state.py:186-210(register_nara에 validate_range 부재), nara_state.py:167-182(validate_range 정의, acquire 내부 226-228에서만 호출), run_state.py:75-87(실행 시점 재검증→RuntimeError). visual_evidence: ...\scratchpad\review-round1\verify\RC-13\rc13_stale_edit_ok_enabled.png(편집된 기간 표시+OK 활성+옛 기간 결과 라벨 동시 노출). 심각도 high 유지 타당: '취득 성공에서만 수용' 불변식(panel docstring이 명시 주장)이 깨지고 조용한 성공→이연 실패라 확인-또는-경보 원칙 위반으로 상향 가중 대상이나, 데이터 파손·문서 오생성은 없고 실행 시점 실패는 시끄러움 — critical 아님. 이슈의 merged_symptoms 2번은 축소 필요: 위저드/실행뷰는 acquire 시점 스냅샷(dlg.records/datasource/label)을 소비하므로 죽은 참조가 아니라 '수용 시점 위젯 표시 vs 수용 데이터 기간 표시 불일치'(혼동·polish급)에 그침. num_rows/page_no 편집도 동일 기전으로 풀 opts에 미검증 반영됨(재현 스크립트 opts 저장 확인). 권고(dt/spin 변경 시 OK 무효화+재취득 안내, register_nara에 validate_range, acquire 시점 캡처 기간 저장)는 관찰과 비례 — 타당.

</details>

### RC-14 · 템플릿 워크숍 패널이 실사용 강도 미달 — library_dir 공급 계약 부재로 백지, 액션 핸들러 4종 예외 무방비(확정 클릭 직후 실패도 통지 0), 스테일 단일 결과 라벨

- **심각도/유형**: high/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F7 · **유닛**: U2
- **근본 원인**: 죽은 라우트(RC-04) 뒤에서 사용자 경로 검증 없이 사장된 C5 유닛 — 템플릿 라이브러리 기본 루트를 어느 유닛도 소유하지 않고(core 기본 루트 4종에 템플릿용 부재, 시그널 관례상 무인자라 library_dir=None 확정), 링2 핸들러는 링1이 던지는 예외를 받을 준비가 없으며, 결과 표시가 단일 라벨 공유라 실패·성공·대상이 뒤섞인다. RC-04만 고치면 끝이라는 착각을 유발하는 2단 수선 대상.
- **사용자 영향**: RC-04 소생 후에도 사용자는 빈 창을 만나고, 읽기전용/점유/손상 템플릿에서 컴파일·검토가 조용히 증발한다 — 템플릿 위생 표면 전체의 신뢰 문제.
- **코드 증거**: gui/app.py:105-112(None 기본), gui/template_manager_state.py:200-206(_discover 무구분),262-265(vocabulary 미전달), gui/template_manager.py:106-114(빈상태·라벨 무효화 없음),145-202(무가드 핸들러 4종+성형 인라인), core/job.py:47·mapping_base.py:22·text_registry.py:18·dataset_pool.py:35(기본 루트 전수 — 템플릿용 부재)
- **병합 증상**:
  - TemplateManagerPanel(None) 완전 백지 — 행 0·라벨 빈 문자열, 폴더 선택 수단·빈상태 안내 전무(홈의 빈상태 패턴과 대조)
  - 세션 중 라이브러리 폴더 소실 시 rows 1→0 침묵 백지화 + 직전 결과 라벨 잔존 — _discover가 '폴더 없음'과 '빈 폴더'를 동일 []로 붕괴(failure W6)
  - 컴파일 Yes 확정 직후 PermissionError·미리보기 FileNotFoundError·드리프트 BadZipFile이 슬롯에서 삼켜져 QMessageBox 0건, lbl_result는 직전 성공 결과 잔존 — 실패한 작업 자리에 직전 결과가 보여 적극 오도(failure W2/W4/W5 실증)
  - lint/미리보기/드리프트/컴파일 결과가 단일 lbl_result를 무맥락 덮어씀 — 대상 템플릿명 미표기, 5행 라이브러리에서 식별 불가(ui S3)
  - 결과 텍스트 성형 4종이 뷰 핸들러 상주(VM 계약 docstring과 불일치, f.severity 영문 원시 노출) — 헤드리스 테스트 불가 위치
  - GUI lint에 통제 어휘(--vocab 상당) 미노출 — CLI와 위생 점검 범위 비동등(VM 시그니처부터 부재)
- **권고**: 링0에 default_templates_dir 추가 + 기본 주입 + 빈상태 안내·폴더 선택. 4개 핸들러 vm 호출을 공통 가드(QMessageBox.critical + lbl_result '실패: 사유+파일명')로, 액션 시작 시 라벨 무효화. 결과 성형은 링1 메서드로(대상 템플릿명 포함). VM.lint(path, vocabulary=None) 시그니처 정렬.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-14\repro_rc14.py (offscreen+FONTDIR+임시 HWPXFILLER_HOME, QMessageBox 4종 계측 monkeypatch, 실제 카드 버튼 click()으로 슬롯 경유). 관찰 전건 로그 repro_log.txt + 캡처 4장 동폴더 저장. [S1 백지] TemplateManagerPanel(None) → rows=0, lbl_count='', 빈상태 안내·폴더 선택 수단 전무 — s1_blank_panel_none.png(제목+드리프트 버튼만 있는 빈 창). [S2/W6 폴더 소실] rows 1→0 침묵 전환, 다이얼로그 delta={}, lbl_result에 직전 '미리보기: 계약명 = {{계약명}}' 잔존 — s2_folder_loss_stale_label.png. [S3/W2 읽기전용 컴파일] question 모달 Yes 확정 직후 hwpxcore/package.py:71 open(path,'wb')에서 PermissionError — 예외는 슬롯 안에서 stderr 트레이스백으로만 소멸(호출자 미도달, 앱 생존, windowed exe에선 불가시), critical/warning 0건, lbl_result는 직전 a_ok의 '컴파일 완료: 필드 1개 추가' 잔존 + 실패 행은 '원문' 배지 그대로 — s3_readonly_compile_stale_label.png(성공 문구가 실패 작업 밑에 표시되는 적극 오도 실증). [S4/W4 TOCTOU] 렌더 후 파일 삭제 → 미리보기 클릭 → hwpxcore/package.py:38 FileNotFoundError 동일 소멸, 통지 0건, 라벨 여전히 직전 성공 문구 — s4_toctou_preview_stale_label.png. [S5] inspect로 시그니처 대조: core lint_template(pkg_or_path, vocabulary=None, threshold=0.8) vs VM.lint(self, path) — vocabulary 전달 경로 부재, CLI는 --vocab 노출(src/hwpxfiller/cli.py:99-107). 드리프트 BadZipFile(W5)은 미실행이나 _on_drift(src/hwpxfiller/gui/template_manager.py:184-202)가 동일 무가드 패턴이라 기전은 실증 2건(W2/W4)으로 입증됨.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 4갈래 전부 실패 → confirmed. (1) '예외가 다른 층에서 잡혀 통지될 것'—전역 excepthook/핸들러 부재 확인, 런타임 실증으로 PySide6가 슬롯 예외를 stderr 인쇄 후 계속 진행(크래시도 통지도 없음), 다이얼로그 계측 0건. (2) '어딘가 library_dir을 공급할 것'—유일 라우트 gui/app.py:105-112가 기본 None이고 그 연결 자체가 home.py에 없는 시그널 뒤 hasattr 가드(app.py:39-40, home.py:127-139 grep으로 manage_templates_requested 부재 확정 = RC-04)라 죽어 있음; core 기본 루트는 job.py:47·mapping_base.py:22·text_registry.py:18·dataset_pool.py:35 4종뿐, default_templates* grep 결과 텍스트기안용(text_registry)만 존재하고 hwpx 템플릿 라이브러리용 부재; 홈 시그널 관례상 무인자(pool/matrix/vocab 전부 Signal())라 소생 후에도 None 확정. (3) '테스트가 실패 경로를 커버할 것'—tests/test_template_manager.py·test_gui_smoke.py:320-386 전수 확인: 해피패스+발견 시점 오류 행(vm.refresh의 try/except, state:211-217)만 커버, 액션 핸들러 4종(template_manager.py:145-202)의 액션 시점 예외는 무커버·무가드; 발견 시점 오류 행 처리('읽기 실패' 행)는 존재하나 액션 시점(TOCTOU·저장 실패)은 refresh를 안 타므로 미적용. (4) '빈상태·폴더 선택이 실은 있을 것'—패널 내 QFileDialog는 드리프트 판본 선택 2회뿐(185-188), 빈상태 위젯 없음(홈은 home.py:254 _build_empty_state 보유 — 대조 확인). 성형 상주·severity 원시 노출도 코드 직접 확인(template_manager.py:170-173 f"[{f.severity}] {f.message}", 모듈 docstring '얇은 렌더러' 계약과 불일치). 유일한 정상참작: RC-04로 현재 GUI 도달 불가라 실사용자 노출은 잠재적 — 그러나 이슈 자체가 'RC-04 소생 후' 2단 수선 대상으로 명시했고, Yes 확정 직후 침묵 실패+직전 성공 라벨 잔존은 확인-또는-경보 원칙 정면 위반(심각도 상향 규칙 해당)이라 high 유지.

</details>

<details><summary>Verifier 비고</summary>

code_evidence 재확인(전건 직접 열람): src/hwpxfiller/gui/app.py:105-112(library_dir=None 기본, 39-40 죽은 hasattr 배선), src/hwpxfiller/gui/template_manager_state.py:200-206(_discover — 폴더 부재·빈 폴더 동일 [] 붕괴, is_dir() False면 무구분), 263-265(lint에 vocabulary 미전달), src/hwpxfiller/gui/template_manager.py:82-84(None 기본)·96-114(빈상태 없음, 단일 lbl_result)·145-202(무가드 핸들러 4종+결과 성형 인라인, 대상 템플릿명 미표기: 163·168·170·178·180·193·202 전부 무맥락 setText), src/hwpxfiller/core/{job.py:47, mapping_base.py:22, text_registry.py:18, dataset_pool.py:35}(기본 루트 4종 — 템플릿 라이브러리용 부재), src/hwpxfiller/cli.py:99-107(--vocab CLI만 노출). 이슈가 인용한 파일:라인 전부 실코드와 일치(사소한 행번호 오차 없음). visual_evidence: 증거 폴더의 s1_blank_panel_none.png, s2_folder_loss_stale_label.png, s3_readonly_compile_stale_label.png, s4_toctou_preview_stale_label.png. 권고사항(default_templates_dir 신설+빈상태+공통 예외 가드+성형 링1 이관+lint 시그니처 정렬)은 관찰 영향에 비례하며 타당. 한 가지 보강: 예외 가드는 windowed exe에서 stderr가 소실되는 점까지 근거로 명시할 것 — 콘솔 트레이스백은 완화책이 아님.

</details>

## 중간 (medium) — 14건

### RC-15 · 파괴적 확인 정책이 두 계열로 분열 — ADR-E 강화 패턴은 _ack_partial 1곳뿐, 덮어쓰기·삭제 3곳은 기본버튼 미지정 영어 Yes/No라 Enter 반사로 파괴 확정(런타임 실증), 충돌 사실 재진술도 거짓·부재

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F1, F8 · **유닛**: U7
- **근본 원인**: 확인 헬퍼를 추출하지 않아 정책이 호출부 로컬 — 강화 패턴(한국어 명시 버튼+기본=취소+구체 재진술) 이후 추가된 확인들이 Qt 기본형 question으로 회귀했고, 확인 문구가 '무엇이 파괴되는가'를 전달하지 못하는 경우(슬러그 접힘·참조 조회 실패)까지 방치됐다. 가장 위험한 액션이 가장 약한 확인을 받는 역전.
- **사용자 영향**: 이름 입력→Enter 연타 습관이 기존 작업·공유 베이스의 매핑을 무의식 중에 교체(레지스트리 백업 없음, RC-01 비원자성과 결합 시 파괴 반경 확대).
- **코드 증거**: gui/job_editor.py:98-100(본 세션 재확인: defaultButton 미지정 축약 호출), gui/wizard.py:231-241,635-646(except Exception: return),698-707, gui/app.py:191-193, core/job.py:42-44,136-137,145-146
- **병합 증상**:
  - P1 실증: Return 키 1타로 '&Yes' 클릭 — 기존 작업 덮어쓰기 확정(defaultButton 미지정 2-인자 question). ui:F1의 investigation_needed(conf 0.6)를 failure:F1이 QTest 주입으로 확정
  - 무방비 question 3사본: 작업 덮어쓰기(job_editor.py:98-100)·베이스 덮어쓰기(wizard.py:701-706)·작업 삭제(app.py:191-193) — 대조 원본 _ack_partial(wizard.py:231-241)은 기본=취소+ADR-E 주석
  - P5a: 베이스 덮어쓰기는 참조 0개면 확인 자체가 없음(if refs and question 구조) — durable 공유 자산이 이름+Enter만으로 교체
  - P5b: _referencing_jobs가 list_jobs 예외를 except→[]로 삼켜 참조가 실존해도 전파 경고 우회 — 실패를 '참조 없음'으로 오역(조용한 오류 삼킴, RC-05의 손상 파일 상태에서 보호막이 하나 더 꺼짐)
  - P6: '예산/2026' 저장이 slug 접힘으로 '예산_2026'을 파괴하는데 문구는 입력 이름만 재진술 — 확인 내용이 거짓(기왕 인지 부채의 UI 발현)
- **권고**: confirm_destructive(parent, title, text, action_label) 공용 헬퍼(기본=취소, 한국어 라벨) 1개 추가 후 3곳 치환. 베이스 덮어쓰기는 참조 유무 무관 확인 + 조회 실패 시 '참조 여부 확인 불가' 명시. slug 충돌은 실제 파괴 대상 이름을 문구에 포함.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-15\repro_rc15.py (로그 repro_output.log). 5개 프로브 전부 REPRODUCED, 전부 임시 HWPXFILLER_HOME·임시 레지스트리(사용자 홈 비접촉), offscreen+FONTDIR. [P1] 실 코드 경로 — JobEditorWizard.accept()(src/hwpxfiller/gui/job_editor.py:98-100)로 기존 작업 'victim' 존재 상태에서 확인 모달에 QTest Return 1타 주입 → safety-close 미사용으로 &Yes 확정, filename_pattern 'ORIGINAL-{{ID}}'→'OVERWRITTEN-{{ID}}' 덮어쓰기 완료. defaultButton()은 '(없음)'(명시 미지정) — Qt가 첫 AcceptRole(Yes)을 자동 기본으로 삼아 Enter가 파괴를 확정. [CONTRAST] wizard.py:231-241 _ack_partial 패턴 복제(setDefaultButton(취소)) — 동일 Return 주입이 '취소' 클릭으로 귀결, 강화 패턴은 실제로 Enter 반사에 저항함을 대조 실증. [P5b] 손상 .job.json 1개로 JobRegistry.list_jobs()가 실제 예외 전파(core/job.py:170) 확인 후, 예외 나는 레지스트리로 wizard.py:635-646 _referencing_jobs('아무베이스') 호출 → 예외 대신 [] 반환(645-646 except Exception: return []) — 참조 실존 여부 불명을 '참조 없음'으로 오역. [P5a] 참조 작업 0개 + 동명 베이스 실존 상태에서 _save_base()(wizard.py:698-707) — QMessageBox.question 호출 0회(확인 전무), 기존 공유 베이스 필드 ['원본필드']→['필드'] 무확인 교체(if refs and question 구조라 refs 빈 리스트면 확인 자체 생략). [P6] '예산_2026' 작업 실존 + '예산/2026' 저장 — path_for 동일(core/job.py:42-44,145-146 slug 접힘), exists('예산/2026')=True로 확인은 뜨지만 문구(job_editor.py:99)는 "작업 '예산/2026' 이(가) 이미 있습니다"로 실제 파괴 대상 '예산_2026' 미언급, Yes 진행 시 파일 내용이 name='예산/2026'으로 교체돼 원본 파괴 확인. app.py:191-193(작업 삭제)도 동일 2-인자 축약 question임을 파일 직접 확인.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 4갈래 전부 실패(이슈 생존). ① 인용 라인 전수 대조: job_editor.py:98-100, wizard.py:231-241·635-646·698-707, app.py:191-193, core/job.py:42-44·136-137·145-146 모두 실제 코드와 일치 — 재진술 오류 없음. ② '다른 곳에서 이미 처리' 탐색: 전 저장소 grep 결과 setDefaultButton은 wizard.py:240 단 1곳, confirm_destructive류 공용 헬퍼 부재. 오히려 이슈가 든 3곳 외에 무방비 2-인자 question이 더 있음(vocab_workbench.py:143 베이스 삭제·:153 이름변경, dataset_pool_panel.py:152, template_manager.py:158 등) — 이슈는 과소집계 쪽. ③ 테스트 가드 탐색: tests/*는 QMessageBox.question을 통째 monkeypatch(Yes/No 분기만 검증) — 기본 버튼/Enter 반사 의미론을 단언하는 테스트 전무. ④ '의도된 설계' 문서 탐색: slug 충돌은 core/job.py:136-137 독스트링이 '스캐폴드 수용, 후일 보강'으로 기왕 인지 — 단 이는 파일 충돌 자체에 대한 것이고, 확인 문구가 파괴 대상을 오재진술하는 UI 발현(P6)이나 question 기본버튼 회귀를 의도로 문서화한 곳은 없음. 이슈 원문 중 P6를 '기왕 인지 부채의 UI 발현'으로 이미 한정한 것도 정확. Qt 의미론 반증(기본버튼 미지정이면 Enter가 무해할 가능성)은 P1 런타임으로 직접 격파 — 미지정 시 Qt가 Yes를 자동 기본으로 승격.

</details>

<details><summary>Verifier 비고</summary>

심각도 medium 유지 타당: 파괴 확정에는 여전히 사용자 키 입력 1타가 필요하고 대상이 재작성 가능한 작업/베이스 정의(생성 문서 아님)라 critical/high까지는 아니나, P5b는 '조용한 오류 삼킴→보호막 우회'로 확인-또는-경보 원칙 위반의 정면 사례(§7 상향 규칙의 근거)이며 merged 이슈의 medium은 이를 이미 반영한 수준. 병합 5증상 중 5/5 재현. 수정 권고(공용 confirm_destructive 헬퍼 + 참조 조회 실패 시 '확인 불가' 명시 + slug 충돌 시 실제 파괴 대상 명기)는 관찰 영향에 비례하고 최소 경계임. 부수 발견(참고): 무방비 question 사본은 3곳이 아니라 vocab_workbench 삭제/이름변경 등 최소 5곳+ — 헬퍼 치환 시 함께 정리 권장. 증거물: repro_rc15.py, repro_output.log (RC-15 증거 폴더).

</details>

### RC-16 · 예외→사용자 메시지 번역 층 부재 — 3개 CLI가 일상 실패를 원시 traceback으로 노출하고 exit 1이 게이트/부분실패/크래시를 구분 못하며, GUI 오류 문구도 원인 파일·다음 행동을 지목 못함

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F10, F4, F7, F12, F13 · **유닛**: U8
- **근본 원인**: 최상위 오류 경계 설계가 없음 — 검증 실패(정돈된 진단+exit)와 예외(traceback)가 뒤섞이고, 종료코드 의미 체계가 충돌(lint의 '이슈 게이트 exit 1' vs 크래시 exit 1, 부분실패 1 vs 사이드카 실패 1). GUI 쪽도 str(exc) 직행으로 파서·errno 원문이 사용자에게 관통.
- **사용자 영향**: 자동화 파이프라인이 실패 종류를 오분류하고(성공 배치 재실행 유발 포함), 비개발자 사용자는 traceback·영어 파서 문구 앞에서 행동 불가.
- **코드 증거**: hwpxfiller/cli.py:360,366-367,333,107,113,125,68, batch.py:47(out.mkdir raise), hwpxdiff/cli.py:25-31, hwpxdiff/app.py:475-479, hwpxdiff/diff.py:658-660, nara_state.py:236-237, run_view.py:509-511(GUI측 대조 구현)
- **병합 증상**:
  - hwpxfiller CLI: --out이 기존 파일이면 FileExistsError 15줄 traceback(FX3b); --ledger 쓰기 실패 시 문서 3건 생성 완료 후 PermissionError traceback+exit 1로 '생성 실패' 위장 — 성공 배치 재실행 유도(→RC-02 덮어쓰기)(FX6, GUI는 같은 상황을 '[원장 실패]'로 처리하는 비대칭); NaraFetchError 미처리 traceback(마스킹은 유지)(C4)
  - hwpxfiller lint/drift/fieldize: 손상·부재 파일에서 traceback+exit 1 — '위생 이슈 게이트 1'과 구분 불가로 자동화가 손상 템플릿을 이슈 있는 정상 템플릿으로 오분류(5케이스 실증)
  - hwpxdiff CLI: 예외 처리 전무 — BadZipFile 'File is not a zip file'만으로 어느 판본이 손상인지 미지목(C1~C3)
  - hwpxdiff GUI 모달: 원시 영어 예외+판본 미지목(diff_files가 두 파일을 한 번에 열어 원인 문맥 소실)
  - F4 GUI: XML(비JSON) 오류 응답 시 'Expecting value: line 1 column 1' 파서 원문 노출 — 응답 본문의 returnAuthMsg(실원인) 소실(G2)
- **권고**: 각 CLI main에 최상위 try 경계: OSError/BadZipFile/NaraFetchError → '[오류] …' 한국어 1줄 + 게이트(1)와 구분되는 코드(2). 원장 실패는 '[원장 실패]' 진단 후 생성 성패 기준 exit 유지. diff는 판본별 분리 로드로 '구판/신판' 지목. F4는 JSON 해석 실패 시 XML returnAuthMsg 추출 문구.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 하네스: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-16\repro_rc16.py (실 네트워크 0건, 저장소 무수정, 케이스별 로그 + summary.json 동봉). 12케이스 전건 실행 결과:
[FX3b] `hwpxfiller --out <기존파일>` → batch.py:47 out.mkdir에서 FileExistsError 원시 traceback(14줄)+exit 1 (case1 로그).
[FX6] `--ledger` + out/fill-ledger.json 자리에 디렉터리 → stdout "완료: 3/3 성공" 출력·hwpx 3건 실제 디스크 생성 확인 후, fill_ledger.py:371 write_text에서 PermissionError traceback+exit 1 — 자동화가 exit code만 보면 성공 배치를 실패로 오분류(재실행→RC-02 덮어쓰기 위험 실증). GUI 동일 상황은 run_view.py:509-511이 catch해 "[원장 실패]" 진단 — 비대칭 확인 (case2 로그+생성 파일 목록).
[lint/drift/fieldize] 손상 파일 lint→BadZipFile traceback exit 1(case3a), 부재 파일→FileNotFoundError traceback exit 1(case3b), drift/fieldize 손상→traceback exit 1(case3d/3e). 대조군: 정상 템플릿 어휘 게이트 lint→정돈된 findings 출력+exit 1(case3c2), 이슈 없음→exit 0(case3c). 즉 '위생 게이트 1'과 '크래시 1'이 exit code로 구분 불가 — 실증.
[hwpxdiff CLI] 손상 구판+정상 신판 → `zipfile.BadZipFile: File is not a zip file` traceback exit 1, 메시지에 파일 경로·판본 미포함(case4); 신판 부재도 동일 형태(case4b). hwpxdiff/cli.py:16-31 예외 처리 전무 확인.
[F4 G2] NaraAcquireViewModel(MemorySecretStore+주입 fetcher)로 data.go.kr 인증실패 XML(returnAuthMsg=SERVICE_KEY_IS_NOT_REGISTERED_ERROR) 반환 → res.error == "Expecting value: line 1 column 1 (char 0)" — 실원인 returnAuthMsg 완전 소실(case5, nara_state.py:236-237 경로).
[C4] 서브프로세스 내 urlopen 몽키패치 후 cli.main(--source nara) → NaraFetchError 미처리 traceback+exit 1, 메시지엔 마스킹 유지(가짜 키 미노출)(case6, cli.py:268 무가드 확인).
code_evidence(전부 직접 열어 대조): src/hwpxfiller/cli.py:281-368(main 최상위 try 부재)·:93,113(lint 게이트 exit 1 문서화)·:268(records() 무가드), src/hwpxfiller/batch.py:47, src/hwpxfiller/core/fill_ledger.py:371, src/hwpxfiller/gui/run_view.py:509-511, src/hwpxdiff/cli.py:16-31, src/hwpxdiff/app.py:471-479(str(exc) 직행 모달), src/hwpxdiff/diff.py:658-660(양 판본 동시 로드), src/hwpxfiller/gui/nara_state.py:230-237.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 4갈래 전부 실패(이슈 생존): ① "이미 어딘가 처리되나?" — hwpxfiller/cli.py(413줄)·hwpxdiff/cli.py(36줄) 전문을 읽음: 두 main 모두 최상위 예외 경계 없음. 검증 실패류(ap.error, 드리프트 cli.py:348, missing_columns 경고)만 정돈돼 있고 OSError/BadZipFile/NaraFetchError는 전부 관통. tests grep 결과 NaraFetchError 테스트(tests/test_nara.py:111-149)는 데이터소스 계층의 마스킹만 검증 — CLI 경계의 traceback 노출을 의도로 문서화한 테스트·주석 없음. ② "exit code가 실제로 구분되나?" — 실측: 게이트 1(case3c2) vs 크래시 1(case3a/3b/3d/3e) 동일값, 부분실패 1(cli.py:368) vs 원장실패 1(case2)도 동일값. 구분 불가 실증. ③ "FX6이 과장인가?" — stdout엔 '완료: 3/3 성공'이 남으므로 사람이 전체 출력을 읽으면 성공을 알 수 있음(부분 반증). 그러나 자동화 계약은 exit code이고 그게 1이며, 같은 저장소의 GUI가 동일 실패를 비치명(warn)으로 처리(run_view.py:509-511)해 '생성 성패 기준 exit'가 이 코드베이스 자신의 의도임을 방증 — 주장 유지. ④ "diff가 판본을 정말 미지목?" — 부분 반증 성립: Python 3.13 caret 주석이 traceback에서 extract_document(old_path) 호출을 가리켜 개발자는 CLI에서 구판임을 추론 가능. 단 예외 메시지 자체엔 경로·판본 없음 + GUI 모달(app.py:479)은 str(exc)만 표시해 caret 정보가 아예 없으므로 사용자 관점 주장은 유지. 사소 정정: FX3b traceback은 15줄이 아닌 14줄(비물질적). 종합: 병합 증상 5개 전부 재현·코드 대조 성립, root_cause(최상위 오류 경계 부재+종료코드 의미 충돌) 타당 — confirmed, severity medium 유지(시끄럽게 실패하긴 하므로 '조용한 no-op' 상향 규칙 비적용, 단 FX6의 exit 오분류는 medium의 상단).

</details>

<details><summary>Verifier 비고</summary>

증거 폴더: ...\scratchpad\review-round1\verify\RC-16\ — repro_rc16.py, case1~case6 로그 12건, summary.json. 권고 보완: hwpxdiff CLI 수리 시 판본별 분리 로드(diff.py:660의 단일식 호출 분해)가 이슈 recommendation대로 필요하며, GUI 모달도 같은 분리 없이는 판본 지목 불가. F4는 nara_state.py:236 파싱 실패 경로에서 XML 여부 감지 후 returnAuthMsg/returnReasonCode 추출이 정확한 수리 지점. lint의 '이슈 게이트 exit 1'은 문서화된 의도(cli.py:93)이므로 크래시를 별도 코드(예: 2)로 분리하는 방향이 기존 계약 비파괴.

</details>

### RC-17 · hwpxdiff 성형·렌더 로직의 뷰 상주(링1 부재) — 같은 DiffResult가 GUI와 CLI HTML에서 다른 낱말 강조로 렌더(8/85행 실측), 사본·라벨 재파싱·팔레트 이원 동반

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F12, F13 · **유닛**: U5
- **근본 원인**: 단일 화면 앱이라 링1 분리를 생략한 채 성장 — stdlib-only 순수 함수 무리가 Qt 임포트 모듈(app.py)에 갇혀 CLI 렌더가 재사용 불가하고, DocRow에 구조화 키가 없어 뷰가 사람용 라벨 문자열을 준-API로 재파싱한다. RC-11(그룹 거짓 병합)의 구조적 원인이며 §8-7 사본의 상위 원인. ARCH_UI_SEPARATION.md가 앱 A를 스코프 밖으로 명시해 선언 위반이 아닌 관용 이탈.
- **사용자 영향**: GUI로 검토한 사람과 HTML 리포트를 회람받은 사람이 같은 변경을 다른 강조로 읽는다 — 표면 간 정보 동등성 파괴. 나머지는 유지보수 드리프트 표면.
- **코드 증거**: hwpxdiff/app.py:92-118,215(_coalesce_ops GUI 전용),131-133,173-179,67-71,188-221,429-439, hwpxdiff/diff.py:635-638,732-748,847-848,773-774,668-673(단일 출처 선언 주석)
- **병합 증상**:
  - _coalesce_ops가 GUI 렌더에만 적용 — CLI HTML은 원본 word_ops 파편 렌더('’25~’26→’26~’27'이 GUI 한 덩어리 vs HTML 잘게 쪼개짐), word_ops 보유 85행 중 8행 갈림 실측(두 리뷰어 독립)
  - _snippet 문자 단위 동일 사본 2개(app.py:131-133/diff.py:635-638) — app.py는 이미 .diff 심볼 7종 임포트 중(§8-7)
  - _row_group_key가 ' · ' 라벨 문자열 split으로 그룹 헤더 역산 — 라벨 포맷 변경 시 테스트 실패 없이 전문 뷰 헤더 침묵 오분류
  - del/ins 강조·틴트 팔레트가 GUI CSS와 HTML CSS에 서로 다른 하드코딩(#fdecec vs #ffe3e3 등) — 저장소 스스로 명문화한 색 단일 출처 원칙과 상충, 리터럴 6곳+
  - 순수 로직 테스트 전부가 PySide6 로드 강제('headless' 명명 테스트 포함), 최근 비교 QSettings 파싱이 뷰 상주 + 손상 침묵 폴백
- **권고**: 이관 패키지: _coalesce_ops→diff.py(순수 함수, test_architecture 무충돌) 후 _render_inline과 공유, _snippet 사본 삭제, 그룹화·구조화 키를 diff.py 소유(RC-11과 동일 절개), 팔레트 리터럴을 KIND_COLORS/style 상수 참조로.

<details><summary>재현 (Verifier 기록 원문)</summary>

독립 재현 스크립트 repro_rc17.py 작성·실행 (증거: ...\scratchpad\review-round1\verify\RC-17\repro_rc17.py 및 repro_rc17.log). 실측 결과 — (A) 프레시 인터프리터에서 import hwpxdiff.diff 후 PySide6 미로드(False), import hwpxdiff.app 후 PySide6.QtWidgets 로드(True): 순수 함수 무리가 Qt 임포트 모듈에 갇힘 확증. (B) corpus 실물(spec_revision_2025 vs 2026, rows=371, changes=162)에서 word_ops 보유 85행 중 _coalesce_ops로 GUI/CLI 렌더가 갈라지는 행 정확히 8건 — 이슈 주장 수치와 일치(선행 리뷰어 audit_f12_coupling.log와도 일치, 3중 독립 확인). 구체 사례(seq=0, '본문 1 · 문단 5'): 같은 word_ops가 GUI에선 <del>25~’26</del>/<ins>26~’27</ins> 한 덩어리, 실제 render_html 산출물(chg-0 블록 덤프)에선 ’<del>25</del><ins>26</ins>~’<del>26</del><ins>27</ins> 3파편 — 이슈가 든 예시 그대로 재현. (C) _snippet 사본: app.py:131-133 vs diff.py:635-638, docstring 제외 로직 라인 문자 단위 동일(inspect.getsource 대조). (E) 팔레트 리터럴: GUI _QT_VIEW_CSS(#fdecec/#e5f2ea, app.py:67-71 + 행 틴트 하드코딩 app.py:210,213) vs CLI _HTML_CSS(#ffe3e3/#dcffe0, diff.py:773-774) 상이 확인. 인용 파일:라인 전수 대조 — 실제 경로는 src/hwpxdiff/(이슈는 hwpxdiff/로 표기)이나 라인 번호는 전부 일치: _coalesce_ops app.py:92-118 적용점 215(GUI _render_doc_html 내부만), CLI는 diff.py:847-848에서 원본 c.word_ops를 _render_inline(732-748)에 직결. _row_group_key app.py:173-179가 ' · ' split으로 라벨 재파싱, DocRow(diff.py:191-206)는 label:str만 보유(Change의 location dict 같은 구조화 키 부재), 라벨 생산은 diff.py:472,479,493-494,571. 최근 비교 QSettings 파싱 app.py:429-434 손상 시 침묵 [] 폴백. diff.py:664-673 주석이 색 단일 출처 원칙 명문화.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

4갈래로 공격했고 3갈래 실패, 1갈래는 부분 성공(뉘앙스만). ① "갈림이 의도된 설계인가": app.py:16-17 docstring은 render_html을 CLI 전용으로 남긴다고만 선언 — 강조 입도가 표면 간 달라야 한다는 의도는 어디에도 없고, _coalesce_ops 주석(app.py:77-78,93)은 coalesce를 파편화 '문제'의 수정으로 규정 → CLI HTML은 알려진-나쁜 렌더를 그대로 노출 중. ARCH_UI_SEPARATION.md:65가 앱 A를 스코프 밖으로 명시함도 확인(선언 위반 아닌 관용 이탈이라는 이슈 서술 정확). 반증 실패. ② "다른 곳에서 가드되는가": _row_group_key의 ' · ' 계약을 잇는 테스트 부재 확인 — test_gui_smoke.py:844-861은 합성 DocRow에 라벨을 하드코딩해 diff.py가 구분자를 바꿔도 통과 유지(침묵 오분류 주장 성립). 순수 함수 테스트(_visible:758-765, _group_changes:768-784, _coalesce_ops:787-809, _render_doc_html:844-861)는 전부 test_gui_smoke.py에서 hwpxdiff.app 임포트 → PySide6 강제, 'headless' 명명 테스트(758행) 포함 — 주장 성립. 반증 실패. ③ "팔레트 이원이 과장인가": 부분 성공 — 배지색은 KIND_COLORS 단일 출처가 테스트로 집행됨(test_gui_smoke.py:898-914, HTML .b-* 생성도 diff.py:780-783에서 CATEGORY_COLORS 파생). 그러나 del/ins 강조·행 틴트는 무가드 이원 하드코딩 그대로(GUI 4곳: app.py:69,70,210,213 vs HTML 2곳: diff.py:773,774) — 이슈의 핵심 주장은 유지, '리터럴 6곳+' 표현도 실측과 부합. ④ "사용자 영향이 없는 수준인가": 실측 8/85행(~9.4%)이 같은 변경을 다른 낱말 경계로 강조 — 법적 효력 문서 검토 도구에서 GUI 검토자와 HTML 회람자의 표면 간 정보 동등성 파괴는 실재하나, 기저 텍스트·변경 집합 자체는 동일(데이터 오염 아님) → severity medium 유지가 적정, 상향·하향 모두 근거 부족. 종합: defect confirmed, medium 유지.

</details>

<details><summary>Verifier 비고</summary>

증거물: C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-17\repro_rc17.py, repro_rc17.log. 정정 1건: code_evidence의 경로는 src/hwpxdiff/app.py·src/hwpxdiff/diff.py가 정확(이슈는 src/ 누락, 라인 번호는 전부 유효). 보강 2건: (1) 배지색·범주색은 이미 단일 출처+테스트 집행(test_gui_smoke.py:898-914, diff.py:780-783) — 팔레트 증상은 del/ins 강조·틴트 리터럴에 국한해 서술해야 정확. (2) 권고의 _coalesce_ops→diff.py 이관은 stdlib-only 제약과 무충돌 확인(순수 함수, 현재도 diff.WordOp만 소비). recommendation 타당성 지지. RC-11(그룹 거짓 병합)의 구조적 원인이라는 연결 주장은 이 검증 범위 밖이나, _group_changes가 app.py 상주(136-152)이고 seq 인접 조건이 라벨·구조 정보 없이 동작함은 코드로 확인됨.

</details>

### RC-18 · 섹션 0개 빈 컨테이너 HWPX 쌍을 '변경 없음'으로 단언 — 추출 완전성 신호를 diff 표면 어느 층도 실패로 승격하지 않음

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F12, F13 · **유닛**: U5
- **근본 원인**: 패키지 검증(_validate)은 mimetype 존재만, text_extract는 section 매치 0건을 조용히 빈 목록으로, diff_files는 완전성 검사 없음, Document.unhandled 원장은 hwpxdiff 전체에서 참조 0건 — '추출된 본문이 0'이 어떤 경보도 만들지 않는 조용한 빈 결과.
- **사용자 영향**: 읽을 수 없는/변형 컨테이너를 물리면 법적 문서 검토 도구가 '변경 없음'이라는 최악 방향의 거짓 음성을 낸다. 트리거는 드묾(암호화 HWPX는 시끄럽게 실패함을 확인).
- **코드 증거**: hwpxcore/package.py:50-52, hwpxcore/text_extract.py:462-466, hwpxdiff/diff.py:658-660, hwpxdiff 전체 'unhandled' grep 0건
- **병합 증상**:
  - mimetype만 있는 zip 쌍 비교: GUI 모달 없음·KPI 0/0/0/0 — 진짜 동일 문서 비교와 시각적으로 동일, CLI exit 0 + '(변경 없음)'(W2/C7 실증)
  - 실문서 vs 빈 컨테이너는 removed 228건으로 드러나지만 양쪽 다 빈 컨테이너면 완전 침묵 — 거짓 음성('개정 없음' 오결론)
- **권고**: diff_files(또는 호출부)에서 양 문서 추출 문단 수 0이면 예외 또는 경고 플래그 — RC-17 이관 시 GUI/CLI 공유 지점에 완전성 게이트 배치.

<details><summary>재현 (Verifier 기록 원문)</summary>

스크립트: ...\scratchpad\review-round1\verify\RC-18\repro_rc18.py (offscreen, QT_QPA_FONTDIR, 임시 HWPXFILLER_HOME, QMessageBox 3종 monkeypatch). 관찰: (a) mimetype 단독 zip 쌍 → extract_document sections=0/headers=0/footers=0/unhandled={}; (b) diff_files summary 전항목 0; (c) CLI exit=0 + '(변경 없음)' 출력; (d) GUI _on_compare 모달 0건, KPI 0/0/0/0, kpi_wrap 표시(오류 안내 없음) — 캡처 gui_empty_pair.png; (e) 대조군 동일 실문서(spec_revision_2025.hwpx) 2회 비교도 KPI 0/0/0/0 + CLI '(변경 없음)' exit 0 — CLI 출력은 빈 쌍과 구분 불가, GUI는 KPI 동일하나 본문 페인만 다름(gui_identical_real.png); (f) 실문서 vs 빈 컨테이너는 removed=228로 시끄러움 — 양쪽 다 비어야만 완전 침묵(거짓 음성) 확인. 전 assert 통과, 로그 repro_log.txt 저장.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 공격 4방향 모두 실패(=이슈 생존). (1) 인용 파일:라인 전수 대조 — src/hwpxcore/package.py:50-52 _validate는 mimetype 엔트리 존재만 검사(정확); src/hwpxcore/text_extract.py:462-466 section 루프는 매치 0건이면 조용히 빈 sections(정확, section_xml_names:229-242도 매치 없으면 빈 목록 반환); src/hwpxdiff/diff.py:658-660 diff_files는 완전성 검사 전무(정확); src/hwpxdiff 전체 'unhandled' grep 0건 재확인 — extract_document가 채우는 doc.unhandled 원장(text_extract.py:481)을 diff 표면 어디서도 소비 안 함. (2) 다른 층 가드 탐색 — hwpxdiff/cli.py:25-31 무조건 return 0, render_summary(diff.py:727-728)는 changes 비면 '(변경 없음)' 출력, app.py:471-484 _on_compare는 예외만 모달 처리(빈 결과는 정상 경로), 빈 문서 검사 코드 부재. (3) 테스트/문서화된 의도 탐색 — tests 전체에서 빈 컨테이너 쌍 시나리오 커버 0건(mimetype 관련 테스트는 zip 규칙 검증뿐). (4) 재현 실패 시도 — 오히려 전 층 침묵이 그대로 재현됨. 유일한 부분 반증: GUI 본문 페인은 빈 쌍에서 공백, 동일 실문서 비교에서는 본문 렌더 — 'GUI 시각적으로 완전 동일' 주장은 KPI 타일·모달 부재·CLI 출력에 한해 정확하고 본문 페인은 다름. 단 이는 경보가 아닌 모호한 공백이라 결함 자체는 유지.

</details>

<details><summary>Verifier 비고</summary>

정정 1건: merged_symptoms의 'GUI가 진짜 동일 문서 비교와 시각적으로 동일'은 KPI 타일(0/0/0/0)·모달 부재·CLI 출력에 한해 정확 — 본문 신구대비표 페인은 빈 쌍에서 완전 공백, 동일 실문서에서는 본문 렌더로 구분 가능. 단 공백 페인은 경보가 아니라 해석을 사용자에게 떠넘기는 모호 신호이며, CLI(F13)는 exit 0 + '(변경 없음)'으로 완전한 거짓 음성. 확인-또는-경보 원칙 위반(조용한 빈 결과)으로 상향 압력이 있으나, 트리거 희귀성(암호화 HWPX는 zipfile 예외로 시끄럽게 실패, 정상 훼손 경로 드묾)을 감안해 원안 medium 유지. 수리 지점은 권고대로 diff_files 또는 GUI/CLI 공유 호출부의 완전성 게이트(양 문서 추출 문단 0 → 예외/경고)가 적절 — extract_document의 doc.unhandled 원장을 diff 표면이 소비하기 시작하면 부수 이득. 증거물: repro_rc18.py, repro_log.txt, gui_empty_pair.png, gui_identical_real.png (모두 ...\scratchpad\review-round1\verify\RC-18\).

</details>

### RC-19 · 대규모 전량 개정 문서에서 hwpxdiff 비교가 UI 스레드를 수십 초 동결 — 전쌍 SequenceMatcher.ratio O(N²) + 동기 핸들러(취소·진행 없음)

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.95 · **기능**: F12 · **유닛**: U5
- **근본 원인**: _pair_replace_block이 quick_ratio 프리필터 없이 replace 블록 내 모든 old×new 쌍에 ratio를 계산(문단 2배당 약 4배 스케일) + _on_compare가 UI 스레드에서 diff+렌더+바인딩을 동기 수행 — 대개정(이 도구의 존재 이유인 상황)에서 창이 '응답 없음'으로 전이.
- **사용자 영향**: 수백~수천 문단 대개정 리뷰에서 창 동결 — 사용자 강제 종료 유도. 실코퍼스 규모 무증상이라 우선순위는 프리필터.
- **코드 증거**: hwpxdiff/diff.py:415-425, hwpxdiff/app.py:471-483
- **병합 증상**:
  - 전량 재작성 100/200/400/800문단: 0.27/1.11/4.70/19.94s 실측(quadratic), 실코퍼스 371행은 0.09s 무증상(W4)
  - 동결 중 강제 종료 시 비교 결과 전체 유실
- **권고**: 단기: cands 수집에 quick_ratio/real_quick_ratio 프리필터. 중기: 비교를 워커 스레드로(F2 worker 패턴).

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-19\repro_rc19.py (출력 로그 repro_output.log 동일 폴더). 합성 전량 재작성 문단 계열(인메모리 Document, 파일 비접촉)로 diff_documents 실측: n=100→0.603s, 200→2.480s(x4.11), 400→10.779s(x4.35), 800→40.659s(x3.77) — 문단 2배당 약 4배의 명백한 O(N²). 이슈의 19.94s(800문단) 주장보다 이 환경에서 더 나쁨(40.7s). 대조군: 실코퍼스 tests/corpus/real/spec_revision_2025↔2026.hwpx는 0.029s(summary 36/41/78/7 — 킥오프 관찰치와 일치)로 무증상 주장(W4)도 확증. 코드 확인: src/hwpxdiff/diff.py:415-425 _pair_replace_block이 프리필터 없이 전쌍 SequenceMatcher.ratio 계산(파일 전체 grep에 quick_ratio/real_quick_ratio/size cap 0건), src/hwpxdiff/app.py:471-484 _on_compare가 UI 스레드에서 diff_files+HTML렌더+테이블 바인딩을 동기 수행(app.py 전체에 QThread/worker/thread 0건, 유일 완화는 WaitCursor). 따라서 800문단 전량 개정 시 UI 스레드 40초 동결이 연역적으로 성립. 참고: 인용 경로는 src/ 접두 누락(hwpxdiff/→src/hwpxdiff/), 라인 번호 자체는 정확.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

4갈래 공격 모두 반증 실패. (1) 프리필터·크기 상한이 다른 곳에 존재하는가 — diff.py 전체 grep: quick_ratio·cap·limit류 0건, _REPLACE_PAIR_THRESHOLD(0.6, :93)는 ratio 계산 '후' 필터라 비용 절감 없음. (2) app.py에 워커/스레딩이 있는가 — QThread|worker|thread grep 0건, _on_compare(:471)는 슬롯에서 diff_files를 직접 호출. (3) 외곽 문단 매처가 replace 블록을 분할해 N×N을 막는가 — 전량 재작성은 equal 앵커가 없어 섹션 전체가 단일 replace 블록이 됨을 실측 4배 스케일링으로 확증. (4) 실코퍼스 무증상이 결함 자체를 기각하는가 — 아니오: 도구 목적이 규격서 대개정 비교이므로 수백 문단 개정은 정상 사용례이고, 무증상은 심각도를 medium으로 한정할 뿐. 추가 관찰: 합성 케이스에서 임계 0.6 이상 쌍이 0개(전부 added/removed)인데도 40s 소요 — 짝짓기 성패와 무관하게 O(N²) ratio 비용을 전액 지불함이 확인돼, quick_ratio 프리필터 권고의 타당성도 지지됨.

</details>

<details><summary>Verifier 비고</summary>

code_evidence 정정: src/hwpxdiff/diff.py:415-425 (cands 수집 루프, :422 ratio 호출, :93 임계값), src/hwpxdiff/app.py:471-484 (_on_compare 동기 핸들러, :475 diff_files, :483 _render_doc_html). 증거물: scratchpad\review-round1\verify\RC-19\{repro_rc19.py, repro_output.log}. 권고 타당성: 단기 quick_ratio/real_quick_ratio 프리필터(difflib 표준 관용구, O(n) 상한 계산으로 비유사쌍 조기 기각), 중기 워커 스레드 이관은 hwpxfiller F2 worker 패턴 재사용 가능. 확인-또는-경보 원칙 관점: 동결은 '조용한 실패'는 아니나 진행 표시·취소 부재로 사용자가 강제 종료를 유도당하는 경로라 medium 유지가 적정(실코퍼스 규모 무증상이므로 상향 불요).

</details>

### RC-20 · 출력 파일명 패턴 계약 부실 — 기본값 2종이 3링 4곳 산재, 빈 입력 시 화면에 없던 값으로 조용한 폴백, 미치환 {{토큰}}이 무경고로 실파일명이 됨

- **심각도/유형**: medium/defect · **판정**: 확정(재현+반증 통과) · **신뢰도**: 0.97 · **기능**: F1, F10, F4 · **유닛**: U8
- **근본 원인**: 기본 패턴의 단일 출처 부재(§8-9): UI 프리필('공고서-{{ID}}')과 저장 폴백·CLI·dataclass·from_dict('output-{{ID}}')가 서로 다른 리터럴로 하드코딩. 더해 파일명 패턴 치환이 레코드에 없는 키를 조용히 원문 유지 — 문서 식별자 결정에 확인-또는-경보 부재.
- **사용자 영향**: 법적 문서의 파일 식별자가 사용자가 본 적 없는 규칙으로 결정되고, 나라 소스 일괄 생성물이 output-{{ID}}_N.hwpx로 쌓여 식별 불가.
- **코드 증거**: gui/job_editor.py:106,138(본 세션 재확인),163-170, core/job.py:72,117, cli.py:305
- **병합 증상**:
  - 패턴 칸을 비우고 저장하면 화면에 등장한 적 없는 'output-{{ID}}'가 무고지 저장(ui S3·failure P7 이중 실증), isComplete는 패턴 공백 미검사
  - 기본값 4곳 산재: job_editor.py:138 UI '공고서-' / :106 or-폴백 / core/job.py:72 dataclass / :117 from_dict — 사본 드리프트의 전형
  - --source nara + 기본 패턴 조합은 레코드에 'ID' 키가 없어 항상 'output-{{ID}}.hwpx', 'output-{{ID}}_1.hwpx' 실파일 생성 — 경고 없이 '완료: 2/2 성공'(ui:F4 실증). 본문 미치환 토큰은 시끄럽게 다루는 원칙과 대조되는 파일명 토큰의 조용한 통과
- **권고**: core/job.py에 DEFAULT_FILENAME_PATTERN 상수 1개 → 4곳 참조. 빈 패턴은 isComplete 게이트 차단. 파일명 토큰 미치환 시 경고(가능하면 실패) + --source nara 도움말에 패턴 지정 명시.

<details><summary>재현 (Verifier 기록 원문)</summary>

재현 스크립트 C:\Users\rfast\AppData\Local\Temp\claude\C--Users-rfast-Desktop-PYTHON-Projects-hwpx-filler\0a3caf83-a8bb-4b75-aa15-ffe56dee4654\scratchpad\review-round1\verify\RC-20\repro_rc20.py (offscreen, 임시 HWPXFILLER_HOME, QMessageBox monkeypatch, 실 API 비접촉). 관찰 결과 — [P7] 패턴 칸을 비운 상태에서 SaveJobPage.isComplete()=True(패턴 공백 미검사, src/hwpxfiller/gui/job_editor.py:163-170), accept() 저장 성공, 모달 호출 0건(무고지), 저장 JSON filename_pattern='output-{{ID}}'(폴백 src/hwpxfiller/gui/job_editor.py:106; UI 프리필은 '공고서-{{ID}}' :138) — 증거 p7_saved_job.json. [nara] fixture 2건(tests/fixtures/nara_std_response.json, 주입 fetcher) + cli.py:305 기본 패턴 'output-{{ID}}'로 generate_batch(cli.py:360 동일 호출) → 레코드에 'ID' 키 부재, 생성 실파일명 ['output-{{ID}}.hwpx', 'output-{{ID}}_1.hwpx'], 완료: 2/2 성공, 경고 없음 — 증거 repro_log.txt, nara_out/. 기본값 4곳 산재도 grep으로 전수 확정: job_editor.py:106, core/job.py:72, core/job.py:116(이슈의 :117은 1줄 오차), cli.py:305 — 전부 'output-{{ID}}' 리터럴 하드코딩, UI만 '공고서-{{ID}}'.

</details>

<details><summary>반증 시도 (Verifier 기록 원문)</summary>

반증 시도 3갈래 전부 실패(이슈 성립). ① 인용 파일:라인 전수 대조 — job_editor.py:106,138,163-170 / core/job.py:72 / cli.py:305 실코드와 정확 일치; 유일한 오차는 from_dict 기본값이 core/job.py:117이 아닌 :116(1줄, 실질 무영향). ② 다른 곳의 가드 탐색 — naming.py:66-69는 레코드에 있는 키만 치환하고 잔존 토큰 무경고 통과(make_output_filename에 경고·실패 경로 전무); '{{토큰}} 시끄럽게' 처리는 본문 전용(core lint stray_token — tests/test_lint.py:58, tests/test_schema.py:187)으로 파일명 미적용. 부분 완화 1건 발견: cli.py:270-272가 --source nara + --profile 미지정 시 '[주의] 영문 코드 키... 대부분 빈칸' 경고 — 그러나 본문 빈칸 얘기지 파일명 패턴 언급 없고, --profile 지정 시(apply_all 후에도 'ID' 부재) 경고 자체가 안 뜸 → 반증 불성립. ③ 문서화된 의도 탐색 — core/job.py:203-205 docstring이 '빈 키 파일명은 이상 신호라 시끄러운 쪽을 택한다'고 명시(빈값-존재 키는 loud 마커) — 부재 키의 조용한 리터럴 잔존은 저장소 자체 원칙과도 배치됨을 확인. 심각도는 medium 유지(파일 생성 자체는 성공하고 dedupe로 덮어쓰기는 없으나, 법적 문서 식별자가 무고지 결정 — 확인-또는-경보 위반 가중이 이미 반영된 수준).

</details>

<details><summary>Verifier 비고</summary>

code_evidence 확정: src/hwpxfiller/gui/job_editor.py:106(or-폴백),:138(UI 프리필 '공고서-{{ID}}'),:163-170(isComplete 패턴 미검사); src/hwpxfiller/core/job.py:72(dataclass 기본),:116(from_dict 기본 — 이슈 원문 :117은 1줄 오차, 정정 요망); src/hwpxfiller/cli.py:305(--pattern 기본); src/hwpxfiller/naming.py:66-69(부재 키 무경고 통과). 보조 사실: docs/UI_PROTOTYPE_APPB.html:373,523,575 — 디자인 목업의 유일한 패턴 표기도 '공고서-{{ID}}'로, 'output-{{ID}}'는 어떤 사용자-가시 표면에도 등장하지 않음. 부분 완화(권고에 반영할 것): cli.py:270-272의 나라 무프로파일 경고는 존재하나 파일명 패턴 불언급 + --profile 지정 시 미발동. 권고안(단일 상수 DEFAULT_FILENAME_PATTERN + isComplete 게이트 + 미치환 토큰 경고)은 관찰 영향에 비례하고 타당. 증거물: 스크래치패드 review-round1/verify/RC-20/{repro_rc20.py, repro_log.txt, p7_saved_job.json, nara_out/output-{{ID}}.hwpx, nara_out/output-{{ID}}_1.hwpx}.

</details>

### RC-21 · hwpxfiller 최상위 --help가 서브커맨드 6종을 전혀 표기하지 않음 — pre-argparse 수동 디스패치로 도움말이 실제 CLI 표면을 오표현

- **심각도/유형**: medium/defect · **판정**: 미검증(검증 정원 초과) · **신뢰도**: 0.97 · **기능**: F10, F11 · **유닛**: U8
- **근본 원인**: 하위명령 디스패치가 argparse 이전 수동 문자열 비교(cli.py:283-297)로 수행되고 메인 파서에 subparsers/epilog 안내가 없음 — 하위명령 문서가 --help로 노출되지 않는 모듈 docstring에만 존재.
- **사용자 영향**: lint/drift/fieldize/render 같은 핵심 저작·위생 도구가 소스를 읽은 사람만 아는 그림자 표면이 된다.
- **코드 증거**: cli.py:283-299,10-14
- **병합 증상**:
  - --help 전문에 schema/fieldize/lint/drift/render 0회 등장(실행 캡처), 각 하위명령 --help는 개별 정상
  - RC-26의 fieldize/컴파일 용어 이원과 결합해 GUI에서 '컴파일'을 배운 사용자가 CLI 대응 명령을 이중으로 못 찾음
- **권고**: argparse subparsers 통합 또는 최소 메인 파서 epilog에 하위명령 목록 명기.
- **검증 방법(미실시)**: python -m hwpxfiller.cli --help 출력에서 하위명령명 grep(cli_help_all.txt 재채집).

### RC-22 · run_view↔matrix_view 사본 8종(QThread 배선·완료/실패 핸들러·teardown·open_folder·나라/풀 데이터 겨눔 3종) — _teardown_thread는 이미 의미가 갈라진 사본 부패 개시 상태

- **심각도/유형**: medium/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.95 · **기능**: F2, F3, F4 · **유닛**: U9
- **근본 원인**: 매트릭스 화면 추가 시 복붙 — 배치 실행 뷰 공통의 스레드 수명주기·완료/실패 표시·데이터 겨눔을 소유할 공용 컨트롤러/헬퍼 부재(§8-8). RC-06(취소)·RC-07(스냅샷)·RC-30(모달) 등 후속 수정을 전부 두 번 해야 하는 구조적 회귀 예약.
- **사용자 영향**: 직접 체감 없음 — 취소 도입·실패 표시 개선·되읽기 오프로드 같은 후속 수정의 한쪽 누락 회귀가 구조적으로 예정.
- **코드 증거**: run_view.py:472-537,282-335,322-325 vs matrix_view.py:264-312,205-241,235; run_state.py:146-148,170-172
- **병합 증상**:
  - 스레드 생성·moveToThread·시그널 4연결, 완료 question 모달(둘 다 실패 무언급), _on_failed, _open_folder 축자 사본
  - 사본 부패 실증: _teardown_thread가 run_view는 _sync_generate_enabled() 게이트 재평가, matrix_view는 무조건 setEnabled(True) — 한쪽 수정이 반영 안 되는 단계 진입
  - _pick_nara/_pick_from_pool/_after_data_loaded 사본(경고문까지 동일) — F4 워커화(RC-12) 시 병렬 수정 필요
  - RunViewModel에만 set_acquired seam 부재(매트릭스 VM엔 존재) — _pick_nara가 datasource/records 직접 대입+reset_acks 수동 호출, 누락 시 stale ack로 미입력 게이트 무단 통과하는 잠복 함정
- **권고**: BatchRunController(스레드 시작/teardown/진행/완료·실패 라우팅) 통합, _open_folder는 gui 유틸로, 데이터 겨눔 3종 공용 헬퍼, RunViewModel.set_acquired 추가.

### RC-23 · 게이트 상태의 표시 결정이 VM과 위젯에 쪼개져 모순 신호 — 드리프트 차단 중에도 상단 '사전검증 통과' 녹색 유지, 상태 리프레시 1회당 템플릿 zip 5회 재파싱

- **심각도/유형**: medium/convention_deviation · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F2 · **유닛**: U9
- **근본 원인**: 링1이 이미 계산한 표시 결정(PreflightResult.level/text)을 위젯이 버리고 missing_columns만으로 재조립하고, unmet/drift 판정·차단 문구를 위젯이 재질의·재작성(이중 진실) — 게이트 상태의 단일 산출(GateState) 부재(§2-2). 부수로 field_states/structure_drift가 캐시 seam 없이 매 호출 재읽기.
- **사용자 영향**: 법적 문서 생성 직전 화면에서 '통과'와 '차단'이 동시에 보이는 혼합 신호 — 차단 자체는 유효해 실행 위험은 없으나 신뢰를 깎음. 대형 템플릿·느린 디스크에서 클릭마다 지연 누적.
- **코드 증거**: run_view.py:342-355,398-423, run_state.py:190-200,210-218,237-243,282-297
- **병합 증상**:
  - 드리프트 차단 화면에서 상단 녹색 '사전검증 통과'와 하단 빨간 배지 12개+danger 문구 동시 표시(캡처 실증) — VM 기준 level='warn'인 상태에서도 위젯은 녹색
  - 동일 판정·차단 문구가 run_view.py:398-423과 run_state.py:282-297에 다른 문구로 병존(문구 4곳 산개는 RC-03과 접점)
  - _on_selection_changed 1회당 required_fields 5회 호출(=zip 5회 파싱) 실측 — 레코드 체크 토글마다 반복
- **권고**: vm.gate_state(indices)→(enabled, level, text) 단일 통합 + preflight 라벨은 PreflightResult.level/text 그대로 렌더(드리프트 반영). vm.refresh가 (field_states, unmet, drift)를 단일 스냅샷으로 반환 — 같은 절개로 5회 재파싱도 해소.

### RC-24 · 취득 결과 스냅샷의 소유가 링2 뷰 — 실패 시 records만 리셋되어 datasource/fields/label에 이전 성공값 잔존, 수용성 판정·위젯 관통도 뷰에 산재

- **심각도/유형**: medium/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F4 · **유닛**: U4
- **근본 원인**: VM에 '현재 취득'(last_result) 개념이 없어(AcquireResult는 반환값일 뿐) 리셋 책임이 뷰의 수작업 4속성 관리로 흩어짐 — 출력 계약이 절반은 접근자(datetime_range), 절반은 내부 위젯 직접 읽기(spin_rows/spin_page)이고, '0건 수용 불가' 도메인 정책은 뷰가 res.ok and res.records로 2회 합성.
- **사용자 영향**: 현재 실누출 없음(관례 방어) — 다섯 번째 진입점 추가 시 stale 데이터로 매핑이 진행될 잠복 결합.
- **코드 증거**: nara_view.py:210-223(실패 분기 records만 리셋),49-52,126-131,208-214,221-223, dataset_pool_panel.py:211-225, nara_state.py:94-114
- **병합 증상**:
  - 성공(records=2/fields=53) 후 실패 시 records=0만 리셋 — fields/datasource/label 잔존(런타임 실증). 호출측 4곳 중 3곳의 자발적 관례 검사(Accepted+records)가 방어의 전부, 새 호출측이 dlg.datasource를 읽으면 stale 데이터
  - dataset_pool_panel이 dlg.spin_rows.value()/spin_page.value() 위젯 직접 관통(기간만 접근자) — RC-13의 이중 소스 문제와 동일 표면
  - 수용성 판정 res.ok and res.records가 nara_view 2곳에 이중 기술 + 라벨 문안 조합도 뷰
- **권고**: VM에 last_result(성공 스냅샷 or None) 원자 소유 + AcquireResult.acceptable 프로퍼티 + NaraAcquireDialog.query_options() 접근자 — RC-13 수리와 같은 절개.

### RC-25 · 미선언 덕타이핑 이음새 — 위저드 주입 2속성(secret_store/nara_fetcher)이 호스트에 정의조차 없어 주입 실수가 조용히 실 자격증명 저장소·실 네트워크로 폴백, 문자열 타입명 검사·미선언 인스턴스 속성 동반

- **심각도/유형**: medium/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.87 · **기능**: F1, F4, F2 · **유닛**: U10
- **근본 원인**: 주입·식별 계약이 코드 어디에도 열거되지 않고 getattr 기본값이 계약 문서를 대체 — RC-04 hasattr 배선과 동일 계열의 전방호환 이음새인데, 여기서는 폴백 대상이 하필 실 비밀 저장소·실 urlopen이라 발현이 더 은밀(테스트·감사 코드의 오타가 시끄러운 실패 대신 실 API 호출이 됨 — 본 리뷰의 절대 제약과 충돌하는 실패 모드, 원칙상 상향).
- **사용자 영향**: 사용자 직접 영향 낮음 — 테스트·리뷰 환경에서 주입 실수가 실 ServiceKey 접근·실 API 호출로 조용히 넘어가는 표면, 개명·확장 시 원장 표기 회귀가 테스트에 안 걸림.
- **코드 증거**: gui/wizard.py:337-344, gui/job_editor.py:59-77, gui/run_state.py:323,345, gui/run_view.py:461,501, tests/test_nara_view.py:110-112
- **병합 증상**:
  - wizard.py:342-343 getattr(wiz,'secret_store'/'nara_fetcher',None) — JobEditorWizard 세션 속성 선언부(59-71)에 부재, 테스트가 동적 부착으로만 존재. 대조: run_view/matrix_view/dataset_pool_panel은 생성자 명시 계약
  - run_state.py:323 type(src).__name__=='AcquiredNaraData' 문자열 비교 — 클래스 개명 시 원장 source가 침묵 오기록(원장은 증거물)
  - run_state.py:345 getattr(datasource,'field_labels',None) — 포트 프로토콜 미명세
  - run_view _ledger_ctx가 __init__ 미선언·:461에서만 생성·:501 getattr 방어로만 읽힘 — 속성 수명주기 비선언(RC-07의 표면)
- **권고**: JobEditorWizard.__init__에 secret_store=None/nara_fetcher=None 파라미터 승격(오타는 AttributeError로). DataSource 포트에 source_pointer()/field_labels() 선택 프로토콜 명세, nara 스냅샷은 명시 마커 속성으로. _ledger_ctx는 RC-07 GenerationPlan화로 소거.

### RC-26 · 사용자 용어 체계의 전역 미정렬 — 1개념 다이름(공유 베이스 4이름·fieldize/컴파일), 1단어 다개념('어휘' 3개념, 비움/공란/빈칸 어휘 침범), 라벨↔창 제목 짝 불일치

- **심각도/유형**: medium/convention_deviation · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F8, F7, F1, F2, F5, F9, F12 · **유닛**: U12
- **근본 원인**: ADR 트랙 병렬 저작에서 GUI 문구·CLI 도움말·docs·코드 심볼 4원의 용어 정렬 패스 부재 — 개념 명칭이 진화('매핑 프로파일'→'공유 베이스'→'어휘 워크벤치')하며 표면별로 다른 시점의 이름이 잔존(§8-11 포함, Naming 전역 패스 우선 병합).
- **사용자 영향**: 기능 발견성(공유 베이스의 CLI 재사용, 컴파일의 CLI 대응) 저해와 핵심 안전장치 문구의 혼동 — 치명 오해보다는 누적 마찰.
- **코드 증거**: home.py:174,86,194,217,264, vocab_workbench.py:76,84, wizard.py:455-457,494,270, cli.py:99,305,307-308,121-122, core/mapping_base.py:1-5,41, template_manager.py:155,159, mapping_table.py:37,43-44,56,180,335-341, core/mapping.py:44-62, run_state.py:292, run_view.py:348,374, dataset_pool_state.py:27-36, hwpxdiff/app.py:267-294, gui/mapping_state.py:6
- **병합 증상**:
  - 동일 산출물(MappingProfile, *.mapping.json)이 '어휘 워크벤치'(홈 버튼·창 제목)/'공유 베이스 매핑'(창 본문)/'공유 어휘'(위저드 부제)/'매핑 프로파일 JSON'(CLI --profile) 4이름 — GUI 산출물을 CLI --profile에 그대로 쓸 수 있다는 사실이 어디에도 미고지(재사용 가치 은폐)
  - '어휘' 1단어가 lint 통제 사전 / DataSource.field_labels / 공유 베이스 3개념을 지칭 — lint --vocab에 워크벤치 산출물을 넣는 오용 유도
  - fieldize(CLI 명령명)↔컴파일(전 사용자 문구) 이원 + GUI 모달 제목에 'fieldize' 내부 영어 원문 노출(현재는 RC-04로 잠복)
  - 선언적 비채움이 (비움)/채우지 않음/공란 선언 3문구, 데이터 빈 값이 빈칸/빈 값 2문구 — 두 상태축 어휘가 상호 침범해 빈값 ack 게이트(핵심 안전장치) 이해도를 직접 깎음
  - 변환 join의 라벨 '그대로'가 실제 의미(N→1 구분자 결합+마스크 표시형)와 불일치, 인접 '원문'과 유사어 병치 + mapping.py:44-48 docstring 등 3곳이 코드와 모순(실효 문서)
  - 판본 쌍: GUI/HTML '구판/신판' vs CLI 도움말 '이전/새 판본'; 홈 라벨↔목적지 창 제목 4건(간단 기안↔즉시 기안, 문서 생성↔실행: 등); 데이터셋 '보관/은퇴' 구분 불가+경보 위계 역전(은퇴=warn>보관=muted)+'데이터 풀/데이터셋' 혼용; '겨눔' 내부 은유 사용자 문구 1곳 누출(wizard.py:270); wizard.py 파일명·mapping_state.py:6 '생성 스텝' docstring 잔재
- **권고**: 용어표 1개 확정 후 일괄 치환: 정준 용어(예: '공유 베이스 매핑') 통일, '어휘'는 1개념에만, 사용자 문구 '컴파일' 통일+CLI 도움말에 대응 병기, 비채움/빈 값 2용어 고정, 판본·홈 라벨 정렬, join 라벨·docstring 갱신. 코드 식별자(blank, fieldize 명령명)는 유지 가능.

### RC-27 · 전 한국어 제품에 Qt 표준 문자열이 영어로 잔존 — QTranslator 미설치로 위저드 Back/Next/Cancel·파괴적 확인 &Yes/&No가 영어

- **심각도/유형**: medium/convention_deviation · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F1, F8 · **유닛**: U11
- **근본 원인**: PySide6는 번역을 자동 로드하지 않는데 앱 부트스트랩에 QTranslator/qtbase_ko 설치가 없음(src 전체 grep 0건) — 위저드는 Finish만 개별 교체. 파괴적 확인의 선택지가 외국어 'Yes/No'인 지점은 RC-15와 수리 부위가 겹침.
- **사용자 영향**: 명시성 게이트의 심장부에서 파괴적 확인의 의미 전달이 약해짐 — RC-15(Enter 반사)와 결합 시 실질 위험.
- **코드 증거**: gui/job_editor.py:55(FinishButton만 교체),98-100, gui/wizard.py:700-706, QTranslator/installTranslator grep 0건(gui/app.py 포함)
- **병합 증상**:
  - 위저드 하단 Back/Next/Cancel 영어 렌더(Finish만 '작업 저장'), 덮어쓰기·베이스 덮어쓰기 확인 버튼 '&Yes'/'&No'(offscreen 렌더 실증)
  - ack 다이얼로그는 한국어 명시 버튼이라 품질 낙차가 드러남
- **권고**: app.py 부트스트랩에서 QLibraryInfo.TranslationsPath의 qtbase_ko 설치, 또는 최소 위저드 버튼 setButtonText + 확인류를 RC-15 공용 헬퍼의 한국어 명시 버튼으로 통일.

### RC-30 · 부분 실패 배치의 완료 모달이 실패를 무언급 — succeeded>0만으로 '완료' 서사(run/matrix 동일 사본), 실패 사유는 원시 errno 관통

- **심각도/유형**: medium/defect · **판정**: 미검증(검증 정원 초과) · **신뢰도**: 0.9 · **기능**: F2, F3 · **유닛**: U9
- **근본 원인**: 완료 모달 문구가 성공 집계만 참조(batch.failed 미사용) — 요약 라벨(danger)·로그와 정보 비대칭. 사용자의 마지막 상호작용점(최전면 모달)이 가장 낙관적으로 말하는 역전이며, 실패 상세는 'Permission denied: <경로>' 원시 errno 그대로.
- **사용자 영향**: 모달만 보고 폴더를 열어 발송하면 실패분이 인지 밖으로 샌다 — 법적 문서 배치에서 부분 실패를 전건 성공으로 오인할 수 있는 지점.
- **코드 증거**: run_view.py:513-516(본 세션 재확인: f'{batch.succeeded}건 생성 완료.', failed 미포함), matrix_view.py:288-291, run_view.py:492-494, engine.py:60
- **병합 증상**:
  - 3건 중 1건 실패 배치: 모달 '2건 생성 완료.\n결과 폴더를 여시겠습니까?' — 실패 무언급, 실패는 화면 하단 라벨·로그에만(스크롤 상태 따라 비가시)(S4 실증, 캡처)
  - matrix_view도 동일 문구·조건 사본(RC-22 접점)
- **권고**: 모달에 실패 건수 병기('2건 성공 · 1건 실패 — 실패 내역은 로그'), failed>0이면 경고형 아이콘. 실패 사유는 행동 지향 문구로. RC-22 통합 시 한 곳 수정.
- **검증 방법(미실시)**: S4 재현(권한 거부 1건 섞인 3건 배치) — 모달 문구 채집.

## 낮음 (low) — 8건

### RC-28 · 저작 화면의 링1 연기 잔여 비용 — accept() 5책임 fat handler, _compile_here 인라인 컴파일·IO, 레지스트리 질의·베이스 저장이 뷰 상주, 안내문이 절차 순서의 부수효과

- **심각도/유형**: low/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.85 · **기능**: F1 · **유닛**: U10
- **근본 원인**: EditorSession(링1) 연기가 ARCH_UI_SEPARATION.md에 문서화된 부채 — 저장 정책·컴파일 오케스트레이션·계보 판단이 Qt 오버라이드/핸들러로 자연 유입되어 헤드리스 테스트 사각을 형성. RC-08(dead guard)이 그 사각에서 시그널 없이 썩은 실증이며, RC-15의 _referencing_jobs 오류 정책도 위젯 임의 결정의 산물.
- **사용자 영향**: 직접 영향 없음 — RC-08 같은 판단 오류가 테스트 사각에서 발생·잔존하는 구조적 원인.
- **코드 증거**: gui/job_editor.py:79-118,41-42, gui/wizard.py:185-219,626-718,489-507, gui/mapping_table.py:427-445 vs 355-363, gui/app.py:60-71,173-186
- **병합 증상**:
  - accept() 40줄이 검증·이름검사·프로파일 변환·덮어쓰기 정책·Job 조립·레지스트리 IO·오류표시 겸임
  - _compile_here가 scan→compile→출력 경로 파생→pkg.save 인라인(경로·충돌 정책 뷰 하드코딩 — 덮어쓰기 증상은 RC-02로)
  - _base_registry/_referencing_jobs 링1 성격 질의가 페이지(링2) 상주
  - setSubTitle 2연속 호출 — base_mapping+initial_job 동시 주입 시 베이스 안내가 소리 없이 덮임(현행 배선상 도달 불가 잠복 지뢰)
  - _on_arg_edited가 _sync_row의 행 색·확정 해제 규칙을 부분 복제(포커스 보존 동기는 정당, 브러시 결정식만 공유 필요)
- **권고**: 연기 해소 시점에 EditorSession.build_job()/can_save() 이관, compile_to_sibling은 core/authoring으로. 당장은 가드 술어를 링1 질의로 + 헤드리스 테스트 추가로 부패 방지. _row_brush 추출 5줄.

### RC-29 · CompileState→시각 심각도 매핑이 링2(home)와 링1(template_manager_state)에 상이한 어휘로 이중 존재 + fb 셀렉터 값 어휘가 원 의미와 다른 뜻으로 재전용

- **심각도/유형**: low/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.88 · **기능**: F7, F2 · **유닛**: U10
- **근본 원인**: 홈(C2)과 템플릿 관리(C5)가 병렬 저작되며 같은 도메인 파생(상태→배지)을 각자 다른 링·다른 셀렉터 체계로 착지(§2-2의 F7 측 실체) — 홈은 필드 상태용 fb 값('ack'=확인됨 등)을 색 팔레트로 차용하며 의미를 전복('ack' 스타일이 '해야 할 일' RAW를 칠함), 'fb'가 무엇의 약자인지도 저장소 어디에도 없음.
- **사용자 영향**: 사용자 직접 영향 없음(색은 의도대로) — 유지보수 시 배지 스타일 오적용 위험과 상태 어휘 변경 시 2곳 수동 동기화.
- **코드 증거**: gui/home.py:36-48,71, gui/template_manager_state.py:32-45,151-152, gui/style.py:126-147, gui/run_view.py:372-387, gui/txt_view.py:168
- **병합 증상**:
  - home.py:36-48 _badge_fb(링2, fb 셀렉터: RAW→ack·PARTIAL→blank·COMPILED→fill) vs template_manager_state.py:32-45(_BADGE_LEVELS 링1, level 셀렉터: RAW→muted·PARTIAL→warn·COMPILED→ok) — 같은 상태가 화면마다 다른 심각도 신호 가능
  - run_view/txt_view는 fb를 원 의미대로 사용 — 두 사용처에서 상반된 의미
- **권고**: CompileState→(label, level) 매핑을 링1 단일 모듈로 통합, 홈 배지는 기존 QLabel[level=…] 팔레트로 이관하거나 fb에 의미 중립 별칭.

### RC-31 · hwpxdiff 첫 비교 실패 시 인라인 실패 문구 미설정 — _invalidate_result 조기 반환이 '지울 결과 없음'과 '표시할 메시지 없음'을 동일시

- **심각도/유형**: low/defect · **판정**: 미검증(검증 정원 초과) · **신뢰도**: 0.97 · **기능**: F12 · **유닛**: U5
- **근본 원인**: app.py:457-459의 'result is None and not self._html'이면 message 반영 전에 return하는 가드 — 결과 클리어 불요와 메시지 표시 불요를 과잉 일반화. 성공 이력이 있는 창에서는 정상 표시됨(대조 재현으로 양쪽 런타임 확정).
- **사용자 영향**: 모달이 시끄럽게 알리므로 영향 제한적 — 모달 닫은 뒤 화면 잔존 상태의 조용한 미갱신.
- **코드 증거**: hwpxdiff/app.py:457-459,471-479
- **병합 증상**:
  - 새 창 첫 비교 실패: 모달 후 lbl_summary가 초기 안내 '판본 2개를 선택하고 비교를 누르세요.' 잔존 — 손상 경로가 입력칸에 남은 채 실패 사실 미반영(2개 리뷰어 독립 확정)
- **권고**: lbl_summary.setText(message)는 항상 수행하고 조기 반환은 결과 클리어에만 적용.
- **검증 방법(미실시)**: 새 창에서 첫 비교를 손상 파일로 실행 후 lbl_summary 텍스트 확인(wf_audit W1).

### RC-32 · hwpxdiff 세 표면(GUI/CLI/HTML)의 요약·빈 상태 카피가 각자 하드코딩 — GUI만 '변경 없음' 확정 문장 부재, HTML만 번호변경 KPI 부재

- **심각도/유형**: low/polish · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.85 · **기능**: F12, F13 · **유닛**: U5
- **근본 원인**: 요약 지표 집합·빈 상태 문구의 공유 출처가 없어 표면별 하드코딩 — CLI '(변경 없음)'·HTML '변경 없음 — 두 문서가 동일합니다.'는 명시하는데 GUI는 KPI 0과 빈 리스트만.
- **사용자 영향**: 빈 리스트의 의미 모호 + HTML만 보는 회람 소비자가 재번호 규모를 스크롤 전까지 모름 — 경미.
- **코드 증거**: hwpxdiff/app.py:490,511-517, hwpxdiff/diff.py:727-728,838,798-801
- **병합 증상**:
  - 변경 0건 비교: GUI에 '두 판본 동일' 확정 문장 없음(lbl_summary hide) — 개정 검토 결론이 화면에 안 남음(S3 실증)
  - 필터 3종 전부 해제 시 말없이 빈 리스트 — '필터 때문인가/진짜 동일인가' 구분 불가
  - HTML 상단 카드에 renumber 카운트 부재(GUI KPI·CLI 텍스트 요약엔 존재) — 접이식 요약줄에만
- **권고**: 0건이면 lbl_summary 재노출('변경 없음 — 두 판본이 동일합니다.'), 필터 0행 안내 라벨, HTML 카드 튜플에 ('번호변경','renumber') 추가. RC-18의 완전성 게이트와 함께 두면 '진짜 동일'과 '추출 실패'도 구분됨.

### RC-33 · CLI lint --vocab이 UTF-8 BOM 파일의 첫 필드명을 오염 — Windows 표준 도구로 만든 어휘 파일이 오탐 off_vocabulary + exit 1 게이트 실패

- **심각도/유형**: low/defect · **판정**: 미검증(검증 정원 초과) · **신뢰도**: 0.95 · **기능**: F7, F11 · **유닛**: U8
- **근본 원인**: cli.py:103-105가 encoding='utf-8'로 열어 BOM 미처리 — 첫 줄 '계약명'이 '﻿계약명'으로 읽혀 실제로 어휘에 있는 필드가 위양성 차단됨. PowerShell Set-Content -Encoding utf8·메모장 기본 저장이 즉발 트리거.
- **사용자 영향**: 자동화 게이트에서 위양성 차단 — 조달 담당자가 메모장으로 어휘를 관리하는 현실 시나리오에서 즉발.
- **코드 증거**: cli.py:103-105
- **병합 증상**:
  - 오탐 문구까지 실증: "off_vocabulary: '계약명' (가까운 표준: '﻿계약명')" + exit 1
- **권고**: encoding='utf-8-sig' 교체 + BOM 잔존 검사 테스트 1건.
- **검증 방법(미실시)**: PowerShell로 BOM 어휘 파일 생성 후 lint --vocab 재실행(s4_cli_lint_drift_log.txt 절차).

### RC-34 · 파일 다이얼로그 필터 문자열 하드코딩 10곳 — 지원 확장자 단일 출처(data/factory.py)와 드리프트 대기 상태

- **심각도/유형**: low/code_smell · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.95 · **기능**: F1, F2, F3, F5, F7, F9, F12 · **유닛**: U11
- **근본 원인**: 화면 단위 병렬 저작에서 필터 리터럴을 각자 복사(§8-10) — '엑셀/CSV (*.xlsx *.xlsm *.csv)' 5곳 + 'HWPX (*.hwpx)' 5곳이 data/factory.py:16의 실질 단일 출처와 미연결. 확장자 추가 시 일부 다이얼로그가 새 형식을 조용히 숨기는 형태로 어긋남.
- **사용자 영향**: 현재 없음 — 확장자 정책 변경 시 화면별 비대칭 위험.
- **코드 증거**: run_view.py:256,268, matrix_view.py:193, txt_view.py:137, dataset_pool_panel.py:166, wizard.py:111,378, template_manager.py:185,188, hwpxdiff/app.py:389, data/factory.py:16
- **권고**: EXCEL_FILTER/HWPX_FILTER 상수화(양 제품 각각) 후 참조.

### RC-35 · 언더스코어 사명 클래스(_AppController·_JobCard·_TemplateCard)가 사실상 공용 API — 테스트 4파일·docs 4곳이 크로스모듈 임포트/인용

- **심각도/유형**: low/convention_deviation · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F7 · **유닛**: U11
- **근본 원인**: 초기 스캐폴드의 프라이빗 관례가 컨트롤러의 역할 성장(앱 전체 배선·수명 소유, GUI 진입점) 후에도 유지 — 이름이 약속하는 가시성과 실제 사용(계약 표면)이 어긋남.
- **사용자 영향**: 없음 — 리팩터 시 '프라이빗이니 자유 변경' 오신호로 테스트·문서 동반 파손 위험.
- **코드 증거**: gui/app.py:16,208, gui/home.py:51, gui/template_manager.py:37, tests/test_gui_smoke.py:169,282,325,374, docs/UI_DESIGN_HANDOFF.md:17-20
- **권고**: _AppController→AppController 공개화(별칭 유지 무파괴). 카드류는 팀 관례 선택.

### RC-36 · 매핑 테이블에서 말줄임된 긴 필드명·소스 콤보의 전체 이름 확인 수단(툴팁) 부재 — 유사 접두 필드 오인 확정 위험

- **심각도/유형**: low/polish · **판정**: 수용(검증 생략 — 정적 교차확증) · **신뢰도**: 0.9 · **기능**: F1 · **유닛**: U11
- **근본 원인**: 필드 아이템 툴팁이 spec.context 존재 시 '문맥:'만 노출하고 전체 필드명 상시 툴팁이 없음, 소스 콤보(220px 고정)도 현재 선택 잘림 — 레이아웃 자체는 견고(수평 스크롤 0 실측).
- **사용자 영향**: 명시성 게이트의 '검토' 품질 저하 — 기능 손실 없음.
- **코드 증거**: gui/mapping_table.py:138-142,222-227,299-304
- **병합 증상**:
  - 30자+ 필드 14행이 170px 열에서 거의 동일하게 보임 — 차수·회차 반복 실무 서식에서 행 오인 위험(캡처 실증)
- **권고**: fld.setToolTip에 전체 필드명 상시 포함(문맥 병기), 소스 콤보에 현재 선택 전체 문자열 툴팁.

## 기각 계열 (Correlator 판단 — 사유 보존)

- failure:F4 '[반증·양호 확인] 키 마스킹 전 실패 경로 견고' — 결함이 아니라 반증 시도의 긍정 기록(GUI 라벨·연결시험·CLI traceback·원장 전부 키 원문 무노출, 특수문자 키 포함). 이슈 목록에서 제외하되 Verifier에게 '비밀 취급 축은 재검증 불요'라는 정보로 전달할 가치만 있음.
- ui:F12 'KPI 타일 4장이 창 전폭으로 늘어나 여백 과다' — 기능 무영향 순수 심미로 취향-결함 경계에 있고 confidence 0.7로 증거 기준에 미달(리뷰어 스스로 픽셀성 유보). addStretch 1줄 개선은 RC-32류 F12 폴리시 수선 시 부수 반영 가능하나 독립 이슈로는 기각.
- failure:F12 '파일 2개 동시 투입 시 구판/신판 역할을 투입 순서로 추측' — 두 경로가 읽기전용 입력칸에 항상 표시되어 완전한 침묵이 아니고, 동작이 코드 주석으로 문서화된 관례이며 파일 다이얼로그·개별 드롭 등 정상 경로가 주류. 실피해 시나리오(반전 오독)의 개연성 대비 근거가 얇아 기각 — 원하면 RC-32 문구 개선에 '배정 결과 1줄 고지'로 흡수 가능.
- ui:F1 '작업 덮어쓰기 확인 기본 버튼 미지정 — Enter 반사 확인 가능성(investigation_needed, conf 0.6)' — 기각이 아닌 해소로 제외: failure:F1 P1이 QTest Return 키 주입으로 '&Yes' 클릭을 런타임 확정하여 RC-15에 확정 증상으로 병합됨(별도 조사 항목 불요).
- 리뷰어 간 중복 발견 전량(동일 대상의 2~4중 보고: 드리프트 경계 비대칭 3건, 원장 이중화 3건, 덮어쓰기 2건, 취소 2건, dead guard 3건, F7 도달 불가 3건, 파일명 기본값 4건, _snippet 3건, 그룹 거짓 병합 2건, coalesce 갈림 3건, resultCode 미검증 3건, 동기 네트워크 4건, 부분 실패 모달 2건, 테스트 우회·문서 오기 각 2건 등) — 기각이 아니라 각 RC 이슈로 병합(교차 확증은 해당 이슈 confidence에 반영).
- 기능별 명명 지적(ui:F1 wizard.py 명명 잔재, coupling:F1 mapping_state docstring 스테일, F4/F12 용어 소항목) — Naming 전역 패스 우선 규칙에 따라 RC-26 하위 증상으로 흡수(독립 이슈 기각).

