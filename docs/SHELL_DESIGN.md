# 셸 설계 — 단일창 네비 레일 셸 (ST-01 착지 라운드)

작성 2026-07-13. 표준 관행 리뷰 라운드의 후속 항목 **ST-01**(`REVIEW_LEDGER.md` Part 3,
중간)을 착지시키는 구조 리팩터의 설계서다. 이전 라운드가 창 수명(U3)·재사용 싱글턴(U5)을
먼저 마감해 이 리팩터의 표면을 줄여 두었다.

> **착지 완료(2026-07-13)** — S1~S7 전량, 최종 게이트 834 passed(+13 신규)·ruff·pyright.
> 착지 기록은 §5 표. 이후 이 문서는 셸 계약(§1~§4·§6·§7)의 원장으로 산다.

> **문제(ST-01):** `AppController` 의 7개 `_open_*` 가 능력마다 별도 최상위 창을 생성해
> `win.show()` — 인-윈도 전환·복귀·현재 위치 표지가 없다(Nielsen H3/H4 · Fluent
> NavigationView). `app.py` 모듈 docstring 이 임베드를 "후속 리팩터"로 자인해 온 상태.

---

## 1. 결정 (ADR)

| # | 결정 | 근거 | 기각한 대안 |
|---|---|---|---|
| D1 | **단일창 셸**: 홈을 페이지로 강등, 좌 네비 레일(216px) + `QStackedWidget` 임베드 | 원장 제안 (a)안 · `UI_PROTOTYPE_APPB.html` 목업(`.shell{grid-template-columns:216px 1fr}`) · Fluent NavigationView 정합 | (b) 다중창 유지 + 공통 네비 크롬 — 창 모델 자체가 존치돼 부분 해소에 그침 |
| D2 | **셸은 신규 클래스** `gui/shell.py` `ShellWindow(QMainWindow)` — `JobListHome` 개조 아님 | home.py 는 이미 532줄 대시보드 렌더러. 별도 셸이면 홈은 시그널 계약을 든 채 페이지로 강등만 되고, 배선 소유자는 계속 `AppController`(핸드오프 §2 고정 이음새 존중) | 홈을 셸로 확장 — 대시보드 렌더링과 창 크롬이 한 클래스에 엉킴 |
| D3 | **위저드만 창으로 남긴다**: `JobEditorWizard`(QWizard)는 임베드하지 않고 **ApplicationModal** 부여 | QWizard 는 스택 임베드가 어색한 컴포넌트(자체 버튼 크롬·페이지 흐름). 모달성이 ST-10 의 `editor:{name}` 싱글턴(last-save-wins 방어)을 상위 호환 대체 | 위저드 해체·페이지화 — 재작성 비용·회귀 위험 대비 이득 없음 |
| D4 | **모달성 부여 방식**: parent 없이 `wiz.setWindowModality(Qt.ApplicationModal)` + 기존 `wiz.show()`. **`exec()` 금지** | offscreen 테스트에서 `exec()` 는 hang. 결과 처리는 기존 `job_saved` 시그널이라 반환값 불요. parent 를 주면 창 배치·수명이 바뀌므로 무부여(`_track` GC 방지 유지) | `wiz.exec()` — offscreen hang · parent 부여 — 최소 변경 위반 |
| D5 | **네비게이션 시그널 계약 불변**: 홈의 시그널과 `app.py` 배선부는 한 줄도 바꾸지 않는다. `_open_*` **본문만** 창 생성 → 셸 활성화로 교체 | `UI_CONTRACT.md` 시그널 이음새 "app.py가 배선, 바꾸지 말 것" | 셸이 직접 배선 — 고정 이음새 파괴 |
| D6 | **페이지 지연 생성 + 은닉 보존 + 재진입 `refresh()`**: 첫 방문 시 factory 생성, 전환 시 파괴하지 않음(상태 보존), 재방문 시 `hasattr` 로 `refresh()` 호출 | TemplateManagerPanel 은 생성자에서 라이브러리 전수 파싱(즉시 생성은 기동 지연). 재진입 refresh 는 현행 "닫힌 창은 stale → 신선 재생성" 의미를 계승해 은닉 중 외부 변경 스테일을 막음 | 즉시 전체 생성 · 전환 시 파괴 |
| D7 | **지오메트리는 셸 단일 키 `"shell"`**(기본 1140×720). 기존 뷰별 키는 읽기·쓰기 중단만 — INI 잔존 무해, **마이그레이션 코드 발명 금지**. `"editor"` 키만 존치(위저드는 여전히 창) | 창이 하나뿐이므로 ST-11 의 지속 대상도 하나. 레일 216px 가 붙어 기존 home 900×560 재사용 부적합 → 신규 키로 깨끗한 단절 | home 키 승계 · 키 마이그레이션 코드 |
| D8 | **dirty 이탈 게이트 단일 경로**: 레일 전환·`activate()`·셸 `closeEvent` 모두 현재 페이지의 `can_leave()` 경유. run/matrix 의 기존 closeEvent ST-21 로직을 `can_leave()` 로 추출 | 창 닫기에만 걸려 있던 확인 게이트가 "페이지 이탈"로 일반화돼야 함. 단일 경로가 confirm-or-alarm 원칙의 누락 지점을 없앰 | 전환 경로별 개별 확인 |
| D9 | **단축키 컨텍스트**: `wire_refresh_shortcut`/`wire_submit_shortcut` 의 QShortcut 에 `WidgetWithChildrenShortcut` 부여 | 한 창에 F5×4(home/template/pool/vocab)·Ctrl+Return×2(run/matrix)가 공존하면 기본 WindowShortcut 은 **모호 활성으로 전부 무동작**하는 조용한 회귀. 포커스 소유 페이지에서만 발화해야 함 | 창별 유지 — 임베드 후 즉시 회귀 |
| D10 | **레일 스타일은 기존 토큰만**: `style.py` `#navRail` 셀렉터 소량 추가, 새 팔레트 발명 금지 | ST-14(고대비) 보류 존중 · 토큰 단일출처 관행 | 다크 레일 등 신규 팔레트 |

## 2. 창 → 페이지 매핑

| 현재 (최상위 창) | 이후 | 레일 키 | 비고 |
|---|---|---|---|
| `home.JobListHome` (QMainWindow) | **페이지** (QWidget) | `home` "대시보드" | 시그널 12개·refresh·카드 렌더 불변 |
| `txt_view.TxtDraftView` | 페이지 | `txt` "즉시 기안" | `select_template` API 불변 |
| `matrix_view.MatrixRunView` | 페이지 | `matrix` "같은 데이터로 여러 작업 실행" | `can_leave()` = 실행 중 ST-21 확인 |
| `template_manager.TemplateManagerPanel` | 페이지 | `template` "템플릿 관리" | HWPX·TXT 통합 관리; TXT는 즉시 기안으로 연결 |
| `dataset_pool_panel.DatasetPoolPanel` | 페이지 | `pool` "데이터 풀" | |
| `vocab_workbench.VocabWorkbenchPanel` | 페이지 | `vocab` "어휘 워크벤치" | |
| `run_view.RunView` | **파라미터 페이지** (동적 레일 항목 "실행: {작업명}") | `run` | 단일 슬롯: 같은 job 재사용 / 다른 job 은 `can_leave()` → `teardown()` → 교체 |
| `job_editor.JobEditorWizard` (QWizard) | **창 유지 + ApplicationModal** | (레일 없음) | 뷰 코드 무접촉, 모달성은 AppController 가 부여 |

**뷰 공통 개조(QMainWindow→QWidget):** ① 상속 교체 ② `setCentralWidget` 보일러플레이트
→ `QVBoxLayout(self)` ③ 생성자 `restore_geometry` 삭제 ④ `setWindowTitle` **유지**(레일
라벨 소스 + 기존 테스트 호환) ⑤ closeEvent 는 지오메트리 저장뿐이면 삭제, run/matrix 는
`can_leave()` 추출 후 위임.

## 3. 셸 계약 — `gui/shell.py`

```python
class ShellWindow(QMainWindow):
    """단일창 셸 — 좌 네비 레일(QListWidget 216px) + QStackedWidget 페이지 호스트(ST-01)."""
    def register_static(self, key, title, desc="") -> None   # 레일 자리 예약(위젯은 지연)
    def activate(self, key, factory=None) -> QWidget   # 없으면 factory() 생성·등록, 있으면 재사용(+refresh)
    def open_run(self, job_name, factory) -> QWidget   # "run" 파라미터 슬롯 교체 정책(§2)
    def go_home(self) -> None
    def current_key(self) -> str                       # 테스트 seam
    def closeEvent(self, event): ...                   # 전 생존 페이지 can_leave() → save_geometry("shell")
```

- 레일 = `QListWidget`(`objectName="navRail"`, 커스텀 위젯 아님 — 제목+한줄 설명은
  아이템 텍스트+툴팁으로 수렴, 커스텀 아이템은 후속 폴리시).
- 현재 위치 표지 = 레일 선택 하이라이트. `currentRowChanged` → `can_leave` 게이트,
  거부 시 `blockSignals` 로 선택 복원(시그널 재귀 방지 규율).
- **페이지 프로토콜(덕타이핑, ABC 발명 금지):** `can_leave() -> bool`(없으면 True) ·
  `refresh()`(재진입 시 hasattr 호출) · `windowTitle()`(레일 라벨 소스).
- `AppController` 재배선: 관리형 4종 `shell.activate(key, factory=...)`(factory 안에 기존
  생성·시그널 배선·`_track` 유지), `_open_run` 은 진입 가드 불변 → `shell.open_run`,
  `main()` 은 `controller.shell.show()`. `_track`/`_children` 은 기존 테스트 10여 곳이
  isinstance 로 소비하므로 **호환 seam 으로 존치**. `_raise_singleton`/`_singletons` 은
  스택이 유일성을 구조로 보장하므로 S6 에서 제거.

## 4. 지오메트리 키 대장 (ST-11 재적합)

| 키 | 처분 |
|---|---|
| `shell` | **신설** — 셸 유일 지속 키, 기본 1140×720 |
| `editor` | 존치 — 위저드는 여전히 창 |
| `home` `run` `txt` `template` `pool` `matrix` `vocab` | **읽기·쓰기 중단**(코드에서 제거). INI 잔존은 무해 — 마이그레이션/청소 코드 발명 금지 |

## 5. 스테이지 착지 기록

S1~S7 전량 착지(2026-07-13), 최종 게이트 834 passed. 스테이지별 내용·커밋 해시는
git 히스토리 참조(`git log --oneline e24e03d..e317962` — S1 `e24e03d` → S7 `e317962`).
혼재 스테이지(S3~S5)의 일부-창·일부-임베드는 각 스테이지가 게이트 통과·기동 가능했다.

## 6. 테스트 영향

| 구분 | 항목 |
|---|---|
| 무개정 통과(설계로 보장) | 전수 배선(`_children` seam 유지) · 관리 창 싱글턴(페이지 유일성이 len==1 만족 — docstring 만 갱신) · 지오메트리 헬퍼(generic probe) · vocab `windowTitle` · 위저드 ST-08 가드 · headless VM 테스트 전부 |
| 개정 | run closeEvent 테스트(S2 위임 구조면 무개정 → S5 에서 `can_leave` 직접 검증으로 이관) · editor 싱글턴 전제 테스트 · 패널 "창" 어휘 docstring |
| 신규(ST-01 회귀 계약) | 레일↔스택 동기·현재 위치 / 홈 시그널 emit → `current_key()` 전이 + **새 최상위 창 0개**(`topLevelWidgets` 검사) / 복귀 시 상태 보존 / dirty 가드(전환·닫기) / run 슬롯 교체+teardown / 위저드 모달성 속성(exec 없이) / 재진입 refresh |
| offscreen 규율 | 기존 QMessageBox·`confirm_destructive` monkeypatch 패턴 유지 · `exec()` 호출 전면 금지 · `HWPXFILLER_HOME=tmp_path` 격리 |

## 7. 위험 대장

| # | 위험 | 처방 |
|---|---|---|
| R1 | QWizard `exec()` hang(offscreen) | D4 — 모달성만 부여, exec 금지 |
| R2 | QShortcut 모호 활성(F5×4·Ctrl+Return×2 전부 무동작) | D9 — S2 선행 수정 |
| R3 | closeEvent 로직 이전 누락(ST-21·ST-11 발화 불능) | D8 — `can_leave()` 추출 + 셸 closeEvent 집약, S2 위임 구조로 기존 테스트가 회귀 즉시 탐지 |
| R4 | run 페이지 교체 시 QThread 누수(hang/크래시) | `open_run` 수락 경로가 `request_cancel`+`teardown` 경유 강제 |
| R5 | QWizard parent 부여 부작용(배치·수명) | D4 — parent 무부여 |
| R6 | 레일 시그널 재귀(`activate` ↔ `currentRowChanged`) | `blockSignals` 규율 |
| R7 | QMainWindow→QWidget 시각 미세 변화(마진·viewport 타이밍) | 스테이지별 수동 기동 확인 |
