@echo off
rem Builds the Windows version of Neo8085 with PyInstaller.
rem
rem Output: dist\Neo8085-v<version>\Neo8085.exe with all of its files in the
rem same folder. The version comes from src\version.py, which is also written
rem into the exe's file properties.
rem
rem Requirements: pip install -r requirements.txt (uses venv\ when it exists).

setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"

set "PYTHON=python"
if exist "venv\Scripts\python.exe" set "PYTHON=venv\Scripts\python.exe"

for /f "delims=" %%v in ('call "%PYTHON%" -c "import sys; sys.path.insert(0, 'src'); import version; print(version.version_info)"') do set "VERSION=%%v"
if not defined VERSION (
    echo Could not read the version from src\version.py
    exit /b 1
)
set "OUTPUT=dist\Neo8085-v%VERSION%"
echo Building Neo8085 %VERSION% into %OUTPUT%

if not exist build mkdir build

rem Windows file properties (version, description, copyright) from src\version.py
"%PYTHON%" -c "import sys; sys.path.insert(0, 'src'); import version as v; from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct; n = tuple(int(x) for x in v.__version__.split('.')) + (v.__build_number__,); strings = [StringStruct('CompanyName', 'Shahibur Rahaman'), StringStruct('FileDescription', 'Neo8085 - 8085 Microprocessor Simulator'), StringStruct('FileVersion', v.version_string), StringStruct('InternalName', 'Neo8085'), StringStruct('LegalCopyright', 'Copyright (C) 2026 Shahibur Rahaman. GPL v3.'), StringStruct('OriginalFilename', 'Neo8085.exe'), StringStruct('ProductName', 'Neo8085'), StringStruct('ProductVersion', v.version_info)]; info = VSVersionInfo(ffi=FixedFileInfo(filevers=n, prodvers=n), kids=[StringFileInfo([StringTable('040904B0', strings)]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]); open('build/version_info.txt', 'w', encoding='utf-8').write(str(info))"
if errorlevel 1 exit /b 1

"%PYTHON%" -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --contents-directory . ^
    --name Neo8085 ^
    --icon "%ROOT%8085-logo.ico" ^
    --version-file "%ROOT%build\version_info.txt" ^
    --add-data "%ROOT%8085-logo.ico;." ^
    --add-data "%ROOT%8085-splash-screen.png;." ^
    --paths "%ROOT%src" ^
    --distpath "%ROOT%dist" ^
    --workpath "%ROOT%build\pyinstaller" ^
    --specpath "%ROOT%build" ^
    "%ROOT%src\main.py"
if errorlevel 1 exit /b 1

if exist "%OUTPUT%" rmdir /s /q "%OUTPUT%"
move "dist\Neo8085" "%OUTPUT%" >nul
if errorlevel 1 exit /b 1

echo.
echo Done: %OUTPUT%\Neo8085.exe
