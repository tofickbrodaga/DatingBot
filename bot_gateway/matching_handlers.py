from aiogram import Router, F, Bot
from aiogram.types import (
    Message, FSInputFile, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from keyboards.match import like_dislike_kb
import aiohttp
import tempfile
from config import r
import os
from io import BytesIO
import logging

logger = logging.getLogger(__name__)
bot = Bot(token=os.getenv("TELEGRAM_TOKEN", "fake"), parse_mode=ParseMode.HTML)

def get_router(minio_client, bucket_name):
    router = Router()

    @router.message(F.text == "💘 Начать поиск")
    async def show_match(message: Message):
        user_id = message.from_user.id
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://matchmaking_service:8000/match?user_id={user_id}") as resp:
                profiles = await resp.json() if resp.status == 200 else []

        if not profiles:
            liked_by = r.lrange(f"liked_by:{user_id}", 0, -1)
            if liked_by:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Да", callback_data="show_likes")],
                        [InlineKeyboardButton(text="Нет", callback_data="cancel_likes")]
                    ]
                )
                await message.answer(
                    f"💌 Вашу анкету лайкнули {len(liked_by)} человек(а). Хотите посмотреть?",
                    reply_markup=kb
                )
            else:
                await message.answer("Нет новых анкет 😔")
            return

        await send_profile(message, profiles[0], minio_client, bucket_name)

    async def send_profile(message: Message, profile: dict, minio_client, bucket_name):
        text = (
            f"<b>{profile['name']}, {profile['age']}</b>\n"
            f"📍 {profile['city']}"
        )
        try:
            photo_url = profile["photos"][0]
            object_name = photo_url.rsplit("/", 1)[-1]
            resp = minio_client.get_object(bucket_name, object_name)
            content = resp.read()
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            photo_file = FSInputFile(tmp_path)

            msg = await message.answer_photo(
                photo_file,
                caption=text,
                parse_mode="HTML",
                reply_markup=like_dislike_kb()
            )
            r.set(f"match_message:{msg.message_id}", profile["user_id"])
        except Exception as e:
            logger.exception("❌ Не удалось загрузить фото анкеты")
            await message.answer("❌ Не удалось загрузить фото")

    @router.callback_query(F.data == "show_likes")
    async def show_likes(callback: CallbackQuery):
        user_id = callback.from_user.id
        liked_by = r.lrange(f"liked_by:{user_id}", 0, -1)
        if not liked_by:
            await callback.message.answer("😔 Пока никто вас не лайкнул.")
            return

        r.delete(f"likes_to_review:{user_id}")
        for uid in liked_by:
            r.rpush(f"likes_to_review:{user_id}", uid)
        next_id = r.lpop(f"likes_to_review:{user_id}")
        if next_id:
            await show_liked_profile(callback.message, next_id, user_id)
        await callback.answer()

    async def show_liked_profile(message: Message, target_id: str, viewer_id: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://user_service:8000/profile/{target_id}") as resp:
                if resp.status != 200:
                    await message.answer("❌ Не удалось загрузить анкету")
                    return
                profile = await resp.json()

        text = (
            f"<b>{profile['name']}, {profile['age']}</b>\n"
            f"📍 {profile['city']}"
        )

        try:
            photo_url = profile["photos"][0]
            object_name = photo_url.rsplit("/", 1)[-1]
            resp = minio_client.get_object(bucket_name, object_name)
            content = resp.read()
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            photo_file = FSInputFile(tmp_path)

            msg = await message.answer_photo(
                photo_file,
                caption=text,
                parse_mode="HTML",
                reply_markup=like_dislike_kb()
            )
            r.set(f"match_message:{msg.message_id}", target_id)
        except Exception:
            await message.answer("❌ Ошибка при загрузке анкеты")

    @router.callback_query(F.data == "cancel_likes")
    async def cancel_likes(callback: CallbackQuery):
        await callback.message.answer("👌 Может позже 😉")
        await callback.answer()

    @router.callback_query(F.data.in_({"like", "dislike"}))
    async def handle_vote(callback: CallbackQuery):
        user_id = callback.from_user.id
        message_id = callback.message.message_id
        liked_user_id = r.get(f"match_message:{message_id}")

        if not liked_user_id:
            await callback.answer("❌ Не удалось определить анкету")
            return

        vote = callback.data
        r.hset(f"votes:{user_id}", liked_user_id, vote)

        if vote == "like":
            r.rpush(f"liked_by:{liked_user_id}", user_id)
            if r.hget(f"votes:{liked_user_id}", str(user_id)) == "like":
                # Мэтч!
                await notify_match(user_id, liked_user_id)

        await callback.answer("👍 Голос учтён")
        await callback.message.delete()

        next_liked = r.lpop(f"likes_to_review:{user_id}")
        if next_liked:
            await show_liked_profile(callback.message, next_liked, user_id)

    async def notify_match(uid1, uid2):
        try:
            async with aiohttp.ClientSession() as session:
                p1, p2 = {}, {}
                r1 = await session.get(f"http://user_service:8000/profile/{uid1}")
                r2 = await session.get(f"http://user_service:8000/profile/{uid2}")
                if r1.status == 200:
                    p1 = await r1.json()
                if r2.status == 200:
                    p2 = await r2.json()

            link1 = f"https://t.me/{p2.get('username')}" if p2.get("username") else f"ID: {uid2}"
            link2 = f"https://t.me/{p1.get('username')}" if p1.get("username") else f"ID: {uid1}"

            await bot.send_message(uid1, f"🎉 У вас мэтч! Свяжитесь: {link1}")
            await bot.send_message(uid2, f"🎉 У вас мэтч! Свяжитесь: {link2}")

        except Exception as e:
            logger.exception("Ошибка при отправке уведомления о мэтче")

    return router
