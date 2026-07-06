def reward_from_rating(rating: int) -> float:
    return 1.0 if rating >= 0 else -1.0
