import logging
import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# MongoDB setup
MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["your_database_name"]  # Change to your database name
authorized_users_collection = db["authorized_users"]
exempted_users_collection = db["exempted_users"]  # Collection for exempted users
user_interaction_collection = db["user_interactions"]  # Collection for user interactions
chat_collection = db["chat_ids"]  # Collection for chat IDs

# Replace with the bot owner's user ID and log group chat ID
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))
LOG_GROUP_CHAT_ID = int(os.getenv("LOG_GROUP_CHAT_ID"))  # New log group chat ID

# Default delay time for media and stickers (in seconds)
DEFAULT_MEDIA_DELAY = 30 * 60  # 30 minutes

# Store delay time per chat
chat_media_delay = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I will delete edited messages from non-authorized users and media/stickers after a set time.")

    # Log to the log group when a user starts a conversation in PM
    if update.message.chat.type == 'private':  # Check if it's a private message
        await context.bot.send_message(
            chat_id=LOG_GROUP_CHAT_ID,
            text=f"User {update.message.from_user.mention} started a conversation in PM.",
            parse_mode='HTML'
        )

    # Record user interaction
    user_interaction_collection.update_one({"user_id": update.message.from_user.id}, {"$set": {"user_id": update.message.from_user.id}}, upsert=True)
    # Record chat interaction
    chat_collection.update_one({"chat_id": update.message.chat.id}, {"$set": {"chat_id": update.message.chat.id}}, upsert=True)

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Log when the bot is added to a new chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:  # Check if the bot is the one being added
            await context.bot.send_message(
                chat_id=LOG_GROUP_CHAT_ID,
                text=f"The bot has been added to a new chat: {update.message.chat.title}.",
                parse_mode='HTML'
            )
            break

async def setdelay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Check if the user is an admin
    if user.id in [admin.user.id for admin in await chat.get_administrators()]:
        if context.args:
            try:
                delay = int(context.args[0])
                chat_media_delay[chat.id] = delay  # Set the delay for this chat
                await update.message.reply_text(f"Media and sticker deletion delay set to {delay} seconds for this chat.")
            except ValueError:
                await update.message.reply_text("Please provide a valid number.")
        else:
            await update.message.reply_text("Please provide the delay time in seconds.")
    else:
        await update.message.reply_text("Only admins can set the delay.")

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Check if the user is an admin
    if user.id in [admin.user.id for admin in await chat.get_administrators()]:
        if context.args:
            user_id = get_user_id(context, context.args[0])
            # Add user to authorized users in MongoDB
            authorized_users_collection.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
            await update.message.reply_text(f"User {user_id} has been authorized to edit messages.")
        elif update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            authorized_users_collection.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
            await update.message.reply_text(f"User {user_id} has been authorized to edit messages.")
        else:
            await update.message.reply_text("Please provide a user ID or reply to a user.")

async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Check if the user is an admin
    if user.id in [admin.user.id for admin in await chat.get_administrators()]:
        if context.args:
            user_id = get_user_id(context, context.args[0])
            # Remove user from authorized users in MongoDB
            result = authorized_users_collection.delete_one({"user_id": user_id})
            if result.deleted_count > 0:
                await update.message.reply_text(f"User {user_id} has been unauthorized.")
            else:
                await update.message.reply_text(f"User {user_id} is not authorized.")
        elif update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            result = authorized_users_collection.delete_one({"user_id": user_id})
            if result.deleted_count > 0:
                await update.message.reply_text(f"User {user_id} has been unauthorized.")
            else:
                await update.message.reply_text(f"User {user_id} is not authorized.")
        else:
            await update.message.reply_text("Please provide a user ID or reply to a user.")
    else:
        await update.message.reply_text("Only admins can unauthorize users.")

async def gauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Check if the user is the bot owner
    if user.id == BOT_OWNER_ID:
        if context.args:
            user_id = get_user_id(context, context.args[0])
            # Add user to exempted users in MongoDB
            exempted_users_collection.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
            await update.message.reply_text(f"User {user_id} has been exempted from editing restrictions.")
        elif update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            exempted_users_collection.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
            await update.message.reply_text(f"User {user_id} has been exempted from editing restrictions.")
        else:
            await update.message.reply_text("Please provide a user ID or reply to a user.")
    else:
        await update.message.reply_text("Only the bot owner can exempt users.")

async def gunauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Check if the user is the bot owner
    if user.id == BOT_OWNER_ID:
        if context.args:
            user_id = get_user_id(context, context.args[0])
            # Remove user from exempted users in MongoDB
            result = exempted_users_collection.delete_one({"user_id": user_id})
            if result.deleted_count > 0:
                await update.message.reply_text(f"User {user_id} has been unexempted from editing restrictions.")
            else:
                await update.message.reply_text(f"User {user_id} is not exempted.")
        elif update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            result = exempted_users_collection.delete_one({"user_id": user_id})
            if result.deleted_count > 0:
                await update.message.reply_text(f"User {user_id} has been unexempted from editing restrictions.")
            else:
                await update.message.reply_text(f"User {user_id} is not exempted.")
        else:
            await update.message.reply_text("Please provide a user ID or reply to a user.")
    else:
        await update.message.reply_text("Only the bot owner can unexempt users.")

async def authusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat = update.message.chat

    # Check if the user is an admin
    if user.id in [admin.user.id for admin in await chat.get_administrators()]:
        exempted_users = exempted_users_collection.find()
        if exempted_users.count() == 0:
            await update.message.reply_text("No exempted users in this chat.")
        else:
            response = "Exempted users:\n" + "\n".join([f"{i+1}- {u['user_id']}" for i, u in enumerate(exempted_users)])
            await update.message.reply_text(response)
    else:
        await update.message.reply_text("Only admins can view exempted users.")

async def gauthusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Check if the user is the bot owner
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

async def main():
    application = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))  # New handler for new chat members
    application.add_handler(CommandHandler("setdelay", setdelay))  # New command for setting media/sticker deletion delay
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("unauth", unauth))
    application.add_handler(CommandHandler("gauth", gauth))
    application.add_handler(CommandHandler("gunauth", gunauth))
    application.add_handler(CommandHandler("authusers", authusers))
    application.add_handler(CommandHandler("gauthusers", gauthusers))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, delete_edited_message))
    application.add_handler(MessageHandler(filters.Document | filters.Photo | filters.Sticker, delete_media))  # New handler for media/sticker deletion

    # Start the bot
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
