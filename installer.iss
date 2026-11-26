; Inno Setup script for the Neo8085 Windows installer.
;
; Built by build.bat, which passes the version and the PyInstaller output:
;   ISCC /DAppVersion=2.0.0 /DBuildDir=dist\Neo8085-v2.0.0 installer.iss
; The result is dist\Neo8085-Installer-v<version>.exe.
;
; Neo8085 bundles 64-bit Python 3.13 and Qt 6.8, which need 64-bit
; Windows 10 version 1809 or later (Windows 11 on Arm runs it as x64).

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z /DBuildDir=... installer.iss
#endif
#ifndef BuildDir
  #define BuildDir "dist\Neo8085-v" + AppVersion
#endif

#define AppName "Neo8085"
#define AppExe "Neo8085.exe"
#define AppPublisher "Shahibur Rahaman"
#define AppURL "https://github.com/rusty-jar/Neo8085"

[Setup]
; The AppId identifies the application across versions: never change it,
; or new versions will install next to old ones instead of upgrading them
AppId={{2C220B30-FE0C-458D-82F5-F75A180A7491}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Copyright (C) 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
SetupIconFile=8085-logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

; Install for all users (needs admin) or only for the current user (no admin)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

; Close a running Neo8085 before replacing its files
CloseApplications=yes
RestartApplications=no

WizardStyle=modern dynamic
Compression=lzma2/max
SolidCompression=yes
OutputDir=dist
OutputBaseFilename={#AppName}-Installer-v{#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove the bundled runtime of an earlier version first, so files it had
; and this version no longer uses do not stay behind
Type: filesandordirs; Name: "{app}\PySide6"
Type: filesandordirs; Name: "{app}\shiboken6"
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\base_library.zip"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
