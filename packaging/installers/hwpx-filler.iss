#include "..\..\build\version\version.iss"

#define AppName "HWPX Filler"
#define AppExe "hwpx-filler.exe"

[Setup]
AppId={{A08D764C-A28D-4E7E-A8E9-E391E11A5A8C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HWPX Tools
DefaultDirName={localappdata}\Programs\HWPX Filler
DefaultGroupName=HWPX Filler
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\installer-dist
OutputBaseFilename=HWPX-Filler-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: unchecked

[Files]
Source: "..\..\dist\hwpx-filler\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
