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
VersionInfoVersion={#AppVersionInfo}

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: unchecked

[Files]
Source: "..\..\dist\hwpx-filler-web\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}_is1';

var
  ModePage: TInputOptionWizardPage;

function IsUpgrade(): Boolean;
begin
  Result := RegKeyExists(HKEY_CURRENT_USER, UninstallKey);
end;

function DataHomeDir(): String;
begin
  Result := GetEnv('HWPXFILLER_HOME');
  if Result = '' then
    Result := ExpandConstant('{%USERPROFILE}\.hwpxfiller');
end;

procedure InitializeWizard();
begin
  ModePage := CreateInputOptionPage(wpWelcome,
    '기존 설치 감지', '설치 방식을 선택하세요',
    '이 컴퓨터에 문서나르미가 이미 설치되어 있습니다.',
    True, False);
  ModePage.Add('기존 데이터를 유지하며 덮어쓰기(권장)');
  ModePage.Add('모든 데이터를 지우고 새로 설치(초기화)');
  ModePage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ModePage.ID) and not IsUpgrade();
end;

function WipeSelected(): Boolean;
begin
  { silent 모드에서는 페이지가 뜨지 않아 인덱스가 0으로 남지만, 무인 경로가
    실수로도 삭제로 빠지지 않도록 WizardSilent 를 명시 가드로 겹친다 }
  Result := (not WizardSilent()) and IsUpgrade()
    and (ModePage.SelectedValueIndex = 1);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ModePage.ID) and (ModePage.SelectedValueIndex = 1) then
    Result := MsgBox(
      '모든 데이터를 지우고 새로 설치합니다.'
      + #13#10 + #13#10
      + '사라지는 것: 작업 · 템플릿 · 데이터셋 · 실행 기록 · 설정'
      + #13#10 + '삭제 위치: ' + DataHomeDir()
      + #13#10 + #13#10
      + '삭제한 데이터는 되돌릴 수 없습니다.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and WipeSelected() then
  begin
    if DirExists(DataHomeDir()) then
      DelTree(DataHomeDir(), True, True, True);
    if DirExists(ExpandConstant('{app}')) then
      DelTree(ExpandConstant('{app}'), True, True, True);
  end;
end;
