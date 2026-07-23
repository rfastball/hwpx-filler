#include "..\..\build\version\version.iss"

; 사용자 노출 제품명(#258) — 설치 마법사·시작 메뉴·바로가기 표기.
; 기술 식별자(설치 폴더·산출 파일명·AppId)는 hwpx-filler 계열 유지: 폴더/파일명 변경은
; 기존 설치 업그레이드 연속성과 release.yml 스모크(HWPX-Filler-*-Setup.exe 수집)를 깬다.
; 개명 마이그레이션(옛 그룹·옛 .lnk 정리, UsePreviousGroup=no)은 두지 않는다 — 개명 시점
; (#258, v0.1.x) 기준 구버전 "HWPX Filler" 설치 사용자가 0 이라 정리할 잔재가 없다.
#define AppName "문서나르미"
#define AppExe "hwpx-filler-web.exe"

[Setup]
AppId={{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HWPX Tools
DefaultDirName={localappdata}\Programs\HWPX Filler
DefaultGroupName={#AppName}
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

[Files]
Source: "..\..\dist\hwpx-filler-web\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
