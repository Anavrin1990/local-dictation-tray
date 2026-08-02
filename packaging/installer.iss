; Inno Setup template. Build with scripts/build-installer.ps1.

#ifndef AppName
  #define AppName "Local Dictation"
#endif
#ifndef AppVersion
  #define AppVersion "0.3.3"
#endif
#ifndef AppExeName
  #define AppExeName "LocalDictationTray.exe"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\LocalDictationTray"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist-installer"
#endif
#ifndef OutputBaseName
  #define OutputBaseName "LocalDictationTray-Setup"
#endif
#ifndef IconFile
  #define IconFile "..\assets\tray-icon.ico"
#endif

[Setup]
AppId={{D14E9C70-A0DF-43A3-9FA5-20CB6B0B1E8B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Local Dictation
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile={#IconFile}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start with Windows"; GroupDescription: "Additional settings:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LocalDictationTray"; ValueData: """{app}\{#AppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
