"""
Cron-triggered sync endpoint — replaces the in-process APScheduler/startup
thread on serverless platforms like Vercel, where nothing survives between
invocations.

Protected by a shared secret (CRON_SECRET env var), checked two ways so it
works with different schedulers:
  - Authorization: Bearer <CRON_SECRET>  — Vercel automatically sends this
    header on any request it makes to a route listed in vercel.json's
    "crons" array, as long as CRON_SECRET is set as an environment
    variable on the Vercel project (verified against Vercel's current
    docs at vercel.com/docs/cron-jobs/manage-cron-jobs — re-check there
    if this ever stops matching, since platform behavior can change).
  - ?secret=<CRON_SECRET> query param — for any other scheduler (GitHub
    Actions on a cron schedule, cron-job.org, EasyCron, etc.) that can't
    set custom headers, or for manually testing with curl.

Free/Hobby Vercel accounts are limited to one cron job total — this
project defines exactly one (/cron/sync-youtube), so that's fine as-is.
Check your plan's frequency limits in the Vercel dashboard before relying
on the 6-hour schedule in vercel.json; adjust the cron expression there
if your plan only allows a coarser interval, or use an external free
scheduler hitting this same endpoint instead.
"""
from flask import Blueprint, request, jsonify, current_app
from services.youtube_sync import full_sync, YouTubeSyncError

cron_bp = Blueprint("cron", __name__, url_prefix="/cron")


def _authorized():
    expected = current_app.config.get("CRON_SECRET")
    if not expected:
        return False  # refuse to run an unprotected sync endpoint

    auth_header = request.headers.get("Authorization", "")
    if auth_header == f"Bearer {expected}":
        return True

    if request.args.get("secret") == expected:
        return True

    return False


@cron_bp.route("/sync-youtube")
def sync_youtube():
    if not _authorized():
        return jsonify({"error": "Unauthorized. Set CRON_SECRET and pass it as a Bearer token or ?secret=."}), 401

    try:
        result = full_sync()
        return jsonify({
            "ok": True,
            "already_running": result["already_running"],
            "added": result["uploads_added"],
            "updated": result["uploads_updated"],
        })
    except YouTubeSyncError as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@cron_bp.route("/migrate-db")
def migrate_db_route():
    """
    Same one-time schema upgrade as `flask migrate-db`, but reachable by
    just visiting the URL in a browser — for when there's no easy way to
    run a terminal command against the production database (e.g. a
    managed DB that only accepts connections from inside Vercel).

    Visit once (with your real CRON_SECRET):
        https://<your-site>/cron/migrate-db?secret=<CRON_SECRET>

    Safe to run more than once — it only adds columns/tables that are
    missing and skips ones that already exist. Consider removing this
    route (or at least rotating CRON_SECRET) once you've confirmed it
    worked, since it's schema-changing even though it's secret-protected.
    """
    if not _authorized():
        return jsonify({"error": "Unauthorized. Set CRON_SECRET and pass it as ?secret=."}), 401

    from models import db
    from sqlalchemy import inspect, text

    log = []
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()

    dialect = db.engine.dialect.name  # 'postgresql', 'mysql', or 'sqlite'
    TYPE_MAP = {
        "BLOB": {"postgresql": "BYTEA"},
        "DATETIME": {"postgresql": "TIMESTAMP"},
    }

    def add_column_if_missing(table, column, ddl_type):
        if table not in existing_tables:
            return
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column not in cols:
            real_type = TYPE_MAP.get(ddl_type, {}).get(dialect, ddl_type)
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {real_type}"))
            log.append(f"added {table}.{column}")

    try:
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
            log.append("dropped sant_vachans")
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e), "done_so_far": log}), 500

    return jsonify({"ok": True, "changes": log or ["nothing to do — already up to date"]})


@cron_bp.route("/debug-reading-slug")
def debug_reading_slug():
    """
    Temporary diagnostic — shows the exact Unicode codepoints of the slug
    received in the URL vs. every reading-library slug stored in the DB,
    so an invisible mismatch (extra character, different Unicode form,
    etc.) shows up directly instead of us guessing from how text *looks*.

    Visit (with your real CRON_SECRET):
        /cron/debug-reading-slug?slug=हनुमान-चालीसा&secret=<CRON_SECRET>

    Safe to remove this route once the mismatch is found and fixed.
    """
    if not _authorized():
        return jsonify({"error": "Unauthorized. Set CRON_SECRET and pass it as ?secret=."}), 401

    from models import DevotionalText

    incoming = request.args.get("slug", "")

    def describe(s):
        return {
            "text": s,
            "length": len(s),
            "codepoints": [f"U+{ord(c):04X}" for c in s],
        }

    rows = DevotionalText.query.with_entities(
        DevotionalText.id, DevotionalText.title, DevotionalText.slug, DevotionalText.is_published
    ).all()

    # Run the *exact* query routes/reading.py's detail() runs, so we see
    # specifically whether that one succeeds or not — not just a raw
    # slug comparison.
    production_query_result = DevotionalText.query.filter_by(slug=incoming, is_published=True).first()

    # Also check which route Flask's URL map actually resolves /reading/<slug>
    # to — rules out something else (a static handler, a catch-all, a
    # duplicate registration) intercepting before reaching reading.detail.
    from flask import current_app
    try:
        adapter = current_app.url_map.bind(request.host)
        endpoint, args = adapter.match(f"/reading/{incoming}", method="GET")
        route_resolution = {"endpoint": endpoint, "args": args}
    except Exception as e:
        route_resolution = {"error": str(e)}

    return jsonify({
        "incoming_slug": describe(incoming),
        "exact_match_found": any(r.slug == incoming for r in rows),
        "production_query_result": (
            {"id": production_query_result.id, "title": production_query_result.title}
            if production_query_result else None
        ),
        "route_resolution": route_resolution,
        "all_stored_slugs": [
            {"id": r.id, "title": r.title, "is_published": r.is_published, **describe(r.slug)}
            for r in rows
        ],
    })
