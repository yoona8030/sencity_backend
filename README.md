윈도우
:: 1) 레포 받기
git clone https://github.com/yoona8030/sencity_backend.git
cd sencity_backend

:: 2) (비공개 레포면 1회) GitHub 토큰 저장
::    개인 GitHub에서 발급한 fine-grained token 값으로 대체
setx GITHUB_TOKEN "github_pat_여기에_토큰"

:: 3) DB 자동 동기화 훅 설치
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_hooks.ps1

:: 4) 업데이트 받기(훅이 DB도 같이 최신화)
git pull

:: 5) (선택) 수동 동기화
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_db.ps1

맥
 1) 레포 받기
git clone https://github.com/yoona8030/sencity_backend.git
cd sencity_backend

 2) (비공개 레포면 1회) GitHub 토큰 저장(zsh)
echo 'export GITHUB_TOKEN="github_pat_여기에_토큰"' >> ~/.zshrc
source ~/.zshrc

 3) PowerShell 7 설치(처음 1회)
brew install --cask powershell   # 없으면 설치
pwsh -v                          # 버전 확인

 4) DB 자동 동기화 훅 설치
pwsh -NoProfile -File ./scripts/install_hooks.ps1

 5) 업데이트 받기(훅이 DB도 같이 최신화)
git pull

 6) (선택) 수동 동기화
pwsh -NoProfile -File ./scripts/sync_db.ps1

* db.sqlite3를 커밋/푸시 금지 (git에서 무시됨)
* Releases의 db_release.sqlite3/db_release.sha256.txt를 임의 수정 금지
* 훅 스크립트 수정 금지(문제 땐 다시 설치만) -> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_hooks.ps1

401, 404 오류 시 말씀해주세용...
