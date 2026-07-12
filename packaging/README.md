# PyInstaller onedir 패키징

앱 A(`hwpx-diff`), 앱 B(`hwpx-filler`), 자동화 CLI(`hwpx-cli`)를 각각 독립
`onedir` 번들로 만든다. 받는 사람에게는 exe 하나가 아니라 해당 폴더
전체를 배포한다.

## 빌드

```powershell
uv sync --locked --all-extras --group dev --group build
.\packaging\build.ps1
.\packaging\build.ps1 -Target filler
.\packaging\build.ps1 -Target diff
.\packaging\build.ps1 -Target cli
```

산출물:

- `dist\hwpx-diff\hwpx-diff.exe`
- `dist\hwpx-filler\hwpx-filler.exe`
- `dist\hwpx-cli\hwpx-cli.exe`

아이콘은 없으면 spec이 생성한다. 디자인 토큰은 `gui/style.py`의 빌드타임
상수이므로 런타임 data 파일이 필요 없다.

## 빌드 검증

`build.ps1`은 spec 계약 검사 후 실제 번들에서 다음을 스모크한다.

- 앱 A: HWPX 두 판본 diff + HTML 렌더 selfcheck, GUI 이벤트 루프 기동
- 앱 B: Qt + openpyxl + 매핑 + txt 렌더 selfcheck, GUI 이벤트 루프 기동
- CLI: `schema`, `fieldize`, `lint`, `drift` 네 하위명령

`lint`는 이슈를 찾으면 정상적으로 exit 1을 내므로 빌드 스크립트가 0과 1을
둘 다 실행 성공으로 받는다.

## 의존성 경계

- GUI는 QtCore/Gui/Widgets만 쓰고 WebEngine/QML/Quick/Multimedia/Sql 등을 제외한다.
- CLI에서는 PySide6 전체를 제외한다.
- `cli.py`의 함수 내 import를 CLI spec의 hidden import로 명시한다.
- 앱 A에서 `hwpxfiller`/openpyxl, 앱 B에서 `hwpxdiff`를 제외해 제품 경계를 유지한다.
- 한글 COM PDF 경로는 번들하지 않는 호스트 옵션 기능으로 남겨둔다.

## 설치 패키징

`packaging/installers/*.iss`는 onedir 폴더 전체를 Inno Setup에 담도록 구성되어
있다. 코드 서명과 Nuitka 전환은 이 유닛의 범위 밖이다.
