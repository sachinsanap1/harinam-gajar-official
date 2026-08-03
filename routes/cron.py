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
