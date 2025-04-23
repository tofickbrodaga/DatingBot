from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List

app = FastAPI()

class Profile(BaseModel):
    name: str
    age: int
    gender: str
    interests: List[str] = []
    city: str
    photos: List[str]

@app.post("/rate")
async def rate(profile: Profile):
    score = 0
    score += min(len(profile.photos), 5)
    if profile.name:
        score += 1
    if profile.age:
        score += 1
    if profile.gender:
        score += 1
    if profile.city:
        score += 1
    if profile.interests:
        score += 1

    return {"rating": score}
