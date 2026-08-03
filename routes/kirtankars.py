from flask import Blueprint, render_template, request, abort, Response
from models import db, KirtankarProfile

kirtankars_bp = Blueprint("kirtankars", __name__, url_prefix="/kirtankar")


@kirtankars_bp.route("/<int:kirtankar_id>/photo")
def photo(kirtankar_id):
    """
    Streams a kirtankar's photo straight out of Postgres (Neon) — there's
    no file on disk to serve, since Vercel's filesystem is read-only and
    ephemeral. Cached hard by the browser/CDN since the URL only changes
    when a new photo is actually uploaded (see admin.py's photo handling).
    """
    kirtankar = KirtankarProfile.query.get_or_404(kirtankar_id)
    if not kirtankar.photo_data:
        abort(404)
    return Response(
        kirtankar.photo_data,
        mimetype=kirtankar.photo_mimetype or "image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


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
