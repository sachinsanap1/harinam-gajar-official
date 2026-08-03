import os
import threading
import click
from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from dotenv import load_dotenv

load_dotenv()

from config import Config
from models import db, User, Category

login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Vercel's Python runtime is serverless: the filesystem is read-only
    # except /tmp, and /tmp itself is wiped between invocations — so
    # instance/ and static/uploads/ can't be created or relied on there.
    # VERCEL=1 is set automatically by the platform.
    on_vercel = os.environ.get("VERCEL") == "1"
    if on_vercel and not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL is not set. SQLite cannot be used on Vercel (the "
            "filesystem is read-only and ephemeral) — set DATABASE_URL to "
            "an external MySQL/Postgres database in the Vercel project's "
            "environment variables. See README 'Deploying to Vercel'."
        )
    if not on_vercel:
        os.makedirs(os.path.join(app.instance_path), exist_ok=True)
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.main import main_bp
    from routes.blog import blog_bp
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.api import api_bp
    from routes.saints import saints_bp
    from routes.kirtankars import kirtankars_bp
    from routes.reading import reading_bp
    from routes.abhang import abhang_bp
    from routes.cron import cron_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(saints_bp)
    app.register_blueprint(kirtankars_bp)
    app.register_blueprint(reading_bp)
    app.register_blueprint(abhang_bp)
    app.register_blueprint(cron_bp)
    csrf.exempt(api_bp)   # JSON API — protected by login_required + role check instead of CSRF tokens
    csrf.exempt(cron_bp)  # called by Vercel Cron (or any external scheduler), not a browser form —
                           # protected by a shared-secret token instead (see routes/cron.py)

    register_cli(app)
    register_context_processors(app)

    # In-process background work (APScheduler, a startup-sync thread) has
    # no persistent process to live in on Vercel — a serverless function
    # can be frozen or killed the instant the response is sent, and a new
    # invocation may land on a completely different container with no
    # memory of the last one. Both are skipped there; use Vercel Cron
    # hitting /cron/sync-youtube instead (see routes/cron.py + vercel.json).
    if not on_vercel:
        if os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true":
            register_scheduler(app)
        if os.environ.get("ENABLE_STARTUP_SYNC", "true").lower() == "true":
            run_startup_sync(app)

    return app


def run_startup_sync(app):
    """
    Fire-and-forget YouTube sync once at application startup, per the
    brief's "runs when the Flask application starts" requirement.
    - Skips silently if YOUTUBE_API_KEY isn't set (no error, no crash —
      the site works fine with an empty video list either way).
    - Skips if the API is temporarily unreachable; logs to the sync
      status (visible in Admin > Videos) rather than raising.
    - Runs in a background thread so it never delays the app from
      accepting requests.
    - Under Flask's debug reloader, only runs in the actual serving
      process (not the watcher process) to avoid syncing twice.
    """
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if not app.config.get("YOUTUBE_API_KEY"):
        return

    def _run():
        with app.app_context():
            from services.youtube_sync import full_sync, YouTubeSyncError
            try:
                full_sync()
                app.logger.info("Startup YouTube sync completed.")
            except YouTubeSyncError as e:
                # Never log the API key itself — YouTubeSyncError messages
                # are already scrubbed to status code + short body text.
                app.logger.warning(f"Startup YouTube sync skipped: {e}")

    threading.Thread(target=_run, daemon=True).start()


def register_context_processors(app):
    @app.context_processor
    def inject_site_globals():
        return {
            "site_name": app.config["SITE_NAME"],
            "site_tagline": app.config["SITE_TAGLINE"],
            "social_youtube": app.config["SOCIAL_YOUTUBE"],
            "social_instagram": app.config["SOCIAL_INSTAGRAM"],
            "social_facebook": app.config["SOCIAL_FACEBOOK"],
        }

    @app.template_global()
    def photo_version(dt):
        """
        Turns an 'updated at' datetime into an int for use as a ?v=... query
        param on photo/audio URLs, so the browser fetches the new file
        instead of serving a stale one from its long-lived cache after a
        re-upload. Falls back to 0 when there's no timestamp yet.
        """
        return int(dt.timestamp()) if dt else 0


def register_scheduler(app):
    """Optional background YouTube sync every N minutes (APScheduler)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from services.youtube_sync import full_sync, YouTubeSyncError

    scheduler = BackgroundScheduler()

    def job():
        with app.app_context():
            try:
                full_sync()
            except YouTubeSyncError as e:
                app.logger.warning(f"Scheduled YouTube sync failed: {e}")

    scheduler.add_job(job, "interval", minutes=app.config["YOUTUBE_SYNC_INTERVAL_MINUTES"])
    scheduler.start()


def slugify_for_seed(text):
    import re as _re
    text = text.lower().strip()
    text = _re.sub(r"[^\w\s\u0900-\u097F-]", "", text)
    return _re.sub(r"[\s_-]+", "-", text).strip("-")


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all tables. Run once: `flask init-db`"""
        db.create_all()
        for name in ["कीर्तन", "भजन", "अभंग", "प्रवचन", "वारी"]:
            slug = name  # devanagari slug kept readable; swap for transliteration if you prefer ASCII urls
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name, slug=slug))
        db.session.commit()
        click.echo("Database initialized.")

    @app.cli.command("migrate-db")
    def migrate_db():
        """
        One-time schema upgrade for this update: adds the new photo/audio
        upload columns to existing tables (db.create_all() only creates
        *missing* tables, it never alters ones that already exist), creates
        the new kirtankar_videos table, and drops the old sant_vachans
        table. Safe to run more than once. Run once after deploying:
        `flask migrate-db`
        """
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        def add_column_if_missing(table, column, ddl_type):
            if table not in existing_tables:
                return
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                click.echo(f"  + {table}.{column}")

        add_column_if_missing("sant_profiles", "photo_data", "BLOB")
        add_column_if_missing("sant_profiles", "photo_mimetype", "VARCHAR(100)")
        add_column_if_missing("sant_profiles", "photo_updated_at", "DATETIME")
        add_column_if_missing("kirtankar_profiles", "photo_updated_at", "DATETIME")
        add_column_if_missing("devotional_texts", "audio_data", "BLOB")
        add_column_if_missing("devotional_texts", "audio_mimetype", "VARCHAR(100)")
        add_column_if_missing("devotional_texts", "audio_public_id", "VARCHAR(300)")
        db.session.commit()

        db.create_all()  # picks up the new kirtankar_videos table

        if "sant_vachans" in existing_tables:
            db.session.execute(text("DROP TABLE sant_vachans"))
            db.session.commit()
            click.echo("  - dropped sant_vachans")

        click.echo("Database migrated.")

    @app.cli.command("seed-example-abhang")
    def seed_example_abhang():
        """
        Adds ONE clearly-labeled placeholder abhang so you can see the
        homepage rotation working immediately. This is NOT verified sacred
        text — replace/delete it from Admin > Abhangs and add your own
        verified collection (use the Bulk Paste importer for speed).
        Run once: `flask seed-example-abhang`
        """
        from models import Abhang
        if Abhang.query.count() > 0:
            click.echo("Abhangs table already has content — skipping seed.")
            return
        db.session.add(Abhang(
            text_marathi="[ही एक उदाहरण ओळ आहे — कृपया अ‍ॅडमिन पॅनलमधून खरे अभंग जोडा]",
            saint_name=None,
            source="Placeholder — replace via Admin > Abhangs",
            is_active=True,
        ))
        db.session.commit()
        click.echo("Added 1 placeholder abhang. Replace it via Admin > Abhangs, then use Bulk Paste to add your real collection.")

    @app.cli.command("create-admin")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(name, email, password):
        """Create the first administrator account. Run once: `flask create-admin`"""
        if User.query.filter_by(email=email.lower()).first():
            click.echo("A user with that email already exists.")
            return
        user = User(name=name, email=email.lower().strip(), role="super_admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin account created for {email}.")

    @app.cli.command("sync-admin-from-env")
    def sync_admin_from_env():
        """
        Create or update the primary administrator from ADMIN_NAME /
        ADMIN_EMAIL / ADMIN_PASSWORD in .env. Never hard-codes the password.
        Idempotent: if a super_admin already exists (matched by
        ADMIN_EMAIL, or the first super_admin if that email isn't found),
        it's updated in place — no duplicate accounts are created, and the
        password is only changed if ADMIN_PASSWORD is set.
        Run: `flask sync-admin-from-env`
        """
        name = os.environ.get("ADMIN_NAME")
        email = os.environ.get("ADMIN_EMAIL")
        password = os.environ.get("ADMIN_PASSWORD")

        if not email:
            click.echo("ADMIN_EMAIL is not set in .env — nothing to do.")
            return

        email = email.lower().strip()
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User.query.filter_by(role="super_admin").order_by(User.id).first()

        if user:
            user.email = email
            if name:
                user.name = name
            if password:
                user.set_password(password)
            user.role = "super_admin"
            db.session.commit()
            click.echo(f"Updated existing admin account -> {email}.")
        else:
            if not password:
                click.echo("No existing admin found and ADMIN_PASSWORD is not set — cannot create one. Add ADMIN_PASSWORD to .env and re-run.")
                return
            user = User(name=name or "Administrator", email=email, role="super_admin")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f"Created new admin account -> {email}.")

    @app.cli.command("seed-reading-library")
    def seed_reading_library():
        """
        Adds the 12 devotional reading titles from the brief as UNPUBLISHED
        drafts with a placeholder note in place of real text — never fake
        sacred text. Go to Admin > Reading Library, paste the verified
        Marathi text into each, and publish. Safe to re-run — skips titles
        that already exist. Run: `flask seed-reading-library`
        """
        from models import DevotionalText

        titles = [
            ("हनुमान चालीसा", "stotra"),
            ("श्री हरिपाठ", "haripath"),
            ("तारक मंत्र", "namasmaran"),
            ("पसायदान", "prayer"),
            ("श्री विठ्ठल आरती", "aarti"),
            ("श्री ज्ञानेश्वर महाराज आरती", "aarti"),
            ("श्री तुकाराम महाराज आरती", "aarti"),
            ("रामरक्षा स्तोत्र", "stotra"),
            ("नामस्मरण", "namasmaran"),
            ("काकड आरती", "aarti"),
            ("भूपाळी", "aarti"),
            ("प्रार्थना", "prayer"),
        ]
        added = 0
        for i, (title, category) in enumerate(titles):
            slug = slugify_for_seed(title)
            if DevotionalText.query.filter_by(slug=slug).first():
                continue
            db.session.add(DevotionalText(
                title=title,
                slug=slug,
                category=category,
                content_marathi="[मजकूर लवकरच जोडला जाईल — कृपया अ‍ॅडमिन पॅनलमधून खरा व सत्यापित मजकूर टाका आणि नंतर प्रकाशित करा.]",
                order_index=i,
                is_published=False,
            ))
            added += 1
        db.session.commit()
        click.echo(f"Added {added} draft reading entries (unpublished). Fill in verified text via Admin > Reading Library, then publish each.")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
