from flask import Blueprint, render_template, request, abort
from models import SantProfile

saints_bp = Blueprint("saints", __name__, url_prefix="/sant-charitra")


@saints_bp.route("/")
def list_saints():
    q = request.args.get("q", "").strip()
    tradition = request.args.get("tradition", "").strip()

    query = SantProfile.query.filter_by(is_published=True)
    if q:
        query = query.filter(SantProfile.name.ilike(f"%{q}%"))
    if tradition:
        query = query.filter(SantProfile.tradition == tradition)

    saints = query.order_by(SantProfile.name).all()
    traditions = [
        t[0] for t in SantProfile.query.with_entities(SantProfile.tradition)
        .filter(SantProfile.tradition.isnot(None)).distinct().all() if t[0]
    ]
    return render_template("saints/list.html", saints=saints, traditions=traditions, q=q, tradition=tradition)


@saints_bp.route("/<slug>")
def detail(slug):
    saint = SantProfile.query.filter_by(slug=slug, is_published=True).first()
    if not saint:
        abort(404)
    related = (
        SantProfile.query.filter(SantProfile.is_published == True, SantProfile.id != saint.id)
        .filter(SantProfile.tradition == saint.tradition)
        .limit(4)
        .all()
    )
    return render_template("saints/detail.html", saint=saint, related=related)
