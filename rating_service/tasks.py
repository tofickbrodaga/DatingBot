from celery import shared_task

@shared_task(name="calculate_rating")
def calculate_rating(profile):
    rating = 0

    if profile.get("photos"):
        rating += len(profile["photos"]) * 10

    if profile.get("interests"):
        rating += min(len(profile["interests"]), 5) * 5

    if profile.get("city"):
        rating += 5

    return {"rating": min(rating, 100)}
