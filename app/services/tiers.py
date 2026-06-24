from typing import Literal

SubscriptionTier = Literal["free", "pro", "business"]

TIER_LIMITS: dict[SubscriptionTier, dict] = {
    "free": {
        "questions_per_month": 50,
        "tokens_per_month": 100_000,
        "allowed_formats": ["pdf"],
    },
    "pro": {
        "questions_per_month": 500,
        "tokens_per_week": 300_000,
        "allowed_formats": ["pdf", "docx"],
    },
    "business": {
        "questions_per_month": 1000,
        "tokens_per_week": 500_000,
        "allowed_formats": ["pdf", "doc", "docx"],
    },
}

VALID_TIERS: set[str] = set(TIER_LIMITS.keys())


def normalize_tier(tier: str | None) -> SubscriptionTier:
    if tier in VALID_TIERS:
        return tier  # type: ignore[return-value]
    return "free"


def get_tier_limits(tier: str | None) -> dict:
    return TIER_LIMITS[normalize_tier(tier)]


def is_format_allowed(tier: str | None, file_type: str) -> bool:
    limits = get_tier_limits(tier)
    return file_type.lower() in limits["allowed_formats"]
