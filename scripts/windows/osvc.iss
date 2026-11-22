; Instalátor OSVČ evidence pro Windows (krok I4) – Inno Setup 6. Sestavení: scripts/windows/sestav.py, pak ve složce windows-VERZE:
;   ISCC.exe osvc.iss        (verzi doplní sestav.py; ručně /DVerze=…)
; Instaluje jen pro přihlášeného uživatele (bez práv správce) do %LOCALAPPDATA%\Programs\OSVC evidence.
; Data a nastavení: %LOCALAPPDATA%\OSVC evidence (místní disk – SQLite nesmí být na síťové/roamingové složce).
; Odinstalace data NEMAŽE. Aktualizace = spustit novější instalátor (běžící aplikaci nejdřív ukončí).
#define Verze "0.0.0"
#define VerzeCislo "0.0.0"   ; číselná verze X.Y.Z (doplní sestav.py z tagu, bez přípony -test; čtvrté číslo nepoužíváme)
#define Nazev "OSVČ evidence"
#define Konf "{localappdata}\OSVC evidence\osvc.conf"
#define Data "{localappdata}\OSVC evidence\data"
; uvozovky zdvojené – hodnota se vkládá do "…" v sekcích níže
#define Spust '-X utf8 -m osvc_app.spoustec spust --config ""' + Konf + '"" --data ""' + Data + '""'

[Setup]
AppId={{6F1C2B7E-4A0D-4C8E-9B57-0D3E2A51C9A4}
AppName={#Nazev}
AppVersion={#Verze}
AppVerName={#Nazev} {#Verze}
AppPublisher={#Nazev}
; Metadata souboru (podmínka SignPath: název produktu a verze ve všech atributech)
VersionInfoProductName={#Nazev}
VersionInfoDescription={#Nazev} – instalátor
VersionInfoCompany={#Nazev}
VersionInfoCopyright=EUPL-1.2
VersionInfoVersion={#VerzeCislo}
VersionInfoProductVersion={#VerzeCislo}
VersionInfoTextVersion={#Verze}
VersionInfoProductTextVersion={#Verze}
; Zásady soukromí ukázané při instalaci (aplikace se připojuje k ARES a GitHubu – podmínka SignPath)
InfoBeforeFile=soukromi.txt
DefaultDirName={localappdata}\Programs\OSVC evidence
DisableDirPage=yes
DefaultGroupName={#Nazev}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=.
OutputBaseFilename=osvc-evidence-{#Verze}-windows
SetupIconFile=osvc.ico
UninstallDisplayIcon={app}\osvc.ico
UninstallDisplayName={#Nazev}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "cs"; MessagesFile: "compiler:Languages\Czech.isl"

[Tasks]
Name: "autostart"; Description: "Spouštět {#Nazev} po přihlášení do Windows (doporučeno – jen když aplikace běží, dělá denní zálohy a synchronizaci)"
Name: "plocha"; Description: "Zástupce na ploše"; Flags: unchecked

[InstallDelete]
; při aktualizaci nejdřív pryč starý kód i Python, aby nezůstaly staré moduly (data jsou jinde a zůstávají)
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"

[UninstallDelete]
; Python si za běhu ukládá mezipaměť (__pycache__) do složky programu – Inno maže jen soubory, které nainstaloval.
; Smaže se jen složka programu; data jsou v %LOCALAPPDATA%\OSVC evidence a o nich rozhoduje odinstalace (viz [Code]).
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: files; Name: "{app}\Obnovit heslo.cmd"
Type: dirifempty; Name: "{app}"

[Files]
Source: "python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "osvc.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "Obnovit heslo.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#Nazev}"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#Spust} --otevrit"; WorkingDir: "{app}\app"; IconFilename: "{app}\osvc.ico"; Comment: "Spustí evidenci a otevře ji v prohlížeči"
Name: "{autoprograms}\Zastavit {#Nazev}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-X utf8 -m osvc_app.spoustec zastav --config ""{#Konf}"""; WorkingDir: "{app}\app"; IconFilename: "{app}\osvc.ico"; Comment: "Ukončí běžící evidenci"
; zapomenuté heslo (1.0.3): dočasné přihlášení osvc / osvc jen na tomto počítači; nástroj se zeptá a výsledek oznámí v okně
Name: "{autoprograms}\{#Nazev} – obnovit heslo"; Filename: "{app}\python\pythonw.exe"; Parameters: "-X utf8 -m osvc_app.spoustec obnovit-heslo --config ""{#Konf}"""; WorkingDir: "{app}\app"; IconFilename: "{app}\osvc.ico"; Comment: "Zapomenuté heslo: dočasné přihlášení osvc / osvc na tomto počítači"
Name: "{autodesktop}\{#Nazev}"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#Spust} --otevrit"; WorkingDir: "{app}\app"; IconFilename: "{app}\osvc.ico"; Tasks: plocha
Name: "{userstartup}\{#Nazev}"; Filename: "{app}\python\pythonw.exe"; Parameters: "{#Spust}"; WorkingDir: "{app}\app"; IconFilename: "{app}\osvc.ico"; Tasks: autostart

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "{#Spust} --otevrit"; WorkingDir: "{app}\app"; Description: "Spustit {#Nazev}"; Flags: postinstall nowait skipifsilent
; aktualizace z aplikace (skrytá instalace /VERYSILENT /SPUSTIT=1): po instalaci aplikaci znovu spustit, stránka v prohlížeči se obnoví sama
Filename: "{app}\python\pythonw.exe"; Parameters: "{#Spust}"; WorkingDir: "{app}\app"; Flags: nowait; Check: SpustitPoAktualizaci

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-X utf8 -m osvc_app.spoustec zastav --config ""{#Konf}"""; WorkingDir: "{app}\app"; Flags: runhidden waituntilterminated; RunOnceId: "zastavit"

[Code]
// Odinstalace (V3): zastavit aplikaci → „Ponechat data“ (výchozí) / „Smazat i data“ → u smazání nabídnout ZIP zálohu na Plochu
// a vyžádat potvrzení. Tichá odinstalace (/SILENT, testy): data zůstanou; /SMAZATDATA=1 je smaže, předtím ZIP do /ZALOHA=složka
// (výchozí Plocha). Zástupce (Start, plocha, po přihlášení) odebere Inno samo; plánovač je jen uvnitř aplikace.
// Pravidlo firewallu „OSVC evidence“ vzniká jen při zapnutém síťovém přístupu (Nastavení) – odinstalace ho odebere (UAC).
var
  SmazatData: Boolean;

function Python(Parametry: String; var Kod: Integer): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\python\python.exe')) and
            Exec(ExpandConstant('{app}\python\python.exe'), '-X utf8 -m osvc_app.spoustec ' + Parametry,
                 ExpandConstant('{app}\app'), SW_HIDE, ewWaitUntilTerminated, Kod);
end;

function ZastavAplikaci(): Boolean;
var
  Kod: Integer;
begin
  Result := Python('zastav --config "' + ExpandConstant('{#Konf}') + '"', Kod);
end;

function SpustitPoAktualizaci(): Boolean;
begin
  Result := ExpandConstant('{param:SPUSTIT|0}') = '1';
end;

// Před aktualizací ukončit běžící aplikaci (jinak by byly soubory Pythonu zamčené). Data jsou mimo {app} a zůstávají.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  ZastavAplikaci();
end;

function ZalohaZip(Slozka: String): Boolean;
var
  Kod: Integer;
begin
  Result := Python('zaloha-zip --config "' + ExpandConstant('{#Konf}') + '" --cil "' + Slozka + '"', Kod) and (Kod = 0);
end;

// Pravidlo firewallu ze síťového přístupu: netsh „show rule“ jde bez práv správce, smazání přes UAC (runas).
procedure OdeberPravidloFirewallu();
var
  Kod: Integer;
begin
  if Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="OSVC evidence"', '', SW_HIDE, ewWaitUntilTerminated, Kod) and (Kod = 0) then
    if not ShellExec('runas', ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall delete rule name="OSVC evidence"', '', SW_HIDE, ewWaitUntilTerminated, Kod) then
      if not UninstallSilent then
        MsgBox('Pravidlo „OSVC evidence“ ve firewallu Windows se nepodařilo odebrat (oprávnění správce nebylo uděleno).' + #13#10 +
               'Odeberete ho v Ovládacích panelech → Brána firewall systému Windows → Upřesnit nastavení → Příchozí pravidla.', mbInformation, MB_OK);
end;

procedure RozhodniOData();
var
  Volba: Integer;
begin
  SmazatData := False;
  if not DirExists(ExpandConstant('{localappdata}\OSVC evidence')) then Exit;
  if UninstallSilent then
  begin
    if ExpandConstant('{param:SMAZATDATA|0}') = '1' then
      SmazatData := ZalohaZip(ExpandConstant('{param:ZALOHA|{userdesktop}}'));   // bez úspěšné zálohy se data nesmažou
    Exit;
  end;
  Volba := TaskDialogMsgBox('Co s vašimi daty?',
    'Data (databáze, doklady, zálohy) jsou ve složce' + #13#10 + ExpandConstant('{localappdata}\OSVC evidence') + #13#10#13#10 +
    'Ponechaná data použije další instalace.', mbConfirmation, MB_YESNO, ['Ponechat data (doporučeno)', 'Smazat i data'], 0);
  if Volba <> IDNO then Exit;
  Volba := TaskDialogMsgBox('Uložit nejdřív zálohu?',
    'Před smazáním doporučujeme uložit ZIP zálohu všech dat na Plochu. Z ní jde vše obnovit v nové instalaci (Nastavení → Záloha a obnova).',
    mbConfirmation, MB_YESNOCANCEL, ['Uložit zálohu na Plochu', 'Neukládat', 'Zpět – data ponechat'], 0);
  if Volba = IDCANCEL then Exit;
  if Volba = IDYES then
    if not ZalohaZip(ExpandConstant('{userdesktop}')) then
    begin
      MsgBox('Zálohu se nepodařilo uložit. Data proto zůstanou zachovaná.', mbError, MB_OK);
      Exit;
    end;
  SmazatData := MsgBox('Opravdu smazat všechna data OSVČ evidence?' + #13#10#13#10 +
    'Databáze, doklady i automatické zálohy budou nenávratně odstraněny.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    ZastavAplikaci();      // dokud je Python ještě na místě
    OdeberPravidloFirewallu();
    RozhodniOData();
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    if SmazatData then
    begin
      DelTree(ExpandConstant('{localappdata}\OSVC evidence'), True, True, True);
      if not UninstallSilent then MsgBox('Aplikace i její data jsou odstraněné.', mbInformation, MB_OK);
    end
    else if not UninstallSilent and DirExists(ExpandConstant('{localappdata}\OSVC evidence')) then
      MsgBox('Aplikace je odinstalovaná. Vaše data zůstala ve složce' + #13#10 + ExpandConstant('{localappdata}\OSVC evidence') + #13#10#13#10 +
             'Při nové instalaci se použijí znovu.', mbInformation, MB_OK);
  end;
end;
