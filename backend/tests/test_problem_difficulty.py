"""Problem-difficulty boundaries and ordinal compatibility."""

import pytest
from pydantic import ValidationError

from app.api.routes.problems import PROBLEM_DIFFICULTIES
from app.models.schemas import ProblemCreate
from app.services.learning import DIFFICULTIES
from app.services.rating import DIFFICULTY_LEVELS, DIFFICULTY_VALUES, calculate_rating_stats


LEGACY_DIFFICULTIES = (
    "iron5", "iron4", "iron3", "iron2", "iron1",
    "bronze5", "bronze4", "bronze3", "bronze2", "bronze1",
    "silver5", "silver4", "silver3", "silver2", "silver1",
    "gold5", "gold4", "gold3", "gold2", "gold1",
    "platinum5", "platinum4", "platinum3", "platinum2", "platinum1",
    "diamond5", "diamond4", "diamond3", "diamond2", "diamond1",
)
RUBY_DIFFICULTIES = ("ruby5", "ruby4", "ruby3", "ruby2", "ruby1")


def test_problem_difficulty_lists_append_ruby_without_moving_existing_ordinals():
    expected = LEGACY_DIFFICULTIES + RUBY_DIFFICULTIES

    assert DIFFICULTY_LEVELS == expected
    assert tuple(PROBLEM_DIFFICULTIES) == expected
    assert tuple(DIFFICULTIES) == expected
    assert tuple(DIFFICULTY_VALUES) == expected
    assert tuple(DIFFICULTY_VALUES.values()) == tuple(range(1, len(expected) + 1))


def test_ruby_difficulties_validate_at_the_bounded_problem_api_schema_edge():
    for difficulty in RUBY_DIFFICULTIES:
        problem = ProblemCreate(title="Ruby boundary", difficulty=difficulty, description="test")
        assert problem.difficulty == difficulty

    for invalid in ("ruby6", "ruby0", "ruby", "Ruby1", "sapphire1"):
        with pytest.raises(ValidationError):
            ProblemCreate(title="Invalid boundary", difficulty=invalid, description="test")


def test_ruby_rating_values_follow_unchanged_legacy_values():
    legacy = calculate_rating_stats(["iron5", "gold3", "diamond1"])
    ruby = calculate_rating_stats(["ruby5", "ruby1"])

    assert legacy.difficulty_score == 1 + 18 + 30
    assert ruby.difficulty_score == 31 + 35
