"""
Audio uploads for the Reading Library, stored on Cloudinary instead of in
the database:

    Admin selects audio
        -> Audio uploads to Cloudinary
        -> Cloudinary returns audio URL
        -> Save only that URL (+ its public_id, so we can delete/replace
           it later) in the database
        -> Website plays audio straight from that URL
"""
import cloudinary
import cloudinary.uploader
from flask import current_app

ALLOWED_AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "ogg", "wav", "webm"}
MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB

_configured = False


def _ensure_configured():
    """Cloudinary's SDK is configured lazily, on first use, from the
    app's config — avoids needing app context at import time."""
    global _configured
    if _configured:
        return
    cloudinary.config(
        cloud_name=current_app.config["CLOUDINARY_CLOUD_NAME"],
        api_key=current_app.config["CLOUDINARY_API_KEY"],
        api_secret=current_app.config["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    _configured = True


class CloudinaryUploadError(ValueError):
    """User-facing message — caught in routes/admin.py and flashed as-is."""
    pass


def upload_audio(file_storage):
    """
    Validates and uploads an audio file (from request.files.get('audio'))
    straight to Cloudinary. Returns (secure_url, public_id), or
    (None, None) if no file was chosen.
    """
    if not file_storage or not file_storage.filename:
        return None, None

    if not current_app.config.get("CLOUDINARY_CLOUD_NAME"):
        raise CloudinaryUploadError(
            "Audio uploads aren't configured yet — set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in your environment."
        )

    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise CloudinaryUploadError("Audio must be an MP3, M4A/AAC, OGG, WAV, or WEBM file.")

    # Peek at the size without loading the whole thing into memory twice.
    file_storage.stream.seek(0, 2)  # seek to end
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_AUDIO_BYTES:
        raise CloudinaryUploadError("Audio file is too large — please use a file under 15 MB.")
    if size == 0:
        return None, None

    _ensure_configured()
    try:
        result = cloudinary.uploader.upload(
            file_storage,
            resource_type="video",  # Cloudinary files audio under "video"
            folder="harinam-gajar/reading-audio",
        )
    except Exception as e:
        raise CloudinaryUploadError(f"Audio upload to Cloudinary failed: {e}")

    return result["secure_url"], result["public_id"]


def delete_audio(public_id):
    """Best-effort delete of a previously-uploaded clip. Never raises —
    a failed cleanup shouldn't block the admin from saving their edit."""
    if not public_id:
        return
    try:
        _ensure_configured()
        cloudinary.uploader.destroy(public_id, resource_type="video")
    except Exception:
        current_app.logger.warning("Cloudinary delete failed for %s", public_id, exc_info=True)
