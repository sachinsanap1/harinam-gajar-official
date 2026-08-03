from flask import Blueprint, render_template, request, abort
from models import db, KirtankarProfile

kirtankars_bp = Blueprint("kirtankars", __name__, url_prefix="/kirtankar")


@kirtankars_bp.route("/")
def list_kirtankars():
    q = request.args.get("q", "").strip()
    district = request.args.get("district", "").strip()

    query = KirtankarProfile.query.filter_by(is_published=True)
    if q:
        query = query.filter(KirtankarProfile.full_name.ilike(f"%{q}%"))
    if district:
        query = query.filter(KirtankarProfile.district == district)

    kirtankars = query.order_by(KirtankarProfile.full_name).all()
    districts = [
        d[0] for d in KirtankarProfile.query.with_entities(KirtankarProfile.district)
        .filter(KirtankarProfile.district.isnot(None)).distinct().all() if d[0]
    ]
    return render_template("kirtankars/list.html", kirtankars=kirtankars, districts=districts, q=q, district=district)


@kirtankars_bp.route("/<slug>")
def detail(slug):
    kirtankar = KirtankarProfile.query.filter_by(slug=slug, is_published=True).first()
    if not kirtankar:
        abort(404)
    kirtankar.view_count = (kirtankar.view_count or 0) + 1
    db.session.commit()
    related = (
        KirtankarProfile.query.filter(KirtankarProfile.is_published == True, KirtankarProfile.id != kirtankar.id)
        .filter(KirtankarProfile.district == kirtankar.district)
        .limit(4)
        .all()
    )
    return render_template("kirtankars/detail.html", kirtankar=kirtankar, related=related)
