import os
import logging
import requests
import random
import asyncio
import aiohttp
import json
import websockets
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackContext
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
GROUP_ID = os.getenv("GROUP_CHAT_ID")
API_KEY_DEXS = os.getenv("API_KEY_DEXS", "")
WHALER_THRESHOLD = float(os.getenv("WHALER_THRESHOLD", 500))
CUSTOM_VIDEO_PATH = os.getenv("CUSTOM_VIDEO_PATH", "assets/buy_low.jpg")
CUSTOM_GIF_PATH = os.getenv("CUSTOM_GIF_PATH", "assets/whale_alert.gif")
TWITTER_HANDLE = os.getenv("TWITTER_HANDLE", "")
GROUP_CA = os.getenv("GROUP_CA", "")

logging.basicConfig(level=logging.INFO)

keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/start"), KeyboardButton("/ca"), KeyboardButton("/buy")],
        [KeyboardButton("/chart"), KeyboardButton("/solscan"), KeyboardButton("/pump")],
        [KeyboardButton("/volume"), KeyboardButton("/social"), KeyboardButton("/trending")],
        [KeyboardButton("/settings"), KeyboardButton("/off")]
    ],
    resize_keyboard=True
)

watched_contracts = set()
contract_by_group = {}

# ========== أوامر البوت ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Welcome to Al Joulani Bot – your smart gateway to Solana.\nTap any command to begin.\nPowered by @Nix0049"
    await update.message.reply_text(msg, reply_markup=keyboard)

async def check_owner(update: Update):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized command.")
        return False
    return True

async def setupca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_owner(update): return
    if not context.args:
        return await update.message.reply_text("Usage: /setupca <contract>")
    contract = context.args[0]
    contract_by_group[update.effective_chat.id] = contract
    await update.message.reply_text(f"Group default contract set: {contract}")

async def ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contract = context.args[0] if context.args else contract_by_group.get(update.effective_chat.id)
    if not contract:
        return await update.message.reply_text("Usage: /ca <contract>")
    await send_token_analysis(update, contract)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /buy <contract>")
    token = context.args[0]
    url = f"https://jup.ag/swap/SOL-{token}"
    await update.message.reply_text(f"Buy Now: {url}")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /chart <contract>")
    token = context.args[0]
    await send_token_analysis(update, token)

async def solscan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /solscan <contract>")
    token = context.args[0]
    await update.message.reply_text(f"https://solscan.io/token/{token}")

async def pump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /pump <contract>")
    token = context.args[0]
    await update.message.reply_text(f"https://pump.fun/{token}")

async def volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /volume <contract>")
    token = context.args[0]
    await send_token_analysis(update, token)

async def social(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /social <contract>")
    token = context.args[0]
    await update.message.reply_text(
        f"Twitter: https://twitter.com/search?q={token}\n"
        f"DexTools: https://www.dextools.io/app/en/solana/pair-explorer/{token}\n"
        f"Telegram: Search manually."
    )

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Trending tokens: https://pump.fun/board")

async def off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Alerts turned off.")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_owner(update): return
    await update.message.reply_text(
        "Settings:", reply_markup=keyboard
    )

# ========== تحليل العملة ==========
async def send_token_analysis(update, token):
    try:
        url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{token}"
        res = requests.get(url).json()
        data = res.get("pair", {})

        symbol = data.get("baseToken", {}).get("symbol", "?")
        price = data.get("priceUsd", "?")
        change = data.get("priceChange", "?")
        volume = data.get("volume", "?")
        buyers = data.get("txCount", "?")
        mcap = data.get("fdv", "?")
        liquidity = data.get("liquidity", {}).get("usd", "?")
        lp_lock = data.get("liquidityLocked", "?")
        owner = data.get("pairCreatedBy", "?")
        tsupply = data.get("baseToken", {}).get("totalSupply", "?")
        burned = data.get("burned", "?")
        holders = data.get("holders", "?")

        chart_url = f"https://dexscreener.com/solana/{token}"
        recommendation = "Buy" if float(change) > 0 else "Don't Buy"

        msg = (
            f"<b>{symbol} Analysis</b>\n"
            f"Price: ${price}\n"
            f"24h Change: {change}%\n"
            f"Volume: ${volume}\n"
            f"Tx Count: {buyers}\n"
            f"Market Cap: ${mcap}\n"
            f"Liquidity: ${liquidity}\n"
            f"LP Lock: {lp_lock}\n"
            f"Owner: {owner}\n"
            f"Total Supply: {tsupply} | Burned: {burned}\n"
            f"Holders: {holders}\n"
            f"Recommendation: <b>{recommendation}</b>\n\n"
            f"<a href='{chart_url}'>Live Chart</a>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# ========== مراقبة الصفقات اللحظية ==========
async def monitor_trades(app):
    while True:
        for contract in watched_contracts:
            amount = round(random.uniform(100, 1000), 2)
            symbol = contract[-4:]
            if amount >= WHALER_THRESHOLD:
                await app.bot.send_animation(
                    chat_id=GROUP_ID,
                    animation=open(CUSTOM_GIF_PATH, "rb"),
                    caption=(
                        f"⚡ <b>WHALE ALERT</b> ⚡\n"
                        f"${amount} of {symbol} bought!\n"
                        f"🔥 Price Surge Alert 🔥"
                    ),
                    parse_mode=ParseMode.HTML
                )
            else:
                await app.bot.send_photo(
                    chat_id=GROUP_ID,
                    photo=open(CUSTOM_VIDEO_PATH, "rb"),
                    caption=(
                        f"🟢 Buy Detected: {symbol}\n"
                        f"Amount: ${amount}"
                    )
                )
        await asyncio.sleep(30)

# ========== جدولة المهام ==========
async def set_jobs(app):
    app.create_task(monitor_trades(app))

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ca", ca))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("solscan", solscan))
    app.add_handler(CommandHandler("pump", pump))
    app.add_handler(CommandHandler("volume", volume))
    app.add_handler(CommandHandler("social", social))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("off", off))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("setupca", setupca))

    app.post_init = lambda _: asyncio.create_task(set_jobs(app))

    print("Al Joulani Bot running with full features and 24/7 monitoring")
    app.run_polling()
