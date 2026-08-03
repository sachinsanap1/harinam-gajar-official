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
# AUDIO MIME TYPE DETECTION
# =========================================================

def detect_audio_mimetype(data, saved_mimetype=None):

    # Convert PostgreSQL memoryview/BYTEA to bytes
    data = bytes(data)

    # MP3 with ID3 metadata
    if data.startswith(b"ID3"):
        return "audio/mpeg"

    # MP3 without ID3 metadata
    if len(data) >= 2:
        if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
            return "audio/mpeg"

    # WAV
    if (
        len(data) >= 12
        and data[0:4] == b"RIFF"
        and data[8:12] == b"WAVE"
    ):
        return "audio/wav"

    # OGG
    if data.startswith(b"OggS"):
        return "audio/ogg"

    # WEBM / Matroska
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"

    # M4A / AAC / MP4 files normally contain "ftyp"
    if (
        len(data) >= 12
        and data[4:8] == b"ftyp"
    ):
        return "audio/mp4"

    # Use the MIME type saved in the database
    if saved_mimetype:

        saved_mimetype = (
            saved_mimetype
            .strip()
            .lower()
        )

        mime_map = {
            "audio/mp3": "audio/mpeg",
            "audio/mpeg": "audio/mpeg",
            "audio/x-mpeg": "audio/mpeg",

            "audio/m4a": "audio/mp4",
            "audio/x-m4a": "audio/mp4",
            "audio/mp4": "audio/mp4",

            "audio/aac": "audio/aac",

            "audio/ogg": "audio/ogg",
            "application/ogg": "audio/ogg",

            "audio/wav": "audio/wav",
            "audio/x-wav": "audio/wav",

            "audio/webm": "audio/webm",
        }

        return mime_map.get(
            saved_mimetype,
            saved_mimetype
        )

    # Final fallback
    return "application/octet-stream"


# =========================================================
# AUDIO ROUTE
# =========================================================

@reading_bp.route("/<int:text_id>/audio")
def audio(text_id):

    text = DevotionalText.query.get_or_404(text_id)

    if not text.audio_data:
        abort(404)

    data = bytes(text.audio_data)

    if not data:
        abort(404)

    total_length = len(data)

    # The downloaded file was confirmed to be MP3
    mimetype = "audio/mpeg"

    range_header = request.headers.get("Range")

    # Full file request
    if not range_header:

        response = Response(
            data,
            status=200,
            content_type=mimetype
        )

        response.headers["Content-Length"] = str(
            total_length
        )

        response.headers["Accept-Ranges"] = "bytes"

        response.headers["Content-Disposition"] = (
            "inline"
        )

        response.headers["Cache-Control"] = (
            "no-store"
        )

        return response

    # Browser Range request
    try:

        range_value = (
            range_header
            .replace("bytes=", "")
            .split(",")[0]
            .strip()
        )

        start_text, end_text = (
            range_value
            .split("-", 1)
        )

        start = (
            int(start_text)
            if start_text
            else 0
        )

        end = (
            int(end_text)
            if end_text
            else total_length - 1
        )

        end = min(
            end,
            total_length - 1
        )

    except (
        ValueError,
        IndexError
    ):

        abort(416)

    if (
        start < 0
        or start >= total_length
        or end < start
    ):

        abort(416)

    chunk = data[
        start:end + 1
    ]

    response = Response(
        chunk,
        status=206,
        content_type=mimetype
    )

    response.headers["Content-Range"] = (
        f"bytes {start}-{end}/{total_length}"
    )

    response.headers["Content-Length"] = str(
        len(chunk)
    )

    response.headers["Accept-Ranges"] = "bytes"

    response.headers["Content-Disposition"] = (
        "inline"
    )

    response.headers["Cache-Control"] = (
        "no-store"
    )

    return response    # =====================================================
    # RANGE AUDIO RESPONSE
    # =====================================================

    try:

        unit, _, range_value = (
            range_header.partition("=")
        )

        if (
            unit.strip()
            .lower()
            != "bytes"
        ):
            abort(416)

        # Only use the first range
        range_value = (
            range_value
            .split(",")[0]
            .strip()
        )

        start_text, _, end_text = (
            range_value.partition("-")
        )

        # -------------------------------------------------
        # Example:
        # Range: bytes=1000-2000
        # -------------------------------------------------

        if start_text:

            start = int(
                start_text
            )

            if end_text:

                end = int(
                    end_text
                )

            else:

                end = (
                    total_length - 1
                )

        # -------------------------------------------------
        # Example:
        # Range: bytes=-500
        # Last 500 bytes
        # -------------------------------------------------

        else:

            suffix_length = int(
                end_text
            )

            if suffix_length <= 0:
                abort(416)

            suffix_length = min(
                suffix_length,
                total_length
            )

            start = (
                total_length
                - suffix_length
            )

            end = (
                total_length - 1
            )

        # Keep end inside the audio
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
        or end < start
    ):

        abort(416)

    # Requested part
    chunk = data[
        start:end + 1
    ]

    response = Response(
        chunk,
        status=206,
        content_type=mimetype
    )

    response.headers[
        "Content-Range"
    ] = (
        f"bytes "
        f"{start}-{end}/"
        f"{total_length}"
    )

    response.headers[
        "Content-Length"
    ] = str(
        len(chunk)
    )

    response.headers[
        "Accept-Ranges"
    ] = "bytes"

    response.headers[
        "Cache-Control"
    ] = "no-cache"

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

    if category:

        query = (
            query
            .filter_by(
                category=category
            )
        )

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
# READING DETAIL
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

    if not text:

        abort(404)

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

    prev_text = (
        siblings[idx - 1]
        if idx > 0
        else None
    )

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
