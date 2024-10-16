import os
import threading
from datetime import datetime
from telegram import Update, Bot, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))
MONGODB_URI = os.getenv("MONGODB_URI")
LOG_GROUP_CHAT_ID = os.getenv("LOG_GROUP_CHAT_ID")

# MongoDB setup
client = MongoClient(MONGODB_URI)
db = client['telegram_bot']
users_collection = db['users']
groups_collection = db['groups']
log_collection = db['logs']

# Check if user is admin
def is_admin(chat_id, user_id):
    # Implement your own method to check if user is admin
    return False  # Placeholder: You need to implement this

# Check if user is globally authorized
def is_globally_authorized(user_id):
    user = users_collection.find_one({"user_id": user_id})
    return user.get("is_globally_authorized", False)

# Check if user is authorized in a specific group
def is_authorized(chat_id, user_id):
    group = groups_collection.find_one({"chat_id": chat_id})
    authorized_users = group.get("authorized_users", [])
    return user_id in authorized_users

# Get user ID by username
def get_user_id_by_username(username, context):
    username = username.lstrip('@')  # Remove '@' if present
    user = context.bot.get_chat(username)
    return user.id if user else None

# Log to the log group chat
def log_to_chat(log_message):
    try:
        bot = Bot(token=BOT_TOKEN)
        bot.send_message(chat_id=LOG_GROUP_CHAT_ID, text=log_message)
    except Exception as e:
        print(f"Error logging to chat: {e}")

# Authorize a user in a specific group
def auth(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    if context.args:
        if context.args[0].startswith('@'):  # Check if the argument is a username
            user_id = get_user_id_by_username(context.args[0], context)
        else:
            user_id = int(context.args[0])  # Assume it's a user ID
    else:
        user_id = update.reply_to_message.from_user.id if update.reply_to_message else None

    if user_id is not None and is_admin(chat_id, update.message.from_user.id):
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$addToSet": {"authorized_users": user_id}},
            upsert=True
        )
        update.message.reply_text(f"User {user_id} has been authorized in this group.")
    else:
        update.message.reply_text("Only group admins can authorize users.")

# Unauthorize a user in a specific group
def unauth(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    if context.args:
        if context.args[0].startswith('@'):  # Check if the argument is a username
            user_id = get_user_id_by_username(context.args[0], context)
        else:
            user_id = int(context.args[0])  # Assume it's a user ID
    else:
        user_id = update.reply_to_message.from_user.id if update.reply_to_message else None

    if user_id is not None and is_admin(chat_id, update.message.from_user.id):
        groups_collection.update_one(
            {"chat_id": chat_id},
            {"$pull": {"authorized_users": user_id}}
        )
        update.message.reply_text(f"User {user_id} has been unauthorized in this group.")
    else:
        update.message.reply_text("Only group admins can unauthorize users.")

# Globally authorize a user
def gauth(update: Update, context: CallbackContext):
    if update.message.from_user.id == BOT_OWNER_ID:
        if context.args:
            if context.args[0].startswith('@'):  # Check if the argument is a username
                user_id = get_user_id_by_username(context.args[0], context)
            else:
                user_id = int(context.args[0])  # Assume it's a user ID
        else:
            user_id = update.reply_to_message.from_user.id if update.reply_to_message else None

        if user_id is not None:
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"is_globally_authorized": True}},
                upsert=True
            )
            update.message.reply_text(f"User {user_id} has been globally authorized.")
        else:
            update.message.reply_text("User not found.")
    else:
        update.message.reply_text("Only the bot owner can globally authorize users.")

# Globally unauthorize a user
def ungauth(update: Update, context: CallbackContext):
    if update.message.from_user.id == BOT_OWNER_ID:
        if context.args:
            if context.args[0].startswith('@'):  # Check if the argument is a username
                user_id = get_user_id_by_username(context.args[0], context)
            else:
                user_id = int(context.args[0])  # Assume it's a user ID
        else:
            user_id = update.reply_to_message.from_user.id if update.reply_to_message else None

        if user_id is not None:
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"is_globally_authorized": False}},
                upsert=True
            )
            update.message.reply_text(f"User {user_id} has been globally unauthorized.")
        else:
            update.message.reply_text("User not found.")
    else:
        update.message.reply_text("Only the bot owner can globally unauthorize users.")

# Log when the bot is added to a new chat
def log_new_chat(context: CallbackContext, chat_id, chat_title=None, chat_username=None):
    log_message = f"Bot added to new chat:\nChat ID: {chat_id}\nChat Title: {chat_title or 'N/A'}\nChat Username: {chat_username or 'N/A'}"
    log_collection.insert_one({
        "event": "bot_added_to_chat",
        "chat_id": chat_id,
        "chat_title": chat_title or "Private Chat",
        "chat_username": chat_username,
        "timestamp": datetime.utcnow()
    })
    log_to_chat(log_message)  # Log to the log group chat

# Log when a user starts the bot
def log_new_user_start(context: CallbackContext, user_id, username=None):
    log_message = f"User started the bot:\nUser ID: {user_id}\nUsername: {username or 'Unknown'}"
    log_collection.insert_one({
        "event": "bot_started_by_user",
        "user_id": user_id,
        "username": username or "Unknown",
        "timestamp": datetime.utcnow()
    })
    log_to_chat(log_message)  # Log to the log group chat

# /start command handler
def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    update.message.reply_text("Hello! I'm a group management bot. Use /features to see what I can do!")

    # Log the event when a user starts the bot
    log_new_user_start(context, user.id, user.username)

# /setdelay command handler (sets media deletion delay)
def set_delay(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if not context.args:
        update.message.reply_text("Please specify the delay time in minutes.")
        return
    delay = int(context.args[0])

    groups_collection.update_one({"chat_id": chat_id}, {"$set": {"delete_delay": delay}}, upsert=True)
    update.message.reply_text(f"Media deletion delay set to {delay} minutes.")

# Deleting media and stickers after delay (without notifications)
def schedule_media_deletion(bot: Bot, chat_id, message_id, delay):
    def delete_media():
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            print(f"Error deleting media: {e}")  # Log any errors

    # Start a timer that will delete the media after the specified delay (in minutes)
    threading.Timer(delay * 60, delete_media).start()

# Media handler that schedules deletion of media and stickers
def media_handler(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    group = groups_collection.find_one({"chat_id": chat_id})
    delay = group.get("delete_delay", 30)  # Default delay: 30 minutes
    schedule_media_deletion(context.bot, chat_id, message_id, delay)

# Function to delete edited messages
def delete_edited_messages(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    if is_authorized(chat_id, user_id):
        return  # If the user is authorized, do nothing

    # Log message deletion and notify group
    context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    user_mention = f"<a href='tg://user?id={user_id}'>{update.message.from_user.first_name}</a>"
    context.bot.send_message(chat_id=chat_id, text=f"{user_mention} just edited a message and I deleted it.", parse_mode=ParseMode.HTML)

# Broadcast messages to all groups (owner only)
def broadcast(update: Update, context: CallbackContext):
    if update.message.from_user.id == BOT_OWNER_ID:
        message = ' '.join(context.args)
        for group in groups_collection.find({}):
            context.bot.send_message(chat_id=group['chat_id'], text=message)
        update.message.reply_text("Broadcast message sent to all groups.")
    else:
        update.message.reply_text("Only the bot owner can send broadcast messages.")

# Stats command to display bot usage statistics
def stats(update: Update, context: CallbackContext):
    total_chats = groups_collection.count_documents({})
    total_users = users_collection.count_documents({})
    
    stats_message = f"Bot Statistics:\n"
    stats_message += f"Total Chats: {total_chats}\n"
    stats_message += f"Total Users: {total_users}\n\n"
    stats_message += "Chat Details:\n"
    
    for chat in groups_collection.find({}):
        chat_username = chat.get('chat_username', 'N/A')
        chat_id = chat['chat_id']
        chat_title = chat.get('chat_title', 'N/A')
        stats_message += f"Chat ID: {chat_id}, Title: {chat_title}, Username: {chat_username}\n"
    
    stats_message += "\nUser Details:\n"
    
    for user in users_collection.find({}):
        username = user.get('username', 'N/A')
        user_id = user['user_id']
        stats_message += f"User ID: {user_id}, Username: {username}\n"

    update.message.reply_text(stats_message)

# Command to show authorized users in the current chat
def authusers(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    group = groups_collection.find_one({"chat_id": chat_id})
    authorized_users = group.get("authorized_users", [])
    
    if authorized_users:
        user_list = "\n".join(str(user_id) for user_id in authorized_users)
        update.message.reply_text(f"Authorized Users in this chat:\n{user_list}")
    else:
        update.message.reply_text("No authorized users in this chat.")

# Command to show globally authorized users (owner only)
def gauthusers(update: Update, context: CallbackContext):
    if update.message.from_user.id == BOT_OWNER_ID:
        globally_authorized_users = users_collection.find({"is_globally_authorized": True})
        if globally_authorized_users:
            user_list = "\n".join(f"User ID: {user['user_id']}, Username: {user.get('username', 'N/A')}" for user in globally_authorized_users)
            update.message.reply_text(f"Globally Authorized Users:\n{user_list}")
        else:
            update.message.reply_text("No globally authorized users.")
    else:
        update.message.reply_text("Only the bot owner can view globally authorized users.")

# Display features of the bot
def features(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Features:\n"
        "- Deletes edited messages from non-admin users\n"
        "- Deletes media and stickers after a customizable delay\n"
        "- Admins can authorize/unauthorize users to edit messages\n"
        "- Global authorization/unauthorization by the bot owner\n"
        "- Broadcast messages to all groups\n"
        "- View bot statistics\n"
        "- Customizable deletion delay\n"
        "- Logs user and chat activity\n"
        "- /features for feature list\n"
        "- /help for help information"
    )

# Display help information
def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Help:\n"
        "Use the following commands:\n"
        "/start - Start the bot\n"
        "/auth - Authorize a user in this group\n"
        "/unauth - Unauthorize a user in this group\n"
        "/gauth - Globally authorize a user\n"
        "/ungauth - Globally unauthorize a user\n"
        "/setdelay - Set deletion delay for media and stickers\n"
        "/broadcast - Broadcast a message to all groups\n"
        "/stats - Show bot statistics\n"
        "/authusers - Show authorized users in this chat\n"
        "/gauthusers - Show globally authorized users\n"
        "/features - List bot features\n"
        "/help - Show this help message"
    )

# Function to handle when the bot is added to a new chat
def bot_added_to_chat(update: Update, context: CallbackContext):
    chat = update.message.chat
    chat_id = chat.id
    chat_title = chat.title
    chat_username = chat.username

    log_new_chat(context, chat_id, chat_title, chat_username)

    context.bot.send_message(chat_id=chat_id, text="Hello! I'm your group gaurdian bot. Use /help to see what I can do!")

# Main function to start the bot
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add handlers for commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("auth", auth))
    dp.add_handler(CommandHandler("unauth", unauth))
    dp.add_handler(CommandHandler("gauth", gauth))
    dp.add_handler(CommandHandler("ungauth", ungauth))
    dp.add_handler(CommandHandler("setdelay", set_delay))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("authusers", authusers))
    dp.add_handler(CommandHandler("gauthusers", gauthusers))
    dp.add_handler(CommandHandler("features", features))
    dp.add_handler(CommandHandler("help", help_command))

    # Add handlers for messages and chat events
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, bot_added_to_chat))
    dp.add_handler(MessageHandler(Filters.edited_message, delete_edited_messages))
    dp.add_handler(MessageHandler(Filters.media, media_handler))

    # Start polling for updates
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
