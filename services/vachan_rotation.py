"""
Daily Sant Vachan ("आजचा संतविचार") rotation — same locking pattern as
services/abhang_rotation.py: one quote per calendar day, same for every
visitor, admin can override.
"""
from datetime import date
from models import db, SantVachan, Setting

SETTING_DATE_KEY = "vachan_today_date"
SETTING_ID_KEY = "vachan_today_id"


def get_todays_vachan():
    today_str = date.today().isoformat()
    locked_date = Setting.get(SETTING_DATE_KEY)
    locked_id = Setting.get(SETTING_ID_KEY)

    if locked_date == today_str and locked_id:
        vachan = SantVachan.query.get(int(locked_id))
        if vachan and vachan.is_active:
            return vachan

    return _pick_and_lock_for_today()


def _pick_and_lock_for_today():
    active = SantVachan.query.filter_by(is_active=True).order_by(SantVachan.id).all()
    if not active:
        return None
    day_index = date.today().toordinal() % len(active)
    chosen = active[day_index]
    _lock_today(chosen.id)
    return chosen


def _lock_today(vachan_id):
    Setting.set(SETTING_DATE_KEY, date.today().isoformat())
    Setting.set(SETTING_ID_KEY, str(vachan_id))


def set_todays_vachan(vachan_id):
    vachan = SantVachan.query.get_or_404(vachan_id)
    _lock_today(vachan.id)
    return vachan
