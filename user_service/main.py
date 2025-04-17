
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI()

users = {}
profiles = {}

class ProfileCreate(BaseModel):
    user_id: str
    name: str
    age: int
    gender: str
    interests: List[str]
    city: str
    photos: List[str]
    latitude: float
    longitude: float

@app.post("/profile")
def create_profile(profile: ProfileCreate):
    profiles[profile.user_id] = profile.dict()
    return {"message": "Profile saved"}

@app.get("/profile/{user_id}")
def get_profile(user_id: str):
    profile = profiles.get(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile
