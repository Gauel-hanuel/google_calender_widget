@echo off
rem Builds the installer: dist\GoogleCalendarWidget-Setup.exe
rem Needs Inno Setup 6 and redist\MicrosoftEdgeWebview2Setup.exe (https://go.microsoft.com/fwlink/p/?LinkId=2124703)
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install -q -r requirements.txt pyinstaller || exit /b 1
.venv\Scripts\python.exe make_icon.py || exit /b 1
rem onedir build: no unpacking on every launch, so it starts fast
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --name GoogleCalendarWidget --icon icon.ico widget.py || exit /b 1
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
"%ISCC%" /Q installer.iss
