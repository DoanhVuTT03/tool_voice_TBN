; Inno Setup script for Tool Voice
; Builds a small installer. The heavy runtime (~7GB) and model (~3.4GB) are
; downloaded by the app on first launch, so they are NOT bundled here.
;
; Installs per-user into %LocalAppData%\Programs\Tool Voice so first-run
; downloads need no admin rights.

#define AppName "Tool Voice"
#define AppVer "1.0.0"
#define AppExe "ToolVoice.exe"
#define Pub "Tool Voice"

[Setup]
AppId={{B7F2B3B1-9C2E-4E2A-9E7A-TOOLVOICE0001}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#Pub}
DefaultDirName={localappdata}\Programs\Tool Voice
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build_output\installer_out
OutputBaseFilename=ToolVoice-Setup-{#AppVer}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=

[Languages]
Name: "vi"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong ngoai man hinh (Desktop)"; GroupDescription: "Tuy chon:"

[Files]
Source: "..\build_output\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.json";                 DestDir: "{app}";          Flags: ignoreversion
Source: "..\app\*";       DestDir: "{app}\app";       Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\*";   DestDir: "{app}\scripts";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tk_bundle\*"; DestDir: "{app}\tk_bundle"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Go cai dat {#AppName}";   Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Mo {#AppName} ngay"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the runtime + model that the app downloaded after install.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\models"
