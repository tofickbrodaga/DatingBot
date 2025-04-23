from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def liked_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Хочу посмотреть", callback_data="view_likers")],
        [InlineKeyboardButton(text="❌ Не сейчас", callback_data="ignore_likers")]
    ])
