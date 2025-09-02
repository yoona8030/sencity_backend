백엔드에서 
git clone https://github.com/yoona8030/sencity_backend.git
cd sencity_backend

1. 최초 1회
깃 훅 설치
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_hooks.ps1

동작 확인
git pull
또는 
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_db.ps1
--> 성공 예: Sync done: ...\db.sqlite3 (tag=vYYYY.MM.DD)

2. 평소 업데이트
git pull

3. 수동 동기화가 필요할 깨
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_db.ps1

* db.sqlite3를 커밋/푸시 금지 (git에서 무시됨)
* Releases의 db_release.sqlite3/db_release.sha256.txt를 임의 수정 금지
* 훅 스크립트 수정 금지(문제 땐 다시 설치만) -> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_hooks.ps1

401, 404 오류 시 말씀해주세용...
