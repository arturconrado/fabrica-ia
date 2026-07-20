def reward_from_rating(rating: int) -> float:
    return max(-1.0, min(1.0, float(rating)))
