; Inno Setup script for TG Drop Deck.
;
; Drop Deck shipped as a zip through 2.0.0, which meant there was no way to send
; anyone a new version - a release with no update channel is frozen forever,
; bugs included. An installer is what appupdate.py can actually run, so from
; 2.1.0 the installer is the update path and the zip stays only for people who
; would rather unpack a folder.
;
; Per-user install under LocalAppData with PrivilegesRequired=lowest. That is an
; accessibility decision, not a packaging one: installing into Program Files
; raises a UAC prompt, and a UAC prompt appearing while the app is closing
; around it is a dialog with no context for a screen reader user.
;
; The AppId GUID must never change. Change it and the next release installs
; alongside the old one instead of over it.

#define AppName "TG Drop Deck"
#define AppPublisher "TG Studios"
#define AppExeName "TG Drop Deck.exe"
#define AppURL "https://tgstudios.app"

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\TG Drop Deck"
#endif
#ifndef OutputDir
  #define OutputDir "installer"
#endif
#ifndef IconFile
  #define IconFile "..\assets\dropdeck.ico"
#endif

[Setup]
AppId={{3D7B9E42-8C15-4A6F-B03E-1F5A72C8D904}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppPublisher}\{#AppName}
DefaultGroupName={#AppPublisher}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
OutputDir={#OutputDir}
OutputBaseFilename=TGDropDeck-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
; Close the app before replacing files, and restart it after. Without this an
; update fails silently because the exe is locked - and Drop Deck holds an open
; audio stream, which makes that more likely, not less.
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the installed program. The user's board, their own sounds and their
; hotkeys live in {userappdata}\TG Studios\TG Drop Deck and are deliberately
; left behind: uninstalling to fix a problem must not destroy a board someone
; spent an afternoon building.
Type: filesandordirs; Name: "{app}"
