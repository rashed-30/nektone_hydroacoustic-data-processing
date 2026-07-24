@echo off
REM Build NekTone.exe on Windows. Run from the repository root.
setlocal

echo === Creating build environment ===
python -m venv .venv-build || goto :error
call .venv-build\Scripts\activate.bat

echo === Installing dependencies ===
python -m pip install --upgrade pip                || goto :error
python -m pip install -e .                          || goto :error
python -m pip install pyinstaller                   || goto :error

echo === Freezing ===
pyinstaller packaging\nektone.spec --noconfirm --clean || goto :error

echo.
echo === Done ===
echo Your application is in:  dist\NekTone\NekTone.exe
echo Zip the whole dist\NekTone folder to share it.
goto :eof

:error
echo.
echo BUILD FAILED - see the messages above.
echo.
echo For a step-by-step walkthrough and a troubleshooting table, open:
echo     packaging\WINDOWS_BUILD.md
exit /b 1
