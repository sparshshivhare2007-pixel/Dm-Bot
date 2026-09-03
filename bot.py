import asyncio
import sqlite3
import re
import os
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, PeerIdInvalid

# ============================================
# CONFIGURATION
# ============================================

API_ID = 32141443
API_HASH = "4f34a89257ac316505f5a47b237454cc"
SESSION_STRING = "BQCZzqEAgaPva-BCCdfZXTFdBuFymHf78kAFzLGh_lxby6K4iIyXXtmItVIv8VxwyBIlZloGgMh-Rn-GKZifaJ4Ir2gEOuIWjjKQcZKQYLugYXhGfB9Pot0N8aFo7BKwla4sEb_Idues1Q7tXiJwP3yvJlo8W1dfTUSJPP3wdSRMNZs2_IdX8lTTM-2-sbdVRCqbzXM9NPkjw5bgQfw2SQvAVR4MzsP2YietQ47cQqPM8Wa_sYDGvUqPFcZSqSlbcd-EVuq4G_ot3HRX3Lh-8fETwyEvd74j9huZxx--jm508F0tnKVZ7V2og6Kcx1E79kijX9kQzrDTh9B74ZWqm3myOMOQPwAAAAF1XmqZAA"
BOT_TOKEN = "8640436717:AAHT6YYX2szV3Q3OUGR2_Wfa2QxAnunjFbE"

# ============================================
# DATABASE SETUP
# ============================================

print("🔍 [DEBUG] Initializing database...")
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
print("✅ [DEBUG] Database initialized successfully!")

# Default settings
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('member_limit', '20')")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('delay_seconds', '3')")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_running', 'false')")
conn.commit()
print("✅ [DEBUG] Default settings set!")

# ============================================
# DATABASE FUNCTIONS
# ============================================

def get_setting(key):
    print(f"🔍 [DEBUG] get_setting: {key}")
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    print(f"🔍 [DEBUG] get_setting result: {result[0] if result else None}")
    return result[0] if result else None

def set_setting(key, value):
    print(f"🔍 [DEBUG] set_setting: {key} = {value}")
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    print(f"✅ [DEBUG] Setting saved!")

def add_group(group_id, group_link, is_private=0, title=""):
    print(f"🔍 [DEBUG] add_group: {group_id}, {group_link}, {is_private}, {title}")
    cursor.execute("""
        INSERT OR IGNORE INTO groups (group_id, group_link, is_private, group_title)
        VALUES (?, ?, ?, ?)
    """, (group_id, group_link, is_private, title))
    conn.commit()
    print(f"✅ [DEBUG] Group added!")

def remove_group(group_id):
    print(f"🔍 [DEBUG] remove_group: {group_id}")
    cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()
    print(f"✅ [DEBUG] Group removed!")

def get_all_groups():
    print(f"🔍 [DEBUG] get_all_groups called")
    cursor.execute("SELECT * FROM groups")
    result = cursor.fetchall()
    print(f"🔍 [DEBUG] Found {len(result)} groups")
    return result

def get_group_count():
    cursor.execute("SELECT COUNT(*) FROM groups")
    result = cursor.fetchone()[0]
    print(f"🔍 [DEBUG] Group count: {result}")
    return result

def save_caption(caption):
    print(f"🔍 [DEBUG] save_caption: {caption[:50]}...")
    cursor.execute("DELETE FROM captions")
    cursor.execute("INSERT INTO captions (caption_text) VALUES (?)", (caption,))
    conn.commit()
    print(f"✅ [DEBUG] Caption saved!")

def get_caption():
    print(f"🔍 [DEBUG] get_caption called")
    cursor.execute("SELECT caption_text FROM captions ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    print(f"🔍 [DEBUG] Caption found: {result[0] if result else None}")
    return result[0] if result else None

def track_sent(group_id, user_id):
    print(f"🔍 [DEBUG] track_sent: group={group_id}, user={user_id}")
    cursor.execute("""
        INSERT OR REPLACE INTO sent_tracking (group_id, user_id, sent_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (group_id, user_id))
    conn.commit()
    print(f"✅ [DEBUG] Sent tracked!")

def is_already_sent(group_id, user_id):
    cursor.execute("""
        SELECT 1 FROM sent_tracking 
        WHERE group_id = ? AND user_id = ? 
        AND sent_at > datetime('now', '-1 hour')
    """, (group_id, user_id))
    result = cursor.fetchone() is not None
    print(f"🔍 [DEBUG] is_already_sent: {result}")
    return result

def track_active_user(user_id, group_id):
    print(f"🔍 [DEBUG] track_active_user: user={user_id}, group={group_id}")
    cursor.execute("""
        INSERT OR REPLACE INTO active_users (user_id, group_id, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (user_id, group_id))
    conn.commit()
    print(f"✅ [DEBUG] Active user tracked!")

def get_active_users(group_id, minutes=30):
    print(f"🔍 [DEBUG] get_active_users: group={group_id}, minutes={minutes}")
    cursor.execute("""
        SELECT user_id FROM active_users 
        WHERE group_id = ? AND last_seen > datetime('now', ?)
    """, (group_id, f'-{minutes} minutes'))
    result = [row[0] for row in cursor.fetchall()]
    print(f"🔍 [DEBUG] Found {len(result)} active users")
    return result

def clear_sent_log():
    print(f"🔍 [DEBUG] clear_sent_log called")
    cursor.execute("DELETE FROM sent_tracking WHERE sent_at < datetime('now', '-1 day')")
    conn.commit()
    print(f"✅ [DEBUG] Old sent logs cleared!")

# ============================================
# INITIALIZE BOT
# ============================================

print("🔍 [DEBUG] Initializing Pyrogram Client...")
app = Client(
    "dm_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)
print("✅ [DEBUG] Client initialized!")

# ============================================
# COMMAND HANDLERS
# ============================================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    print(f"🔍 [DEBUG] START command received from {message.from_user.id}")
    try:
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
        print(f"✅ [DEBUG] Start reply sent to {message.from_user.id}")
    except Exception as e:
        print(f"❌ [DEBUG] Error in start_command: {e}")

@app.on_message(filters.command("addgroup") & filters.private)
async def add_public_group(client, message):
    print(f"🔍 [DEBUG] ADDGROUP command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /addgroup https://t.me/groupusername")
            print(f"❌ [DEBUG] No link provided")
            return
        
        link = parts[1].strip()
        print(f"🔍 [DEBUG] Group link: {link}")
        
        # Extract username
        match = re.search(r'(?:https?://)?t\.me/([a-zA-Z0-9_]+)', link)
        if not match:
            await message.reply_text("❌ Invalid group link!")
            print(f"❌ [DEBUG] Invalid link format")
            return
        
        username = match.group(1)
        print(f"🔍 [DEBUG] Username: {username}")
        
        try:
            print(f"🔍 [DEBUG] Getting chat info...")
            chat = await client.get_chat(username)
            print(f"✅ [DEBUG] Chat found: {chat.title}, ID: {chat.id}")
            
            add_group(chat.id, link, 0, chat.title or username)
            
            await message.reply_text(
                f"✅ **Group added!**\n"
                f"📌 Title: {chat.title}\n"
                f"🆔 ID: `{chat.id}`\n"
                f"👥 Members: {chat.members_count or 'Unknown'}"
            )
            print(f"✅ [DEBUG] Group added successfully!")
            
        except Exception as e:
            print(f"❌ [DEBUG] Error getting chat: {e}")
            await message.reply_text(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        print(f"❌ [DEBUG] Error in addgroup: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("addprivate") & filters.private)
async def add_private_group(client, message):
    print(f"🔍 [DEBUG] ADDPRIVATE command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /addprivate -100123456789")
            return
        
        chat_id = int(parts[1].strip())
        print(f"🔍 [DEBUG] Chat ID: {chat_id}")
        
        try:
            chat = await client.get_chat(chat_id)
            print(f"✅ [DEBUG] Chat found: {chat.title}")
            
            add_group(chat_id, f"private_{chat_id}", 1, chat.title or "Private Group")
            
            await message.reply_text(
                f"✅ **Private group added!**\n"
                f"📌 Title: {chat.title}\n"
                f"🆔 ID: `{chat_id}`"
            )
            print(f"✅ [DEBUG] Private group added!")
            
        except Exception as e:
            print(f"❌ [DEBUG] Error: {e}")
            await message.reply_text(f"❌ Error: {e}\n\nMake sure you're a member of this group.")
            
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("removegroup") & filters.private)
async def remove_group_cmd(client, message):
    print(f"🔍 [DEBUG] REMOVEGROUP command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /removegroup 123456789")
            return
        
        group_id = int(parts[1].strip())
        print(f"🔍 [DEBUG] Removing group: {group_id}")
        
        remove_group(group_id)
        await message.reply_text("✅ Group removed successfully!")
        print(f"✅ [DEBUG] Group removed!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("listgroups") & filters.private)
async def list_groups(client, message):
    print(f"🔍 [DEBUG] LISTGROUPS command received from {message.from_user.id}")
    try:
        groups = get_all_groups()
        
        if not groups:
            await message.reply_text("❌ No groups added yet!")
            print(f"🔍 [DEBUG] No groups found")
            return
        
        text = "📋 **Added Groups:**\n\n"
        for group in groups:
            status = "🔒 Private" if group[3] else "🌐 Public"
            text += f"• {group[4]} ({status})\n  ID: `{group[1]}`\n\n"
        
        await message.reply_text(text)
        print(f"✅ [DEBUG] Listed {len(groups)} groups")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("caption") & filters.private)
async def set_caption(client, message):
    print(f"🔍 [DEBUG] CAPTION command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /caption Your message here")
            return
        
        caption = parts[1].strip()
        print(f"🔍 [DEBUG] Caption: {caption[:50]}...")
        
        save_caption(caption)
        
        await message.reply_text(
            f"✅ **Caption set!**\n\n"
            f"📝 {caption}\n\n"
            f"Use /forcestart to begin sending."
        )
        print(f"✅ [DEBUG] Caption saved!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("setlimit") & filters.private)
async def set_limit(client, message):
    print(f"🔍 [DEBUG] SETLIMIT command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /setlimit 20")
            return
        
        limit = int(parts[1].strip())
        print(f"🔍 [DEBUG] Limit: {limit}")
        
        if limit < 1 or limit > 50:
            await message.reply_text("❌ Limit must be between 1 and 50")
            return
        
        set_setting("member_limit", str(limit))
        await message.reply_text(f"✅ Member limit set to: {limit}")
        print(f"✅ [DEBUG] Limit set!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("setdelay") & filters.private)
async def set_delay(client, message):
    print(f"🔍 [DEBUG] SETDELAY command received from {message.from_user.id}")
    try:
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            await message.reply_text("❌ Usage: /setdelay 3")
            return
        
        delay = int(parts[1].strip())
        print(f"🔍 [DEBUG] Delay: {delay}")
        
        if delay < 1 or delay > 10:
            await message.reply_text("❌ Delay must be between 1 and 10 seconds")
            return
        
        set_setting("delay_seconds", str(delay))
        await message.reply_text(f"✅ Delay set to: {delay} seconds")
        print(f"✅ [DEBUG] Delay set!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("status") & filters.private)
async def show_status(client, message):
    print(f"🔍 [DEBUG] STATUS command received from {message.from_user.id}")
    try:
        groups = get_all_groups()
        caption = get_caption()
        limit = get_setting("member_limit") or "20"
        delay = get_setting("delay_seconds") or "3"
        running = get_setting("is_running") == "true"
        
        print(f"🔍 [DEBUG] Status: groups={len(groups)}, running={running}")
        
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
        print(f"✅ [DEBUG] Status sent!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("forcestart") & filters.private)
async def force_start(client, message):
    print(f"🔍 [DEBUG] FORCESTART command received from {message.from_user.id}")
    try:
        # Check if already running
        if get_setting("is_running") == "true":
            await message.reply_text("⚠️ Campaign already running! Use /stop first.")
            print(f"⚠️ [DEBUG] Already running")
            return
        
        # Check caption
        caption = get_caption()
        if not caption:
            await message.reply_text("❌ Please set a caption first using /caption")
            print(f"❌ [DEBUG] No caption set")
            return
        
        # Check groups
        groups = get_all_groups()
        if not groups:
            await message.reply_text("❌ No groups added! Use /addgroup or /addprivate")
            print(f"❌ [DEBUG] No groups added")
            return
        
        set_setting("is_running", "true")
        print(f"✅ [DEBUG] Campaign started!")
        
        await message.reply_text(
            f"🚀 **Campaign started!**\n\n"
            f"📝 Message: {caption[:100]}{'...' if len(caption) > 100 else ''}\n"
            f"📊 Groups: {len(groups)}\n"
            f"👥 Limit: {get_setting('member_limit')} members/group\n"
            f"⏱️ Delay: {get_setting('delay_seconds')} seconds\n\n"
            f"⏳ Sending messages... (Check /status for progress)"
        )
        
        # Start DM loop
        print(f"🚀 [DEBUG] Starting DM loop...")
        asyncio.create_task(dm_loop(client, message.chat.id))
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@app.on_message(filters.command("stop") & filters.private)
async def stop_campaign(client, message):
    print(f"🔍 [DEBUG] STOP command received from {message.from_user.id}")
    try:
        if get_setting("is_running") != "true":
            await message.reply_text("⚠️ No campaign is currently running!")
            print(f"⚠️ [DEBUG] Not running")
            return
        
        set_setting("is_running", "false")
        await message.reply_text("🛑 **Campaign stopped!**")
        print(f"✅ [DEBUG] Campaign stopped!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

# ============================================
# TRACK ACTIVE USERS IN GROUPS
# ============================================

@app.on_message(filters.group)
async def track_active(client, message):
    try:
        if message.from_user:
            print(f"🔍 [DEBUG] Tracking active user: {message.from_user.id} in group {message.chat.id}")
            track_active_user(message.from_user.id, message.chat.id)
    except Exception as e:
        print(f"❌ [DEBUG] Error tracking user: {e}")

# ============================================
# DM LOOP ENGINE
# ============================================

async def dm_loop(client, admin_chat_id):
    print(f"🚀 [DEBUG] dm_loop started!")
    try:
        groups = get_all_groups()
        caption = get_caption()
        member_limit = int(get_setting("member_limit") or 20)
        delay = int(get_setting("delay_seconds") or 3)
        
        print(f"🔍 [DEBUG] Settings: groups={len(groups)}, limit={member_limit}, delay={delay}")
        
        total_sent = 0
        total_failed = 0
        
        for group in groups:
            print(f"🔄 [DEBUG] Processing group: {group[4]}")
            
            # Check if stopped
            if get_setting("is_running") != "true":
                print(f"⏹️ [DEBUG] Campaign stopped by user")
                break
            
            group_id = group[1]
            group_title = group[4] or "Unknown"
            
            await client.send_message(
                admin_chat_id,
                f"🔄 Processing: {group_title}..."
            )
            print(f"✅ [DEBUG] Status update sent for {group_title}")
            
            try:
                # Get active users (last 30 minutes)
                active_users = get_active_users(group_id, minutes=30)
                print(f"🔍 [DEBUG] Active users found: {len(active_users)}")
                
                # If no active users, get recent members
                if not active_users:
                    await client.send_message(
                        admin_chat_id,
                        f"⚠️ No active users found in {group_title}. Getting recent members..."
                    )
                    print(f"⚠️ [DEBUG] No active users, getting recent members...")
                    
                    recent_members = []
                    async for member in client.get_chat_members(group_id, limit=member_limit):
                        recent_members.append(member.user.id)
                    
                    users_to_dm = recent_members
                    print(f"🔍 [DEBUG] Found {len(users_to_dm)} recent members")
                else:
                    users_to_dm = active_users[:member_limit]
                    print(f"🔍 [DEBUG] Will DM {len(users_to_dm)} active users")
                
                sent_count = 0
                failed_count = 0
                
                for user_id in users_to_dm:
                    print(f"🔄 [DEBUG] Processing user: {user_id}")
                    
                    # Check if stopped
                    if get_setting("is_running") != "true":
                        print(f"⏹️ [DEBUG] Campaign stopped during processing")
                        break
                    
                    # Skip if already sent recently
                    if is_already_sent(group_id, user_id):
                        print(f"⏭️ [DEBUG] User {user_id} already sent, skipping")
                        continue
                    
                    # Try to send message
                    try:
                        print(f"📤 [DEBUG] Sending to {user_id}...")
                        await client.send_message(user_id, caption)
                        track_sent(group_id, user_id)
                        sent_count += 1
                        total_sent += 1
                        print(f"✅ [DEBUG] Sent to {user_id} (Total: {total_sent})")
                        
                        # Progress update every 5 messages
                        if total_sent % 5 == 0:
                            await client.send_message(
                                admin_chat_id,
                                f"📊 Progress: {total_sent} DMs sent so far..."
                            )
                            print(f"📊 [DEBUG] Progress update sent: {total_sent}")
                            
                    except FloodWait as e:
                        print(f"⏳ [DEBUG] Flood wait: {e.x} seconds")
                        await client.send_message(
                            admin_chat_id,
                            f"⏳ Flood wait: {e.x} seconds. Pausing..."
                        )
                        await asyncio.sleep(e.x)
                        
                    except PeerIdInvalid:
                        failed_count += 1
                        total_failed += 1
                        print(f"❌ [DEBUG] PeerIdInvalid for {user_id}")
                        
                    except Exception as e:
                        failed_count += 1
                        total_failed += 1
                        print(f"❌ [DEBUG] Error sending to {user_id}: {e}")
                    
                    # Delay between messages
                    print(f"⏱️ [DEBUG] Waiting {delay} seconds...")
                    await asyncio.sleep(delay)
                
                await client.send_message(
                    admin_chat_id,
                    f"✅ {group_title}: Sent {sent_count} DMs, Failed {failed_count}"
                )
                print(f"✅ [DEBUG] Group {group_title} completed: sent={sent_count}, failed={failed_count}")
                
                # Clear old sent logs to free space
                clear_sent_log()
                
            except Exception as e:
                print(f"❌ [DEBUG] Error processing group {group_title}: {e}")
                await client.send_message(
                    admin_chat_id,
                    f"❌ Error in {group_title}: {e}"
                )
                continue
        
        # Campaign completed
        set_setting("is_running", "false")
        print(f"✅ [DEBUG] Campaign finished!")
        
        await client.send_message(
            admin_chat_id,
            f"✅ **Campaign completed!**\n\n"
            f"📊 Total DMs sent: {total_sent}\n"
            f"❌ Total failed: {total_failed}\n"
            f"📋 Groups processed: {len(groups)}"
        )
        print(f"✅ [DEBUG] Final summary sent!")
        
    except Exception as e:
        print(f"❌ [DEBUG] Fatal error in dm_loop: {e}")
        set_setting("is_running", "false")
        await client.send_message(admin_chat_id, f"❌ Campaign stopped due to error: {e}")

# ============================================
# TEST COMMAND
# ============================================

@app.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    print(f"🔍 [DEBUG] TEST command received from {message.from_user.id}")
    try:
        await message.reply_text("✅ **Bot is working!** Test successful!\n\nYour bot is running perfectly. 🎉")
        print(f"✅ [DEBUG] Test reply sent!")
    except Exception as e:
        print(f"❌ [DEBUG] Error in test: {e}")
        await message.reply_text(f"❌ Error: {e}")

# ============================================
# RUN BOT
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 DM Bot Starting... (DEBUG MODE)")
    print("=" * 60)
    
    print(f"🔍 [DEBUG] API ID: {API_ID}")
    print(f"🔍 [DEBUG] API Hash: {API_HASH[:10]}...")
    print(f"🔍 [DEBUG] Session String: {SESSION_STRING[:20]}...")
    print(f"🔍 [DEBUG] Bot Token: {BOT_TOKEN[:15]}...")
    print("=" * 60)
    
    # Check configuration
    if API_ID == 32141443:
        print("✅ [DEBUG] API ID found!")
    else:
        print("❌ [DEBUG] API ID looks wrong")
    
    if API_HASH != "4f34a89257ac316505f5a47b237454cc":
        print("✅ [DEBUG] API Hash found!")
    else:
        print("❌ [DEBUG] API Hash looks wrong (default value)")
    
    if SESSION_STRING != "your_session_string_here":
        print("✅ [DEBUG] Session String found!")
    else:
        print("❌ [DEBUG] Session String is default value! Please update!")
    
    print("=" * 60)
    print(f"📊 Groups in database: {get_group_count()}")
    print("=" * 60)
    print("🚀 Starting bot... (Watch for errors below)")
    print("=" * 60)
    
    try:
        app.run()
    except Exception as e:
        print(f"❌ [DEBUG] Fatal error: {e}")
        import traceback
        traceback.print_exc()
    
    print("👋 Bot stopped!")
