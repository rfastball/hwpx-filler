#include "..\..\build\version\version.iss"

#define AppName "HWPX Diff"
#define AppExe "hwpx-diff.exe"

[Setup]
AppId={{3BF62B4B-856D-451D-967D-8A31F0714409}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HWPX Tools
DefaultDirName={localappdata}\Programs\HWPX Diff
DefaultGroupName=HWPX Diff
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\installer-dist
OutputBaseFilename=HWPX-Diff-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: unchecked

[Files]
Source: "..\..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
