import asyncio
import os
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config

async def main():
    print("=== Testing Telethon Media Download ===")
    
    if not config.SESSION_STRING:
        print("ERROR: SESSION_STRING is empty!")
        return

    # Get Jira bot username
    bot_jira = Bot(token=config.BOT_JIRA_TOKEN)
    await bot_jira.initialize()
    bot_jira_info = await bot_jira.get_me()
    
    client = TelegramClient(
        StringSession(config.SESSION_STRING),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    
    await client.start()
    
    # Try resolving via Username
    entity = await client.get_entity(f"@{bot_jira_info.username}")
    print(f"Resolved Bot: @{bot_jira_info.username}")
    
    # Find the last message with media
    target_msg = None
    async for msg in client.iter_messages(entity, limit=20):
        if msg.media:
            target_msg = msg
            break
            
    if not target_msg:
        print("No message with media found in last 20 messages.")
        return
        
    print(f"Found message with media: ID {target_msg.id}, Type: {type(target_msg.media).__name__}")
    
    # Download the media
    dest_path = "scratch/telethon_download_test.zip"
    if os.path.exists(dest_path):
        os.remove(dest_path)
        
    print(f"Downloading media to: {dest_path}...")
    await client.download_media(target_msg, file=dest_path)
    
    if os.path.exists(dest_path):
        size = os.path.getsize(dest_path)
        print(f"Success! Downloaded file exists. Size: {size} bytes ({size / (1024*1024):.2f} MB)")
    else:
        print("Error: Downloaded file does not exist!")

if __name__ == "__main__":
    asyncio.run(main())
