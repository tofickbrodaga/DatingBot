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
from config import minio_client, BUCKET_NAME, MINIO_PUBLIC_URL, r
from matching_handlers import get_router as get_match_router
from io import BytesIO
from aiogram.filters import Command
from like_handlers import router as like_router


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "fake")

bot = Bot(token=TELEGRAM_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

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
            [KeyboardButton(text="🌍 Ввести город вручную")]
        ],
        resize_keyboard=True
    )
    await message.answer("Хочешь указать координаты или ввести город?", reply_markup=kb)
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
        await message.answer("Не удалось определить город. Введи его вручную.")
        await state.set_state(ProfileFSM.city)
        return
    await state.update_data(city=city, latitude=lat, longitude=lon)
    await message.answer("Отправь 1–2 фото профиля", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ProfileFSM.photos)

@router.message(ProfileFSM.city_or_geo, F.text)
async def ask_manual_city(message: Message, state: FSMContext):
    await message.answer("Окей, введи свой город:", reply_markup=ReplyKeyboardRemove())
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
        await show_preview(message, state)
    except Exception as e:
        logger.exception("Error in handle_photos")
        await message.answer(f"❌ Ошибка при обработке фото: {e}")

async def show_preview(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        gender_icon = "👨" if data["gender"] == "male" else "👩"
        text = (
            f"<b>Вот как выглядит анкета:</b>\n"
            f"{data['name']}\n"
            f"{data['age']}\n"
            f"{gender_icon}\n"
            f"{', '.join(data['interests'])}\n"
            f"{data['city']}"
        )
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Всё верно")],
                [KeyboardButton(text="🔄 Заполнить заново")]
            ],
            resize_keyboard=True
        )
        object_name = data['photos'][0]
        resp = minio_client.get_object(BUCKET_NAME, object_name)
        content = resp.read()
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        photo_file = FSInputFile(tmp_path)
        await message.answer_photo(photo_file, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
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
            "photos": [f"{MINIO_PUBLIC_URL}/{BUCKET_NAME}/{obj}" for obj in data['photos']],
            "latitude": data['latitude'],
            "longitude": data['longitude']
        }
        async with aiohttp.ClientSession() as session:
            await session.post("http://user_service:8000/profile", json=profile)

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

    gender_icon = "👨" if data["gender"] == "male" else "👩"
    text = (
        f"<b>Вот как выглядит анкета:</b>\n"
        f"{data['name']}\n"
        f"{data['age']}\n"
        f"{gender_icon}\n"
        f"{', '.join(data['interests'])}\n"
        f"{data['city']}"
    )

    if data.get("photos"):
        photo_url = data['photos'][0]
        object_name = photo_url.rsplit("/", 1)[-1]
        response = minio_client.get_object(BUCKET_NAME, object_name)
        content = response.read()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        photo_file = FSInputFile(tmp_path)
        await message.answer_photo(photo_file, caption=text, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML)


app = FastAPI()
dp.include_router(router)
dp.include_router(get_match_router(minio_client, BUCKET_NAME))
dp.include_router(like_router)


@app.on_event("startup")
async def on_startup():
    for key in r.scan_iter("shown_user_ids:*"):
        r.delete(key)
    print("🧹 Redis очищен: shown_user_ids:*")
    asyncio.create_task(dp.start_polling(bot))
