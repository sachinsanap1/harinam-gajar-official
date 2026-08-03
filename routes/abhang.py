from flask import Blueprint, render_template, abort
from models import Abhang
from services.abhang_rotation import get_todays_abhang

abhang_bp = Blueprint("abhang_public", __name__, url_prefix="/abhang")


@abhang_bp.route("/")
def today():
    abhang = get_todays_abhang()
    if not abhang:
        return render_template("abhang/today.html", abhang=None, prev_abhang=None, next_abhang=None)

    active = Abhang.query.filter_by(is_active=True).order_by(Abhang.id).all()
    ids = [a.id for a in active]
    idx = ids.index(abhang.id) if abhang.id in ids else -1
    prev_abhang = active[idx - 1] if idx > 0 else None
    next_abhang = active[idx + 1] if 0 <= idx < len(active) - 1 else None

    return render_template("abhang/today.html", abhang=abhang, prev_abhang=prev_abhang, next_abhang=next_abhang)


@abhang_bp.route("/archive")
def archive():
    abhangs = Abhang.query.filter_by(is_active=True).order_by(Abhang.id.desc()).all()
    return render_template("abhang/archive.html", abhangs=abhangs)


@abhang_bp.route("/<int:abhang_id>")
def view(abhang_id):
    abhang = Abhang.query.filter_by(id=abhang_id, is_active=True).first()
    if not abhang:
        abort(404)
    active = Abhang.query.filter_by(is_active=True).order_by(Abhang.id).all()
    ids = [a.id for a in active]
    idx = ids.index(abhang.id) if abhang.id in ids else -1
    prev_abhang = active[idx - 1] if idx > 0 else None
    next_abhang = active[idx + 1] if 0 <= idx < len(active) - 1 else None
    return render_template("abhang/today.html", abhang=abhang, prev_abhang=prev_abhang, next_abhang=next_abhang)
