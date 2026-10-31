#define AppName "RoseSI"
#define AppVersion "1.2.0"
#define AppExe "RoseSI.exe"

#ifdef Lite
#define OutputSuffix "-Lite"
#define InstallSuffix " Lite"
#define AppIdValue "{{A2B4E6F8-1C3D-4E5F-8A9B-0C1D2E3F4A5B}"
#else
#define OutputSuffix ""
#define InstallSuffix ""
#define AppIdValue "{{7D6A0C3B-6D7E-4F62-9B7C-2C8F0B7A1E42}"
#endif

[Setup]
AppId={#AppIdValue}
AppName={#AppName}{#InstallSuffix}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}{#InstallSuffix}
AppPublisher=RoseSI
DefaultDirName={autopf}\RoseSI{#InstallSuffix}
DefaultGroupName={#AppName}{#InstallSuffix}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=RoseSI-{#AppVersion}{#OutputSuffix}-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSES\HY-MT1.5-License.txt
InfoBeforeFile=install_notice.txt
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
Source: "..\dist\RoseSI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\models"
