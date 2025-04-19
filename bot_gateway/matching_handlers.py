import aiohttp
import tempfile
from aiogram import Router, F
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from keyboards.match import like_dislike_kb

def get_router(minio_client, bucket_name):
    router = Router()

    @router.message(F.text == "💘 Начать поиск")
    async def show_match(message: Message, state: FSMContext):
        user_id = message.from_user.id
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://matchmaking_service:8000/match?user_id={user_id}") as resp:
                profiles = await resp.json()

        if not profiles:
            await message.answer("Нет новых анкет 😔")
            return

        profile = profiles[0]
        text = f"<b>{profile['name']}, {profile['age']}</b>\n📍 {profile['city']}"

        try:
            photo_url = profile["photos"][0]
            object_name = photo_url.rsplit('/', 1)[-1]

            response = minio_client.get_object(bucket_name, object_name)
            content = response.read()
            response.close()
            response.release_conn()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            file = FSInputFile(tmp_path, filename=object_name)
            await message.answer_photo(file, caption=text, parse_mode="HTML", reply_markup=like_dislike_kb())

        except Exception as e:
            await message.answer(f"⚠️ Не удалось загрузить фото: {e}")

    return router
