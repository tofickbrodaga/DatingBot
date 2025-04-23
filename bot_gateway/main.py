import os
import time
import asyncio
import logging
import aiohttp
import tempfile
from collections import defaultdict
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile, Message, InputMediaPhoto,
    KeyboardButton, ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import minio_client, BUCKET_NAME, MINIO_PUBLIC_URL, r
from matching_handlers import get_router as get_match_router
from like_handlers import get_like_router
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "fake")
bot = Bot(token=TELEGRAM_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

media_groups = defaultdict(list)

class ProfileFSM(StatesGroup):
    name = State()
    age = State()
    gender = State()
    interests = State()
    city_or_geo = State()
    city = State()
    photos = State()
    preview = State()

@router.message(Command("start"))
async def start_profile(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Как тебя зовут?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ProfileFSM.name)

@router.message(ProfileFSM.name)
async def handle_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Сколько тебе лет?")
    await state.set_state(ProfileFSM.age)

@router.message(ProfileFSM.age)
async def handle_age(message: Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👨 Мужской")], [KeyboardButton(text="👩 Женский")]],
        resize_keyboard=True
    )
    await message.answer("Выбери пол:", reply_markup=kb)
    await state.set_state(ProfileFSM.gender)

@router.message(ProfileFSM.gender)
async def handle_gender(message: Message, state: FSMContext):
    gender = "male" if "муж" in message.text.lower() else "female"
    await state.update_data(gender=gender)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")]],
        resize_keyboard=True
    )
    await message.answer("Напиши интересы через запятую или нажми 'Пропустить':", reply_markup=kb)
    await state.set_state(ProfileFSM.interests)

@router.message(ProfileFSM.interests)
async def handle_interests(message: Message, state: FSMContext):
    if message.text.lower() == "пропустить":
        interests = []
    else:
        interests = [i.strip() for i in message.text.split(",")]
    await state.update_data(interests=interests)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить координаты", request_location=True)],
            [KeyboardButton(text="🌍 Ввести город вручную")]
        ],
        resize_keyboard=True
    )
    await message.answer("Хочешь указать координаты или ввести город?", reply_markup=kb)
    await state.set_state(ProfileFSM.city_or_geo)

@router.message(ProfileFSM.city_or_geo, F.location)
async def handle_location(message: Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
    city = data.get("address", {}).get("city") or data.get("address", {}).get("town") or data.get("address", {}).get("village")
    if not city:
        await message.answer("Не удалось определить город. Введи его вручную.")
        await state.set_state(ProfileFSM.city)
        return
    await state.update_data(city=city, latitude=lat, longitude=lon)
    await message.answer("Отправь 1–3 фото профиля", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ProfileFSM.photos)

@router.message(ProfileFSM.city_or_geo, F.text)
async def ask_manual_city(message: Message, state: FSMContext):
    if message.text == "🌍 Ввести город вручную":
        await message.answer("Окей, введи свой город:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(ProfileFSM.city)
    else:
        await message.answer("Пожалуйста, нажмите кнопку или отправьте геолокацию.")

@router.message(ProfileFSM.city)
async def handle_manual_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text, latitude=55.75, longitude=37.61)
    await message.answer("Отправь 1–3 фото профиля")
    await state.set_state(ProfileFSM.photos)

@router.message(ProfileFSM.photos, F.photo)
async def handle_album_photos(message: Message, state: FSMContext):
    media_group_id = message.media_group_id
    user_id = message.from_user.id

    if media_group_id:
        media_groups[(user_id, media_group_id)].append(message.photo[-1].file_id)
        await asyncio.sleep(2.5)

        if len(media_groups[(user_id, media_group_id)]) >= 1:
            file_ids = media_groups.pop((user_id, media_group_id))
            photos = []

            for file_id in file_ids:
                tg_file = await bot.get_file(file_id)
                download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_file.file_path}"

                async with aiohttp.ClientSession() as session:
                    async with session.get(download_url) as resp:
                        content = await resp.read()

                object_name = f"{user_id}_{int(time.time() * 1000)}.jpg"
                minio_client.put_object(
                    bucket_name=BUCKET_NAME,
                    object_name=object_name,
                    data=BytesIO(content),
                    length=len(content),
                    content_type="image/jpeg"
                )
                photos.append(object_name)

            await state.update_data(photos=photos)
            await state.set_state(ProfileFSM.preview)
            await message.answer("Фото добавлены. Нажми '✅ Всё верно' или '🔄 Заполнить заново'.", reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="✅ Всё верно")], [KeyboardButton(text="🔄 Заполнить заново")]],
                resize_keyboard=True
            ))
    else:
        await message.answer("Пожалуйста, отправь все фото одновременно (альбомом).")

@router.message(ProfileFSM.preview, F.text)
async def handle_preview_response(message: Message, state: FSMContext):
    text = message.text.lower()
    if "верно" in text:
        data = await state.get_data()
        await show_preview(message, data)

        profile = {
            "user_id": str(message.from_user.id),
            "name": data['name'],
            "age": data['age'],
            "gender": data['gender'],
            "interests": data['interests'],
            "city": data['city'],
            "photos": [f"{MINIO_PUBLIC_URL}/{BUCKET_NAME}/{obj}" for obj in data['photos']],
            "latitude": data['latitude'],
            "longitude": data['longitude'],
            "username": message.from_user.username
        }

        async with aiohttp.ClientSession() as session:
            async with session.post("http://user_service:8000/profile", json=profile) as resp:
                await resp.text()
            try:
                async with session.post("http://rating_service:8000/rate", json=profile) as resp:
                    rating_data = await resp.json()
                    rating = rating_data.get("rating")
                    logger.info(f"✅ Рейтинг анкеты: {rating}")
            except Exception as e:
                logger.warning(f"❌ Не удалось получить рейтинг: {e}")

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📄 Мой профиль")],
                [KeyboardButton(text="💘 Начать поиск")]
            ],
            resize_keyboard=True
        )
        await message.answer("✅ Анкета успешно сохранена!", reply_markup=kb)
        await state.clear()

    elif "заново" in text:
        await state.clear()
        await start_profile(message, state)


async def show_preview(message: Message, data: dict):
    gender_icon = "👨" if data["gender"] == "male" else "👩"
    interests = ', '.join(data['interests']) if data['interests'] else '—'
    caption = (
        f"<b>Вот как выглядит анкета:</b>\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"{gender_icon} Пол: {'Мужской' if data['gender'] == 'male' else 'Женский'}\n"
        f"🎯 Интересы: {interests}\n"
        f"📍 Город: {data['city']}"
    )

    media = []
    for idx, object_name in enumerate(data['photos']):
        file = minio_client.get_object(BUCKET_NAME, object_name)
        content = file.read()
        file.close()
        file.release_conn()

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp_file.write(content)
        tmp_file.close()
        input_file = FSInputFile(tmp_file.name)

        if idx == 0:
            media.append(InputMediaPhoto(media=input_file, caption=caption, parse_mode=ParseMode.HTML))
        else:
            media.append(InputMediaPhoto(media=input_file))

    if len(media) > 1:
        await bot.send_media_group(chat_id=message.chat.id, media=media)
    else:
        await bot.send_photo(chat_id=message.chat.id, photo=media[0].media, caption=caption, parse_mode=ParseMode.HTML)

@router.message(F.text == "📄 Мой профиль")
@router.message(Command("myprofile"))
async def show_my_profile(message: Message):
    user_id = str(message.from_user.id)

    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://user_service:8000/profile/{user_id}") as resp:
            if resp.status != 200:
                await message.answer("❌ Анкета не найдена.")
                return
            data = await resp.json()

        try:
            async with session.get(f"http://rating_service:8000/rate/{user_id}") as resp:
                rating = (await resp.json()).get("rating", "—")
        except:
            rating = "—"

    gender_icon = "👨" if data["gender"] == "male" else "👩"
    interests = ', '.join(data["interests"]) if data["interests"] else "—"

    caption = (
        f"<b>Вот как выглядит анкета:</b>\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"{gender_icon} Пол: {'Мужской' if data['gender'] == 'male' else 'Женский'}\n"
        f"🎯 Интересы: {interests}\n"
        f"📍 Город: {data['city']}\n"
        f"⭐ Рейтинг: {rating}/100"
    )

    media = []
    for i, photo_url in enumerate(data['photos']):
        object_name = photo_url.rsplit("/", 1)[-1]
        file = minio_client.get_object(BUCKET_NAME, object_name)
        content = file.read()
        file.close()
        file.release_conn()

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.write(content)
        tmp_path = tmp.name
        tmp.close()

        file_input = FSInputFile(tmp_path)
        if i == 0:
            media.append(InputMediaPhoto(media=file_input, caption=caption, parse_mode=ParseMode.HTML))
        else:
            media.append(InputMediaPhoto(media=file_input))

    if len(media) > 1:
        await bot.send_media_group(chat_id=message.chat.id, media=media)
    else:
        await bot.send_photo(chat_id=message.chat.id, photo=media[0].media, caption=caption, parse_mode=ParseMode.HTML)


app = FastAPI()
dp.include_router(router)
dp.include_router(get_match_router(minio_client, BUCKET_NAME))
dp.include_router(get_like_router())

@app.on_event("startup")
async def on_startup():
    for key in r.scan_iter("shown_user_ids:*"):
        r.delete(key)
    for key in r.scan_iter("votes:*"):
        r.delete(key)
    for key in r.scan_iter("liked_by:*"):
        r.delete(key)
    print("🧹 Redis очищен")
    asyncio.create_task(dp.start_polling(bot))