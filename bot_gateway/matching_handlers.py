import os
import logging
import aiohttp
import tempfile
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.enums import ParseMode
from config import r, minio_client, BUCKET_NAME
from keyboards.match import like_dislike_kb
from keyboards.liked_back import liked_back_kb

logger = logging.getLogger(__name__)
bot = Bot(token=os.getenv("TELEGRAM_TOKEN", "fake"), parse_mode=ParseMode.HTML)

def get_router(minio_client, bucket_name):
    router = Router()

    @router.message(F.text == "💘 Начать поиск")
    async def show_match(message: Message):
        user_id = message.from_user.id

        # Если пользователь никого не лайкал, но его лайкали
        user_votes = r.hkeys(f"votes:{user_id}")
        liked_by = r.lrange(f"liked_by:{user_id}", 0, -1)

        if not user_votes and liked_by:
            await message.answer(
                f"Вашу анкету лайкнули {len(liked_by)} человек(а). Хотите посмотреть?",
                reply_markup=liked_back_kb()
            )
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://matchmaking_service:8000/match?user_id={user_id}") as resp:
                profiles = await resp.json()

        if not profiles:
            if liked_by:
                await message.answer(
                    f"Вашу анкету лайкнули {len(liked_by)} человек(а). Хотите посмотреть?",
                    reply_markup=liked_back_kb()
                )
            else:
                await message.answer("Нет новых анкет 😔")
            return

        profile = profiles[0]
        text = f"<b>{profile['name']}, {profile['age']}</b>\n📍 {profile['city']}"

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

            # Проверка на взаимный лайк
            if r.hget(f"votes:{liked_user_id}", str(user_id)) == "like":
                # Мэтч!
                contact = f"ID: {liked_user_id}"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"http://user_service:8000/profile/{liked_user_id}") as resp:
                            if resp.status == 200:
                                profile = await resp.json()
                                username = profile.get("username")
                                if username:
                                    contact = f"https://t.me/{username}"
                except Exception:
                    pass

                sender_contact = f"https://t.me/{callback.from_user.username}" if callback.from_user.username else f"ID: {user_id}"

                await bot.send_message(
                    user_id,
                    f"🎉 У вас мэтч с пользователем!\nСвяжитесь: {contact}"
                )
                await bot.send_message(
                    liked_user_id,
                    f"🎉 У вас мэтч с пользователем!\nСвяжитесь: {sender_contact}"
                )

        await callback.answer("👍 Голос учтён")
        await callback.message.delete()

    @router.callback_query(F.data == "view_likers")
    async def handle_view_likers(callback: CallbackQuery):
        user_id = callback.from_user.id
        liked_by = r.lrange(f"liked_by:{user_id}", 0, -1)

        if not liked_by:
            await callback.message.edit_text("На данный момент вас никто не лайкал.")
            return

        next_user_id = liked_by.pop(0)
        r.ltrim(f"liked_by:{user_id}", 1, -1)

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://user_service:8000/profile/{next_user_id}") as resp:
                if resp.status != 200:
                    await callback.message.edit_text("❌ Не удалось загрузить анкету.")
                    return
                profile = await resp.json()

        photo_url = profile["photos"][0]
        object_name = photo_url.rsplit("/", 1)[-1]
        resp = minio_client.get_object(bucket_name, object_name)
        content = resp.read()
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        photo_file = FSInputFile(tmp_path)

        text = f"<b>{profile['name']}, {profile['age']}</b>\n📍 {profile['city']}"
        msg = await callback.message.answer_photo(photo_file, caption=text, parse_mode="HTML", reply_markup=like_dislike_kb())
        r.set(f"match_message:{msg.message_id}", next_user_id)
        await callback.message.delete()

    @router.callback_query(F.data == "ignore_likers")
    async def handle_ignore_likers(callback: CallbackQuery):
        await callback.message.edit_text("Хорошо, продолжим позже 👌")

    return router
