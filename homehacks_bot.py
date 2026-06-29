#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HomeHacks Affiliate Bot
חיפוש מוצרים מאלי אקספרס ושליחה לקבוצה
"""

import asyncio
import hashlib
import logging
import time

import aiohttp
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
#  הגדרות
# ============================================================

BOT_TOKEN         = "8710753369:AAGAQgJvKZpJNDX8OHmFywGz2dB4h8F3QK4"
APP_KEY           = "535546"
APP_SECRET        = "mXB4CsSeXNpjwRrLRXEzHWt3zoil5AvB"
TRACKING_ID       = "homehacks_telegram"
CHANNEL_ID        = "@homehacks_il"
BRIDGE_GROUP      = -1004350404248
YOUR_USER_ID      = 1370253420

CATEGORIES = {
    "בית וגינה כללי":   "home garden gadgets",
    "תאורה חכמה":        "smart lighting home",
    "ריהוט ואחסון":      "furniture storage home",
    "גינון וצמחים":      "gardening plants tools",
    "מטבח וכלים":        "kitchen gadgets tools",
    "כלי עבודה":         "home tools DIY",
    "ניקיון וסדר":       "cleaning organization home",
    "אבטחה וסייבר":      "home security camera",
}

ALI_API_URL = "https://api-sg.aliexpress.com/sync"

# ============================================================
#  AliExpress API
# ============================================================

def _sign(params: dict, secret: str) -> str:
    sorted_params = sorted(params.items())
    sign_string = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_string.encode("utf-8")).hexdigest().upper()


async def search_products(keyword: str) -> list:
    """חפש מוצרים בAliExpress"""
    timestamp = str(int(time.time() * 1000))
    params = {
        "method":        "aliexpress.affiliate.product.query",
        "app_key":       APP_KEY,
        "timestamp":     timestamp,
        "format":        "json",
        "v":             "2.0",
        "sign_method":   "md5",
        "keywords":      keyword,
        "tracking_id":   TRACKING_ID,
        "page_no":       "1",
        "page_size":     "50",
        "sort":          "LAST_VOLUME_DESC",
        "fields":        "product_id,product_title,product_main_image_url,sale_price,original_price,evaluate_rate,volume,promotion_link,lastest_volume",
    }
    params["sign"] = _sign(params, APP_SECRET)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ALI_API_URL, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json(content_type=None)

        result = data.get("aliexpress_affiliate_product_query_response", {}).get("resp_result", {})
        if result.get("resp_code") != 200:
            logger.error("AliExpress error: %s", result.get("resp_msg"))
            return []
        
        all_products = result.get("result", {}).get("products", {}).get("product", [])
        filtered = []
        for p in all_products:
            try:
                vol = int(str(p.get("lastest_volume", 0)))
                rating = float(str(p.get("evaluate_rate", "0")).replace("%", ""))
                if vol >= 100 and rating >= 90:
                    filtered.append(p)
            except Exception:
                pass
        
        logger.info("Found %d products, %d passed filter", len(all_products), len(filtered))
        return filtered if filtered else all_products

    except Exception as e:
        logger.error("Search error: %s", e)
        return []


# ============================================================
#  UI Helpers
# ============================================================

def build_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ שלח לקבוצה", callback_data="action:publish"),
            InlineKeyboardButton("❌ דלג",        callback_data="action:skip"),
        ],
        [
            InlineKeyboardButton("🔁 חפש עוד",   callback_data="action:more"),
        ],
    ])


async def show_product(source, ctx: ContextTypes.DEFAULT_TYPE):
    products = ctx.user_data.get("products", [])
    index    = ctx.user_data.get("index", 0)

    if index >= len(products):
        await source.message.reply_text("✅ סיום! שלח /find לחיפוש חדש.")
        return

    product = products[index]
    title   = product.get("product_title", "מוצר")[:80]
    price   = product.get("sale_price", "N/A")
    orig    = product.get("original_price", "")
    volume  = product.get("lastest_volume", "")
    image   = product.get("product_main_image_url", "")
    total   = len(products)

    discount = ""
    try:
        p = float(str(price).replace(",", ""))
        o = float(str(orig).replace(",", ""))
        if o > p:
            pct = int((1 - p / o) * 100)
            discount = f"🔻 {pct}% הנחה"
    except Exception:
        pass

    preview = f"📦 מוצר {index + 1}/{total}\n\n🛒 {title}\n💰 ${price}"
    if discount:
        preview += f"\n{discount}"
    if volume:
        preview += f"\n📦 {volume} הזמנות"

    buttons = build_buttons()

    try:
        if image:
            await source.message.reply_photo(photo=image, caption=preview, reply_markup=buttons)
        else:
            await source.message.reply_text(preview, reply_markup=buttons)
    except Exception as e:
        logger.error("Error showing product: %s", e)


# ============================================================
#  Commands
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return
    await update.message.reply_text(
        "👋 *ברוך הבא!*\n\n"
        "/find — חפש מוצרים\n"
        "/category — בחר קטגוריה\n"
        "/help — עזרה",
        parse_mode="Markdown",
    )


async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return

    await update.message.reply_text("🔍 מחפש מוצרים...")
    keywords = list(CATEGORIES.values())
    products = await search_products(keywords[0])

    if not products:
        await update.message.reply_text("❌ לא נמצאו מוצרים.")
        return

    ctx.user_data["products"]    = products
    ctx.user_data["index"]       = 0
    ctx.user_data["kw_index"]    = 0
    ctx.user_data["cat_counter"] = 0
    ctx.user_data["seen_ids"]    = set()
    await show_product(update, ctx)


async def cmd_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"cat:{kw}")]
        for name, kw in CATEGORIES.items()
    ]
    await update.message.reply_text("📂 בחר קטגוריה:", reply_markup=InlineKeyboardMarkup(buttons))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return
    await update.message.reply_text(
        "📖 עזרה\n\n"
        "/find — חפש\n"
        "/category — קטגוריה",
        parse_mode="Markdown",
    )


# ============================================================
#  Callbacks
# ============================================================

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if update.effective_user.id != YOUR_USER_ID:
        await query.answer("לא מורשה", show_alert=True)
        return
    
    await query.answer()

    data     = query.data
    products = ctx.user_data.get("products", [])
    index    = ctx.user_data.get("index", 0)
    bot: Bot = ctx.bot

    # בחירת קטגוריה
    if data.startswith("cat:"):
        keyword = data.split("cat:")[1]
        await query.message.reply_text("🔍 מחפש...")
        found = await search_products(keyword)
        if not found:
            await query.message.reply_text("❌ לא נמצאו מוצרים.")
            return
        ctx.user_data["products"] = found
        ctx.user_data["index"]    = 0
        ctx.user_data["cat_counter"] = 0
        await show_product(query, ctx)
        return

    # שלח לקבוצה
    if data == "action:publish":
        if not products or index >= len(products):
            await query.message.reply_text("❌ אין מוצר.")
            return

        product = products[index]
        link = product.get("promotion_link", "")

        try:
            await bot.send_message(chat_id=BRIDGE_GROUP, text=link)
            await query.message.reply_text("✅ קישור נשלח!\n\nעבור אותו ידנית ל-@homehacks_il_bot")
            logger.info("Link sent: %s", link)
        except Exception as e:
            await query.message.reply_text(f"❌ שגיאה: {e}")
            logger.error("Send error: %s", e)

        ctx.user_data["index"] = index + 1
        await show_product(query, ctx)

    # דלג
    elif data == "action:skip":
        if products and index < len(products):
            seen = ctx.user_data.get("seen_ids", set())
            seen.add(products[index].get("product_id"))
            ctx.user_data["seen_ids"] = seen

        ctx.user_data["index"]       = index + 1
        ctx.user_data["cat_counter"] = ctx.user_data.get("cat_counter", 0) + 1

        if ctx.user_data["cat_counter"] >= 5:
            seen = ctx.user_data.get("seen_ids", set())
            keywords = list(CATEGORIES.values())
            names = list(CATEGORIES.keys())
            kw_idx = (ctx.user_data.get("kw_index", 0) + 1) % len(keywords)
            ctx.user_data["kw_index"]    = kw_idx
            ctx.user_data["cat_counter"] = 0
            await query.message.reply_text(f"🔄 עובר ל: {names[kw_idx]}...")
            found = await search_products(keywords[kw_idx])
            found = [p for p in found if p.get("product_id") not in seen]
            if found:
                ctx.user_data["products"] = found
                ctx.user_data["index"]    = 0

        await show_product(query, ctx)

    # חפש עוד
    elif data == "action:more":
        seen = ctx.user_data.get("seen_ids", set())
        keywords = list(CATEGORIES.values())
        names = list(CATEGORIES.keys())
        kw_idx = (ctx.user_data.get("kw_index", 0) + 1) % len(keywords)
        ctx.user_data["kw_index"]    = kw_idx
        ctx.user_data["cat_counter"] = 0
        await query.message.reply_text(f"🔍 עובר ל: {names[kw_idx]}...")
        found = await search_products(keywords[kw_idx])
        found = [p for p in found if p.get("product_id") not in seen]
        if not found:
            await query.message.reply_text("❌ לא נמצאו מוצרים חדשים.")
            return
        ctx.user_data["products"] = found
        ctx.user_data["index"]    = 0
        await show_product(query, ctx)


# ============================================================
#  Main
# ============================================================

def main():
    logger.info("Starting HomeHacks Bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("find",     cmd_find))
    app.add_handler(CommandHandler("category", cmd_category))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Bot running!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
