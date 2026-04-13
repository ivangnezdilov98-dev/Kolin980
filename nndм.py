import asyncio
import json
import os
import traceback  
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Загружаем переменные окружения
load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
class Config:
    # Администраторы
    ADMIN_IDS = [1824049351, 5568154436]
    ADMIN_USERNAME = "@koliin98"
    
    # ID каналов для заявок
    PAYMENT_CHANNEL_ID = -1001862240317
    ORDER_CHANNEL_ID = -1002893927706
    
    # КАНАЛ ДЛЯ ТИКЕТОВ (закрытый канал администратора)
    TICKET_CHANNEL_ID = -1001234567890  # ЗАМЕНИТЕ НА ID ВАШЕГО КАНАЛА!
    
    # Канал для проверки подписки
    REQUIRED_CHANNEL = "@prodaja_akkov_tg"
    REQUIRED_CHANNEL_URL = "https://t.me/prodaja_akkov_tg"
    
    # Реквизиты для оплаты (только Ozon)
    PAYMENT_DETAILS = {
        "ozon": {
            "name": "Ozon Банк (СБП/Карта)",
            "card_number": "2200 2488 7412 7581",
            "phone_number": "+79225739192",
            "owner": "Иван Г."
        }
    }
    
    # Настройки реферальной программы (можно менять)
    REFERRAL_CONFIG = {
        "enabled": True,
        "min_purchase_amount": 70,
        "reward_type": "free_account",
        "reward_description": "1 аккаунт Мьянма бесплатно",
        "reward_trigger": "next_purchase",
        "max_referrals_per_user": 10,
    }

    # Файлы данных
    DATA_FILE = "products_data.json"
    USERS_FILE = "users_data.json"
    TICKETS_FILE = "tickets_data.json"
    CHATS_FILE = "chats_data.json"

config = Config()

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))

# Создаем storage и dispatcher
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== СОСТОЯНИЯ FSM ====================

class AddProductStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_description = State()

class PaymentStates(StatesGroup):
    waiting_for_screenshot = State()

class DeleteProductStates(StatesGroup):
    waiting_for_product_choice = State()

class CartStates(StatesGroup):
    waiting_for_quantity = State()
    managing_cart = State()

class ReferralStates(StatesGroup):
    waiting_for_new_amount = State()
    waiting_for_new_reward = State()

class TicketStates(StatesGroup):
    waiting_for_ticket_text = State()
    chat_mode = State()  # Состояние чата с пользователем

# ==================== БАЗА ДАННЫХ ====================

class Database:
    def __init__(self):
        self.products: List[Dict] = []
        self.categories: List[Dict] = []
        self.users: Dict[int, Dict] = {}
        self.transactions: List[Dict] = []
        self.pending_orders: Dict[str, Dict] = {}
        self.load_data()
    
    def load_data(self):
        """Загружаем данные из файлов"""
        try:
            # Загружаем товары и категории
            if os.path.exists(config.DATA_FILE):
                with open(config.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.products = data.get('products', [])
                    self.categories = data.get('categories', [])
            else:
                self.categories = [
                    {"id": 1, "name": "💻 Цифровые услуги"},
                    {"id": 2, "name": "🎨 Дизайн"},
                    {"id": 3, "name": "📝 Контент"}
                ]
                self.save_products_data()
            
            # Загружаем пользователей
            if os.path.exists(config.USERS_FILE):
                with open(config.USERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    users_data = data.get('users', {})
                    self.users = {int(k): v for k, v in users_data.items()}
                    self.transactions = data.get('transactions', [])
                    self.pending_orders = data.get('pending_orders', {})
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            self.products = []
            self.categories = []
            self.users = {}
            self.transactions = []
            self.pending_orders = {}
    
    def save_products_data(self):
        """Сохраняем товары и категории"""
        try:
            data = {
                "products": self.products,
                "categories": self.categories
            }
            with open(config.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения товаров: {e}")
    
    def save_users_data(self):
        """Сохраняем пользователей"""
        try:
            data = {
                "users": self.users,
                "transactions": self.transactions,
                "pending_orders": self.pending_orders
            }
            with open(config.USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения пользователей: {e}")
    
    def _generate_referral_code(self, user_id: int) -> str:
        """Генерирует уникальный реферальный код"""
        code = hashlib.md5(f"{user_id}{datetime.now().timestamp()}".encode()).hexdigest()[:8]
        return code.upper()
    
    # Работа с пользователями
    def get_user(self, user_id: int) -> Dict:
        if user_id not in self.users:
            self.users[user_id] = {
                "total_spent": 0.0,
                "total_orders": 0,
                "registration_date": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "referral_code": self._generate_referral_code(user_id),
                "referred_by": None,
                "referrals": [],
                "qualified_referrals": 0,
                "available_rewards": 0,
                "used_rewards": 0,
                "is_subscribed": False,
                "subscription_checked_at": None
            }
            self.save_users_data()
        return self.users[user_id]
    
    def update_user_stats(self, user_id: int, amount: float):
        """Обновить статистику пользователя после покупки"""
        try:
            user = self.get_user(user_id)
            user["total_spent"] = user.get("total_spent", 0.0) + amount
            user["total_orders"] = user.get("total_orders", 0) + 1
            user["last_activity"] = datetime.now().isoformat()
            
            transaction = {
                "id": len(self.transactions) + 1,
                "user_id": user_id,
                "type": "purchase",
                "amount": amount,
                "description": "Оплата товара",
                "date": datetime.now().isoformat()
            }
            self.transactions.append(transaction)
            
            self.save_users_data()
        except Exception as e:
            print(f"Ошибка обновления статистики: {e}")
    
    # Работа с ожидающими заказами
    def add_pending_order(self, order_id: str, order_data: Dict):
        """Добавить ожидающий заказ"""
        self.pending_orders[order_id] = order_data
        self.save_users_data()
    
    def get_pending_order(self, order_id: str) -> Optional[Dict]:
        """Получить ожидающий заказ"""
        return self.pending_orders.get(order_id)
    
    def remove_pending_order(self, order_id: str):
        """Удалить ожидающий заказ"""
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            self.save_users_data()
    
    # Работа с категориями и товарами
    def get_categories(self) -> List[Dict]:
        return self.categories
    
    def get_category(self, category_id: int) -> Optional[Dict]:
        for category in self.categories:
            if category["id"] == category_id:
                return category
        return None
    
    def add_category(self, name: str) -> int:
        new_id = max([cat["id"] for cat in self.categories], default=0) + 1
        self.categories.append({"id": new_id, "name": name})
        self.save_products_data()
        return new_id
    
    def get_products_by_category(self, category_id: int) -> List[Dict]:
        return [p for p in self.products if p["category_id"] == category_id]
    
    def get_all_products(self) -> List[Dict]:
        """Получить все товары"""
        return self.products
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        for product in self.products:
            if product["id"] == product_id:
                return product
        return None
    
    def add_product(self, category_id: int, name: str, price: float, description: str = "", quantity: int = 9999) -> int:
        new_id = max([prod["id"] for prod in self.products], default=0) + 1
        product = {
            "id": new_id,
            "category_id": category_id,
            "name": name,
            "price": price,
            "description": description,
            "quantity": quantity
        }
        self.products.append(product)
        self.save_products_data()
        return new_id
    
    def delete_product(self, product_id: int) -> bool:
        initial_len = len(self.products)
        self.products = [prod for prod in self.products if prod["id"] != product_id]
        self.save_products_data()
        return len(self.products) < initial_len

db = Database()

# ==================== СИСТЕМА ТИКЕТОВ И ЧАТОВ ====================

class TicketManager:
    """Менеджер тикетов и чатов"""
    
    def __init__(self):
        self.tickets: Dict[int, Dict] = {}  # user_id -> ticket_data
        self.active_chats: Dict[int, Dict] = {}  # user_id -> chat_data
        self.load_data()
    
    def load_data(self):
        """Загрузить тикеты и чаты"""
        try:
            if os.path.exists(config.TICKETS_FILE):
                with open(config.TICKETS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tickets = {int(k): v for k, v in data.get('tickets', {}).items()}
                    self.active_chats = {int(k): v for k, v in data.get('active_chats', {}).items()}
            else:
                self.tickets = {}
                self.active_chats = {}
        except Exception as e:
            print(f"Ошибка загрузки тикетов: {e}")
            self.tickets = {}
            self.active_chats = {}
    
    def save_data(self):
        """Сохранить тикеты и чаты"""
        try:
            data = {
                "tickets": self.tickets,
                "active_chats": self.active_chats
            }
            with open(config.TICKETS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения тикетов: {e}")
    
    def create_ticket(self, user_id: int, username: str, ticket_text: str) -> Dict:
        """Создать новый тикет"""
        if user_id in self.tickets:
            return None  # Уже есть активный тикет
        
        ticket_id = f"TICKET_{user_id}_{int(datetime.now().timestamp())}"
        
        ticket_data = {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "username": username,
            "text": ticket_text,
            "status": "open",
            "created_at": datetime.now().isoformat(),
            "messages": []
        }
        
        self.tickets[user_id] = ticket_data
        self.save_data()
        return ticket_data
    
    def get_user_ticket(self, user_id: int) -> Optional[Dict]:
        """Получить активный тикет пользователя"""
        return self.tickets.get(user_id)
    
    def close_ticket(self, user_id: int):
        """Закрыть тикет"""
        if user_id in self.tickets:
            self.tickets[user_id]["status"] = "closed"
            self.tickets[user_id]["closed_at"] = datetime.now().isoformat()
            del self.tickets[user_id]
            self.save_data()
    
    def create_chat(self, user_id: int, username: str) -> Dict:
        """Создать активный чат с пользователем"""
        if user_id in self.active_chats:
            return self.active_chats[user_id]
        
        chat_data = {
            "user_id": user_id,
            "username": username,
            "started_at": datetime.now().isoformat(),
            "is_active": True,
            "message_history": []
        }
        
        self.active_chats[user_id] = chat_data
        self.save_data()
        return chat_data
    
    def get_active_chat(self, user_id: int) -> Optional[Dict]:
        """Получить активный чат"""
        chat = self.active_chats.get(user_id)
        if chat and chat.get("is_active"):
            return chat
        return None
    
    def close_chat(self, user_id: int):
        """Закрыть чат"""
        if user_id in self.active_chats:
            self.active_chats[user_id]["is_active"] = False
            self.active_chats[user_id]["closed_at"] = datetime.now().isoformat()
            del self.active_chats[user_id]
            self.save_data()
    
    def add_message_to_chat(self, user_id: int, message: str, is_from_admin: bool = False):
        """Добавить сообщение в историю чата"""
        chat = self.active_chats.get(user_id)
        if chat:
            chat["message_history"].append({
                "text": message,
                "is_from_admin": is_from_admin,
                "timestamp": datetime.now().isoformat()
            })
            self.save_data()
    
    def has_active_ticket(self, user_id: int) -> bool:
        """Проверить, есть ли у пользователя активный тикет"""
        return user_id in self.tickets
    
    def has_active_chat(self, user_id: int) -> bool:
        """Проверить, есть ли активный чат с пользователем"""
        chat = self.active_chats.get(user_id)
        return chat is not None and chat.get("is_active", False)

ticket_manager = TicketManager()

# ==================== ФУНКЦИИ ПРОВЕРКИ ПОДПИСКИ И РЕФЕРАЛОВ ====================

async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(chat_id=config.REQUIRED_CHANNEL, user_id=user_id)
        
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False

async def process_referral(user_id: int, referral_code: str):
    """Обрабатывает переход по реферальной ссылке"""
    try:
        referrer_id = None
        for uid, data in db.users.items():
            if data.get('referral_code') == referral_code and uid != user_id:
                referrer_id = uid
                break
        
        if referrer_id:
            user_data = db.get_user(user_id)
            if not user_data.get('referred_by'):
                user_data['referred_by'] = referrer_id
                
                referrer_data = db.get_user(referrer_id)
                if user_id not in referrer_data.get('referrals', []):
                    referrer_data.setdefault('referrals', []).append(user_id)
                
                db.save_users_data()
                print(f"✅ Пользователь {user_id} перешел по реферальной ссылке {referral_code}")
                
    except Exception as e:
        print(f"Ошибка при обработке реферала: {e}")

async def check_referral_qualification(referrer_id: int, purchase_amount: float):
    """Проверяет, выполнил ли реферал условия для награды"""
    try:
        config_ref = Config.REFERRAL_CONFIG
        if not config_ref["enabled"]:
            return False
        
        if purchase_amount >= config_ref["min_purchase_amount"]:
            referrer_data = db.get_user(referrer_id)
            referrer_data["qualified_referrals"] = referrer_data.get("qualified_referrals", 0) + 1
            referrer_data["available_rewards"] = referrer_data.get("available_rewards", 0) + 1
            db.save_users_data()
            
            await bot.send_message(
                chat_id=referrer_id,
                text=f"""🎉 Поздравляем! Ваш реферал совершил покупку на {purchase_amount:.2f}₽!

🎁 Вы получили: {config_ref['reward_description']}
📊 Всего наград: {referrer_data['available_rewards']}

Использовать награду можно при следующей покупке автоматически."""
            )
            return True
        return False
    except Exception as e:
        print(f"Ошибка при проверке квалификации реферала: {e}")
        return False

async def apply_referral_reward(user_id: int, purchase_amount: float) -> Dict:
    """Применяет реферальную награду к покупке"""
    try:
        config_ref = Config.REFERRAL_CONFIG
        user_data = db.get_user(user_id)
        
        available_rewards = user_data.get("available_rewards", 0)
        
        if available_rewards > 0 and purchase_amount >= config_ref["min_purchase_amount"]:
            user_data["available_rewards"] = available_rewards - 1
            user_data["used_rewards"] = user_data.get("used_rewards", 0) + 1
            db.save_users_data()
            
            return {
                "applied": True,
                "reward_description": config_ref["reward_description"],
                "remaining_rewards": user_data["available_rewards"]
            }
        
        return {"applied": False, "remaining_rewards": available_rewards}
        
    except Exception as e:
        print(f"Ошибка при применении награды: {e}")
        return {"applied": False, "error": str(e)}

# ==================== МИГРАЦИЯ ДАННЫХ ДЛЯ СТАРЫХ ПОЛЬЗОВАТЕЛЕЙ ====================

async def migrate_existing_users():
    """Добавляет реферальные коды всем существующим пользователям"""
    print("🔄 Проверка и миграция данных пользователей...")
    
    migrated_count = 0
    for user_id, user_data in db.users.items():
        if 'referral_code' not in user_data or not user_data.get('referral_code'):
            user_data['referral_code'] = db._generate_referral_code(user_id)
            migrated_count += 1
            print(f"  ➕ Добавлен реферальный код для пользователя {user_id}")
        
        default_fields = {
            'referred_by': None,
            'referrals': [],
            'qualified_referrals': 0,
            'available_rewards': 0,
            'used_rewards': 0
        }
        
        for field, default_value in default_fields.items():
            if field not in user_data:
                user_data[field] = default_value
    
    if migrated_count > 0:
        db.save_users_data()
        print(f"✅ Миграция завершена. Обновлено {migrated_count} пользователей")
    else:
        print("✅ Все пользователи уже имеют реферальные коды")


async def get_referral_info(user_id: int) -> str:
    """Получает информацию о реферальной программе для пользователя"""
    try:
        config_ref = Config.REFERRAL_CONFIG
        if not config_ref["enabled"]:
            return ""
        
        user_data = db.get_user(user_id)
        
        bot_username = (await bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user_data['referral_code']}"
        
        info = f"""
🎁 РЕФЕРАЛЬНАЯ ПРОГРАММА

Приглашайте друзей и получайте награды!

📊 Ваша статистика:
• Приглашено друзей: {len(user_data.get('referrals', []))}
• Квалифицированных рефералов: {user_data.get('qualified_referrals', 0)}
• Доступно наград: {user_data.get('available_rewards', 0)}

🎁 Награда: {config_ref['reward_description']}
💰 Условие: покупка реферала от {config_ref['min_purchase_amount']}₽

🔗 Ваша реферальная ссылка:
`{referral_link}`

💡 Отправьте эту ссылку друзьям!
"""
        return info
    except Exception as e:
        print(f"Ошибка при получении реферальной информации: {e}")
        return ""

# ==================== МЕНЕДЖЕР КОРЗИНЫ ====================

class CartManager:
    """Менеджер корзины пользователя"""
    
    def __init__(self):
        self.carts: Dict[int, List[Dict]] = {}
        self.load_carts()
    
    def load_carts(self):
        """Загрузить корзины из файла"""
        try:
            if os.path.exists('carts_data.json'):
                with open('carts_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.carts = {int(k): v for k, v in data.items()}
            else:
                self.carts = {}
        except Exception as e:
            print(f"Ошибка загрузки корзин: {e}")
            self.carts = {}
    
    def save_carts(self):
        """Сохранить корзины в файл"""
        try:
            with open('carts_data.json', 'w', encoding='utf-8') as f:
                json.dump(self.carts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения корзин: {e}")
    
    def get_cart(self, user_id: int) -> List[Dict]:
        """Получить корзину пользователя"""
        if user_id not in self.carts:
            self.carts[user_id] = []
        return self.carts[user_id]
    
    def add_to_cart(self, user_id: int, product_id: int, quantity: int = 1) -> bool:
        """Добавить товар в корзину"""
        try:
            cart = self.get_cart(user_id)
            product = db.get_product(product_id)
            
            if not product:
                return False
            
            if quantity > product.get('quantity', 9999):
                return False
            
            for item in cart:
                if item['product_id'] == product_id:
                    item['quantity'] += quantity
                    self.save_carts()
                    return True
            
            cart.append({
                'product_id': product_id,
                'quantity': quantity,
                'added_at': datetime.now().isoformat()
            })
            self.save_carts()
            return True
            
        except Exception as e:
            print(f"Ошибка добавления в корзину: {e}")
            return False
    
    def remove_from_cart(self, user_id: int, product_id: int) -> bool:
        """Удалить товар из корзины"""
        try:
            cart = self.get_cart(user_id)
            initial_len = len(cart)
            self.carts[user_id] = [item for item in cart if item['product_id'] != product_id]
            
            if len(self.carts[user_id]) < initial_len:
                self.save_carts()
                return True
            return False
            
        except Exception as e:
            print(f"Ошибка удаления из корзины: {e}")
            return False
    
    def update_quantity(self, user_id: int, product_id: int, quantity: int) -> bool:
        """Обновить количество товара в корзине"""
        try:
            cart = self.get_cart(user_id)
            product = db.get_product(product_id)
            
            if not product:
                return False
            
            if quantity > product.get('quantity', 9999):
                return False
            
            for item in cart:
                if item['product_id'] == product_id:
                    item['quantity'] = quantity
                    self.save_carts()
                    return True
            
            return False
            
        except Exception as e:
            print(f"Ошибка обновления количества: {e}")
            return False
    
    def clear_cart(self, user_id: int) -> bool:
        """Очистить корзину"""
        try:
            if user_id in self.carts:
                del self.carts[user_id]
                self.save_carts()
                return True
            return False
        except Exception as e:
            print(f"Ошибка очистки корзины: {e}")
            return False
    
    def get_cart_total(self, user_id: int) -> Dict:
        """Получить итог корзины"""
        try:
            cart = self.get_cart(user_id)
            total_amount = 0.0
            total_quantity = 0
            items_details = []
            
            for item in cart:
                product = db.get_product(item['product_id'])
                if product:
                    price = float(product['price'])
                    quantity = item['quantity']
                    item_total = price * quantity
                    
                    total_amount += item_total
                    total_quantity += quantity
                    
                    items_details.append({
                        'product_id': product['id'],
                        'name': product['name'],
                        'price': price,
                        'quantity': quantity,
                        'item_total': item_total
                    })
            
            return {
                'total_amount': total_amount,
                'total_quantity': total_quantity,
                'items': items_details,
                'items_count': len(items_details)
            }
            
        except Exception as e:
            print(f"Ошибка расчета итога корзины: {e}")
            return {'total_amount': 0, 'total_quantity': 0, 'items': [], 'items_count': 0}
    
    def get_cart_items_count(self, user_id: int) -> int:
        """Получить количество товаров в корзине"""
        return len(self.get_cart(user_id))

# Создаем экземпляр менеджера корзины
cart_manager = CartManager()

# ==================== УТИЛИТЫ ====================

async def send_to_order_channel(order_data: Dict, screenshot_file_id: str = None) -> Optional[int]:
    """Отправить заявку на покупку в канал заказов"""
    try:
        print(f"DEBUG: Начинаем отправку в канал заказов...")
        
        user_info = order_data.get('username', 'без username')
        user_id = order_data.get('user_id')
        order_id = order_data.get('order_id', 'N/A')
        total_amount = order_data.get('total', 0)
        product_name = order_data.get('product_name', 'Неизвестный товар')
        product_price = order_data.get('product_price', 0)
        
        if user_info == 'без username':
            username_warning = "⚠️ ВНИМАНИЕ: У покупателя НЕТ USERNAME!"
        else:
            username_warning = ""
        
        message_text = f"""🛒 НОВЫЙ ЗАКАЗ

👤 Покупатель: @{user_info}
🆔 ID: {user_id}
📦 Товар: {product_name}
💰 Цена: {product_price:.2f}₽
💳 Способ оплаты: Ozon (СБП/Карта)
📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
🆔 ID заказа: {order_id}
"""
        
        if username_warning:
            message_text += f"\n{username_warning}"
        
        if screenshot_file_id:
            message_text += "\n📸 Прикреплен скриншот оплаты"
        
        db.add_pending_order(order_id, {
            'user_id': user_id,
            'username': user_info,
            'order_id': order_id,
            'total': total_amount,
            'product_name': product_name,
            'product_price': product_price,
            'payment_method': 'Ozon (СБП/Карта)',
            'date': datetime.now().isoformat(),
            'has_username': user_info != 'без username'
        })
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text='✅ Подтвердить заказ', callback_data=f'confirm_order_{order_id}'))
        builder.row(InlineKeyboardButton(text='❌ Отклонить', callback_data=f'reject_order_{order_id}'))
        
        if user_info == 'без username':
            builder.row(InlineKeyboardButton(text='⚠️ НЕТ USERNAME!', callback_data=f'no_username_{order_id}'))
        
        keyboard = builder.as_markup()
        
        if screenshot_file_id:
            message = await bot.send_photo(
                chat_id=config.ORDER_CHANNEL_ID,
                photo=screenshot_file_id,
                caption=message_text,
                reply_markup=keyboard
            )
        else:
            message = await bot.send_message(
                chat_id=config.ORDER_CHANNEL_ID,
                text=message_text,
                reply_markup=keyboard
            )
        
        print(f"✅ Заказ успешно отправлен в канал. Message ID: {message.message_id}")
        return message.message_id
        
    except Exception as e:
        print(f"❌ Критическая ошибка в send_to_order_channel: {e}")
        import traceback
        print(f"❌ Трассировка ошибки:\n{traceback.format_exc()}")
        return None

async def send_cart_to_order_channel(order_data: Dict, screenshot_file_id: str = None) -> Optional[int]:
    """Отправить заказ из корзины в канал заказов"""
    try:
        user_info = order_data.get('username', 'без username')
        user_id = order_data.get('user_id')
        order_id = order_data.get('order_id', 'N/A')
        cart_total = order_data.get('cart_total', {})
        
        if cart_total['items_count'] == 0:
            print("❌ Пустая корзина при отправке в канал")
            return None
        
        items_text = "📦 Состав заказа:\n"
        for item in cart_total['items']:
            items_text += f"• {item['name']} x{item['quantity']} = {item['item_total']:.2f}₽\n"
        
        message_text = f"""🛒 НОВЫЙ ЗАКАЗ ИЗ КОРЗИНЫ

👤 Покупатель: @{user_info}
🆔 ID: {user_id}
{items_text}
📦 Всего товаров: {cart_total['total_quantity']} шт.
💰 Общая сумма: {cart_total['total_amount']:.2f}₽
💳 Способ оплаты: Ozon (СБП/Карта)
📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
🆔 ID заказа: {order_id}
"""
        
        if user_info == 'без username':
            message_text += "\n⚠️ ВНИМАНИЕ: У покупателя НЕТ USERNAME!"
        
        if screenshot_file_id:
            message_text += "\n📸 Прикреплен скриншот оплаты"
        
        db.add_pending_order(order_id, {
            'user_id': user_id,
            'username': user_info,
            'order_id': order_id,
            'total': cart_total['total_amount'],
            'is_cart_order': True,
            'cart_items': cart_total['items'],
            'total_quantity': cart_total['total_quantity'],
            'payment_method': 'Ozon (СБП/Карта)',
            'date': datetime.now().isoformat(),
            'has_username': user_info != 'без username'
        })
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text='✅ Подтвердить заказ', callback_data=f'confirm_order_{order_id}'))
        builder.row(InlineKeyboardButton(text='❌ Отклонить', callback_data=f'reject_order_{order_id}'))
        
        if user_info == 'без username':
            builder.row(InlineKeyboardButton(text='⚠️ НЕТ USERNAME!', callback_data=f'no_username_{order_id}'))
        
        keyboard = builder.as_markup()
        
        if screenshot_file_id:
            message = await bot.send_photo(
                chat_id=config.ORDER_CHANNEL_ID,
                photo=screenshot_file_id,
                caption=message_text,
                reply_markup=keyboard
            )
        else:
            message = await bot.send_message(
                chat_id=config.ORDER_CHANNEL_ID,
                text=message_text,
                reply_markup=keyboard
            )
        
        print(f"✅ Заказ из корзины отправлен в канал. Message ID: {message.message_id}")
        return message.message_id
        
    except Exception as e:
        print(f"❌ Ошибка отправки заказа из корзины: {e}")
        import traceback
        print(f"❌ Трассировка ошибки:\n{traceback.format_exc()}")
        return None

# ==================== КЛАВИАТУРЫ ====================

def main_menu_kb(user_id: int = None) -> InlineKeyboardMarkup:
    """Главное меню с учетом прав администратора"""
    builder = InlineKeyboardBuilder()
    
    cart_count = cart_manager.get_cart_items_count(user_id) if user_id else 0
    cart_text = f'🛒 Корзина ({cart_count})' if cart_count > 0 else '🛒 Корзина'
    
    builder.row(InlineKeyboardButton(text='🛒 Посмотреть услуги', callback_data='view_categories'))
    builder.row(
        InlineKeyboardButton(text=cart_text, callback_data='view_cart'),
        InlineKeyboardButton(text='🎁 Реферальная программа', callback_data='referral_info')
    )
    builder.row(
        InlineKeyboardButton(text='🆘 Поддержка', callback_data='support'),
        InlineKeyboardButton(text='📝 Создать тикет', callback_data='create_ticket')
    )
    
    if user_id in config.ADMIN_IDS:
        builder.row(InlineKeyboardButton(text='👨‍💼 Админ-панель', callback_data='admin_panel'))
    
    return builder.as_markup()

def categories_kb() -> InlineKeyboardMarkup:
    """Категории товаров"""
    builder = InlineKeyboardBuilder()
    categories = db.get_categories()
    
    for category in categories:
        builder.row(InlineKeyboardButton(text=category["name"], callback_data=f"category_{category['id']}"))
    
    cart_count = cart_manager.get_cart_items_count(0)
    cart_text = f'🛒 Корзина ({cart_count})' if cart_count > 0 else '🛒 Корзина'
    
    builder.row(
        InlineKeyboardButton(text=cart_text, callback_data='view_cart'),
        InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu'),
    )
    return builder.as_markup()

def products_kb(category_id: int, page: int = 0, items_per_page: int = 10) -> InlineKeyboardMarkup:
    """Товары в категории с пагинацией"""
    builder = InlineKeyboardBuilder()
    products = db.get_products_by_category(category_id)
    
    if not products:
        builder.row(InlineKeyboardButton(text="📭 Нет товаров в этой категории", callback_data="no_action"))
    else:
        total_pages = max(1, (len(products) + items_per_page - 1) // items_per_page)
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(products))
        
        for product in products[start_idx:end_idx]:
            product_name = product['name']
            if len(product_name) > 25:
                product_name = product_name[:22] + "..."
            
            builder.row(InlineKeyboardButton(
                text=f"📦 {product_name} - {product['price']}₽",
                callback_data=f"product_{product['id']}"
            ))
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{category_id}_{page-1}"))
        
        if total_pages > 1:
            nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="no_action"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{category_id}_{page+1}"))
        
        if nav_buttons:
            builder.row(*nav_buttons)
    
    cart_count = cart_manager.get_cart_items_count(0)
    cart_text = f'🛒 Корзина ({cart_count})' if cart_count > 0 else '🛒 Корзина'
    
    builder.row(InlineKeyboardButton(text=cart_text, callback_data='view_cart'))
    builder.row(
        InlineKeyboardButton(text='🔙 Назад к категориям', callback_data='view_categories'),
        InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')
    )
    
    return builder.as_markup()

def product_detail_kb(product_id: int, category_id: int) -> InlineKeyboardMarkup:
    """Детали товара"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='🛒 Добавить в корзину', callback_data=f'add_to_cart_{product_id}'),
        InlineKeyboardButton(text='💳 Купить сейчас', callback_data=f'buy_product_{product_id}')
    )
    
    cart_count = cart_manager.get_cart_items_count(0)
    cart_text = f'🛒 Моя корзина ({cart_count})' if cart_count > 0 else '🛒 Моя корзина'
    
    builder.row(InlineKeyboardButton(text=cart_text, callback_data='view_cart'))
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data=f'category_{category_id}'),
        InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')
    )
    return builder.as_markup()

def cart_kb(cart_items: List[Dict], show_checkout: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура для управления корзиной"""
    builder = InlineKeyboardBuilder()
    
    for item in cart_items:
        product = db.get_product(item['product_id'])
        if product:
            product_name = product['name']
            if len(product_name) > 20:
                product_name = product_name[:17] + "..."
            
            builder.row(InlineKeyboardButton(
                text=f"➖ {product_name} x{item['quantity']}",
                callback_data=f"cart_remove_{item['product_id']}"
            ))
    
    if cart_items:
        if show_checkout:
            builder.row(
                InlineKeyboardButton(text='✅ Оформить заказ', callback_data='cart_checkout'),
                InlineKeyboardButton(text='🗑️ Очистить корзину', callback_data='cart_clear')
            )
        
        builder.row(
            InlineKeyboardButton(text='➕ Добавить еще товары', callback_data='view_categories'),
            InlineKeyboardButton(text='✏️ Изменить количество', callback_data='cart_edit_quantity')
        )
    
    builder.row(InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu'))
    
    return builder.as_markup()

def cart_checkout_kb() -> InlineKeyboardMarkup:
    """Клавиатура для оформления заказа из корзины"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='✅ Подтвердить заказ', callback_data='cart_confirm_payment'),
        InlineKeyboardButton(text='✏️ Изменить корзину', callback_data='view_cart')
    )
    builder.row(InlineKeyboardButton(text='❌ Отменить', callback_data='main_menu'))
    return builder.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text='❌ Отмена', callback_data='main_menu'))
    return builder.as_markup()

def admin_panel_kb() -> InlineKeyboardMarkup:
    """Клавиатура админ-панели"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='📦 Управление товарами', callback_data='admin_products'),
        InlineKeyboardButton(text='📁 Управление категориями', callback_data='admin_categories')
    )
    builder.row(
        InlineKeyboardButton(text='👥 Пользователи', callback_data='admin_users'),
        InlineKeyboardButton(text='📊 Статистика', callback_data='admin_stats')
    )
    builder.row(
        InlineKeyboardButton(text='⏳ Ожидающие заявки', callback_data='admin_pending'),
        InlineKeyboardButton(text='🎁 Реферальная программа', callback_data='admin_referral')
    )
    builder.row(
        InlineKeyboardButton(text='💬 Управление чатами', callback_data='admin_chats'),
        InlineKeyboardButton(text='🎫 Управление тикетами', callback_data='admin_tickets')
    )
    builder.row(
        InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu')
    )
    return builder.as_markup()

def admin_products_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления товарами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='➕ Добавить товар', callback_data='admin_add_product'),
        InlineKeyboardButton(text='🗑️ Удалить товар', callback_data='admin_delete_product')
    )
    builder.row(
        InlineKeyboardButton(text='📋 Список товаров', callback_data='admin_list_products')
    )
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
    )
    return builder.as_markup()

def admin_categories_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления категориями"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='➕ Добавить категорию', callback_data='admin_add_category'),
        InlineKeyboardButton(text='📋 Список категорий', callback_data='admin_list_categories')
    )
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
    )
    return builder.as_markup()

def admin_referral_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления реферальной программой"""
    builder = InlineKeyboardBuilder()
    config_ref = Config.REFERRAL_CONFIG
    status_text = '✅ Включена' if config_ref['enabled'] else '❌ Выключена'
    
    builder.row(
        InlineKeyboardButton(text=f'🔄 Статус: {status_text}', callback_data='admin_referral_toggle')
    )
    builder.row(
        InlineKeyboardButton(text='💰 Изменить мин. сумму', callback_data='admin_referral_amount'),
        InlineKeyboardButton(text='🎁 Изменить награду', callback_data='admin_referral_reward')
    )
    builder.row(
        InlineKeyboardButton(text='📊 Детальная статистика', callback_data='admin_referral_stats'),
        InlineKeyboardButton(text='📋 Список рефералов', callback_data='admin_referral_list')
    )
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
    )
    return builder.as_markup()

def admin_list_products_kb() -> InlineKeyboardMarkup:
    """Клавиатура списка товаров"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data='admin_products')
    )
    return builder.as_markup()

def admin_list_categories_kb() -> InlineKeyboardMarkup:
    """Клавиатура списка категорий"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text='🔙 Назад', callback_data='admin_categories')
    )
    return builder.as_markup()

def admin_chats_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления чатами"""
    builder = InlineKeyboardBuilder()
    
    active_chats = ticket_manager.active_chats
    
    if active_chats:
        for user_id, chat_data in active_chats.items():
            username = chat_data.get('username', f'user_{user_id}')
            if len(username) > 20:
                username = username[:17] + "..."
            builder.row(InlineKeyboardButton(
                text=f"💬 Чат с {username}",
                callback_data=f"admin_open_chat_{user_id}"
            ))
        builder.row(InlineKeyboardButton(
            text='📋 Список всех чатов',
            callback_data='admin_list_chats'
        ))
    else:
        builder.row(InlineKeyboardButton(
            text='📭 Нет активных чатов',
            callback_data='no_action'
        ))
    
    builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel'))
    return builder.as_markup()

def admin_tickets_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления тикетами"""
    builder = InlineKeyboardBuilder()
    
    open_tickets = ticket_manager.tickets
    
    if open_tickets:
        for user_id, ticket_data in open_tickets.items():
            username = ticket_data.get('username', f'user_{user_id}')
            if len(username) > 20:
                username = username[:17] + "..."
            builder.row(InlineKeyboardButton(
                text=f"🎫 Тикет от {username}",
                callback_data=f"admin_view_ticket_{user_id}"
            ))
    else:
        builder.row(InlineKeyboardButton(
            text='📭 Нет открытых тикетов',
            callback_data='no_action'
        ))
    
    builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel'))
    return builder.as_markup()

def chat_kb(user_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для чата"""
    builder = InlineKeyboardBuilder()
    
    if is_admin:
        builder.row(InlineKeyboardButton(
            text='🔒 Завершить чат',
            callback_data=f'close_chat_{user_id}'
        ))
        builder.row(InlineKeyboardButton(
            text='🔙 В админ-панель',
            callback_data='admin_panel'
        ))
    else:
        builder.row(InlineKeyboardButton(
            text='❌ Закрыть чат',
            callback_data='close_chat_user'
        ))
        builder.row(InlineKeyboardButton(
            text='🔙 Главное меню',
            callback_data='main_menu'
        ))
    
    return builder.as_markup()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """Обработка команды /start с проверкой подписки"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        
        # Проверяем наличие юзернейма
        if not username:
            warning_text = """⚠️ ВНИМАНИЕ!

У вас не установлен username в Telegram.

Это может привести к проблемам:
1. Я не смогу связаться с вами для отправки товара
2. Администраторы не смогут уточнить детали заказа

📌 Как установить username:
1. Откройте Настройки Telegram
2. Выберите "Имя пользователя" (Username)
3. Установите уникальное имя (например, @ivan_ivanov)
4. Сохраните изменения

После установки username нажмите /start снова."""
            
            await message.answer(text=warning_text, reply_markup=main_menu_kb(user_id))
            return
        
        # Проверяем подписку на канал
        is_subscribed = await check_subscription(user_id)
        
        if not is_subscribed:
            # Сохраняем, что пользователь пытался зайти
            await state.update_data(pending_start=True)
            
            # Показываем сообщение о необходимости подписки
            sub_text = f"""📢 Для доступа к боту необходимо подписаться на наш канал!

👉 {config.REQUIRED_CHANNEL_URL}

На канале вы найдете:
• Актуальные новости
• Специальные предложения
• Новые поступления товаров

После подписки нажмите кнопку "✅ Я подписался(ась)" для проверки."""

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text='📢 Подписаться на канал',
                url=config.REQUIRED_CHANNEL_URL
            ))
            builder.row(InlineKeyboardButton(
                text='✅ Я подписался(ась)',
                callback_data='check_subscription'
            ))
            
            await message.answer(text=sub_text, reply_markup=builder.as_markup())
            return
        
        # Если есть реферальный код в параметрах
        args = message.text.split()
        if len(args) > 1:
            referral_code = args[1]
            await process_referral(user_id, referral_code)
        
        # Регистрируем пользователя
        user_data = db.get_user(user_id)
        user_data["is_subscribed"] = True
        user_data["subscription_checked_at"] = datetime.now().isoformat()
        db.save_users_data()
        
        # Показываем информацию о реферальной программе
        ref_info = await get_referral_info(user_id)
        
        # Показываем количество товаров в корзине
        cart_count = cart_manager.get_cart_items_count(user_id)
        cart_info = f"\n🛒 Товаров в корзине: {cart_count}" if cart_count > 0 else ""
        
        welcome_text = f"""👋 Добро пожаловать, @{username}!{cart_info}

✨ Возможности:
• 🛒 Просмотр и покупка услуг
• 🛍️ Корзина для покупки нескольких товаров
• 💳 Оплата через Ozon (СБП/Карта)
• ✅ Подтверждение заказов администраторами
• 💬 Чат с поддержкой
• 🎫 Система тикетов

{ref_info}

Используйте кнопки ниже для навигации:
"""
        
        await message.answer(
            text=welcome_text,
            reply_markup=main_menu_kb(user_id)
        )
        
    except Exception as e:
        print(f"Ошибка при обработке /start: {e}")
        await message.answer("❌ Произошла ошибка при запуске")

@dp.message(Command("support"))
async def handle_support_command(message: Message):
    """Обработка команды /support"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        support_text = f"""🆘 Поддержка

По всем вопросам обращайтесь:
👨‍💼 Администратор: {config.ADMIN_USERNAME}

📞 Контакты:
• Telegram: {config.ADMIN_USERNAME}
• Наш бот: @{message.bot.username}

🕐 Режим работы: 24/7
⏱️ Среднее время ответа: 5-15 минут

💬 Мы поможем с:
• Выбором и оформлением заказа
• Оплатой товара
• Получением товара
• Возвратом средств
• Техническими проблемами
• Реферальной программой

📝 Для связи с поддержкой используйте кнопку "Создать тикет" в главном меню.

Ваш ID для связи: {user_id}
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text='💬 Написать администратору',
                url=f'https://t.me/{config.ADMIN_USERNAME.replace("@", "")}'
            )
        )
        builder.row(
            InlineKeyboardButton(text='📝 Создать тикет', callback_data='create_ticket'),
            InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')
        )
        
        await message.answer(
            text=support_text,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"Ошибка при обработке команды /support: {e}")
        await message.answer("❌ Произошла ошибка при загрузке информации о поддержке")

@dp.message(Command("admin"))
async def handle_admin_command(message: Message):
    """Обработка команды /admin"""
    try:
        user_id = message.from_user.id
        
        if user_id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            return
        
        active_chats = len(ticket_manager.active_chats)
        open_tickets = len(ticket_manager.tickets)
        
        admin_text = f"""👨‍💼 Админ-панель

📊 Текущая ситуация:
• 💬 Активных чатов: {active_chats}
• 🎫 Открытых тикетов: {open_tickets}

Доступные команды:
• /addproduct - Добавить новый товар
• /addcategory <название> - Добавить категорию
• /stats - Показать статистику
• /referral_stats - Статистика рефералов

Или используйте кнопки ниже:
"""
        
        await message.answer(
            text=admin_text,
            reply_markup=admin_panel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при обработке /admin: {e}")
        await message.answer("❌ Ошибка при загрузке админ-панели")

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data == 'main_menu')
async def handle_main_menu(callback: CallbackQuery, state: FSMContext):
    """Обработка перехода в главное меню"""
    try:
        await state.clear()
        
        # Если пользователь был в режиме чата, выходим из него
        current_state = await state.get_state()
        if current_state == TicketStates.chat_mode:
            await state.set_state(None)
        
        await callback.message.edit_text(
            text="🏠 Главное меню\n\nВыберите действие:",
            reply_markup=main_menu_kb(callback.from_user.id)
        )
        
    except Exception as e:
        print(f"Ошибка при переходе в главное меню: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'view_categories')
async def handle_view_categories(callback: CallbackQuery):
    """Показать список категорий"""
    try:
        categories = db.get_categories()
        
        if not categories:
            text = "📭 Категории пока отсутствуют"
        else:
            text = "📁 Выберите категорию:"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=categories_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при загрузке категорий: {e}")
        await callback.answer("Ошибка загрузки категорий", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('category_'))
async def handle_category_products(callback: CallbackQuery):
    """Показать товары в выбранной категории"""
    try:
        _, category_id_str = callback.data.split('_')
        category_id = int(category_id_str)
        
        category = db.get_category(category_id)
        products = db.get_products_by_category(category_id)
        
        if not products:
            category_name = category.get('name', 'Неизвестно') if category else 'Неизвестно'
            text = f"📭 В категории '{category_name}' пока нет товаров"
        else:
            category_name = category.get('name', 'Неизвестно') if category else 'Неизвестно'
            items_per_page = 5
            total_pages = max(1, (len(products) + items_per_page - 1) // items_per_page)
            
            text = f"🛒 Товары в категории '{category_name}':\n"
            text += f"📄 Показано 1-{min(items_per_page, len(products))} из {len(products)} товаров\n\n"
            text += "Выберите товар:"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=products_kb(category_id, page=0)
        )
        
    except ValueError:
        await callback.answer("Неверный ID категории", show_alert=True)
    except Exception as e:
        print(f"Ошибка при загрузке товаров категории: {e}")
        await callback.answer("Ошибка загрузки товаров", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('product_'))
async def handle_product_detail(callback: CallbackQuery):
    """Показать детали товара"""
    try:
        _, product_id_str = callback.data.split('_')
        product_id = int(product_id_str)
        
        product = db.get_product(product_id)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        category = db.get_category(product["category_id"])
        
        cart_count = cart_manager.get_cart_items_count(callback.from_user.id)
        cart_info = f"\n🛒 Товаров в корзине: {cart_count}" if cart_count > 0 else ""
        
        product_text = f"""📦 {product['name']}{cart_info}

💰 Цена: {product['price']:.2f}₽
📝 Описание: {product.get('description', 'Нет описания')}
📊 В наличии: {product.get('quantity', 9999)} шт.
📁 Категория: {category.get('name', 'Не указана') if category else 'Не указана'}
"""
        
        await callback.message.edit_text(
            text=product_text,
            reply_markup=product_detail_kb(product_id, product["category_id"])
        )
        
    except ValueError:
        await callback.answer("Неверный ID товара", show_alert=True)
    except Exception as e:
        print(f"Ошибка при загрузке товара: {e}")
        await callback.answer("Ошибка загрузки товара", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'referral_info')
async def handle_referral_info(callback: CallbackQuery):
    """Показывает информацию о реферальной программе"""
    try:
        user_id = callback.from_user.id
        ref_info = await get_referral_info(user_id)
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text='📢 Пригласить друзей', callback_data='share_referral'),
            InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu')
        )
        
        await callback.message.edit_text(
            text=ref_info,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'share_referral')
async def handle_share_referral(callback: CallbackQuery):
    """Поделиться реферальной ссылкой"""
    try:
        user_id = callback.from_user.id
        user_data = db.get_user(user_id)
        
        bot_username = (await bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user_data['referral_code']}"
        
        share_text = f"""🎁 МОЯ РЕФЕРАЛЬНАЯ ССЫЛКА

🔗 {referral_link}

📋 Отправьте эту ссылку друзьям!
Когда они совершат первую покупку от {Config.REFERRAL_CONFIG['min_purchase_amount']}₽, вы получите награду!

💡 Скопируйте ссылку и отправьте в личные сообщения или чаты."""

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text='📋 Скопировать ссылку',
            callback_data=f'copy_{referral_link}'
        ))
        builder.row(InlineKeyboardButton(
            text='🔙 Назад',
            callback_data='referral_info'
        ))
        
        await callback.message.edit_text(
            text=share_text,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('copy_'))
async def handle_copy_link(callback: CallbackQuery):
    """Обработка копирования ссылки"""
    try:
        link = callback.data.replace('copy_', '')
        await callback.answer(f"Ссылка скопирована: {link}", show_alert=True)
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == 'check_subscription')
async def handle_check_subscription(callback: CallbackQuery, state: FSMContext):
    """Проверяет подписку пользователя"""
    try:
        user_id = callback.from_user.id
        
        is_subscribed = await check_subscription(user_id)
        
        if is_subscribed:
            user_data = db.get_user(user_id)
            user_data["is_subscribed"] = True
            user_data["subscription_checked_at"] = datetime.now().isoformat()
            db.save_users_data()
            
            data = await state.get_data()
            if data.get('pending_start'):
                await state.clear()
                # Создаем новое сообщение как при /start
                await handle_start(callback.message, state)
            else:
                ref_info = await get_referral_info(user_id)
                
                await callback.message.edit_text(
                    text=f"""✅ Спасибо за подписку!

{ref_info}

Теперь вы можете пользоваться ботом!""",
                    reply_markup=main_menu_kb(user_id)
                )
        else:
            await callback.answer(
                "❌ Вы еще не подписались на канал! Подпишитесь и попробуйте снова.",
                show_alert=True
            )
            
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        await callback.answer("Ошибка при проверке", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'support')
async def handle_support(callback: CallbackQuery):
    """Обработка кнопки поддержки"""
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.first_name
        
        support_text = f"""🆘 Поддержка

По всем вопросам обращайтесь:
👨‍💼 Администратор: {config.ADMIN_USERNAME}

🕐 Время ответа: 24/7
💬 Мы поможем с:
• Оформлением заказа
• Оплатой товара
• Получением товара
• Техническими проблемами
• Реферальной программой

📝 Для связи с поддержкой используйте кнопку "Создать тикет" в главном меню.

Ваш ID для связи: {user_id}
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text='💬 Написать администратору',
                url=f'https://t.me/{config.ADMIN_USERNAME.replace("@", "")}'
            )
        )
        builder.row(
            InlineKeyboardButton(text='📝 Создать тикет', callback_data='create_ticket'),
            InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu')
        )
        
        await callback.message.edit_text(
            text=support_text,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"Ошибка при обработке поддержки: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await callback.answer()

# ==================== СИСТЕМА ТИКЕТОВ ====================

@dp.callback_query(F.data == 'create_ticket')
async def handle_create_ticket(callback: CallbackQuery, state: FSMContext):
    """Создание нового тикета"""
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username or f"user_{user_id}"
        
        # Проверяем, есть ли уже активный тикет
        if ticket_manager.has_active_ticket(user_id):
            ticket = ticket_manager.get_user_ticket(user_id)
            await callback.answer("❌ У вас уже есть активный тикет! Дождитесь ответа администратора.", show_alert=True)
            
            # Отправляем напоминание
            await callback.message.edit_text(
                text=f"❌ У вас уже есть активный тикет #{ticket['ticket_id']}\n\n"
                     f"Администратор скоро ответит вам.\n"
                     f"Если хотите закрыть тикет - используйте кнопку ниже.",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='❌ Закрыть тикет', callback_data='close_my_ticket'))
                    .add(InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu'))
                    .adjust(1)
                    .as_markup()
            )
            return
        
        await state.set_state(TicketStates.waiting_for_ticket_text)
        
        await callback.message.edit_text(
            text="📝 **Создание тикета в поддержку**\n\n"
                 "Опишите вашу проблему или вопрос как можно подробнее:\n\n"
                 "• Укажите номер заказа (если есть)\n"
                 "• Опишите ситуацию\n"
                 "• Приложите скриншоты (если нужно)\n\n"
                 "💡 Вы можете отправить текстовое сообщение или фото с описанием.\n\n"
                 "Нажмите ❌ Отмена, чтобы вернуться в меню.",
            reply_markup=cancel_kb(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка при создании тикета: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.message(TicketStates.waiting_for_ticket_text, F.text)
async def handle_ticket_text(message: Message, state: FSMContext):
    """Обработка текста тикета"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or f"user_{user_id}"
        ticket_text = message.text.strip()
        
        if len(ticket_text) < 5:
            await message.answer(
                "❌ Слишком короткое сообщение. Пожалуйста, опишите проблему подробнее:",
                reply_markup=cancel_kb()
            )
            return
        
        # Создаем тикет
        ticket = ticket_manager.create_ticket(user_id, username, ticket_text)
        
        if not ticket:
            await message.answer(
                "❌ Не удалось создать тикет. Возможно, у вас уже есть активный тикет.",
                reply_markup=main_menu_kb(user_id)
            )
            await state.clear()
            return
        
        # Отправляем уведомление администратору в закрытый канал
        ticket_message = f"""🎫 **НОВЫЙ ТИКЕТ**

🆔 **ID пользователя:** `{user_id}`
👤 **Username:** @{username}
📅 **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
🆔 **Тикет ID:** `{ticket['ticket_id']}`

📝 **Текст обращения:**
{ticket_text}

---

🔘 **Действия:**
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text='💬 Ответить (создать чат)',
                callback_data=f'answer_ticket_{user_id}'
            )
        )
        builder.row(
            InlineKeyboardButton(
                text='❌ Закрыть тикет',
                callback_data=f'close_ticket_{user_id}'
            )
        )
        
        await bot.send_message(
            chat_id=config.TICKET_CHANNEL_ID,
            text=ticket_message,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
        # Подтверждение пользователю
        await message.answer(
            text=f"✅ **Тикет успешно создан!**\n\n"
                 f"🆔 Номер тикета: `{ticket['ticket_id']}`\n\n"
                 f"Администратор скоро ответит вам.\n"
                 f"Вы получите уведомление, когда ответ появится.\n\n"
                 f"💡 Для закрытия тикета используйте кнопку ниже.",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='❌ Закрыть тикет', callback_data='close_my_ticket'))
                .add(InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu'))
                .adjust(1)
                .as_markup(),
            parse_mode='Markdown'
        )
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка при обработке текста тикета: {e}")
        await message.answer("❌ Ошибка при создании тикета", reply_markup=main_menu_kb(message.from_user.id))
        await state.clear()

@dp.message(TicketStates.waiting_for_ticket_text, F.photo)
async def handle_ticket_photo(message: Message, state: FSMContext):
    """Обработка тикета с фото"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or f"user_{user_id}"
        
        # Получаем подпись к фото
        caption = message.caption if message.caption else "Нет описания"
        
        if len(caption) < 3 and caption != "Нет описания":
            await message.answer(
                "❌ Пожалуйста, добавьте описание к фото:",
                reply_markup=cancel_kb()
            )
            return
        
        # Создаем тикет
        ticket_text = f"[Фото] {caption}"
        ticket = ticket_manager.create_ticket(user_id, username, ticket_text)
        
        if not ticket:
            await message.answer(
                "❌ Не удалось создать тикет. Возможно, у вас уже есть активный тикет.",
                reply_markup=main_menu_kb(user_id)
            )
            await state.clear()
            return
        
        # Получаем file_id фото
        photo_file_id = message.photo[-1].file_id
        
        # Отправляем уведомление администратору с фото
        ticket_message = f"""🎫 **НОВЫЙ ТИКЕТ (С ФОТО)**

🆔 **ID пользователя:** `{user_id}`
👤 **Username:** @{username}
📅 **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
🆔 **Тикет ID:** `{ticket['ticket_id']}`

📝 **Описание:**
{caption}

---

🔘 **Действия:**
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text='💬 Ответить (создать чат)',
                callback_data=f'answer_ticket_{user_id}'
            )
        )
        builder.row(
            InlineKeyboardButton(
                text='❌ Закрыть тикет',
                callback_data=f'close_ticket_{user_id}'
            )
        )
        
        await bot.send_photo(
            chat_id=config.TICKET_CHANNEL_ID,
            photo=photo_file_id,
            caption=ticket_message,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
        # Подтверждение пользователю
        await message.answer(
            text=f"✅ **Тикет успешно создан!**\n\n"
                 f"🆔 Номер тикета: `{ticket['ticket_id']}`\n\n"
                 f"Администратор скоро ответит вам.\n"
                 f"Вы получите уведомление, когда ответ появится.\n\n"
                 f"💡 Для закрытия тикета используйте кнопку ниже.",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='❌ Закрыть тикет', callback_data='close_my_ticket'))
                .add(InlineKeyboardButton(text='🔙 Главное меню', callback_data='main_menu'))
                .adjust(1)
                .as_markup(),
            parse_mode='Markdown'
        )
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка при обработке фото тикета: {e}")
        await message.answer("❌ Ошибка при создании тикета", reply_markup=main_menu_kb(message.from_user.id))
        await state.clear()

@dp.callback_query(F.data == 'close_my_ticket')
async def handle_close_my_ticket(callback: CallbackQuery):
    """Закрыть свой тикет"""
    try:
        user_id = callback.from_user.id
        
        if not ticket_manager.has_active_ticket(user_id):
            await callback.answer("❌ У вас нет активных тикетов", show_alert=True)
            await callback.message.edit_text(
                text="У вас нет активных тикетов.",
                reply_markup=main_menu_kb(user_id)
            )
            return
        
        ticket_manager.close_ticket(user_id)
        
        await callback.message.edit_text(
            text="✅ Ваш тикет закрыт.\n\nЕсли у вас остались вопросы - создайте новый тикет.",
            reply_markup=main_menu_kb(user_id)
        )
        
    except Exception as e:
        print(f"Ошибка при закрытии тикета: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

# ==================== СИСТЕМА ЧАТОВ ====================

@dp.callback_query(F.data.startswith('answer_ticket_'))
async def handle_answer_ticket(callback: CallbackQuery, state: FSMContext):
    """Ответ на тикет - создание чата"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('answer_ticket_', ''))
        
        # Получаем информацию о пользователе
        user_data = db.get_user(user_id)
        username = callback.from_user.username or f"user_{user_id}"
        
        # Проверяем, есть ли уже активный чат
        if ticket_manager.has_active_chat(user_id):
            await callback.answer("⚠️ Чат с этим пользователем уже активен!", show_alert=True)
            return
        
        # Создаем чат
        chat = ticket_manager.create_chat(user_id, username)
        
        # Закрываем тикет
        ticket_manager.close_ticket(user_id)
        
        # Отправляем сообщение пользователю
        user_message = f"""💬 **Чат с поддержкой открыт!**

Администратор подключился к диалогу.

Теперь вы можете общаться напрямую с поддержкой.
Просто отправьте сообщение в этот чат.

Для завершения диалога используйте кнопку ниже.

💡 **Важно:** Все сообщения сохраняются в истории."""
        
        await bot.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=chat_kb(user_id, is_admin=False),
            parse_mode='Markdown'
        )
        
        # Обновляем сообщение в канале тикетов
        await callback.message.edit_text(
            text=f"{callback.message.text}\n\n✅ **Чат создан!**\nАдминистратор @{callback.from_user.username} ответил пользователю.",
            parse_mode='Markdown'
        )
        
        # Устанавливаем состояние чата для админа
        await state.set_state(TicketStates.chat_mode)
        await state.update_data(chat_user_id=user_id)
        
        await callback.message.answer(
            f"✅ **Чат с пользователем {username} (ID: {user_id}) открыт!**\n\n"
            f"Теперь вы можете общаться. Все сообщения, которые вы отправите сюда, будут переданы пользователю.\n"
            f"Для завершения чата используйте кнопку ниже.",
            reply_markup=chat_kb(user_id, is_admin=True)
        )
        
    except Exception as e:
        print(f"Ошибка при ответе на тикет: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('close_chat_'))
async def handle_close_chat(callback: CallbackQuery, state: FSMContext):
    """Закрыть чат (администратор)"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('close_chat_', ''))
        
        # Закрываем чат
        ticket_manager.close_chat(user_id)
        
        # Уведомляем пользователя
        await bot.send_message(
            chat_id=user_id,
            text="🔒 **Чат закрыт администратором.**\n\nСпасибо за обращение! Если остались вопросы - создайте новый тикет.",
            reply_markup=main_menu_kb(user_id),
            parse_mode='Markdown'
        )
        
        await callback.message.edit_text(
            text=f"✅ **Чат с пользователем (ID: {user_id}) закрыт.**\n\nВозврат в админ-панель...",
            reply_markup=admin_panel_kb()
        )
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка при закрытии чата: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'close_chat_user')
async def handle_close_chat_user(callback: CallbackQuery, state: FSMContext):
    """Закрыть чат (пользователь)"""
    try:
        user_id = callback.from_user.id
        
        # Закрываем чат
        ticket_manager.close_chat(user_id)
        
        # Уведомляем администратора
        for admin_id in config.ADMIN_IDS:
            await bot.send_message(
                chat_id=admin_id,
                text=f"🔒 **Пользователь {user_id} закрыл чат.**\n\nЧат завершен по инициативе пользователя."
            )
        
        await callback.message.edit_text(
            text="✅ **Чат закрыт.**\n\nСпасибо за обращение! Если остались вопросы - создайте новый тикет.",
            reply_markup=main_menu_kb(user_id)
        )
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка при закрытии чата пользователем: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.message(TicketStates.chat_mode)
async def handle_chat_message(message: Message, state: FSMContext):
    """Обработка сообщений в режиме чата"""
    try:
        user_id = message.from_user.id
        data = await state.get_data()
        chat_user_id = data.get('chat_user_id')
        
        # Администратор пишет пользователю
        if user_id in config.ADMIN_IDS and chat_user_id:
            # Проверяем, активен ли чат
            if not ticket_manager.has_active_chat(chat_user_id):
                await message.answer("❌ Чат уже закрыт. Пользователь завершил диалог.")
                await state.clear()
                return
            
            # Отправляем сообщение пользователю
            if message.text:
                await bot.send_message(
                    chat_id=chat_user_id,
                    text=f"💬 **Поддержка:** {message.text}",
                    parse_mode='Markdown'
                )
                # Сохраняем в историю
                ticket_manager.add_message_to_chat(chat_user_id, message.text, is_from_admin=True)
                await message.answer("✅ Сообщение отправлено пользователю.")
            elif message.photo:
                photo_file_id = message.photo[-1].file_id
                caption = message.caption if message.caption else None
                await bot.send_photo(
                    chat_id=chat_user_id,
                    photo=photo_file_id,
                    caption=f"💬 **Поддержка:** {caption}" if caption else "💬 **Поддержка отправила фото**",
                    parse_mode='Markdown'
                )
                await message.answer("✅ Фото отправлено пользователю.")
            else:
                await message.answer("❌ Поддерживаются только текстовые сообщения и фото.")
        
        # Пользователь пишет администратору
        elif user_id not in config.ADMIN_IDS:
            # Проверяем, активен ли чат
            if not ticket_manager.has_active_chat(user_id):
                await message.answer("❌ Чат закрыт. Создайте новый тикет для связи с поддержкой.")
                await state.clear()
                return
            
            # Сохраняем сообщение в историю
            if message.text:
                ticket_manager.add_message_to_chat(user_id, message.text, is_from_admin=False)
                
                # Отправляем всем администраторам
                for admin_id in config.ADMIN_IDS:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=f"💬 **Сообщение от пользователя {user_id}:**\n\n{message.text}",
                        reply_markup=InlineKeyboardBuilder()
                            .add(InlineKeyboardButton(
                                text='💬 Ответить',
                                callback_data=f'answer_in_chat_{user_id}'
                            ))
                            .as_markup(),
                        parse_mode='Markdown'
                    )
                
                await message.answer("✅ Сообщение отправлено в поддержку.")
            elif message.photo:
                photo_file_id = message.photo[-1].file_id
                caption = message.caption if message.caption else "Фото от пользователя"
                ticket_manager.add_message_to_chat(user_id, f"[Фото] {caption}", is_from_admin=False)
                
                for admin_id in config.ADMIN_IDS:
                    await bot.send_photo(
                        chat_id=admin_id,
                        photo=photo_file_id,
                        caption=f"💬 **Фото от пользователя {user_id}:**\n\n{caption}",
                        reply_markup=InlineKeyboardBuilder()
                            .add(InlineKeyboardButton(
                                text='💬 Ответить',
                                callback_data=f'answer_in_chat_{user_id}'
                            ))
                            .as_markup(),
                        parse_mode='Markdown'
                    )
                
                await message.answer("✅ Фото отправлено в поддержку.")
            else:
                await message.answer("❌ Поддерживаются только текстовые сообщения и фото.")
        
    except Exception as e:
        print(f"Ошибка при обработке сообщения в чате: {e}")
        await message.answer("❌ Ошибка при отправке сообщения")

@dp.callback_query(F.data.startswith('answer_in_chat_'))
async def handle_answer_in_chat(callback: CallbackQuery, state: FSMContext):
    """Ответить в существующий чат"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('answer_in_chat_', ''))
        
        # Проверяем, активен ли чат
        if not ticket_manager.has_active_chat(user_id):
            await callback.answer("❌ Чат уже закрыт!", show_alert=True)
            return
        
        # Устанавливаем состояние чата
        await state.set_state(TicketStates.chat_mode)
        await state.update_data(chat_user_id=user_id)
        
        await callback.message.answer(
            f"💬 **Режим чата с пользователем {user_id}**\n\n"
            f"Теперь все ваши сообщения будут отправляться пользователю.\n"
            f"Для выхода из режима чата нажмите 'Завершить чат'.",
            reply_markup=chat_kb(user_id, is_admin=True)
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

# ==================== АДМИН-ПАНЕЛЬ (ЧАТЫ И ТИКЕТЫ) ====================

@dp.callback_query(F.data == 'admin_chats')
async def handle_admin_chats(callback: CallbackQuery):
    """Управление чатами"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        active_chats = ticket_manager.active_chats
        
        if not active_chats:
            text = "💬 **Активные чаты**\n\n📭 Нет активных чатов."
        else:
            text = f"💬 **Активные чаты ({len(active_chats)})**\n\n"
            for uid, chat_data in active_chats.items():
                username = chat_data.get('username', f'user_{uid}')
                started_at = datetime.fromisoformat(chat_data['started_at']).strftime('%d.%m %H:%M')
                text += f"• @{username} (ID: {uid}) - с {started_at}\n"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=admin_chats_kb(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_tickets')
async def handle_admin_tickets(callback: CallbackQuery):
    """Управление тикетами"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        open_tickets = ticket_manager.tickets
        
        if not open_tickets:
            text = "🎫 **Открытые тикеты**\n\n📭 Нет открытых тикетов."
        else:
            text = f"🎫 **Открытые тикеты ({len(open_tickets)})**\n\n"
            for uid, ticket_data in open_tickets.items():
                username = ticket_data.get('username', f'user_{uid}')
                created_at = datetime.fromisoformat(ticket_data['created_at']).strftime('%d.%m %H:%M')
                ticket_preview = ticket_data['text'][:50] + "..." if len(ticket_data['text']) > 50 else ticket_data['text']
                text += f"• @{username} (ID: {uid})\n  📝 {ticket_preview}\n  🕐 {created_at}\n\n"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=admin_tickets_kb(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_open_chat_'))
async def handle_admin_open_chat(callback: CallbackQuery, state: FSMContext):
    """Открыть чат с пользователем из админ-панели"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('admin_open_chat_', ''))
        
        # Проверяем, активен ли чат
        if not ticket_manager.has_active_chat(user_id):
            await callback.answer("❌ Чат уже закрыт!", show_alert=True)
            await handle_admin_chats(callback)
            return
        
        # Устанавливаем состояние чата
        await state.set_state(TicketStates.chat_mode)
        await state.update_data(chat_user_id=user_id)
        
        await callback.message.answer(
            f"💬 **Режим чата с пользователем {user_id}**\n\n"
            f"Теперь все ваши сообщения будут отправляться пользователю.\n"
            f"Для выхода из режима чата нажмите 'Завершить чат'.",
            reply_markup=chat_kb(user_id, is_admin=True)
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_view_ticket_'))
async def handle_admin_view_ticket(callback: CallbackQuery):
    """Просмотр тикета"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('admin_view_ticket_', ''))
        
        ticket = ticket_manager.get_user_ticket(user_id)
        
        if not ticket:
            await callback.answer("❌ Тикет не найден или уже закрыт", show_alert=True)
            await handle_admin_tickets(callback)
            return
        
        text = f"""🎫 **Детали тикета**

🆔 **ID пользователя:** `{user_id}`
👤 **Username:** @{ticket['username']}
🆔 **Тикет ID:** `{ticket['ticket_id']}`
📅 **Создан:** {datetime.fromisoformat(ticket['created_at']).strftime('%d.%m.%Y %H:%M:%S')}

📝 **Текст обращения:**
{ticket['text']}

---

🔘 **Действия:**
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text='💬 Ответить (создать чат)',
                callback_data=f'answer_ticket_{user_id}'
            )
        )
        builder.row(
            InlineKeyboardButton(
                text='❌ Закрыть тикет',
                callback_data=f'close_ticket_{user_id}'
            )
        )
        builder.row(
            InlineKeyboardButton(
                text='🔙 Назад',
                callback_data='admin_tickets'
            )
        )
        
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('close_ticket_'))
async def handle_admin_close_ticket(callback: CallbackQuery):
    """Закрыть тикет администратором"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        user_id = int(callback.data.replace('close_ticket_', ''))
        
        ticket_manager.close_ticket(user_id)
        
        # Уведомляем пользователя
        await bot.send_message(
            chat_id=user_id,
            text="🎫 **Ваш тикет закрыт администратором.**\n\nЕсли у вас остались вопросы - создайте новый тикет.",
            reply_markup=main_menu_kb(user_id),
            parse_mode='Markdown'
        )
        
        await callback.answer("✅ Тикет закрыт", show_alert=True)
        
        # Обновляем сообщение
        await callback.message.edit_text(
            text=f"{callback.message.text}\n\n✅ **Тикет закрыт администратором**",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_list_chats')
async def handle_admin_list_chats(callback: CallbackQuery):
    """Список всех чатов с историей"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        # Загружаем историю чатов из файла
        if os.path.exists(config.CHATS_FILE):
            with open(config.CHATS_FILE, 'r', encoding='utf-8') as f:
                chats_data = json.load(f)
        else:
            chats_data = {}
        
        if not chats_data:
            text = "📋 **История чатов**\n\n📭 Нет сохраненных чатов."
        else:
            text = "📋 **История чатов**\n\n"
            for uid, chat_data in list(chats_data.items())[:20]:
                username = chat_data.get('username', f'user_{uid}')
                started_at = datetime.fromisoformat(chat_data['started_at']).strftime('%d.%m.%Y')
                text += f"• @{username} (ID: {uid}) - {started_at}\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_chats'))
        
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ КОРЗИНЫ И ПОКУПОК ====================
# (Здесь идут все остальные обработчики из оригинального кода - корзина, покупки, админка и т.д.)
# Для краткости я пропустил их, но они должны остаться без изменений

# ==================== ЗАПУСК БОТА ====================

async def main():
    """Основная функция запуска бота"""
    
    # Проверяем настройки канала для тикетов
    if config.TICKET_CHANNEL_ID == -1001234567890:
        print("\n⚠️ ВНИМАНИЕ! Не настроен канал для тикетов!")
        print("Пожалуйста, укажите TICKET_CHANNEL_ID в Config")
        print("Создайте закрытый канал, добавьте туда бота администратором")
        print("и укажите ID канала (например, -1001234567890)\n")
    
    startup_info = f"""
{'=' * 50}
🤖 БОТ ЗАПУЩЕН
{'=' * 50}

📊 Загруженные данные:
• 📁 Категорий: {len(db.categories)}
• 📦 Товаров: {len(db.products)}
• 👥 Пользователей: {len(db.users)}
• 💳 Транзакций: {len(db.transactions)}
• ⏳ Ожидающих заказов: {len(db.pending_orders)}
• 🛍️ Активных корзин: {len(cart_manager.carts)}
• 💬 Активных чатов: {len(ticket_manager.active_chats)}
• 🎫 Открытых тикетов: {len(ticket_manager.tickets)}

⚙️ Конфигурация:
• 👨‍💼 Администраторы: {config.ADMIN_IDS}
• 💳 Оплата: Только Ozon (СБП/Карта)
• 📢 Канал подписки: {config.REQUIRED_CHANNEL}
• 🎁 Реферальная программа: {'Включена' if Config.REFERRAL_CONFIG['enabled'] else 'Выключена'}
• 🎫 Канал тикетов: {'Настроен' if config.TICKET_CHANNEL_ID != -1001234567890 else '⚠️ НЕ НАСТРОЕН!'}

🎉 НОВЫЕ ФУНКЦИИ:
• 🛍️ Корзина для покупки нескольких товаров
• 📢 Проверка подписки на канал
• 🎁 Реферальная программа с наградами
• 💬 Система индивидуальных чатов с поддержкой
• 🎫 Система тикетов в закрытый канал

{'=' * 50}
✅ Бот готов к работе!
✅ Подписка на канал обязательна!
✅ Реферальная программа активна!
✅ Система чатов и тикетов активна!
{'=' * 50}
"""
    print(startup_info)
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        print("\n\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка при запуске бота: {e}")
    finally:
        cart_manager.save_carts()
        ticket_manager.save_data()
        print("✅ Данные корзины и чатов сохранены")
        await bot.session.close()
        print("✅ Сессия бота закрыта")

if __name__ == "__main__":
    asyncio.run(main())
