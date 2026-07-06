from app.models import LearningLesson, RewardSignal


def list_lessons(db):
    return db.query(LearningLesson).order_by(LearningLesson.created_at.desc()).all()


def list_reward_signals(db):
    return db.query(RewardSignal).order_by(RewardSignal.created_at.desc()).all()
