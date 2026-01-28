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
from database import Database

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
ADDING_GIFT_NAME, ADDING_GIFT_PRICE, ADDING_GIFT_CATEGORY = range(3)
SETTING_CONTRIBUTION = 3
BANNING_USER = 4

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
    return db.is_admin(user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    user = update.effective_user
    
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


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📋 Список подарков", callback_data="list_gifts")],
        [InlineKeyboardButton("➕ Добавить идею", callback_data="add_gift")],
        [InlineKeyboardButton("🎁 Мои подарки", callback_data="my_gifts")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🎁 *Бот для сбора подарков* 🎁\n\n"
        "Здесь мы собираем идеи подарков и координируем покупки!\n\n"
        "📋 — посмотреть все идеи\n"
        "➕ — предложить свою идею\n"
        "🎁 — посмотреть что вы покупаете\n"
        "📊 — общая статистика\n"
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
                    names = [b['user_name'].split()[0] for b in buyers]
                    buyer_info = f" — {', '.join(names)}"
                
                text += f"{status} {gift['name']} (~{price_str}){buyer_info}\n"
                keyboard.append([InlineKeyboardButton(
                    f"{status} {gift['name'][:30]}",
                    callback_data=f"gift_{gift['id']}"
                )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    # Trim text if too long
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (список сокращён)"
    
    await query.edit_message_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
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
    
    text = (
        f"🎁 *{gift['name']}*\n\n"
        f"💰 Цена: ~{price_str}\n"
        f"📁 Категория: {category}\n"
        f"📊 Статус: {status} {status_text}\n"
        f"💡 Добавил: {gift['added_by_name']}\n"
    )
    
    buyers = db.get_gift_buyers(gift_id)
    if buyers:
        text += "\n👥 *Участники:*\n"
        for buyer in buyers:
            amount = f" — {buyer['amount']}₽" if buyer['amount'] else ""
            text += f"  • {buyer['user_name']}{amount}\n"
    
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
        parse_mode="Markdown"
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
    
    await query.edit_message_text(
        f"🎉 *Идея добавлена!*\n\n"
        f"🎁 {context.user_data['new_gift_name']}\n"
        f"💰 {context.user_data.get('new_gift_price', 'не указана')}₽\n"
        f"📁 {CATEGORIES[category]}",
        parse_mode="Markdown"
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
        amount = f" (ваш вклад: {gift['amount']}₽)" if gift.get('amount') else ""
        
        text += f"{status} {gift['name']} (~{price_str}){amount}\n"
        keyboard.append([InlineKeyboardButton(
            f"{status} {gift['name'][:30]}",
            callback_data=f"gift_{gift['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
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
        "Здесь вы можете управлять ботом:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def admin_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start banning process"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_panel")]]
    
    await query.edit_message_text(
        "🚫 *Забанить именинника*\n\n"
        "Перешлите сюда любое сообщение от именинника,\n"
        "или отправьте его @username или ID.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BANNING_USER


async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user"""
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END
    
    target_id = None
    target_name = "Пользователь"
    
    # Check if forwarded message
    if update.message.forward_from:
        target_id = update.message.forward_from.id
        target_name = update.message.forward_from.full_name
    elif update.message.text:
        text = update.message.text.strip()
        # Try to parse as ID
        try:
            target_id = int(text)
        except ValueError:
            # Try to parse as username (won't work without user interaction)
            await update.message.reply_text(
                "❌ Не удалось определить пользователя.\n"
                "Лучше перешлите его сообщение."
            )
            return BANNING_USER
    
    if target_id:
        db.ban_user(target_id, target_name)
        await update.message.reply_text(
            f"✅ Пользователь {target_name} (ID: {target_id}) забанен!\n"
            "Теперь он не сможет пользоваться ботом."
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
    
    # Conversation handler for banning
    ban_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$")],
        states={
            BANNING_USER: [
                MessageHandler(filters.ALL & ~filters.COMMAND, admin_ban_user),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
        ],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(add_gift_handler)
    application.add_handler(contribution_handler)
    application.add_handler(ban_handler)
    
    # Callback query handlers
    application.add_handler(CallbackQueryHandler(handle_main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(list_gifts, pattern="^list_gifts$"))
    application.add_handler(CallbackQueryHandler(my_gifts, pattern="^my_gifts$"))
    application.add_handler(CallbackQueryHandler(show_stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
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
