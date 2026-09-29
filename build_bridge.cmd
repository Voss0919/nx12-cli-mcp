@echo off
setlocal
set "ROOT=%~dp0"
set "CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
"%CSC%" /nologo /target:exe /platform:x64 /out:"%ROOT%pipe_client.exe" "%ROOT%pipe_client.cs"
if errorlevel 1 exit /b 1
echo Built: %ROOT%pipe_client.exe
