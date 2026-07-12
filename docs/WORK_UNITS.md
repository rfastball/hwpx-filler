# 작업 유닛 — 워크트리 병렬 착수 브리프

`ROADMAP.md`·`UI_DESIGN_DECISIONS.md`의 **미완 작업**을, 격리 git 워크트리에서 자율 에이전트가
각각 독립 실행할 수 있는 단위로 분할한 문서다. 개발 방식은 로드맵 규정 그대로 —
**기능마다 격리 워크트리 + 전용 브랜치 → 메인이 재검증(pytest + 불변식 + 변이 테스트) 후
fast-forward 병합**.

## 분할 원리 — 워크트리 병렬은 "파일 서로소"가 가른다

워크트리는 저장소의 격리 사본이라 **두 에이전트가 같은 파일을 고치면 병합 충돌**이다. 그래서:
1. 새 능력은 **새 파일**로 격리(기존 파일 편집 최소화).
2. 불가피한 공유 파일은 **단일 소유 트랙으로 직렬화**(§충돌 핫스팟).
3. **seam(코어 파생)을 먼저 착지** → 렌더러(GUI)들이 그 위에 얹혀 병렬화.

각 유닛은 **자체 테스트 동봉 + 독립 병합 가능**해야 한다.

## 웨이브 = 병렬 배치 계획

```
웨이브 1 (지금 즉시 6-병렬, 파일 완전 서로소):
  C1 fields.py │ C2 template_status.py(신규) │ P1 authoring.py+corpus
  N1 secret_store(신규)+nara+cli │ K1 packaging │ J1a txt_*

웨이브 2 (C2 seam + N1 착지 후):
  C4 home │ C5 template_manager(신규)+app │ V1 어휘 탈하드코딩
  [wizard.py 직렬: C3 → N2]

웨이브 3 (ADR J 확정 → 착수 가능; 핫스팟 직렬 有):
  J1 데이터셋풀+마법사 데이터스텝제거 │ J2 매트릭스실행 │ J3 공유베이스매핑+어휘워크벤치

웨이브 2/3 (ADR L 축확정 — L1 독립 착지 가능):
  L1 전건커버+대칭차 드리프트(오라벨 닫음) → L2 원장 export+소스프로파일링(C1 필요·D-8 해동)

수요 파킹 (ADR K 조립 파이프라인 — 지금 비-목표):
  K 다소스 조립(Power-Query식·DuckDB 선호) — 실 2+소스 워크플로 나타날 때 착수
```

## 의존 그래프

```
C1(필드읽기) ─────┐
                  ├──▶ C2(compile_status) ──▶ C3(위저드게이트)
                  │                         └▶ C4(홈배지)
                  └──────────────────────────▶ C5(관리패널)
P1(파서고도화) ····(C2 품질 향상, 병합 무충돌)
N1(SecretStore) ─▶ N2(나라 GUI)
                └▶ V1(어휘 탈하드코딩) ─▶ J3(공유베이스매핑+어휘워크벤치)
K1(패키징) ──(독립, 최후 재검증)
J1a(txt인라인) ──(독립)
[ADR J 확정] ─▶ J1(데이터셋풀) ─▶ J2(매트릭스실행)
                            └──▶ J3
[ADR L 축확정] ─▶ L1(전건커버+대칭차, 독립) ─▶ L2(원장 export+프로파일링)  [C1 필요]  ← run_state 오라벨 구멍 닫음
[ADR K 확정·수요파킹] ── K(조립 파이프라인)  ── 수요 게이트, 지금 미착수
```

---

# 기동 지침 — 프로바이더 배정 (2026-07-12 결정 · 새 세션 자동 착수용)

**두 플릿(Claude·Codex)이 대화 문맥 없이 이 절만 읽고 독립 착수한다.** 배정은 웨이브 1 기준
(J1a 제외 — `gui/txt_*`가 진행 중 미커밋 작업이라 워크트리 분기 시 충돌). 유닛이 파일 서로소라
프로바이더가 섞여도 충돌 0.

## 배정

| 유닛 | 크기 | 프로바이더 | 성격 |
|---|---|---|---|
| **C2** compile_status(seam) | M | **Claude** | 임계경로(웨이브2 전제) |
| **N1** SecretStore + redaction | M | **Claude** | 보안(redaction 누락=키유출) |
| **P1** 파서 고도화 | L | **Codex** | 독립 리프 |
| **K1** 패키징 | M | **Codex** | 독립 리프 |
| **C1** 필드 값 읽기 | S | **Codex** | 독립 리프 |

배정 근거: 임계경로(C2)·보안(N1)은 안정 예산(Claude ×4)에, 정체-내성 독립 리프(P1·K1·C1)는
주간캡이 걸려도 무해하므로 Codex에. **Codex 주간 헤드룸이 빠듯하면 C1(S)만 Claude로 이관**
(나머지 불변).

## Claude 플릿 — 다음 세션에서 이 절 읽고 자동 착수

너는 **저자(C2·N1) + 통합 게이트** 둘 다다.
1. **저자**: C2·N1을 각각 격리 워크트리(`isolation: worktree`)에서 해당 유닛 브리프대로 구현.
   워크트리마다 `uv sync --locked --all-extras --group dev --group build` 선행 → 자체 테스트.
   **C2 먼저**(웨이브 2 seam).
2. **통합 게이트**(저자 무관 — Claude·Codex 브랜치 공통): 브랜치가 준비될 때마다 master 위에
   얹어 `.\test.ps1` 재검증 → **의존순 ff 병합**. C2 최우선, 나머지 웨이브 1(N1·P1·K1·C1)은
   서로소라 순서 자유. **master 병합은 오직 여기서만.**
3. **교차 리뷰**(정합 치명 3브랜치만): P1(Codex 저작)→Claude 적대 리뷰, C2·N1(Claude 저작)→
   독립 Claude 리뷰 에이전트(저자와 다른). 다른 모델계열 교차가 맹점 최대.
4. 웨이브 1 5개 병합 완료 후에야 웨이브 2(C3·C4·C5·V1) 착수 판단 — C3/N2의 `wizard.py` 직렬
   유의(§충돌 핫스팟).

## Codex 플릿 — 별도로 이 절 읽고 착수

너는 **저자(P1·K1·C1)**다. **머지는 하지 않는다**(Claude 메인이 게이트 소유).
1. 각 유닛을 자기 워크트리/브랜치에서 해당 브리프대로 구현. `uv sync …` 선행 → 자체 테스트.
2. 세 유닛은 독립 리프라 순서·병렬 자유. 파일 서로소라 Claude 몫(C2·N1)과 충돌 없음.
3. **캡 근접 시**: 현재 유닛 WIP를 브랜치에 커밋(테스트 미통과여도) 후 정지 — Claude 게이트가
   재검증·병합·필요 시 이어받는다. 유닛이 원자라 손실 없음.
4. 완료 브랜치는 push/공유만. **master 직접 병합 금지.**

## 공통 규약
- **유닛 = 원자 단위.** 한 유닛을 두 프로바이더로 쪼개지 말 것(그 쪼갬이 곧 "중간 끊김").
- **브랜치명**: `wu/<유닛ID>-<슬러그>` (예 `wu/C2-compile-status`, `wu/P1-fieldize-fragments`).
- 환경: §워크트리 환경(uv) 준수. 맨 시스템 `python` 금지.
- 완료 정의: §공통 완료 조건.

---

# 유닛 브리프

각 브리프: **목적 · 범위(산출물) · 파일 · 의존 · 병렬가능 · 인수조건 · 비-목표 · 근거**.

## C1 — 필드 값 읽기 API

- **목적.** 누름틀 값을 읽는 코어 프리미티브. 여러 파킹 항목의 공통 결측물:
  COMPILED vs FILLED 구분(C2), ADR G 값 수준 겹침 감지, run_view "이미 채워짐" 검사.
- **범위.** `FieldDocument.read_field(name) -> str | None` (fieldBegin~fieldEnd 사이 텍스트 조립,
  파편 `hp:t` 이어붙임). `set_field`의 읽기 역연산. 패키지 수준 `read_fields() -> dict[name,value]`도.
- **파일.** `core/fields.py` (+ `tests/test_fields.py`).
- **의존.** 없음. **웨이브 1.**
- **병렬가능.** 전부 (fields.py 단독 소유).
- **인수조건.** 채워진 필드→값 반환, 미채움(placeholder `{{X}}`)→그 리터럴 반환, 파편 걸친 값 정확 복원,
  없는 필드→None. 라운드트립: `set_field(v)` 후 `read_field()==v`.
- **비-목표.** 값 수정(이미 `set_field`). 값 수준 겹침 정책(그건 C2/run_view 소비자 몫).
- **근거.** 누름틀 구조 `fields.py:1-13`·`_fill_one:83-119`. 파킹 기록 `run_state.py:87-88`,
  ADR G 미결 `UI_DESIGN_DECISIONS.md:186-189, 300-301`.

## C2 — `compile_status` 코어 + 계약 테스트 (seam)

- **목적.** `.hwpx`의 컴파일 생애주기 상태를 **저장 아닌 계산**으로 파생. (C) 컴파일 상태 가독성의
  단일 진실원 — C3·C4·C5가 전부 이 위에 얹힌다.
- **범위.** **신규** `core/template_status.py`:
  - `CompileState` enum: `RAW`(필드0+`{{}}`토큰) / `PARTIAL`(필드有+skip·stray 잔존) /
    `COMPILED`(필드有+stray0+값=`{{X}}` 리터럴) / `FILLED`(값≠placeholder).
  - `compile_status(pkg_or_path) -> TemplateStatus{state, field_n, compilable_n, skipped_n, stray_n}`.
  - 파생: `scan_tokens`(authoring) + `extract_schema`(schema)에서 **읽기만**. FILLED 판별은 C1의
    `read_field`(값이 아직 `{{X}}`인지). C1 미착지면 **3-상태(RAW/PARTIAL/COMPLETE)만** 정직 반환.
- **파일.** 신규 `core/template_status.py`, `tests/test_template_status.py`.
  (authoring·schema는 **import만**, 편집 없음 → P1과 병합 무충돌.)
- **의존.** 없음(FILLED만 C1 soft-dep). **웨이브 1.**
- **병렬가능.** 전부. P1이 authoring.py를 고쳐도 다른 파일이라 무충돌.
- **인수조건.** 4상태 각 픽스처(원문/부분/완전/채워짐) 정확 분류. **저장 없음**(호출마다 재계산).
  한글 재편집 시뮬(필드 추가 후 stray 발생)→COMPILED가 PARTIAL로 재판정.
- **비-목표.** GUI 렌더(C4/C5). 파일 도장/캐시(원칙 위반). 상태 전이 부작용.
- **근거.** (C) 결정 `ROADMAP.md` "컴파일 상태 가독성" 절. `scan_tokens:274`·`CompileReport:65`
  ·`extract_schema:221`·`schema.stray_tokens`.

## P1 — fieldize skip률 축소 (파서 고도화)

- **목적.** 현재 단일 `hp:t` 단순 런만 컴파일하고 파편·복합 런은 skip(MVP 경계). 허위 파편을
  **무손실로** 접어 skip률↓ — 알람 최소화(레버 B), 사용성 회수.
- **범위.**
  - **(a) 무손실 정규화 전처리** — 매칭 전 **인접·동일 `charPrIDRef` 텍스트 런 병합**(추측 아닌
    동치 변환). 허위 파편·허위 복합 런을 simple로 접음.
  - **(b, 선택) offset 매핑 수술** — 재구성 문단 문자열 매치 → (런,`hp:t`,문자위치) span 되돌려
    파편 경계에서 잘라 wrap. `text_extract` 재구성 machinery 재사용.
  - **혼합 서식(진짜 상이 `charPrIDRef`) 잔여 skip은 유지** — 값 서식 상속 애매 = 조용한 추측 금지.
  - **격리 병리 코퍼스 + 파편화 택소노미 회귀테스트**: 명명 fixture(중간분리/tab·lineBreak 삽입/
    혼합 charPrIDRef/ctrl 끼임/런경계 상이) 각각 기대결과(compile|skip-이유).
  - dry-run **skip률 계측 로깅**(`CompileReport` compiled/skipped 이미 보유).
- **파일.** `core/authoring.py`, **신규** `tests/corpus/frag/*`, `tests/test_authoring.py`(확장).
- **의존.** 없음. **웨이브 1.**
- **병렬가능.** 전부(authoring.py 단독 소유). `scan_tokens`/`compile_document` **시그니처 불변** 유지 →
  C2 무영향.
- **인수조건.** 정규화가 허위 파편 fixture를 compile로 전환, 혼합 서식 fixture는 여전히 skip(이유 명시).
  라운드트립 `test_authoring.py:60`(compile→fill) 불변. 멱등 불변.
- **비-목표.** 혼합 서식 자동 처리(조용한 추측). `scan_tokens`/`compile_document` 시그니처 변경.
- **근거.** MVP 경계 `authoring.py:19-21`·`_run_shape:113-126`, skip 사유 `:230-232, 268-270`,
  재구성 machinery `text_extract.py:15, 270-302`, "누락은 시끄럽게" `text_extract.py:118`.
  (B-2 🔭 후속) `ROADMAP.md` 트랙 B-2.

## N1 — 나라장터 SecretStore + redaction 코어 (B-3b 보안 절반)

- **목적.** 사용자별 ServiceKey를 OS 자격 증명 저장소에 안전 보관 + 로그/예외 redaction.
  나라 GUI(N2)의 선결 보안 토대.
- **범위.**
  - **신규** `data/secret_store.py`: `SecretStore` 포트 + Windows 구현(**Windows Credential Manager
    Generic Credential**, 대상명 `hwpx-tools/nara-service-key`) + `MemorySecretStore`(테스트 주입).
  - **redaction 유틸**: URL·예외·진단·로그에서 `ServiceKey`→`[REDACTED]`(HTTP 오류가 원본 URL 포함
    가능하므로 예외 경계에서도). 텔레메트리엔 값·일부·해시 모두 금지.
  - `data/nara.py`: 요청 경로에 redaction 적용. `cli.py`: `DATA_GO_KR_KEY` 환경변수 +
    `--service-key-file` 우선, `--service-key VALUE`는 경고 후 제거 경로.
- **파일.** 신규 `data/secret_store.py`, `data/nara.py`, `cli.py`, `tests/test_secret_store.py`.
- **의존.** 없음. **웨이브 1.**
- **병렬가능.** 전부(cli.py는 가산 편집, 타 웨이브1 유닛 미접촉).
- **인수조건.** 저장/읽기/교체/삭제, Windows 사용자 범위, 로그 redaction, URL 인코딩, 인증실패·
  타임아웃·빈응답, **키가 Job/프로파일/QSettings에 직렬화되지 않음** 자동 테스트.
- **비-목표.** GUI(N2). 공용/내장 키(원칙 금지). 같은 사용자 악성 프로세스 방어(경계 밖).
- **근거.** `ROADMAP.md:327-349`(B-3b 완료 조건 전문).

## K1 — exe 패키징 (C-3)

- **목적.** 최종 사용자 배포 산출물(현재 `pip install -e` 개발 설치뿐).
- **범위.** **PyInstaller `--onedir`** + spec 저장소 커밋 + `packaging/` 빌드 스크립트. 런타임 의존성엔
  안 넣고 dev/build 격리. PySide6 축소(미사용 Qt 모듈 제외), `cli.py` 지연·동적 import →
  hidden-import/hook 점검. 한글 COM PDF 경로는 번들 불가(optional 유지).
- **파일.** `packaging/` 만.
- **의존.** 없음(기능 코드 무관). **웨이브 1** 병렬, **최후 재검증**(전체 번들 확인).
- **병렬가능.** 전부(packaging/ 완전 격리).
- **인수조건.** 빌드된 exe가 앱 A·B 기동, `--onedir` 실행, 세 CLI 하위명령 동작.
- **비-목표.** 코드 서명(장기), Nuitka 전환(후속 저울질).
- **근거.** `ROADMAP.md:475-481`.

## J1a — txt 수동 인라인 입력 (H 후속, J 독립 안전분)

- **목적.** 즉시 기안이 값 몇 개에 스프레드시트를 강제하는 마찰 제거. **파일 로드 유지 + 파일 없는
  수동 인라인 입력을 1차 경로로** 추가. ADR J의 데이터풀과 **독립인 가산 입력 경로**(J 확정 전 안전).
- **범위.** VM `set_manual_record(dict)` 훅 + 간단 폼(필드명=템플릿 토큰, 값 타이핑). 표시형 필요 시
  기존 매핑 프로파일 결합(선택).
- **파일.** `gui/txt_state.py`, `gui/txt_view.py`, `core/text_registry.py`.
- **의존.** 없음. **웨이브 1**(단 J 확정 시 "파일 없는 풀 항목"으로 흡수될 수 있음 — 가산이라 재작업 최소).
- **병렬가능.** 전부(txt_* 단독 소유).
- **인수조건.** 파일 없이 값 입력→실시간 렌더 view 갱신→복사. 파일 로드 경로 불변. 미입력 토큰
  `{{}}` 유지(ADR E 준용).
- **비-목표.** 데이터 풀 모델(J1). 매트릭스 실행.
- **근거.** `ROADMAP.md:25-28`(#1), ADR H `UI_DESIGN_DECISIONS.md:194-209`, ADR J 1단계 `:269`,
  미결 H 후속 `:312-314`.

## C3 — 위저드 PARTIAL 확정 게이트

- **목적.** (C)의 지렛대. "성공처럼 보이나 skip 토큰을 fill이 조용히 흘리는" PARTIAL을 **조용히 통과
  불가**로.
- **범위.** `TemplatePage`에서 `compile_status`(C2) 읽어: RAW→이미 차단 유지. **PARTIAL→비차단 경고를
  확정 게이트로 승격** — 둘 중 하나 강제: (a) **[여기서 컴파일]** 인라인 fieldize(scan 미리보기→apply),
  (b) **명시적 ack**("이 N개는 값 안 들어감·의도적", ADR-E 의도적공란 `_acked` 패턴 재사용).
- **파일.** `gui/wizard.py` (필요 시 `gui/mapping_state.py` ack 상태).
- **의존.** **C2**. **웨이브 2.**
- **병렬가능.** C4·C5와는 병렬. **N2와 wizard.py 공유 → 직렬(C3 먼저).**
- **인수조건.** PARTIAL 템플릿으로 매핑 스텝 진행 불가(컴파일 or ack 전). ack 경로는 미충족 필드
  이름 재진술 + 직접 상호작용(반사적 dismiss 봉쇄, ADR E).
- **비-목표.** 홈 배지(C4). 관리 패널(C5).
- **근거.** 현 stray 비차단 경고 `wizard.py:116-121`, RAW 차단 `:101-108`, ADR-E `_acked`
  `run_state.py:69`, ADR E `UI_DESIGN_DECISIONS.md:119-149`.

## C4 — 홈 컴파일 상태 배지

- **목적.** 라이브러리 앰비언트 가독성 — 훑기만 해도 "완전 vs 확인 필요" 구분.
- **범위.** `JobRow.compile_status`(→ C2) 노출 + 카드 배지("✅ 실행 준비 / ⚠ 미확인 토큰 N개 /
  ✏ 원문·컴파일 필요 / ❌ 템플릿 없음"). 기존 `template_missing` pill 어휘 **확장**. `refresh`마다
  **재계산**(한글 편집으로 COMPILED→PARTIAL 드리프트).
- **파일.** `gui/home.py`, `gui/home_state.py`.
- **의존.** **C2**. **웨이브 2.**
- **병렬가능.** C3·C5와 병렬(home 단독). (J2 매트릭스가 후일 home 공유 → J2를 C4 후로.)
- **인수조건.** 상태별 배지 정확, refresh 후 드리프트 반영, `UI_CONTRACT` seam 갱신(`data-vm` +
  `test_ui_contract.py` 통과).
- **비-목표.** 배지 클릭 액션의 게이팅(그건 C3/C5). 저장 플래그.
- **근거.** `home.py:161`, `JobRow.template_missing`(`UI_CONTRACT.md:23`), 계약 seam `UI_CONTRACT.md:1-12`.

## C5 — 템플릿 관리 패널 (C-2 = (C) 워크숍)

- **목적.** 특정 작업 밖에서 템플릿 라이브러리 관리. schema/fieldize/lint/drift의 GUI 표면이자
  상태별 안전연산 게이팅 워크숍.
- **범위.** **신규** `gui/template_manager.py`: 템플릿 목록(파일별 `compile_status` 배지 + 필드수 +
  skip/stray 상세) + **상태별 액션**(RAW→[컴파일], PARTIAL→[마저 컴파일][검토], COMPILED→[미리보기][작업만들기]).
  CLI 2단계(scan 미리보기→apply) 그대로 렌더. lint/drift 결과 표시. `app.py` 라우팅 가산.
- **파일.** 신규 `gui/template_manager.py`, `gui/app.py`(라우팅 가산).
- **의존.** **C2**, C1(FILLED 표시 시). **웨이브 2/3.**
- **병렬가능.** C3·C4와 병렬(신규 파일 + app 가산).
- **인수조건.** 각 상태 액션 게이팅, fieldize dry-run 미리보기 후 apply, lint/drift 리포트 렌더.
- **비-목표.** 새 코어(전부 재사용: `template_status`·`authoring`·`lint`·`schema`).
- **근거.** C-2 `ROADMAP.md:472-474`, CLI `_fieldize_main:49`·`_lint_main:85`·`_drift_main:111`.

## N2 — 나라장터 GUI (소스 선택·키 등록·검색)

- **목적.** B-3b 제품 표면. 위저드/실행이 여전히 Excel/CSV만 고르는 공백을 닫음.
- **범위.** 데이터 소스 선택 `Excel/CSV | 나라장터`. 최초 키 등록, 이후 `등록됨/미등록` + `교체`·`삭제`·
  `연결 시험`. 나라 화면: 시작/종료일시(1개월 제한)·페이지/건수·취득 결과·재시도. GUI는 보관 키를
  **암묵 사용 안 함**(N1 SecretStore 경유).
- **파일.** **신규** `gui/nara_view.py`, `gui/wizard.py`(DataPage 소스 선택).
- **의존.** **N1**. **웨이브 2.** **C3와 wizard.py 공유 → C3 후 직렬.**
- **병렬가능.** C4·C5와 병렬. C3·(J1)과는 wizard.py 직렬.
- **인수조건.** 키 미등록 시 등록 유도, 취득→매핑→생성 e2e, redaction(N1) 관통, 키 비직렬화.
- **비-목표.** 세부 operation DataSource(별도 확장). 키 저장 로직(N1 소유).
- **근거.** `ROADMAP.md:9-13`(정정), `:339-341`(UI 조건), `data/nara.py`.

## V1 — NARA_ALIASES 탈하드코딩 (소스 어휘 소유권 step ①)

- **목적.** 범용 코어가 특정 API 어휘를 품는 두 냄새 제거(README "core=제품 로직 없음" 위반 +
  GUI가 전 소스에 nara 어휘를 기본 깖). **삭제가 아니라 승격** — J3 소스-선언 어휘의 선결.
- **범위.** `core/mapping.py`의 `NARA_ALIASES`(36쌍)를 **소스로 재배치**(예 `NaraStdDataSource.
  field_labels()`). `suggest_mappings`는 이미 `aliases`를 범용 인자로 받음 → GUI `from_suggestions`
  기본 인자가 전 소스에 깔던 nara 어휘 제거, **선택된 소스가 어휘 소유**. **동작 무변**(step ①).
  퍼지 `suggest_mappings`/`similarity`는 **유지**(콜드스타트·드리프트·B-3b 의존 — 생짜 삭제 금지).
- **파일.** `core/mapping.py`, `data/nara.py`, `gui/wizard.py`(`from_suggestions` 기본 인자, 소량).
- **의존.** 없음. **웨이브 2.** (nara.py는 N1 후, mapping.py는 J3 전, wizard.py는 C3 후 직렬.)
- **병렬가능.** C4·C5와 병렬. nara.py→N1, wizard.py→C3, mapping.py→J3와 직렬(V1 먼저).
- **인수조건.** 재배치 후 자동제안 **동작 무변**(나라 응답 22필드 중 12 자동초안 회귀 불변),
  **코어에 API별 어휘 0**(README 규율 회복).
- **비-목표.** 저장 프로파일 수렴(step ② = J3). 퍼지 삭제.
- **근거.** ADR J 하위결정(어휘 소유권) `UI_DESIGN_DECISIONS.md:301-312`, `core/mapping.py` `NARA_ALIASES`.

## J1 — 데이터셋 풀(durable 참조) + 마법사 데이터 스텝 제거

- **목적.** 매핑 저작을 데이터 파일에서 분리(스키마만으로 확정). 데이터 = **durable 풀 항목이되
  스냅샷 아닌 참조**(엑셀 경로·나라 쿼리) + 아카이브/은퇴 상태. "데이터·행 미저장" 불변식 유지
  (포인터만). H 후속(txt 인라인, J1a) 흡수.
- **범위.** **신규** `core/dataset_pool.py`: DataSource 참조 레지스트리(홈 `~/.hwpxfiller/`, archive/retire
  상태, 실행 때 재읽기="싱크"). `data/factory.py`: 풀 항목→DataSource 복원(현 factory `kind` 확장점).
  위저드에서 **데이터 스텝 제거**(스키마만으로 매핑 확정, 샘플=선택적 미리보기로 강등). 대시보드
  데이터 풀 표면.
- **파일.** 신규 `core/dataset_pool.py`, `data/factory.py`, `gui/wizard.py`(데이터 스텝 제거 — 핫스팟),
  대시보드(신규 pool view or `gui/home.py`).
- **의존.** ADR J 확정(닫힘). **웨이브 3.**
- **병렬가능.** 코어는 독립. `gui/wizard.py`→C3·N2·V1 후 직렬. `gui/home.py` 접촉 시 C4·J2와 직렬.
- **인수조건.** 데이터셋 참조 등록/아카이브/은퇴, 실행 재읽기, **스냅샷 미저장**(포인터만 직렬화 검증),
  위저드가 데이터 없이 스키마로 매핑 확정.
- **비-목표.** 매트릭스 다중선택(J2). 조인(ADR K). 데이터 스냅샷.
- **근거.** ADR J §축확정 데이터 수명 `UI_DESIGN_DECISIONS.md:316-320, 332-338`, 단계1 `:278`.

## J2 — 매트릭스 실행 (M 잡 × K 데이터)

- **목적.** 대시보드에서 **잡(=템플릿+매핑) 다중선택 × 데이터 겨눔 → 일괄 생성**. 1:1 실행 표면
  인공물 해소.
- **범위.** `generate_batch`(1 템플릿 × N행)의 **M 잡 × K 데이터** 확장. 교차 충돌은 파일명 패턴에
  템플릿명 토큰 + `OutputNamer` 연번·충돌 접미사 재사용. 대시보드 잡 다중선택 + 데이터 겨눔. 워커.
- **파일.** `core/job.py`(or `batch.py`), `gui/home.py`(다중선택 — 핫스팟 C4/J1), `gui/worker.py`,
  `gui/run_view.py`.
- **의존.** **J1**(데이터 풀). **웨이브 3.**
- **병렬가능.** `gui/home.py`→C4·J1 후 직렬.
- **인수조건.** M×K 일괄 생성, 교차 충돌 파일명 방어, **빈값 스킵 불변**(`engine.py:42`), 단일 잡×단일
  데이터 회귀 불변.
- **비-목표.** 조인(K). 데이터 복수는 후속(초기 K=1 → 확장). 케이스 객체(한 겹이라 불필요).
- **근거.** ADR J 축2 매트릭스 `:256-258`, 단계2 `:279`, 한 겹 착지 `:332-335`.

## J3 — 공유 베이스 매핑 + 인별 오버레이 + 어휘 일괄매핑 워크벤치

- **목적.** 인별 재작성 공수 제거 — **공유 베이스 프로파일(풀) + 잡/사용자 로컬 오버레이**(sparse).
  공유 어휘 1회 선언 → 템플릿 필드에 **이름 교집합 투영**(부분집합 구조 활용).
- **범위.** `core/mapping.py`: 오버레이(**`apply_profile`이 이미 오버레이 적용 기제** — 변경 행만 덮는
  sparse 프로파일). 베이스 편집 = **loud 전파 경고**("이 매핑을 잡 N개 참조", ADR G 겹침 패턴 재사용),
  오버레이 격리. 게이트(ADR D): 오버레이 바꾼 행 **재확정**(공유라도 자동확정 없음). **위저드 시드
  소스를 "한 템플릿 스키마"→"공유 어휘"로 교체**(`apply`/`engine` **무변경** — 코어 정합 확증).
  어휘 워크벤치 GUI. 정준 이름셋 = **공유 베이스 매핑의 필드 집합**(별도 vocab 아티팩트 불필요).
- **파일.** `core/mapping.py`(V1 후 직렬), `gui/mapping_state.py`, **신규** `gui/vocab_workbench.py`,
  `gui/wizard.py`(시드 교체 — 핫스팟).
- **의존.** **V1**(소스-선언 어휘), **J1**(풀 저장). **웨이브 3.** 출력측 정준 네임스페이스는 착수 시 확정
  (J-축2 잔여: 템플릿 합집합 프리필 vs `--vocab` freeze).
- **병렬가능.** `core/mapping.py`→V1 후. `gui/wizard.py`→C3·N2·J1 후 직렬.
- **인수조건.** 어휘→정준필드 1회 확정 후 템플릿 **순수 이름 교집합** 투영, 투영 누락 필드 **loud**
  (ADR D), 베이스 편집 전파 경고, 오버레이 격리+재확정, `apply`/`engine` 무변경 회귀.
- **비-목표.** 자동확정(편의지 게이트 우회 아님). 별도 vocab 아티팩트.
- **근거.** ADR J 매핑모델 `:327-343`, 코어 정합 `:292-299`, 단계3 `:280`.

## L1 — 생성 원장 코어: 매핑 전건 커버 + 대칭차 드리프트 (오라벨 구멍 닫음)

- **목적.** `run_state`가 드리프트 유입을 "의도적 공란"으로 **오라벨**하는 구멍(`field_states` `:179`)을
  닫는다. 의도를 **매핑의 일급 선언**으로 승격 → **대칭차**로 양방향 드리프트를 시끄럽게. ADR L 축3
  (기전·트리거) + 축1 척추의 착지.
- **범위.**
  - `core/mapping.py`: `FieldMapping`에 **명시적 공란 항목**(가산 — `transform="blank"` 등 마커).
    `MappingProfile`이 **커버 집합**(`mapped ∪ blank`)을 노출. 엔진 동작 불변(여전히 빈 누름틀).
  - **신규** `core/fill_ledger.py`: 드리프트 = **(템플릿 누름틀) △ (매핑 커버)**. 구조/값 분리 +
    구조 하위 **템플릿-구조**(하드게이트 사유)/**소스-구조**(포인터 교정 사유)를 상태값으로.
  - `gui/run_state.py`: `_intentional_blanks` 를 추론(차집합)→**선언**(매핑 항목)으로 교체.
    `field_states` 가 `blank` 을 매핑 선언에서, 드리프트를 대칭차에서. **템플릿-구조 드리프트 시
    `validate_generate` 하드게이트**(무시 경로 없음 — `confirm-or-alarm`).
- **파일.** `core/mapping.py`(가산·핫스팟 직렬), 신규 `core/fill_ledger.py`, `gui/run_state.py`,
  `tests/`.
- **의존.** 없음(**독립 착지**). effective-mapping 평가는 J3 착지 시 합성 매핑으로 확장(J3가 L1
  불변식 보존). 소스-구조 처방은 J1 풀과 정합(J1 없이 애드혹 소스에도 동일 적용). **웨이브 2/3.**
- **병렬가능.** `core/mapping.py`→V1/J3 트랙과 파일 직렬(가산이라 저충돌). `run_state.py`·
  `fill_ledger.py` 단독.
- **인수조건.** 미매핑 토큰 유입·**매핑되던 토큰 소멸** 둘 다 loud(후자 = 현 `unmatched` `engine.py:62`
  침묵 구멍 닫힘). 명시적 공란=quiet. 템플릿-구조 드리프트 시 생성 **하드게이트**(무시 경로 부재).
  값 공란은 **ADR E ack 유지**(회귀 불변). 엔진 동작·라운드트립 불변.
- **비-목표.** 원장 export·소스 프로파일링(L2). 스냅샷/이력 저장물. **소스-구조 하드락**(포인터
  교정이지 매핑 수리 아님 — J1 휘발성 참조 정합).
- **근거.** 오라벨 `run_state.py:166-180`·`_intentional_blanks:152-164`, `output_report` 자기검증
  `job.py:217-219`, `unmatched` 침묵 `engine.py:62`, ADR L 축확정 `UI_DESIGN_DECISIONS.md`.

## L2 — 소스 프로파일링 + 생성 원장 export (dry-run 매니페스트·사후 증거)

- **목적.** 생성 전 "무엇이 어떻게 들어갈지"(헤더 실제형·결과값) **dry-run 매니페스트** + 생성 후
  **주입 증거**. 고위험 문서 계보 opt-in. ADR L 축1(열 집합)·축2(프로파일링)·축4(산출)의 착지.
- **범위.**
  - **소스 프로파일링**: 샘플 N건(작게)·**잠정** 타입 라벨(서술적·degrade·주장 아님, 모르면 샘플만).
    D-8 소스측 해동.
  - **원장 export**: 필드당 행 `{누름틀, 소스출처, 소스실제형(샘플), 변환·표시형, 결과값(dry-run),
    상태, 주입 ✓/✗}`. `to_dict`→JSON **사이드카**, **opt-in per batch**. **포인터-온리**(나라 쿼리
    박제 금지) + **N1 redaction 관통**.
  - **사후 검증**: C1 `read_field` 로 생성물 **실값 되읽기**(`GenerateResult.applied` 주장 넘어 증거).
- **파일.** `core/fill_ledger.py`(L1 확장), **신규** `core/source_profile.py`, `data/nara.py`(프로파일
  — N1 후), 원장 표면(GUI/CLI).
- **의존.** **L1**(원장 코어), **C1**(`read_field` — 착지 완료). 소스 프로파일 실화는 실데이터. **웨이브 3.**
- **병렬가능.** `core/fill_ledger.py`→L1 후. `data/nara.py`→N1 후. `source_profile.py` 단독.
- **인수조건.** dry-run 매니페스트 정확, opt-in export, **키 비직렬화**(redaction 관통), 프로파일
  degrade(모르면 샘플만), **값 미리보기 ≠ HWPX 렌더**(ADR C 불변).
- **비-목표.** 인앱 HWPX 렌더(ADR C). 강제 감사로그. 타입 *주장*(제안까지만).
- **근거.** ADR L 결정(제안)+축확정, coverage ledger 대칭 `text_extract.py:61`, D-8 소스측 해동.

---

# ⚠ 충돌 핫스팟 (직렬 강제)

| 파일 | 경합 유닛 | 처방 |
|---|---|---|
| `gui/wizard.py` | C3, N2, V1, J1, J3 | **단일 소유 트랙 직렬**: C3 → N2 → V1 → J1 → J3 |
| `gui/home.py`·`home_state.py` | C4, J1(풀뷰), J2 | C4 → J1 → J2 순 |
| `core/mapping.py` | V1, J3, L1 | **V1 먼저**(어휘 탈하드코딩) → J3(오버레이·시드); L1(공란 항목) 가산·저충돌, 트랙에 직렬 삽입 |
| `data/nara.py` | N1, V1 | N1(redaction) 먼저 → V1(field_labels 승격) |
| `cli.py` | N1 | 가산 편집·저위험, N1 단독 |
| `core/job.py` | J2 | J1 병합 후 단독 |

# ✅ 설계 확정 블록 — ADR J (다대다) · **J0 닫힘(2026-07-12, 사용자)**

`UI_DESIGN_DECISIONS.md` ADR J §축확정 — **J-축 3결정 닫힘**:
1. 잡 경계 = **한 겹** (조합은 일회·저장 안 함; durable = 잡·데이터셋참조·매핑 베이스 3풀).
   "가공방식 저장" 요구는 데이터가 아니라 **매핑 베이스 + [ADR K](UI_DESIGN_DECISIONS.md)
   파이프라인 레시피**가 흡수(데이터는 참조만). 조인/조립은 **ADR K로 분리**(수요 파킹).
2. "공유 소스 어휘" 소유 = 소스-측 닫힘(NARA_ALIASES 탈하드코딩); 잔여 = 출력측 정준
   네임스페이스(템플릿 합집합 vs 별도 vocab, J3 착수 시 확정).
3. 풀 저장 위치 = **홈 레지스트리**(`~/.hwpxfiller/`, 매핑 프로파일 레지스트리 흡수).

→ **J0(사용자 확정) 선결 충족.** **J1(데이터 풀)·J2(매트릭스)·J3(어휘 일괄매핑) 착수 가능**
(단 J3의 출력측 정준 네임스페이스는 착수 시 확정). J1a(txt 인라인)는 여전히 J 독립·웨이브 1.
**매핑 프로파일 레지스트리 미결·H 후속은 이 트랙이 흡수**(닫힘).

# ✅ 설계 확정 블록 — ADR L (생성 원장 + 워크플로 드리프트) · **축3 닫힘·1/4 척추(2026-07-12)**

`UI_DESIGN_DECISIONS.md` ADR L §축 확정 — 오라벨 구멍을 코드로 해부해 닫음. **닫힌 결정:**
1. **의도적 공란 = 매핑의 일급 선언**(추론 폐기) → `FieldMapping` 명시 공란 항목(가산) → 매핑이
   템플릿 누름틀을 **전건 커버**(각 토큰 = {소스 매핑 | 명시적 공란}). `_intentional_blanks` 추론→선언.
2. **드리프트 = (현재 템플릿 누름틀) △ (매핑 커버 집합)** — 스냅샷/이력 저장물 불요(매핑이 계약).
   양방향 loud(매핑 토큰 소멸의 현 침묵 구멍 `GenerateResult.unmatched` 포함).
3. **구조 ≠ 값 드리프트.** 값 공란 = ADR E ack 유지. **구조(토큰 집합 변화)는 ack 대상 아님.**
4. **"무시 없음"은 템플릿-구조 한정.** 템플릿-구조=하드게이트·재확정(C3 대응); 소스-구조(J1 휘발성
   풀 참조)=loud but 포인터 교정. **J1 durable/휘발성 비대칭이 차등을 정당화**(§J1 정합).
5. **원장 export = 포인터-온리 + N1 redaction**; 커버/드리프트는 **effective mapping** 평가(J3 대비).

→ **L0 척추 충족.** **잔여(구현 시 확정, 발명 위험 낮음):** (축1) export 열 집합 정확형·직렬화
(`CoverageLedger.to_dict`→JSON 재사용). (축2) 소스 프로파일링 **깊이 수치**(방향은 서술적·degrade·
주장 아님으로 닫힘; **D-8 소스 측 해동** + C1 `read_field`로 사후 실화). L 착수 시 `FieldMapping`
공란 항목·`run_state`(대칭차 라벨링)·`core/fill_ledger.py`(신규) 예상. 경계: **값 미리보기 ≠ HWPX
렌더(ADR C 불변)**. **의존:** effective-mapping 평가는 J3와, 소스-구조 처방은 J1과 정합 전제.

# ⏸ 수요 파킹 — ADR K (조립 파이프라인)

ADR K는 **목표 형태 확정·구현 파킹**(착수 조건 = **수요**, 철학 아님). 다소스 조립(여러 원천 →
하나의 `DataSource`)이 필요해질 때 **Power-Query식 파이프라인**으로 착지(추론 엔진 아님, 사람이
저작·미리보기). 후보 엔진 DuckDB 선호(구현 시 결정). **`AssemblyEngine` 프로토콜 + 교체점**
(`format_engine` 선례) = 착지 이음새, `data/factory.py` `"pipeline"` kind.

→ **지금 비-목표.** 현 코퍼스 근거는 *한 소스 → 여러 템플릿 부분집합 투영*(J 어휘 케이스)이지
다소스 조인이 아님. 실 2+소스 워크플로(나라 세부 op·ERP API) 나타날 때 착수. 수요 없이 착수 =
"능력 없는 슬롯 발명"(핸드오프 관통 경고) 위험 최대라 **자율 에이전트 대상 아님**.

# 워크트리 환경 (uv — 각 에이전트 선행)

환경은 **uv 관리**(`docs/DEVELOPMENT_ENVIRONMENT.md` 기준). **맨 시스템 `python` 금지** — 반드시
uv `.venv` 경유. `.venv`는 gitignore(체크아웃별)라 **각 워크트리가 자기 `.venv`를 만들어야** 한다:

```powershell
uv sync --locked --all-extras --group dev --group build   # 워크트리 진입 후 1회(uv 캐시로 빠름)
.\test.ps1                                                 # Ruff→Pyright→pytest→coverage(offscreen 자동)
# 직접: uv run pytest  /  QT_QPA_PLATFORM=offscreen (GUI 테스트)
```

# 공통 완료 조건

- **자체 테스트 동봉** — 코어 유닛=불변식·멱등·라운드트립, GUI=상태모델(Qt 비의존) 테스트 +
  `test_ui_contract.py`(seam 변경 시).
- **메인 재검증** — `.\test.ps1`(Ruff→Pyright→pytest→coverage) + 불변식 + 변이 테스트(회귀 스위트
  하중 확인) → **ff 병합**. (기준선: 현재 `master` 에서 pytest 323개 수집.)
- **파서 원칙** — 충실도 완전 · 기능 최소 · 누락은 시끄럽게. 명시성(암묵 자동 금지, dry-run 기본).
