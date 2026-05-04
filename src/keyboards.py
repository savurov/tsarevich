from aiogram import types

AFTER_ROUTE_OPTIONS = ["📍 Та же станция", "🔀 Сменить станцию", "🏠 В начало"]


def build_keyboard(buttons, row_width=2):
    keyboard = []
    row = []
    for button in buttons:
        row.append(types.KeyboardButton(text=button))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
