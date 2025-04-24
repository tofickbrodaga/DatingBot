from fastapi import FastAPI, Request
from tasks import calculate_rating
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
async def rate(request: Request):
    profile = await request.json()
    task = calculate_rating.delay(profile)
    return {"task_id": task.id}
