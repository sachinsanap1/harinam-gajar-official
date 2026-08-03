import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """
    All secrets/config come from environment variables (.env).
    Nothing sensitive is hard-coded here — see .env.example.
    """
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-.env")

    # --- Database ---
    # Defaults to local SQLite so the project runs out of the box.
    # For production, set DATABASE_URL to a MySQL URI, e.g.:
    # mysql+pymysql://user:password@host:3306/harinam_gajar
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'instance', 'harinam_gajar.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- YouTube Data API v3 ---
    YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
    YOUTUBE_CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "HarinamGajarOfficial")
    YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")  # resolved & cached on first sync
    YOUTUBE_SYNC_INTERVAL_MINUTES = int(os.environ.get("YOUTUBE_SYNC_INTERVAL_MINUTES", "15"))

    # --- Google API key (server-side only, never sent to the frontend) ---
    # If YouTube Data API v3 is enabled on the same Google Cloud key as
    # YOUTUBE_API_KEY, you can leave this unset and reuse that one — this
    # is a separate variable only for future Google integrations that
    # aren't wired up yet (see README "Limitations").
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

    # --- Cron-triggered sync (routes/cron.py) — required on serverless
    # platforms like Vercel, where there's no in-process scheduler.
    # Leave unset locally if you're not using the /cron/sync-youtube route.
    CRON_SECRET = os.environ.get("CRON_SECRET", "")

    # --- Primary admin account (see `flask sync-admin-from-env` in app.py) ---
    # Read directly from os.environ at CLI-run time, not cached here, so
    # they're never baked into a WSGI process that started before .env
    # was updated. Never hard-code ADMIN_PASSWORD — set it only in .env.

    # --- Mail / SMTP ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")

    # --- Uploads ---
    UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # --- Cloudinary (audio file storage — see services/cloudinary_upload.py) ---
    # Get these three from your Cloudinary dashboard (cloudinary.com/console),
    # top-right "Account Details" card. Set them in .env / Vercel env vars.
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

    # --- Session / security ---
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_ENABLED = True

    # --- Site identity (editable later from Admin > Settings; these are first-run defaults) ---
    SITE_NAME = os.environ.get("SITE_NAME", "हरिनाम गजर | Harinam Gajar Official")
    SITE_TAGLINE = "मराठी कीर्तन • भजन • अभंग • वारकरी संस्कृती"
    SOCIAL_YOUTUBE = "https://www.youtube.com/@HarinamGajarOfficial"
    SOCIAL_INSTAGRAM = "https://www.instagram.com/harinamgajar/"
    SOCIAL_FACEBOOK = "https://www.facebook.com/harinamgajar/"
