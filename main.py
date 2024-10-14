import asyncio
import os
import time
import logging
from pymongo import MongoClient
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    CallbackContext, PicklePersistence, CallbackQueryHandler
)
from dotenv import load_dotenv
from telegram.constants import ParseMode

# Load environment variables
load_dotenv()

# Retrieve environment variables
API_TOKEN = os.getenv('API_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID'))
LOG_GROUP_ID = int(os.getenv('LOG_GROUP_ID'))
MONGO_URI = os.getenv('MONGO_URI')
# Ensure all environment variables are set
if not all([API_TOKEN, OWNER_ID, LOG_GROUP_ID, MONGO_URI]):
    raise ValueError("Missing one or more required environment variables.")

# Configure logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection setup
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(MONGO_URI)
db = client['telegram_bot']

# Load persistent data with PicklePersistence
persistence = PicklePersistence(filepath='bot_data.pkl')  # Specify a file path for persistence

# Track the bot's uptime
start_time = time.time()

# Set to keep track of exempted user IDs
exempted_users = set()

# Function to check if a user is an admin
async def is_user_admin(chat, user_id):
    try:
        member = await chat.get_member(user_id)
        return member.status in (ChatMember.ADMINISTRATOR, ChatMember.CREATOR)
    except Exception as e:
        logger.error(f"Error retrieving member status: {e}")
        return False

# Command handler for /start
async def start(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    welcome_message = f"Hello {user.mention_markdown_v2()}!"

    # Create buttons for additional commands
    keyboard = [
        [InlineKeyboardButton("Add Bot To Your Groups", url="https://t.me/surveillantsbot?startgroup=true")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the welcome message with the inline buttons
    await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_message, reply_markup=reply_markup)
    logger.info(f"{user.mention_markdown_v2()} started a bot.")

# Command handler for /help
async def help_command(update: Update, context: CallbackContext) -> None:
    help_message = (
        "Some people on Telegram find it entertaining to destroy a group. "
        "These individuals will hide their presence among normal users and later on they will edit their messages.\n\n"
        "The edited message system auto-deletes anyone's message who is editing their present or past messages. "
        "Doesn't matter how much time has passed.\n\n"
        "Admin commands:\n"
        "- /auth You can authorize a person you trust and their messages won't be deleted even after they edit.\n\n"
        "Examples:\n"
        "- Authorize a user by username or user id:\n"
        "  /auth @username\n"
        "  or /auth 1110013191\n\n"
        "- Unauthorize a user by username or user id:\n"
        "  /unauth @username\n"
        "  or /unauth 1110013191"
    )

    # Create InlineKeyboardButton for editing messages
    keyboard = [
        [InlineKeyboardButton("Edited Messages", callback_data='edited_messages')],
        [InlineKeyboardButton("Back", callback_data='help_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(help_message, reply_markup=reply_markup)

# Callback for button presses in help command
async def help_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'edited_messages':
        edit_message_text = (
            "Some people on Telegram find it entertaining to destroy a group. "
            "These individuals will hide their presence among normal users and later on they will edit their messages.\n\n"
            "The edited message system auto-deletes anyone's message who is editing their present or past messages. "
            "Doesn't matter how much time has passed.\n\n"
            "Admin commands:\n"
            "- /auth You can authorize a person you trust and their messages won't be deleted even after they edit.\n\n"
            "Examples:\n"
            "- Authorize a user by username or user id:\n"
            "  /auth @username\n"
            "  or /auth 1110013191\n\n"
            "- Unauthorize a user by username or user id:\n"
            "  /unauth @username\n"
            "  or /unauth 1110013191"
        )
        await query.edit_message_text(text=edit_message_text, reply_markup=query.message.reply_markup)

    elif query.data == 'help_back':
        await help_command(update, context)

# Command handler for /features
async def features(update: Update, context: CallbackContext) -> None:
    features_message = (
        "Features of this bot:\n"
        "- **Message Editing Detection**: Automatically deletes messages if users edit them after sending.\n"
        "- **Admin Control**: Admins can authorize or unauthorize users, protecting them from auto-deletion.\n"
        "- **Broadcast Messages**: The owner can send messages to all groups where the bot is present.\n"
        "- **User Management**: Admins can view and manage exempted users easily.\n"
        "- **Help Command**: Provides detailed information about bot commands and usage.\n"
    )
    await update.message.reply_text(features_message, parse_mode=ParseMode.MARKDOWN_V2)

# Command handler to authorize a user (exempt them)
async def auth(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat.id
    user_id = None
    user_mention = None

    if update.message.chat.type in ['group', 'supergroup']:
        identifier = context.args[0] if context.args else None

        if update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            user_mention = update.message.reply_to_message.from_user.mention_markdown_v2()
        else:
            if identifier and (await is_user_admin(update.message.chat, update.message.from_user.id) or update.message.from_user.id == OWNER_ID):
                if identifier.isdigit():
                    user_id = int(identifier)
                    user_mention = f"[User](tg://user?id={user_id})"
                else:
                    user_id = None
                    user_mention = None

        # Check if the command is invoked by the owner
        if update.message.from_user.id == OWNER_ID:
            if user_id:
                # Store the user ID globally for the owner
                exempted_users.add(user_id)
                persistence.update_user_data({'global_exempted_users': exempted_users})
                await update.message.reply_text(f"User {user_mention} has been globally exempted from message deletion.")
                logger.info(f"Global exemption for user {user_id} by owner in chat {update.message.chat.title}")
            else:
                await update.message.reply_text("User not found.")
        else:
            # For admins, store the exemption only for this chat
            if user_id and user_id not in exempted_users:
                # Retrieve current chat-specific exempted users from persistence
                chat_exempted_users = persistence.get_chat_data().get(chat_id, {}).get('exempted_users', set())
                chat_exempted_users.add(user_id)
                
                # Update the persistent data for this chat
                persistence.update_chat_data({chat_id: {'exempted_users': chat_exempted_users}})
                await update.message.reply_text(f"User {user_mention} has been exempted from message deletion in this chat.")
                logger.info(f"Exemption for user {user_id} by admin in chat {update.message.chat.title}")
            else:
                await update.message.reply_text("User not found or already exempted.")

# Command handler to unauthorize a user
async def unauth(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat.id
    user_id = None
    user_mention = None

    if update.message.chat.type in ['group', 'supergroup']:
        identifier = context.args[0] if context.args else None

        if update.message.reply_to_message:
            user_id = update.message.reply_to_message.from_user.id
            user_mention = update.message.reply_to_message.from_user.mention_markdown_v2()
        else:
            if identifier and (await is_user_admin(update.message.chat, update.message.from_user.id) or update.message.from_user.id == OWNER_ID):
                if identifier.isdigit():
                    user_id = int(identifier)
                    user_mention = f"[User](tg://user?id={user_id})"
                else:
                    user_id = None
                    user_mention = None

        if update.message.from_user.id == OWNER_ID:
            if user_id and user_id in exempted_users:
                exempted_users.remove(user_id)
                persistence.update_user_data({'global_exempted_users': exempted_users})
                await update.message.reply_text(f"User {user_mention} has been globally unauthorized from message deletion.")
                logger.info(f"Global unauthorized for user {user_id} by owner in chat {update.message.chat.title}")
            else:
                await update.message.reply_text("User not found or was not exempted.")
        else:
            if user_id and user_id in exempted_users:
                # Retrieve current chat-specific exempted users from persistence
                chat_exempted_users = persistence.get_chat_data().get(chat_id, {}).get('exempted_users', set())
                chat_exempted_users.discard(user_id)  # Remove the user from the exempted set
                
                # Update the persistent data for this chat
                persistence.update_chat_data({chat_id: {'exempted_users': chat_exempted_users}})
                await update.message.reply_text(f"User {user_mention} has been unauthorized from message deletion in this chat.")
                logger.info(f"Unauthorized for user {user_id} by admin in chat {update.message.chat.title}")
            else:
                await update.message.reply_text("User not found or was not exempted.")

# Function to get exempted users for a chat
async def get_exempted_users(chat_id):
    # Retrieve the exempted users from the database
    chat_exempted_users = await db.exempted_users.find_one({'chat_id': chat_id})
    return chat_exempted_users['user_ids'] if chat_exempted_users else []

# Command handler to list exempted users
async def authusers(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat.id
    exempted_users = await get_exempted_users(chat_id)
    
    if exempted_users:
        users_list = "\n".join(f"[User](tg://user?id={uid})" for uid in exempted_users)
        await update.message.reply_text(f"Exempted users:\n{users_list}", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("No exempted users in this chat.")

# Command handler to get globally exempted users
async def gauthusers(update: Update, context: CallbackContext) -> None:
    global_exempted_users = persistence.get_user_data().get('global_exempted_users', set())
    
    if global_exempted_users:
        users_list = "\n".join(f"[User](tg://user?id={uid})" for uid in global_exempted_users)
        await update.message.reply_text(f"Globally exempted users:\n{users_list}", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("No globally exempted users.")

# Command handler for broadcasting messages
async def broadcast(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id == OWNER_ID:
        message = ' '.join(context.args)
        if message:
            async for chat in db.chats.find({}):  # Assuming you have a collection of chat IDs
                try:
                    await context.bot.send_message(chat_id=chat['_id'], text=message)
                except Exception as e:
                    logger.error(f"Failed to send message to chat {chat['_id']}: {e}")
            await update.message.reply_text("Broadcast message sent.")
        else:
            await update.message.reply_text("Please provide a message to broadcast.")
    else:
        await update.message.reply_text("Only the owner can broadcast messages.")

# Main function to run the bot
async def main() -> None:
    # Create the Application
    application = ApplicationBuilder().token(API_TOKEN).persistence(persistence).build()

    # Add command handlers (assuming these are defined somewhere in your code)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("features", features))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("unauth", unauth))
    application.add_handler(CommandHandler("authusers", authusers))
    application.add_handler(CommandHandler("gauthusers", gauthusers))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(help_callback, pattern='help_back|edited_messages'))

    # Start the bot
    try:
        await application.initialize()  # Ensure the application is initialized
        await application.run_polling()  # Run the bot until the user presses Ctrl-C
    except Exception as e:
        logger.error(f"Error in running bot: {e}")
    finally:
        await application.shutdown()  # Properly shut down the application

if __name__ == "__main__":
    try:
        asyncio.run(main())  # Run the main function using asyncio.run()
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
