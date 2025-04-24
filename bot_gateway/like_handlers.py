from aiogram import Router, F
from aiogram.types import Message, FSInputFile, CallbackQuery
from aiogram.enums import ParseMode
from keyboards.match import like_dislike_kb
from config import r, minio_client, BUCKET_NAME
import aiohttp
import tempfile
import logging
import os

logger = logging.getLogger(__name__)
router = Router()

def get_like_router():
    return router

@router.message(F.text == "💘 Начать поиск")
async def show_match(message: Message):
    user_id = message.from_user.id
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://matchmaking_service:8000/match?user_id={user_id}") as resp:
            profiles = await resp.json()

    if not profiles:
        liked_by = r.lrange(f"liked_by:{user_id}", 0, -1)
        if liked_by:
            await message.answer(f"Вашу анкету лайкнули {len(liked_by)} человек(а). Хотите посмотреть?")
        else:
            await message.answer("Нет новых анкет 😔")
        return

    profile = profiles[0]
    text = (
        f"<b>{profile['name']}, {profile['age']}</b>\n"
        f"📍 {profile['city']}"
    )

    photo_url = profile["photos"][0]
    object_name = photo_url.rsplit("/", 1)[-1]
    response = minio_client.get_object(BUCKET_NAME, object_name)
    content = response.read()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    photo_file = FSInputFile(tmp_path)
    msg = await message.answer_photo(
        photo_file,
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=like_dislike_kb()
    )

    r.set(f"match_message:{msg.message_id}", profile["user_id"])


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
            # Мэтч найден
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://user_service:8000/profile/{liked_user_id}") as resp1:
                    target_profile = await resp1.json() if resp1.status == 200 else {}

                async with session.get(f"http://user_service:8000/profile/{user_id}") as resp2:
                    source_profile = await resp2.json() if resp2.status == 200 else {}

            target_link = (
                f"https://t.me/{target_profile['username']}" if target_profile.get("username")
                else f"https://t.me/user?id={liked_user_id}"
            )
            source_link = (
                f"https://t.me/{source_profile['username']}" if source_profile.get("username")
                else f"https://t.me/user?id={user_id}"
            )

            await callback.message.answer("🎉 У вас мэтч!")
            await callback.bot.send_message(
                user_id,
                f"🎯 Вы понравились друг другу!\nСвяжитесь: {target_link}"
            )
            await callback.bot.send_message(
                liked_user_id,
                f"🎯 Вы понравились друг другу!\nСвяжитесь: {source_link}"
            )

    await callback.answer("👍 Голос учтён")
    await callback.message.delete()
