import requests
import os
import redis

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user_service:8000")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def get_users(exclude_user_id):
    try:
        response = requests.get(f"{USER_SERVICE_URL}/users")
        if response.status_code != 200:
            return []
        users = response.json()
        return [u for u in users if str(u["user_id"]) != str(exclude_user_id)]
    except Exception as e:
        print("Ошибка получения пользователей:", e)
        return []

def find_matches(user_id):
    all_users = get_users(user_id)
    key = f"shown_user_ids:{user_id}"
    shown_ids = r.smembers(key)

    for user in all_users:
        if str(user["user_id"]) not in shown_ids:
            r.sadd(key, user["user_id"])
            return [user]

    return []
