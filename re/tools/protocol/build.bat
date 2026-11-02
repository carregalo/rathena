@echo off
rem Compiles the protocol dump tools against the server's headers with the map server's settings and writes
rem re/spec/protocol/login_char.json and map.json. Needs the Visual Studio Build Tools (C++).
rem login/char and map packets are dumped by separate programs: their headers share an include guard and define
rem some packets twice, so the servers never include both either.
setlocal
set HERE=%~dp0
set SRV=%HERE%..\..\..\server
set OUT=%HERE%..\..\spec\protocol
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if not exist "%HERE%out" mkdir "%HERE%out"
if not exist "%OUT%" mkdir "%OUT%"
set FLAGS=/nologo /std:c++17 /EHsc /W0 /D WIN32 /D FD_SETSIZE=4096 /D PCRE_SUPPORT /D _CRT_SECURE_NO_DEPRECATE ^
  /D _WINSOCK_DEPRECATED_NO_WARNINGS /D LIBCONFIG_STATIC ^
  /I "%SRV%\src" /I "%SRV%\3rdparty\rapidyaml\src" /I "%SRV%\3rdparty\rapidyaml\ext\c4core\src" ^
  /I "%SRV%\3rdparty\pcre\include" /I "%SRV%\3rdparty\libconfig" /I "%SRV%\3rdparty\mysql\include"
cl %FLAGS% "%HERE%dump_login_char.cpp" /Fe"%HERE%out\dump_login_char.exe" /Fo"%HERE%out\\" || exit /b 1
cl %FLAGS% "%HERE%dump_protocol.cpp" /Fe"%HERE%out\dump_protocol.exe" /Fo"%HERE%out\\" || exit /b 1
"%HERE%out\dump_login_char.exe" > "%OUT%\login_char.json" || exit /b 1
"%HERE%out\dump_protocol.exe" > "%OUT%\map.json" || exit /b 1
echo wrote re\spec\protocol\login_char.json and map.json
