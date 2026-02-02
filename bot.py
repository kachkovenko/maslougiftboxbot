"""
Telegram Gift Management Bot
Бот для управления подарками на день рождения
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from database import Database, DATABASE_PATH

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    """Escape Markdown special characters for MarkdownV2"""
    if not text:
        return ""
    # Escape special MarkdownV2 characters (order matters for backslash)
    special_chars = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

# Conversation states
ADDING_GIFT_NAME, ADDING_GIFT_PRICE, ADDING_GIFT_CATEGORY = range(3)
SETTING_CONTRIBUTION = 3
BANNING_USER = 4
ADDING_FACT = 5
BROADCAST_MESSAGE = 6
EDITING_GIFT_NAME = 7
EDITING_GIFT_PRICE = 8

# Birthday person name (all declensions)
BIRTHDAY_PERSON = "Толя"          # Именительный: кто?
BIRTHDAY_PERSON_GEN = "Толи"      # Родительный: кого? (для Толи)
BIRTHDAY_PERSON_DAT = "Толе"      # Дательный: кому? (к Толе)  
BIRTHDAY_PERSON_ACC = "Толю"      # Винительный: кого? (узнать Толю)
BIRTHDAY_PERSON_PREP = "Толе"     # Предложный: о ком? (о Толе)

# Super admin ID (cannot be lost)
SUPER_ADMIN_ID = 143043787

# Initialize database
db = Database()

# Gift categories
CATEGORIES = {
    "tech": "🖥 Техника",
    "home": "🏠 Для дома",
    "hobby": "🎨 Хобби",
    "fashion": "👔 Одежда/Аксессуары",
    "experience": "🎭 Впечатления",
    "other": "📦 Другое"
}

# Status emojis
STATUS_EMOJI = {
    "available": "🟢",      # Свободен
    "claimed": "🟡",        # Один человек купит
    "shared": "👥",         # Несколько скидываются (не набрано)
    "funded": "🔴",         # Сумма полностью набрана
    "bought": "✅",         # Уже куплен
    "already_has": "🚫"     # Уже есть у именинника
}

# Minimum contribution amount
MIN_CONTRIBUTION = 1000  # Минимальный взнос 1000₽

# Maximum number of contributors for shared purchases
MAX_CONTRIBUTORS = 5  # Максимум 5 человек скидываются на один подарок


def is_banned(user_id: int) -> bool:
    """Check if user is banned (the birthday person)"""
    return db.is_user_banned(user_id)


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    if user_id == SUPER_ADMIN_ID:
        return True
    return db.is_admin(user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    user = update.effective_user
    
    # Track this user (before ban check so we can ban them later if needed!)
    db.track_user(user.id, user.username, user.full_name)
    
    if is_banned(user.id):
        await update.message.reply_text(
            "🎂 Привет, именинник(ца)! 🎂\n\n"
            "Этот бот — секрет! Тебе сюда нельзя 😉\n"
            "Жди сюрпризов на празднике! 🎁"
        )
        return ConversationHandler.END
    
    # Auto-add first user as admin
    if not db.has_any_admin():
        db.add_admin(user.id, user.full_name)
        await update.message.reply_text(
            "👑 Вы первый пользователь — теперь вы администратор!"
        )
    
    await show_main_menu(update, context)
    return ConversationHandler.END


async def export_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export database file (admin only)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ Только для администраторов")
        return
    
    if not os.path.exists(DATABASE_PATH):
        await update.message.reply_text("❌ База данных не найдена")
        return
    
    await update.message.reply_text("📤 Отправляю базу данных...")
    
    with open(DATABASE_PATH, 'rb') as f:
        await update.message.reply_document(
            document=f,
            filename="gifts_backup.db",
            caption="🗄 Бэкап базы данных\n\nСохраните этот файл!"
        )


async def import_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Import database file (admin only)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ Только для администраторов")
        return
    
    if not update.message.document:
        await update.message.reply_text(
            "📥 *Импорт базы данных*\n\n"
            "Отправьте файл `.db` ответом на это сообщение.\n\n"
            "⚠️ Текущие данные будут заменены!",
            parse_mode="Markdown"
        )
        return
    
    # Check file extension
    file_name = update.message.document.file_name
    if not file_name.endswith('.db'):
        await update.message.reply_text("❌ Нужен файл с расширением .db")
        return
    
    try:
        file = await update.message.document.get_file()
        await file.download_to_drive(DATABASE_PATH)
        
        # Reinitialize database connection
        global db
        db = Database()
        
        await update.message.reply_text(
            "✅ База данных успешно импортирована!\n\n"
            "Все данные восстановлены."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка импорта: {e}")


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast process (admin only)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("❌ Только для администраторов")
        return ConversationHandler.END
    
    users = db.get_all_users()
    banned = db.get_banned_users()
    banned_ids = {b['user_id'] for b in banned}
    
    # Count recipients (excluding banned)
    recipients = [u for u in users if u['user_id'] not in banned_ids]
    
    await update.message.reply_text(
        f"📢 *Рассылка сообщений*\n\n"
        f"Получателей: {len(recipients)} чел.\n"
        f"(забаненные исключены)\n\n"
        f"Напишите сообщение для рассылки:\n\n"
        f"_Отправьте /cancel для отмены_",
        parse_mode="Markdown"
    )
    return BROADCAST_MESSAGE


async def broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview and confirm broadcast"""
    context.user_data['broadcast_text'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("✅ Отправить всем", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")],
    ]
    
    await update.message.reply_text(
        f"📋 *Превью сообщения:*\n\n"
        f"{update.message.text}\n\n"
        f"─────────────────\n"
        f"Отправить это сообщение всем пользователям?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send broadcast to all users"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    text = context.user_data.get('broadcast_text')
    if not text:
        await query.edit_message_text("❌ Сообщение не найдено. Начните заново: /broadcast")
        return
    
    await query.edit_message_text("📤 Отправляю сообщения...")
    
    users = db.get_all_users()
    banned = db.get_banned_users()
    banned_ids = {b['user_id'] for b in banned}
    
    sent = 0
    failed = 0
    
    for u in users:
        if u['user_id'] in banned_ids:
            continue
        
        try:
            await context.bot.send_message(
                chat_id=u['user_id'],
                text=f"📢 *Объявление:*\n\n{text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1
    
    await query.edit_message_text(
        f"✅ *Рассылка завершена!*\n\n"
        f"📨 Доставлено: {sent}\n"
        f"❌ Не доставлено: {failed}\n\n"
        f"_(Не доставлено = заблокировали бота)_",
        parse_mode="Markdown"
    )
    
    context.user_data.pop('broadcast_text', None)


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel broadcast"""
    query = update.callback_query
    await query.answer("Рассылка отменена")
    
    context.user_data.pop('broadcast_text', None)
    
    await query.edit_message_text("❌ Рассылка отменена")
    await show_main_menu(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📋 Список подарков", callback_data="list_gifts")],
        [InlineKeyboardButton("➕ Добавить идею", callback_data="add_gift")],
        [InlineKeyboardButton(f"💡 Узнать {BIRTHDAY_PERSON_ACC} лучше", callback_data="facts_menu")],
        [InlineKeyboardButton("🎁 Мои подарки", callback_data="my_gifts")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"🎁 *Бот для сбора подарков* 🎁\n\n"
        f"Здесь мы собираем идеи подарков для {BIRTHDAY_PERSON_GEN} и координируем покупки!\n\n"
        f"📋 — посмотреть все идеи\n"
        f"➕ — предложить свою идею\n"
        f"💡 — узнать больше о {BIRTHDAY_PERSON_PREP}\n"
        f"🎁 — посмотреть что вы покупаете\n"
        f"📊 — общая статистика\n"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )


async def list_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all gifts"""
    query = update.callback_query
    await query.answer()
    
    gifts = db.get_all_gifts()
    
    if not gifts:
        keyboard = [[InlineKeyboardButton("➕ Добавить первую идею", callback_data="add_gift")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        await query.edit_message_text(
            "📋 Список пока пуст!\n\nБудьте первым — добавьте идею подарка!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Group by category
    by_category = {}
    for gift in gifts:
        cat = gift['category'] or 'other'
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(gift)
    
    text = "📋 *Список идей подарков:*\n\n"
    keyboard = []
    
    for cat_key, cat_name in CATEGORIES.items():
        if cat_key in by_category:
            text += f"\n{escape_md(cat_name)}\n"
            for gift in by_category[cat_key]:
                price_str = f"{gift['price']}₽" if gift['price'] else "цена?"
                buyers = db.get_gift_buyers(gift['id'])
                
                # Determine the right status icon
                if gift['status'] in ["bought", "already_has"]:
                    status = STATUS_EMOJI.get(gift['status'], "🟢")
                elif gift['status'] == "claimed" and buyers:
                    total_pledged = sum(b['amount'] or 0 for b in buyers)
                    gift_price = gift['price'] or 0

                    # Check if fully funded
                    if gift_price > 0 and total_pledged >= gift_price:
                        status = "🔴"  # Fully funded
                    # Check if it's a shared purchase (any buyer contributed less than full price)
                    elif any(b['amount'] and b['amount'] < gift_price for b in buyers):
                        status = "👥"  # Sharing (even if only one person so far)
                    else:
                        status = "🟡"  # Single buyer who will buy solo
                else:
                    status = STATUS_EMOJI.get(gift['status'], "🟢")
                
                buyer_info = ""
                if buyers:
                    buyer_parts = []
                    for b in buyers:
                        name = escape_md(b['user_name'].split()[0])
                        if b['amount']:
                            buyer_parts.append(f"{name} {b['amount']}₽")
                        else:
                            buyer_parts.append(name)
                    buyer_info = f" \\- {', '.join(buyer_parts)}"
                
                gift_name_escaped = escape_md(gift['name'])
                text += f"{status} {gift_name_escaped} \\(\\~{escape_md(price_str)}\\){buyer_info}\n"
                keyboard.append([InlineKeyboardButton(
                    f"{status} {gift['name'][:30]}",
                    callback_data=f"gift_{gift['id']}"
                )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    # Trim text if too long
    if len(text) > 4000:
        text = text[:4000] + "\n\n\\.\\.\\. \\(список сокращён\\)"
    
    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )


async def show_gift_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show details for a specific gift"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    gift = db.get_gift(gift_id)
    
    if not gift:
        await query.edit_message_text("❌ Подарок не найден")
        return
    
    user = update.effective_user
    buyers = db.get_gift_buyers(gift_id)
    
    # Calculate funding status
    total_pledged = sum(b['amount'] or 0 for b in buyers)
    gift_price = gift['price'] or 0
    is_fully_funded = gift_price > 0 and total_pledged >= gift_price
    
    # Check if it's a shared purchase (any buyer contributed less than full price)
    is_sharing = any(b['amount'] and b['amount'] < gift_price for b in buyers)

    # Determine status emoji and text
    if gift['status'] == "bought":
        status = "✅"
        status_text = "Уже куплен"
    elif gift['status'] == "already_has":
        status = "🚫"
        status_text = "Уже есть у именинника"
    elif gift['status'] == "claimed":
        if is_fully_funded:
            status = "🔴"
            status_text = "Сумма собрана\\!"
        elif is_sharing:
            status = "👥"
            if len(buyers) == 1:
                status_text = "Ищут компанию для скидывания"
            else:
                status_text = "Скидываются несколько человек"
        else:
            status = "🟡"
            status_text = "Кто\\-то покупает"
    else:
        status = "🟢"
        status_text = "Свободен"
    
    price_str = f"{gift['price']}₽" if gift['price'] else "не указана"
    category = CATEGORIES.get(gift['category'], CATEGORIES['other'])
    
    # Escape user-provided data
    gift_name = escape_md(gift['name'])
    added_by = escape_md(gift['added_by_name'])
    
    text = (
        f"🎁 *{gift_name}*\n\n"
        f"💰 Цена: \\~{escape_md(price_str)}\n"
        f"📁 Категория: {escape_md(category)}\n"
        f"📊 Статус: {status} {status_text}\n"
        f"💡 Добавил: {added_by}\n"
    )
    
    # Show funding progress if there are buyers
    if buyers and gift_price > 0:
        progress_pct = min(100, int(total_pledged / gift_price * 100))
        text += f"\n💵 *Собрано:* {total_pledged} из {gift_price}₽ \\({progress_pct}%\\)\n"
    
    if buyers:
        text += "\n👥 *Участники:*\n"
        for buyer in buyers:
            buyer_name = escape_md(buyer['user_name'])
            amount = f" \\- {buyer['amount']}₽" if buyer['amount'] else " \\- сумма не указана"
            text += f"  • {buyer_name}{amount}\n"
    
    keyboard = []
    
    # Check if current user is a buyer
    user_is_buyer = any(b['user_id'] == user.id for b in buyers)
    
    if gift['status'] == "available":
        keyboard.append([InlineKeyboardButton("🙋 Я куплю это сам!", callback_data=f"claim_{gift_id}")])
        if gift_price and gift_price >= MIN_CONTRIBUTION * 2:
            keyboard.append([InlineKeyboardButton("👥 Скинемся вместе", callback_data=f"share_{gift_id}")])
    elif gift['status'] == "claimed":
        if user_is_buyer:
            keyboard.append([InlineKeyboardButton("✅ Уже купил!", callback_data=f"bought_{gift_id}")])
            keyboard.append([InlineKeyboardButton("❌ Отказаться", callback_data=f"unclaim_{gift_id}")])
        elif not is_fully_funded and gift_price and gift_price >= MIN_CONTRIBUTION * 2:
            # Can join only if not fully funded
            keyboard.append([InlineKeyboardButton("👥 Присоединиться", callback_data=f"share_{gift_id}")])
    
    if gift['status'] not in ["already_has", "bought"]:
        keyboard.append([InlineKeyboardButton("🚫 Уже есть у именинника", callback_data=f"already_has_{gift_id}")])

    if is_admin(user.id):
        keyboard.append([
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{gift_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{gift_id}")
        ])

    keyboard.append([InlineKeyboardButton("🔙 К списку", callback_data="list_gifts")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )


async def claim_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Claim a gift for yourself (buying solo)"""
    query = update.callback_query
    
    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    gift = db.get_gift(gift_id)
    
    if not gift:
        await query.answer("❌ Подарок не найден", show_alert=True)
        return
    
    # Set amount to full price when claiming solo
    amount = gift['price'] if gift['price'] else None
    db.add_buyer(gift_id, user.id, user.full_name, amount)
    db.update_gift_status(gift_id, "claimed")
    
    await query.answer("✅ Отлично! Вы записались на этот подарок!", show_alert=True)
    
    # Refresh gift details
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


def get_contribution_options(price: int, existing_pledged: int = 0) -> list:
    """Calculate reasonable contribution options for a gift price

    Constraints:
    - Minimum contribution: MIN_CONTRIBUTION (1000₽)
    - Maximum contributors: MAX_CONTRIBUTORS (5 people)
    - So minimum contribution is max(MIN_CONTRIBUTION, price / MAX_CONTRIBUTORS)
    """
    if not price or price <= 0:
        return []

    remaining = price - existing_pledged
    if remaining <= 0:
        return []

    # Minimum contribution to ensure no more than MAX_CONTRIBUTORS people
    min_share = max(MIN_CONTRIBUTION, remaining // MAX_CONTRIBUTORS)

    options = []

    # Find divisors of the remaining amount that are >= min_share
    # and result in a reasonable number of contributors (2-MAX_CONTRIBUTORS people)
    for num_people in range(2, MAX_CONTRIBUTORS + 1):
        share = remaining // num_people
        if share >= min_share and remaining % num_people == 0:
            if share not in options:
                options.append(share)

    # Also add some round numbers that divide evenly
    round_amounts = [1000, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000, 15000, 20000]
    for amount in round_amounts:
        if amount >= min_share and amount <= remaining and remaining % amount == 0:
            # Check that this amount doesn't require more than MAX_CONTRIBUTORS people
            num_people_needed = remaining // amount
            if num_people_needed <= MAX_CONTRIBUTORS and amount not in options:
                options.append(amount)

    # Sort and limit to 6 options
    options = sorted(set(options))

    # Filter to keep reasonable range (not more than 60% of remaining, unless it's the only option)
    options = [o for o in options if o <= remaining * 0.6 or o == remaining]

    return options[:6]


async def share_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Join shared purchase - show contribution options or fixed amount"""
    query = update.callback_query
    await query.answer()

    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    gift = db.get_gift(gift_id)

    if not gift:
        await query.answer("❌ Подарок не найден", show_alert=True)
        return

    # Check if already participating
    buyers = db.get_gift_buyers(gift_id)
    if any(b['user_id'] == user.id for b in buyers):
        await query.answer("Вы уже участвуете в покупке этого подарка!", show_alert=True)
        return

    # Check if fully funded
    total_pledged = sum(b['amount'] or 0 for b in buyers)
    if gift['price'] and total_pledged >= gift['price']:
        await query.answer("❌ Сумма уже полностью собрана!", show_alert=True)
        return

    gift_price = gift['price'] or 0
    remaining = gift_price - total_pledged

    context.user_data['contribution_gift_id'] = gift_id

    # Check if there are already contributors with a set amount
    # If so, the contribution amount is fixed (first contributor sets it)
    existing_contribution = None
    for buyer in buyers:
        if buyer['amount'] and buyer['amount'] < gift_price:
            existing_contribution = buyer['amount']
            break

    keyboard = []

    if existing_contribution:
        # Fixed amount - first contributor already set the price
        keyboard.append([InlineKeyboardButton(
            f"✅ Присоединиться за {existing_contribution}₽",
            callback_data=f"contrib_{gift_id}_{existing_contribution}"
        )])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"gift_{gift_id}")])

        participants_info = ", ".join([escape_md(b['user_name'].split()[0]) for b in buyers])
        needed_people = gift_price // existing_contribution
        current_people = len(buyers)

        await query.edit_message_text(
            f"👥 *Присоединиться к сбору*\n\n"
            f"🎁 {escape_md(gift['name'])}\n"
            f"💰 Цена: {escape_md(str(gift_price))}₽\n\n"
            f"📊 Сумма взноса: *{existing_contribution}₽*\n"
            f"👥 Уже участвуют \\({current_people}/{needed_people}\\): {participants_info}\n"
            f"💵 Собрано: {total_pledged} из {gift_price}₽\n\n"
            f"Хотите присоединиться?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )
    else:
        # No contributors yet - show options for first contributor
        options = get_contribution_options(gift_price, total_pledged)

        if options:
            # Create rows of 2 buttons each
            for i in range(0, len(options), 2):
                row = []
                for opt in options[i:i+2]:
                    num_people = remaining // opt
                    row.append(InlineKeyboardButton(
                        f"{opt}₽ ({num_people} чел.)",
                        callback_data=f"contrib_{gift_id}_{opt}"
                    ))
                keyboard.append(row)

        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"gift_{gift_id}")])

        await query.edit_message_text(
            f"👥 *Скинуться на подарок*\n\n"
            f"🎁 {escape_md(gift['name'])}\n"
            f"💰 Цена: {escape_md(str(gift_price))}₽\n"
            f"📊 Осталось собрать: {escape_md(str(remaining))}₽\n\n"
            f"Вы первый\\! Выберите сумму взноса\\.\n"
            f"_Остальные участники будут скидываться по той же сумме\\._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )


async def select_contribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contribution amount selection"""
    query = update.callback_query
    
    parts = query.data.split("_")
    gift_id = int(parts[1])
    amount = int(parts[2])
    user = update.effective_user
    
    # Check if already participating
    buyers = db.get_gift_buyers(gift_id)
    if any(b['user_id'] == user.id for b in buyers):
        await query.answer("Вы уже участвуете!", show_alert=True)
        return
    
    # Add buyer with amount
    db.add_buyer(gift_id, user.id, user.full_name, amount)
    db.update_gift_status(gift_id, "claimed")
    
    await query.answer(f"✅ Отлично! Вы вложили {amount}₽", show_alert=True)
    
    # Show gift details
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


async def set_contribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set contribution amount (legacy text input)"""
    user = update.effective_user
    gift_id = context.user_data.get('contribution_gift_id')
    
    if not gift_id:
        await update.message.reply_text("❌ Ошибка. Попробуйте заново.")
        return ConversationHandler.END
    
    try:
        amount = int(update.message.text.replace(" ", "").replace("₽", ""))
        db.update_buyer_amount(gift_id, user.id, amount)
        await update.message.reply_text(f"✅ Отлично! Записано: {amount}₽")
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите число")
        return SETTING_CONTRIBUTION
    
    await show_main_menu(update, context)
    return ConversationHandler.END


async def skip_contribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip setting contribution amount"""
    query = update.callback_query
    await query.answer("✅ Вы добавлены к покупке!", show_alert=True)
    await show_main_menu(update, context)
    return ConversationHandler.END


async def unclaim_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove yourself from gift"""
    query = update.callback_query
    
    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    
    db.remove_buyer(gift_id, user.id)
    
    # Check if any buyers left
    buyers = db.get_gift_buyers(gift_id)
    if not buyers:
        db.update_gift_status(gift_id, "available")
    
    await query.answer("✅ Вы успешно отказались от покупки", show_alert=True)
    
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


async def mark_bought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark gift as bought"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    db.update_gift_status(gift_id, "bought")
    
    await query.answer("🎉 Подарок помечен как купленный!", show_alert=True)
    
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


async def mark_already_has(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark gift as 'already has'"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    db.update_gift_status(gift_id, "already_has")
    
    # Remove all buyers since gift is invalid now
    db.remove_all_buyers(gift_id)
    
    await query.answer("🚫 Подарок помечен как 'уже есть'", show_alert=True)
    
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


async def start_add_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a new gift"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]]
    
    await query.edit_message_text(
        "➕ *Добавление идеи подарка*\n\n"
        "Напишите название подарка:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADDING_GIFT_NAME


async def add_gift_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save gift name and ask for price"""
    context.user_data['new_gift_name'] = update.message.text
    
    keyboard = [[InlineKeyboardButton("Пропустить", callback_data="skip_price")]]
    
    await update.message.reply_text(
        f"✅ Название: *{update.message.text}*\n\n"
        "💰 Укажите примерную цену (в рублях):\n"
        "Или нажмите 'Пропустить'",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADDING_GIFT_PRICE


async def add_gift_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save gift price and ask for category"""
    try:
        price = int(update.message.text.replace(" ", "").replace("₽", ""))
        context.user_data['new_gift_price'] = price
    except ValueError:
        await update.message.reply_text("❌ Введите число. Например: 5000")
        return ADDING_GIFT_PRICE
    
    await ask_category(update, context)
    return ADDING_GIFT_CATEGORY


async def skip_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip price input"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['new_gift_price'] = None
    await ask_category(update, context, edit=True)
    return ADDING_GIFT_CATEGORY


async def ask_category(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    """Ask for category"""
    keyboard = []
    for key, name in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=f"category_{key}")])
    
    text = "📁 Выберите категорию:"
    
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def add_gift_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save category and create gift"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.split("_")[1]
    user = update.effective_user
    
    gift_id = db.add_gift(
        name=context.user_data['new_gift_name'],
        price=context.user_data.get('new_gift_price'),
        category=category,
        added_by_id=user.id,
        added_by_name=user.full_name
    )
    
    gift_name = escape_md(context.user_data['new_gift_name'])
    price_display = context.user_data.get('new_gift_price', 'не указана')
    
    await query.edit_message_text(
        f"🎉 *Идея добавлена\\!*\n\n"
        f"🎁 {gift_name}\n"
        f"💰 {escape_md(str(price_display))}₽\n"
        f"📁 {CATEGORIES[category]}",
        parse_mode="MarkdownV2"
    )
    
    # Clear user data
    context.user_data.clear()
    
    await show_main_menu(update, context)
    return ConversationHandler.END


async def my_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's claimed gifts"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    gifts = db.get_user_gifts(user.id)
    
    if not gifts:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        await query.edit_message_text(
            "🎁 *Мои подарки*\n\n"
            "Вы пока не записались ни на один подарок.\n"
            "Загляните в список идей!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    text = "🎁 *Мои подарки:*\n\n"
    keyboard = []
    
    for gift in gifts:
        status = STATUS_EMOJI.get(gift['status'], "🟢")
        price_str = f"{gift['price']}₽" if gift['price'] else "?"
        amount = f" \\(ваш вклад: {gift['amount']}₽\\)" if gift.get('amount') else ""
        
        gift_name = escape_md(gift['name'])
        text += f"{status} {gift_name} \\(\\~{escape_md(price_str)}\\){amount}\n"
        keyboard.append([InlineKeyboardButton(
            f"{status} {gift['name'][:30]}",
            callback_data=f"gift_{gift['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    query = update.callback_query
    await query.answer()
    
    stats = db.get_stats()
    
    text = (
        "📊 *Статистика:*\n\n"
        f"📋 Всего идей: {stats['total']}\n"
        f"🟢 Свободных: {stats['available']}\n"
        f"🟡 В процессе: {stats['claimed']}\n"
        f"✅ Куплено: {stats['bought']}\n"
        f"🚫 Уже есть: {stats['already_has']}\n\n"
        f"👥 Участников: {stats['participants']}\n"
        f"💰 Собрано: ~{stats['total_amount']}₽"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ============ FACTS ABOUT BIRTHDAY PERSON ============

async def facts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show facts menu"""
    query = update.callback_query
    await query.answer()
    
    facts_count = db.get_facts_count()
    
    keyboard = [
        [InlineKeyboardButton(f"📖 Почитать о {BIRTHDAY_PERSON_PREP}", callback_data="read_facts")],
        [InlineKeyboardButton(f"✏️ Рассказать о {BIRTHDAY_PERSON_PREP}", callback_data="add_fact")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
    ]
    
    text = (
        f"💡 *Узнать {BIRTHDAY_PERSON_ACC} лучше*\n\n"
        f"Здесь гости делятся тем, что знают о {BIRTHDAY_PERSON_PREP} — "
        f"его увлечениях, вкусах и мечтах.\n"
        f"Это поможет выбрать идеальный подарок!\n\n"
        f"📝 Уже рассказов: {facts_count}"
    )
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def read_facts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all facts about the birthday person"""
    query = update.callback_query
    await query.answer()
    
    facts = db.get_all_facts()
    
    if not facts:
        keyboard = [
            [InlineKeyboardButton(f"✏️ Рассказать первым!", callback_data="add_fact")],
            [InlineKeyboardButton("🔙 Назад", callback_data="facts_menu")],
        ]
        await query.edit_message_text(
            f"📖 *Что мы знаем о {BIRTHDAY_PERSON_PREP}:*\n\n"
            f"Пока ничего... 😅\n\n"
            f"Будьте первым — расскажите что-нибудь о {BIRTHDAY_PERSON_PREP}!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    text = f"📖 *Что мы знаем о {BIRTHDAY_PERSON_PREP}:*\n\n"
    
    for fact in facts:
        text += f"💬 _{fact['fact_text']}_\n\n"
    
    # Trim if too long
    if len(text) > 3800:
        text = text[:3800] + "\n\n... _(показаны не все записи)_"
    
    keyboard = [
        [InlineKeyboardButton("✏️ Добавить своё", callback_data="add_fact")],
        [InlineKeyboardButton("🔙 Назад", callback_data="facts_menu")],
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def start_add_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a fact"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="facts_menu")]]
    
    await query.edit_message_text(
        f"✏️ *Расскажите что-нибудь о {BIRTHDAY_PERSON_PREP}!*\n\n"
        f"Чем увлекается {BIRTHDAY_PERSON}? Что любит есть и пить?\n"
        f"Как проводит свободное время? О чём мечтает?\n\n"
        f"Любая информация поможет гостям выбрать подарок.\n\n"
        f"_Напишите одним сообщением:_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ADDING_FACT


async def save_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the fact"""
    user = update.effective_user
    fact_text = update.message.text.strip()
    
    if len(fact_text) < 5:
        await update.message.reply_text(
            "❌ Слишком короткое сообщение. Расскажите чуть подробнее!"
        )
        return ADDING_FACT
    
    if len(fact_text) > 500:
        await update.message.reply_text(
            "❌ Слишком длинное сообщение. Попробуйте уложиться в 500 символов."
        )
        return ADDING_FACT
    
    db.add_fact(user.id, fact_text)
    
    keyboard = [
        [InlineKeyboardButton("✏️ Добавить ещё", callback_data="add_fact")],
        [InlineKeyboardButton("📖 Почитать что пишут другие", callback_data="read_facts")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")],
    ]
    
    await update.message.reply_text(
        f"✅ *Спасибо! Ваш рассказ сохранён.*\n\n"
        f"Вы написали:\n"
        f"_{fact_text}_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return ConversationHandler.END


# ============ ADMIN FUNCTIONS ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        await query.answer("❌ Только для администраторов", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("🚫 Забанить именинника", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Разбанить пользователя", callback_data="admin_unban")],
        [InlineKeyboardButton("👑 Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton("📋 Список забаненных", callback_data="admin_banned_list")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
    ]
    
    await query.edit_message_text(
        "⚙️ *Админ-панель*\n\n"
        "Команды:\n"
        "📢 /broadcast — рассылка всем пользователям\n"
        "📤 /export — скачать бэкап базы\n"
        "📥 /import — восстановить из бэкапа\n",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def admin_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start banning process - show options"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📋 Выбрать из списка", callback_data="ban_from_list")],
        [InlineKeyboardButton("✏️ Ввести ID вручную", callback_data="ban_manual")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
    ]
    
    await query.edit_message_text(
        "🚫 *Забанить именинника*\n\n"
        "Выберите способ:\n\n"
        "📋 *Из списка* — выбрать из пользователей, которые уже писали боту\n"
        "✏️ *Вручную* — ввести Telegram ID\n\n"
        "💡 _Совет: попросите именинника написать боту /start до того, "
        "как вы его забаните — тогда он появится в списке_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def ban_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of users to ban"""
    query = update.callback_query
    await query.answer()
    
    users = db.get_all_users()
    
    if not users:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_ban")]]
        await query.edit_message_text(
            "📋 Список пуст!\n\n"
            "Пока никто не писал боту.\n"
            "Попросите именинника написать /start",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for u in users[:20]:  # Limit to 20 users
        display_name = u['full_name'] or u['username'] or f"ID: {u['user_id']}"
        username_str = f" (@{u['username']})" if u['username'] else ""
        keyboard.append([InlineKeyboardButton(
            f"🚫 {display_name}{username_str}",
            callback_data=f"confirm_ban_{u['user_id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_ban")])
    
    await query.edit_message_text(
        "📋 *Выберите кого забанить:*\n\n"
        "_Это пользователи, которые писали боту_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def confirm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm ban action"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split("_")[2])
    context.user_data['ban_target_id'] = user_id
    
    # Try to get user info
    users = db.get_all_users()
    target_user = next((u for u in users if u['user_id'] == user_id), None)
    
    if target_user:
        name = target_user['full_name'] or target_user['username'] or str(user_id)
    else:
        name = str(user_id)
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, забанить!", callback_data=f"do_ban_{user_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="ban_from_list")],
    ]
    
    await query.edit_message_text(
        f"⚠️ *Подтверждение*\n\n"
        f"Вы уверены, что хотите забанить:\n"
        f"👤 *{name}*\n"
        f"🆔 `{user_id}`\n\n"
        f"Этот пользователь больше не сможет пользоваться ботом.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def do_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually perform the ban"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split("_")[2])
    
    # Get user info for the name
    users = db.get_all_users()
    target_user = next((u for u in users if u['user_id'] == user_id), None)
    name = target_user['full_name'] if target_user else "Пользователь"
    
    db.ban_user(user_id, name)
    
    await query.edit_message_text(
        f"✅ *Готово!*\n\n"
        f"Пользователь *{name}* забанен.\n"
        f"Теперь он не сможет видеть список подарков!",
        parse_mode="Markdown"
    )
    
    # Return to admin panel after a moment
    await show_main_menu(update, context)


async def ban_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start manual ban input"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_ban")]]
    
    await query.edit_message_text(
        "✏️ *Ввод ID вручную*\n\n"
        "Отправьте Telegram ID пользователя (только цифры).\n\n"
        "💡 _Как узнать ID:_\n"
        "1. Именинник пишет боту @userinfobot\n"
        "2. Бот присылает его ID\n"
        "3. Именинник говорит вам этот ID",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BANNING_USER


async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user by ID input"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END
    
    text = update.message.text.strip()
    
    # Try to parse as ID
    try:
        target_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Это не похоже на ID.\n\n"
            "ID состоит только из цифр, например: `123456789`\n"
            "Попробуйте ещё раз или нажмите Отмена.",
            parse_mode="Markdown"
        )
        return BANNING_USER
    
    # Check if trying to ban themselves
    if target_id == user.id:
        await update.message.reply_text("❌ Вы не можете забанить самого себя!")
        return BANNING_USER
    
    db.ban_user(target_id, f"ID: {target_id}")
    
    await update.message.reply_text(
        f"✅ Пользователь с ID `{target_id}` забанен!\n"
        "Теперь он не сможет пользоваться ботом.",
        parse_mode="Markdown"
    )
    
    await show_main_menu(update, context)
    return ConversationHandler.END


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show unban menu"""
    query = update.callback_query
    await query.answer()
    
    banned = db.get_banned_users()
    
    if not banned:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await query.edit_message_text(
            "Нет забаненных пользователей",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for user in banned:
        keyboard.append([InlineKeyboardButton(
            f"✅ Разбанить {user['name']}",
            callback_data=f"unban_{user['user_id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    
    await query.edit_message_text(
        "Выберите кого разбанить:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def do_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually unban user"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split("_")[1])
    db.unban_user(user_id)
    
    await query.answer("✅ Пользователь разбанен!", show_alert=True)
    await admin_panel(update, context)


async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of banned users"""
    query = update.callback_query
    await query.answer()
    
    banned = db.get_banned_users()
    
    if not banned:
        text = "Нет забаненных пользователей"
    else:
        text = "🚫 *Забаненные пользователи:*\n\n"
        for user in banned:
            text += f"• {user['name']} (ID: {user['user_id']})\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding admin"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👑 *Добавить админа*\n\n"
        "Попросите нового админа написать боту /start,\n"
        "затем перешлите сюда его сообщение.",
        parse_mode="Markdown"
    )
    return BANNING_USER  # Reuse state


async def delete_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a gift (admin only)"""
    query = update.callback_query

    user = update.effective_user
    if not is_admin(user.id):
        await query.answer("❌ Только для администраторов", show_alert=True)
        return

    gift_id = int(query.data.split("_")[1])
    db.delete_gift(gift_id)

    await query.answer("🗑 Подарок удалён!", show_alert=True)
    await list_gifts(update, context)


# ============ EDIT GIFT (ADMIN) ============

async def start_edit_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing a gift (admin only)"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_admin(user.id):
        await query.answer("❌ Только для администраторов", show_alert=True)
        return ConversationHandler.END

    gift_id = int(query.data.split("_")[1])
    gift = db.get_gift(gift_id)

    if not gift:
        await query.answer("❌ Подарок не найден", show_alert=True)
        return ConversationHandler.END

    context.user_data['edit_gift_id'] = gift_id

    price_str = f"{gift['price']}₽" if gift['price'] else "не указана"

    keyboard = [
        [InlineKeyboardButton("✏️ Изменить название", callback_data=f"edit_name_{gift_id}")],
        [InlineKeyboardButton("💰 Изменить цену", callback_data=f"edit_price_{gift_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"gift_{gift_id}")],
    ]

    await query.edit_message_text(
        f"✏️ *Редактирование подарка*\n\n"
        f"🎁 Название: {escape_md(gift['name'])}\n"
        f"💰 Цена: {escape_md(price_str)}\n\n"
        f"Что хотите изменить?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )
    return ConversationHandler.END


async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing gift name"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    gift_id = int(query.data.split("_")[2])
    context.user_data['edit_gift_id'] = gift_id

    gift = db.get_gift(gift_id)
    if not gift:
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"edit_{gift_id}")]]

    await query.edit_message_text(
        f"✏️ *Изменение названия*\n\n"
        f"Текущее название: {escape_md(gift['name'])}\n\n"
        f"Введите новое название:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )
    return EDITING_GIFT_NAME


async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new gift name"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    gift_id = context.user_data.get('edit_gift_id')
    if not gift_id:
        await update.message.reply_text("❌ Ошибка. Попробуйте заново.")
        return ConversationHandler.END

    new_name = update.message.text.strip()
    if len(new_name) < 2:
        await update.message.reply_text("❌ Название слишком короткое. Попробуйте ещё раз:")
        return EDITING_GIFT_NAME

    db.update_gift(gift_id, name=new_name)

    await update.message.reply_text(
        f"✅ Название изменено на: *{new_name}*",
        parse_mode="Markdown"
    )

    # Show gift details
    context.user_data.clear()
    await show_main_menu(update, context)
    return ConversationHandler.END


async def edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing gift price"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    gift_id = int(query.data.split("_")[2])
    context.user_data['edit_gift_id'] = gift_id

    gift = db.get_gift(gift_id)
    if not gift:
        return ConversationHandler.END

    price_str = f"{gift['price']}₽" if gift['price'] else "не указана"

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"edit_{gift_id}")]]

    await query.edit_message_text(
        f"💰 *Изменение цены*\n\n"
        f"Текущая цена: {escape_md(price_str)}\n\n"
        f"Введите новую цену \\(в рублях\\):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )
    return EDITING_GIFT_PRICE


async def edit_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new gift price"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    gift_id = context.user_data.get('edit_gift_id')
    if not gift_id:
        await update.message.reply_text("❌ Ошибка. Попробуйте заново.")
        return ConversationHandler.END

    try:
        new_price = int(update.message.text.replace(" ", "").replace("₽", ""))
        if new_price <= 0:
            raise ValueError("Price must be positive")
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число. Например: 5000")
        return EDITING_GIFT_PRICE

    db.update_gift(gift_id, price=new_price)

    await update.message.reply_text(
        f"✅ Цена изменена на: *{new_price}₽*",
        parse_mode="Markdown"
    )

    context.user_data.clear()
    await show_main_menu(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    context.user_data.clear()
    await show_main_menu(update, context)
    return ConversationHandler.END


async def handle_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button press"""
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context)


def main():
    """Main function to run the bot"""
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Conversation handler for adding gifts
    add_gift_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_gift, pattern="^add_gift$")],
        states={
            ADDING_GIFT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_gift_name),
                CallbackQueryHandler(handle_main_menu_callback, pattern="^main_menu$"),
            ],
            ADDING_GIFT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_gift_price),
                CallbackQueryHandler(skip_price, pattern="^skip_price$"),
            ],
            ADDING_GIFT_CATEGORY: [
                CallbackQueryHandler(add_gift_category, pattern="^category_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(handle_main_menu_callback, pattern="^main_menu$"),
        ],
    )
    
    # Conversation handler for banning (manual ID input)
    ban_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ban_manual_start, pattern="^ban_manual$")],
        states={
            BANNING_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_user),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$"),
        ],
    )
    
    # Conversation handler for adding facts
    facts_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_fact, pattern="^add_fact$")],
        states={
            ADDING_FACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_fact),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(facts_menu, pattern="^facts_menu$"),
        ],
    )
    
    # Conversation handler for broadcast
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_preview),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
    )

    # Conversation handler for editing gift name
    edit_name_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_name_start, pattern="^edit_name_")],
        states={
            EDITING_GIFT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(start_edit_gift, pattern="^edit_\\d+$"),
        ],
    )

    # Conversation handler for editing gift price
    edit_price_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_price_start, pattern="^edit_price_")],
        states={
            EDITING_GIFT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_save),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(start_edit_gift, pattern="^edit_\\d+$"),
        ],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CommandHandler("export", export_db))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.COMMAND, import_db))
    application.add_handler(CommandHandler("import", import_db))
    application.add_handler(add_gift_handler)
    application.add_handler(ban_handler)
    application.add_handler(facts_handler)
    application.add_handler(broadcast_handler)
    application.add_handler(edit_name_handler)
    application.add_handler(edit_price_handler)

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(handle_main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(list_gifts, pattern="^list_gifts$"))
    application.add_handler(CallbackQueryHandler(my_gifts, pattern="^my_gifts$"))
    application.add_handler(CallbackQueryHandler(show_stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(facts_menu, pattern="^facts_menu$"))
    application.add_handler(CallbackQueryHandler(read_facts, pattern="^read_facts$"))
    application.add_handler(CallbackQueryHandler(broadcast_confirm, pattern="^broadcast_confirm$"))
    application.add_handler(CallbackQueryHandler(broadcast_cancel, pattern="^broadcast_cancel$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(ban_from_list, pattern="^ban_from_list$"))
    application.add_handler(CallbackQueryHandler(confirm_ban, pattern="^confirm_ban_"))
    application.add_handler(CallbackQueryHandler(do_ban, pattern="^do_ban_"))
    application.add_handler(CallbackQueryHandler(admin_unban, pattern="^admin_unban$"))
    application.add_handler(CallbackQueryHandler(do_unban, pattern="^unban_"))
    application.add_handler(CallbackQueryHandler(admin_banned_list, pattern="^admin_banned_list$"))
    application.add_handler(CallbackQueryHandler(admin_add_start, pattern="^admin_add$"))
    application.add_handler(CallbackQueryHandler(show_gift_details, pattern="^gift_"))
    application.add_handler(CallbackQueryHandler(claim_gift, pattern="^claim_"))
    application.add_handler(CallbackQueryHandler(share_gift, pattern="^share_"))
    application.add_handler(CallbackQueryHandler(select_contribution, pattern="^contrib_"))
    application.add_handler(CallbackQueryHandler(unclaim_gift, pattern="^unclaim_"))
    application.add_handler(CallbackQueryHandler(mark_bought, pattern="^bought_"))
    application.add_handler(CallbackQueryHandler(mark_already_has, pattern="^already_has_"))
    application.add_handler(CallbackQueryHandler(delete_gift, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(start_edit_gift, pattern="^edit_\\d+$"))

    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
