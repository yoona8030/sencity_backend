-- insert_group_notices.sql
PRAGMA foreign_keys=OFF;
BEGIN;

INSERT INTO api_notification (type, user_id, admin_id, report_id, reply, status_change, created_at) VALUES
('group', NULL, NULL, NULL, 'SENCITY 앱이 업데이트되었어요!', NULL, datetime('now','localtime','+0 seconds')),
('group', NULL, NULL, NULL, '우천 시 로드킬 발생 주의 안내 감속 운전으로 함께 생명을 지켜주세요.', NULL, datetime('now','localtime','+2 seconds')),
('group', NULL, NULL, NULL, '적설 시 로드킬 사고 급증 야간이나 새벽 운행 시 저속 운전 부탁드립니다.', NULL, datetime('now','localtime','+4 seconds')),
('group', NULL, NULL, NULL, '안개로 시야 확보 어려움 주변 도로에 야생동물 주의 바랍니다.', NULL, datetime('now','localtime','+6 seconds')),
('group', NULL, NULL, NULL, '태풍 후 야생동물 이동 증가 도로 위 돌발 상황에 주의하세요.', NULL, datetime('now','localtime','+8 seconds')),
('group', NULL, NULL, NULL, '건조한 날씨로 산불 위험 증가 야생동물의 이동이 잦아질 수 있습니다.', NULL, datetime('now','localtime','+10 seconds')),
('group', NULL, NULL, NULL, '우박으로 인한 야생동물 이동 증가 야생동물의 이동이 잦아질 수 있습니다.', NULL, datetime('now','localtime','+12 seconds')),
('group', NULL, NULL, NULL, 'SENCITY 서비스 점검 안내 보다 나은 서비스 제공을 위해 점검 시간에는 일부 기능 이용이 제한될 수 있으니 양해 부탁드립니다.', NULL, datetime('now','localtime','+14 seconds')),
('group', NULL, NULL, NULL, '새로운 기능이 추가되었어요! 지금 앱을 열고 새로운 기능을 확인해보세요', NULL, datetime('now','localtime','+16 seconds')),
('group', NULL, NULL, NULL, 'SENCITY 캠페인 참여 안내 작은 관심이 생명을 살립니다지금 SENCITY와 함께 로 드킬 줄이기 캠페인에 참여해 보세요!', NULL, datetime('now','localtime','+18 seconds')),
('group', NULL, NULL, NULL, '위치정보 오류 수정 안내 불편을 드려 죄송합니다. 앞으로 더 안정적인 서비스를 제공하겠습니다.', NULL, datetime('now','localtime','+20 seconds')),
('group', NULL, NULL, NULL, '보안 강화/정책 변경 안내 비밀번호는 주기적으로 변경해 주세요.', NULL, datetime('now','localtime','+22 seconds')),
('group', NULL, NULL, NULL, '앱 버전 지원 중단 안내 원활한 이용을 위해 최신 버전으로 업데이트해 주세요.', NULL, datetime('now','localtime','+24 seconds')),
('group', NULL, NULL, NULL, '일시적 장애/복구 안내 불편을 드려 죄송합니다. 더 안정적인 서비스를 위해 노력하겠습니다.', NULL, datetime('now','localtime','+26 seconds')),
('group', NULL, NULL, NULL, '최근 산책로 인근 야생동물 출현 주변 야생동물 주의 바랍니다.', NULL, datetime('now','localtime','+28 seconds')),
('group', NULL, NULL, NULL, '야생동물 번식기에는 공격성이 증가합니다 새끼를 발견해도 가까이 다가가지 마세요.', NULL, datetime('now','localtime','+30 seconds')),
('group', NULL, NULL, NULL, '최근 산불 영향으로 야생동물 이동이 증가 중입니다 산행 중 마주칠 경우 천천히 거리 유지하세요.', NULL, datetime('now','localtime','+32 seconds')),
('group', NULL, NULL, NULL, '최근 멧돼지 출몰 신고 다수 발생 산행 시 마주칠 경우 등을 보이지 말고 천천히 이동하세요.', NULL, datetime('now','localtime','+34 seconds')),
('group', NULL, NULL, NULL, '산길 인근 먹이 활동이 활발하므로 음식물 쓰레기 방치 금지 및 주변 환경 보호에 협조 바랍니다.', NULL, datetime('now','localtime','+36 seconds')),
('group', NULL, NULL, NULL, '산길 낙석 및 미끄럼 주의 위험 구간에서는 주변을 잘 살피고 조심하세요.', NULL, datetime('now','localtime','+38 seconds'));

COMMIT;
