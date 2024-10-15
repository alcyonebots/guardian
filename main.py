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

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! I'm a bot that manages message edits in this group.")

# Command to authorize users
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id in await get_admin_ids(update):
        user_id = context.args[0] if context.args else update.reply_to_message.from_user.id
        authorized_users_collection.update_one({"user_id": user_id}, {"$set": {"authorized": True}}, upsert=True)
        await update.message.reply_text(f"User {user_id} has been authorized to edit messages.")
    else:
        await update.message.reply_text("You are not authorized to use this command.")

# Command to unauthorize users
async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id in await get_admin_ids(update):
        user_id = context.args[0] if context.args else update.reply_to_message.from_user.id
        authorized_users_collection.update_one({"user_id": user_id}, {"$set": {"authorized": False}})
        await update.message.reply_text(f"User {user_id} has been unauthorized.")
    else:
        await update.message.reply_text("You are not authorized to use this command.")

# Command to globally authorize users
async def gauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == BOT_OWNER_ID:
        user_id = context.args[0] if context.args else update.reply_to_message.from_user.id
        exempted_users_collection.update_one({"user_id": user_id}, {"$set": {"exempted": True}}, upsert=True)
        await update.message.reply_text(f"User {user_id} has been globally authorized.")
    else:
        await update.message.reply_text("You are not the bot owner.")

# Command to globally unauthorize users
async def gunauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == BOT_OWNER_ID:
        user_id = context.args[0] if context.args else update.reply_to_message.from_user.id
        exempted_users_collection.update_one({"user_id": user_id}, {"$set": {"exempted": False}})
        await update.message.reply_text(f"User {user_id} has been globally unauthorized.")
    else:
        await update.message.reply_text("You are not the bot owner.")

# Command to list authorized users
async def authusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id in await get_admin_ids(update):
        authorized_users = authorized_users_collection.find({"authorized": True})
        response = "Authorized users:\n" + "\n".join(f"{i + 1}- {user['user_id']}" for i, user in enumerate(authorized_users))
        await update.message.reply_text(response if authorized_users else "No authorized users.")
    else:
        await update.message.reply_text("You are not authorized to use this command.")

# Command to list globally exempted users
async def gauthusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == BOT_OWNER_ID:
        exempted_users = exempted_users_collection.find({"exempted": True})
        response = "Globally exempted users:\n" + "\n".join(f"{i + 1}- {user['user_id']}" for i, user in enumerate(exempted_users))
        await update.message.reply_text(response if exempted_users else "No globally exempted users.")
    else:
        await update.message.reply_text("You are not the bot owner.")

# Command to display statistics
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == BOT_OWNER_ID:
        user_count = user_interaction_collection.count_documents({})
        chat_count = chat_collection.count_documents({})
        await update.message.reply_text(f"Total users interacted with: {user_count}\nTotal chats: {chat_count}")
    else:
        await update.message.reply_text("You are not the bot owner.")

# Handle edited messages
async def delete_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in await get_authorized_users(update.effective_chat.id):
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"{update.message.from_user.mention_markdown_v2()} just edited a message and I deleted it.", parse_mode='MarkdownV2')
