# UI 디자인 결함 전용 병렬 리뷰 오케스트레이터 — 킥오프 설계서

> **용도**: 라운드 1(총체적 코드·프로덕트 리뷰, [REVIEW_ORCHESTRATOR.md](REVIEW_ORCHESTRATOR.md))의
> 후속 라운드. 이번 라운드는 **오직 UI 디자인 결함**(시각 위계·토큰 일관성·상태 표현·
> 어포던스·마이크로카피)만 탐색해 **보고**한다 — 수리(패치)는 스코프 밖.
> 2026-07-12 킥오프 세션의 병렬 탐색 + `style.py`/RC 원장 실측에 근거한 자기완결 문서.
> 본 문서의 파일:라인 인용은 킥오프 시점 기준 — 실행 전 유효성 재확인 필수.
>
> **새 세션 킥오프 방법**: 이 문서를 읽고 §10 실행 절차를 수행하라.
> 발견 원장은 [REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md)(UD-번호)에 박제한다.

---

## 1. 목적·범위

- **대상: 앱 B(hwpxfiller GUI, `src/hwpxfiller/gui/`)만.** 앱 A(hwpxdiff)는 스코프 밖.
- **보고만**: 발견 → 상관 병합 → 적대 검증 → 원장 박제까지. 코드 무접촉.
- **왜 이 라운드인가**: 로직/seam은 헤드리스 테스트(`test_gui_smoke.py`·`test_ui_contract.py`·
  `test_design_tokens.py`)로 가드되지만, **시각·레이아웃층은 무가드**다 —
  [UI_CONTRACT.md](UI_CONTRACT.md)가 "시각·레이아웃 권위 = Qt 위젯('사람 눈')"이라고
  명시한 바로 그 층. 이번 라운드가 그 틈을 사람 눈(에이전트 눈) 전수 관찰로 메운다.
- **라운드 1과의 관계**: 파이프라인 골격·증거 규율은 계승, 렌즈는 엔지니어링
  (결합·실패흐름·명명) → **디자인 5렌즈**로 교체. 발견 번호는 RC-와 분리된
  **UD-01~** 신규 체계(성격이 다른 원장 — §9 중복 방지 규칙으로 교차 연결).
- **링 스코프**: 링2 뷰(`gui/*.py` 중 위젯·`style.py`·`design_tokens.json`)만.
  링1 VM(`*_state.py`)은 스코프 밖 — 단, 위젯이 VM에 없는 것을 지어내는
  seam 위반은 UI_CONTRACT 결함으로 잡는다.

## 2. Ground truth — 결함 판정 기준 3층 + 권위 규칙

디자인 리뷰의 고질병은 "주관적 취향 나열"이다. 이 저장소는 판정 기준선이
문서로 존재하므로, **모든 발견은 아래 근거에 접지해야 한다**:

1. **[UI_DESIGN_DECISIONS.md](UI_DESIGN_DECISIONS.md) (ADR A~L) — 최강 기준.**
   위반 = 결함으로 판정 가능한 조항들:
   - **B**: 필드는 모든 표면에서 채움/의도적 빈칸/미입력 3상태를 각기 다른 배지로.
     **"빈 공간으로 보이면 안 됨."**
   - **D**: 자동매칭 = 제안(suggested)일 뿐. 미매칭 필드는 loud hard-stop.
   - **E**: 누락·빈칸은 **상시 인라인 배지**(차단 모달은 습관화로 무력화 — 강등됨).
     최종 게이트는 미충족 필드를 이름으로 재진술 + 직접 건드리게 하는 강제 상호작용.
   - **F**: 소스 열은 드롭다운 선택만(자유 타이핑 금지).
   - **C**: 인앱 라이브 미리보기 없음(한글이 권위 렌더러) — **단 txt 트랙(H)은 정반대**.
   - **G**: 신규/누적 2모드 radio, 필드 겹침은 loud 확인.
   - **I**: 홈 = 투트랙 허브 대시보드. KPI는 **실재 데이터만**(가짜 지표·차트 발명 금지).
   - **관통 원리**: function → UX → UI, 역방향 금지. "없던 기능 발명 금지."
2. **[UI_DESIGN_HANDOFF.md](UI_DESIGN_HANDOFF.md)**: 라우팅 다이어그램(§0),
   화면별 "고정 스캐폴드(불변)" vs "디자인이 채울 것"(§2~4), 불변식/non-goal(§6).
3. **[UI_CONTRACT.md](UI_CONTRACT.md) 권위 분할** — 구조/seam = 목업이 진실,
   **시각·레이아웃 = Qt 위젯이 진실, 문구 = 코드가 SoT.**
   → **"목업과 다르다"는 자동으로 결함이 아니다.** 목업 대조를 유일 근거로 삼은
   시각·문구 지적은 기각.

**+ 저장소 자기 규율** (문서 없이도 결함 성립 근거):
- `style.py:3` 헤더 선언: "인라인 `setStyleSheet` 산재 금지 — 상수·QSS 동적 프로퍼티로 통일"
- `design_tokens.json` 단일 출처 규율(`_note`: space/radius/type은 "예약(현재 미생성)" — 즉
  간격·radius·타이포는 **가드가 없음이 문서화**된 상태)
- 저장소 핵심 원칙 "확인-또는-경보"(조용한 추측 금지)의 **시각적 형태**: 상태가 조용히
  안 보이면 위반.

## 3. UI 표면 지도 — 화면 패키지 A~F

| 패키지 | 화면 | 파일 (라인) | 핵심 ADR |
|---|---|---|---|
| **A** | 홈 대시보드 | `home.py`(416) | I, B |
| **B** | 작업 저작 위저드 | `wizard.py`(776) + `job_editor.py`(190) + `mapping_table.py`(493) — 최대 표면 | D, F, B |
| **C** | 실행 화면 | `run_view.py`(520) + `record_select.py`(137) + `batch_run.py`(316) | E, G, B |
| **D** | 데이터 계열 | `dataset_pool_panel.py`(236) + `nara_view.py`(402) + `pipeline_builder.py`(292) + `matrix_view.py`(340) + `vocab_workbench.py`(167) | J, K |
| **E** | txt 즉시 기안 | `txt_view.py`(208) | C, H |
| **F** | 템플릿 관리 | `template_manager.py`(264) + `compile_badge.py`(53) | J |

공용(전역 렌즈 대상): `style.py`(169) + `design_tokens.json` + `flow_layout.py` +
`confirm.py` + `app.py`(라우팅 265) + `file_filters.py`.

## 4. 디자인 렌즈 5종 — 체크리스트

### L1 — 시각 위계·레이아웃 (화면별)
- 정렬: 라벨-입력 베이스라인, 카드 그리드, 버튼 행 정렬.
- 간격 리듬: 토큰 미배선이므로 절대값이 아니라 **"동일 화면 내 동일 관계의 간격이
  서로 다름"**(자기 모순)을 잡는다.
- 크기 위계: kpi 22px / heading 15px / body / kpi-label 11px 체계 준수 여부.
- 현실 밀도: 22필드 템플릿(`tests/corpus/scenario/templates/입찰공고서.hwpx`)·
  다수 레코드에서 잘림/스크롤/말줄임(RC-36 툴팁 착지의 회귀 확인 포함).
- 리사이즈: 표준 1280×800 + 좁은 폭 980×700 캡처 쌍으로 붕괴 관찰.
- ADR: I(홈 투트랙 위계), HANDOFF §2~4(고정 스캐폴드 침범 여부).

### L2 — 토큰·스타일 일관성 (전역 1패스)
`style.py` 실측(킥오프 확정 — 리뷰 시 재확인) 출발점:
- BASE_QSS 내부 raw hex 리터럴: `#f3f4f6`(read-only/disabled 배경), `#2b3038`·`#cbd0d6`
  (버튼), `#eef0f3`×3, `#eef1f4`·`#4a505a`(헤더), `#adb3bb`(체크박스), 배지 테두리
  `#e6c98f`/`#bfe0cb`/`#e6a49c`/`#c8c3e6`, hover `#f0f2f5`/`#e6e9ee`/`#f9d9d4` —
  의미상 기존 토큰(MUTED/BORDER 등)으로 환원 가능한데 리터럴인 곳 식별.
- **border-radius 3/4/5/6/7/9/11 혼재** — 값 분포 지도 작성.
- **`pill` vs `fb` 동일 시맨틱 배지 이중 어휘**: pill(radius 9, padding 1px 8px) vs
  fb(radius 11, padding 3px 10~11px) — 같은 상태 배지 개념이 두 시각 언어.
  RC-29(레벨 어휘 단일화, 착지)의 후속 잔재인지 판별.
- 위젯 인라인 예외: `home.py:132` `setStyleSheet("font-weight:600;")`,
  `txt_view.py:178` 인라인 hex span(`#fde2dd`/`#c0392b`) — `style.py:3` 자기 규율 위반.
- 색 의미 계약(`style.py:20-21`: PRIMARY=주 액션·WARN=비차단·DANGER=치명·OK=통과·
  MUTED=부차) vs 실사용 대조.
- `QColor(0,0,0,0)` 텍스트 투명화 관용구 반복(home/dataset_pool/template_manager/vocab).
- ADR: 토큰 단일 출처 규율, `test_design_tokens.py` 가드 범위 **밖**임을 확인하고 지적.

### L3 — 상태 표현·피드백 (화면별)
- **ADR B 직접 검증**: 채움/빈칸/미입력 3상태의 시각 구별이 실행 배지·매핑 미리보기·
  txt 토큰 패널 전 표면에서 성립하는가. "빈 공간으로 보이면 안 됨."
- ADR E: 인라인 게이트의 차단 사유 가시성(왜 실행 불가인지 화면이 말하는가),
  RC-23(게이트 단일 스냅샷, 착지) 후 모순 신호 회귀.
- 빈 상태 화면 전수: 홈 emptyView·풀·템플릿 관리·매트릭스·vocab —
  안내문 + 다음 행동 제안이 있는가, 그냥 공백인가.
- 진행/로딩: worker 실행 중, 나라 취득(RC-12 착지 후 형태). 스테일 결과 잔존
  (RC-14 계열 회귀). 완료 후 다음 행동 명확성(요약·폴더 열기).
- ADR I: KPI 실재 데이터만. ADR G: 겹침 경고 가시성.

### L4 — 상호작용 어포던스·플로우 (화면별)
- primary 위계: 화면당 `[primary="true"]` 분포 — 0개(주 행동 불명) 또는 복수(경쟁) 화면.
- 파괴 버튼: 시각 구별 + `confirm.py`(`confirm_destructive`, RC-15 착지) 일관 경유 —
  Enter 반사 안전성 회귀 확인.
- 모달 규율: ADR E "차단 모달 강등" 이후 신규 모달 침입 여부.
- 탭 순서·첫 포커스(위저드 스텝별), 클릭 가능 어포던스: 같은 배지 모양인데
  QLabel(정적) vs QPushButton(클릭) 혼용 — `fb=missing`은 버튼, 나머지는 라벨.
- 비활성 컨트롤의 사유 전달(툴팁·인접 라벨), ADR D 미매칭 hard-stop의 상호작용 형태,
  위저드 뒤로가기 상태 보존(RC-09 착지 회귀).

### L5 — 마이크로카피·용어 (전역 1패스)
- 라벨↔버튼↔창 제목 짝, 동사 일관성(생성/실행/채우기), 확인 버튼의 결과 재진술
  ("예" vs "덮어쓰기"), 단위 표기(건/개/행), 경어 톤 혼재.
- **RC-26(용어 전역 미정렬, U12로 착지 `b733c76`) 전문을 입력으로 지급.** RC-26이
  열거했던 사례는 착지 후 잔존 여부만 확인 — 잔존 시 "RC-26 회귀" 명기해 UD 등재,
  비잔존 시 기각. 신규 사례만 무조건 UD 부여. RC-27/36 착지분도 회귀 확인만.
- ADR 관통 원리(function→UX→UI), UI_CONTRACT "문구=코드 SoT"(목업 문구 대조 금지).

## 5. 캡처 뱅크 — 선행 1회 공용 구축

**모든 리뷰어가 같은 픽셀을 본다.** 에이전트별 하네스 재작성은 상태 조성 드리프트로
같은 화면을 다른 상태로 보고 판정이 갈라지므로 금지. 뱅크에 없는 상태가 필요하면
시나리오 레지스트리에 항목을 추가하고 동일 하네스를 단건 재실행한다(자유 캡처 금지).

- **위치**: 세션 스크래치패드 `ui-review/capture_bank.py` + `ui-review/bank/*.png` +
  `ui-review/bank/INDEX.md`. **저장소에 쓰지 않는다**(라운드 1 원칙 계승) — 캡처는
  휘발, 재현성은 아래 레지스트리 표가 담보.
- **표준 env** (라운드 1 §4 검증 레시피 계승):

| env | 값 | 이유 |
|---|---|---|
| `QT_QPA_PLATFORM` | `offscreen` | 헤드리스 렌더 |
| `QT_QPA_FONTDIR` | `C:\Windows\Fonts` | 없으면 한글 전부 □(tofu) |
| `HWPXFILLER_HOME` | 임시 폴더 | 사용자 `~/.hwpxfiller` 절대 비접촉 |

- **실행**: `./.venv/Scripts/python.exe` (저장소 루트 cwd).
- **상태 주입**: `tests/test_gui_smoke.py`(1684줄) 패턴 이식 — 홈 빈/채움
  (`test_home_empty_state_and_job_cards` 부근), 실행 인라인 게이트
  (`test_run_view_inline_blank_gate_and_marker_injection` 부근), 템플릿 관리 배지
  (`test_template_manager_panel_renders_badges_and_gated_actions` 부근).
  corpus: `입찰공고서.hwpx`(22필드)·`조달_한글.csv`·`구매요청서.hwpx`.
  RAW/PARTIAL·실행 템플릿은 `test_gui_smoke.py`의 `_hwpx_pkg`/`_partial_template_file`/
  `_write_run_template` 헬퍼를 이식해 조성(별도 fixture 스크립트 없음 — 구축 시 실측).
  나라장터는 주입 fetcher + `tests/fixtures/nara_std_response.json` —
  **실 API·실 ServiceKey 절대 금지.**
  모달은 스모크와 같이 monkeypatch로 열림을 가로채 다이얼로그 위젯을 직접 `grab()`.
- **하네스 스켈레톤**:

```python
# ./.venv/Scripts/python.exe 로 실행. 저장소 루트 cwd.
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.setdefault("HWPXFILLER_HOME", tempfile.mkdtemp(prefix="ui-review-home-"))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

def snap(widget, scenario_id, w=1280, h=800):
    widget.resize(w, h); widget.show(); app.processEvents()
    widget.grab().save(f"bank/{scenario_id}.png")
# 시나리오별 상태 조성 → snap(위젯, "A2") / 좁은 폭은 snap(..., w=980, h=700)
```

- **시나리오 레지스트리 v1 (34건)** — INDEX.md의 원본. 구축 실패 건은 봉쇄하지 말고
  `investigation_needed`로 마킹 후 진행:

| ID | 화면 | 상태 |
|---|---|---|
| A1 | 홈 | 빈 상태(작업 0건, emptyView) |
| A2 | 홈 | 채움(HWPX 작업 카드 다수 + txt 기안 + 손상 작업 배지) |
| A3 | 홈 | 다량(카드 10+개, 스크롤·KPI 갱신) |
| B1 | 위저드 | 스텝1 — COMPILED 템플릿 선택 정상 |
| B2 | 위저드 | 스텝1 — RAW 템플릿 게이트 차단 |
| B3 | 위저드 | 스텝1 — PARTIAL 게이트(ack 재진술 요구) |
| B4 | 위저드 | 스텝2 — 데이터 로드 후(조달_한글.csv) |
| B5 | 위저드 | 스텝3 — 매핑 초기(자동매칭 제안 + 미매칭 잔존) |
| B6 | 위저드 | 스텝3 — 전건 확정(완료 가능 상태) |
| B7 | 위저드 | 스텝3 — 22필드·긴 필드명 밀도 |
| C1 | 실행 | 초기(작업 로드, 데이터 겨눔 전) |
| C2 | 실행 | preflight 후 — fill/blank/missing/ack 배지 4종 공존 |
| C3 | 실행 | 인라인 빈칸 게이트 차단(missing 미확인) |
| C4 | 실행 | 드리프트 차단 상태 |
| C5 | 실행 | 진행 중(progress) |
| C6 | 실행 | 부분 실패 요약 모달 |
| D1 | 데이터 풀 | 빈 상태 |
| D2 | 데이터 풀 | 채움(활성/보관 혼재) |
| D3 | 나라장터 | 초기 다이얼로그 |
| D4 | 나라장터 | 취득 성공(주입 fetcher) |
| D5 | 나라장터 | 취득 실패(resultCode≠00) |
| D6 | 파이프라인 | 빌더(merge/append 조립 상태) |
| D7 | 매트릭스 | 작업 다수 × 데이터 선택 |
| D8 | 어휘 | 워크벤치(베이스 + 매핑 행) |
| E1 | txt | 초기(양식 선택) |
| E2 | txt | 채움 렌더(전 토큰 치환) |
| E3 | txt | 미치환 토큰 잔존(빨간 강조) |
| F1 | 템플릿 관리 | 목록 + 배지 혼재(compiled/raw/partial) |
| F2 | 템플릿 관리 | 게이트 잠긴 액션(비활성 상태) |
| F3 | 템플릿 관리 | lint/드리프트 결과 표시 |
| W1~W4 | 좁은 폭 | A2·B5·C2·D7을 980×700로 재캡처 |

- **구축 후 검증**: PNG 전건 존재 + 비검정(크기 임계) + INDEX 대조,
  홈 1장을 직접 열어 한글 렌더(tofu 아님) 확인 후에만 리뷰어 투입.

## 6. 화면×렌즈 매트릭스와 편성

| 화면 | L1 위계 | L3 상태 | L4 어포던스 | L2 토큰 | L5 카피 |
|---|---|---|---|---|---|
| A 홈 | ✅ | ✅ | ✅ | 전역 1패스 | 전역 1패스 |
| B 저작 | ✅ | ✅ | ✅ | 〃 | 〃 |
| C 실행 | ✅ | ✅ | ✅ | 〃 | 〃 |
| D 데이터 계열 | ✅ | ✅ | ✅ | 〃 | 〃 |
| E txt | ✅ | ✅ | ✅ | 〃 | 〃 |
| F 템플릿 관리 | ✅ | ✅ | ✅ | 〃 | 〃 |

- **리뷰어 20**: 화면 6 × 렌즈 3(L1/L3/L4) = 18 + 전역 2(L2, L5).
  L2·L5는 교차 비교가 본질이라 전역 1패스(라운드 1 Naming 패스와 같은 이유).
- 총 규모: 리뷰어 20 + Correlator 1 + Verifier 12~18(병렬) + Editor 1 ≈ **34~40**.
- 오케스트레이션 흐름(배리어는 Correlation 앞 한 곳만 — 라운드 1 골격):

```text
캡처 뱅크 구축 (직렬 1)
  → Parallel Review 20 ┬ 화면×렌즈 18 (A~F × L1/L3/L4)
                       └ 전역 2 (L2 토큰, L5 카피)
  → [배리어] Correlation (근본 원인 병합 + RC 대조)
  → Verification (이슈별 병렬 — 반증 4축 + 캡처 재확인)
  → Review Editing (심각도·신뢰도 확정 → 원장 박제)
```

## 7. UD 발견 스키마·증거 규칙·심각도

각 발견은 아래 JSON으로 기록한다(라운드 1 §7 변형):

```json
{
  "screen": "A~F | global", "lens": "L1~L5",
  "type": "defect | convention_deviation | code_smell | polish | investigation_needed",
  "severity": "critical | high | medium | low",
  "title": "...", "observed": "...", "expected": "...", "user_impact": "...",
  "design_basis": ["ADR-B", "style.py:3 자기규율", "내부 다수 패턴", "정량(대비 2.1:1)"],
  "visual_evidence": {"scenario_id": "C2", "screenshot": "bank/C2.png", "target_control": "..."},
  "code_evidence": [{"file": "...", "lines": "...", "symbol": "..."}],
  "related_rc": ["RC-29"],
  "root_cause": "...", "recommendation": "...", "confidence": 0.0
}
```

**성립 요건**: `design_basis`에 4근거 중 최소 1개 —
① ADR/HANDOFF/CONTRACT 조항 ② 저장소 자기 규율 ③ **내부 다수 패턴 위반**(같은
시맨틱을 앱 스스로 두 방식으로 렌더 — 자기 모순은 문서 없이도 결함) ④ 정량 임계
(명도 대비·터치 타깃·말줄임로 식별 불가). **전무하면 취향으로 기각**
(최대 polish, confidence ≤ 0.4).

**증거 규칙**(라운드 1 계승 + 강화): 실행 못 한 UI를 본 것처럼 쓰지 않는다 /
**캡처 없는 시각 주장은 무조건 `investigation_needed`**(defect·convention_deviation의
시각 주장에 screenshot 필수 — 스키마로 강제) / 취향≠결함 / 동일 근본 원인 병합 /
runtime_evidence는 선택(디자인 라운드라 재현 스크립트 필수 아님).

**심각도 (UX 영향 기반)**:

| 심각도 | 기준 | 예시 |
|---|---|---|
| critical | 디자인이 법적 문서의 데이터 오류·손실로 오도 | 빈칸이 채움처럼 보임(ADR-B 정면 위반), 파괴 액션이 안전 액션과 시각 동일 |
| high | 상태 신호 오전달·부재 — 확인-또는-경보의 시각적 위반 | 게이트 차단 사유 비가시, 에러 조용히 지나감, 스테일 상태 잔존 표시 |
| medium | 태스크 마찰 | 위계 혼란 오클릭 유도, 배지 어휘 이중화, 현실 데이터 레이아웃 파손 |
| low | 비차단 드리프트 | radius·간격 리듬, 톤 불일치 |

**상향 규칙**: "조용히 안 보이는 상태"(확인-또는-경보 위반의 시각형)와
ADR-B/E 명시 조항 위반은 한 단계 상향.

## 8. 적대 반증 4축 (Verifier 프로토콜)

Verifier는 기각을 목표로 공격한다. defect 전건 + high 이상 전건 투입,
나머지는 수용(정적 교차확증 — L2 grep성 발견에 주로 적용)/미검증 표기.

1. **문서 의도 반증**: ADR에 그렇게 하기로 결정한 것 아닌가.
   (예: 인앱 미리보기 부재 지적 → ADR-C 의도 — 기각)
2. **권위 반증**: UI_CONTRACT상 "목업과 다름"을 근거로 삼지 않았는가 —
   목업 참조를 제거해도 주장이 서는가. 문구 지적이 목업 문구 대조면 기각.
3. **태스크 마찰 입증**: 구체 사용자 태스크 워크스루에서 실제 마찰(오인·재작업·
   학습 비용)을 지목하는가 — 못 하면 polish 강등.
4. **캡처 재확인**: 시나리오를 독립 재실행해 동일 관찰. offscreen 아티팩트
   (가는 글꼴·네이티브 테마 부재·안티앨리어싱) 의심이면 `investigation_needed` 강등.

판정 어휘는 라운드 1 유지: **확정**(재확인+반증 통과) / **수용**(정적 교차확증) /
**미검증**.

## 9. RC-01~36 중복 방지 규칙

리뷰어 전원에게 RC 추적 표(제목만), Correlator에게
[REVIEW_ROUND1_FINDINGS.md](REVIEW_ROUND1_FINDINGS.md) 원장 전문 지급.

1. **동일 근본원인 + RC 착지됨**(킥오프 시점 36/36 전량 착지 — RC-26도 `b733c76`로 착지)
   → 현 워킹트리 캡처로 잔존 확인. 잔존 시 신규 UD로 등재하되 "RC-xx 회귀/후속" 명기,
   비잔존 시 기각(부록 기록).
2. **부분 겹침**(같은 부위, 새 디자인 증상) → 신규 UD + `related_rc` 연결.

라운드 1 패치 직후라 회귀성 발견이 다수일 수 있다 — 규칙 1이 흡수한다(정상).

## 10. 실행 절차

1. **준비**: `./.venv/Scripts/python.exe -c "import PySide6"` 확인.
   본 문서의 파일:라인 앵커 grep 재확인(패치로 이동 가능). RC-26 상태 재확인.
   증거 위치: 스크래치패드 `ui-review/`(bank/·findings/) — 저장소에 쓰지 않는다.
2. **캡처 뱅크**: §5 레지스트리 34건 구축 + 검증(직렬 1에이전트).
3. **병렬 리뷰 20**: 입력 = 담당 화면 소스 + 뱅크 PNG + 담당 렌즈 체크리스트(§4) +
   ground truth 3층(§2) + RC 제목표. 출력 = §7 스키마 JSON 배열
   (`ui-review/findings/<screen>-<lens>.json`).
4. **배리어 — Correlation 1**: 근본 원인 병합(특히 L2 토큰 드리프트의 화면별 증상 →
   단일 이슈), §9 RC 대조, 심각도 잠정 정렬.
5. **적대 검증**: §8 반증 4축, defect + high 이상 전건 병렬.
6. **편집·원장 박제**: [REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md) —
   추적 표 `| UD-ID | 심각도 | 렌즈 | 화면 | 유형 | 판정 | 상태 | 제목 |` +
   이슈 상세(관찰·기대·시나리오 ID·파일:라인·디자인 근거·반증 기록·권고) +
   RC 대조 부록. 캡처는 휘발이므로 시나리오 ID가 재현 경로다.
7. **마감 검증**: 신규 파일이 docs 2개뿐인지 `git status` 확인, 추적 표↔상세 건수
   교차 대조, 스크린샷 없는 defect 0건, UD↔RC 연결 누락 0건.

### 환경 함정 (라운드 1 §9 계승)

- uv는 `%USERPROFILE%\.local\bin`(PATH 누락 주의) — 직접 실행은 `./.venv/Scripts/python.exe`.
- `QT_QPA_FONTDIR` 없으면 한글 전부 tofu — 캡처 전건 무효화되므로 필수.
- 임시 `HWPXFILLER_HOME` 필수 — 사용자 `~/.hwpxfiller` 절대 비접촉.
- PowerShell 5.1에서 native exe에 `2>&1` 금지(NativeCommandError 위장 실패).
- 콘솔 한글: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`.
- offscreen은 글꼴이 가늘고 네이티브 테마가 빠짐 — 픽셀성 미세 주장의
  `investigation_needed` 강등은 정상 동작이며 원장에 그대로 기록한다.

## 11. 실행 기록

- **UI 디자인 라운드 완료 (2026-07-13)**: 캡처 뱅크 34/34 전건 구축(한글 렌더 확인,
  적대검증 중 스테일 상태 재현용 D6b 1건 추가). 리뷰어 20(화면 6×렌즈 3 + 전역 2) →
  원발견 97건 → Correlator 병합 46건(기각 1) → 적대검증 20건 투입(확정 19 / 반증 기각 1) →
  Editor 확정 **최종 45건**(높음 10 / 중간 20 / 낮음 15, critical 0 — 확정 19·수용 18·
  미검증 8). 전량 박제: **[REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md)** (UD-01~45
  추적 표 포함 — 조치는 별도 계획에서 그 표를 원장으로 갱신).
  실측 보정: `tests/fixtures/make_hwpx.py`는 실재하지 않아 §5를 스모크 헬퍼 이식
  방식으로 수정, RC-26이 실행 직전 착지(b733c76)되어 §4 L5·§9를 전량 착지 기준으로 갱신.
- **조치 계획 수립 (2026-07-13)**: UD 45건을 직교 고립단위 **V1~V15 · 6스테이지 직렬
  머지**로 편성 — [REVIEW_UI_FINDINGS.md](REVIEW_UI_FINDINGS.md) "조치 계획" 절이 원장.
  V1(확증·하네스 수리) 최우선, style.py는 V2→V8→V11→V14 스테이지당 1소유자 직렬 사슬.
