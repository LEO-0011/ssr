"""
Shana Project Torrent to Telegram Uploader with Bot Monitoring
Automatically fetches torrents from Shana Project and uploads to Telegram channel
Includes monitoring bot for control and status updates
"""

import os
import asyncio
import logging
from pathlib import Path
import aiohttp
from bs4 import BeautifulSoup
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
import libtorrent as lt
from datetime import datetime
import json
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CONFIG = {
    'api_id': int(os.getenv('API_ID', '0')),
    'api_hash': os.getenv('API_HASH', ''),
    'session_name': os.getenv('SESSION_NAME', 'shana_session'),
    'bot_token': os.getenv('BOT_TOKEN', ''),  # Bot token for monitoring
    'target_channel_id': int(os.getenv('TARGET_CHANNEL_ID', '0')),  # Numeric channel ID
    'admin_user_id': int(os.getenv('ADMIN_USER_ID', '0')),  # Admin user ID for bot commands
    'download_path': os.getenv('DOWNLOAD_PATH', './downloads'),
    'shana_url': os.getenv('SHANA_URL', 'https://www.shanaproject.com'),
    'check_interval': int(os.getenv('CHECK_INTERVAL', '3600')),
    'max_file_size': int(os.getenv('MAX_FILE_SIZE', str(2 * 1024 * 1024 * 1024))),
}


class ShanaProjectScraper:
    """Scraper for Shana Project website"""
    
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = None
        
    async def init_session(self):
        """Initialize aiohttp session"""
        self.session = aiohttp.ClientSession()
        
    async def close_session(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
            
    async def get_latest_torrents(self, limit=10):
        """
        Fetch latest torrents from Shana Project
        Returns list of torrent dicts with info
        """
        try:
            async with self.session.get(self.base_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch page: {response.status}")
                    return []
                    
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                torrents = []
                
                # Find torrent links
                torrent_links = soup.find_all('a', href=lambda x: x and ('.torrent' in x or 'magnet:' in x))
                
                for link in torrent_links[:limit]:
                    torrent_url = link.get('href')
                    
                    # Handle relative URLs
                    if torrent_url and not torrent_url.startswith(('http', 'magnet:')):
                        torrent_url = self.base_url + torrent_url
                    
                    # Extract torrent info
                    title = link.get_text(strip=True) or link.get('title', 'Unknown')
                    
                    # Try to find parent element for more info
                    parent = link.find_parent(['tr', 'div', 'li'])
                    size = "Unknown"
                    
                    if parent:
                        # Look for size information
                        size_text = parent.get_text()
                        size_match = re.search(r'(\d+\.?\d*\s*(MB|GB|KB))', size_text, re.IGNORECASE)
                        if size_match:
                            size = size_match.group(1)
                            
                    torrents.append({
                        'title': title,
                        'url': torrent_url,
                        'size': size,
                        'timestamp': datetime.now().isoformat(),
                    })
                    
                logger.info(f"Found {len(torrents)} torrents")
                return torrents
                
        except Exception as e:
            logger.error(f"Error fetching torrents: {e}")
            return []
            
    async def download_torrent_file(self, url, save_path):
        """Download .torrent file"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    with open(save_path, 'wb') as f:
                        f.write(content)
                    logger.info(f"Downloaded torrent file: {save_path}")
                    return True
                else:
                    logger.error(f"Failed to download torrent: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error downloading torrent file: {e}")
            return False


class TorrentDownloader:
    """Download torrents using libtorrent"""
    
    def __init__(self, download_path):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True, parents=True)
        self.session = lt.session()
        self.session.listen_on(6881, 6891)
        
    async def download_torrent(self, torrent_file, timeout=7200):
        """
        Download torrent content
        Returns path to downloaded file/folder
        """
        try:
            info = lt.torrent_info(str(torrent_file))
            h = self.session.add_torrent({
                'ti': info,
                'save_path': str(self.download_path)
            })
            
            logger.info(f"Starting download: {h.name()}")
            
            # Wait for download to complete
            start_time = datetime.now()
            while not h.is_seed():
                s = h.status()
                
                if s.progress > 0:
                    logger.info(f"Progress: {s.progress * 100:.2f}% "
                              f"Down: {s.download_rate / 1000:.1f} kB/s "
                              f"Up: {s.upload_rate / 1000:.1f} kB/s "
                              f"Peers: {s.num_peers}")
                
                # Check timeout
                if (datetime.now() - start_time).seconds > timeout:
                    logger.error("Download timeout")
                    self.session.remove_torrent(h)
                    return None
                    
                await asyncio.sleep(5)
                
            logger.info(f"Download complete: {h.name()}")
            
            # Get the downloaded file path
            download_path = self.download_path / h.name()
            return download_path
            
        except Exception as e:
            logger.error(f"Error downloading torrent: {e}")
            return None


class TelegramUploader:
    """Upload files to Telegram channel with user account"""
    
    def __init__(self, api_id, api_hash, session_name):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.uploaded_files = self.load_uploaded_history()
        
    def load_uploaded_history(self):
        """Load history of uploaded files"""
        history_file = 'uploaded_history.json'
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
        
    def save_uploaded_history(self):
        """Save history of uploaded files"""
        with open('uploaded_history.json', 'w') as f:
            json.dump(self.uploaded_files, f, indent=2)
            
    async def start(self):
        """Start Telegram client"""
        await self.client.start()
        logger.info("Telegram uploader client started")
        
    async def stop(self):
        """Stop Telegram client"""
        await self.client.disconnect()
        
    async def upload_file(self, file_path, channel_id, caption=""):
        """
        Upload file to Telegram channel using numeric ID
        Returns True if successful
        """
        try:
            file_path = Path(file_path)
            
            # Check if already uploaded
            file_hash = str(file_path)
            if file_hash in self.uploaded_files:
                logger.info(f"File already uploaded: {file_path.name}")
                return True
                
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > CONFIG['max_file_size']:
                logger.warning(f"File too large: {file_path.name} ({file_size / 1024 / 1024:.2f} MB)")
                return False
                
            logger.info(f"Uploading to Telegram channel {channel_id}: {file_path.name}")
            
            # Upload file
            await self.client.send_file(
                channel_id,
                file_path,
                caption=caption,
                attributes=[DocumentAttributeFilename(file_name=file_path.name)],
                force_document=True
            )
            
            # Mark as uploaded
            self.uploaded_files[file_hash] = {
                'name': file_path.name,
                'upload_time': datetime.now().isoformat(),
                'size': file_size
            }
            self.save_uploaded_history()
            
            logger.info(f"Successfully uploaded: {file_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False


class MonitoringBot:
    """Telegram bot for monitoring and controlling the uploader"""
    
    def __init__(self, bot_token, admin_user_id):
        self.bot = TelegramClient('bot_session', CONFIG['api_id'], CONFIG['api_hash'])
        self.bot_token = bot_token
        self.admin_user_id = admin_user_id
        self.is_running = False
        self.stats = {
            'torrents_found': 0,
            'files_uploaded': 0,
            'errors': 0,
            'last_check': None
        }
        
    async def start(self):
        """Start monitoring bot"""
        await self.bot.start(bot_token=self.bot_token)
        logger.info("Monitoring bot started")
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup bot command handlers"""
        
        @self.bot.on(events.NewMessage(pattern='/start', from_users=self.admin_user_id))
        async def start_handler(event):
            await event.respond(
                "🤖 **Shana Project Uploader Bot**\n\n"
                "Available commands:\n"
                "/status - Show current status\n"
                "/stats - Show statistics\n"
                "/pause - Pause automatic uploads\n"
                "/resume - Resume automatic uploads\n"
                "/check - Force check for new torrents\n"
                "/config - Show configuration"
            )
            
        @self.bot.on(events.NewMessage(pattern='/status', from_users=self.admin_user_id))
        async def status_handler(event):
            status = "🟢 Running" if self.is_running else "🔴 Paused"
            last_check = self.stats['last_check'] or "Never"
            await event.respond(
                f"**Status Report**\n\n"
                f"Status: {status}\n"
                f"Last Check: {last_check}\n"
                f"Torrents Found: {self.stats['torrents_found']}\n"
                f"Files Uploaded: {self.stats['files_uploaded']}\n"
                f"Errors: {self.stats['errors']}"
            )
            
        @self.bot.on(events.NewMessage(pattern='/stats', from_users=self.admin_user_id))
        async def stats_handler(event):
            await event.respond(
                f"📊 **Statistics**\n\n"
                f"Torrents Found: {self.stats['torrents_found']}\n"
                f"Files Uploaded: {self.stats['files_uploaded']}\n"
                f"Errors: {self.stats['errors']}\n"
                f"Last Check: {self.stats['last_check'] or 'Never'}"
            )
            
        @self.bot.on(events.NewMessage(pattern='/pause', from_users=self.admin_user_id))
        async def pause_handler(event):
            self.is_running = False
            await event.respond("⏸️ Automatic uploads paused")
            
        @self.bot.on(events.NewMessage(pattern='/resume', from_users=self.admin_user_id))
        async def resume_handler(event):
            self.is_running = True
            await event.respond("▶️ Automatic uploads resumed")
            
        @self.bot.on(events.NewMessage(pattern='/config', from_users=self.admin_user_id))
        async def config_handler(event):
            await event.respond(
                f"⚙️ **Configuration**\n\n"
                f"Channel ID: {CONFIG['target_channel_id']}\n"
                f"Check Interval: {CONFIG['check_interval']}s\n"
                f"Max File Size: {CONFIG['max_file_size'] / 1024 / 1024:.0f} MB\n"
                f"Shana URL: {CONFIG['shana_url']}"
            )
            
    async def notify_admin(self, message):
        """Send notification to admin"""
        try:
            await self.bot.send_message(self.admin_user_id, message)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
            
    async def stop(self):
        """Stop monitoring bot"""
        await self.bot.disconnect()


class ShanaUploader:
    """Main uploader class"""
    
    def __init__(self):
        self.scraper = ShanaProjectScraper(CONFIG['shana_url'])
        self.downloader = TorrentDownloader(CONFIG['download_path'])
        self.uploader = TelegramUploader(CONFIG['api_id'], CONFIG['api_hash'], CONFIG['session_name'])
        self.bot = MonitoringBot(CONFIG['bot_token'], CONFIG['admin_user_id'])
        self.bot.is_running = True
        
    async def start(self):
        """Start all services"""
        await self.scraper.init_session()
        await self.uploader.start()
        await self.bot.start()
        await self.bot.notify_admin("🚀 Shana Project Uploader started!")
        
    async def stop(self):
        """Stop all services"""
        await self.scraper.close_session()
        await self.uploader.stop()
        await self.bot.stop()
        
    async def process_torrent(self, torrent_info):
        """Process a single torrent"""
        try:
            # Download torrent file
            torrent_filename = f"{torrent_info['title']}.torrent".replace('/', '_')
            torrent_path = Path(CONFIG['download_path']) / torrent_filename
            
            if await self.scraper.download_torrent_file(torrent_info['url'], torrent_path):
                # Download torrent content
                content_path = await self.downloader.download_torrent(torrent_path)
                
                if content_path and content_path.exists():
                    # Upload to Telegram
                    caption = f"📁 {torrent_info['title']}\n💾 Size: {torrent_info['size']}"
                    
                    if await self.uploader.upload_file(content_path, CONFIG['target_channel_id'], caption):
                        self.bot.stats['files_uploaded'] += 1
                        await self.bot.notify_admin(f"✅ Uploaded: {torrent_info['title']}")
                        return True
                        
            return False
            
        except Exception as e:
            logger.error(f"Error processing torrent: {e}")
            self.bot.stats['errors'] += 1
            return False
            
    async def run(self):
        """Main run loop"""
        await self.start()
        
        try:
            while True:
                if self.bot.is_running:
                    logger.info("Checking for new torrents...")
                    self.bot.stats['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    torrents = await self.scraper.get_latest_torrents(limit=5)
                    self.bot.stats['torrents_found'] += len(torrents)
                    
                    for torrent in torrents:
                        await self.process_torrent(torrent)
                        
                await asyncio.sleep(CONFIG['check_interval'])
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.stop()


async def main():
    """Main entry point"""
    uploader = ShanaUploader()
    await uploader.run()


if __name__ == '__main__':
    asyncio.run(main())
