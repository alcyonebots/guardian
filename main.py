import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, CallbackQueryHandler, ChatMemberHandler, filters
from pymongo import MongoClient

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
mongo_uri = os.getenv("MONGODB_URI")
client = MongoClient(mongo_uri)
db = client['telegram_bot']  # replace with your database name
authorized_users_collection = db['authorized_users']
global_auth_users_collection = db['global_auth_users']
log_collection = db['log_collection']

# Owner ID and Bot Token
OWNER_ID = os.getenv("OWNER_ID")  # Owner ID should be set in the environment
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome to the bot!")

async def auth(update: Update, context: CallbackContext):
    if update.effective_chat.type in ["group", "supergroup"]:
        user_id = update.message.reply_to_message.from_user.id if update.message.reply_to_message else None
        if user_id:
            # Authorize the user in the current chat
            await authorized_users_collection.update_one(
                {"chat_id": update.effective_chat.id},
                {"$addToSet": {"authorized_users": user_id}},
                upsert=True
            )
            await update.message.reply_text(f"User {update.message.reply_to_message.from_user.mention_html()} authorized.", parse_mode='HTML')
        else:
            await update.message.reply_text("Please reply to a user's message to authorize them.")

async def unauth(update: Update, context: CallbackContext):
    if update.effective_chat.type in ["group", "supergroup"]:
        user_id = update.message.reply_to_message.from_user.id if update.message.reply_to_message else None
        if user_id:
            # Unauthorize the user in the current chat
            await authorized_users_collection.update_one(
                {"chat_id": update.effective_chat.id},
                {"$pull": {"authorized_users": user_id}}
            )
            await update.message.reply_text(f"User {update.message.reply_to_message.from_user.mention_html()} unauthorized.", parse_mode='HTML')
        else:
            await update.message.reply_text("Please reply to a user's message to unauthorize them.")

async def gauth(update: Update, context: CallbackContext):
    if update.message.from_user.id == int(OWNER_ID):
        user_id = context.args[0] if context.args else None
        if user_id:
            # Global authorization
            await global_auth_users_collection.update_one(
                {},
                {"$addToSet": {"global_auth_users": user_id}},
                upsert=True
            )
            await update.message.reply_text(f"User {user_id} globally authorized.")
        else:
            await update.message.reply_text("Please provide a user ID to globally authorize.")

async def gunauth(update: Update, context: CallbackContext):
    if update.message.from_user.id == int(OWNER_ID):
        user_id = context.args[0] if context.args else None
        if user_id:
            # Global unauthorization
            await global_auth_users_collection.update_one(
                {},
                {"$pull": {"global_auth_users": user_id}}
            )
            await update.message.reply_text(f"User {user_id} globally unauthorized.")
        else:
            await update.message.reply_text("Please provide a user ID to globally unauthorize.")

async def set_delay(update: Update, context: CallbackContext):
    if update.effective_chat.type in ["group", "supergroup"]:
        delay = int(context.args[0]) if context.args else 30  # Default to 30 minutes
        await update.message.reply_text(f"Media deletion delay set to {delay} minutes.")

async def stats(update: Update, context: CallbackContext):
    # Get bot stats
    chat_count = await authorized_users_collection.count_documents({})
    user_count = await global_auth_users_collection.count_documents({})
    await update.message.reply_text(f"Bot is in {chat_count} chats.\n{user_count} users have started the bot.")

async def broadcast(update: Update, context: CallbackContext):
    if update.message.from_user.id == int(OWNER_ID):
        message_to_broadcast = update.message.reply_to_message.text if update.message.reply_to_message else None
        if message_to_broadcast:
            # Send to all chats
            # You need to implement the logic for this based on how you store the chat IDs
            await update.message.reply_text("Broadcast message sent!")
        else:
            await update.message.reply_text("Please reply to a message to broadcast it.")

async def auth_users(update: Update, context: CallbackContext):
    if update.effective_chat.type in ["group", "supergroup"]:
        authorized_users = await authorized_users_collection.find_one({"chat_id": update.effective_chat.id})
        user_list = authorized_users.get("authorized_users", []) if authorized_users else []
        response = "\n".join([f"{i+1}- {user}" for i, user in enumerate(user_list)])
        await update.message.reply_text(response or "No authorized users found.")

async def gauth_users(update: Update, context: CallbackContext):
    global_auth_users = await global_auth_users_collection.find_one({})
    user_list = global_auth_users.get("global_auth_users", []) if global_auth_users else []
    response = "\n".join([f"{i+1}- {user}" for i, user in enumerate(user_list)])
    await update.message.reply_text(response or "No globally authorized users found.")

async def handle_media(update: Update, context: CallbackContext) -> None:
    # Process the media message here
    media_type = "unknown"
    if update.message.photo:
        media_type = "photo"
    elif update.message.video:
        media_type = "video"
    elif update.message.sticker:
        media_type = "sticker"

    # Delete media message after a specific delay
    # You need to implement the logic for deletion after a delay based on the set delay
    print(f"Received {media_type} from {update.message.from_user.username}")

async def edited_message(update: Update, context: CallbackContext) -> None:
    # Handle edited message here
    print(f"Edited message from {update.message.from_user.username}")

async def log_new_chat(update: Update, context: CallbackContext):
    # Log new chat details
    chat = update.message.chat
    log_message = f"Chat added:\nChat title: {chat.title}\nChat username: @{chat.username}\nChat ID: {chat.id}"
    await log_collection.insert_one({"log": log_message})

    # Optionally, you can log this to a specific log group chat
    logger.info(log_message)

async def help_command(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("Edited Messages", callback_data='edited_messages')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("How to use this bot:", reply_markup=reply_markup)

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == 'edited_messages':
        await query.edit_message_text(text="This bot deletes edited messages.")
        await query.message.reply_text("Press 'Back' to return to the help menu.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='back')]]))
    elif query.data == 'back':
        await help_command(query.message, context)

async def error(update: Update, context: CallbackContext):
    logger.warning(f'Update {update} caused error {context.error}')

def main() -> None:
    # Create the application
    application = ApplicationBuilder().token(bot_token).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("unauth", unauth))
    application.add_handler(CommandHandler("gauth", gauth))
    application.add_handler(CommandHandler("gunauth", gunauth))
    application.add_handler(CommandHandler("setdelay", set_delay))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("authusers", auth_users))
    application.add_handler(CommandHandler("gauthusers", gauth_users))
    application.add_handler(CommandHandler("help", help_command))

    # Updated message handlers with the correct filter syntax
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.STICKER, handle_media))
    application.add_handler(MessageHandler(filters.TEXT & filters.EDITED, edited_message))

    # Chat member handler to track when the bot is added to a new chat
    application.add_handler(ChatMemberHandler(log_new_chat, pattern='new_chat_members'))

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button))

    # Log all errors
    application.add_error_handler(error)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
