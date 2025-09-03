-- reload_notifications_reset_ids.sql
PRAGMA foreign_keys=OFF;
BEGIN;

-- 0) 전체 비우기(그룹 포함) + PK 시퀀스 리셋 → 다음 INSERT가 id=1부터 시작
DELETE FROM api_notification;
DELETE FROM sqlite_sequence WHERE name='api_notification';

-- 1) Report 원상태가 completed인 건 제외하고, 1번부터 순서대로 생성
--    checking : 홀수 report_id → checking->on_hold,  짝수 → checking->completed
--    on_hold  : on_hold->completed
--    completed: 제외
--    created_at: report_date + (3|4|5)일 순환
INSERT INTO api_notification (type, user_id, admin_id, report_id, reply, status_change, created_at)
SELECT
  'individual' AS type,
  r.user_id,
  a.id AS admin_id,                         -- Feedback.admin(User) -> Admin 매핑 (없으면 NULL)
  r.id AS report_id,
  NULLIF(TRIM(f.content), '') AS reply,     -- 피드백 내용(없으면 NULL)
  CASE
    WHEN r.status='checking' AND (r.id % 2)=1 THEN 'checking->on_hold'
    WHEN r.status='checking' AND (r.id % 2)=0 THEN 'checking->completed'
    WHEN r.status='on_hold'                  THEN 'on_hold->completed'
    ELSE NULL
  END AS status_change,
  datetime(r.report_date, printf('+%d days', ((r.id - 1) % 3) + 3)) AS created_at
FROM api_report   AS r
LEFT JOIN api_feedback AS f ON f.report_id = r.id
LEFT JOIN api_user     AS au ON au.id = f.admin_id
LEFT JOIN api_admin    AS a  ON a.user_id = au.id
WHERE r.status IN ('checking','on_hold')   -- ★ completed 제외
ORDER BY r.id;                             -- ★ 1번부터 순서대로 INSERT

COMMIT;
