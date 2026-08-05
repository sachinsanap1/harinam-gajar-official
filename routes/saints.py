import unicodedata
from flask import Blueprint, render_template, request, abort, Response
from models import SantProfile

saints_bp = Blueprint("saints", __name__, url_prefix="/sant-charitra")


@saints_bp.route("/<int:saint_id>/photo")
def photo(saint_id):
    """
    Streams a saint's photo straight out of the database — mirrors
    kirtankars.photo. See that route's docstring for why (no writable
    disk on Vercel). Cache-Control is long + immutable because the URL
    is versioned with ?v=<timestamp> by the templates (see photo_version
    in app.py), so a new upload always gets a fresh URL.
    """
    saint = SantProfile.query.get_or_404(saint_id)
    if not saint.photo_data:
        abort(404)
    return Response(
        saint.photo_data,
        mimetype=saint.photo_mimetype or "image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


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
    slug = unicodedata.normalize("NFC", slug).strip()
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
