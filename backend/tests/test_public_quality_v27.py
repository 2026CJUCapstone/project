"""Static safety contract for the reviewed, reversible production cleanup."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "public_quality_v27.sql"


def test_public_quality_cleanup_is_exact_reversible_and_transactional():
    source = SCRIPT.read_text(encoding="utf-8")
    normalized = source.upper()

    assert "\\SET ON_ERROR_STOP ON" in normalized
    assert "BEGIN;" in normalized and normalized.rstrip().endswith("COMMIT;")
    assert not re.search(r"\bDELETE\b|\bTRUNCATE\b|\bDROP\b", normalized)
    assert "PUBLIC_PROFILE_ENABLED = FALSE" in normalized
    assert "PUBLISHED = FALSE" in normalized
    assert "DELETED_AT = COALESCE(DELETED_AT, CURRENT_TIMESTAMP)" in normalized
    assert source.count("RAISE EXCEPTION") == 5
    assert source.count("GET DIAGNOSTICS affected = ROW_COUNT") == 5


def test_public_quality_cleanup_targets_only_reviewed_inventory():
    source = SCRIPT.read_text(encoding="utf-8")

    assert source.count("debug_1781525547367") == 1
    assert source.count("report_178055") == 3
    assert source.count("testtok_1780557741") == 1
    assert source.count("B++ 입문 콘테스트 · 운영 예시") == 1
    assert source.count("채점·종료 동작 확인 · 운영 검증") == 1
    assert "system-community-guide-v1" in source
    assert "replace(content, '챌린지', '문제')" in source
