; Google Calendar Widget installer (Inno Setup 6). build.bat builds dist\GoogleCalendarWidget first.
#define AppName "Google Calendar Widget"
#define AppExe "GoogleCalendarWidget.exe"
#define AppVersion "1.2.2"

[Setup]
AppId={{6C1E2B7A-3F4D-4E8B-9A51-0D2C7F3B8E61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Inhu Kim
; Per-user install, no admin rights needed
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\GoogleCalendarWidget
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist
OutputBaseFilename=GoogleCalendarWidget-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

; Shows a language picker (defaults to the Windows display language)
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.DesktopIcon=바탕화면에 바로가기 만들기
english.DesktopIcon=Create a desktop shortcut
korean.InstallingWebView2=WebView2 런타임 설치 중...
english.InstallingWebView2=Installing the WebView2 runtime...
korean.RunNow=지금 실행
english.RunNow=Launch now
korean.UninstallFailed=이전 버전(%1)을 제거하지 못했습니다. 제어판에서 직접 제거한 뒤 다시 설치해 주세요.
english.UninstallFailed=Could not remove the previous version (%1). Please uninstall it from Settings and run setup again.
korean.UninstallTimeout=이전 버전(%1) 제거가 끝나지 않았습니다. 잠시 후 다시 설치해 주세요.
english.UninstallTimeout=Removing the previous version (%1) did not finish. Please run setup again in a moment.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "dist\GoogleCalendarWidget\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[InstallDelete]
; Shortcuts from the pre-1.1.0 name
Type: files; Name: "{userprograms}\Google Calendar 위젯.lnk"
Type: files; Name: "{userdesktop}\Google Calendar 위젯.lnk"

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Created by the tray "Start with Windows" option, removed on uninstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GoogleCalendarWidget"; ValueType: none; Flags: uninsdeletevalue
; The widget's language until one is picked in the tray
Root: HKCU; Subkey: "Software\GoogleCalendarWidget"; ValueName: "InstallerLanguage"; ValueType: string; ValueData: "{language}"; Flags: uninsdeletekey

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "{cm:InstallingWebView2}"; Check: NeedsWebView2; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "{cm:RunNow}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "KillWidget"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6C1E2B7A-3F4D-4E8B-9A51-0D2C7F3B8E61}_is1';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'GoogleCalendarWidget';
  WebView2Key = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasVersion(RootKey: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function NeedsWebView2: Boolean;
begin
  Result := not (HasVersion(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2Key) or
                 HasVersion(HKLM, 'SOFTWARE\' + WebView2Key) or
                 HasVersion(HKCU, 'Software\' + WebView2Key));
end;

var
  SavedAutostart: String;

{ Silently uninstall an older version first.
  Sign-in and settings in %LOCALAPPDATA%\GoogleCalendarWidget are kept. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldVersionText, Uninstaller: String;
  OldVersion, NewVersion: Int64;
  ResultCode, Waited: Integer;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', OldVersionText) then
    Exit;
  if not (StrToVersion(OldVersionText, OldVersion) and StrToVersion('{#AppVersion}', NewVersion)) then
    Exit;
  if ComparePackedVersion(OldVersion, NewVersion) >= 0 then
    Exit;
  if not RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', Uninstaller) then
    Exit;
  { The old uninstaller removes the autostart entry, so restore it afterwards }
  if not RegQueryStringValue(HKCU, RunKey, RunValue, SavedAutostart) then
    SavedAutostart := '';
  if not Exec('>', Uninstaller + ' /VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Result := FmtMessage(CustomMessage('UninstallFailed'), [OldVersionText]);
    Exit;
  end;
  { The uninstaller re-launches itself from %TEMP% and returns at once; wait up to 30 s }
  Uninstaller := RemoveQuotes(Uninstaller);
  Waited := 0;
  while FileExists(Uninstaller) and (Waited < 30000) do
  begin
    Sleep(200);
    Waited := Waited + 200;
  end;
  if FileExists(Uninstaller) then
    Result := FmtMessage(CustomMessage('UninstallTimeout'), [OldVersionText]);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (SavedAutostart <> '') then
    RegWriteStringValue(HKCU, RunKey, RunValue, SavedAutostart);
end;
