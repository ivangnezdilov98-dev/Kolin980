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
        # Проверяем, есть ли реферальный код
        if 'referral_code' not in user_data or not user_data.get('referral_code'):
            # Генерируем новый код
            user_data['referral_code'] = db._generate_referral_code(user_id)
            migrated_count += 1
            print(f"  ➕ Добавлен реферальный код для пользователя {user_id}")
        
        # Добавляем недостающие поля, если их нет
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
                if field not in ['referred_by', 'referrals']:
                    print(f"  ➕ Добавлено поле {field} для пользователя {user_id}")
    
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
            InlineKeyboardButton(text='🛒 Посмотреть товары', callback_data='view_categories'),
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
        
        admin_text = """👨‍💼 Админ-панель

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

📝 Вы также можете написать напрямую администратору.
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

# ==================== ОБРАБОТЧИКИ КОРЗИНЫ ====================

@dp.callback_query(F.data == 'view_cart')
async def handle_view_cart(callback: CallbackQuery, state: FSMContext):
    """Показать корзину пользователя"""
    try:
        user_id = callback.from_user.id
        cart = cart_manager.get_cart(user_id)
        cart_total = cart_manager.get_cart_total(user_id)
        
        if not cart:
            await callback.message.edit_text(
                text="🛒 Ваша корзина пуста\n\nДобавьте товары из категорий!",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🛍️ Посмотреть товары', callback_data='view_categories'))
                    .add(InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu'))
                    .adjust(1)
                    .as_markup()
            )
            return
        
        cart_text = "🛒 Ваша корзина:\n\n"
        
        for i, item_detail in enumerate(cart_total['items'], 1):
            cart_text += f"{i}. {item_detail['name']}\n"
            cart_text += f"   💰 {item_detail['price']:.2f}₽ × {item_detail['quantity']} = {item_detail['item_total']:.2f}₽\n\n"
        
        cart_text += f"📦 Всего товаров: {cart_total['total_quantity']} шт.\n"
        cart_text += f"💸 Общая сумма: {cart_total['total_amount']:.2f}₽\n\n"
        cart_text += "Выберите действие:"
        
        await state.set_state(CartStates.managing_cart)
        await callback.message.edit_text(
            text=cart_text,
            reply_markup=cart_kb(cart)
        )
        
    except Exception as e:
        print(f"Ошибка при показе корзины: {e}")
        await callback.answer("Ошибка при загрузке корзины", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('add_to_cart_'))
async def handle_add_to_cart(callback: CallbackQuery, state: FSMContext):
    """Добавить товар в корзину"""
    try:
        product_id = int(callback.data.replace('add_to_cart_', ''))
        
        product = db.get_product(product_id)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        if product.get('quantity', 9999) <= 0:
            await callback.answer("❌ Товар закончился", show_alert=True)
            return
        
        if cart_manager.add_to_cart(callback.from_user.id, product_id, 1):
            product = db.get_product(product_id)
            if product:
                category = db.get_category(product["category_id"])
                cart_count = cart_manager.get_cart_items_count(callback.from_user.id)
                
                product_text = f"""📦 {product['name']}

💰 Цена: {product['price']:.2f}₽
📝 Описание: {product.get('description', 'Нет описания')}
📊 В наличии: {product.get('quantity', 9999)} шт.
📁 Категория: {category.get('name', 'Не указана') if category else 'Не указана'}

✅ Товар добавлен в корзину!
🛒 Товаров в корзине: {cart_count}
"""
                
                await callback.message.edit_text(
                    text=product_text,
                    reply_markup=product_detail_kb(product_id, product["category_id"])
                )
            
            await callback.answer(f"✅ {product['name']} добавлен в корзину!")
        else:
            await callback.answer("❌ Ошибка при добавлении в корзину", show_alert=True)
        
    except Exception as e:
        print(f"Ошибка при добавлении в корзину: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('cart_remove_'))
async def handle_cart_remove(callback: CallbackQuery, state: FSMContext):
    """Удалить товар из корзины"""
    try:
        product_id = int(callback.data.replace('cart_remove_', ''))
        
        if cart_manager.remove_from_cart(callback.from_user.id, product_id):
            cart = cart_manager.get_cart(callback.from_user.id)
            cart_total = cart_manager.get_cart_total(callback.from_user.id)
            
            if not cart:
                await callback.message.edit_text(
                    text="✅ Товар удален из корзины!\n\n🛒 Ваша корзина теперь пуста",
                    reply_markup=InlineKeyboardBuilder()
                        .add(InlineKeyboardButton(text='🛍️ Посмотреть товары', callback_data='view_categories'))
                        .add(InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu'))
                        .adjust(1)
                        .as_markup()
                )
            else:
                cart_text = "🛒 Ваша корзина:\n\n"
                
                for i, item_detail in enumerate(cart_total['items'], 1):
                    cart_text += f"{i}. {item_detail['name']}\n"
                    cart_text += f"   💰 {item_detail['price']:.2f}₽ × {item_detail['quantity']} = {item_detail['item_total']:.2f}₽\n\n"
                
                cart_text += f"📦 Всего товаров: {cart_total['total_quantity']} шт.\n"
                cart_text += f"💸 Общая сумма: {cart_total['total_amount']:.2f}₽\n\n"
                cart_text += "Выберите действие:"
                
                await callback.message.edit_text(
                    text=cart_text,
                    reply_markup=cart_kb(cart)
                )
            
            await callback.answer("✅ Товар удален из корзины")
        else:
            await callback.answer("❌ Товар не найден в корзине", show_alert=True)
        
    except Exception as e:
        print(f"Ошибка при удалении из корзины: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'cart_clear')
async def handle_cart_clear(callback: CallbackQuery, state: FSMContext):
    """Очистить корзину"""
    try:
        if cart_manager.clear_cart(callback.from_user.id):
            await callback.message.edit_text(
                text="✅ Корзина очищена!",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🛍️ Посмотреть товары', callback_data='view_categories'))
                    .add(InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu'))
                    .adjust(1)
                    .as_markup()
            )
            await callback.answer("Корзина очищена")
        else:
            await callback.answer("❌ Корзина уже пуста", show_alert=True)
        
    except Exception as e:
        print(f"Ошибка при очистке корзины: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'cart_checkout')
async def handle_cart_checkout(callback: CallbackQuery, state: FSMContext):
    """Оформление заказа из корзины"""
    try:
        user_id = callback.from_user.id
        username = callback.from_user.username
        
        if not username:
            error_text = """⚠️ У вас не установлен username!

Для оформления заказа необходимо:
1. Установить username в настройках Telegram
2. Нажать /start в этом боте
3. Повторить покупку

📌 Как установить username:
1. Откройте Настройки Telegram
2. Выберите "Имя пользователя" (Username)
3. Установите уникальное имя
4. Сохраните изменения"""
            
            await callback.message.edit_text(
                text=error_text,
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🚀 Начать заново (/start)', callback_data='force_start'))
                    .as_markup()
            )
            await callback.answer("❌ Установите username для покупки", show_alert=True)
            return
        
        cart_total = cart_manager.get_cart_total(user_id)
        
        if cart_total['items_count'] == 0:
            await callback.answer("❌ Корзина пуста", show_alert=True)
            return
        
        await state.set_state(PaymentStates.waiting_for_screenshot)
        
        order_id = f"CART_{user_id}_{int(datetime.now().timestamp())}"
        
        payment_info = config.PAYMENT_DETAILS["ozon"]
        
        await state.update_data(
            user_id=user_id,
            username=username,
            order_id=order_id,
            payment_method='ozon',
            payment_name=payment_info['name'],
            cart_total=cart_total,
            is_cart_order=True
        )
        
        cart_items_text = ""
        for item in cart_total['items']:
            cart_items_text += f"• {item['name']} x{item['quantity']} = {item['item_total']:.2f}₽\n"
        
        payment_text = f"""🏦 Оплата через {payment_info['name']}

🛒 Ваш заказ из корзины:
{cart_items_text}
📦 Всего товаров: {cart_total['total_quantity']} шт.
💰 Общая сумма: {cart_total['total_amount']:.2f}₽

👤 Ваш username: @{username}

💳 Номер карты для перевода:
{payment_info['card_number']}

📱 Номер телефона для СБП:
{payment_info['phone_number']}

👤 Получатель:
{payment_info['owner']}

📝 В комментарии к переводу укажите:
Заказ {order_id}

📸 После оплаты отправьте скриншот чека в этот чат
"""
        
        await callback.message.edit_text(
            text=payment_text,
            reply_markup=cart_checkout_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при оформлении заказа из корзины: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
        await state.clear()
    
    await callback.answer()

@dp.callback_query(F.data == 'cart_edit_quantity')
async def handle_cart_edit_quantity(callback: CallbackQuery, state: FSMContext):
    """Редактирование количества товаров в корзине"""
    try:
        user_id = callback.from_user.id
        cart = cart_manager.get_cart(user_id)
        
        if not cart:
            await callback.answer("Корзина пуста", show_alert=True)
            return
        
        builder = InlineKeyboardBuilder()
        cart_total = cart_manager.get_cart_total(user_id)
        
        for item_detail in cart_total['items']:
            product_name = item_detail['name']
            if len(product_name) > 20:
                product_name = product_name[:17] + "..."
            
            builder.row(
                InlineKeyboardButton(
                    text=f"✏️ {product_name} x{item_detail['quantity']}",
                    callback_data=f"cart_edit_{item_detail['product_id']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text='🔙 Назад', callback_data='view_cart')
        )
        
        await state.set_state(CartStates.waiting_for_quantity)
        await callback.message.edit_text(
            text="✏️ Редактирование количества\n\nВыберите товар, количество которого хотите изменить:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при редактировании количества: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('cart_edit_'))
async def handle_cart_edit_item(callback: CallbackQuery, state: FSMContext):
    """Выбор товара для редактирования количества"""
    try:
        product_id = int(callback.data.replace('cart_edit_', ''))
        
        await state.update_data(edit_product_id=product_id)
        
        product = db.get_product(product_id)
        if product:
            product_name = product['name']
        else:
            product_name = "Товар"
        
        cart = cart_manager.get_cart(callback.from_user.id)
        current_qty = 1
        for item in cart:
            if item['product_id'] == product_id:
                current_qty = item['quantity']
                break
        
        await callback.message.edit_text(
            text=f"✏️ Введите новое количество для товара:\n"
                 f"📦 {product_name}\n\n"
                 f"Текущее количество: {current_qty}\n\n"
                 f"Введите число:",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='🔙 Назад', callback_data='cart_edit_quantity'))
                .as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при выборе товара для редактирования: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await callback.answer()

# ==================== ОБРАБОТКА ПОКУПКИ ТОВАРА ====================

@dp.callback_query(F.data.startswith('buy_product_'))
async def handle_buy_product(callback: CallbackQuery, state: FSMContext):
    """Обработать покупку товара"""
    try:
        print(f"DEBUG: Начало обработки покупки: {callback.data}")
        
        username = callback.from_user.username
        user_id = callback.from_user.id
        
        if not username:
            print(f"DEBUG: У пользователя {user_id} нет username")
            
            error_text = """⚠️ У вас не установлен username!

Для оформления заказа необходимо:
1. Установить username в настройках Telegram
2. Нажать /start в этом боте
3. Повторить покупку

📌 Как установить username:
1. Откройте Настройки Telegram
2. Выберите "Имя пользователя" (Username)
3. Установите уникальное имя
4. Сохраните изменения

После установки username нажмите /start и попробуйте снова."""
            
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text='🚀 Начать заново (/start)', callback_data='force_start'))
            
            await callback.message.edit_text(text=error_text, reply_markup=builder.as_markup())
            await callback.answer("❌ Установите username для покупки", show_alert=True)
            return
        
        parts = callback.data.split('_')
        print(f"DEBUG: parts = {parts}")
        
        if len(parts) != 3:
            print(f"DEBUG: Неверный формат callback_data: {callback.data}")
            await callback.answer("❌ Неверный формат запроса", show_alert=True)
            return
            
        product_id_str = parts[2]
        print(f"DEBUG: product_id_str = {product_id_str}")
        
        try:
            product_id = int(product_id_str)
        except ValueError:
            print(f"DEBUG: Не удалось преобразовать '{product_id_str}' в число")
            await callback.answer("❌ Неверный ID товара", show_alert=True)
            return
            
        print(f"DEBUG: ID товара: {product_id}")
        
        product = db.get_product(product_id)
        print(f"DEBUG: Найден товар: {product}")
        
        if not product:
            print("DEBUG: ❌ Товар не найден в базе")
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        quantity = product.get('quantity', 9999)
        print(f"DEBUG: Количество товара: {quantity}")
        
        if quantity <= 0:
            print("DEBUG: ❌ Товар закончился")
            await callback.answer("❌ Товар закончился", show_alert=True)
            return
        
        order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}"
        print(f"DEBUG: Сгенерирован order_id: {order_id}")
        
        payment_info = config.PAYMENT_DETAILS["ozon"]
        
        try:
            if isinstance(product.get('price'), (int, float)):
                product_price = float(product['price'])
            elif isinstance(product.get('price'), str):
                price_str = product['price'].replace('₽', '').replace('руб', '').replace(' ', '').strip()
                product_price = float(price_str)
            else:
                print(f"DEBUG: Неизвестный формат цены: {product.get('price')}")
                product_price = 0.0
        except (ValueError, TypeError) as e:
            print(f"DEBUG: Ошибка при обработке цены: {e}")
            product_price = 0.0
            
        print(f"DEBUG: Цена товара: {product_price}")
        print(f"DEBUG: Username пользователя: @{username}")
        
        await state.set_state(PaymentStates.waiting_for_screenshot)
        print("DEBUG: Установлено состояние ожидания скриншота")
        
        await state.update_data(
            user_id=user_id,
            username=username,
            product_id=product_id,
            product_name=product['name'],
            product_price=product_price,
            order_id=order_id,
            payment_method='ozon',
            payment_name=payment_info['name']
        )
        print("DEBUG: Данные сохранены в state")
        
        payment_text = f"""🏦 Оплата через {payment_info['name']}

📦 Товар: {product['name']}
💰 Сумма к оплате: {product_price:.2f}₽
👤 Ваш username: @{username}

💳 Номер карты для перевода:
{payment_info['card_number']}

📱 Номер телефона для СБП:
{payment_info['phone_number']}

👤 Получатель:
{payment_info['owner']}

📝 В комментарии к переводу укажите:
Заказ {order_id}

📸 После оплаты отправьте скриншот чека в этот чат
"""
        
        await callback.message.edit_text(
            text=payment_text,
            reply_markup=cancel_kb()
        )
        print("DEBUG: Сообщение с инструкцией отправлено")
        
    except ValueError as e:
        print(f"ERROR: ValueError при обработке покупки: {e}")
        print(f"ERROR: Traceback: {traceback.format_exc()}")
        await callback.answer("❌ Ошибка при обработке заказа", show_alert=True)
        await state.clear()
    except Exception as e:
        print(f"ERROR: Общая ошибка при покупке товара: {e}")
        print(f"ERROR: Traceback: {traceback.format_exc()}")
        await callback.answer("❌ Ошибка при покупке", show_alert=True)
        await state.clear()
    
    await callback.answer()

# ==================== ОБРАБОТКА СКРИНШОТОВ ====================

@dp.message(PaymentStates.waiting_for_screenshot, F.photo)
async def handle_payment_screenshot(message: Message, state: FSMContext):
    """Обработать полученный скриншот оплаты"""
    try:
        file_id = message.photo[-1].file_id
        
        data = await state.get_data()
        
        is_cart_order = data.get('is_cart_order', False)
        
        await state.clear()
        
        if is_cart_order:
            await _process_cart_purchase_screenshot(message, data, file_id)
        else:
            await _process_purchase_screenshot(message, data, file_id)
        
    except Exception as e:
        print(f"Ошибка при обработке скриншота: {e}")
        await message.answer(
            text="❌ Ошибка при обработке скриншота",
            reply_markup=main_menu_kb(message.from_user.id)
        )
        await state.clear()

async def _process_purchase_screenshot(message: Message, data: dict, file_id: str):
    """Обработать скриншот оплаты заказа (обновленная версия с рефералами)"""
    try:
        user_id = data.get('user_id')
        username = data.get('username')
        payment_name = data.get('payment_name')
        order_id = data.get('order_id')
        
        try:
            product_price = float(data.get('product_price', 0))
        except (ValueError, TypeError) as e:
            print(f"ERROR: Ошибка преобразования цены: {e}")
            product_price = 0.0
            
        product_name = data.get('product_name', 'Неизвестный товар')
        
        print(f"DEBUG: Обработка скриншота для заказа {order_id}")
        
        order_data = {
            'user_id': user_id,
            'username': username,
            'order_id': order_id,
            'total': product_price,
            'product_name': product_name,
            'product_price': product_price,
            'payment_method': payment_name
        }
        
        result = await send_to_order_channel(order_data, file_id)
        
        if result is None:
            error_text = """❌ Не удалось отправить заявку.

Возможные причины:
1. Бот не добавлен в канал заказов
2. У бота нет прав на отправку сообщений в канал
3. Технические проблемы с Telegram

Пожалуйста, обратитесь к администратору: @koliin98
"""
            await message.answer(text=error_text, reply_markup=main_menu_kb(user_id))
            return
        
        try:
            db.update_user_stats(user_id, product_price)
            print(f"DEBUG: Статистика пользователя {user_id} обновлена")
        except Exception as e:
            print(f"ERROR: Ошибка обновления статистики: {e}")
        
        # Проверяем реферальные награды
        user_data = db.get_user(user_id)
        referred_by = user_data.get('referred_by')
        
        reward_text = ""
        if referred_by:
            await check_referral_qualification(referred_by, product_price)
        
        reward_result = await apply_referral_reward(user_id, product_price)
        if reward_result.get('applied'):
            reward_text = f"\n\n🎁 Применена награда: {reward_result['reward_description']}!\nОсталось наград: {reward_result['remaining_rewards']}"
        
        success_text = f"""✅ Заказ оформлен!

🆔 Номер заказа: {order_id}
📦 Товар: {product_name}
💰 Сумма: {product_price:.2f}₽
💳 Способ оплаты: {payment_name}

📋 Заказ отправлен на обработку.
Мы свяжемся с вами в ближайшее время.{reward_text}
"""
        
        await message.answer(text=success_text, reply_markup=main_menu_kb(user_id))
        print(f"DEBUG: Пользователь уведомлен об успешной отправке")
        
    except Exception as e:
        print(f"❌ Ошибка при обработке скриншота заказа: {e}")
        import traceback
        print(f"❌ Трассировка ошибки:\n{traceback.format_exc()}")
        
        error_text = f"""❌ Ошибка при обработке заказа

Произошла техническая ошибка.
Пожалуйста, обратитесь к администратору: @koliin98

Ошибка: {str(e)}
"""
        await message.answer(text=error_text, reply_markup=main_menu_kb(message.from_user.id))

async def _process_cart_purchase_screenshot(message: Message, data: dict, file_id: str):
    """Обработать скриншот оплаты заказа из корзины (обновленная версия с рефералами)"""
    try:
        user_id = data.get('user_id')
        username = data.get('username')
        payment_name = data.get('payment_name')
        order_id = data.get('order_id')
        cart_total = data.get('cart_total', {})
        
        print(f"DEBUG: Обработка заказа из корзины {order_id}")
        
        order_data = {
            'user_id': user_id,
            'username': username,
            'order_id': order_id,
            'cart_total': cart_total,
            'total': cart_total.get('total_amount', 0),
            'payment_method': payment_name,
            'is_cart_order': True
        }
        
        result = await send_cart_to_order_channel(order_data, file_id)
        
        if result is None:
            error_text = """❌ Не удалось отправить заявку.

Возможные причины:
1. Бот не добавлен в канал заказов
2. У бота нет прав на отправку сообщений в канал
3. Технические проблемы с Telegram

Пожалуйста, обратитесь к администратору: @koliin98
"""
            await message.answer(text=error_text, reply_markup=main_menu_kb(user_id))
            return
        
        total_amount = cart_total.get('total_amount', 0)
        
        try:
            db.update_user_stats(user_id, total_amount)
            print(f"DEBUG: Статистика пользователя {user_id} обновлена")
        except Exception as e:
            print(f"ERROR: Ошибка обновления статистики: {e}")
        
        # Проверяем реферальные награды
        user_data = db.get_user(user_id)
        referred_by = user_data.get('referred_by')
        
        reward_text = ""
        if referred_by:
            await check_referral_qualification(referred_by, total_amount)
        
        reward_result = await apply_referral_reward(user_id, total_amount)
        if reward_result.get('applied'):
            reward_text = f"\n\n🎁 Применена награда: {reward_result['reward_description']}!\nОсталось наград: {reward_result['remaining_rewards']}"
        
        cart_manager.clear_cart(user_id)
        
        items_text = ""
        for item in cart_total.get('items', []):
            items_text += f"• {item['name']} x{item['quantity']} = {item['item_total']:.2f}₽\n"
        
        success_text = f"""✅ Заказ из корзины оформлен!

🆔 Номер заказа: {order_id}
🛒 Состав заказа:
{items_text}
📦 Всего товаров: {cart_total.get('total_quantity', 0)} шт.
💰 Общая сумма: {total_amount:.2f}₽
💳 Способ оплаты: {payment_name}

📋 Заказ отправлен на обработку.
Мы свяжемся с вами в ближайшее время.{reward_text}
"""
        
        await message.answer(text=success_text, reply_markup=main_menu_kb(user_id))
        print(f"DEBUG: Пользователь уведомлен об успешной отправке заказа из корзины")
        
    except Exception as e:
        print(f"❌ Ошибка при обработке скриншота заказа из корзины: {e}")
        import traceback
        print(f"❌ Трассировка ошибки:\n{traceback.format_exc()}")
        
        error_text = f"""❌ Ошибка при обработке заказа

Произошла техническая ошибка.
Пожалуйста, обратитесь к администратору: @koliin98

Ошибка: {str(e)}
"""
        await message.answer(text=error_text, reply_markup=main_menu_kb(message.from_user.id))

@dp.callback_query(F.data == 'cart_confirm_payment')
async def handle_cart_confirm_payment(callback: CallbackQuery, state: FSMContext):
    """Подтверждение оплаты из корзины"""
    try:
        await callback.message.edit_text(
            text="📸 Отправьте скриншот оплаты в этот чат",
            reply_markup=cancel_kb()
        )
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == 'force_start')
async def handle_force_start(callback: CallbackQuery, state: FSMContext):
    """Принудительный запуск бота с проверкой username"""
    try:
        await state.clear()
        
        user_id = callback.from_user.id
        username = callback.from_user.username
        
        if not username:
            error_text = """❌ Username не найден!

Вы не установили username в Telegram.

📌 Как установить username:
1. Откройте Настройки Telegram
2. Выберите "Имя пользователя" (Username)
3. Установите уникальное имя
4. Сохраните изменения

После установки username нажмите /start"""
            
            await callback.message.edit_text(
                text=error_text,
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🔄 Проверить снова', callback_data='force_start'))
                    .as_markup()
            )
            return
        
        db.get_user(user_id)
        
        cart_count = cart_manager.get_cart_items_count(user_id)
        cart_info = f"\n🛒 Товаров в корзине: {cart_count}" if cart_count > 0 else ""
        
        welcome_text = f"""✅ Username обнаружен: @{username}{cart_info}

👋 Добро пожаловать в магазин виртуальных услуг!

✨ Возможности:
• 🛒 Просмотр и покупка услуг
• 🛍️ Корзина для покупки нескольких товаров
• 💳 Оплата через Ozon (СБП/Карта)
• ✅ Подтверждение заказов администраторами

Теперь вы можете покупать товары!"""
        
        await callback.message.edit_text(
            text=welcome_text,
            reply_markup=main_menu_kb(user_id)
        )
        
    except Exception as e:
        print(f"Ошибка при принудительном запуске: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

# ==================== АДМИН-ПАНЕЛЬ ====================

@dp.callback_query(F.data == 'admin_panel')
async def handle_admin_panel(callback: CallbackQuery):
    """Показать админ-панель"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        pending_orders = len(db.pending_orders)
        
        admin_text = f"""👨‍💼 Админ-панель

📊 Быстрая статистика:
• 🛒 Ожидающих заказов: {pending_orders}
• 👥 Пользователей: {len(db.users)}
• 📦 Товаров: {len(db.products)}
• 🛍️ Активных корзин: {len(cart_manager.carts)}

Выберите раздел для управления:
"""
        
        await callback.message.edit_text(
            text=admin_text,
            reply_markup=admin_panel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при открытии админ-панели: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_pending')
async def handle_admin_pending(callback: CallbackQuery):
    """Показать ожидающие заявки"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        pending_orders = db.pending_orders
        
        if not pending_orders:
            text = "📭 Нет ожидающих заказов"
        else:
            text = "⏳ Ожидающие заказы:\n\n"
            
            for i, (order_id, order_data) in enumerate(pending_orders.items(), 1):
                text += f"{i}. 🆔 {order_id}\n"
                text += f"   👤 @{order_data.get('username', 'N/A')} ({order_data.get('user_id')})\n"
                
                if order_data.get('is_cart_order'):
                    text += f"   🛍️ Заказ из корзины ({order_data.get('total_quantity', 0)} товаров)\n"
                else:
                    text += f"   📦 {order_data.get('product_name', 'Неизвестно')}\n"
                
                text += f"   💰 {order_data.get('total', 0)}₽\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text='🔄 Обновить', callback_data='admin_pending'),
            InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
        )
        
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при показе ожидающих заявок: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_users')
async def handle_admin_users(callback: CallbackQuery):
    """Показать пользователей"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        users = db.users
        if not users:
            text = "📭 Пользователей пока нет"
        else:
            text = "👥 Пользователи:\n\n"
            
            sorted_users = sorted(
                users.items(),
                key=lambda x: x[1].get('total_orders', 0),
                reverse=True
            )
            
            for i, (user_id, user_data) in enumerate(sorted_users[:10], 1):
                total_spent = user_data.get('total_spent', 0)
                total_orders = user_data.get('total_orders', 0)
                reg_date = datetime.fromisoformat(user_data.get('registration_date', '2000-01-01')).strftime('%d.%m.%Y')
                referrals = len(user_data.get('referrals', []))
                rewards = user_data.get('available_rewards', 0)
                
                text += f"{i}. 🆔 {user_id}\n"
                text += f"   💸 Потрачено: {total_spent:.2f}₽\n"
                text += f"   📦 Заказов: {total_orders}\n"
                text += f"   👥 Рефералов: {referrals}\n"
                text += f"   🎁 Наград: {rewards}\n"
                text += f"   📅 Регистрация: {reg_date}\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
        )
        
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при показе пользователей: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_stats')
async def handle_admin_stats(callback: CallbackQuery):
    """Показать статистику"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        categories_count = len(db.get_categories())
        products_count = len(db.products)
        users_count = len(db.users)
        
        purchases = [t for t in db.transactions if t['type'] == 'purchase']
        total_purchases = sum(abs(t['amount']) for t in purchases)
        
        total_orders = sum(user.get('total_orders', 0) for user in db.users.values())
        total_spent = sum(user.get('total_spent', 0) for user in db.users.values())
        
        active_carts = len(cart_manager.carts)
        total_cart_items = sum(len(cart) for cart in cart_manager.carts.values())
        
        # Реферальная статистика
        total_referrals = sum(len(u.get('referrals', [])) for u in db.users.values())
        total_qualified = sum(u.get('qualified_referrals', 0) for u in db.users.values())
        total_rewards = sum(u.get('available_rewards', 0) for u in db.users.values())
        
        stats_text = f"""📊 СТАТИСТИКА БОТА

📈 Общая статистика:
• 📁 Категорий: {categories_count}
• 📦 Товаров: {products_count}
• 👥 Пользователей: {users_count}
• ⏳ Ожидающих заказов: {len(db.pending_orders)}
• 🛍️ Активных корзин: {active_carts}
• 🛒 Товаров в корзинах: {total_cart_items}

💰 Финансовая статистика:
• 🛒 Покупок: {len(purchases)} на {total_purchases:.2f}₽
• 💸 Всего потрачено: {total_spent:.2f}₽
• 📦 Всего заказов: {total_orders}

🎁 Реферальная статистика:
• 👥 Всего рефералов: {total_referrals}
• ✅ Квалифицированных: {total_qualified}
• 🎁 Доступно наград: {total_rewards}

💳 Способ оплаты:
• 🏦 Только Ozon (СБП/Карта)
"""
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text='🔙 Назад', callback_data='admin_panel')
        )
        
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при показе статистики: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_products')
async def handle_admin_products(callback: CallbackQuery):
    """Управление товарами"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        await callback.message.edit_text(
            text="📦 Управление товарами\n\nВыберите действие:",
            reply_markup=admin_products_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при управлении товарами: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_categories')
async def handle_admin_categories(callback: CallbackQuery):
    """Управление категориями"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        await callback.message.edit_text(
            text="📁 Управление категориями\n\nВыберите действие:",
            reply_markup=admin_categories_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при управлении категориями: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_referral')
async def handle_admin_referral(callback: CallbackQuery):
    """Управление реферальной программой"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        config_ref = Config.REFERRAL_CONFIG
        
        total_referrals = sum(len(u.get('referrals', [])) for u in db.users.values())
        total_qualified = sum(u.get('qualified_referrals', 0) for u in db.users.values())
        total_rewards_used = sum(u.get('used_rewards', 0) for u in db.users.values())
        total_rewards_available = sum(u.get('available_rewards', 0) for u in db.users.values())
        
        text = f"""🎁 Управление реферальной программой

📊 **ТЕКУЩИЕ НАСТРОЙКИ:**
• Статус: {'✅ Включена' if config_ref['enabled'] else '❌ Выключена'}
• Минимальная сумма: {config_ref['min_purchase_amount']}₽
• Награда: {config_ref['reward_description']}
• Макс. рефералов: {config_ref['max_referrals_per_user']}

📈 **СТАТИСТИКА:**
• Всего рефералов: {total_referrals}
• Квалифицированных: {total_qualified}
• Доступно наград: {total_rewards_available}
• Использовано наград: {total_rewards_used}

Выберите действие:"""

        await callback.message.edit_text(
            text=text,
            reply_markup=admin_referral_kb(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_referral_toggle')
async def handle_admin_referral_toggle(callback: CallbackQuery):
    """Включение/выключение реферальной программы"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        Config.REFERRAL_CONFIG["enabled"] = not Config.REFERRAL_CONFIG["enabled"]
        status = "включена" if Config.REFERRAL_CONFIG["enabled"] else "выключена"
        
        await callback.answer(f"✅ Реферальная программа {status}", show_alert=True)
        await handle_admin_referral(callback)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == 'admin_referral_amount')
async def handle_admin_referral_amount(callback: CallbackQuery, state: FSMContext):
    """Изменение минимальной суммы для реферальной программы"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        await state.set_state(ReferralStates.waiting_for_new_amount)
        
        await callback.message.edit_text(
            text=f"""💰 Изменение минимальной суммы покупки

Текущая сумма: {Config.REFERRAL_CONFIG['min_purchase_amount']}₽

Введите новую сумму (в рублях):
Например: 100""",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
                .as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.message(ReferralStates.waiting_for_new_amount)
async def handle_new_referral_amount(message: Message, state: FSMContext):
    """Обработка новой минимальной суммы"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            await state.clear()
            return
        
        try:
            new_amount = float(message.text.strip())
        except ValueError:
            await message.answer(
                "❌ Неверный формат! Введите число.\nНапример: 100",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
                    .as_markup()
            )
            return
        
        if new_amount <= 0:
            await message.answer(
                "❌ Сумма должна быть больше 0!",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
                    .as_markup()
            )
            return
        
        Config.REFERRAL_CONFIG["min_purchase_amount"] = new_amount
        await state.clear()
        
        await message.answer(
            f"✅ Минимальная сумма изменена на {new_amount}₽",
            reply_markup=admin_panel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("❌ Ошибка", reply_markup=admin_panel_kb())
        await state.clear()

@dp.callback_query(F.data == 'admin_referral_reward')
async def handle_admin_referral_reward(callback: CallbackQuery, state: FSMContext):
    """Изменение описания награды"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        await state.set_state(ReferralStates.waiting_for_new_reward)
        
        await callback.message.edit_text(
            text=f"""🎁 Изменение описания награды

Текущее описание: {Config.REFERRAL_CONFIG['reward_description']}

Введите новое описание награды:
Например: 1 аккаунт Мьянма бесплатно""",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
                .as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.message(ReferralStates.waiting_for_new_reward)
async def handle_new_referral_reward(message: Message, state: FSMContext):
    """Обработка нового описания награды"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            await state.clear()
            return
        
        new_reward = message.text.strip()
        
        if len(new_reward) < 3:
            await message.answer(
                "❌ Описание слишком короткое!",
                reply_markup=InlineKeyboardBuilder()
                    .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
                    .as_markup()
            )
            return
        
        Config.REFERRAL_CONFIG["reward_description"] = new_reward
        await state.clear()
        
        await message.answer(
            f"✅ Описание награды изменено на: {new_reward}",
            reply_markup=admin_panel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("❌ Ошибка", reply_markup=admin_panel_kb())
        await state.clear()

@dp.callback_query(F.data == 'admin_referral_stats')
async def handle_admin_referral_stats(callback: CallbackQuery):
    """Детальная статистика рефералов"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        top_referrers = []
        for user_id, user_data in db.users.items():
            referrals_count = len(user_data.get('referrals', []))
            if referrals_count > 0:
                top_referrers.append({
                    'user_id': user_id,
                    'referrals': referrals_count,
                    'qualified': user_data.get('qualified_referrals', 0),
                    'rewards': user_data.get('available_rewards', 0)
                })
        
        top_referrers.sort(key=lambda x: x['referrals'], reverse=True)
        
        text = "📊 **ДЕТАЛЬНАЯ СТАТИСТИКА РЕФЕРАЛОВ**\n\n"
        
        if not top_referrers:
            text += "Пока нет активных рефералов"
        else:
            text += "🏆 **ТОП РЕФЕРАЛОВ:**\n"
            for i, ref in enumerate(top_referrers[:10], 1):
                text += f"{i}. ID: {ref['user_id']}\n"
                text += f"   👥 Рефералов: {ref['referrals']}\n"
                text += f"   ✅ Квалифицированных: {ref['qualified']}\n"
                text += f"   🎁 Наград: {ref['rewards']}\n\n"
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_referral'))
        
        await callback.message.edit_text(
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_list_products')
async def handle_admin_list_products(callback: CallbackQuery):
    """Список товаров"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        products = db.get_all_products()
        
        if not products:
            text = "📭 Товары пока отсутствуют"
        else:
            text = "📦 Список всех товаров:\n\n"
            
            for i, product in enumerate(products, 1):
                category = db.get_category(product.get('category_id', 0))
                category_name = category.get('name', 'Неизвестно') if category else 'Неизвестно'
                
                text += f"{i}. 📦 {product['name']}\n"
                text += f"   🆔 ID: {product['id']}\n"
                text += f"   💰 Цена: {product['price']:.2f}₽\n"
                text += f"   📁 Категория: {category_name}\n"
                text += f"   📊 В наличии: {product.get('quantity', 9999)} шт.\n"
                
                if product.get('description'):
                    text += f"   📝 Описание: {product['description'][:50]}...\n"
                
                text += "\n"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=admin_list_products_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при показе списка товаров: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_list_categories')
async def handle_admin_list_categories(callback: CallbackQuery):
    """Список категорий"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        categories = db.get_categories()
        
        if not categories:
            text = "📭 Категории пока отсутствуют"
        else:
            text = "📁 Список категорий:\n\n"
            
            for i, category in enumerate(categories, 1):
                products_count = len(db.get_products_by_category(category['id']))
                text += f"{i}. {category['name']}\n"
                text += f"   🆔 ID: {category['id']}\n"
                text += f"   📦 Товаров: {products_count}\n\n"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=admin_list_categories_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при показе списка категорий: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_add_category')
async def handle_admin_add_category(callback: CallbackQuery):
    """Добавление категории через меню"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        await callback.message.edit_text(
            text="📁 Добавление новой категории\n\n"
                 "Введите название новой категории:\n"
                 "(например: 💻 Цифровые услуги)\n\n"
                 "Или нажмите '🔙 Назад' для отмены",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_categories'))
                .as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при добавлении категории: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data == 'admin_add_product')
async def handle_admin_add_product(callback: CallbackQuery, state: FSMContext):
    """Добавление товара через меню"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        categories = db.get_categories()
        if not categories:
            await callback.message.edit_text(
                text="❌ Нет доступных категорий.\nСначала создайте категорию.",
                reply_markup=admin_products_kb()
            )
            return
        
        await state.set_state(AddProductStates.waiting_for_category)
        
        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.row(
                InlineKeyboardButton(
                    text=category["name"],
                    callback_data=f"admin_add_product_cat_{category['id']}"
                )
            )
        builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='admin_products'))
        
        await callback.message.edit_text(
            text="➕ Добавление нового товара\n\nВыберите категорию для товара:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при запуске добавления товара: {e}")
        await callback.answer("Ошибка", show_alert=True)
        await state.clear()
    
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_add_product_cat_'))
async def handle_admin_product_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории для товара"""
    try:
        category_id = int(callback.data.replace('admin_add_product_cat_', ''))
        
        await state.update_data(category_id=category_id)
        await state.set_state(AddProductStates.waiting_for_name)
        
        await callback.message.edit_text(
            text="📝 Введите название товара:",
            reply_markup=cancel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при выборе категории товара: {e}")
        await callback.answer("Ошибка", show_alert=True)
        await state.clear()
    
    await callback.answer()

@dp.message(AddProductStates.waiting_for_name)
async def handle_product_name(message: Message, state: FSMContext):
    """Обработка ввода названия товара"""
    try:
        product_name = message.text.strip()
        
        if len(product_name) < 2:
            await message.answer(
                text="❌ Название слишком короткое. Введите название товара:",
                reply_markup=cancel_kb()
            )
            return
        
        await state.update_data(product_name=product_name)
        await state.set_state(AddProductStates.waiting_for_price)
        
        await message.answer(
            text="💰 Введите цену товара (в рублях):\n\nПример: 1000 или 1500.50",
            reply_markup=cancel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при вводе названия товара: {e}")
        await message.answer("❌ Ошибка", reply_markup=cancel_kb())
        await state.clear()

@dp.message(AddProductStates.waiting_for_price)
async def handle_product_price(message: Message, state: FSMContext):
    """Обработка ввода цены товара"""
    try:
        price_text = message.text.strip().replace(',', '.')
        
        try:
            price = float(price_text)
        except ValueError:
            await message.answer(
                text="❌ Неверный формат цены!\n\nВведите число. Пример: 1000 или 1500.50",
                reply_markup=cancel_kb()
            )
            return
        
        if price <= 0:
            await message.answer(
                text="❌ Цена должна быть больше 0!\n\nВведите цену товара:",
                reply_markup=cancel_kb()
            )
            return
        
        await state.update_data(product_price=price)
        await state.set_state(AddProductStates.waiting_for_description)
        
        await message.answer(
            text="📝 Введите описание товара (или 'нет' для пропуска):",
            reply_markup=cancel_kb()
        )
        
    except Exception as e:
        print(f"Ошибка при вводе цены товара: {e}")
        await message.answer("❌ Ошибка", reply_markup=cancel_kb())
        await state.clear()

@dp.message(AddProductStates.waiting_for_description)
async def handle_product_description(message: Message, state: FSMContext):
    """Обработка ввода описания товара"""
    try:
        description = message.text.strip()
        if description.lower() == 'нет':
            description = ""
        
        data = await state.get_data()
        category_id = data.get('category_id')
        product_name = data.get('product_name')
        price = data.get('product_price')
        
        product_id = db.add_product(
            category_id=category_id,
            name=product_name,
            price=price,
            description=description
        )
        
        await state.clear()
        
        category = db.get_category(category_id)
        
        await message.answer(
            text=f"✅ Товар успешно добавлен!\n\n"
                 f"📦 Название: {product_name}\n"
                 f"💰 Цена: {price:.2f}₽\n"
                 f"📝 Описание: {description or 'Нет описания'}\n"
                 f"📁 Категория: {category.get('name', 'Неизвестно') if category else 'Неизвестно'}\n"
                 f"🆔 ID товара: {product_id}",
            reply_markup=main_menu_kb(message.from_user.id)
        )
        
        print(f"✅ Добавлен новый товар: {product_name} (ID: {product_id}) в категорию {category_id}")
        
    except Exception as e:
        print(f"Ошибка при добавлении товара: {e}")
        await message.answer(
            text="❌ Ошибка при добавлении товара",
            reply_markup=main_menu_kb(message.from_user.id)
        )
        await state.clear()

@dp.callback_query(F.data == 'admin_delete_product')
async def handle_admin_delete_product(callback: CallbackQuery, state: FSMContext):
    """Удаление товара"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        products = db.get_all_products()
        
        if not products:
            await callback.message.edit_text(
                text="📭 Нет товаров для удаления",
                reply_markup=admin_products_kb()
            )
            return
        
        builder = InlineKeyboardBuilder()
        
        for product in products:
            product_name = product['name']
            if len(product_name) > 25:
                product_name = product_name[:22] + "..."
            
            builder.row(
                InlineKeyboardButton(
                    text=f"🗑️ {product_name} - {product['price']}₽",
                    callback_data=f"admin_delete_product_confirm_{product['id']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text='🔙 Назад', callback_data='admin_products')
        )
        
        await callback.message.edit_text(
            text="🗑️ Выберите товар для удаления:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при удалении товара: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_delete_product_confirm_'))
async def handle_admin_delete_product_confirm(callback: CallbackQuery):
    """Подтверждение удаления товара"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        product_id = int(callback.data.replace('admin_delete_product_confirm_', ''))
        
        product = db.get_product(product_id)
        if not product:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text='✅ Да, удалить', callback_data=f'admin_delete_product_final_{product_id}'),
            InlineKeyboardButton(text='❌ Нет, отмена', callback_data='admin_products')
        )
        
        await callback.message.edit_text(
            text=f"⚠️ Вы уверены, что хотите удалить товар?\n\n"
                 f"📦 {product['name']}\n"
                 f"💰 Цена: {product['price']}₽\n\n"
                 f"Это действие нельзя отменить!",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при подтверждении удаления товара: {e}")
        await callback.answer("Ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith('admin_delete_product_final_'))
async def handle_admin_delete_product_final(callback: CallbackQuery):
    """Финальное удаление товара"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        product_id = int(callback.data.replace('admin_delete_product_final_', ''))
        
        product = db.get_product(product_id)
        
        if db.delete_product(product_id):
            await callback.message.edit_text(
                text=f"✅ Товар успешно удален!\n\n"
                     f"📦 Название: {product['name']}\n"
                     f"💰 Цена: {product['price']}₽\n"
                     f"🆔 ID: {product_id}",
                reply_markup=admin_products_kb()
            )
            print(f"🗑️ Удален товар: {product['name']} (ID: {product_id})")
        else:
            await callback.message.edit_text(
                text="❌ Не удалось удалить товар. Возможно, товар не существует.",
                reply_markup=admin_products_kb()
            )
        
    except Exception as e:
        print(f"Ошибка при удалении товара: {e}")
        await callback.message.edit_text(
            text="❌ Ошибка при удалении товара",
            reply_markup=admin_products_kb()
        )
    
    await callback.answer()

# ==================== ОБРАБОТЧИКИ ПОДТВЕРЖДЕНИЯ АДМИНИСТРАТОРОМ ====================

@dp.callback_query(F.data.startswith('confirm_order_'))
async def handle_confirm_order(callback: CallbackQuery):
    """Подтвердить заказ администратором"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        order_id = callback.data.replace('confirm_order_', '')
        
        order_data = db.get_pending_order(order_id)
        if not order_data:
            await callback.answer("Заказ не найден", show_alert=True)
            return
        
        user_id = order_data.get('user_id')
        total_amount = order_data.get('total', 0)
        username = callback.from_user.username or callback.from_user.first_name
        
        is_cart_order = order_data.get('is_cart_order', False)
        
        if is_cart_order:
            product_name = f"Заказ из корзины ({order_data.get('total_quantity', 0)} товаров)"
        else:
            product_name = order_data.get('product_name', 'Неизвестный товар')
        
        db.remove_pending_order(order_id)
        
        try:
            if callback.message.photo:
                new_caption = callback.message.caption + f"\n\n✅ ПОДТВЕРЖДЕНО АДМИНИСТРАТОРОМ: @{username}"
                await bot.edit_message_caption(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    caption=new_caption,
                    reply_markup=None
                )
            else:
                new_text = callback.message.text + f"\n\n✅ ПОДТВЕРЖДЕНО АДМИНИСТРАТОРОМ: @{username}"
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=new_text,
                    reply_markup=None
                )
        except Exception as e:
            print(f"Ошибка обновления сообщения: {e}")
        
        try:
            if is_cart_order:
                cart_items_text = ""
                cart_items = order_data.get('cart_items', [])
                for item in cart_items:
                    cart_items_text += f"• {item['name']} x{item['quantity']} = {item['item_total']:.2f}₽\n"
                
                user_message = f"""✅ Ваш заказ из корзины подтвержден администратором!

🆔 Номер заказа: {order_id}
🛒 Состав заказа:
{cart_items_text}
📦 Всего товаров: {order_data.get('total_quantity', 0)} шт.
💰 Общая сумма: {total_amount:.2f}₽

📦 Товары будут отправлены вам в ближайшее время.
"""
            else:
                user_message = f"""✅ Ваш заказ подтвержден администратором!

🆔 Номер заказа: {order_id}
📦 Товар: {product_name}
💰 Сумма: {total_amount:.2f}₽

📦 Товар будет отправлен вам в ближайшее время.
"""
            
            await bot.send_message(chat_id=user_id, text=user_message)
            print(f"✅ Заказ {order_id} подтвержден для пользователя {user_id}")
        except Exception as e:
            print(f"Ошибка уведомления пользователя: {e}")
            await callback.answer("Пользователь не получил уведомление", show_alert=True)
        
        await callback.answer("✅ Заказ подтвержден")
        
    except Exception as e:
        print(f"Ошибка при подтверждении заказа: {e}")
        await callback.answer("❌ Ошибка при подтверждении", show_alert=True)

@dp.callback_query(F.data.startswith('reject_order_'))
async def handle_reject_order(callback: CallbackQuery):
    """Отклонить заказ администратором"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        order_id = callback.data.replace('reject_order_', '')
        
        order_data = db.get_pending_order(order_id)
        if not order_data:
            await callback.answer("Заказ не найден", show_alert=True)
            return
        
        user_id = order_data.get('user_id')
        total_amount = order_data.get('total', 0)
        
        is_cart_order = order_data.get('is_cart_order', False)
        
        if is_cart_order:
            product_name = f"Заказ из корзины ({order_data.get('total_quantity', 0)} товаров)"
        else:
            product_name = order_data.get('product_name', 'Неизвестный товар')
        
        db.remove_pending_order(order_id)
        
        try:
            if callback.message.photo:
                await bot.edit_message_caption(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    caption=callback.message.caption + f"\n\n❌ ОТКЛОНЕНО АДМИНИСТРАТОРОМ: @{callback.from_user.username}",
                    reply_markup=None
                )
            else:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=callback.message.text + f"\n\n❌ ОТКЛОНЕНО АДМИНИСТРАТОРОМ: @{callback.from_user.username}",
                    reply_markup=None
                )
        except Exception as e:
            print(f"Ошибка обновления сообщения: {e}")
        
        try:
            message_text = f"""❌ Ваш заказ отклонен администратором!

🆔 Номер заказа: {order_id}
📦 Товар: {product_name}
💰 Сумма: {total_amount:.2f}₽

💳 Если есть вопросы, обратитесь в поддержку: {config.ADMIN_USERNAME}
"""
            
            await bot.send_message(chat_id=user_id, text=message_text)
        except Exception as e:
            print(f"Ошибка уведомления пользователя: {e}")
        
        await callback.answer("❌ Заказ отклонен")
        
    except Exception as e:
        print(f"Ошибка при отклонении заказа: {e}")
        await callback.answer("❌ Ошибка при отклонении", show_alert=True)

@dp.callback_query(F.data.startswith('no_username_'))
async def handle_no_username_warning(callback: CallbackQuery):
    """Обработка предупреждения о отсутствии username"""
    try:
        if callback.from_user.id not in config.ADMIN_IDS:
            await callback.answer("⛔ Нет доступа", show_alert=True)
            return
        
        order_id = callback.data.replace('no_username_', '')
        
        order_data = db.get_pending_order(order_id)
        if not order_data:
            await callback.answer("Заказ не найден", show_alert=True)
            return
        
        user_id = order_data.get('user_id')
        
        warning_text = f"""⚠️ ВНИМАНИЕ! У покупателя НЕТ USERNAME!

🆔 ID заказа: {order_id}
🆔 ID покупателя: {user_id}

Действия:
1. Отклонить заказ и попросить установить username
2. Связаться с покупателем через личные сообщения по ID
3. Попросить покупателя написать вам напрямую

Риски:
• Невозможно отправить товар
• Невозможно уточнить детали
• Покупатель может не получить уведомления"""
        
        await callback.answer(warning_text, show_alert=True)
        
    except Exception as e:
        print(f"Ошибка при показе предупреждения: {e}")
        await callback.answer("Ошибка", show_alert=True)

# ==================== ОБРАБОТЧИК ПАГИНАЦИИ ====================

@dp.callback_query(F.data.startswith('page_'))
async def handle_page_change(callback: CallbackQuery):
    """Обработка смены страницы"""
    try:
        parts = callback.data.split('_')
        if len(parts) != 3:
            await callback.answer("Неверный формат запроса", show_alert=True)
            return
            
        category_id = int(parts[1])
        page = int(parts[2])
        
        category = db.get_category(category_id)
        category_name = category.get('name', 'Неизвестно') if category else 'Неизвестно'
        
        products = db.get_products_by_category(category_id)
        items_per_page = 5
        total_pages = max(1, (len(products) + items_per_page - 1) // items_per_page)
        
        if not products:
            text = f"📭 В категории '{category_name}' пока нет товаров"
        else:
            start_idx = page * items_per_page + 1
            end_idx = min((page + 1) * items_per_page, len(products))
            
            text = f"🛒 Товары в категории '{category_name}':\n"
            text += f"📄 Показано {start_idx}-{end_idx} из {len(products)} товаров\n\n"
            text += "Выберите товар:"
        
        await callback.message.edit_text(
            text=text,
            reply_markup=products_kb(category_id, page)
        )
        
    except ValueError:
        await callback.answer("Неверный ID категории", show_alert=True)
    except Exception as e:
        print(f"Ошибка при смене страницы: {e}")
        await callback.answer("Ошибка загрузки товаров", show_alert=True)
    
    await callback.answer()

# ==================== АДМИН КОМАНДЫ ====================

@dp.message(Command("addproduct"))
async def handle_add_product_command(message: Message, state: FSMContext):
    """Команда добавления товара"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            return
        
        categories = db.get_categories()
        if not categories:
            await message.answer(
                "❌ Нет доступных категорий.\nСначала создайте категорию командой /addcategory"
            )
            return
        
        await state.set_state(AddProductStates.waiting_for_category)
        
        builder = InlineKeyboardBuilder()
        for category in categories:
            builder.row(
                InlineKeyboardButton(
                    text=category["name"],
                    callback_data=f"admin_add_product_cat_{category['id']}"
                )
            )
        builder.row(InlineKeyboardButton(text='❌ Отмена', callback_data='cancel'))
        
        await message.answer(
            text="➕ Добавление нового товара\n\nВыберите категорию для товара:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        print(f"Ошибка при запуске добавления товара: {e}")
        await message.answer("❌ Произошла ошибка")
        await state.clear()

@dp.message(Command("addcategory"))
async def handle_add_category_command(message: Message):
    """Команда добавления категории"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            return
        
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            await message.answer(
                "❌ Не указано название категории.\n\n"
                "Использование:\n"
                "/addcategory <название категории>\n\n"
                "Пример:\n"
                "/addcategory 💻 Цифровые услуги"
            )
            return
        
        category_name = command_parts[1].strip()
        
        if len(category_name) < 2:
            await message.answer("❌ Название категории слишком короткое")
            return
        
        if len(category_name) > 50:
            await message.answer("❌ Название категории слишком длинное")
            return
        
        existing_categories = db.get_categories()
        for cat in existing_categories:
            if cat['name'].lower() == category_name.lower():
                await message.answer(f"❌ Категория с названием '{category_name}' уже существует")
                return
        
        category_id = db.add_category(category_name)
        
        await message.answer(
            text=f"✅ Категория добавлена!\n\n"
                 f"📁 Название: {category_name}\n"
                 f"🆔 ID: {category_id}",
            reply_markup=main_menu_kb(message.from_user.id)
        )
        
        print(f"✅ Добавлена новая категория: {category_name} (ID: {category_id})")
        
    except Exception as e:
        print(f"Ошибка при добавлении категории: {e}")
        await message.answer("❌ Ошибка при добавлении категории")

@dp.message(Command("stats"))
async def handle_stats_command(message: Message):
    """Команда показа статистики"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            return
        
        categories_count = len(db.get_categories())
        products_count = len(db.products)
        users_count = len(db.users)
        pending_orders = len(db.pending_orders)
        
        purchases = [t for t in db.transactions if t['type'] == 'purchase']
        total_purchases = sum(abs(t['amount']) for t in purchases)
        
        active_carts = len(cart_manager.carts)
        total_cart_items = sum(len(cart) for cart in cart_manager.carts.values())
        
        total_referrals = sum(len(u.get('referrals', [])) for u in db.users.values())
        total_rewards = sum(u.get('available_rewards', 0) for u in db.users.values())
        
        stats_text = f"""📊 СТАТИСТИКА БОТА (команда /stats)

📈 Общая статистика:
• 📁 Категорий: {categories_count}
• 📦 Товаров: {products_count}
• 👥 Пользователей: {users_count}
• ⏳ Ожидающих заказов: {pending_orders}
• 🛍️ Активных корзин: {active_carts}
• 🛒 Товаров в корзинах: {total_cart_items}

💰 Финансовая статистика:
• 🛒 Всего покупок: {len(purchases)}
• 💸 Общая сумма: {total_purchases:.2f}₽

🎁 Реферальная статистика:
• 👥 Всего рефералов: {total_referrals}
• 🎁 Доступно наград: {total_rewards}

💳 Способ оплаты:
• 🏦 Только Ozon (СБП/Карта)
"""
        
        await message.answer(stats_text)
        
    except Exception as e:
        print(f"Ошибка при показе статистики: {e}")
        await message.answer("❌ Ошибка при загрузке статистики")

@dp.message(Command("referral_stats"))
async def handle_referral_stats_command(message: Message):
    """Команда показа статистики рефералов"""
    try:
        if message.from_user.id not in config.ADMIN_IDS:
            await message.answer("⛔ У вас нет прав администратора")
            return
        
        config_ref = Config.REFERRAL_CONFIG
        
        total_referrals = sum(len(u.get('referrals', [])) for u in db.users.values())
        total_qualified = sum(u.get('qualified_referrals', 0) for u in db.users.values())
        total_rewards_available = sum(u.get('available_rewards', 0) for u in db.users.values())
        total_rewards_used = sum(u.get('used_rewards', 0) for u in db.users.values())
        
        top_referrers = []
        for user_id, user_data in db.users.items():
            referrals_count = len(user_data.get('referrals', []))
            if referrals_count > 0:
                top_referrers.append({
                    'user_id': user_id,
                    'referrals': referrals_count,
                    'qualified': user_data.get('qualified_referrals', 0)
                })
        
        top_referrers.sort(key=lambda x: x['referrals'], reverse=True)
        
        text = f"""🎁 **СТАТИСТИКА РЕФЕРАЛЬНОЙ ПРОГРАММЫ**

📊 **ОБЩАЯ СТАТИСТИКА:**
• Статус: {'✅ Включена' if config_ref['enabled'] else '❌ Выключена'}
• Минимальная сумма: {config_ref['min_purchase_amount']}₽
• Награда: {config_ref['reward_description']}

📈 **ПОКАЗАТЕЛИ:**
• Всего рефералов: {total_referrals}
• Квалифицированных: {total_qualified}
• Доступно наград: {total_rewards_available}
• Использовано наград: {total_rewards_used}

"""
        if top_referrers:
            text += "🏆 **ТОП РЕФЕРАЛОВ:**\n"
            for i, ref in enumerate(top_referrers[:5], 1):
                text += f"{i}. ID: {ref['user_id']} - {ref['referrals']} рефералов ({ref['qualified']} квалиф.)\n"
        
        await message.answer(text, parse_mode='Markdown')
        
    except Exception as e:
        print(f"Ошибка при показе статистики рефералов: {e}")
        await message.answer("❌ Ошибка")

@dp.callback_query(F.data == 'no_action')
async def handle_no_action(callback: CallbackQuery):
    """Обработка неактивных кнопок (номер страницы)"""
    await callback.answer()

@dp.callback_query(F.data == 'cancel')
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить текущую операцию"""
    try:
        await state.clear()
        await callback.message.edit_text(
            text="❌ Операция отменена",
            reply_markup=main_menu_kb(callback.from_user.id)
        )
    except Exception as e:
        print(f"Ошибка при отмене операции: {e}")
        await callback.answer("Ошибка при отмене", show_alert=True)
    
    await callback.answer()

@dp.message(F.text & ~F.command)
async def handle_unknown_text(message: Message, state: FSMContext):
    """Обработать неизвестные текстовые сообщения"""
    current_state = await state.get_state()
    
    if not current_state:
        if message.reply_to_message and "Добавление новой категории" in message.reply_to_message.text:
            try:
                if message.from_user.id not in config.ADMIN_IDS:
                    await message.answer("⛔ У вас нет прав администратора")
                    return
                
                category_name = message.text.strip()
                
                if len(category_name) < 2:
                    await message.answer("❌ Название категории слишком короткое")
                    return
                
                if len(category_name) > 50:
                    await message.answer("❌ Название категории слишком длинное")
                    return
                
                existing_categories = db.get_categories()
                for cat in existing_categories:
                    if cat['name'].lower() == category_name.lower():
                        await message.answer(f"❌ Категория с названием '{category_name}' уже существует")
                        return
                
                category_id = db.add_category(category_name)
                
                await message.answer(
                    text=f"✅ Категория добавлена!\n\n"
                         f"📁 Название: {category_name}\n"
                         f"🆔 ID: {category_id}",
                    reply_markup=admin_categories_kb()
                )
                
                print(f"✅ Добавлена новая категория: {category_name} (ID: {category_id})")
                
            except Exception as e:
                print(f"Ошибка при добавлении категории: {e}")
                await message.answer("❌ Ошибка при добавлении категории")
        else:
            await message.answer(
                text="👋 Для навигации используйте кнопки меню:",
                reply_markup=main_menu_kb(message.from_user.id)
            )


# Запускаем миграцию при старте
async def run_migration():
    await migrate_existing_users()

# ==================== ЗАПУСК БОТА ====================

async def main():
    """Основная функция запуска бота"""
    
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

⚙️ Конфигурация:
• 👨‍💼 Администраторы: {config.ADMIN_IDS}
• 💳 Оплата: Только Ozon (СБП/Карта)
• 📢 Канал подписки: {config.REQUIRED_CHANNEL}
• 🎁 Реферальная программа: {'Включена' if Config.REFERRAL_CONFIG['enabled'] else 'Выключена'}

🎉 НОВЫЕ ФУНКЦИИ:
• 🛍️ Корзина для покупки нескольких товаров
• 📢 Проверка подписки на канал
• 🎁 Реферальная программа с наградами

{'=' * 50}
✅ Бот готов к работе!
✅ Подписка на канал обязательна!
✅ Реферальная программа активна!
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
        print("✅ Данные корзины сохранены")
        await bot.session.close()
        print("✅ Сессия бота закрыта")

if __name__ == "__main__":
    asyncio.run(main())
