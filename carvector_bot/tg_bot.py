"""Telegram-бот: поиск запчастей LAND ROVER и оформление заявок (без ссылок на сайт)."""
import asyncio
import logging
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ErrorEvent
from aiogram.exceptions import TelegramNetworkError

from parser import CarVectorParser
from storage import add_order

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CARVECTOR_LOGIN = os.getenv("CARVECTOR_LOGIN")
CARVECTOR_PASSWORD = os.getenv("CARVECTOR_PASSWORD")
TELEGRAM_MANAGER_CHAT_ID = os.getenv("TELEGRAM_MANAGER_CHAT_ID")  # Куда слать новые заявки
DEBUG_SAVE_HTML = os.getenv("DEBUG_SAVE_HTML", "0").strip().lower() in ("1", "true", "yes")

if not BOT_TOKEN or not CARVECTOR_LOGIN or not CARVECTOR_PASSWORD:
    raise SystemExit(
        "Заполните .env: BOT_TOKEN, CARVECTOR_LOGIN, CARVECTOR_PASSWORD. "
        "Скопируйте .env.example в .env и отредактируйте."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
parser = CarVectorParser(
    username=CARVECTOR_LOGIN,
    password=CARVECTOR_PASSWORD,
    debug_save_html=DEBUG_SAVE_HTML,
)

# Состояние пользователя: последний результат поиска и шаг оформления заявки
user_state: dict[int, dict] = {}

# Позиции 1–5 = запрашиваемый артикул, 6–10 = оригинальные замены (макс. 5+5)
MAX_REQUESTED = 5
MAX_ORIGINALS = 5


def _get_shown_offers(result: dict) -> list:
    """Список позиций 1–10 для заказа: каждая с best_offer (лучшая цена по позиции)."""
    positions = result.get("positions") or []
    out = []
    for pos in positions:
        offers = pos.get("offers") or []
        best = min(offers, key=lambda x: x["price"]) if offers else None
        out.append({
            "position_num": pos["position_num"],
            "type": pos["type"],
            "brand": pos["brand"],
            "code": pos["code"],
            "description": pos.get("description", ""),
            "offer": best,
        })
    return out


# ---------- /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    logging.info("Получен /start от user_id=%s", user_id)
    user_state.pop(user_id, None)

    try:
        auth_msg = await message.answer("🔐 Авторизация...")
        loop = asyncio.get_event_loop()
        auth_result = await loop.run_in_executor(None, parser.authorize)
    if auth_result:
        parser.is_authorized = True  # явно в основном потоке, чтобы поиск видел авторизацию
        await auth_msg.edit_text(
            "✅ Авторизация успешна!\n\n"
            "👋 Привет! Я ищу запчасти ТОЛЬКО для LAND ROVER.\n"
            "Отправь артикул, и я покажу все цены.\n\n"
            "Пример: LR034262"
        )
    else:
        hint = "Проверьте логин/пароль в .env."
        if DEBUG_SAVE_HTML:
            hint += " Ответ сайта сохранён в debug_login_response.html."
        await auth_msg.edit_text(
            f"❌ Ошибка авторизации. {hint}\n\n"
            "Если бот на Railway — сайт CarVector может блокировать серверные IP. Запустите локально или на домашнем NUC."
        )
    except Exception as e:
        logging.exception("Ошибка в /start: %s", e)
        try:
            await message.answer(f"❌ Ошибка: {e}")
        except Exception:
            pass


# ---------- Кнопка «Оформить заявку» ----------
@dp.callback_query(F.data == "order_start")
async def cb_order_start(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    state = user_state.get(user_id) or {}
    if not state.get("result") or not state.get("shown_offers"):
        await callback.answer("Сначала выполните поиск по артикулу.", show_alert=True)
        return
    user_state[user_id] = {**state, "state": "offer_num", "draft": {}}
    await callback.message.answer(
        "Введите номер позиции из списка (1–5 запрашиваемый артикул, 6–10 замены)."
    )
    await callback.answer()


# ---------- Подтверждение / отмена заявки ----------
@dp.callback_query(F.data == "order_confirm")
async def cb_order_confirm(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    state = user_state.get(user_id) or {}
    if state.get("state") != "confirm":
        await callback.answer("Заявка уже обработана или отменена.", show_alert=True)
        return
    draft = state.get("draft") or {}
    slot = draft.get("offer") or {}  # позиция: position_num, type, brand, code, description, offer
    best = slot.get("offer") or {}   # лучшее предложение по цене
    username = (callback.from_user.username and f"@{callback.from_user.username}") if callback.from_user else ""
    order_id = add_order(
        telegram_user_id=user_id,
        telegram_username=username or (callback.from_user.first_name if callback.from_user else ""),
        part_number=draft.get("part_number", ""),
        offer_code=slot.get("code", best.get("code", "")),
        offer_description=slot.get("description", best.get("description", "")),
        price_value=best.get("price", 0),
        price_text=best.get("price_text", ""),
        supplier_status=best.get("status", ""),
        quantity=draft.get("quantity", 1),
        phone=draft.get("phone", ""),
    )
    user_state.pop(user_id, None)

    manager_text = (
        f"📋 Новая заявка №{order_id}\n"
        f"От: {username or 'без username'} (id: {user_id})\n"
        f"Артикул: {draft.get('part_number', '')}\n"
        f"Код: {slot.get('code', '')} ({slot.get('brand', '')})\n"
        f"Описание: {(slot.get('description') or '')[:200]}\n"
        f"Цена: {best.get('price_text', '')} — {best.get('status', '')}\n"
        f"Количество: {draft.get('quantity', 1)}\n"
    )
    if draft.get("phone"):
        manager_text += f"Телефон: {draft['phone']}\n"
    manager_text += f"Дата: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"

    if TELEGRAM_MANAGER_CHAT_ID:
        try:
            await bot.send_message(TELEGRAM_MANAGER_CHAT_ID, manager_text)
        except Exception as e:
            logging.warning("Не удалось отправить заявку менеджеру: %s", e)

    await callback.message.edit_text(f"✅ Заявка №{order_id} принята. Ожидайте обработки.")
    await callback.answer()


@dp.callback_query(F.data == "order_cancel")
async def cb_order_cancel(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    user_state.pop(user_id, None)
    await callback.message.edit_text("Заявка отменена.")
    await callback.answer()


# ---------- Обработка шагов заявки (номер предложения, количество, комментарий) ----------
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    text = (message.text or "").strip()
    logging.info("Получено сообщение от user_id=%s: %r", user_id, text[:50] if text else "")
    state = user_state.get(user_id) or {}

    if state.get("state") in ("offer_num", "quantity", "phone"):
        await _handle_order_flow(message, state, text, user_id)
        return
    if state.get("state") == "confirm":
        await message.answer("Нажмите кнопку «Подтвердить» или «Отмена» под сводкой заявки.")
        return

    # Не искать по артикулу, если похоже на телефон или «-» (3-й шаг заявки при сбросе состояния)
    if text == "-" or (text and re.match(r"^[\d\s\+\-\(\)]+$", text) and len(re.sub(r"\D", "", text)) >= 10):
        await message.answer(
            "Похоже, вы вводите телефон для заявки. Сессия заявки могла сброситься.\n\n"
            "Сделайте поиск по артикулу → нажмите «Оформить заявку» → введите номер позиции (1–10) → количество → телефон или «-»."
        )
        return

    # Новый поиск по артикулу
    if not parser.is_authorized:
        # одна попытка переавторизации (на случай потери флага между потоками)
        loop = asyncio.get_event_loop()
        reauth = await loop.run_in_executor(None, parser.authorize)
        if reauth:
            parser.is_authorized = True
        else:
            await message.answer("❌ Бот не авторизован. Отправьте /start")
            return
    if not text:
        await message.answer("❌ Введите артикул.")
        return

    status_msg = await message.answer(f"🔍 Ищу {text.upper()} для LAND ROVER...")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, parser.search_land_rover, text.upper())

    if not result or not result.get("positions"):
        await status_msg.edit_text(f"❌ Ничего не найдено для LAND ROVER по артикулу {text.upper()}.")
        return

    shown_offers = _get_shown_offers(result)
    user_state[user_id] = {"result": result, "shown_offers": shown_offers, "state": None, "draft": {}}

    positions = result.get("positions") or []
    requested_pos = [p for p in positions if p.get("type") == "Запрашиваемый"]
    originals_pos = [p for p in positions if p.get("type") == "Оригинальная замена"]

    def _format_pos(pos):
        offers = pos.get("offers") or []
        best = min(offers, key=lambda x: x["price"]) if offers else None
        price_str = f"{best['price']:.2f} ₽" if best else "—"
        star = " ★" if (best and best.get("is_reliable")) else ""
        block = [f"{pos['position_num']}. {pos['brand']} {pos['code']}{star}"]
        if pos.get("description"):
            desc = pos["description"][:60] + "..." if len(pos["description"]) > 60 else pos["description"]
            block.append(f"📝 {desc}")
        block.append(f"💰 {price_str}")
        if best:
            emoji = best.get("emoji", "")
            status_text = best.get("status") or ""
            if status_text:
                prefix = f"{emoji} " if emoji else ""
                block.append(f"{prefix}Статус: {status_text}")
        if best and best.get("deadline"):
            block.append(f"⏱ Ожид. срок: {best['deadline']}")
        return "\n".join(block)

    lines = [
        f"🔍 Артикул: {result['part_number']}",
        f"🚗 Бренд: LAND ROVER",
        "",
        "=" * 40,
        "",
        "Запрашиваемый артикул:",
        "",
    ]
    for pos in requested_pos:
        lines.append(_format_pos(pos))
        lines.append("")
    if originals_pos:
        lines.append("Оригинальные замены:")
        lines.append("")
        for pos in originals_pos:
            lines.append(_format_pos(pos))
            lines.append("")
    lines.append("=" * 40)
    min_p = result.get("min_price")
    lines.append(f"💰 Минимальная возможная цена: {f'{min_p:.2f} ₽' if min_p is not None else '—'}")
    lines.append(f"📊 Позиций: {result.get('total_requested', 0)} запрашиваемых / {result.get('total_originals', 0)} замен")

    answer = "\n".join(lines)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📋 Оформить заявку", callback_data="order_start")]]
    )
    if len(answer) > 4096:
        parts = [answer[i : i + 4096] for i in range(0, len(answer), 4096)]
        for part in parts[:-1]:
            await message.answer(part)
        await message.answer(parts[-1], reply_markup=kb)
        await status_msg.delete()
    else:
        await status_msg.edit_text(answer, reply_markup=kb)


async def _handle_order_flow(message: types.Message, state: dict, text: str, user_id: int):
    shown = state.get("shown_offers") or []
    step = state.get("state")
    draft = state.get("draft") or {}

    if step == "offer_num":
        try:
            num = int(text)
        except ValueError:
            await message.answer("Введите число — номер предложения из списка (1, 2, 3…).")
            return
        if num < 1 or num > len(shown):
            await message.answer(f"Введите номер от 1 до {len(shown)}.")
            return
        slot = shown[num - 1]
        draft["part_number"] = state.get("result", {}).get("part_number", "")
        draft["offer"] = slot
        draft["created_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        user_state[user_id] = {**state, "state": "quantity", "draft": draft}
        await message.answer("Введите количество (целое число, например 1 или 2):")
        return

    if step == "quantity":
        try:
            qty = int(text)
        except ValueError:
            await message.answer("Введите целое число (количество).")
            return
        if qty < 1:
            await message.answer("Количество должно быть не меньше 1.")
            return
        draft["quantity"] = qty
        user_state[user_id] = {**state, "state": "phone", "draft": draft}
        await message.answer("Добавьте телефон или отправьте «-» чтобы пропустить.")
        return

    if step == "phone":
        phone = "" if text.strip() == "-" else text.strip()
        await _send_order_confirm(message, user_id, state, draft, phone)
        return


async def _send_order_confirm(message: types.Message, user_id: int, state: dict, draft: dict, phone: str):
    """Сохраняет телефон в черновик, переводит в шаг подтверждения и отправляет сводку заявки с кнопками."""
    draft = {**draft, "phone": (phone or "").strip()}
    user_state[user_id] = {**state, "state": "confirm", "draft": draft}

    slot = draft.get("offer") or {}
    best = slot.get("offer") or {}
    summary = (
        f"Проверьте заявку:\n\n"
        f"Артикул: {draft.get('part_number', '')}\n"
        f"Позиция: {slot.get('brand', '')} {slot.get('code', '')} — {best.get('price_text', '')}\n"
        f"Количество: {draft.get('quantity', 1)}\n"
    )
    if draft.get("phone"):
        summary += f"Телефон: {draft['phone']}\n"
    summary += f"\nСумма: {best.get('price', 0) * draft.get('quantity', 1):.2f} ₽"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data="order_confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="order_cancel"),
            ]
        ]
    )
    await message.answer(summary, reply_markup=kb)


# ---------- Телефон через кнопку «Поделиться контактом» на шаге заявки ----------
@dp.message(F.contact)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    state = user_state.get(user_id) or {}
    if state.get("state") != "phone":
        await message.answer("Отправьте контакт только когда бот просит ввести телефон для заявки.")
        return
    draft = state.get("draft") or {}
    phone = (message.contact.phone_number or "") if message.contact else ""
    await _send_order_confirm(message, user_id, state, draft, phone)


@dp.error()
async def error_handler(event: ErrorEvent):
    """Ловим любые необработанные исключения в хендлерах, чтобы бот не падал."""
    logging.exception("Необработанная ошибка в обработчике: %s", event.exception)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    if TELEGRAM_MANAGER_CHAT_ID:
        logging.info("Уведомления о заявках → chat_id %s", TELEGRAM_MANAGER_CHAT_ID)
    else:
        logging.warning("TELEGRAM_MANAGER_CHAT_ID не задан — заявки не будут дублироваться менеджеру")
    logging.info("Бот запущен (LAND ROVER, заявки в data/orders.json)")

    # Даём контейнеру время поднять сеть/DNS
    await asyncio.sleep(20)

    while True:
        try:
            await dp.start_polling(bot)
        except TelegramNetworkError as e:
            logging.warning("Нет связи с Telegram (api.telegram.org). Повтор через 60 с: %s", e)
            await asyncio.sleep(60)
        except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as e:
            logging.warning("Сетевая ошибка. Повтор через 60 с: %s", e)
            await asyncio.sleep(60)
        except Exception as e:
            logging.exception("Ошибка polling, повтор через 60 с: %s", e)
            await asyncio.sleep(60)
        else:
            break


if __name__ == "__main__":
    asyncio.run(main())

