"""Хранение заявок в JSON-файле."""
import json
import os
from datetime import datetime
from pathlib import Path

# В add-on через run.sh задаётся STORAGE_PATH=/data, чтобы заявки сохранялись в том HA
_data_dir = Path(os.getenv("STORAGE_PATH", ""))
if _data_dir:
    ORDERS_FILE = _data_dir / "orders.json"
else:
    ORDERS_FILE = Path(__file__).resolve().parent / "data" / "orders.json"


def _ensure_data_dir():
    ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> list:
    _ensure_data_dir()
    if not ORDERS_FILE.exists():
        return []
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(orders: list) -> None:
    _ensure_data_dir()
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def add_order(
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    part_number: str,
    offer_code: str,
    offer_description: str,
    price_value: float,
    price_text: str,
    supplier_status: str,
    quantity: int,
    phone: str = "",
) -> int:
    """Добавляет заявку и возвращает её номер (id)."""
    orders = _load_raw()
    next_id = max((o.get("id", 0) for o in orders), default=0) + 1
    order = {
        "id": next_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "telegram_user_id": telegram_user_id,
        "telegram_username": telegram_username or "",
        "part_number": part_number,
        "offer_code": offer_code,
        "offer_description": offer_description,
        "price_value": price_value,
        "price_text": price_text,
        "supplier_status": supplier_status,
        "quantity": quantity,
        "phone": (phone or "").strip(),
        "status": "new",
    }
    orders.append(order)
    _save_raw(orders)
    return next_id


def get_orders(status: str | None = None) -> list:
    """Возвращает список заявок, опционально отфильтрованный по status."""
    orders = _load_raw()
    if status:
        orders = [o for o in orders if o.get("status") == status]
    return orders
