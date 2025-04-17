import os
import asyncio
import logging
import aiohttp
import tempfile
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile, Message,
    KeyboardButton, ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from minio import Minio
from io import BytesIO

event_loop = asyncio.get_event_loop()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "fake")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "user-photos")

bot = Bot(token=TELEGRAM_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

minio_client = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)
if not minio_client.bucket_exists(BUCKET_NAME):
    minio_client.make_bucket(BUCKET_NAME)

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
    await message.answer(
        "Как тебя зовут?", reply_markup=ReplyKeyboardRemove()
    )
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
        keyboard=[
            [KeyboardButton(text="👨 Мужской")],
            [KeyboardButton(text="👩 Женский")]
        ],
        resize_keyboard=True
    )
    await message.answer("Выбери пол:", reply_markup=kb)
    await state.set_state(ProfileFSM.gender)

@router.message(ProfileFSM.gender)
async def handle_gender(message: Message, state: FSMContext):
    gender = "male" if "муж" in message.text.lower() else "female"
    await state.update_data(gender=gender)
    await message.answer("Напиши интересы через запятую:")
    await state.set_state(ProfileFSM.interests)

@router.message(ProfileFSM.interests)
async def handle_interests(message: Message, state: FSMContext):
    interests = [i.strip() for i in message.text.split(",")]
    await state.update_data(interests=interests)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить координаты", request_location=True)],
            [KeyboardButton(text="🏙 Ввести город вручную")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "Хочешь указать координаты или ввести город?", reply_markup=kb
    )
    await state.set_state(ProfileFSM.city_or_geo)

@router.message(ProfileFSM.city_or_geo, F.location)
async def handle_location(message: Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    url = (
        f"https://nominatim.openstreetmap.org/reverse?format=json"
        f"&lat={lat}&lon={lon}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
    city = (
        data.get("address", {}).get("city")
        or data.get("address", {}).get("town")
        or data.get("address", {}).get("village")
    )
    if not city:
        await message.answer(
            "Не удалось определить город. Введи его вручную."
        )
        await state.set_state(ProfileFSM.city)
        return
    await state.update_data(city=city, latitude=lat, longitude=lon)
    await message.answer(
        "Отправь 1–2 фото профиля", reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ProfileFSM.photos)

@router.message(ProfileFSM.city_or_geo, F.text)
async def ask_manual_city(message: Message, state: FSMContext):
    await message.answer(
        "Окей, введи свой город:", reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ProfileFSM.city)

@router.message(ProfileFSM.city)
async def handle_manual_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text, latitude=55.75, longitude=37.61)
    await message.answer("Отправь 1–2 фото профиля")
    await state.set_state(ProfileFSM.photos)

@router.message(ProfileFSM.photos, F.photo)
async def handle_photos(message: Message, state: FSMContext):
    try:
        await message.answer("🔄 Обрабатываю фотографию...")
        data = await state.get_data()
        photos = data.get("photos", [])
        file_id = message.photo[-1].file_id
        tg_file = await bot.get_file(file_id)
        download_url = (
            f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/"
            f"{tg_file.file_path}"
        )
        logger.info(f"Downloading photo from Telegram: {download_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as resp:
                content = await resp.read()
        object_name = f"{file_id}.jpg"
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=object_name,
            data=BytesIO(content),
            length=len(content),
            content_type="image/jpeg"
        )
        photos.append(object_name)
        await state.update_data(photos=photos)
        logger.info(f"Photo stored in MinIO as: {object_name}")
        await show_preview(message, state)
    except Exception as e:
        logger.exception("Error in handle_photos")
        await message.answer(f"❌ Ошибка при обработке фото: {e}")

async def show_preview(message: Message, state: FSMContext):
    try:
        await message.answer("🔄 Формирую превью анкеты...")
        data = await state.get_data()
        gender_icon = "👨" if data["gender"] == "male" else "👩"
        text = (
            f"<b>Вот как выглядит анкета:</b>\n"
            f"Имя: {data['name']}\n"
            f"Возраст: {data['age']}\n"
            f"Пол: {gender_icon}\n"
            f"Интересы: {', '.join(data['interests'])}\n"
            f"Город: {data['city']}"
        )
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Всё верно")],
                [KeyboardButton(text="🔄 Заполнить заново")]
            ],
            resize_keyboard=True
        )
        object_name = data['photos'][0]
        logger.info(f"Downloading preview photo from MinIO obj: {object_name}")
        resp = minio_client.get_object(BUCKET_NAME, object_name)
        content = resp.read()
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        photo_file = FSInputFile(tmp_path)
        await message.answer_photo(
            photo_file,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        await state.set_state(ProfileFSM.preview)
    except Exception as e:
        logger.exception("Error in show_preview")
        await message.answer(f"❌ Ошибка при формировании превью: {e}")

@router.message(ProfileFSM.preview, F.text)
async def handle_preview_response(message: Message, state: FSMContext):
    text = message.text.lower()
    if "верно" in text:
        data = await state.get_data()
        profile = {
            "user_id": str(message.from_user.id),
            "name": data['name'],
            "age": data['age'],
            "gender": data['gender'],
            "interests": data['interests'],
            "city": data['city'],
            "photos": [
                f"http://{MINIO_ENDPOINT}/{BUCKET_NAME}/{obj}"
                for obj in data['photos']
            ],
            "latitude": data['latitude'],
            "longitude": data['longitude']
        }
        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://user_service:8000/profile",
                json=profile
            )
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

@router.message(Command("myprofile"))
async def show_my_profile(message: Message):
    user_id = str(message.from_user.id)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://user_service:8000/profile/{user_id}"
        ) as resp:
            data = await resp.json()
    gender_icon = "👨" if data["gender"] == "male" else "👩"
    text = (
        f"<b>Твоя анкета:</b>\n"
        f"Имя: {data['name']}\n"
        f"Возраст: {data['age']}\n"
        f"Пол: {gender_icon}\n"
        f"Интересы: {', '.join(data['interests'])}\n"
        f"Город: {data['city']}"
    )
    if data.get("photos"):
        async with aiohttp.ClientSession() as session:
            async with session.get(data['photos'][0]) as resp:
                img = await resp.read()
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(img)
            tmp_path = tmp.name
        photo_file = FSInputFile(tmp_path)
        await message.answer_photo(photo_file, caption=text, parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ Анкета не найдена.")

app = FastAPI()
dp.include_router(router)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot))