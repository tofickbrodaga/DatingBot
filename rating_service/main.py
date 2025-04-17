
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
ratings = {}

class RatingInput(BaseModel):
    user_id: str
    profile_completeness: float  # 0–1
    photos_count: int
    preferred_city: str
    preferred_gender: str

@app.post("/rate")
def rate(data: RatingInput):
    score = 0
    score += data.profile_completeness * 5
    score += min(data.photos_count, 5) * 1
    score += 2  # предпочтения
    ratings[data.user_id] = score
    return {"user_id": data.user_id, "score": score}

@app.get("/score/{user_id}")
def get_score(user_id: str):
    return {"user_id": user_id, "score": ratings.get(user_id, 0)}
