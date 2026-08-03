from flask import Blueprint, render_template, request, abort
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
    slug = slug.strip()

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
