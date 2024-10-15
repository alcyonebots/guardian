import os
import asyncio
import logging
from pymongo import MongoClient
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client['telegram_bot']
authorized_users_collection = db['authorized_users']
exempted_users_collection = db['exempted_users']
user_interaction_collection = db['user_interactions']
chat_collection = db['chats']

# Constants
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))
LOG_GROUP_CHAT_ID = int(os.getenv("LOG_GROUP_CHAT_ID"))
DEFAULT_MEDIA_DELAY = 1800  # 30 minutes
chat_media_delay = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Start command received from user: %s", update.message.from_user.id)
    await update.message.reply_text("Hello! I'm your bot.")

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Bot added to new chat: %s", update.message.chat.title)
    await context.bot.send_message(
        chat_id=LOG_GROUP_CHAT_ID,
        text=f"Bot added to chat: {update.message.chat.title} (ID: {update.message.chat.id})"
    )

async def setdelay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if user.id in authorized_users_collection.find():
        delay = int(context.args[0]) if context.args else DEFAULT_MEDIA_DELAY
        chat_media_delay[update.message.chat.id] = delay
        await update.message.reply_text(f"Media/sticker deletion delay set to {delay} seconds.")
    else:
        await update.message.reply_text("You are not authorized to set delays.")

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    target_user_id = get_user_id(context, context.args[0]) if context.args else user.id
    logger.info("Auth command by user %s for user %s", user.id, target_user_id)

    if user.id in authorized_users_collection.find():
        authorized_users_collection.insert_one({"user_id": target_user_id})
        await update.message.reply_text(f"User {target_user_id} has been authorized.")
    else:
        await update.message.reply_text("You are not authorized to perform this action.")

async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    target_user_id = get_user_id(context, context.args[0]) if context.args else user.id
    logger.info("Unauth command by user %s for user %s", user.id, target_user_id)

    if user.id in authorized_users_collection.find():
        authorized_users_collection.delete_one({"user_id": target_user_id})
        await update.message.reply_text(f"User {target_user_id} has been unauthorised.")
    else:
        await update.message.reply_text("You are not authorized to perform this action.")

async def gauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    target_user_id = get_user_id(context, context.args[0]) if context.args else user.id
    logger.info("Gauth command by bot owner %s for user %s", user.id, target_user_id)

    if user.id == BOT_OWNER_ID:
        exempted_users_collection.insert_one({"user_id": target_user_id})
        await update.message.reply_text(f"User {target_user_id} has been globally authorized.")
    else:
        await update.message.reply_text("Only the bot owner can perform this action.")

async def gunauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    target_user_id = get_user_id(context, context.args[0]) if context.args else user.id
    logger.info("Gunauth command by bot owner %s for user %s", user.id, target_user_id)

    if user.id == BOT_OWNER_ID:
        exempted_users_collection.delete_one({"user_id": target_user_id})
        await update.message.reply_text(f"User {target_user_id} has been globally unauthorised.")
    else:
        await update.message.reply_text("Only the bot owner can perform this action.")

async def authusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info("Authusers command by user %s", user.id)

    if user.id in authorized_users_collection.find():
        exempted_users = authorized_users_collection.find({"chat_id": update.message.chat.id})
        if exempted_users.count() == 0:
            await update.message.reply_text("No exempted users in this chat.")
        else:
            response = "Exempted users:\n" + "\n".join([f"{i+1}- {u['user_id']}" for i, u in enumerate(exempted_users)])
            await update.message.reply_text(response)
    else:
        await update.message.reply_text("You are not authorized to view exempted users.")

async def gauthusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info("Gauthusers command by bot owner %s", user.id)

    if user.id == BOT_OWNER_ID:
        exempted_users = exempted_users_collection.find()
        if exempted_users.count() == 0:
            await update.message.reply_text("No globally exempted users.")
        else:
            response = "Globally exempted users:\n" + "\n".join([f"{i+1}- {u['user_id']}" for i, u in enumerate(exempted_users)])
            await update.message.reply_text(response)
    else:
        await update.message.reply_text("Only the bot owner can view globally exempted users.")

async def delete_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Check if the user is exempted
    if exempted_users_collection.find_one({"user_id": user.id}):
        return  # Do nothing, the user is exempted

    # Check if the user is authorized
    if authorized_users_collection.find_one({"user_id": user.id}):
        return  # Do nothing, the user is authorized

    # Immediately delete the edited message
    await update.message.delete()

    # Send a notification to the group chat
    await context.bot.send_message(
        chat_id=chat.id,
        text=f"{user.mention} just edited a message, and I deleted it.",
        parse_mode='HTML'  # Use HTML mode to allow user mentions
    )

async def delete_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Get the delay time for this chat or use the default
    delay = chat_media_delay.get(chat.id, DEFAULT_MEDIA_DELAY)

    # Delete media and stickers after the specified delay
    await asyncio.sleep(delay)
    if update.message.document or update.message.photo or update.message.sticker:
        await update.message.delete()
        # Removed notification message for media/sticker deletion

def get_user_id(context, identifier):
    """Helper function to get user ID from username or ID."""
    if identifier.startswith('@'):
        username = identifier[1:]
        user = context.bot.get_chat(username)
        return user.id
    else:
        return int(identifier)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Check if the user is the bot owner
    if user.id == BOT_OWNER_ID:
        user_count = user_interaction_collection.count_documents({})
        chat_count = chat_collection.count_documents({})
        await update.message.reply_text(f"User Interactions: {user_count}\nChats: {chat_count}")
    else:
        await update.message.reply_text("Only the bot owner can view stats.")

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

async def main():
    application = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    application.add_handler(CommandHandler("setdelay", setdelay))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("unauth", unauth))
    application.add_handler(CommandHandler("gauth", gauth))
    application.add_handler(CommandHandler("gunauth", gunauth))
    application.add_handler(CommandHandler("authusers", authusers))
    application.add_handler(CommandHandler("gauthusers", gauthusers))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, delete_edited_message))

    # Corrected handler for media/sticker deletion
    application.add_handler(MessageHandler(filters.Document | filters.PHOTO | filters.Sticker, delete_media))

    try:
        # Start the bot
        await application.run_polling()
    except Exception as e:
        logger.error(f"Error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
