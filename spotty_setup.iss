; ─── Spotty Installer Script ───────────────────────────────────
; Inno Setup 6.x

#define MyAppName "Spotty"
; Версию НЕ дублируем: берём из собранного exe, а туда она попадает из
; spotty/core/constants.py (см. Spotty.spec). Поднять версию = поправить одну
; строку в constants.py и пересобрать.
#define MyAppExe "dist\Spotty.exe"
#if !FileExists(AddBackslash(SourcePath) + MyAppExe)
  #error Сначала соберите exe: pyinstaller --clean --noconfirm Spotty.spec
#endif
#define MyAppVersion GetStringFileInfo(AddBackslash(SourcePath) + MyAppExe, PRODUCT_VERSION)
#if MyAppVersion == ""
  #error В exe нет ресурса версии. Пересоберите его текущей Spotty.spec.
#endif
#define MyAppExeName "Spotty.exe"
#define MyAppPublisher "SmeshidoJoe"
#define MyAppUrl "https://github.com/SmeshidoJoe/Spotty"

[Setup]
; Первая скобка удвоена не по ошибке: одиночная «{» в Inno Setup начинает
; константу, и AppId с GUID без экранирования не компилируется.
AppId={{F7E24315-B257-4A33-B701-0C4D8376480E}} 
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
AppUpdatesURL={#MyAppUrl}/releases

; Ставим в папку программ текущего пользователя: при PrivilegesRequired=lowest
; это %LOCALAPPDATA%\Programs, куда можно писать без прав администратора. Это
; нужно самообновлению, которое подменяет exe на месте — в Program Files
; подмена молча не пройдёт.
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

OutputDir=installer_output
OutputBaseFilename=Spotty-Setup-{#MyAppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; Spotty держит один экземпляр на именованном мьютексе и сидит в трее. Если его
; не закрыть, установщик не сможет заменить exe.
CloseApplications=yes
RestartApplications=no
AppMutex=Spotty-Single-Instance-Mutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
english.DirNotWritable=This folder cannot be written to without administrator rights.%n%nSpotty updates itself and needs write access to its own folder, so please pick another location — for example the default one.
russian.DirNotWritable=В эту папку нельзя записывать без прав администратора.%n%nSpotty обновляет себя сам и должен иметь доступ на запись в свою папку, поэтому выберите другое место — например, предложенное по умолчанию.
english.KeepData=Keep settings and launch history
russian.KeepData=Оставить настройки и историю запусков

[Code]
// Проверяем, что в выбранную папку можно писать БЕЗ прав администратора.
// Иначе пользователь выберет Program Files, установка пройдёт, а обновление
// потом будет молча отказывать.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Probe: string;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;
  ForceDirectories(WizardDirValue);
  Probe := AddBackslash(WizardDirValue) + 'spotty_write_test.tmp';
  if SaveStringToFile(Probe, 'x', False) then
    DeleteFile(Probe)
  else begin
    Result := False;
    MsgBox(ExpandConstant('{cm:DirNotWritable}'), mbError, MB_OK);
  end;
end;

// При удалении спрашиваем, оставлять ли настройки. Молча стирать их нельзя,
// молча оставлять мусор — тоже некрасиво. Кэш иконок и списка программ в
// %LOCALAPPDATA% пересобирается сам, его убираем без вопросов.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DelTree(ExpandConstant('{localappdata}\{#MyAppName}'), True, True, True);
  DataDir := ExpandConstant('{userappdata}\{#MyAppName}');
  if not DirExists(DataDir) then
    Exit;
  if MsgBox(ExpandConstant('{cm:KeepData}') + '?', mbConfirmation, MB_YESNO) = IDNO then
    DelTree(DataDir, True, True, True);
end;

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Строка запуска работает из трея, поэтому автозапуск по умолчанию включён.
Name: "startup"; Description: "{cm:AutoStartProgram,{#MyAppName}}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

; Скачанное, но не установленное обновление программа держит в _update рядом с
; exe. Установщик его не ставил и сам бы не удалил — папка пережила бы удаление.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_update"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Автозапуск ставится галочкой в мастере. Программа умеет включать и выключать
; его сама из настроек — ключ тот же, поэтому они не конфликтуют.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Spotty"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

; Автозапуск, включённый уже в самой программе, установщик не создавал — и без
; этой строки запись пережила бы удаление, а Windows потом каждый раз пыталась
; бы запустить стёртый exe. ValueType: none + dontcreatekey означают «при
; установке ничего не делать», удаление значения происходит только при удалении
; программы.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "Spotty"; \
    Flags: dontcreatekey uninsdeletevalue

[Run]
; --show: сразу после установки строка открывается — видно, что всё работает.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--show"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
