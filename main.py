import os
import threading
import time
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ChatMemberHandler
from telegram import Update, Chat, ChatMember
from telegram.ext.callbackcontext import CallbackContext
from dotenv import load_dotenv
from pymongo import MongoClient

# Load environment variables from .env file
load_dotenv()

# Get bot token, MongoDB URI, bot owner ID, and log group ID from .env file
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID'))
LOG_GROUP_ID = int(os.getenv('LOG_GROUP_ID'))  # Group ID where logs will be sent

# Default deletion delay time in seconds (30 minutes)
DEFAULT_DELAY_TIME = 1800

# Initialize MongoDB client and database
client = MongoClient(MONGODB_URI)
db = client['telegram_bot_db']
authorized_users_collection = db['authorized_users']
global_authorized_users_collection = db['global_authorized_users']
bot_stats_collection = db['bot_stats']
group_chats_collection = db['group_chats']
delay_collection = db['delay_settings']

# Function to log new group chats or users
def log_event(context: CallbackContext, message: str):
    context.bot.send_message(chat_id=LOG_GROUP_ID, text=message)

# Function to start the bot
def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    chat = update.effective_chat

    # If it's a private chat (user starting the bot)
    if chat.type == Chat.PRIVATE:
        log_event(context, f"New user started the bot:\n- User: {user.mention_markdown_v2()}\n- User ID: {user.id}")
        update.message.reply_text("Welcome! I'm here to assist you.")

    update_bot_stats(user.id)  # Track user interaction
    add_chat(chat.id)  # Track the group chat (if applicable)

# Function to track the group chat in the database
def add_chat(chat_id):
    group_chats_collection.update_one(
        {"_id": chat_id},
        {"$setOnInsert": {"_id": chat_id}},
        upsert=True
    )

# Function to check if the user is an admin
def is_user_admin(chat_id, user_id, bot):
    member = bot.get_chat_member(chat_id, user_id)
    return member.status in ['administrator', 'creator']

# Function to authorize a user in a group
def auth_user_in_group(chat_id, user_id):
    authorized_users_collection.update_one(
        {"chat_id": chat_id},
        {"$addToSet": {"users": user_id}},
        upsert=True
    )

# Function to unauthorize a user in a group
def unauth_user_in_group(chat_id, user_id):
    authorized_users_collection.update_one(
        {"chat_id": chat_id},
        {"$pull": {"users": user_id}}
    )

# Function to globally authorize a user
def gauth_user(user_id):
    global_authorized_users_collection.update_one(
        {"_id": "global"},
        {"$addToSet": {"users": user_id}},
        upsert=True
    )

# Function to globally unauthorize a user
def ungauth_user(user_id):
    global_authorized_users_collection.update_one(
        {"_id": "global"},
        {"$pull": {"users": user_id}}
    )

# Function to check if a user is globally authorized
def is_globally_authorized(user_id):
    global_auth = global_authorized_users_collection.find_one({"_id": "global"})
    return global_auth and "users" in global_auth and user_id in global_auth['users']

# Function to delete media or sticker after a specific delay
def schedule_deletion(context, chat_id, message_id, delay_time):
    def delete_message():
        time.sleep(delay_time)  # Wait for the specified delay time
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            print(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

    # Run the deletion in a separate thread
    threading.Thread(target=delete_message).start()

# Function to get the deletion delay time for a chat
def get_deletion_delay(chat_id):
    chat_data = delay_collection.find_one({"chat_id": chat_id})
    if chat_data and "delay_time" in chat_data:
        return chat_data['delay_time']
    return DEFAULT_DELAY_TIME  # Default to 30 minutes if no custom delay is set

# Message handler for media and sticker messages
def handle_media_and_stickers(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    # Determine the appropriate delay time for this chat
    delay_time = get_deletion_delay(chat_id)

    # Schedule the deletion of the media or sticker message
    schedule_deletion(context, chat_id, message_id, delay_time)

# Function to handle the /setdelay command (admin only)
def setdelay(update: Update, context: CallbackContext):
    user = update.message.from_user
    chat_id = update.effective_chat.id

    if is_user_admin(chat_id, user.id, context.bot):
        if context.args and context.args[0].isdigit():
            delay_time = int(context.args[0]) * 60  # Convert minutes to seconds
            delay_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"delay_time": delay_time}},
                upsert=True
            )
            update.message.reply_text(f"Deletion delay time is set to {context.args[0]} minutes.")
        else:
            update.message.reply_text("Please provide the delay time in minutes (e.g., /setdelay 10).")
    else:
        update.message.reply_text("Only admins can use the /setdelay command.")

# Function to handle the /auth command (admin only)
def auth(update: Update, context: CallbackContext):
    user = update.message.from_user
    chat_id = update.effective_chat.id

    if is_user_admin(chat_id, user.id, context.bot):
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            auth_user_in_group(chat_id, target_user.id)
            update.message.reply_text(f"{target_user.mention_markdown_v2()} is now authorized.", parse_mode="MarkdownV2")
        elif context.args:
            try:
                target_user = context.bot.get_chat(context.args[0])
                auth_user_in_group(chat_id, target_user.id)
                update.message.reply_text(f"{target_user.mention_markdown_v2()} is now authorized.", parse_mode="MarkdownV2")
            except:
                update.message.reply_text("Could not find user.")
        else:
            update.message.reply_text("Reply to a user or provide a username to authorize.")
    else:
        update.message.reply_text("Only admins can use the /auth command.")

# Function to handle the /unauth command (admin only)
def unauth(update: Update, context: CallbackContext):
    user = update.message.from_user
    chat_id = update.effective_chat.id

    if is_user_admin(chat_id, user.id, context.bot):
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            unauth_user_in_group(chat_id, target_user.id)
            update.message.reply_text(f"{target_user.mention_markdown_v2()} is now unauthorized.", parse_mode="MarkdownV2")
        elif context.args:
            try:
                target_user = context.bot.get_chat(context.args[0])
                unauth_user_in_group(chat_id, target_user.id)
                update.message.reply_text(f"{target_user.mention_markdown_v2()} is now unauthorized.", parse_mode="MarkdownV2")
            except:
                update.message.reply_text("Could not find user.")
        else:
            update.message.reply_text("Reply to a user or provide a username to unauthorize.")
    else:
        update.message.reply_text("Only admins can use the /unauth command.")

# Function to handle the /gauth command (bot owner only)
def gauth(update: Update, context: CallbackContext):
    user = update.message.from_user

    if user.id == BOT_OWNER_ID:
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            gauth_user(target_user.id)
            update.message.reply_text(f"{target_user.mention_markdown_v2()} is now globally authorized.", parse_mode="MarkdownV2")
        elif context.args:
            try:
                target_user = context.bot.get_chat(context.args[0])
                gauth_user(target_user.id)
                update.message.reply_text(f"{target_user.mention_markdown_v2()} is now globally authorized.", parse_mode="MarkdownV2")
            except:
                update.message.reply_text("Could not find user.")
        else:
            update.message.reply_text("Reply to a user or provide a username to globally authorize.")
    else:
        update.message.reply_text("Only the bot owner can use the /gauth command.")

# Function to handle the /ungauth command (bot owner only)
def ungauth(update: Update, context: CallbackContext):
    user = update.message.from_user

    if user.id == BOT_OWNER_ID:
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            ungauth_user(target_user.id)
            update.message.reply_text(f"{target_user.mention_markdown_v2()} is now globally unauthorized.", parse_mode="MarkdownV2")
        elif context.args:
            try:
                target_user = context.bot.get_chat(context.args[0])
                ungauth_user(target_user.id)
                update.message.reply_text(f"{target_user.mention_markdown_v2()} is now globally unauthorized.", parse_mode="MarkdownV2")
            except:
                update.message.reply_text("Could not find user.")
        else:
            update.message.reply_text("Reply to a user or provide a username to globally unauthorize.")
    else:
        update.message.reply_text("Only the bot owner can use the /ungauth command.")

# Function to handle the /authusers command (admin only)
def authusers(update: Update, context: CallbackContext):
    user = update.message.from_user
    chat_id = update.effective_chat.id

    if is_user_admin(chat_id, user.id, context.bot):
        auth_users = authorized_users_collection.find_one({"chat_id": chat_id})
        if auth_users and "users" in auth_users:
            user_mentions = []
            for index, user_id in enumerate(auth_users['users'], 1):
                chat_member = context.bot.get_chat_member(chat_id, user_id)
                user_mentions.append(f"{index}- {chat_member.user.mention_markdown_v2()}")
            update.message.reply_text("\n".join(user_mentions), parse_mode="MarkdownV2")
        else:
            update.message.reply_text("No authorized users in this chat.")
    else:
        update.message.reply_text("Only admins can use the /authusers command.")

# Function to handle the /gauthusers command (bot owner only)
def gauthusers(update: Update, context: CallbackContext):
    user = update.message.from_user

    if user.id == BOT_OWNER_ID:
        global_auth_users = global_authorized_users_collection.find_one({"_id": "global"})
        if global_auth_users and "users" in global_auth_users:
            user_mentions = []
            for index, user_id in enumerate(global_auth_users['users'], 1):
                user_chat = context.bot.get_chat(user_id)
                user_mentions.append(f"{index}- {user_chat.mention_markdown_v2()}")
            update.message.reply_text("\n".join(user_mentions), parse_mode="MarkdownV2")
        else:
            update.message.reply_text("No globally authorized users.")
    else:
        update.message.reply_text("Only the bot owner can use the /gauthusers command.")

# Function to handle the /stats command
def stats(update: Update, context: CallbackContext):
    chat_count = group_chats_collection.count_documents({})
    user_count = bot_stats_collection.count_documents({})
    update.message.reply_text(f"Bot is in {chat_count} group(s) and {user_count} user(s) have interacted with the bot.")

# Function to handle the /broadcast command (bot owner only)
def broadcast(update: Update, context: CallbackContext):
    user = update.message.from_user

    if user.id == BOT_OWNER_ID:
        if context.args:
            message = " ".join(context.args)
            group_chats = group_chats_collection.find()
            users = bot_stats_collection.find()
            for chat in group_chats:
                try:
                    context.bot.send_message(chat_id=chat['_id'], text=message)
                except:
                    continue  # Handle potential failure in group message
            for user in users:
                try:
                    context.bot.send_message(chat_id=user['_id'], text=message)
                except:
                    continue  # Handle potential failure in private message
            update.message.reply_text("Broadcast message sent!")
        else:
            update.message.reply_text("Please provide a message to broadcast.")
    else:
        update.message.reply_text("Only the bot owner can use the /broadcast command.")

# Function to update the bot stats when a user interacts
def update_bot_stats(user_id):
    bot_stats_collection.update_one(
        {"_id": user_id},
        {"$setOnInsert": {"_id": user_id}},
        upsert=True
    )

# Function to handle new chat member updates (bot added to new chat)
def handle_chat_member_update(update: Update, context: CallbackContext):
    if isinstance(update.my_chat_member.new_chat_member, ChatMember):
        if update.my_chat_member.new_chat_member.status in ['administrator', 'member']:
            chat = update.effective_chat
            log_event(context, f"Bot added to a new chat:\n- Chat: {chat.title or chat.first_name}\n- Chat ID: {chat.id}")

# Main function to start the bot
def main():
    updater = Updater(BOT_TOKEN, use_context=True)

    dp = updater.dispatcher

    # Add handlers for the commands and media/sticker messages
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("setdelay", setdelay, Filters.chat_type.groups))
    dp.add_handler(CommandHandler("auth", auth, Filters.chat_type.groups))
    dp.add_handler(CommandHandler("unauth", unauth, Filters.chat_type.groups))
    dp.add_handler(CommandHandler("gauth", gauth))
    dp.add_handler(CommandHandler("ungauth", ungauth))
    dp.add_handler(CommandHandler("authusers", authusers, Filters.chat_type.groups))
    dp.add_handler(CommandHandler("gauthusers", gauthusers))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(MessageHandler(Filters.chat_type.groups & (Filters.photo | Filters.video | Filters.sticker), handle_media_and_stickers))

    # Chat member handler to track when the bot is added to a new group
    dp.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
