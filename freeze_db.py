# 파일: sencity_backend/freeze_db.py
import sqlite3, os
SRC = r"db.sqlite3"           # 기존 운영 중 DB
DST = r"db_release.sqlite3"   # 배포용 스냅샷(이 파일을 Release에 올립니다)

if os.path.exists(DST):
    os.remove(DST)

# Django dev server 등 DB 사용하는 프로세스는 반드시 중지하고 실행
with sqlite3.connect(SRC) as s, sqlite3.connect(DST) as d:
    s.backup(d)   # 일관 스냅샷

print("OK: db_release.sqlite3 created.")
