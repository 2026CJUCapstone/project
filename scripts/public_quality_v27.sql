\set ON_ERROR_STOP on

-- Exact, reversible production visibility cleanup for the v27 public-quality
-- release.  This script never deletes rows and aborts the whole transaction if
-- the production inventory is not the reviewed one.
BEGIN;

DO $quality$
DECLARE
    affected integer;
BEGIN
    UPDATE users
    SET public_profile_enabled = false
    WHERE (id, username) IN (
        ('87b30815-2251-41aa-a330-d3260e4b40d9', 'debug_1781525547367'),
        ('0a3724f1-822c-4eba-b674-3e1aa0989795', 'report_1780557723153'),
        ('289f74f2-a4ca-412b-8d57-4ea043d9fc71', 'report_1780557931902'),
        ('782c6435-46f7-4581-810c-88bda2d1483b', 'report_1780558052106'),
        ('e4e5e3a6-247a-4671-aedd-07731496cdff', 'test123'),
        ('4c9178fb-2728-47b6-a30b-83265e45e5ff', 'testtok_1780557741'),
        ('7fa940a7-33ee-48c8-9c49-5ad171cdf38c', 'ui_1781525911721')
    );
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 7 THEN
        RAISE EXCEPTION 'reviewed test-account inventory changed: % rows', affected;
    END IF;

    UPDATE contests
    SET published = false
    WHERE (id, title) IN (
        ('436e5826-b411-4ecb-a960-d1b3a54b2db9', 'B++ 입문 콘테스트 · 운영 예시'),
        ('d1eef831-4729-4dbb-83d3-8c1178a722fd', '채점·종료 동작 확인 · 운영 검증')
    );
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 2 THEN
        RAISE EXCEPTION 'reviewed validation-contest inventory changed: % rows', affected;
    END IF;

    UPDATE problems
    SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP)
    WHERE (id, title) IN (
        ('5aec67d0-ce85-4378-b299-d24ed3cc8fd2', '두 수의 합'),
        ('da83f02e-639f-4c0c-8bf2-00b813052dda', '짝수와 홀수'),
        ('9ec2f010-c970-487f-ba82-dee241db8d05', '가장 큰 수'),
        ('2172fd0d-bf11-485f-9a95-61f4a1ca3a83', '42 출력하기 · 채점 확인')
    );
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 4 THEN
        RAISE EXCEPTION 'reviewed validation-problem inventory changed: % rows', affected;
    END IF;

    UPDATE problems AS p
    SET difficulty = v.difficulty,
        tags = v.tags_json::json
    FROM (VALUES
        ('40a68f20-722e-4650-a905-7c040232638b', 'Hello, World!', 'iron5', '["io"]'),
        ('ad6dce58-b3f8-444f-af0d-f2603ac1d5c1', '두 수의 합', 'iron4', '["io","math"]'),
        ('348d9cd2-060f-4ced-9389-b298c7ff629c', '두 수의 차', 'iron4', '["io","math"]'),
        ('c61692e0-3bc8-41da-8c12-2131b7c16547', '두 수의 곱', 'iron4', '["io","math"]'),
        ('21821020-37e6-46b5-bed7-4ab7e27bfdd7', '몫과 나머지', 'iron3', '["io","math"]'),
        ('c690a6bb-0f33-47ff-ab88-ecf1c9476a99', '짝수와 홀수', 'iron3', '["control","math"]'),
        ('4df9cdde-a592-40ad-bfed-6854285334f1', '세 수의 최댓값', 'iron2', '["control"]'),
        ('e1b0ad63-a937-4ef5-990b-479768dcb01c', '구구단 출력', 'bronze5', '["loop","control"]'),
        ('03ba45ea-6832-4616-998e-72a5e2ab2e6f', '1부터 N까지의 합', 'bronze5', '["loop","math"]'),
        ('9c44864e-f654-4604-803f-a11d35cf40de', '윤년 판별', 'bronze4', '["condition","math"]'),
        ('8bbcc3d5-0285-496e-9c81-09e0524cf8cd', '팩토리얼', 'bronze4', '["func","loop","math"]'),
        ('60bd73b8-5c6b-459f-b0ce-a498c55a5738', '피보나치 수열', 'silver5', '["func","loop","dp"]'),
        ('6bef44e6-3928-4c48-825b-a606d6b38508', '소수 판별', 'silver5', '["func","math"]'),
        ('94a48527-88e2-4ad6-8a84-2e61a22716c9', '약수의 개수', 'bronze2', '["loop","math"]'),
        ('2bc4f9fb-acdd-4e10-9bd5-9168c15d71d9', '문자열 뒤집기', 'bronze5', '["string","array"]'),
        ('8738e965-57d6-481e-9f33-a71da41f383b', '문자열 길이', 'iron3', '["string","array"]'),
        ('bfbdff67-8891-4961-81b0-3e2bfd384099', '모음 개수', 'bronze5', '["string","array"]'),
        ('e85364bb-c783-4c76-8cb4-22d621f219e3', '회문 판별', 'bronze3', '["string","array"]'),
        ('d560d1ea-e63a-4016-9e5c-61f250235281', '최대공약수와 최소공배수', 'silver5', '["func","math"]'),
        ('cb16908a-e2df-40c4-92bf-6b307e7b1f90', '약수의 합', 'silver4', '["func","loop","math"]')
    ) AS v(id, title, difficulty, tags_json)
    WHERE p.id = v.id AND p.title = v.title;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 20 THEN
        RAISE EXCEPTION 'reviewed public-problem inventory changed: % rows', affected;
    END IF;

    UPDATE comments
    SET content = replace(content, '챌린지', '문제')
    WHERE id = 'system-community-guide-v1'
      AND problem_id = '__notice__';
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'community guide notice inventory changed: % rows', affected;
    END IF;
END
$quality$;

COMMIT;
