import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, Chat
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, CallbackQueryHandler, ChatMemberHandler, filters
from pymongo import MongoClient
from telegram.error import TelegramError
from datetime import timedelta

# Load environment variables from .env file
load_dotenv()

# Enable logging to file
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Set up logging
logger = logging.getLogger(__name__)

# MongoDB setup
MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client['telegram_bot']
authorized_users_col = db['authorized_users']
globally_authorized_users_col = db['globally_authorized_users']
chats_col = db['chats']  # Collection for storing chat IDs
users_col = db['users']  # Collection for storing user IDs
media_deletion_times_col = db['media_deletion_times']  # Collection for storing custom deletion times

OWNER_ID = int(os.getenv("OWNER_ID"))  # Owner's Telegram user ID
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))  # Log group chat ID
DEFAULT_DELETION_TIME = 30  # Default media deletion time in minutes

# Function to log messages to the log group
def log_to_group(message: str):
    try:
        updater.bot.send_message(chat_id=LOG_GROUP_ID, text=message)
    except Exception as e:
        logger.error(f"Failed to send log message: {e}")

# Function to extract user ID from a command
def extract_user_id(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id

    if context.args:
        identifier = context.args[0]
        if identifier.isdigit():
            return int(identifier)
        elif identifier.startswith('@'):
            user = context.bot.get_chat(identifier)
            return user.id
    return None

# Track the chat and user whenever a message is received
def track_chat_and_user(update: Update):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    # Track unique chats
    if not chats_col.find_one({'chat_id': chat_id}):
        chats_col.insert_one({'chat_id': chat_id})

    # Track unique users
    if not users_col.find_one({'user_id': user_id}):
        users_col.insert_one({'user_id': user_id})

# Check if the user is an admin
def is_user_admin(chat_id, user_id, context):
    chat_member = context.bot.get_chat_member(chat_id, user_id)
    return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.CREATOR]

# Check if a user is authorized in the group
def is_user_authorized(chat_id, user_id):
    result = authorized_users_col.find_one({'chat_id': chat_id, 'user_id': user_id})
    return result is not None

# Add a user to the group-level authorization list
def authorize_user(chat_id, user_id):
    authorized_users_col.update_one(
        {'chat_id': chat_id, 'user_id': user_id},
        {'$set': {'chat_id': chat_id, 'user_id': user_id}},
        upsert=True
    )

# Remove a user from the group-level authorization list
def unauthorize_user(chat_id, user_id):
    authorized_users_col.delete_one({'chat_id': chat_id, 'user_id': user_id})

# Check if a user is globally authorized
def is_globally_authorized(user_id):
    result = globally_authorized_users_col.find_one({'user_id': user_id})
    return result is not None

# Globally authorize a user
def globally_authorize_user(user_id):
    globally_authorized_users_col.update_one(
        {'user_id': user_id},
        {'$set': {'user_id': user_id}},
        upsert=True
    )

# Globally unauthorize a user
def globally_unauthorize_user(user_id):
    globally_authorized_users_col.delete_one({'user_id': user_id})

# Handle edited messages and apply restrictions
def edited_message(update: Update, context: CallbackContext) -> None:
    if update.edited_message:
        chat_id = update.edited_message.chat_id
        user_id = update.edited_message.from_user.id
        user_mention = f"@{update.edited_message.from_user.username}" if update.edited_message.from_user.username else update.edited_message.from_user.first_name

        if user_id == OWNER_ID or is_globally_authorized(user_id):
            return

        if not is_user_authorized(chat_id, user_id) and not is_user_admin(chat_id, user_id, context):
            context.bot.delete_message(chat_id, update.edited_message.message_id)
            context.bot.send_message(chat_id, f"{user_mention} just edited a message and I deleted it.")

# Function to schedule media deletion
def schedule_media_deletion(context: CallbackContext, chat_id: int, message_id: int, deletion_time: int) -> None:
    context.job_queue.run_once(delete_media_job, timedelta(minutes=deletion_time), context=(chat_id, message_id))

# Job to delete the media
def delete_media_job(context: CallbackContext) -> None:
    job_context = context.job.context
    chat_id, message_id = job_context
    try:
        context.bot.delete_message(chat_id, message_id)
        # Removed logging message for media deletion
    except TelegramError as e:
        logger.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

# Start command handler
def start(update: Update, context: CallbackContext) -> None:
    track_chat_and_user(update)  # Track the chat and user
    update.message.reply_text('Hello! Use /auth, /unauth, /gauth, /gunauth to manage editing and media deletion privileges.')
    log_to_group(f"Started bot interaction with user {update.message.from_user.id} in chat {update.message.chat_id}.")

# Handle media messages (photos, videos, stickers) and schedule deletion for non-admins
def handle_media(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    message_id = update.message.message_id

    # Check if the user is authorized or admin
    if user_id == OWNER_ID or is_globally_authorized(user_id) or is_user_authorized(chat_id, user_id) or is_user_admin(chat_id, user_id, context):
        return

    # Get the deletion time set for this chat, if any, otherwise use the default
    deletion_time_data = media_deletion_times_col.find_one({'chat_id': chat_id})
    if deletion_time_data:
        deletion_time = deletion_time_data.get('deletion_time', DEFAULT_DELETION_TIME)
    else:
        deletion_time = DEFAULT_DELETION_TIME

    # Schedule the media for deletion
    schedule_media_deletion(context, chat_id, message_id, deletion_time)

# Group-level authorization handler (/auth)
def auth(update: Update, context: CallbackContext) -> None:
    user_id = extract_user_id(update, context)

    if is_user_admin(update.message.chat_id, update.message.from_user.id, context):
        if user_id:
            authorize_user(update.message.chat_id, user_id)
            update.message.reply_text(f'User {user_id} has been authorized to edit messages and exempted from media deletion in this chat.')
        else:
            update.message.reply_text('Please provide a valid user ID or username, or reply to a user.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Group-level unauthorization handler (/unauth)
def unauth(update: Update, context: CallbackContext) -> None:
    user_id = extract_user_id(update, context)

    if is_user_admin(update.message.chat_id, update.message.from_user.id, context):
        if user_id:
            unauthorize_user(update.message.chat_id, user_id)
            update.message.reply_text(f'User {user_id} has been unauthorized in this chat.')
        else:
            update.message.reply_text('Please provide a valid user ID or username, or reply to a user.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Global authorization handler (/gauth)
def gauth(update: Update, context: CallbackContext) -> None:
    user_id = extract_user_id(update, context)

    if update.message.from_user.id == OWNER_ID:
        if user_id:
            globally_authorize_user(user_id)
            update.message.reply_text(f'User {user_id} has been globally authorized to edit messages and exempted from media deletion in any chat.')
        else:
            update.message.reply_text('Please provide a valid user ID or username, or reply to a user.')
    else:
        update.message.reply_text('You are not authorized to use this command. Only the owner can use /gauth.')

# Global unauthorization handler (/gunauth)
def gunauth(update: Update, context: CallbackContext) -> None:
    user_id = extract_user_id(update, context)

    if update.message.from_user.id == OWNER_ID:
        if user_id:
            globally_unauthorize_user(user_id)
            update.message.reply_text(f'User {user_id} has been globally unauthorized.')
        else:
            update.message.reply_text('Please provide a valid user ID or username, or reply to a user.')
    else:
        update.message.reply_text('You are not authorized to use this command. Only the owner can use /gunauth.')

# Set media deletion time (/setdelay)
def set_delay(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    if is_user_admin(chat_id, update.message.from_user.id, context):
        if context.args:
            try:
                deletion_time = int(context.args[0])
                media_deletion_times_col.update_one(
                    {'chat_id': chat_id},
                    {'$set': {'deletion_time': deletion_time}},
                    upsert=True
                )
                update.message.reply_text(f'Media deletion time set to {deletion_time} minutes.')
            except ValueError:
                update.message.reply_text('Please specify a valid number for the media deletion time in minutes.')
        else:
            update.message.reply_text('Please specify the media deletion time in minutes.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Command to show authorized users in the group (/authusers)
def auth_users(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    if is_user_admin(chat_id, update.message.from_user.id, context):
        authorized_users = authorized_users_col.find({'chat_id': chat_id})
        if authorized_users:
            user_mentions = [f"{i + 1}- @{context.bot.get_chat(user['user_id']).username}" for i, user in enumerate(authorized_users)]
            update.message.reply_text('\n'.join(user_mentions))
        else:
            update.message.reply_text('No authorized users in this chat.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Command to show globally authorized users (/gauthusers)
def gauth_users(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id == OWNER_ID:
        globally_authorized_users = globally_authorized_users_col.find()
        if globally_authorized_users:
            user_mentions = [f"{i + 1}- @{context.bot.get_chat(user['user_id']).username}" for i, user in enumerate(globally_authorized_users)]
            update.message.reply_text('\n'.join(user_mentions))
        else:
            update.message.reply_text('No globally authorized users.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Stats command to show bot activity (/stats)
def stats(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id == OWNER_ID:
        chat_count = chats_col.count_documents({})
        user_count = users_col.count_documents({})
        update.message.reply_text(f'The bot is in {chat_count} chats and has been started by {user_count} users.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Broadcast command to send a message to all users and chats (/broadcast)
def broadcast(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id == OWNER_ID:
        if update.message.reply_to_message:
            message_to_forward = update.message.reply_to_message
            for chat in chats_col.find():
                try:
                    context.bot.forward_message(chat_id=chat['chat_id'], from_chat_id=message_to_forward.chat_id, message_id=message_to_forward.message_id)
                except TelegramError as e:
                    logger.warning(f'Failed to send message to chat {chat["chat_id"]}: {e}')

            for user in users_col.find():
                try:
                    context.bot.forward_message(chat_id=user['user_id'], from_chat_id=message_to_forward.chat_id, message_id=message_to_forward.message_id)
                except TelegramError as e:
                    logger.warning(f'Failed to send message to user {user["user_id"]}: {e}')

        else:
            update.message.reply_text('Please reply to a message that you want to broadcast.')
    else:
        update.message.reply_text('You are not authorized to use this command.')

# Features command to describe the bot's functionalities (/features)
def features(update: Update, context: CallbackContext) -> None:
    feature_list = (
        "Here are the features of this bot:\n"
        "1. **Message Editing Control**: Prevents non-admin users from editing messages in the group.\n"
        "2. **Media Deletion Control**: Automatically deletes media messages (photos, videos, stickers) sent by non-admin users after a specified time.\n"
        "3. **User Authorization**: Admins can authorize specific users to edit messages and prevent their media from being deleted.\n"
        "4. **Global Authorization**: The bot owner can authorize users globally, allowing them to edit messages and exempting them from media deletion across all chats.\n"
        "5. **Broadcast Feature**: The owner can broadcast messages to all chats and users who have interacted with the bot.\n"
        "6. **Statistics Tracking**: The owner can view stats about how many chats the bot is in and how many users have started it.\n"
        "7. **Log Messages**: All actions and errors are logged in a specified group chat for easy monitoring."
    )
    update.message.reply_text(feature_list)

# Help command with inline buttons
def help_command(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [
            InlineKeyboardButton("Edited Messages", callback_data='edited_messages'),
            InlineKeyboardButton("Back", callback_data='show_help')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("How to use this bot:\n"
                              "1. Use /auth to authorize users to edit messages.\n"
                              "2. Use /unauth to revoke that authorization.\n"
                              "3. Use /setdelay to set the media deletion time.\n"
                              "4. Use /gauth to globally authorize users.\n"
                              "5. Use /gunauth to revoke global authorization.\n"
                              "6. Use /broadcast to send messages to all users and chats.\n"
                              "7. Use /stats to view bot statistics.", reply_markup=reply_markup)

# Callback query handler for inline buttons
def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()

    if query.data == 'edited_messages':
        query.edit_message_text("Edited Messages:\n"
                                "This bot deletes edited messages that are not from authorized users.\n"
                                "Click 'Back' to return.")
    elif query.data == 'show_help':
        help_command(update, context)

# Log when the bot is added to a new chat
def log_new_chat(update: Update, context: CallbackContext) -> None:
    chat = update.chat
    log_message = (
        f"New chat added:\n"
        f"Chat title: {chat.title}\n"
        f"Chat username: @{chat.username if chat.username else 'No username'}\n"
        f"Chat ID: {chat.id}"
    )
    log_to_group(log_message)

# Error handler
def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update {update} caused error {context.error}')

def main() -> None:
    # Load token from environment variable
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    # Create an application instance
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
    application.add_handler(CommandHandler("features", features))  # Add the features command
    application.add_handler(CommandHandler("help", help_command))  # Add the help command

    # Message handler for media (photos, videos, stickers)
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.sticker, handle_media))
    application.add_handler(MessageHandler(filters.TEXT & filters.EDITED, edited_message))

    # Chat member handler to track when the bot is added to a new chat
    application.add_handler(ChatMemberHandler(log_new_chat, pattern='new_chat_members'))

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button))

    # Log all errors
    application.add_error_handler(error)

    # Start the Application
    application.run_polling()

if __name__ == '__main__':
    main()
