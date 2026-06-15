from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.bootstrap import SYSTEM_BOARD_IDS
from app.models import database as db_models
from app.services.redis_client import cache_delete_pattern, cache_get_json, cache_set_json, redis_key


DIFFICULTY_LEVELS: tuple[str, ...] = (
    "iron5", "iron4", "iron3", "iron2", "iron1",
    "bronze5", "bronze4", "bronze3", "bronze2", "bronze1",
    "silver5", "silver4", "silver3", "silver2", "silver1",
    "gold5", "gold4", "gold3", "gold2", "gold1",
    "platinum5", "platinum4", "platinum3", "platinum2", "platinum1",
    "diamond5", "diamond4", "diamond3", "diamond2", "diamond1",
)

DIFFICULTY_VALUES: dict[str, int] = {
    difficulty: index + 1 for index, difficulty in enumerate(DIFFICULTY_LEVELS)
}

TIER_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (3000, "Master"),
    (2950, "Diamond I"),
    (2900, "Diamond II"),
    (2850, "Diamond III"),
    (2800, "Diamond IV"),
    (2700, "Diamond V"),
    (2600, "Platinum I"),
    (2500, "Platinum II"),
    (2400, "Platinum III"),
    (2300, "Platinum IV"),
    (2200, "Platinum V"),
    (2100, "Gold I"),
    (1900, "Gold II"),
    (1800, "Gold III"),
    (1700, "Gold IV"),
    (1600, "Gold V"),
    (1400, "Silver I"),
    (1250, "Silver II"),
    (1100, "Silver III"),
    (950, "Silver IV"),
    (800, "Silver V"),
    (650, "Bronze I"),
    (500, "Bronze II"),
    (400, "Bronze III"),
    (300, "Bronze IV"),
    (200, "Bronze V"),
    (150, "Iron I"),
    (120, "Iron II"),
    (90, "Iron III"),
    (60, "Iron IV"),
    (30, "Iron V"),
    (0, "Unrated"),
)


@dataclass(frozen=True)
class RatingStats:
    rating: int
    tier: str
    solved_count: int
    difficulty_score: int
    solved_bonus: int

    def to_cache_dict(self) -> dict:
        return {
            "rating": self.rating,
            "tier": self.tier,
            "solved_count": self.solved_count,
            "difficulty_score": self.difficulty_score,
            "solved_bonus": self.solved_bonus,
        }

    @classmethod
    def from_cache_dict(cls, value: dict) -> "RatingStats":
        return cls(
            rating=int(value.get("rating", 0)),
            tier=str(value.get("tier", "Unrated")),
            solved_count=int(value.get("solved_count", 0)),
            difficulty_score=int(value.get("difficulty_score", 0)),
            solved_bonus=int(value.get("solved_bonus", 0)),
        )


@dataclass(frozen=True)
class TagProficiency:
    tag: str
    solved_count: int
    difficulty_score: int
    max_difficulty: str | None
    max_difficulty_value: int
    proficiency: int

    def to_cache_dict(self) -> dict:
        return {
            "tag": self.tag,
            "solved_count": self.solved_count,
            "difficulty_score": self.difficulty_score,
            "max_difficulty": self.max_difficulty,
            "max_difficulty_value": self.max_difficulty_value,
            "proficiency": self.proficiency,
        }

    @classmethod
    def from_cache_dict(cls, value: dict) -> "TagProficiency":
        return cls(
            tag=str(value.get("tag", "")),
            solved_count=int(value.get("solved_count", 0)),
            difficulty_score=int(value.get("difficulty_score", 0)),
            max_difficulty=value.get("max_difficulty"),
            max_difficulty_value=int(value.get("max_difficulty_value", 0)),
            proficiency=int(value.get("proficiency", 0)),
        )


def round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def difficulty_value(difficulty: str) -> int:
    return DIFFICULTY_VALUES.get(difficulty, 0)


def solved_count_bonus(solved_count: int) -> int:
    if solved_count <= 0:
        return 0
    return round_half_up(200 * (1 - (0.997 ** solved_count)))


def tier_for_rating(rating: int) -> str:
    for threshold, tier in TIER_THRESHOLDS:
        if rating >= threshold:
            return tier
    return "Unrated"


def calculate_rating_stats(difficulties: Iterable[str]) -> RatingStats:
    values = [difficulty_value(difficulty) for difficulty in difficulties]
    values = [value for value in values if value > 0]
    values.sort(reverse=True)
    solved_count = len(values)
    difficulty_score = sum(values[:100])
    solved_bonus = solved_count_bonus(solved_count)
    rating = difficulty_score + solved_bonus
    return RatingStats(
        rating=rating,
        tier=tier_for_rating(rating),
        solved_count=solved_count,
        difficulty_score=difficulty_score,
        solved_bonus=solved_bonus,
    )


def rating_stats_for_users(db: Session, user_ids: Iterable[str]) -> dict[str, RatingStats]:
    user_id_list = list(dict.fromkeys(user_ids))
    if not user_id_list:
        return {}

    cached: dict[str, RatingStats] = {}
    missing_user_ids: list[str] = []
    for user_id in user_id_list:
        cached_value = cache_get_json(_rating_cache_key(user_id))
        if isinstance(cached_value, dict):
            cached[user_id] = RatingStats.from_cache_dict(cached_value)
        else:
            missing_user_ids.append(user_id)

    if not missing_user_ids:
        return cached

    rows = (
        db.query(db_models.UserProblemScore.user_id, db_models.Problem.difficulty)
        .join(db_models.Problem, db_models.Problem.id == db_models.UserProblemScore.challenge_id)
        .filter(
            db_models.UserProblemScore.user_id.in_(missing_user_ids),
            ~db_models.Problem.id.in_(SYSTEM_BOARD_IDS),
        )
        .all()
    )

    difficulties_by_user: dict[str, list[str]] = {user_id: [] for user_id in missing_user_ids}
    for user_id, difficulty in rows:
        difficulties_by_user.setdefault(user_id, []).append(difficulty)

    computed = {
        user_id: calculate_rating_stats(difficulties)
        for user_id, difficulties in difficulties_by_user.items()
    }
    for user_id, stats in computed.items():
        cache_set_json(_rating_cache_key(user_id), stats.to_cache_dict())

    return {**cached, **computed}


def rating_stats_for_user(db: Session, user_id: str) -> RatingStats:
    return rating_stats_for_users(db, [user_id]).get(user_id, calculate_rating_stats([]))


def tag_proficiencies_for_user(db: Session, user_id: str, limit: int = 8) -> list[TagProficiency]:
    normalized_limit = max(1, min(limit, 20))
    cached_value = cache_get_json(_tag_proficiency_cache_key(user_id, normalized_limit))
    if isinstance(cached_value, list):
        return [
            TagProficiency.from_cache_dict(item)
            for item in cached_value
            if isinstance(item, dict)
        ]

    rows = (
        db.query(db_models.Problem.tags, db_models.Problem.difficulty)
        .join(db_models.UserProblemScore, db_models.UserProblemScore.challenge_id == db_models.Problem.id)
        .filter(
            db_models.UserProblemScore.user_id == user_id,
            ~db_models.Problem.id.in_(SYSTEM_BOARD_IDS),
        )
        .all()
    )

    buckets: dict[str, dict] = {}
    for tags, difficulty in rows:
        value = difficulty_value(difficulty)
        if value <= 0 or not isinstance(tags, list):
            continue

        seen_in_problem: set[str] = set()
        for raw_tag in tags:
            tag = str(raw_tag).strip().lower()
            if not tag or tag in seen_in_problem:
                continue
            seen_in_problem.add(tag)

            bucket = buckets.setdefault(
                tag,
                {
                    "tag": tag,
                    "solved_count": 0,
                    "difficulty_score": 0,
                    "max_difficulty": None,
                    "max_difficulty_value": 0,
                },
            )
            bucket["solved_count"] += 1
            bucket["difficulty_score"] += value
            if value > bucket["max_difficulty_value"]:
                bucket["max_difficulty"] = difficulty
                bucket["max_difficulty_value"] = value

    ordered = sorted(
        buckets.values(),
        key=lambda item: (
            -int(item["difficulty_score"]),
            -int(item["solved_count"]),
            str(item["tag"]),
        ),
    )[:normalized_limit]
    max_score = int(ordered[0]["difficulty_score"]) if ordered else 0
    result = [
        TagProficiency(
            tag=str(item["tag"]),
            solved_count=int(item["solved_count"]),
            difficulty_score=int(item["difficulty_score"]),
            max_difficulty=item["max_difficulty"],
            max_difficulty_value=int(item["max_difficulty_value"]),
            proficiency=round_half_up((int(item["difficulty_score"]) / max_score) * 100) if max_score else 0,
        )
        for item in ordered
    ]
    cache_set_json(_tag_proficiency_cache_key(user_id, normalized_limit), [item.to_cache_dict() for item in result])
    return result


def invalidate_rating_cache(user_id: str | None = None) -> None:
    if user_id:
        cache_delete_pattern(_rating_cache_key(user_id))
        cache_delete_pattern(redis_key("rating", "tags", "user", user_id, "*"))
    else:
        cache_delete_pattern(redis_key("rating", "user", "*"))
        cache_delete_pattern(redis_key("rating", "tags", "user", "*"))
    cache_delete_pattern(redis_key("leaderboard", "*"))


def _rating_cache_key(user_id: str) -> str:
    return redis_key("rating", "user", user_id)


def _tag_proficiency_cache_key(user_id: str, limit: int) -> str:
    return redis_key("rating", "tags", "user", user_id, str(limit))
