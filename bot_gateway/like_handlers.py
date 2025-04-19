from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from config import r
import os

router = Router()
bot = Bot(token=os.getenv("TELEGRAM_TOKEN", "fake"))

@router.callback_query(F.data.in_({"like", "dislike"}))
async def handle_vote(callback: CallbackQuery):
    user_id = callback.from_user.id
    caption = callback.message.caption

    if not caption or "user_id=" not in caption:
        await callback.answer("❌ Ошибка: не найден ID пользователя")
        return

    target_user_id = caption.split("user_id=")[-1]
    vote = callback.data

    r.hset(f"votes:{user_id}", target_user_id, vote)

    if vote == "like":
        r.rpush(f"liked_by:{target_user_id}", user_id)

        if r.hget(f"votes:{target_user_id}", str(user_id)) == "like":
            await bot.send_message(
                user_id,
                f"🎉 У вас мэтч с пользователем {target_user_id}!\n"
                f"Напишите ему: https://t.me/user?id={target_user_id}"
            )
            await bot.send_message(
                target_user_id,
                f"🎉 У вас мэтч с пользователем {user_id}!\n"
                f"Напишите ему: https://t.me/user?id={user_id}"
            )

    await callback.answer("👍 Голос учтён")
    await callback.message.delete()
