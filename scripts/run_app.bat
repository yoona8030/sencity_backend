@echo off
cd /d C:\Users\a9349\sencity

echo [APP] Metro 서버 실행 창을 띄웁니다...
start cmd /k "cd /d C:\Users\a9349\sencity && npx react-native start"

REM 잠깐 기다렸다가 (원하면 5초)
timeout /t 5 >nul

echo [APP] Android 앱을 빌드 & 실행합니다...
npx react-native run-android

pause
