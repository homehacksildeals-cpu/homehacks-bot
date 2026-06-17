#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HomeHacks Affiliate Bot - Simple Version
שלח קישורים לקבוצת גשר, ומשם @homehacks_il_bot יטפל בהם
"""

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

# ============================================================
#  הגדרות — מלא את הפרטים שלך כאן
# ============================================================

BOT_TOKEN         = "8710753369:AAGAQgJvKZpJNDX8OHmFywGz2dB4h8F3QK4"
APP_KEY           = "535546"
APP_SECRET        = "mXB4CsSeXNpjwRrLRXEzHWt3zoil5AvB"
TRACKING_ID       = "homehacks_telegram"
CHANNEL_ID        = "@homehacks_il"
BRIDGE_GROUP      = -1004350404248

# ============================================================
#  הגדרות חיפוש
# ============================================================

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

MAX_PRODUCTS = 50

# ============================================================
#  לוגינג
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
#  AliExpress API
# ============================================================

ALI_API_URL = "https://api-sg.aliexpress.com/sync"


def _sign(params: dict, secret: str) -> str:
    sorted_params = sorted(params.items())
    sign_string = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_string.encode("utf-8")).hexdigest().upper()


async def search_products(keyword: str) -> list:
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
        "page_size":     str(MAX_PRODUCTS),
        "sort":          "LAST_VOLUME_DESC",
        "fields":        "product_id,product_title,product_main_image_url,sale_price,original_price,evaluate_rate,volume,promotion_link,lastest_volume",
    }
    params["sign"] = _sign(params, APP_SECRET)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ALI_API_URL, data=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json(content_type=None)

        result = data.get("aliexpress_affiliate_product_query_response", {}).get("resp_result", {})
        if result.get("resp_code") != 200:
            logger.error("AliExpress error: %s", result.get("resp_msg"))
            return []
        
        all_products = result.get("result", {}).get("products", {}).get("product", [])
        # סנן מוצרים חמים בלבד (100+ הזמנות, 90%+ דירוג)
        filtered = []
        for p in all_products:
            try:
                vol = int(str(p.get("lastest_volume", 0)))
                rating = float(str(p.get("evaluate_rate", "0")).replace("%", ""))
                if vol >= 100 and rating >= 90:
                    filtered.append(p)
            except Exception:
                pass
        
        logger.info("נמצאו %d מוצרים, %d עברו פילטר", len(all_products), len(filtered))
        return filtered if filtered else all_products

    except Exception as e:
        logger.error("שגיאה בחיפוש: %s", e)
        return []


async def shorten_url(url: str) -> str:
    """קצר קישור באמצעות URL shortener service"""
    try:
        async with aiohttp.ClientSession() as session:
            # נסה עם v.gd shortener
            async with session.get(
                f"https://v.gd/?format=json&url={url}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if "short_url" in data:
                        short = data["short_url"]
                        logger.info("קישור קוצר: %s", short)
                        return short
    except Exception as e:
        logger.error("שגיאה בקיצור קישור: %s", e)
    return url  # אם נכשל, חזור לקישור המקורי


# ============================================================
#  עזר — הצגת מוצר
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


async def show_product(source, ctx: ContextTypes.DEFAULT_TYPE, is_update=True):
    products = ctx.user_data.get("products", [])
    index    = ctx.user_data.get("index", 0)

    if index >= len(products):
        msg = "✅ עברת על כל המוצרים. שלח /find לחיפוש חדש."
        if is_update:
            await source.message.reply_text(msg)
        else:
            await source.message.reply_text(msg)
        return

    product = products[index]
    title   = product.get("product_title", "מוצר")[:80]
    price   = product.get("sale_price", "N/A")
    orig    = product.get("original_price", "")
    rating  = product.get("evaluate_rate", "")
    volume  = product.get("lastest_volume", "")
    image   = product.get("product_main_image_url", "")
    total   = len(products)

    discount = ""
    try:
        p = float(str(price).replace(",", ""))
        o = float(str(orig).replace(",", ""))
        if o > p:
            pct = int((1 - p / o) * 100)
            discount = f"🔻 {pct}% הנחה (היה ${orig})"
    except Exception:
        pass

    stars = ""
    try:
        r = float(str(rating).replace("%", "")) / 20
        stars = "⭐" * round(r)
    except Exception:
        pass

    preview = f"📦 מוצר {index + 1}/{total}\n\n🛒 {title}\n💰 ${price}"
    if discount:
        preview += f"\n{discount}"
    if stars:
        preview += f"\n{stars}"
    if volume:
        preview += f"\n📦 {volume} הזמנות"

    buttons = build_buttons()

    try:
        msg_obj = source.message

        if image:
            await msg_obj.reply_photo(photo=image, caption=preview, reply_markup=buttons)
        else:
            await msg_obj.reply_text(preview, reply_markup=buttons)
    except Exception as e:
        logger.error("שגיאה בהצגת מוצר: %s", e)


# ============================================================
#  Handlers
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *ברוך הבא ל-HomeHacks Bot!*\n\n"
        "/find — חפש מוצרים חמים\n"
        "/category — בחר קטגוריה\n"
        "/help — עזרה",
        parse_mode="Markdown",
    )


async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keywords_list = list(CATEGORIES.values())
    await update.message.reply_text("🔍 מחפש מוצרים...")
    products = await search_products(keywords_list[0])

    if not products:
        await update.message.reply_text("❌ לא נמצאו מוצרים. נסה שוב.")
        return

    ctx.user_data["products"]    = products
    ctx.user_data["index"]       = 0
    ctx.user_data["kw_index"]    = 0
    ctx.user_data["cat_counter"] = 0
    ctx.user_data["seen_ids"]    = set()
    await show_product(update, ctx, is_update=True)


async def cmd_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"cat:{kw}")]
        for name, kw in CATEGORIES.items()
    ]
    await update.message.reply_text("📂 בחר קטגוריה:", reply_markup=InlineKeyboardMarkup(buttons))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *עזרה*\n\n"
        "/find — מחפש מוצרים חמים\n"
        "/category — בחר קטגוריה ספציפית\n\n"
        "✅ *שלח לקבוצה* — משלח קישור לקבוצת הגשר\n"
        "❌ *דלג* — מוצר הבא\n"
        "🔁 *חפש עוד* — קטגוריה הבאה",
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data     = query.data
    products = ctx.user_data.get("products", [])
    index    = ctx.user_data.get("index", 0)
    bot: Bot = ctx.bot

    # בחירת קטגוריה
    if data.startswith("cat:"):
        keyword = data.split("cat:")[1]
        await query.message.reply_text(f"🔍 מחפש...")
        found = await search_products(keyword)
        if not found:
            await query.message.reply_text("❌ לא נמצאו מוצרים.")
            return
        ctx.user_data["products"]    = found
        ctx.user_data["index"]       = 0
        ctx.user_data["cat_counter"] = 0
        await show_product(query, ctx, is_update=False)
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
            await query.message.reply_text(f"✅ קישור נשלח לקבוצה!")
            logger.info("קישור נשלח: %s", link)
        except Exception as e:
            await query.message.reply_text(f"❌ שגיאה: {e}")
            logger.error("שגיאה בשליחה: %s", e)

        ctx.user_data["index"] = index + 1
        await show_product(query, ctx, is_update=False)

    # דלג
    elif data == "action:skip":
        if products and index < len(products):
            seen = ctx.user_data.get("seen_ids", set())
            seen.add(products[index].get("product_id"))
            ctx.user_data["seen_ids"] = seen

        ctx.user_data["index"]       = index + 1
        ctx.user_data["cat_counter"] = ctx.user_data.get("cat_counter", 0) + 1

        # כל 5 מוצרים — עבור לקטגוריה הבאה
        if ctx.user_data["cat_counter"] >= 5:
            seen          = ctx.user_data.get("seen_ids", set())
            keywords_list = list(CATEGORIES.values())
            cat_names     = list(CATEGORIES.keys())
            kw_index      = (ctx.user_data.get("kw_index", 0) + 1) % len(keywords_list)
            ctx.user_data["kw_index"]    = kw_index
            ctx.user_data["cat_counter"] = 0
            await query.message.reply_text(f"🔄 עובר לקטגוריה: {cat_names[kw_index]}...")
            found = await search_products(keywords_list[kw_index])
            found = [p for p in found if p.get("product_id") not in seen]
            if found:
                ctx.user_data["products"] = found
                ctx.user_data["index"]    = 0

        await show_product(query, ctx, is_update=False)

    # חפש עוד
    elif data == "action:more":
        seen          = ctx.user_data.get("seen_ids", set())
        keywords_list = list(CATEGORIES.values())
        cat_names     = list(CATEGORIES.keys())
        kw_index      = (ctx.user_data.get("kw_index", 0) + 1) % len(keywords_list)
        ctx.user_data["kw_index"]    = kw_index
        ctx.user_data["cat_counter"] = 0
        await query.message.reply_text(f"🔍 עובר לקטגוריה: {cat_names[kw_index]}...")
        found = await search_products(keywords_list[kw_index])
        found = [p for p in found if p.get("product_id") not in seen]
        if not found:
            await query.message.reply_text("❌ לא נמצאו מוצרים חדשים. נסה /find.")
            return
        ctx.user_data["products"] = found
        ctx.user_data["index"]    = 0
        await show_product(query, ctx, is_update=False)


# ============================================================
#  Main
# ============================================================

def main():
    logger.info("מפעיל את HomeHacks Bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("find",     cmd_find))
    app.add_handler(CommandHandler("category", cmd_category))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("הבוט פועל! ממתין להודעות...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
