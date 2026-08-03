from flask import Blueprint, render_template, request, abort, Response
from models import DevotionalText


reading_bp = Blueprint(
    "reading",
    __name__,
    url_prefix="/reading"
)


CATEGORY_LABELS = {
    "haripath": "हरिपाठ",
    "aarti": "आरती",
    "stotra": "स्तोत्र",
    "namasmaran": "नामस्मरण",
    "prayer": "प्रार्थना",
    "other": "इतर",
}


# =========================================================
# AUDIO
# =========================================================

@reading_bp.route("/<int:text_id>/audio")
def audio(text_id):

    text = DevotionalText.query.get_or_404(text_id)

    # No audio uploaded
    if not text.audio_data:
        abort(404)

    # Convert PostgreSQL BYTEA / memoryview to normal bytes
    data = bytes(text.audio_data)

    # Use saved MIME type, otherwise use MP3
    mimetype = text.audio_mimetype or "audio/mpeg"

    total_length = len(data)

    # Safety check
    if total_length == 0:
        abort(404)

    # Browser may request only part of the audio
    range_header = request.headers.get("Range")

    # -----------------------------------------------------
    # Full audio request
    # -----------------------------------------------------

    if not range_header:

        response = Response(
            data,
            status=200,
            mimetype=mimetype,
        )

        response.headers["Content-Length"] = str(
            total_length
        )

        response.headers["Accept-Ranges"] = "bytes"

        response.headers["Cache-Control"] = (
            "public, max-age=3600"
        )

        return response

    # -----------------------------------------------------
    # HTTP Range request
    # Example:
    # Range: bytes=0-1023
    # -----------------------------------------------------

    try:

        units, _, range_spec = (
            range_header.partition("=")
        )

        # Only bytes ranges are supported
        if units.strip().lower() != "bytes":
            abort(416)

        start_str, _, end_str = (
            range_spec.partition("-")
        )

        # Example:
        # bytes=0-1000
        if start_str:

            start = int(
                start_str
            )

        else:

            start = 0

        if end_str:

            end = int(
                end_str
            )

        else:

            end = total_length - 1

        # Do not allow end beyond the file
        end = min(
            end,
            total_length - 1
        )

    except (
        ValueError,
        TypeError,
    ):

        abort(416)

    # Invalid range
    if (
        start < 0
        or start >= total_length
        or start > end
    ):

        abort(416)

    # Requested audio part
    chunk = data[
        start:end + 1
    ]

    response = Response(
        chunk,
        status=206,
        mimetype=mimetype,
    )

    response.headers[
        "Content-Range"
    ] = (
        f"bytes {start}-{end}/{total_length}"
    )

    response.headers[
        "Accept-Ranges"
    ] = "bytes"

    response.headers[
        "Content-Length"
    ] = str(
        len(chunk)
    )

    response.headers[
        "Cache-Control"
    ] = (
        "public, max-age=3600"
    )

    return response


# =========================================================
# READING LIBRARY
# =========================================================

@reading_bp.route("/")
def library():

    category = (
        request.args
        .get(
            "category",
            ""
        )
        .strip()
    )

    q = (
        request.args
        .get(
            "q",
            ""
        )
        .strip()
    )

    query = (
        DevotionalText.query
        .filter_by(
            is_published=True
        )
    )

    # Filter by category
    if category:

        query = (
            query
            .filter_by(
                category=category
            )
        )

    # Search by title
    if q:

        query = (
            query
            .filter(
                DevotionalText
                .title
                .ilike(
                    f"%{q}%"
                )
            )
        )

    texts = (
        query
        .order_by(
            DevotionalText.category,
            DevotionalText.order_index,
            DevotionalText.title,
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


# =========================================================
# READING DETAILS
# =========================================================

@reading_bp.route("/<slug>")
def detail(slug):

    slug = slug.strip()

    text = (
        DevotionalText.query
        .filter_by(
            slug=slug,
            is_published=True,
        )
        .first()
    )

    # Reading not found
    if not text:

        abort(404)

    # All readings in the same category
    siblings = (
        DevotionalText.query
        .filter_by(
            category=text.category,
            is_published=True,
        )
        .order_by(
            DevotionalText.order_index,
            DevotionalText.title,
        )
        .all()
    )

    ids = [
        item.id
        for item in siblings
    ]

    idx = (
        ids.index(text.id)
        if text.id in ids
        else -1
    )

    # Previous reading
    prev_text = (
        siblings[idx - 1]
        if idx > 0
        else None
    )

    # Next reading
    next_text = (
        siblings[idx + 1]
        if (
            idx >= 0
            and idx < len(siblings) - 1
        )
        else None
    )

    return render_template(
        "reading/detail.html",
        text=text,
        prev_text=prev_text,
        next_text=next_text,
        category_labels=CATEGORY_LABELS,
    )
