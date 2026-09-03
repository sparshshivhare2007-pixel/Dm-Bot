import asyncio
import sqlite3
import re
import logging
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, PeerIdInvalidError, RPCError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsRecent
from telethon.sessions import StringSession

# ============================================
# LOGGING SETUP
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print("=" * 60)
print("🤖 Telethon DM Bot (With /connect Session)")
print("=" * 60)

# ============================================
# CONFIGURATION - BOT TOKEN
# ============================================

API_ID = 32141443
API_HASH = "4f34a89257ac316505f5a47b237454cc"
BOT_TOKEN = "8640436717:AAHT6YYX2szV3Q3OUGR2_Wfa2QxAnunjFbE"

# ============================================
# DATABASE SETUP - RESET DATABASE
# ============================================

# Delete old database to start fresh
if os.path.exists("bot_data.db"):
    os.remove("bot_data.db")
    print("🗑️ Old database deleted!")

print("🔍 Creating fresh database...")
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()

# Groups table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        group_id INTEGER UNIQUE,
        group_link TEXT,
        group_title TEXT,
        is_private INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# User sessions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        user_id INTEGER PRIMARY KEY,
        session_string TEXT,
        phone TEXT,
        connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Settings table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER,
        key TEXT,
        value TEXT,
        PRIMARY KEY (user_id, key)
    )
""")

# Sent tracking
cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_tracking (
        user_id INTEGER,
        group_id INTEGER,
        target_user_id INTEGER,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, group_id, target_user_id)
    )
""")

# Active users tracking
cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_users (
        user_id INTEGER,
        group_id INTEGER,
        target_user_id INTEGER,
        last_seen TIMESTAMP,
        PRIMARY KEY (user_id, group_id, target_user_id)
    )
""")

# Captions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS captions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        caption_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

conn.commit()
print("✅ Fresh database created!")

# ============================================
# DATABASE FUNCTIONS
# ============================================

def get_setting(user_id, key):
    cursor.execute("SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key))
    result = cursor.fetchone()
    return result[0] if result else None

def set_setting(user_id, key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (user_id, key, value) VALUES (?, ?, ?)", (user_id, key, value))
    conn.commit()

def save_user_session(user_id, session_string, phone=""):
    cursor.execute("INSERT OR REPLACE INTO user_sessions (user_id, session_string, phone) VALUES (?, ?, ?)", 
                   (user_id, session_string, phone))
    conn.commit()

def get_user_session(user_id):
    cursor.execute("SELECT session_string FROM user_sessions WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def get_all_user_sessions():
    cursor.execute("SELECT user_id, session_string FROM user_sessions")
    return cursor.fetchall()

def add_group(user_id, group_id, group_link, is_private=0, title=""):
    cursor.execute("""
        INSERT OR IGNORE INTO groups (user_id, group_id, group_link, is_private, group_title)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, group_id, group_link, is_private, title))
    conn.commit()
    print(f"✅ Group added: {title} (ID: {group_id}) for user {user_id}")

def get_user_groups(user_id):
    cursor.execute("SELECT * FROM groups WHERE user_id = ?", (user_id,))
    return cursor.fetchall()

def remove_group(user_id, group_id):
    cursor.execute("DELETE FROM groups WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    conn.commit()

def save_caption(user_id, caption):
    cursor.execute("DELETE FROM captions WHERE user_id = ?", (user_id,))
    cursor.execute("INSERT INTO captions (user_id, caption_text) VALUES (?, ?)", (user_id, caption))
    conn.commit()

def get_caption(user_id):
    cursor.execute("SELECT caption_text FROM captions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

def track_sent(user_id, group_id, target_user_id):
    cursor.execute("""
        INSERT OR REPLACE INTO sent_tracking (user_id, group_id, target_user_id, sent_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, group_id, target_user_id))
    conn.commit()

def is_already_sent(user_id, group_id, target_user_id):
    cursor.execute("""
        SELECT 1 FROM sent_tracking 
        WHERE user_id = ? AND group_id = ? AND target_user_id = ?
        AND sent_at > datetime('now', '-1 hour')
    """, (user_id, group_id, target_user_id))
    return cursor.fetchone() is not None

def track_active_user(user_id, group_id, target_user_id):
    cursor.execute("""
        INSERT OR REPLACE INTO active_users (user_id, group_id, target_user_id, last_seen)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, group_id, target_user_id))
    conn.commit()

def get_active_users(user_id, group_id, minutes=30):
    cursor.execute("""
        SELECT target_user_id FROM active_users 
        WHERE user_id = ? AND group_id = ? AND last_seen > datetime('now', ?)
    """, (user_id, group_id, f'-{minutes} minutes'))
    return [row[0] for row in cursor.fetchall()]

# ============================================
# INITIALIZE BOT
# ============================================

print("🔍 Initializing Telethon Bot...")

bot = TelegramClient(
    'dm_bot_session',
    api_id=API_ID,
    api_hash=API_HASH
)

print("✅ Bot client created!")

# User clients dictionary
user_clients = {}

# ============================================
# CREATE USER CLIENT WITH SESSION STRING
# ============================================

async def create_user_client(user_id, session_string):
    """Create a TelegramClient with session string"""
    try:
        session = StringSession(session_string)
        client = TelegramClient(
            session,
            api_id=API_ID,
            api_hash=API_HASH
        )
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return None
        
        return client
    except Exception as e:
        print(f"Error creating client: {e}")
        return None

# ============================================
# COMMAND HANDLERS
# ============================================

@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    if event.is_private:
        user_id = event.sender_id
        session = get_user_session(user_id)
        status = "🟢 Connected" if session else "🔴 Not connected"
        
        await event.reply(
            f"🤖 **DM Bot Active!**\n\n"
            f"🔹 **Session Status:** {status}\n\n"
            "📌 **Commands:**\n\n"
            "**Session Management:**\n"
            "/connect <session_string> - Connect your Telethon session\n"
            "/disconnect - Disconnect your session\n"
            "/session_status - Check session status\n\n"
            "**Group Management:**\n"
            "/addgroup <link> - Add public group\n"
            "/addprivate <chat_id> - Add private group (use chat_id)\n"
            "/addprivatelink <link> <chat_id> - Add private group with link\n"
            "/removegroup <id> - Remove group\n"
            "/listgroups - Show all groups\n\n"
            "**Message Settings:**\n"
            "/caption <message> - Set DM message\n"
            "/setlimit <number> - Set member limit (10-50)\n"
            "/setdelay <seconds> - Delay between DMs (2-5)\n\n"
            "**Start/Stop:**\n"
            "/forcestart - Start DM campaign\n"
            "/stop - Stop campaign\n"
            "/status - Show current status\n"
            "/test - Test if bot is working\n\n"
            "**How to get chat_id:**\n"
            "1. Add @getidsbot to your group\n"
            "2. Send /getid in group\n"
            "3. Copy the chat_id (starts with -100)"
        )

@bot.on(events.NewMessage(pattern='/test'))
async def test_command(event):
    if event.is_private:
        await event.reply("✅ **Bot is working!** Test successful! 🎉")

@bot.on(events.NewMessage(pattern='/connect'))
async def connect_session(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply(
                "❌ **Usage:** /connect <session_string>\n\n"
                "**How to get session string:**\n"
                "```python\n"
                "from telethon import TelegramClient\n"
                "client = TelegramClient('session', API_ID, API_HASH)\n"
                "await client.start()\n"
                "print(client.session.save())\n"
                "```\n"
                "Copy the string and paste here."
            )
            return
        
        session_string = parts[1].strip()
        
        await event.reply("⏳ Testing session... Please wait.")
        
        try:
            test_session = StringSession(session_string)
            test_client = TelegramClient(
                test_session,
                api_id=API_ID,
                api_hash=API_HASH
            )
            await test_client.connect()
            
            if not await test_client.is_user_authorized():
                await test_client.disconnect()
                await event.reply("❌ **Invalid session!** Session is not authorized.")
                return
            
            me = await test_client.get_me()
            await test_client.disconnect()
            
            save_user_session(user_id, session_string, me.phone)
            
            if user_id in user_clients:
                try:
                    await user_clients[user_id].disconnect()
                except:
                    pass
            
            client = await create_user_client(user_id, session_string)
            if client:
                user_clients[user_id] = client
            
            await event.reply(
                f"✅ **Session connected!**\n\n"
                f"📱 Phone: {me.phone}\n"
                f"👤 Name: {me.first_name}\n"
                f"🆔 ID: {me.id}\n\n"
                f"Now you can add groups and start campaigns!"
            )
            
        except Exception as e:
            await event.reply(f"❌ **Invalid session!**\n\nError: {e}\n\nPlease check your session string.")
            
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/disconnect'))
async def disconnect_session(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    if user_id in user_clients:
        try:
            await user_clients[user_id].disconnect()
        except:
            pass
        del user_clients[user_id]
    
    cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    
    await event.reply("✅ **Session disconnected!**")

@bot.on(events.NewMessage(pattern='/session_status'))
async def session_status(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    session = get_user_session(user_id)
    
    if session:
        await event.reply("✅ **Session is connected!**")
    else:
        await event.reply("❌ **No session connected!**\n\nUse /connect to connect your session.")

@bot.on(events.NewMessage(pattern='/addgroup'))
async def add_public_group(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    session = get_user_session(user_id)
    if not session:
        await event.reply("❌ **Connect session first!**\n\nUse /connect <session_string>")
        return
    
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply("❌ Usage: /addgroup https://t.me/groupusername")
            return
        
        link = parts[1].strip()
        match = re.search(r'(?:https?://)?t\.me/([a-zA-Z0-9_]+)', link)
        if not match:
            await event.reply("❌ Invalid group link!")
            return
        
        username = match.group(1)
        
        if user_id not in user_clients:
            client = await create_user_client(user_id, session)
            if not client:
                await event.reply("❌ Failed to create client. Please reconnect.")
                return
            user_clients[user_id] = client
        
        try:
            client = user_clients[user_id]
            
            entity = await client.get_entity(f"@{username}")
            title = getattr(entity, 'title', username)
            
            add_group(user_id, entity.id, link, 0, title)
            
            await event.reply(
                f"✅ **Group added!**\n"
                f"📌 Title: {title}\n"
                f"🆔 ID: `{entity.id}`"
            )
            
        except Exception as e:
            await event.reply(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/addprivate'))
async def add_private_group(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    session = get_user_session(user_id)
    if not session:
        await event.reply("❌ **Connect session first!**\n\nUse /connect <session_string>")
        return
    
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply(
                "❌ Usage: /addprivate <chat_id>\n\n"
                "**How to get chat_id:**\n"
                "1. Add @getidsbot to your group\n"
                "2. Send /getid in group\n"
                "3. Copy the chat_id (starts with -100)\n\n"
                "**Example:** /addprivate -1001698843821"
            )
            return
        
        chat_id_str = parts[1].strip()
        
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            await event.reply(f"❌ Invalid chat_id: {chat_id_str}\n\nPlease use numeric chat_id like -1001698843821")
            return
        
        if user_id not in user_clients:
            client = await create_user_client(user_id, session)
            if not client:
                await event.reply("❌ Failed to create client. Please reconnect.")
                return
            user_clients[user_id] = client
        
        try:
            client = user_clients[user_id]
            
            entity = await client.get_entity(chat_id)
            title = getattr(entity, 'title', "Private Group")
            
            add_group(user_id, chat_id, f"private_{chat_id}", 1, title)
            
            await event.reply(
                f"✅ **Private group added!**\n"
                f"📌 Title: {title}\n"
                f"🆔 ID: `{chat_id}`"
            )
            
        except Exception as e:
            await event.reply(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/addprivatelink'))
async def add_private_group_with_link(event):
    """Add private group with link and chat_id"""
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    session = get_user_session(user_id)
    if not session:
        await event.reply("❌ **Connect session first!**\n\nUse /connect <session_string>")
        return
    
    try:
        parts = event.raw_text.split(" ", 2)
        if len(parts) < 3:
            await event.reply(
                "❌ Usage: /addprivatelink <group_link> <chat_id>\n\n"
                "**Example:** /addprivatelink https://t.me/+IP5pMoioYpw1YTll -1001698843821"
            )
            return
        
        link = parts[1].strip()
        chat_id = int(parts[2].strip())
        
        if user_id not in user_clients:
            client = await create_user_client(user_id, session)
            if not client:
                await event.reply("❌ Failed to create client. Please reconnect.")
                return
            user_clients[user_id] = client
        
        try:
            client = user_clients[user_id]
            
            entity = await client.get_entity(chat_id)
            title = getattr(entity, 'title', "Private Group")
            
            add_group(user_id, chat_id, link, 1, title)
            
            await event.reply(
                f"✅ **Private group added!**\n"
                f"📌 Title: {title}\n"
                f"🆔 ID: `{chat_id}`\n"
                f"🔗 Link: {link}"
            )
            
        except Exception as e:
            await event.reply(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/removegroup'))
async def remove_group_cmd(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply("❌ Usage: /removegroup 123456789")
            return
        
        group_id = int(parts[1].strip())
        remove_group(user_id, group_id)
        await event.reply("✅ Group removed successfully!")
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/listgroups'))
async def list_groups(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        groups = get_user_groups(user_id)
        
        if not groups:
            await event.reply("❌ No groups added yet!")
            return
        
        text = "📋 **Added Groups:**\n\n"
        for group in groups:
            status = "🔒 Private" if group[4] else "🌐 Public"
            text += f"• {group[5]} ({status})\n  ID: `{group[2]}`\n\n"
        
        await event.reply(text)
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/caption'))
async def set_caption(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply("❌ Usage: /caption Your message here")
            return
        
        caption = parts[1].strip()
        save_caption(user_id, caption)
        
        await event.reply(
            f"✅ **Caption set!**\n\n"
            f"📝 {caption[:200]}{'...' if len(caption) > 200 else ''}\n\n"
            f"Use /forcestart to begin sending."
        )
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/setlimit'))
async def set_limit(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply("❌ Usage: /setlimit 20")
            return
        
        limit = int(parts[1].strip())
        if limit < 1 or limit > 50:
            await event.reply("❌ Limit must be between 1 and 50")
            return
        
        set_setting(user_id, "member_limit", str(limit))
        await event.reply(f"✅ Member limit set to: {limit}")
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/setdelay'))
async def set_delay(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            await event.reply("❌ Usage: /setdelay 3")
            return
        
        delay = int(parts[1].strip())
        if delay < 1 or delay > 10:
            await event.reply("❌ Delay must be between 1 and 10 seconds")
            return
        
        set_setting(user_id, "delay_seconds", str(delay))
        await event.reply(f"✅ Delay set to: {delay} seconds")
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/status'))
async def show_status(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        groups = get_user_groups(user_id)
        caption = get_caption(user_id)
        limit = get_setting(user_id, "member_limit") or "20"
        delay = get_setting(user_id, "delay_seconds") or "3"
        running = get_setting(user_id, "is_running") == "true"
        session = get_user_session(user_id)
        
        status_text = f"""
📊 **Bot Status**

🔹 **Session:** {'🟢 Connected' if session else '🔴 Not connected'}
🔹 **Groups:** {len(groups)}
🔹 **Message:** {caption[:50] + '...' if caption and len(caption) > 50 else caption or 'Not set'}
🔹 **Limit:** {limit} members/group
🔹 **Delay:** {delay} seconds
🔹 **Status:** {'🟢 Running' if running else '🔴 Stopped'}

**Quick Actions:**
/forcestart - Start campaign
/stop - Stop campaign
"""
        await event.reply(status_text)
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/forcestart'))
async def force_start(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    
    session = get_user_session(user_id)
    if not session:
        await event.reply("❌ **Connect session first!**\n\nUse /connect <session_string>")
        return
    
    try:
        if get_setting(user_id, "is_running") == "true":
            await event.reply("⚠️ Campaign already running! Use /stop first.")
            return
        
        caption = get_caption(user_id)
        if not caption:
            await event.reply("❌ Please set a caption first using /caption")
            return
        
        groups = get_user_groups(user_id)
        if not groups:
            await event.reply("❌ No groups added! Use /addgroup or /addprivate")
            return
        
        set_setting(user_id, "is_running", "true")
        
        await event.reply(
            f"🚀 **Campaign started!**\n\n"
            f"📝 Message: {caption[:100]}{'...' if len(caption) > 100 else ''}\n"
            f"📊 Groups: {len(groups)}\n"
            f"👥 Limit: {get_setting(user_id, 'member_limit') or '20'} members/group\n"
            f"⏱️ Delay: {get_setting(user_id, 'delay_seconds') or '3'} seconds\n\n"
            f"⏳ Sending messages..."
        )
        
        asyncio.create_task(dm_loop(user_id, event.sender_id))
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

@bot.on(events.NewMessage(pattern='/stop'))
async def stop_campaign(event):
    if not event.is_private:
        return
    
    user_id = event.sender_id
    try:
        if get_setting(user_id, "is_running") != "true":
            await event.reply("⚠️ No campaign is currently running!")
            return
        
        set_setting(user_id, "is_running", "false")
        await event.reply("🛑 **Campaign stopped!**")
        
    except Exception as e:
        await event.reply(f"❌ Error: {e}")

# ============================================
# TRACK ACTIVE USERS
# ============================================

@bot.on(events.NewMessage())
async def track_active(event):
    try:
        if event.is_group and event.sender_id:
            sessions = get_all_user_sessions()
            for user_id, _ in sessions:
                track_active_user(user_id, event.chat_id, event.sender_id)
    except Exception as e:
        pass

# ============================================
# DM LOOP ENGINE
# ============================================

async def dm_loop(user_id, admin_chat_id):
    print(f"🚀 DM Loop started for user {user_id}")
    
    session = get_user_session(user_id)
    if not session:
        return
    
    if user_id not in user_clients:
        client = await create_user_client(user_id, session)
        if not client:
            await bot.send_message(admin_chat_id, "❌ Failed to create client. Please reconnect.")
            return
        user_clients[user_id] = client
    
    try:
        client = user_clients[user_id]
        
        groups = get_user_groups(user_id)
        caption = get_caption(user_id)
        member_limit = int(get_setting(user_id, "member_limit") or 20)
        delay = int(get_setting(user_id, "delay_seconds") or 3)
        
        total_sent = 0
        total_failed = 0
        
        for group in groups:
            if get_setting(user_id, "is_running") != "true":
                print(f"⏹️ Campaign stopped for user {user_id}")
                break
            
            group_id = group[2]
            group_title = group[5] or "Unknown"
            
            await bot.send_message(admin_chat_id, f"🔄 Processing: {group_title}...")
            print(f"🔄 Processing {group_title}")
            
            try:
                active_users = get_active_users(user_id, group_id, minutes=30)
                print(f"🔍 Active users: {len(active_users)}")
                
                if not active_users:
                    await bot.send_message(
                        admin_chat_id,
                        f"⚠️ No active users found in {group_title}. Getting members..."
                    )
                    
                    try:
                        entity = await client.get_entity(group_id)
                        members = []
                        async for participant in client.iter_participants(entity, limit=member_limit):
                            if not participant.bot:
                                members.append(participant.id)
                        users_to_dm = members
                        print(f"🔍 Found {len(users_to_dm)} members")
                    except Exception as e:
                        print(f"❌ Error getting members: {e}")
                        await bot.send_message(
                            admin_chat_id,
                            f"⚠️ Could not get members for {group_title}"
                        )
                        continue
                else:
                    users_to_dm = active_users[:member_limit]
                    print(f"🔍 Will DM {len(users_to_dm)} users")
                
                sent_count = 0
                failed_count = 0
                
                for target_user_id in users_to_dm:
                    if get_setting(user_id, "is_running") != "true":
                        break
                    
                    if is_already_sent(user_id, group_id, target_user_id):
                        print(f"⏭️ Already sent to {target_user_id}")
                        continue
                    
                    try:
                        print(f"📤 Sending to {target_user_id}")
                        await client.send_message(target_user_id, caption)
                        track_sent(user_id, group_id, target_user_id)
                        sent_count += 1
                        total_sent += 1
                        print(f"✅ Sent to {target_user_id} (Total: {total_sent})")
                        
                        if total_sent % 5 == 0:
                            await bot.send_message(
                                admin_chat_id,
                                f"📊 Progress: {total_sent} DMs sent so far..."
                            )
                            
                    except FloodWaitError as e:
                        print(f"⏳ Flood wait: {e.seconds}s")
                        await bot.send_message(
                            admin_chat_id,
                            f"⏳ Flood wait: {e.seconds} seconds. Pausing..."
                        )
                        await asyncio.sleep(e.seconds)
                        
                    except PeerIdInvalidError:
                        failed_count += 1
                        total_failed += 1
                        print(f"❌ PeerIdInvalid for {target_user_id}")
                        
                    except Exception as e:
                        failed_count += 1
                        total_failed += 1
                        print(f"❌ Error: {e}")
                    
                    await asyncio.sleep(delay)
                
                await bot.send_message(
                    admin_chat_id,
                    f"✅ {group_title}: Sent {sent_count}, Failed {failed_count}"
                )
                
            except Exception as e:
                print(f"❌ Error in {group_title}: {e}")
                await bot.send_message(
                    admin_chat_id,
                    f"❌ Error in {group_title}: {e}"
                )
                continue
        
        set_setting(user_id, "is_running", "false")
        await bot.send_message(
            admin_chat_id,
            f"✅ **Campaign completed!**\n\n"
            f"📊 Total DMs sent: {total_sent}\n"
            f"❌ Total failed: {total_failed}"
        )
        print(f"✅ Campaign completed for user {user_id}!")
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        set_setting(user_id, "is_running", "false")
        await bot.send_message(admin_chat_id, f"❌ Error: {e}")

# ============================================
# RUN BOT
# ============================================

async def main():
    print("=" * 60)
    print("🤖 Telethon DM Bot with /connect Session (FIXED)")
    print("=" * 60)
    print(f"🔍 Bot Token: {BOT_TOKEN[:15]}...")
    print("=" * 60)
    
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Bot started!")
    
    me = await bot.get_me()
    print(f"✅ Logged in as: {me.first_name} (@{me.username})")
    print("=" * 60)
    print("🚀 Bot is running! Send /connect to add your session")
    print("=" * 60)
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
