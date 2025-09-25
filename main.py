import logging
import os
from threading import Thread
from flask import Flask # Flask import kiya gaya
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)

# --- Configuration ---
BOT_TOKEN = "8208262041:AAFhsFUYKZzTJb3HSla163ud_94ljg1V8eU"
REVIEW_CHANNEL_ID = -1002977955893

# GROUP_INFO keys updated to match the screenshot buttons
GROUP_INFO = {
    "CHAT GC": -1002459622912,
    "Buy & Sell": -1002733226688,
}
# Reverse mapping for easy lookup
GROUP_ID_TO_NAME = {v: k for k, v in GROUP_INFO.items()}

# Conversation States
SELECT_GROUP, SUBMIT_REASON = range(2)

# Dictionary to track pending appeals: {user_id: [group_id, ...]}
PENDING_APPEALS = {}

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Flask Server Logic for Replit Keep-Alive ---
app = Flask(__name__) # Flask app instance

@app.route('/')
def home():
    """Simple route for UptimeRobot check."""
    return "Bot is running"

def run_flask_server():
    """Runs the Flask server in the background, using Replit's environment PORT."""
    # Replit's PORT environment variable ko use kiya gaya
    port = int(os.environ.get('PORT', 8080)) 
    # Server ko 0.0.0.0 par run kiya gaya
    app.run(host="0.0.0.0", port=port)

def start_keep_alive():
    """Starts the Flask server thread."""
    t = Thread(target=run_flask_server)
    t.start()
    
    print("\n" + "="*50)
    print("🤖 TELEGRAM BOT IS RUNNING")
    print("💡 Replit server started. Use the public URL in UptimeRobot.")
    print("="*50 + "\n")
# --- End of Flask Logic ---

# --- Helper Functions (Same as before) ---
async def is_muted_or_banned(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = member.status
        if status == "kicked": return True, "banned"
        if status == "restricted" and not member.can_send_messages: return True, "muted"
        return False, status
    except Exception as e:
        logger.error(f"Error checking chat member status in group {chat_id} for user {user_id}. Bot must be an admin in this group. Error: {e}")
        return False, "CHECK_FAILED"

async def get_group_invite_link(bot, chat_id):
    try:
        chat = await bot.get_chat(chat_id)
        return chat.invite_link if chat.invite_link else None
    except Exception as e:
        logger.error(f"Could not get invite link for group {chat_id}. Error: {e}")
        return None

# --- Handlers (Same as before) ---
async def start(update: Update, context):
    if update.message.chat.type in ['group', 'supergroup']:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception as e: logger.warning(f"Failed to delete message in group. Error: {e}")
        return ConversationHandler.END

    keyboard_row = list(GROUP_INFO.keys())
    reply_markup = ReplyKeyboardMarkup([keyboard_row], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Welcome! Choose a group to start your appeal.", reply_markup=reply_markup)
    return SELECT_GROUP

async def group_selection(update: Update, context):
    group_name = update.message.text
    user_id = update.effective_user.id
    if group_name not in GROUP_INFO:
        await update.message.reply_text("Invalid group selection. Please use the provided buttons or restart with /start.")
        return SELECT_GROUP
    
    group_id = GROUP_INFO[group_name]
    context.user_data['selected_group_id'] = group_id
    context.user_data['selected_group_name'] = group_name

    if user_id in PENDING_APPEALS and group_id in PENDING_APPEALS[user_id]:
        await update.message.reply_text(f"You've already submitted an appeal for **{group_name}**. Our admins will review it soon.", parse_mode='Markdown')
        return ConversationHandler.END

    is_restricted, status = await is_muted_or_banned(context.bot, group_id, user_id)
    context.user_data['user_current_status'] = status

    if is_restricted and status in ['muted', 'banned']:
        restriction_type = "unmute" if status == 'muted' else "unban"
        await update.message.reply_text(f"Please provide a reason for your **{restriction_type}** request in a simple message.")
        return SUBMIT_REASON
    else:
        if status == "CHECK_FAILED":
             await update.message.reply_text("❌ **Status Check Failed!** सुनिश्चित करें कि बॉट ग्रुप में **Administrator** है। `/start` से फिर कोशिश करें।")
        else:
            await update.message.reply_text("You are not muted or banned.")
        return ConversationHandler.END

async def submit_reason(update: Update, context):
    user = update.effective_user
    user_id = user.id
    group_id = context.user_data['selected_group_id']
    group_name = context.user_data['selected_group_name']
    reason = update.message.text
    status = context.user_data.get('user_current_status', 'unknown')

    if user_id not in PENDING_APPEALS: PENDING_APPEALS[user_id] = []
    PENDING_APPEALS[user_id].append(group_id)

    await update.message.reply_text("Your appeal has been submitted. You'll be notified once a moderator reviews it.")

    username = f"@{user.username}" if user.username else "No Username"
    appeal_message = (f"**New Appeal from:** {username}\n**User ID:** `{user_id}`\n**Group:** `{group_name}`\n**Original Status:** `{status.upper()}`\n\n**Reason:**\n{reason}")
    keyboard = [[InlineKeyboardButton("✅ UNMUTE / UNBAN", callback_data=f"unmute_{user_id}_{group_id}_{status}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{group_id}_{status}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id=REVIEW_CHANNEL_ID, text=appeal_message, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END 

async def cancel_appeal(update: Update, context):
    await update.message.reply_text("Only text messages are accepted for the appeal reason, not stickers or GIFs. Please send your reason as a simple message.")
    return SUBMIT_REASON 

async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer() 
    data = query.data
    parts = data.split('_')
    action = parts[0]
    user_id = int(parts[1])
    group_id = int(parts[2])
    original_status = parts[3] 

    if user_id in PENDING_APPEALS and group_id in PENDING_APPEALS[user_id]:
        PENDING_APPEALS[user_id].remove(group_id)
        if not PENDING_APPEALS[user_id]: del PENDING_APPEALS[user_id]

    try:
        user_info = await context.bot.get_chat(user_id)
        mention = user_info.mention_html()
    except Exception:
        mention = f"User ID: `{user_id}`"

    group_name = GROUP_ID_TO_NAME.get(group_id, f"Group ID: `{group_id}`")
    username_id_text = f"@{user_info.username} [ {user_id} ]" if user_info.username else f"[ {user_id} ]"

    if action == "unmute":
        action_type = "unmuted" if original_status == 'muted' else "unbanned"
        try:
            if original_status == 'muted':
                await context.bot.restrict_chat_member(chat_id=group_id, user_id=user_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True, can_invite_users=True))
            elif original_status == 'banned':
                await context.bot.unban_chat_member(chat_id=group_id, user_id=user_id)

            await query.edit_message_text(f"{query.message.text}\n\n**---\n✅ APPEAL ACCEPTED ({action_type.upper()})** by {query.from_user.mention_html()}", parse_mode='HTML')
            
            invite_link = await get_group_invite_link(context.bot, group_id)
            user_notification_text = f"Appeal approved. You have been {action_type} in {group_name}."
            if invite_link:
                join_back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Join Back", url=invite_link)]])
                await context.bot.send_message(chat_id=user_id, text=user_notification_text, reply_markup=join_back_keyboard, parse_mode='Markdown')
            else:
                 await context.bot.send_message(chat_id=user_id, text=user_notification_text + "\n\n*(Note: Could not fetch 'Join Back' link)*", parse_mode='Markdown')

            await context.bot.send_message(chat_id=group_id, text=f"{mention} {username_id_text} user {action_type}", parse_mode='HTML')

        except Exception as e:
            error_message = f"❌ FAILED to {action_type.capitalize()} User `{user_id}` in `{group_id}`. Error: {e}"
            logger.error(error_message)
            await query.edit_message_text(f"{query.message.text}\n\n**---\n❌ ACTION FAILED**\n{error_message}", parse_mode='Markdown')

    elif action == "reject":
        await query.edit_message_text(f"{query.message.text}\n\n**---\n❌ APPEAL REJECTED** by {query.from_user.mention_html()}", parse_mode='HTML')
        appeal_link_button = InlineKeyboardMarkup([[InlineKeyboardButton("Appeal", url=f"https://t.me/{context.bot.username}?start")]])
        rejection_text = f"❌ Your appeal for **{group_name}** has been rejected. This guy cannot be unmuted, he has committed a lot of violations, please appeal again."

        await context.bot.send_message(chat_id=user_id, text=rejection_text, reply_markup=appeal_link_button, parse_mode='Markdown')
        group_notification = f"{mention} {username_id_text} This guy cannot be unmuted, he has committed a lot of violations, please appeal again."
        await context.bot.send_message(chat_id=group_id, text=group_notification, reply_markup=appeal_link_button, parse_mode='HTML')

# --- Main Setup ---

def main():
    """Starts the bot and the Flask server."""
    
    # 1. Start the Flask Keep-Alive server in a separate thread
    start_keep_alive() # <<< Yeh zaroori hai!
    
    # 2. Start the Telegram Bot Application
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_GROUP: [MessageHandler(filters.TEXT & (~filters.COMMAND), group_selection)],
            SUBMIT_REASON: [MessageHandler(filters.TEXT & (~filters.COMMAND), submit_reason), MessageHandler(~filters.TEXT, cancel_appeal)]
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot polling is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
