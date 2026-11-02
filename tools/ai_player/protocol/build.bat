@echo off
rem Compiles a dump tool against the rAthena headers with the map-server's settings.
rem Usage: build.bat <source.cpp> <output.exe>
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
set R=%~dp0..\..\..
cl /nologo /std:c++17 /EHsc /W0 /D WIN32 /D FD_SETSIZE=4096 /D PCRE_SUPPORT /D _CRT_SECURE_NO_DEPRECATE /D _WINSOCK_DEPRECATED_NO_WARNINGS /D LIBCONFIG_STATIC ^
  /I "%R%\src" /I "%R%\3rdparty\rapidyaml\src" /I "%R%\3rdparty\rapidyaml\ext\c4core\src" /I "%R%\3rdparty\pcre\include" /I "%R%\3rdparty\libconfig" /I "%R%\3rdparty\mysql\include" ^
  %1 /Fe%2 /Fo%TEMP%\
