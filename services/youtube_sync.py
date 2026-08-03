"""
YouTube sync service.

Talks to the real YouTube Data API v3. Requires YOUTUBE_API_KEY in .env.
Called from:
  - Admin > Videos > "Sync now" button (routes/admin.py)
  - Once at application startup, in a background thread (app.py) — if
    YOUTUBE_API_KEY is set. Failures here never crash the app; the site
    works fine with zero videos synced, it just shows empty states.
  - A scheduled job (APScheduler, wired in app.py) every
    YOUTUBE_SYNC_INTERVAL_MINUTES, if ENABLE_SCHEDULER=true.

No video is ever hand-entered. This module is the single source of truth
for how videos/shorts/live status enter the database.

Status tracking: every full_sync() call records added/updated/skipped
counts, a timestamp, and any error into the Setting table, so the admin
Videos page can show "Last synced: ... — 3 added, 1 updated" without a
separate SyncLog table.

Concurrency: the "only one sync at a time" lock is stored in the Setting
table (sync_last_status == "running"), NOT an in-memory threading.Lock —
on a serverless platform like Vercel, each invocation can land in a
completely separate process with no shared memory, so an in-process lock
would give zero real protection. A DB-backed lock has one sharp edge: if
a process is killed hard mid-sync (e.g. a serverless function timeout)
without its `finally` block running, the lock could stay "running"
forever. To handle that, a lock older than SYNC_LOCK_STALE_MINUTES is
treated as abandoned and can be re-acquired.
"""
import re
from datetime import datetime, timezone, timedelta
from flask import current_app
import requests
from models import db, Video, Setting

API_BASE = "https://www.googleapis.com/youtube/v3"

SYNC_LOCK_STALE_MINUTES = 10

STATUS_LAST_RUN = "sync_last_run_at"
STATUS_LAST_STATUS = "sync_last_status"      # success | error | running
STATUS_LAST_ADDED = "sync_last_added"
STATUS_LAST_UPDATED = "sync_last_updated"
STATUS_LAST_SKIPPED = "sync_last_skipped"
STATUS_LAST_ERROR = "sync_last_error"


class YouTubeSyncError(Exception):
    pass


def is_sync_running():
    """
    True only if the lock is "running" AND recent — a stale "running"
    status (older than SYNC_LOCK_STALE_MINUTES, meaning whatever process
    set it never got to release it) does not count as running.
    """
    status = Setting.get(STATUS_LAST_STATUS)
    if status != "running":
        return False
    last_run = Setting.get(STATUS_LAST_RUN)
    if not last_run:
        return False
    try:
        started_at = datetime.fromisoformat(last_run)
    except ValueError:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started_at < timedelta(minutes=SYNC_LOCK_STALE_MINUTES)


def get_sync_status():
    """Read-only snapshot for the admin dashboard/videos page."""
    return {
        "last_run_at": Setting.get(STATUS_LAST_RUN),
        "last_status": Setting.get(STATUS_LAST_STATUS),
        "added": Setting.get(STATUS_LAST_ADDED, "0"),
        "updated": Setting.get(STATUS_LAST_UPDATED, "0"),
        "skipped": Setting.get(STATUS_LAST_SKIPPED, "0"),
        "error": Setting.get(STATUS_LAST_ERROR),
        "is_running": is_sync_running(),
    }


def _record_status(status, added=0, updated=0, skipped=0, error=None):
    Setting.set(STATUS_LAST_RUN, datetime.now(timezone.utc).isoformat())
    Setting.set(STATUS_LAST_STATUS, status)
    Setting.set(STATUS_LAST_ADDED, str(added))
    Setting.set(STATUS_LAST_UPDATED, str(updated))
    Setting.set(STATUS_LAST_SKIPPED, str(skipped))
    Setting.set(STATUS_LAST_ERROR, error or "")


def _api_key():
    key = current_app.config.get("YOUTUBE_API_KEY")
    if not key:
        raise YouTubeSyncError(
            "YOUTUBE_API_KEY is not set. Add it in Admin > Settings or in .env."
        )
    return key


def _get(endpoint, params):
    params = {**params, "key": _api_key()}
    resp = requests.get(f"{API_BASE}/{endpoint}", params=params, timeout=15)
    if resp.status_code != 200:
        # Never leak the API key value itself into an error message/log.
        raise YouTubeSyncError(f"YouTube API error ({endpoint}): {resp.status_code} {resp.text[:300]}")
    return resp.json()


def resolve_channel_id():
    cached = current_app.config.get("YOUTUBE_CHANNEL_ID")
    if cached:
        return cached

    handle = current_app.config["YOUTUBE_CHANNEL_HANDLE"].lstrip("@")
    data = _get("channels", {"part": "id,contentDetails,statistics,snippet", "forHandle": handle})
    items = data.get("items", [])
    if not items:
        raise YouTubeSyncError(f"Could not resolve channel handle @{handle}")
    channel_id = items[0]["id"]
    current_app.config["YOUTUBE_CHANNEL_ID"] = channel_id
    return channel_id


def _iso8601_duration_to_seconds(duration):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return 0
    h, m, s = (int(x) if x else 0 for x in match.groups())
    return h * 3600 + m * 60 + s


def _upsert_video(item, kind_hint=None, live_details=None):
    """Returns (video, is_new) — is_new distinguishes "added" from "updated"
    for sync status reporting, and duplicates (same youtube_id) always
    resolve to an update rather than a second row, since youtube_id is
    the unique key."""
    vid_id = item["id"] if isinstance(item["id"], str) else item["id"].get("videoId")
    if not vid_id:
        return None, False

    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})

    duration_seconds = _iso8601_duration_to_seconds(content.get("duration", ""))
    kind = kind_hint or ("short" if duration_seconds and duration_seconds <= 60 else "video")

    is_live = False
    if live_details:
        is_live = live_details.get("actual_end") is None and live_details.get("actual_start") is not None

    video = Video.query.filter_by(youtube_id=vid_id).first()
    is_new = video is None
    if not video:
        video = Video(youtube_id=vid_id)
        db.session.add(video)

    video.kind = "live" if is_live else kind
    video.title = snippet.get("title", "")[:300]
    video.description = snippet.get("description", "")
    thumbs = snippet.get("thumbnails", {})
    video.thumbnail_url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
    published = snippet.get("publishedAt")
    if published:
        video.published_at = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
    video.duration_seconds = duration_seconds
    video.view_count = int(stats.get("viewCount", 0) or 0)
    video.like_count = int(stats.get("likeCount", 0) or 0)
    video.tags = ",".join(snippet.get("tags", [])[:20])
    video.is_live_now = is_live
    video.synced_at = datetime.now(timezone.utc)
    return video, is_new


def sync_uploads(max_results=25):
    """Returns (added_count, updated_count)."""
    channel_id = resolve_channel_id()

    data = _get("channels", {"part": "contentDetails", "id": channel_id})
    items = data.get("items", [])
    if not items:
        raise YouTubeSyncError("Could not find uploads playlist for channel.")
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    playlist_data = _get(
        "playlistItems",
        {"part": "snippet,contentDetails", "playlistId": uploads_playlist, "maxResults": max_results},
    )
    # De-duplicate video IDs within this batch itself (defensive — playlist
    # items are normally already unique, but this guarantees no duplicate
    # row is ever attempted even if YouTube's API ever returns a repeat).
    seen = set()
    video_ids = []
    for pi in playlist_data.get("items", []):
        vid = pi["contentDetails"]["videoId"]
        if vid not in seen:
            seen.add(vid)
            video_ids.append(vid)

    if not video_ids:
        return 0, 0

    details = _get(
        "videos",
        {"part": "snippet,contentDetails,statistics,liveStreamingDetails", "id": ",".join(video_ids)},
    )

    added, updated = 0, 0
    for item in details.get("items", []):
        live = item.get("liveStreamingDetails")
        live_details = None
        if live:
            live_details = {
                "actual_start": live.get("actualStartTime"),
                "actual_end": live.get("actualEndTime"),
            }
        video, is_new = _upsert_video(item, live_details=live_details)
        if video:
            added += 1 if is_new else 0
            updated += 0 if is_new else 1

    db.session.commit()
    return added, updated


def sync_live_status():
    channel_id = resolve_channel_id()

    data = _get(
        "search",
        {"part": "snippet", "channelId": channel_id, "eventType": "live", "type": "video", "maxResults": 1},
    )
    items = data.get("items", [])

    Video.query.filter_by(is_live_now=True).update({"is_live_now": False})

    if not items:
        db.session.commit()
        return None

    video_id = items[0]["id"]["videoId"]
    details = _get("videos", {"part": "snippet,liveStreamingDetails", "id": video_id})
    live_items = details.get("items", [])
    if not live_items:
        db.session.commit()
        return None

    video, _ = _upsert_video(live_items[0], kind_hint="live", live_details={"actual_start": "x", "actual_end": None})
    db.session.commit()
    return video


def full_sync():
    """
    Run everything: uploads + live status. Used by the manual Sync Now
    button, the cron endpoint, and (non-Vercel) the startup sync/scheduler.
    Records status/counts to Setting either way. Refuses to start a second
    sync while one is already running per the DB-backed lock above (returns
    a "skipped, already running" result instead of raising, so overlapping
    triggers don't look like a hard failure) — except when the existing
    "running" lock is stale, in which case it's treated as abandoned and
    a fresh sync proceeds.
    """
    if is_sync_running():
        return {"already_running": True, "uploads_added": 0, "uploads_updated": 0, "live_video": None}

    try:
        _record_status("running")
        added, updated = sync_uploads()
        live = None
        try:
            live = sync_live_status()
        except YouTubeSyncError:
            pass  # live check is best-effort; don't fail the whole sync over it
        _record_status("success", added=added, updated=updated)
        return {"already_running": False, "uploads_added": added, "uploads_updated": updated, "live_video": live.title if live else None}
    except YouTubeSyncError as e:
        _record_status("error", error=str(e))
        raise
