import os
import logging
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
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
group_collection = db['groups']
# In-memory storage for group auth and delay settings
group_auth = {}
group_delay = {}  # Dictionary to store delay settings per group
authorized_users = {}

DEFAULT_DELAY = 1800  # Default delay in seconds (30 minutes)

# Check if user is an admin in the current chat
def is_admin(user_id: int, chat_id: int, context: CallbackContext) -> bool:
    admins = context.bot.get_chat_administrators(chat_id)
    return user_id in [admin.user.id for admin in admins] or user_id in ADMINS

# Command to start the bot
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Add user to the database if they haven't started the bot before
    if not auth_collection.find_one({"user_id": user_id}):
        auth_collection.insert_one({"user_id": user_id, "is_started": True})
    
    # Create mention using first name
    user_mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
    
    # Inline keyboard with the "Add me to your chat!" button
    keyboard = [
        [InlineKeyboardButton("Add me to your chat!", url="http://t.me/surveillantsbot?startgroup=true")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Custom start message with the button
    update.message.reply_text(
        f"𝖧𝖾𝗅𝗅𝗈 {user_mention}, 𝖨'𝗆 𝗒𝗈𝗎𝗋 𝗔𝗹𝗰𝘆𝗼𝗻𝗲 𝗚𝘂𝗮𝗿𝗱𝗶𝗮𝗻, 𝗁𝖾𝗋𝖾 𝗍𝗈 𝗆𝖺𝗂𝗇𝗍𝖺𝗂𝗇 𝖺 𝗌𝖾𝖼𝗎𝗋𝖾 𝖾𝗇𝗏𝗂𝗋𝗈𝗇𝗆𝖾𝗇𝗍 𝖿𝗈𝗋 𝗈𝗎𝗋 𝖽𝗂𝗌𝖼𝗎𝗌𝗌𝗂𝗈𝗇𝗌 𝖺𝗇𝖽 𝗄𝖾𝖾𝗉 𝗍𝗁𝗂𝗌 𝖼𝗈𝗆𝗆𝗎𝗇𝗂𝗍𝗒 𝗌𝖺𝖿𝖾 𝖺𝗇𝖽 𝗌𝗉𝖺𝗆-𝖿𝗋𝖾𝖾. 𝖨'𝗅𝗅 𝗁𝖺𝗇𝖽𝗅𝖾 𝗍𝗁𝗂𝗇𝗀'𝗌 𝗅𝗂𝗄𝖾 𝗋𝖾𝗆𝗈𝗏𝗂𝗇𝗀 𝗎𝗇𝗐𝖺𝗇𝗍𝖾𝖽 𝗌𝗍𝗂𝖼𝗄𝖾𝗋'𝗌, 𝗀𝗂𝖿𝗌, 𝖾𝗅𝗂𝗍𝖾𝖽 𝗆𝖾𝗌𝗌𝖺𝗀𝖾𝗌 𝖺𝗇𝖽 𝗆𝖾𝖽𝗂𝖺𝗌. 𝗐𝖺𝗋𝗇𝗂𝗇𝗀 𝗎𝗌𝖾𝗋𝗌 𝖿𝗈𝗋 𝗂𝗇𝖺𝗉𝗉𝗋𝗈𝗉𝗋𝗂𝖺𝗍𝖾 𝖻𝖾𝗁𝖺𝗏𝗂𝗈𝗎𝗋, 𝖺𝗇𝖽 𝖾𝗇𝗌𝗎𝗋𝗂𝗇𝗀 𝖺 𝗌𝗆𝗈𝗈𝗍𝗁 𝖼𝗈𝗆𝗆𝗎𝗇𝗂𝖼𝖺𝗍𝗂𝗈𝗇 𝗐𝗂𝗍𝗁𝗈𝗎𝗍 𝗐𝗈𝗋𝗋𝗒𝗂𝗇𝗀 𝖺𝖻𝗈𝗎𝗍 𝖺𝗇𝗒𝗍𝗁𝗂𝗇𝗀!!",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )
    
# Function to authorize a user by username or user ID
def auth(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    message = update.message
    args = context.args

    # Check if the user is an admin or the owner
    if not is_admin(update.effective_user.id, chat_id, context) and update.effective_user.id != OWNER_ID:
        message.reply_text("You are not authorized to use this command.")
        return

    # Check if command is issued as a reply
    if update.message.reply_to_message:
        username = update.message.reply_to_message.from_user.username
        user_id = update.message.reply_to_message.from_user.id
    elif args and args[0].startswith('@'):
        username = args[0][1:]  # Remove '@' from the username
        user_id = None  # No user_id from args
    elif args and args[0].isdigit():
        user_id = int(args[0])  # Parse user ID from args
        username = None  # No username from args
    else:
        message.reply_text("Please provide a valid username (e.g., /auth @username) or reply to a user's message.")
        return

    # Determine the username based on the user ID if provided
    if user_id:
        member = context.bot.get_chat_member(chat_id, user_id)
        if member:
            username = member.user.username
        else:
            message.reply_text("Invalid user ID.")
            return

    # Check if the user is already authorized
    if username in authorized_users.get(chat_id, set()):
        message.reply_text(f"@{username} is already authorized.")
    else:
        authorized_users.setdefault(chat_id, set()).add(username)
        message.reply_text(f"@{username} has been authorized.")

# Function to unauthorize a user by username or user ID
def unauth(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    message = update.message
    args = context.args

    # Check if the user is an admin or the owner
    if not is_admin(update.effective_user.id, chat_id, context) and update.effective_user.id != OWNER_ID:
        message.reply_text("You are not authorized to use this command.")
        return

    # Check if command is issued as a reply
    if update.message.reply_to_message:
        username = update.message.reply_to_message.from_user.username
    elif args and args[0].startswith('@'):
        username = args[0][1:]  # Remove '@' from the username
    elif args and args[0].isdigit():
        user_id = int(args[0])  # Parse user ID from args
        member = context.bot.get_chat_member(chat_id, user_id)
        if member:
            username = member.user.username
        else:
            message.reply_text("Invalid user ID.")
            return
    else:
        message.reply_text("Please provide a valid username (e.g., /unauth @username) or reply to a user's message.")
        return

    # Check if the user is authorized
    if username in authorized_users.get(chat_id, set()):
        authorized_users[chat_id].remove(username)
        message.reply_text(f"@{username} has been unauthorized.")
    else:
        message.reply_text(f"@{username} is not authorized.")
        
# Command to list authorized users
def authusers(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in group chats.")
        return
    
    if not is_admin(update.effective_user.id, update.effective_chat.id, context):
        update.message.reply_text("You are not authorized to use this command.")
        return

    authorized_users_list = authorized_users.get(update.effective_chat.id, [])
    if authorized_users_list:
        user_list = ", ".join(authorized_users_list)  # Directly using the set
        update.message.reply_text(f"Authorized users: {user_list}")
    else:
        update.message.reply_text("No authorized users.")
        
# Handler for message edits
def message_edit(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    # Access the edited message
    edited_message = update.edited_message
    user_id = edited_message.from_user.id
    chat_id = update.effective_chat.id

    # Check if the user is authorized to edit messages
    if user_id in [OWNER_ID] or is_admin(user_id, chat_id, context) or \
       (chat_id in authorized_users and edited_message.from_user.username in authorized_users[chat_id]):
        return  # Authorized user, owner, or admin, do nothing

    try:
        context.bot.delete_message(chat_id=chat_id, message_id=edited_message.message_id)
        confirmation_message = context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{edited_message.from_user.mention_html()} just edited a message, and I deleted it.",
            parse_mode=ParseMode.HTML
        )
        
        # Set a timer to delete the confirmation message after 24 hours
        Timer(20, delete_message, [context, update.effective_chat.id, confirmation_message.message_id]).start()  # 86400 seconds = 24 hours

    except BadRequest:
        logger.warning(f"Failed to delete message {edited_message.message_id} from {edited_message.from_user.username}")

# Function to delete a message
def delete_message(context: CallbackContext, chat_id: int, message_id: int):
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest:
        logger.warning(f"Failed to delete message {message_id} from chat {chat_id}")

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

# Function to handle the bot joining a group
def chat_joined(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat.id
    group_auth[chat_id] = set()  # Initialize an empty set for the new group

    # Add the group to the MongoDB collection
    group_collection.update_one({"chat_id": chat_id}, {"$set": {"chat_id": chat_id}}, upsert=True)
    logger.info(f"Bot joined group: {chat_id}")

# Function to handle the bot leaving a group
def chat_left(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat.id
    if chat_id in group_auth:
        del group_auth[chat_id]  # Remove the group from tracking
        
        # Remove the group from the MongoDB collection
        group_collection.delete_one({"chat_id": chat_id})
        logger.info(f"Bot left group: {chat_id}")

# Command to get stats
def stats(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id != OWNER_ID and update.effective_user.id not in ADMINS:
        update.message.reply_text("You are not authorized to use this command.")
        return

    chat_count = group_collection.count_documents({})  # Count the number of unique chat IDs
    user_count = auth_collection.count_documents({"is_started": True})  # Number of users who started the bot
    update.message.reply_text(f"The bot is in {chat_count} chats and has {user_count} users.")

# Function to list bot features
def features(update: Update, context: CallbackContext) -> None:
    features_list = (
        "𝗔𝗹𝗰𝘆𝗼𝗻𝗲 𝗴𝘂𝗮𝗿𝗱𝗶𝗮𝗻 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 -\n\n"
        "<u><b>𝖤𝖽𝗂𝗍𝖾𝖽 𝗆𝖾𝗌𝗌𝖺𝗀𝖾:</b></u> 𝖨𝖿 𝗌𝗈𝗆𝖾𝗈𝗇𝖾 𝖾𝖽𝗂𝗍𝗌 𝖺 𝗆𝖾𝗌𝗌𝖺𝗀𝖾 𝖨'𝗅𝗅 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗍 𝗍𝗈 𝗆𝖺𝗂𝗇𝗍𝖺𝗂𝗇 𝗍𝗋𝖺𝗇𝗌𝗉𝖺𝗋𝖺𝗇𝖼𝗒 𝖺𝗇𝖽 𝗐𝗂𝗅𝗅 𝗅𝖾𝗍 𝗍𝗁𝖾 𝖺𝖽𝗆𝗂𝗇𝗌 𝗄𝗇𝗈𝗐 𝗂𝖿 𝗌𝗈𝗆𝖾𝗈𝗇𝖾 𝖾𝖽𝗂𝗍𝖾𝖽 𝖺 𝗆𝖾𝗌𝗌𝖺𝗀𝖾.\n\n"
        "<u><b>𝖠𝗎𝗍𝗈 𝖽𝖾𝗅𝖾𝗍𝖾:</b></u> 𝗒𝗈𝗎 𝖼𝖺𝗇 𝗌𝖾𝗍 𝖺 𝗍𝗂𝗆𝖾 𝗅𝗂𝗆𝗂𝗍 𝗍𝗈 𝖽𝖾𝗅𝖾𝗍𝖾 𝖺𝗅𝗅 𝗌𝗍𝗂𝖼𝗄𝖾𝗋𝗌 𝖺𝗇𝖽 𝗀𝗂𝖿𝗌 𝖺𝗇𝖽 𝗆𝖾𝖽𝗂𝖺 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝗍𝗁𝖾 𝖻𝗈𝗍 𝗐𝗂𝗅𝗅 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗍."
    )
    
    update.message.reply_text(features_list, parse_mode=ParseMode.HTML)

# help command 
def help_command(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Edited Messages", callback_data='edited_messages')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        "Helpful commands:\n"
        "- /start: Starts me! You've probably already used this.\n"
        "- /help: Sends this message; I'll tell you more about myself!\n\n"
        "If you have any bugs or questions on how to use me, have a look at my "
        "<a href='https://t.me/AlcyoneBots'>Channel</a>, or head to "
        "<a href='https://t.me/Alcyone_Support'>Support Chat</a>.\n\n"
        "All commands can be used with the following: /",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

# Function to handle the callback from inline buttons
def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()

    if query.data == 'edited_messages':
        keyboard = [
            [InlineKeyboardButton("Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
    text="<u><b>Edited messages</b></u>\n\n"
    "Some people on Telegram find it entertaining to destroy a group.\n"
    "These individuals will hide their presence among normal users and later on they will edit their messages.\n\n"
    "The edited message system auto deletes anyone's message who is editing their present or past messages; doesn't matter how many days it has been.\n\n"
    "<u><b>Admin commands:</b></u>\n"
    "- /auth: You can authorize a person you trust, and their messages won't be deleted even after they edit.\n\n"
    "<u><b>Examples:</b></u>\n"
    "- Authorize a user by username or user ID:\n"
    "   -> /auth @username\n"
    "   &lt;optional: /auth 1234567890&gt;\n\n"  # Escaped angle brackets
    "- Unauthorize a user by username or user ID:\n"
    "   -> /unauth @username\n"
    "   &lt;optional: /unauth 1234567890&gt;",
    reply_markup=reply_markup,
    parse_mode=ParseMode.HTML
        )
        
    elif query.data == 'back':
        # Rebuild the help menu
        keyboard = [
            [InlineKeyboardButton("Edited Messages", callback_data='edited_messages')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
    text="Helpful commands:\n"
        "- /start: Starts me! You've probably already used this.\n"
        "- /help: Sends this message; I'll tell you more about myself!\n\n"
        "If you have any bugs or questions on how to use me, have a look at my "
        "<a href='https://t.me/AlcyoneBots'>Channel</a>, or head to "
        "<a href='https://t.me/Alcyone_Support'>Support Chat</a>.\n\n"
        "All commands can be used with the following: /",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
        )
            
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
    dp.add_handler(CommandHandler('features', features))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.update.edited_message, message_edit))
    dp.add_handler(MessageHandler(Filters.photo | Filters.video | Filters.document | Filters.audio | Filters.sticker, media_handler))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, chat_joined))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, chat_left))
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
