import asyncio
import time
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

API_TOKEN = os.getenv("API_TOKEN")
CHANNEL_USERNAME = '@kalloniya'
MODERATORS = [2010183573, 5805173379]

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_last_post = {}
pending_posts = {}

# Словарь: модератор_id -> данные поста, для которого ждём причину отказа
waiting_for_reason = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✉️ Отправить пост")]],
        resize_keyboard=True
    )
    await message.answer("Нажмите кнопку ниже, чтобы предложить пост:", reply_markup=keyboard)

@dp.message()
async def on_message(message: types.Message):
    user_id = message.from_user.id

    if user_id in waiting_for_reason:
        # Модератор пишет причину отказа
        post = waiting_for_reason.pop(user_id)
        post_user_id = post['user_id']
        mod_msg_id = post['mod_message_id']
        reason_msg_id = post.get('reason_message_id')

        # Отправляем отказ пользователю
        await bot.send_message(post_user_id, f"❌ Ваш пост не прошёл модерацию.\nПричина: {message.text}")

        # Удаляем сообщение модератора с кнопками (пост на модерацию)
        try:
            await bot.delete_message(user_id, mod_msg_id)
        except Exception:
            pass

        # Удаляем сообщение с просьбой причины отказа
        if reason_msg_id:
            try:
                await bot.delete_message(user_id, reason_msg_id)
            except Exception:
                pass

        # Удаляем сообщение с текстом причины (текущие сообщение модератора)
        try:
            await message.delete()
        except Exception:
            pass

        # Отправляем сообщение с кнопкой "Хорошо"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Хорошо", callback_data="confirm_delete")]
        ])
        await bot.send_message(user_id, "Отказ принят и отправлен пользователю.", reply_markup=markup)

        # Удаляем пост из ожидания
        for mod_id, msg_id in post.get('message_ids', []):
            pending_posts.pop(msg_id, None)
        return

    if message.text == "✉️ Отправить пост":
        now = time.time()
        last = user_last_post.get(user_id, 0)
        if now - last < 300:
            await message.answer("Пожалуйста, подождите 5 минут перед отправкой нового поста.")
            return
        await message.answer(
            "Отправьте ваш пост который по вашему мнению должен находится в каллонии (фото и/или текст).\n\n"
            "Модерация может отклонить ваш пост, если он неинтересен или нарушает законодательство РФ. Пост можно отправлять раз в 5 минут и ваш юзернейм будет отправлен модератору"
        )
        # Помечаем, что ждём пост
        user_last_post[user_id] = 0  # Помечаем 0 — ждём пост
        return

    if user_last_post.get(user_id, 0) == 0:
        # Ждём пост
        text = message.caption if message.caption else message.text if message.text else ""
        photo = message.photo[-1].file_id if message.photo else None

        if not text and not photo:
            await message.answer("Пост не может быть пустым. Отправьте текст или фото.")
            return

        post_data = {
            'user_id': user_id,
            'username': '@' + (message.from_user.username or "без_ника"),
            'text': text,
            'photo': photo,
            'timestamp': time.time()
        }
        user_last_post[user_id] = post_data['timestamp']

        msg_caption = f"Пост от {post_data['username']}:\n\n{post_data['text']}" if post_data['text'] else f"Пост от {post_data['username']} (без текста)"

        buttons = InlineKeyboardMarkup(inline_keyboard=[[  
            InlineKeyboardButton(text="✅ Принять", callback_data="approve"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data="reject")
        ]])

        post_data['message_ids'] = []
        for mod_id in MODERATORS:
            if post_data['photo']:
                sent_msg = await bot.send_photo(mod_id, post_data['photo'], caption=msg_caption, reply_markup=buttons)
            else:
                sent_msg = await bot.send_message(mod_id, msg_caption, reply_markup=buttons)
            # Сохраняем пару (модератор, message_id) для точного удаления
            post_data['message_ids'].append((mod_id, sent_msg.message_id))
            # Сохраняем по message_id ссылку на общий post_data
            pending_posts[sent_msg.message_id] = post_data

        await message.answer("Ваш пост отправлен на модерацию. Ожидайте ответа.")
        return

@dp.callback_query()
async def on_callback(callback: types.CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if data == "confirm_delete":
        # Удаляем сообщение с кнопкой "Хорошо"
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    message_id = callback.message.message_id
    post = pending_posts.get(message_id)

    if not post:
        await callback.answer("Пост уже обработан.", show_alert=True)
        return

    if data == "approve":
        if post['photo']:
            await bot.send_photo(CHANNEL_USERNAME, post['photo'], caption=post['text'])
        else:
            await bot.send_message(CHANNEL_USERNAME, post['text'])
        await bot.send_message(post['user_id'], "✅ Ваш пост прошёл модерацию и будет опубликован.")

        # Удаляем все сообщения с кнопками у всех модераторов
        await delete_all_mod_messages(post)

        await callback.answer("Пост опубликован.")

    elif data == "reject":
        if user_id in waiting_for_reason:
            await callback.answer("Вы уже вводите причину отказа.", show_alert=True)
            return
        reason_msg = await callback.message.answer("❌ Напишите причину отказа:")
        waiting_for_reason[user_id] = {
            **post,
            'mod_message_id': message_id,
            'reason_message_id': reason_msg.message_id
        }

        # Удаляем все сообщения с кнопками у всех модераторов, чтобы не было двойной модерации
        await delete_all_mod_messages(post)

        # Удаляем вызов edit_reply_markup, чтобы не было ошибки (сообщения уже удалены)

        await callback.answer()

async def delete_all_mod_messages(post):
    # Удаляем все сообщения с кнопками у всех модераторов для данного поста
    for mod_id, msg_id in post.get('message_ids', []):
        try:
            await bot.delete_message(mod_id, msg_id)
        except Exception:
            pass
        pending_posts.pop(msg_id, None)

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
