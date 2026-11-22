import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from helper.database import codeflixbots
from config import Config, Txt


def _home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs •", callback_data="help")],
        [InlineKeyboardButton("• ᴜᴘᴅᴀᴛᴇs", url="https://t.me/Codeflix_Bots"),
         InlineKeyboardButton("sᴜᴘᴘᴏʀᴛ •", url="https://t.me/CodeflixSupport")],
        [InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
         InlineKeyboardButton("sᴏᴜʀᴄᴇ •", callback_data="source")],
    ])


def _help_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ғᴏʀᴍᴀᴛ •", callback_data="file_names")],
        [InlineKeyboardButton("• ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumbnail"),
         InlineKeyboardButton("ᴄᴀᴘᴛɪᴏɴ •", callback_data="caption")],
        [InlineKeyboardButton("• ᴍᴇᴛᴀᴅᴀᴛᴀ", callback_data="meta"),
         InlineKeyboardButton("ᴅᴏɴᴀᴛᴇ •", callback_data="donate")],
        [InlineKeyboardButton("• ʜᴏᴍᴇ", callback_data="home")],
    ])


async def _edit_page(message, text, reply_markup=None, disable_web_page_preview=True):
    """Edit either a text page or a photo caption, depending on message type."""
    if getattr(message, "media", None):
        return await message.edit_caption(caption=text, reply_markup=reply_markup)
    return await message.edit_text(
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


@Client.on_message(filters.private & filters.command("start"))
async def start(client: Client, message: Message):
    user = message.from_user
    await codeflixbots.add_user(client, message)
    buttons = _home_keyboard()
    if Config.START_PIC:
        await message.reply_photo(
            Config.START_PIC,
            caption=Txt.START_TXT.format(user.mention),
            reply_markup=buttons,
        )
    else:
        await message.reply_text(
            Txt.START_TXT.format(user.mention),
            reply_markup=buttons,
            disable_web_page_preview=True,
        )


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    data = query.data or ""
    user_id = query.from_user.id

    if data in {"close", "close_data"}:
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "home":
        text, keyboard = Txt.START_TXT.format(query.from_user.mention), _home_keyboard()
    elif data == "help":
        text, keyboard = Txt.HELP_TXT, _help_keyboard()
    elif data == "caption":
        text = Txt.CAPTION_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data == "file_names":
        template = await codeflixbots.get_format_template(user_id)
        text = Txt.FILE_NAME_TXT + (f"\n\n**Saved format:** `{template}`" if template else "")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data == "thumbnail":
        text = Txt.THUMBNAIL_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data in {"meta", "metadatax"}:
        text = Txt.SEND_METADATA
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data == "donate":
        text = Txt.DONATE_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data == "source":
        text = Txt.SOURCE_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="home")]])
    elif data == "about":
        text = Txt.ABOUT_TXT
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url="https://t.me/CodeflixSupport"),
             InlineKeyboardButton("ᴄᴏᴍᴍᴀɴᴅs •", callback_data="help")],
            [InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="home")],
        ])
    elif data == "premiumx":
        text = Txt.PREMIUM_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    elif data == "plans":
        text = Txt.PREPLANS_TXT
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="help")]])
    else:
        return await query.answer("Unknown menu action", show_alert=False)

    try:
        await _edit_page(query.message, text, keyboard)
        await query.answer()
    except Exception as error:
        await query.answer(f"Could not open this menu: {str(error)[:150]}", show_alert=True)


@Client.on_message(filters.command("donate"))
async def donation(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="help"), InlineKeyboardButton("ᴏᴡɴᴇʀ", url="https://t.me/sewxiy")]
    ])
    await message.reply_photo(
        photo="https://graph.org/file/1919fe077848bd0783d4c.jpg",
        caption=Txt.DONATE_TXT,
        reply_markup=buttons,
    )


@Client.on_message(filters.command("premium"))
async def getpremium(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("ᴏᴡɴᴇʀ", url="https://t.me/sewxiy"), InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")]
    ])
    await message.reply_photo(
        photo="https://graph.org/file/feebef43bbdf76e796b1b.jpg",
        caption=Txt.PREMIUM_TXT,
        reply_markup=buttons,
    )


@Client.on_message(filters.command("plan"))
async def premium(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("sᴇɴᴅ ss", url="https://t.me/sewxiy"), InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")]
    ])
    await message.reply_photo(
        photo="https://graph.org/file/8b50e21db819f296661b7.jpg",
        caption=Txt.PREPLANS_TXT,
        reply_markup=buttons,
    )


@Client.on_message(filters.command("bought") & filters.private)
async def bought(client, message):
    replied = message.reply_to_message
    if not replied or not replied.photo:
        return await message.reply_text(
            "**Reply to a payment screenshot with /bought.**"
        )
    if not Config.ADMIN_IDS:
        return await message.reply_text("**No admins are configured to receive this request.**")

    delivered = 0
    for admin_id in Config.ADMIN_IDS:
        try:
            await client.send_photo(
                chat_id=admin_id,
                photo=replied.photo.file_id,
                caption=(
                    f"<b>Payment review request</b>\n"
                    f"User: {message.from_user.mention}\n"
                    f"User ID: <code>{message.from_user.id}</code>\n"
                    f"Username: <code>{message.from_user.username or 'none'}</code>"
                ),
            )
            delivered += 1
        except Exception:
            continue
    await message.reply_text(f"**✅ Request sent to {delivered} admin(s).**")


@Client.on_message(filters.private & filters.command("help"))
async def help_command(client, message):
    await message.reply_text(
        text=Txt.HELP_TXT,
        disable_web_page_preview=True,
        reply_markup=_help_keyboard(),
    )
