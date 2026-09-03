import asyncio
import sqlite3
import re
import os
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, PeerIdInvalid

# ============================================
# CONFIGURATION - Yahan apna data daalein
# ============================================

API_ID = 32141443  # Apna API ID daalein
API_HASH = "4f34a89257ac316505f5a47b237454cc"  # Apna API Hash daalein
SESSION_STRING = "BQCZzqEAgaPva-BCCdfZXTFdBuFymHf78kAFzLGh_lxby6K4iIyXXtmItVIv8VxwyBIlZloGgMh-Rn-GKZifaJ4Ir2gEOuIWjjKQcZKQYLugYXhGfB9Pot0N8aFo7BKwla4sEb_Idues1Q7tXiJwP3yvJlo8W1dfTUSJPP3wdSRMNZs2_IdX8lTTM-2-sbdVRCqbzXM9NPkjw5bgQfw2SQvAVR4MzsP2YietQ47cQqPM8Wa_sYDGvUqPFcZSqSlbcd-EVuq4G_ot3HRX3Lh-8fETwyEvd74j9huZxx--jm508F0tnKVZ7V2og6Kcx1E79kijX9kQzrDTh9B74ZWqm3myOMOQPwAAAAF1XmqZAA"  # Apna Pyrogram Session String daalein

# Bot Token (optional - agar bot commands chahiye toh)
BOT_TOKEN = "8640436717:AAHT6YYX2szV3Q3OUGR2_Wfa2QxAnunjFbE"  # @BotFather se lo

# ============================================
# DATABASE SETUP
# ============================================

conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()

# Groups table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER UNIQUE,
        group_link TEXT,
        group_title TEXT,
        is_private INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Settings table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
""")

# Sent tracking
cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_tracking (
        group_id INTEGER,
        user_id INTEGER,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (group_id, user_id)
    )
""")

# Active users tracking
cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_users (
        user_id INTEGER,
        group_id INTEGER,
        last_seen TIMESTAMP,
        PRIMARY KEY (user_id, group_id)
    )
""")

# Captions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS captions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caption_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

conn.commit()

# Default settings
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('member_limit', '20')")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('delay_seconds', '3')")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_running', 'false')")
conn.commit()

# ============================================
# DATABASE FUNCTIONS
# ============================================

def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    return result[0] if result else None

def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

def add_group(group_id, group_link, is_private=0, title=""):
    cursor.execute("""
        INSERT OR IGNORE INTO groups (group_id, group_link, is_private, group_title)
        VALUES (?, ?, ?, ?)
    """, (group_id, group_link, is_private, title))
    conn.commit()

def remove_group(group_id):
    cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()

def get_all_groups():
    cursor.execute("SELECT * FROM groups")
    return cursor.fetchall()

def get_group_count():
    cursor.execute("SELECT COUNT(*) FROM groups")
    return cursor.fetchone()[0]

def save_caption(caption):
    cursor.execute("DELETE FROM captions")
    cursor.execute("INSERT INTO captions (caption_text) VALUES (?)", (caption,))
    conn.commit()

def get_caption():
    cursor.execute("SELECT caption_text FROM captions ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    return result[0] if result else None

def track_sent(group_id, user_id):
    cursor.execute("""
        INSERT OR REPLACE INTO sent_tracking (group_id, user_id, sent_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (group_id, user_id))
    conn.commit()

def is_already_sent(group_id, user_id):
    cursor.execute("""
        SELECT 1 FROM sent_tracking 
        WHERE group_id = ? AND user_id = ? 
        AND sent_at > datetime('now', '-1 hour')
    """, (group_id, user_id))
    return cursor.fetchone() is not None

def track_active_user(user_id, group_id):
    cursor.execute("""
        INSERT OR REPLACE INTO active_users (user_id, group_id, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (user_id, group_id))
    conn.commit()

def get_active_users(group_id, minutes=30):
    cursor.execute("""
        SELECT user_id FROM active_users 
        WHERE group_id = ? AND last_seen > datetime('now', ?)
    """, (group_id, f'-{minutes} minutes'))
    return [row[0] for row in cursor.fetchall()]

def clear_sent_log():
    cursor.execute("DELETE FROM sent_tracking WHERE sent_at < datetime('now', '-1 day')")
    conn.commit()

# ============================================
# INITIALIZE BOT
# ============================================

app = Client(
    "dm_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ============================================
# COMMAND HANDLERS
# ============================================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "🤖 **DM Bot Active!**\n\n"
        "📌 **Commands:**\n\n"
        "**Group Management:**\n"
        "/addgroup <link> - Add public group\n"
        "/addprivate <id> - Add private group (use chat_id)\n"
        "/removegroup <id> - Remove group\n"
        "/listgroups - Show all groups\n\n"
        "**Message Settings:**\n"
        "/caption <message> - Set DM message\n"
        "/setlimit <number> - Set member limit (10-50)\n"
        "/setdelay <seconds> - Delay between DMs (2-5)\n\n"
        "**Start/Stop:**\n"
        "/forcestart - Start DM campaign\n"
        "/stop - Stop campaign\n"
        "/status - Show current status\n\n"
        "**Example Flow:**\n"
        "1. /addgroup https://t.me/groupname\n"
        "2. /caption Hello! I'm a freelancer...\n"
        "3. /setlimit 20\n"
        "4. /forcestart"
    )

@app.on_message(filters.command("addgroup") & filters.private)
async def add_public_group(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /addgroup https://t.me/groupusername")
            return
        
        link = parts[1].strip()
        
        # Extract username
        match = re.search(r'(?:https?://)?t\.me/([a-zA-Z0-9_]+)', link)
        if not match:
            await message.reply_text("❌ Invalid group link!")
            return
        
        username = match.group(1)
        
        try:
            chat = await client.get_chat(username)
            add_group(chat.id, link, 0, chat.title or username)
            await message.reply_text(
                f"✅ **Group added!**\n"
                f"📌 Title: {chat.title}\n"
                f"🆔 ID: `{chat.id}`\n"
                f"👥 Members: {chat.members_count or 'Unknown'}"
            )
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("addprivate") & filters.private)
async def add_private_group(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /addprivate -100123456789")
            return
        
        chat_id = int(parts[1].strip())
        
        try:
            chat = await client.get_chat(chat_id)
            add_group(chat_id, f"private_{chat_id}", 1, chat.title or "Private Group")
            await message.reply_text(
                f"✅ **Private group added!**\n"
                f"📌 Title: {chat.title}\n"
                f"🆔 ID: `{chat_id}`"
            )
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("removegroup") & filters.private)
async def remove_group_cmd(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /removegroup 123456789")
            return
        
        group_id = int(parts[1].strip())
        remove_group(group_id)
        await message.reply_text("✅ Group removed successfully!")
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("listgroups") & filters.private)
async def list_groups(client, message):
    groups = get_all_groups()
    
    if not groups:
        await message.reply_text("❌ No groups added yet!")
        return
    
    text = "📋 **Added Groups:**\n\n"
    for group in groups:
        status = "🔒 Private" if group[3] else "🌐 Public"
        text += f"• {group[4]} ({status})\n  ID: `{group[1]}`\n\n"
    
    await message.reply_text(text)

@app.on_message(filters.command("caption") & filters.private)
async def set_caption(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /caption Your message here")
            return
        
        caption = parts[1].strip()
        save_caption(caption)
        await message.reply_text(
            f"✅ **Caption set!**\n\n"
            f"📝 {caption}\n\n"
            f"Use /forcestart to begin sending."
        )
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("setlimit") & filters.private)
async def set_limit(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /setlimit 20")
            return
        
        limit = int(parts[1].strip())
        if limit < 1 or limit > 50:
            await message.reply_text("❌ Limit must be between 1 and 50")
            return
        
        set_setting("member_limit", str(limit))
        await message.reply_text(f"✅ Member limit set to: {limit}")
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("setdelay") & filters.private)
async def set_delay(client, message):
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /setdelay 3")
            return
        
        delay = int(parts[1].strip())
        if delay < 1 or delay > 10:
            await message.reply_text("❌ Delay must be between 1 and 10 seconds")
            return
        
        set_setting("delay_seconds", str(delay))
        await message.reply_text(f"✅ Delay set to: {delay} seconds")
        
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("status") & filters.private)
async def show_status(client, message):
    groups = get_all_groups()
    caption = get_caption()
    limit = get_setting("member_limit") or "20"
    delay = get_setting("delay_seconds") or "3"
    running = get_setting("is_running") == "true"
    
    status_text = f"""
📊 **Bot Status**

🔹 **Groups:** {len(groups)}
🔹 **Message:** {caption[:50] + '...' if caption and len(caption) > 50 else caption or 'Not set'}
🔹 **Limit:** {limit} members/group
🔹 **Delay:** {delay} seconds
🔹 **Status:** {'🟢 Running' if running else '🔴 Stopped'}

**Quick Actions:**
/forcestart - Start campaign
/stop - Stop campaign
"""
    await message.reply_text(status_text)

@app.on_message(filters.command("forcestart") & filters.private)
async def force_start(client, message):
    # Check if already running
    if get_setting("is_running") == "true":
        await message.reply_text("⚠️ Campaign already running! Use /stop first.")
        return
    
    # Check caption
    caption = get_caption()
    if not caption:
        await message.reply_text("❌ Please set a caption first using /caption")
        return
    
    # Check groups
    groups = get_all_groups()
    if not groups:
        await message.reply_text("❌ No groups added! Use /addgroup or /addprivate")
        return
    
    set_setting("is_running", "true")
    await message.reply_text(
        f"🚀 **Campaign started!**\n\n"
        f"📝 Message: {caption[:100]}{'...' if len(caption) > 100 else ''}\n"
        f"📊 Groups: {len(groups)}\n"
        f"👥 Limit: {get_setting('member_limit')} members/group\n"
        f"⏱️ Delay: {get_setting('delay_seconds')} seconds\n\n"
        f"⏳ Sending messages... (Check /status for progress)"
    )
    
    # Start DM loop
    asyncio.create_task(dm_loop(client, message.chat.id))

@app.on_message(filters.command("stop") & filters.private)
async def stop_campaign(client, message):
    if get_setting("is_running") != "true":
        await message.reply_text("⚠️ No campaign is currently running!")
        return
    
    set_setting("is_running", "false")
    await message.reply_text("🛑 **Campaign stopped!**")

# ============================================
# TRACK ACTIVE USERS IN GROUPS
# ============================================

@app.on_message(filters.group)
async def track_active(client, message):
    if message.from_user:
        track_active_user(message.from_user.id, message.chat.id)

# ============================================
# DM LOOP ENGINE
# ============================================

async def dm_loop(client, admin_chat_id):
    try:
        groups = get_all_groups()
        caption = get_caption()
        member_limit = int(get_setting("member_limit") or 20)
        delay = int(get_setting("delay_seconds") or 3)
        
        total_sent = 0
        total_failed = 0
        
        for group in groups:
            # Check if stopped
            if get_setting("is_running") != "true":
                break
            
            group_id = group[1]
            group_title = group[4] or "Unknown"
            
            await client.send_message(
                admin_chat_id,
                f"🔄 Processing: {group_title}..."
            )
            
            try:
                # Get active users (last 30 minutes)
                active_users = get_active_users(group_id, minutes=30)
                
                # If no active users, get recent members
                if not active_users:
                    await client.send_message(
                        admin_chat_id,
                        f"⚠️ No active users found in {group_title}. Getting recent members..."
                    )
                    
                    recent_members = []
                    async for member in client.get_chat_members(group_id, limit=member_limit):
                        recent_members.append(member.user.id)
                    
                    users_to_dm = recent_members
                else:
                    users_to_dm = active_users[:member_limit]
                
                sent_count = 0
                failed_count = 0
                
                for user_id in users_to_dm:
                    # Check if stopped
                    if get_setting("is_running") != "true":
                        break
                    
                    # Skip if already sent recently
                    if is_already_sent(group_id, user_id):
                        continue
                    
                    # Try to send message
                    try:
                        await client.send_message(user_id, caption)
                        track_sent(group_id, user_id)
                        sent_count += 1
                        total_sent += 1
                        
                        # Progress update every 5 messages
                        if total_sent % 5 == 0:
                            await client.send_message(
                                admin_chat_id,
                                f"📊 Progress: {total_sent} DMs sent so far..."
                            )
                            
                    except FloodWait as e:
                        await client.send_message(
                            admin_chat_id,
                            f"⏳ Flood wait: {e.x} seconds. Pausing..."
                        )
                        await asyncio.sleep(e.x)
                        
                    except PeerIdInvalid:
                        failed_count += 1
                        total_failed += 1
                        
                    except Exception as e:
                        failed_count += 1
                        total_failed += 1
                        print(f"Error sending to {user_id}: {e}")
                    
                    # Delay between messages
                    await asyncio.sleep(delay)
                
                await client.send_message(
                    admin_chat_id,
                    f"✅ {group_title}: Sent {sent_count} DMs, Failed {failed_count}"
                )
                
                # Clear old sent logs to free space
                clear_sent_log()
                
            except Exception as e:
                await client.send_message(
                    admin_chat_id,
                    f"❌ Error in {group_title}: {e}"
                )
                continue
        
        # Campaign completed
        set_setting("is_running", "false")
        await client.send_message(
            admin_chat_id,
            f"✅ **Campaign completed!**\n\n"
            f"📊 Total DMs sent: {total_sent}\n"
            f"❌ Total failed: {total_failed}\n"
            f"📋 Groups processed: {len(groups)}"
        )
        
    except Exception as e:
        set_setting("is_running", "false")
        await client.send_message(admin_chat_id, f"❌ Campaign stopped due to error: {e}")

# ============================================
# RUN BOT
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 DM Bot Starting...")
    print("=" * 50)
    
    # Check configuration
    if API_ID == 1234567 or API_HASH == "your_api_hash_here":
        print("❌ ERROR: Please update API_ID and API_HASH in the code!")
        exit(1)
    
    if SESSION_STRING == "your_session_string_here":
        print("❌ ERROR: Please update SESSION_STRING in the code!")
        exit(1)
    
    print("✅ Configuration loaded!")
    print(f"📊 Groups in database: {get_group_count()}")
    print("🚀 Starting bot...")
    
    app.run()
    
    print("👋 Bot stopped!")
