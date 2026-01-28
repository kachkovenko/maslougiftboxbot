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
    "available": "🟢",
    "claimed": "🟡",
    "bought": "✅",
    "already_has": "🚫"
}


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
            text += f"\n{cat_name}\n"
            for gift in by_category[cat_key]:
                status = STATUS_EMOJI.get(gift['status'], "🟢")
                price_str = f"{gift['price']}₽" if gift['price'] else "цена?"
                buyers = db.get_gift_buyers(gift['id'])
                
                buyer_info = ""
                if buyers:
                    names = [escape_md(b['user_name'].split()[0]) for b in buyers]
                    buyer_info = f" — {', '.join(names)}"
                
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
    status = STATUS_EMOJI.get(gift['status'], "🟢")
    status_text = {
        "available": "Свободен",
        "claimed": "Кто-то покупает",
        "bought": "Уже куплен",
        "already_has": "Уже есть у именинника"
    }.get(gift['status'], "Свободен")
    
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
    
    buyers = db.get_gift_buyers(gift_id)
    if buyers:
        text += "\n👥 *Участники:*\n"
        for buyer in buyers:
            buyer_name = escape_md(buyer['user_name'])
            amount = f" — {buyer['amount']}₽" if buyer['amount'] else ""
            text += f"  • {buyer_name}{escape_md(amount)}\n"
    
    keyboard = []
    
    if gift['status'] == "available":
        keyboard.append([InlineKeyboardButton("🙋 Я куплю это!", callback_data=f"claim_{gift_id}")])
        keyboard.append([InlineKeyboardButton("👥 Скинемся вместе", callback_data=f"share_{gift_id}")])
    elif gift['status'] == "claimed":
        # Check if current user is a buyer
        user_is_buyer = any(b['user_id'] == user.id for b in buyers)
        if user_is_buyer:
            keyboard.append([InlineKeyboardButton("✅ Уже купил!", callback_data=f"bought_{gift_id}")])
            keyboard.append([InlineKeyboardButton("❌ Отказаться", callback_data=f"unclaim_{gift_id}")])
        else:
            keyboard.append([InlineKeyboardButton("👥 Присоединиться", callback_data=f"share_{gift_id}")])
    
    if gift['status'] not in ["already_has", "bought"]:
        keyboard.append([InlineKeyboardButton("🚫 Уже есть у именинника", callback_data=f"already_has_{gift_id}")])
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🗑 Удалить (админ)", callback_data=f"delete_{gift_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 К списку", callback_data="list_gifts")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )


async def claim_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Claim a gift for yourself"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    
    db.add_buyer(gift_id, user.id, user.full_name)
    db.update_gift_status(gift_id, "claimed")
    
    await query.answer("✅ Отлично! Вы записались на этот подарок!", show_alert=True)
    
    # Refresh gift details
    context.user_data['viewing_gift'] = gift_id
    query.data = f"gift_{gift_id}"
    await show_gift_details(update, context)


async def share_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Join shared purchase"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    
    # Check if already participating
    buyers = db.get_gift_buyers(gift_id)
    if any(b['user_id'] == user.id for b in buyers):
        await query.answer("Вы уже участвуете в покупке этого подарка!", show_alert=True)
        return
    
    db.add_buyer(gift_id, user.id, user.full_name)
    db.update_gift_status(gift_id, "claimed")
    
    context.user_data['contribution_gift_id'] = gift_id
    
    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data=f"skip_contribution_{gift_id}")]
    ]
    
    await query.edit_message_text(
        "💰 Сколько вы готовы вложить? (в рублях)\n\n"
        "Напишите сумму или нажмите 'Пропустить'",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SETTING_CONTRIBUTION


async def set_contribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set contribution amount"""
    user = update.effective_user
    gift_id = context.user_data.get('contribution_gift_id')
    
    if not gift_id:
        await update.message.reply_text("❌ Ошибка. Попробуйте заново.")
        return ConversationHandler.END
    
    try:
        amount = int(update.message.text.replace(" ", "").replace("₽", ""))
        db.update_buyer_amount(gift_id, user.id, amount)
        await update.message.reply_text(f"✅ Записано: {amount}₽")
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите число")
        return SETTING_CONTRIBUTION
    
    await show_main_menu(update, context)
    return ConversationHandler.END


async def skip_contribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip setting contribution amount"""
    query = update.callback_query
    await query.answer("✅ Вы добавлены к покупке!")
    await show_main_menu(update, context)
    return ConversationHandler.END


async def unclaim_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove yourself from gift"""
    query = update.callback_query
    await query.answer()
    
    gift_id = int(query.data.split("_")[1])
    user = update.effective_user
    
    db.remove_buyer(gift_id, user.id)
    
    # Check if any buyers left
    buyers = db.get_gift_buyers(gift_id)
    if not buyers:
        db.update_gift_status(gift_id, "available")
    
    await query.answer("Вы отказались от покупки", show_alert=True)
    
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
    
    # Conversation handler for contribution
    contribution_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(share_gift, pattern="^share_")],
        states={
            SETTING_CONTRIBUTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_contribution),
                CallbackQueryHandler(skip_contribution, pattern="^skip_contribution_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
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
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CommandHandler("export", export_db))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.COMMAND, import_db))
    application.add_handler(CommandHandler("import", import_db))
    application.add_handler(add_gift_handler)
    application.add_handler(contribution_handler)
    application.add_handler(ban_handler)
    application.add_handler(facts_handler)
    application.add_handler(broadcast_handler)
    
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
    application.add_handler(CallbackQueryHandler(unclaim_gift, pattern="^unclaim_"))
    application.add_handler(CallbackQueryHandler(mark_bought, pattern="^bought_"))
    application.add_handler(CallbackQueryHandler(mark_already_has, pattern="^already_has_"))
    application.add_handler(CallbackQueryHandler(delete_gift, pattern="^delete_"))
    
    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
