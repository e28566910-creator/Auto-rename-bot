"""Concurrent, collision-safe file renaming with metadata and thumbnail preservation."""
import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image
from pyrogram import Client, filters

from config import Config
from helper.database import codeflixbots
from helper.filename_utils import build_renamed_filename
from helper.utils import clear_progress_for_message, humanbytes, progress_for_pyrogram
from plugins.antinsfw import check_anti_nsfw

logger = logging.getLogger(__name__)

_TRANSFER_SEMAPHORE = asyncio.Semaphore(Config.MAX_CONCURRENT_FILES)
_active_jobs = set()
_processed_messages = set()
_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm", ".ts", ".mpg", ".mpeg"}
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma"}


def _media_details(message):
    media = message.document or message.video or message.audio
    if not media:
        return None
    filename = getattr(media, "file_name", None) or message.caption or f"telegram_file_{media.file_unique_id}"
    if not os.path.splitext(filename)[1]:
        if message.video:
            filename += ".mp4"
        elif message.audio:
            filename += ".mp3"
    return {
        "file_id": media.file_id,
        "file_name": filename,
        "file_size": getattr(media, "file_size", 0) or 0,
        "media_type": "video" if message.video else "audio" if message.audio else "document",
        "duration": getattr(media, "duration", 0) or 0,
    }


async def _cleanup(*paths):
    for path in paths:
        if path:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                logger.warning("Could not remove temporary file %s", path, exc_info=True)


def _format_caption(template, filename, size, duration):
    if not template:
        return f"**{filename}**"
    try:
        size_text = humanbytes(size)
        rendered = template.format(**{
            "filename": filename,
            "filesize": size_text,
            "duration": duration,
            # Exact legacy tokens used by the original repository.
            "ꜰɪʟᴇɴᴀᴍᴇ": filename,
            "ꜰɪʟᴇꜱɪᴢᴇ": size_text,
            "ꜰɪʟᴇsɪᴢᴇ": size_text,
        })
        return rendered[:1024]
    except (KeyError, ValueError, IndexError):
        logger.warning("Caption template has an invalid placeholder; using filename caption")
        return f"**{filename}**"


async def _prepare_thumbnail(client, user_id, message, workdir):
    thumb_path = None
    saved_path = Path(Config.STORAGE_DIR) / "thumbnails" / f"{user_id}.jpg"
    if saved_path.is_file():
        thumb_path = str(saved_path)
    else:
        saved_file_id = await codeflixbots.get_thumbnail(user_id)
        if saved_file_id:
            try:
                thumb_path = await client.download_media(saved_file_id, file_name=str(Path(workdir) / "saved_thumb"))
            except Exception:
                logger.warning("Saved Telegram thumbnail file_id could not be downloaded", exc_info=True)
        media = message.video or message.document or message.audio
        source_thumbs = getattr(media, "thumbs", None) if media else None
        if not thumb_path and source_thumbs:
            try:
                thumb_path = await client.download_media(
                    source_thumbs[0].file_id,
                    file_name=str(Path(workdir) / "source_thumb"),
                )
            except Exception:
                logger.warning("Source media thumbnail could not be downloaded", exc_info=True)

    if not thumb_path or not os.path.isfile(thumb_path):
        return None
    try:
        with Image.open(thumb_path) as image:
            image = image.convert("RGB")
            image.thumbnail((320, 320))
            output = str(Path(workdir) / "upload_thumb.jpg")
            for quality in (88, 78, 68, 58):
                image.save(output, "JPEG", quality=quality, optimize=True)
                if os.path.getsize(output) <= 190 * 1024:
                    break
        if thumb_path != str(saved_path):
            await _cleanup(thumb_path)
        return output
    except Exception:
        logger.warning("Thumbnail could not be prepared; uploading without custom thumbnail", exc_info=True)
        if thumb_path != str(saved_path):
            await _cleanup(thumb_path)
        return None


async def _remux_metadata(source_path, output_path, user_id):
    """Copy every stream and existing metadata; never re-encode media."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is not installed")

    metadata = {
        "title": await codeflixbots.get_title(user_id),
        "artist": await codeflixbots.get_artist(user_id),
        "author": await codeflixbots.get_author(user_id),
    }
    stream_metadata = {
        "v": await codeflixbots.get_video(user_id),
        "a": await codeflixbots.get_audio(user_id),
        "s": await codeflixbots.get_subtitle(user_id),
    }

    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", source_path,
               "-map", "0", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]
    for key, value in metadata.items():
        if value:
            command.extend(["-metadata", f"{key}={value}"])
    for stream, value in stream_metadata.items():
        if value:
            command.extend([f"-metadata:s:{stream}", f"title={value}"])
    command.extend(["-loglevel", "error", output_path])

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        try:
            os.remove(output_path)
        except OSError:
            pass
        raise RuntimeError(stderr.decode("utf-8", "replace")[-1500:] or "FFmpeg metadata remux failed")
    return output_path


async def _process_rename(client, message, details, template):
    user_id = message.from_user.id
    original_name = details["file_name"]
    workdir = None
    status = None
    thumbnail_path = None
    try:
        if await check_anti_nsfw(original_name, message):
            return

        workdir = tempfile.mkdtemp(prefix=f"rename_{user_id}_", dir=Config.TEMP_DIR)
        status = await message.reply_text("**📥 Queued for renaming...**")
        async with _TRANSFER_SEMAPHORE:
            final_name = build_renamed_filename(template, original_name)
            source_target = str(Path(workdir) / ("source" + Path(original_name).suffix))
            await status.edit_text("**📥 Downloading file...**")
            downloaded_path = await client.download_media(
                message,
                file_name=source_target,
                progress=progress_for_pyrogram,
                progress_args=("📥 Downloading", status, time.monotonic()),
            )
            if not downloaded_path or not os.path.isfile(downloaded_path):
                raise RuntimeError("Telegram download did not produce a local file")

            final_path = str(Path(workdir) / final_name)
            metadata_state = await codeflixbots.get_metadata(user_id)
            extension = Path(original_name).suffix.lower()
            can_remux = extension in (_VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS)
            if str(metadata_state).lower() in {"on", "true", "1"} and can_remux:
                await status.edit_text("**🧩 Preserving streams and updating metadata...**")
                metadata_path = str(Path(workdir) / ("metadata_" + final_name))
                try:
                    await _remux_metadata(downloaded_path, metadata_path, user_id)
                    os.replace(metadata_path, final_path)
                except Exception as error:
                    logger.warning("Metadata remux skipped; retaining original file unchanged: %s", error)
                    os.replace(downloaded_path, final_path)
            else:
                # Atomic local rename avoids a second full-file disk write.
                os.replace(downloaded_path, final_path)

            thumbnail_path = await _prepare_thumbnail(client, user_id, message, workdir)
            caption_template = await codeflixbots.get_caption(user_id)
            caption = _format_caption(
                caption_template,
                final_name,
                details["file_size"],
                details["duration"],
            )
            preference = (await codeflixbots.get_media_preference(user_id) or "").lower()
            extension = Path(final_name).suffix.lower()
            compatible_preference = (
                preference == "document"
                or (preference == "video" and extension in _VIDEO_EXTENSIONS)
                or (preference == "audio" and extension in _AUDIO_EXTENSIONS)
            )
            output_type = preference if compatible_preference else details["media_type"]

            await status.edit_text("**📤 Uploading renamed file...**")
            common = {
                "chat_id": message.chat.id,
                "caption": caption,
                "thumb": thumbnail_path,
                "progress": progress_for_pyrogram,
                "progress_args": ("📤 Uploading", status, time.monotonic()),
            }
            if output_type == "video":
                await client.send_video(video=final_path, **common)
            elif output_type == "audio":
                await client.send_audio(audio=final_path, **common)
            else:
                await client.send_document(document=final_path, **common)
            await status.edit_text(f"**✅ Renamed and uploaded**\n\n`{final_name}`")
    except Exception as error:
        logger.exception("Rename job failed for %s", original_name)
        error_text = f"**❌ Could not process this file**\n\n`{original_name}`\n\n{str(error)[:700]}"
        try:
            if status is not None:
                await status.edit_text(error_text)
            else:
                await message.reply_text(error_text)
        except Exception:
            logger.debug("Could not send rename failure message", exc_info=True)
    finally:
        if status is not None:
            clear_progress_for_message(status)
        if thumbnail_path and os.path.isfile(thumbnail_path):
            await _cleanup(thumbnail_path)
        if workdir and os.path.isdir(workdir):
            await asyncio.to_thread(shutil.rmtree, workdir, True)
        _processed_messages.discard((message.chat.id, message.id))


@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    user = message.from_user
    if not user:
        return

    details = _media_details(message)
    if not details:
        return

    # File-sort mode takes precedence and never downloads or renames the file.
    if await codeflixbots.is_sort_session_active(user.id):
        count = await codeflixbots.add_sort_file(
            user.id,
            message.chat.id,
            message.id,
            details["file_id"],
            details["file_name"],
            details["media_type"],
        )
        if count > 0:
            if count == 1 or count % 10 == 0:
                await message.reply_text(f"**✅ Collected {count} file(s) for sorting.**")
            return
        # The session may have been stopped between the active check and insert.
        # Fall through to normal rename handling instead of silently dropping the file.

    template = await codeflixbots.get_format_template(user.id)
    if not template:
        return await message.reply_text("**Set your rename format first:**\n`/autorename Naruto S{season}E{episode} {quality}`")

    identity = (message.chat.id, message.id)
    if identity in _processed_messages:
        return
    _processed_messages.add(identity)
    task = asyncio.create_task(_process_rename(client, message, details, template))
    _active_jobs.add(task)
    task.add_done_callback(_active_jobs.discard)
