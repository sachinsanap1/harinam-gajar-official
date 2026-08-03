"""
Abhang-of-the-day rotation.

Behavior:
  - Every calendar day, one active Abhang is shown on the homepage.
  - The choice is "locked" into Settings the first time it's requested each
    day, so every visitor sees the same one all day (not re-randomized per
    request) and it's stable across app restarts.
  - Admin can override today's pick at any time via Admin > Abhang > "Set as
    Today's Abhang" — that overwrites the lock immediately.
"""
from datetime import date
from models import db, Abhang, Setting

SETTING_DATE_KEY = "abhang_today_date"
SETTING_ID_KEY = "abhang_today_id"


def get_todays_abhang():
    """Return today's Abhang (Abhang or None if none exist yet)."""
    today_str = date.today().isoformat()
    locked_date = Setting.get(SETTING_DATE_KEY)
    locked_id = Setting.get(SETTING_ID_KEY)

    if locked_date == today_str and locked_id:
        abhang = Abhang.query.get(int(locked_id))
        if abhang and abhang.is_active:
            return abhang
        # fall through and re-pick if the locked one was deleted/deactivated

    return _pick_and_lock_for_today()


def _pick_and_lock_for_today():
    active = Abhang.query.filter_by(is_active=True).order_by(Abhang.id).all()
    if not active:
        return None

    day_index = date.today().toordinal() % len(active)
    chosen = active[day_index]
    _lock_today(chosen.id)
    return chosen


def _lock_today(abhang_id):
    Setting.set(SETTING_DATE_KEY, date.today().isoformat())
    Setting.set(SETTING_ID_KEY, str(abhang_id))


def set_todays_abhang(abhang_id):
    """Admin override: force a specific abhang to be today's, regardless of rotation."""
    abhang = Abhang.query.get_or_404(abhang_id)
    _lock_today(abhang.id)
    return abhang
