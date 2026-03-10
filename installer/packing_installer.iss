#define MyAppName "Packing MVP"
#ifndef MyAppVersion
#define MyAppVersion "0.3.1"
#endif
#define MyAppPublisher "Packing MVP"
#define MyAppExeName "Packing.exe"

[Setup]
AppId={{8FD8A4C6-8F6F-4F8B-A9AA-FA38718AC550}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Packing MVP
DefaultGroupName=Packing MVP
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=PackingMVP-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные значки:"

[Files]
Source: "..\dist\Packing.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Packing MVP"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Packing MVP"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Packing MVP"; Flags: nowait postinstall skipifsilent
