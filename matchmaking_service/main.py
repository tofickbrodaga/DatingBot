from fastapi import FastAPI
from matcher import find_matches

app = FastAPI()

@app.get("/match")
def match(user_id: int):
    return find_matches(user_id)
