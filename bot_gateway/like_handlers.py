from aiogram import Router, F
from aiogram.types import CallbackQuery
from config import r
from aiogram import Bot
from aiogram.enums import ParseMode
import os
import aiohttp
import logging

logger = logging.getLogger(__name__)
bot = Bot(token=os.getenv("TELEGRAM_TOKEN", "fake"), parse_mode=ParseMode.HTML)

like_router = Router()

@like_router.callback_query(F.data.in_({"like", "dislike"}))
async def handle_vote(callback: CallbackQuery):
    user_id = callback.from_user.id
    message_id = callback.message.message_id
    liked_user_id = r.get(f"match_message:{message_id}")

    if not liked_user_id:
        await callback.answer("❌ Не удалось определить анкету")
        return

    vote = callback.data
    key = f"votes:{user_id}"
    r.hset(key, liked_user_id, vote)

    if vote == "like":
        r.rpush(f"liked_by:{liked_user_id}", user_id)

        if r.hget(f"votes:{liked_user_id}", str(user_id)) == "like":
            # 🎯 Мэтч!
            async with aiohttp.ClientSession() as session:
                try:
                    resp = await session.get(f"http://user_service:8000/profile/{liked_user_id}")
                    data = await resp.json()
                    username = data.get("username")
                    if username:
                        contact = f"https://t.me/{username}"
                    else:
                        contact = f"https://t.me/user?id={liked_user_id}"
                except Exception as e:
                    logger.warning(f"Не удалось получить профиль: {e}")
                    contact = f"https://t.me/user?id={liked_user_id}"

            await bot.send_message(
                user_id,
                f"🎉 У вас мэтч с пользователем!\nСвяжитесь: {contact}"
            )
            await bot.send_message(
                liked_user_id,
                f"🎉 У вас мэтч с пользователем!\nСвяжитесь: https://t.me/{callback.from_user.username or f'user?id={user_id}'}"
            )

    await callback.answer("👍 Голос учтён")
    await callback.message.delete()
