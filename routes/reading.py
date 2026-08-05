import unicodedata
from flask import Blueprint, render_template, request, abort, Response
from models import DevotionalText

reading_bp = Blueprint("reading", __name__, url_prefix="/reading")

CATEGORY_LABELS = {
    "haripath": "हरिपाठ",
    "aarti": "आरती",
    "stotra": "स्तोत्र",
    "namasmaran": "नामस्मरण",
    "prayer": "प्रार्थना",
    "other": "इतर",
}


@reading_bp.route("/<int:text_id>/audio")
def audio(text_id):
    """
    Streams a reading's audio straight out of the database (same reasoning
    as kirtankars.photo — no writable disk on Vercel). Supports HTTP Range
    requests so the browser's <audio> element can seek/scrub instead of
    only being able to play from the start.
    """
    text = DevotionalText.query.get_or_404(text_id)
    if not text.audio_data:
        abort(404)
    data = text.audio_data
    mimetype = text.audio_mimetype or "audio/mpeg"
    total_length = len(data)

    range_header = request.headers.get("Range")
    if not range_header:
        return Response(
            data, mimetype=mimetype,
            headers={"Cache-Control": "public, max-age=31536000, immutable", "Accept-Ranges": "bytes"},
        )

    # Parse a single "bytes=start-end" range (the only form browsers send here).
    try:
        units, _, range_spec = range_header.partition("=")
        start_str, _, end_str = range_spec.partition("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else total_length - 1
        end = min(end, total_length - 1)
    except ValueError:
        abort(416)
    if start > end or start >= total_length:
        abort(416)

    chunk = data[start:end + 1]
    response = Response(chunk, status=206, mimetype=mimetype)
    response.headers["Content-Range"] = f"bytes {start}-{end}/{total_length}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(len(chunk))
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@reading_bp.route("/")
def library():
    category = request.args.get("category", "").strip()
    q = request.args.get("q", "").strip()

    query = DevotionalText.query.filter_by(is_published=True)

    if category:
        query = query.filter_by(category=category)

    if q:
        query = query.filter(
            DevotionalText.title.ilike(f"%{q}%")
        )

    texts = (
        query
        .order_by(
            DevotionalText.category,
            DevotionalText.order_index,
            DevotionalText.title
        )
        .all()
    )

    return render_template(
        "reading/library.html",
        texts=texts,
        category=category,
        q=q,
        category_labels=CATEGORY_LABELS,
    )


# Replace your old detail() function with this one
@reading_bp.route("/<slug>")
def detail(slug):
    # NFC-normalize the slug from the URL — see the comment on slugify()
    # in routes/admin.py for why Devanagari text needs this to match
    # reliably (composed vs decomposed combining marks look identical
    # but are different bytes otherwise).
    slug = unicodedata.normalize("NFC", slug).strip()

    text = DevotionalText.query.filter_by(
        slug=slug,
        is_published=True
    ).first()

    if not text:
        abort(404)

    siblings = (
        DevotionalText.query
        .filter_by(
            category=text.category,
            is_published=True
        )
        .order_by(
            DevotionalText.order_index,
            DevotionalText.title
        )
        .all()
    )

    ids = [t.id for t in siblings]

    idx = ids.index(text.id) if text.id in ids else -1

    prev_text = siblings[idx - 1] if idx > 0 else None

    next_text = (
        siblings[idx + 1]
        if 0 <= idx < len(siblings) - 1
        else None
    )

    return render_template(
        "reading/detail.html",
        text=text,
        prev_text=prev_text,
        next_text=next_text,
        category_labels=CATEGORY_LABELS,
    )
