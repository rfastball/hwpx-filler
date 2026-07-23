#include "..\..\build\version\version.iss"

; 사용자 노출 제품명(#258) — 설치 마법사·시작 메뉴·바로가기 표기.
; 기술 식별자(설치 폴더·산출 파일명·AppId)는 hwpx-filler 계열 유지: 폴더/파일명 변경은
; 기존 설치 업그레이드 연속성과 release.yml 스모크(HWPX-Filler-*-Setup.exe 수집)를 깬다.
#define AppName "문서나르미"
#define AppExe "hwpx-filler-web.exe"

[Setup]
AppId={{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HWPX Tools
DefaultDirName={localappdata}\Programs\HWPX Filler
DefaultGroupName={#AppName}
; 개명 마이그레이션(#258): 기본값 UsePreviousGroup=yes 는 업그레이드에서 저장된 옛 그룹
; ("HWPX Filler")을 재사용해 개명이 사용자에게 안 보인다 — 새 기본 그룹(문서나르미)을 쓰게 한다.
; 옛 그룹·옛 이름 바로가기 잔재는 [InstallDelete] 가 치운다.
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\installer-dist
OutputBaseFilename=HWPX-Filler-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\hwpx-filler.ico
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: unchecked

[InstallDelete]
; 개명 이전(≤v0.1.x "HWPX Filler") 설치의 바로가기 정리 — [Icons] 이름이 바뀌어 옛 .lnk 는
; 덮어써지지 않고 새 문서나르미 바로가기와 병존한다. PrivilegesRequired=lowest 라 auto=user 상수.
Type: files; Name: "{autoprograms}\HWPX Filler\HWPX Filler.lnk"
Type: dirifempty; Name: "{autoprograms}\HWPX Filler"
Type: files; Name: "{autodesktop}\HWPX Filler.lnk"

[Files]
Source: "..\..\dist\hwpx-filler-web\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
