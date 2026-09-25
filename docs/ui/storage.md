# 라이브러리와 저장

## 문서 작업 목록

라이브러리는 저장된 작업을 찾고 선택·복제·삭제·복원하는 곳이다. 상세 패널은 선택한 작업의
템플릿·데이터·연결 상태를 설명하고 편집이나 문서 만들기로 연결한다. 이름은 표시 라벨과
파일 관리에 쓰지만 데이터 풀의 안정 key를 대신하지 않는다.

열린 세션의 identity에 결속된 이름 변경 등은 그 세션의 소유자가 처리한다.
라이브러리 화면이 보인다는 이유로 같은 동사를 두 컨트롤러가 소유하지 않는다.
손상된 작업·끊긴 참조는 조용히 목록에서 버리지 않고 이유와 복구 동사를 보여 준다.
태그·그룹은 [동결 범위](../FEATURE_SCOPE.md)에 속한다.

## 앱 홈

앱 홈은 `HWPXFILLER_HOME` 또는 `~/.hwpxfiller`다.
[host/locations.py](../../src/hwpxfiller/host/locations.py)가 해석하는 유일한 경계다.
작업 레지스트리, TXT 템플릿 레지스트리, 데이터 참조, 설정과 생성 관련 원장은 각각의
external/domain 소유자를 통해 접근한다. UI가 임의 경로를 조립해 영속을 우회하지 않는다.

데이터 풀은 파일의 행 내용을 보관하는 사본 저장소가 아니다. 등록한 참조를 명시적 로드·
새로고침 경계에서 읽어 세션을 만든다. 풀의 key와 그때 포획한 파일 참조는 다른 수명이다.

테스트는 autouse fixture로 앱 홈을 임시 경로에 격리한다. 실제 사용자 설정과 파일을
오염시킬 수 있으므로 이 격리를 끄지 않는다.

## 저장 폴더

출력 위치를 고르는 자리는 설정 모달 하나다. 전역 설정 `last_output_directory`를 사용하고
편집기와 작업 화면은 같은 해석 결과를 읽기 전용으로 보여 준다. 작업마다 별도 저장 폴더
설정을 다시 만들지 않는다.

유효한 설정 폴더를 우선하고, 그렇지 않으면 템플릿 옆 `Results`를 기본값으로 해석한다.
둘 다 사용할 수 없으면 `OUTPUT_DIRECTORY_REQUIRED`로 막는다.
[output_folder_default.py](../../src/hwpxfiller/domain/output_folder_default.py)가 순수 판정을,
[output_folder_zone.py](../../src/hwpxfiller/webapp/output_folder_zone.py)가 공용 화면 투영을
담당한다. 폴더를 고르는 효과와 판정을 섞지 않는다.

## 템플릿 폴더

템플릿 풀은 **설정한 단일 루트 폴더**다. 사용자 폴더를 그대로 관리하며 누름틀 변환도
그 자리에서 수행한다. 앱 홈에 복사한 별도 풀이나 사용자 폴더용 앱 휴지통·복원 기제를
전제로 설명하지 않는다.

명시한 루트가 사라졌으면 실패를 알린다. 출력 폴더와 달리 임의의 다른 폴더로 fallback하지
않는다. 파일의 루트 소속은 경로 해석기로 판정한다. 문자열 prefix 비교로 루트 밖 파일을
안쪽으로 인정하지 않는다. 폴더 교체와 템플릿 연결 복구는 관련 세션을 갱신해야 한다.

템플릿 루트의 원천은 [external/template_root.py](../../src/hwpxfiller/external/template_root.py),
순수 기본값 판정은 [domain/template_root_default.py](../../src/hwpxfiller/domain/template_root_default.py)다.

## 설정과 검증

설정 모달은 테마·글자 크기와 폴더 설정을 제공한다. 생성 중에는 관련 폴더 변경을 잠그고
이유를 표시하지만 테마·글자 크기까지 무조건 잠그지 않는다. 공유 FolderRow와 기존 설정
경계를 사용한다.

[screen_library.py](../../src/hwpxfiller/webapp/screen_library.py),
[screen_template.py](../../src/hwpxfiller/webapp/screen_template.py),
[settings_sheet.ts](../../frontend/src/screens/settings_sheet.ts)가 각 표면을 구현한다.
경로·설정·라이브러리의 행동 테스트와 [실앱 검사](../../tests/test_web_selftest_gate.py)를
함께 사용한다.
