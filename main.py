import os
import logging
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.error import BadRequest
from pymongo import MongoClient
from dotenv import load_dotenv
from threading import Timer

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
OWNER_ID = int(os.getenv("OWNER_ID"))

# List of admin user IDs
ADMINS = [1110013191, 6663845789]  # Replace with actual Telegram user IDs of admins

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
client = MongoClient(MONGODB_URI)
db = client['telegram_bot']
auth_collection = db['authorized_users']

# In-memory storage for group auth and delay settings
group_auth = {}
group_delay = {}  # Dictionary to store delay settings per group

DEFAULT_DELAY = 1800  # Default delay in seconds (30 minutes)

# Helper function to get the user object from a username or user ID
def get_user_from_username_or_id(context: CallbackContext, chat_id: int, identifier: str):
    try:
        if identifier.isdigit():  # If it's a numeric user ID
            user_id = int(identifier)
            member = context.bot.get_chat_member(chat_id, user_id)
            return member.user if member else None

        else:  # Handle username lookup
            username = identifier.lstrip('@')

            # First, check if the user is an admin
            admins = context.bot.get_chat_administrators(chat_id)
            for admin in admins:
                if admin.user.username and admin.user.username.lower() == username.lower():
                    return admin.user

            # Try getting the member from the group using the username
            member = context.bot.get_chat_member(chat_id, username)
            return member.user if member else None

    except telegram.error.BadRequest as e:
        if "user_id" in str(e) or "chat not found" in str(e):
            logger.warning(f"Invalid user_id/username: {identifier}")
        else:
            logger.warning(f"Failed to retrieve user {identifier}: {e}")
        return None

    except Exception as e:
        logger.warning(f"Unexpected error retrieving user {identifier}: {e}")
        return None
           
# Check if user is an admin in the current chat
def is_admin(user_id: int, chat_id: int, context: CallbackContext) -> bool:
    admins = context.bot.get_chat_administrators(chat_id)
    return user_id in [admin.user.id for admin in admins] or user_id in ADMINS

# Command to start the bot
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    
    # Add user to the database if they haven't started the bot before
    if not auth_collection.find_one({"user_id": user_id}):
        auth_collection.insert_one({"user_id": user_id, "is_started": True})

    update.message.reply_text(
        "Welcome to the bot! This bot helps manage message editing in group chats. "
        "Admins can authorize users to edit messages, and the bot will delete edited messages "
        "from unauthorized users immediately. Use /help to see available commands."
    )
    
# Command to authorize users to edit messages
def auth(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in group chats.")
        return

    if not is_admin(update.effective_user.id, update.effective_chat.id, context):
        update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args and not update.message.reply_to_message:
        update.message.reply_text("Usage: /auth <username/user_id or reply to user>")
        return

    target_user = None

    # If replying to a message, get the user from the reply
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user

    # If a username/user ID is provided
    if context.args:
        target_user = get_user_from_username_or_id(context, update.effective_chat.id, context.args[0])

    if target_user is None:
        update.message.reply_text("User not found or invalid username/user ID.")
        return

    # Authorize the user
    if target_user.id not in group_auth.get(update.effective_chat.id, []):
        group_auth.setdefault(update.effective_chat.id, []).append(target_user.id)
        update.message.reply_text(f"{target_user.mention_html()} is now authorized for this chat.", parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text("User is already authorized.")

# Command to unauthorize users to edit messages
def unauth(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in group chats.")
        return

    if not is_admin(update.effective_user.id, update.effective_chat.id, context):
        update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args and not update.message.reply_to_message:
        update.message.reply_text("Usage: /unauth <username/user_id or reply to user>")
        return

    target_user = None

    # If replying to a message, get the user from the reply
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user

    # If a username/user ID is provided
    if context.args:
        target_user = get_user_from_username_or_id(context, update.effective_chat.id, context.args[0])

    if target_user is None:
        update.message.reply_text("User not found or invalid username/user ID.")
        return

    # Unauthorize the user
    if target_user.id in group_auth.get(update.effective_chat.id, []):
        group_auth[update.effective_chat.id].remove(target_user.id)
        update.message.reply_text(f"{target_user.mention_html()} is now unauthorized for this chat.", parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text("User is not authorized or does not exist.")

# Command to list authorized users
def authusers(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in group chats.")
        return
    
    if not is_admin(update.effective_user.id, update.effective_chat.id, context):
        update.message.reply_text("You are not authorized to use this command.")
        return

    authorized_users = group_auth.get(update.effective_chat.id, [])
    if authorized_users:
        user_list = ", ".join([context.bot.get_chat_member(update.effective_chat.id, user_id).user.username for user_id in authorized_users])
        update.message.reply_text(f"Authorized users: {user_list}")
    else:
        update.message.reply_text("No authorized users.")

# Handler for message edits
def message_edit(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    # For edited messages, we should access 'update.edited_message'
    edited_message = update.edited_message
    user_id = edited_message.from_user.id

    if user_id in group_auth.get(update.effective_chat.id, []) or \
       user_id == OWNER_ID or \
       is_admin(user_id, update.effective_chat.id, context):
        return  # Authorized user, owner, or admin, do nothing

    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=edited_message.message_id)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{edited_message.from_user.mention_html()} just edited a message and I deleted it.",
            parse_mode=ParseMode.HTML
        )
    except BadRequest:
        logger.warning(f"Failed to delete message {edited_message.message_id} from {edited_message.from_user.username}")
        
# Command to broadcast a message to all groups and users who started the bot
def broadcast(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id != OWNER_ID:
        update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args:
        update.message.reply_text("Usage: /broadcast <message>")
        return

    message = ' '.join(context.args)

    # Send to all groups
    for chat_id in group_auth.keys():
        try:
            context.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.warning(f"Failed to send message to group {chat_id}: {e}")

    # Send to all users who started the bot
    users = auth_collection.find({"is_started": True})  # Modify this as necessary
    for user in users:
        try:
            context.bot.send_message(chat_id=user['user_id'], text=message)
        except Exception as e:
            logger.warning(f"Failed to send message to user {user['user_id']}: {e}")

    update.message.reply_text("Broadcast message sent.")

# Command to set deletion delay
def setdelay(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in group chats.")
        return
    
    if not is_admin(update.effective_user.id, update.effective_chat.id, context):
        update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("Usage: /setdelay <delay_in_minutes>")
        return

    delay_minutes = int(context.args[0])
    group_delay[update.effective_chat.id] = delay_minutes * 60  # Convert to seconds
    update.message.reply_text(f"Media and sticker deletion delay set to {delay_minutes} minutes.")

# Handler for media and sticker messages
def media_handler(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        return

    user_id = update.message.from_user.id

    if user_id in group_auth.get(update.effective_chat.id, []) or \
       user_id == OWNER_ID or \
       is_admin(user_id, update.effective_chat.id, context):
        return  # Authorized user, owner, or admin, do nothing

    delay = group_delay.get(update.effective_chat.id, DEFAULT_DELAY)
    Timer(delay, delete_message, [context, update.effective_chat.id, update.message.message_id]).start()

def delete_message(context: CallbackContext, chat_id: int, message_id: int):
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest:
        logger.warning(f"Failed to delete message {message_id} from chat {chat_id}")

# Command to get stats
def stats(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id != OWNER_ID and update.effective_user.id not in ADMINS:
        update.message.reply_text("You are not authorized to use this command.")
        return

    chat_count = len(group_auth)  # Number of groups the bot is in
    user_count = auth_collection.count_documents({"is_started": True})  # Number of users who started the bot
    update.message.reply_text(f"The bot is in {chat_count} chats and has {user_count} users.")

# Main function to start the bot
def main() -> None:
    updater = Updater(TELEGRAM_TOKEN)

    # Handlers
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("auth", auth))
    dp.add_handler(CommandHandler("unauth", unauth))
    dp.add_handler(CommandHandler("authusers", authusers))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("setdelay", setdelay))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(MessageHandler(Filters.update.edited_message, message_edit))
    dp.add_handler(MessageHandler(Filters.photo | Filters.video | Filters.document | Filters.audio | Filters.sticker, media_handler))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
