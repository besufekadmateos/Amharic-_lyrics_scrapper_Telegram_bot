import os
import logging
import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from dotenv import load_dotenv

# Load local environment variables if present (used for local testing)
load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- SCRAPER CLASS ---
class WikiMezmurScraper:
    def __init__(self):
        self.base_url = "https://wikimezmur.org"
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        self.singers = [] 

    def clean_text(self, text):
        if not text: return ""
        text = re.sub(r'[፡:]', ' ', text)
        return " ".join(text.split()).lower()

    def build_singer_directory(self):
        if self.singers: return 
        url = f"{self.base_url}/am/Gospel_Singers"
        try:
            res = requests.get(url, headers=self.headers)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            content = soup.find('div', {'id': 'mw-content-text'})
            
            for link in content.find_all('a'):
                path = link.get('href', '')
                if path.startswith('/am/') and not any(x in path for x in ['Special:', 'Category:', 'ልዩ:', 'መደብ:']):
                    full_text = link.text.strip()
                    if full_text:
                        self.singers.append({
                            'display': full_text,
                            'path': path,
                            'clean': self.clean_text(full_text)
                        })
        except Exception as e:
            logging.error(f"Directory sync failed: {e}")

    def get_singer_songs(self, singer_path):
        try:
            res = requests.get(f"{self.base_url}{singer_path}", headers=self.headers)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            body = soup.find('div', {'id': 'mw-content-text'})
            
            songs = []
            for a in body.find_all('a'):
                title = a.get('title', '')
                if title and not any(x in title for x in ["Edit", "Category", "መደብ", "ልዩ"]):
                    songs.append({'name': a.text.strip(), 'path': a['href']})
            return songs
        except Exception as e:
            logging.error(f"Failed to get songs: {e}")
            return []

    def get_lyrics(self, song_path):
        try:
            path = urllib.parse.unquote(song_path)
            url = f"{self.base_url}{urllib.parse.quote(path)}"
            res = requests.get(url, headers=self.headers)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            content = soup.find('div', {'id': 'mw-content-text'})
            
            if not content: return "Lyrics not found."

            for el in content.find_all(['script', 'style', 'table', 'sup']):
                if not el.find(class_='poem'):
                    el.decompose()

            lyrics = []
            poem_elements = content.find_all(True, class_='poem')
            if poem_elements:
                for p in poem_elements:
                    lyrics.append(p.get_text(separator='\n'))
            else:
                for p in content.find_all('p'):
                    lyrics.append(p.get_text())

            return "\n".join(lyrics).strip()
        except Exception as e:
            return f"Error: {e}"

# Instantiate the scraper
scraper = WikiMezmurScraper()
scraper.build_singer_directory()

# Conversation states for searching
AWAITING_SINGER_SEARCH = 1

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu."""
    keyboard = [
        [InlineKeyboardButton("🔍 Search Singer/Song", callback_data="menu_search")],
        [InlineKeyboardButton("🎵 Browse All Singers", callback_data="menu_browse_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "👋 Welcome to WikiMezmur Bot!\nChoose an option below to find lyrics:"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Process cancelled.")
    return ConversationHandler.END

# --- BROWSE FEATURE ---

async def browse_singers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists singers using inline keyboard pagination (5 at a time)."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split("_")[2])
    per_page = 5
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_singers = scraper.singers[start_idx:end_idx]
    
    keyboard = []
    for i, s in enumerate(page_singers):
        global_idx = start_idx + i
        keyboard.append([InlineKeyboardButton(s['display'], callback_data=f"select_singer_{global_idx}_0")])
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_browse_{page-1}"))
    if end_idx < len(scraper.singers):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_browse_{page+1}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    
    await query.message.edit_text("🎵 Select a Singer to browse songs:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- SEARCH FEATURE ---

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔍 Please type and send the **Singer's Name**:")
    return AWAITING_SINGER_SEARCH

async def process_singer_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s_input = update.message.text.strip()
    cleaned_search = scraper.clean_text(s_input)
    
    matches = [s for s in scraper.singers if cleaned_search in s['clean']]
    
    if not matches:
        await update.message.reply_text("❌ Singer not found. Type /start to try again.")
        return ConversationHandler.END
        
    keyboard = []
    for s in matches[:8]: 
        global_idx = scraper.singers.index(s)
        keyboard.append([InlineKeyboardButton(s['display'], callback_data=f"select_singer_{global_idx}_0")])
        
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    
    await update.message.reply_text("Matches found. Select the correct singer:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

# --- SONGS WITH PAGINATION & LYRICS ---

async def handle_singer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    singer_idx = int(data_parts[2])
    song_page = int(data_parts[3])
    
    singer = scraper.singers[singer_idx]
    
    cached_singer_idx = context.user_data.get('cached_singer_idx')
    if cached_singer_idx == singer_idx and 'current_songs' in context.user_data:
        songs = context.user_data['current_songs']
    else:
        await query.message.edit_text(f"⏳ Fetching songs for {singer['display']}...")
        songs = scraper.get_singer_songs(singer['path'])
        context.user_data['current_songs'] = songs
        context.user_data['cached_singer_idx'] = singer_idx

    if not songs:
        await query.message.edit_text("No songs found for this artist.", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
        return

    per_page = 10
    start_idx = song_page * per_page
    end_idx = start_idx + per_page
    page_songs = songs[start_idx:end_idx]
    
    keyboard = []
    for i, song in enumerate(page_songs):
        global_song_idx = start_idx + i
        keyboard.append([InlineKeyboardButton(song['name'], callback_data=f"get_lyrics_{global_song_idx}")])
        
    nav_row = []
    if song_page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev Songs", callback_data=f"select_singer_{singer_idx}_{song_page-1}"))
    if end_idx < len(songs):
        nav_row.append(InlineKeyboardButton("Songs Next ➡️", callback_data=f"select_singer_{singer_idx}_{song_page+1}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    
    await query.message.edit_text(
        text=f"🎶 **Songs by {singer['display']}** (Page {song_page + 1}/{-(-len(songs)//per_page)}):\nSelect a song to extract lyrics.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_lyrics_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    song_idx = int(query.data.split("_")[2])
    songs = context.user_data.get('current_songs', [])
    singer_idx = context.user_data.get('cached_singer_idx', 0)
    
    if not songs or song_idx >= len(songs):
        await query.message.edit_text("Session timed out. Please restart with /start")
        return
        
    song = songs[song_idx]
    await query.message.edit_text(f"⏳ Extracting lyrics for '{song['name']}'...")
    
    lyrics = scraper.get_lyrics(song['path'])
    
    keyboard = [
        [InlineKeyboardButton(f"🔙 Back to Songs", callback_data=f"select_singer_{singer_idx}_0")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    
    if len(lyrics) > 4000:
        chunks = [lyrics[i:i+4000] for i in range(0, len(lyrics), 4000)]
        for chunk in chunks[:-1]:
            await query.message.reply_text(chunk)
        await query.message.reply_text(chunks[-1], reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text(f"📋 **{song['name']}**\n\n{lyrics}", reply_markup=InlineKeyboardMarkup(keyboard))

# --- MAIN ORCHESTRATOR ---
def main():
    # Safely pull the token injected by Railway or your local .env file
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        logging.critical("CRITICAL ERROR: TELEGRAM_BOT_TOKEN environment variable is completely missing!")
        return

    application = Application.builder().token(TOKEN).build()
    
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern="^menu_search$")],
        states={
            AWAITING_SINGER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_singer_search)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(search_conv)
    application.add_handler(CallbackQueryHandler(browse_singers, pattern="^menu_browse_"))
    application.add_handler(CallbackQueryHandler(handle_singer_selection, pattern="^select_singer_"))
    application.add_handler(CallbackQueryHandler(handle_lyrics_request, pattern="^get_lyrics_"))
    application.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    
    print("Bot is up and running with song pagination...")
    application.run_polling()

if __name__ == '__main__':
    main()
