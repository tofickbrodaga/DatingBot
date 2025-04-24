from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

class Profile(BaseModel):
    user_id: str
    name: str
    age: int
    gender: str
    interests: Optional[List[str]]
    city: str
    photos: List[str]
    latitude: float
    longitude: float
    username: Optional[str] = None

@app.post("/rate")
async def rate(profile: Profile):
    score = 0

    photo_score = min(len(profile.photos) * 10, 30)
    score += photo_score

    fields = [profile.name, profile.age, profile.gender, profile.city, profile.latitude, profile.longitude]
    filled_fields = sum(bool(f) for f in fields)
    interests_filled = bool(profile.interests and any(i.strip() for i in profile.interests))

    field_score = (filled_fields + interests_filled) / 7 * 70
    score += field_score

    final_score = int(score)
    return {"rating": final_score}
