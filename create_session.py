"""
Script to create Telegram session file
Run this locally before deploying to Docker
"""

from telethon import TelegramClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

api_id = int(os.getenv('API_ID', '0'))
api_hash = os.getenv('API_HASH', '')
session_name = os.getenv('SESSION_NAME', 'shana_session')

if api_id == 0 or not api_hash:
    print("Error: Please set API_ID and API_HASH in .env file")
    exit(1)

print("Creating Telegram session...")
print(f"API ID: {api_id}")
print(f"Session name: {session_name}")

client = TelegramClient(session_name, api_id, api_hash)

async def main():
    print("\nStarting authentication...")
    await client.start()
    
    # Get user info
    me = await client.get_me()
    print(f"\n✅ Successfully authenticated as: {me.first_name}")
    print(f"User ID: {me.id}")
    print(f"Phone: +{me.phone}")
    
    print(f"\n✅ Session file created: {session_name}.session")
    print("\nYou can now use this session file with Docker or run the main script.")
    
    await client.disconnect()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
