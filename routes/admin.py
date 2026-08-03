import re
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from werkzeug.datastructures import FileStorage
from flask_login import login_required, current_user
from models import (
    db, Video, Post, Category, Abhang, User,
    SantProfile, KirtankarProfile, KirtankarVideo, DevotionalText, ContactMessage,
)
from forms import PostForm
from services.youtube_sync import full_sync, YouTubeSyncError, get_sync_status
from services.abhang_rotation import set_todays_abhang, get_todays_abhang

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def slugify(text):
    text = text.lower().strip()
    # Keep word chars, spaces, hyphens, AND the Devanagari block explicitly —
    # \w alone strips Marathi matras/virama (combining marks), garbling slugs
    # like "श्री" -> "शर". Whitelisting U+0900-U+097F keeps them intact.
    text = re.sub(r"[^\w\s\u0900-\u097F-]", "", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


_PLACEHOLDER_TEXT = {"none", "null", "n/a", "na", "undefined"}


def clean_text(value):
    """
    Strips whitespace and treats literal placeholder words like "None" or
    "null" as blank. These sometimes get pasted in wholesale from
    AI-generated draft bios that print "None" for a field left empty —
    without this, "None" gets saved as if it were a real value (e.g. a
    real URL), which then renders as a broken link/image on the site.
    """
    value = (value or "").strip()
    if value.lower() in _PLACEHOLDER_TEXT:
        return None
    return value or None


# --------------------------------------------------------------------
# Photo uploads — Vercel's filesystem is read-only/ephemeral, so uploaded
# photos can't be saved to disk there. Instead the raw bytes go straight
# into Postgres (Neon) via KirtankarProfile.photo_data / photo_mimetype,
# and get streamed back out by the kirtankars.photo route.
# --------------------------------------------------------------------
ALLOWED_PHOTO_MIMETYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_PHOTO_BYTES = 4 * 1024 * 1024  # 4 MB — keeps individual DB rows small

ALLOWED_AUDIO_MIMETYPES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/aac",
    "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm",
}
MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB — a few minutes of audio, keeps rows reasonable


def read_uploaded_photo(file_storage: "FileStorage"):
    """
    Validate + read an uploaded photo from request.files.get(...).
    Returns (bytes, mimetype), or (None, None) if no file was chosen.
    Raises ValueError with a user-facing message on invalid input.
    """
    if not file_storage or not file_storage.filename:
        return None, None
    mimetype = (file_storage.mimetype or "").lower()
    if mimetype not in ALLOWED_PHOTO_MIMETYPES:
        raise ValueError("Photo must be a JPEG, PNG, WEBP, or GIF image.")
    data = file_storage.read()
    if not data:
        return None, None
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photo is too large — please use an image under 4 MB.")
    return data, mimetype


def read_uploaded_audio(file_storage: "FileStorage"):
    """
    Validate + read an uploaded audio file from request.files.get(...).
    Returns (bytes, mimetype), or (None, None) if no file was chosen.
    Raises ValueError with a user-facing message on invalid input.
    """
    if not file_storage or not file_storage.filename:
        return None, None
    mimetype = (file_storage.mimetype or "").lower()
    if mimetype not in ALLOWED_AUDIO_MIMETYPES:
        raise ValueError("Audio must be an MP3, M4A/AAC, OGG, WAV, or WEBM file.")
    data = file_storage.read()
    if not data:
        return None, None
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Audio file is too large — please use a file under 15 MB.")
    return data, mimetype


def _parse_kirtankar_video_rows(form):
    """
    Reads the repeatable 'लोकप्रिय कीर्तने' rows (title + YouTube link) posted
    from the kirtankar admin form as parallel arrays, skipping any row where
    both fields are blank.
    """
    titles = form.getlist("kirtan_title[]")
    urls = form.getlist("kirtan_youtube_url[]")
    rows = []
    for i, (title, url) in enumerate(zip(titles, urls)):
        title = (title or "").strip()
        url = (url or "").strip()
        if not title and not url:
            continue
        if not title or not url:
            raise ValueError("Each popular kirtan needs both a title and a YouTube link.")
        rows.append((title, url, i))
    return rows


@admin_bp.before_request
@login_required
def require_login():
    pass


@admin_bp.route("/")
def dashboard():
    stats = {
        "videos": Video.query.count(),
        "shorts": Video.query.filter_by(kind="short").count(),
        "posts": Post.query.count(),
        "published_posts": Post.query.filter_by(status="published").count(),
        "abhangs": Abhang.query.count(),
        "saints": SantProfile.query.count(),
        "kirtankars": KirtankarProfile.query.count(),
        "reading_texts": DevotionalText.query.count(),
        "unread_messages": ContactMessage.query.filter_by(is_read=False).count(),
    }
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_videos = Video.query.order_by(Video.synced_at.desc()).limit(5).all()
    todays_abhang = get_todays_abhang()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_posts=recent_posts,
        recent_videos=recent_videos,
        todays_abhang=todays_abhang,
    )


# --------------------------------------------------------------------
# Video manager — sync only, no manual video entry
# --------------------------------------------------------------------
@admin_bp.route("/videos")
def videos():
    all_videos = Video.query.order_by(Video.published_at.desc()).all()
    return render_template("admin/videos.html", videos=all_videos, sync_status=get_sync_status())


@admin_bp.route("/videos/sync", methods=["POST"])
def sync_videos():
    try:
        result = full_sync()
        if result["already_running"]:
            flash("A sync is already in progress — try again in a moment.", "error")
        else:
            flash(
                f"Sync complete: {result['uploads_added']} added, {result['uploads_updated']} updated.",
                "success",
            )
    except YouTubeSyncError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.videos"))


@admin_bp.route("/videos/<int:video_id>/feature", methods=["POST"])
def feature_video(video_id):
    Video.query.update({"is_featured": False})
    video = Video.query.get_or_404(video_id)
    video.is_featured = True
    db.session.commit()
    flash(f'"{video.title}" set as featured video.', "success")
    return redirect(url_for("admin.videos"))


# --------------------------------------------------------------------
# Blog manager
# --------------------------------------------------------------------
@admin_bp.route("/blog")
def blog_list():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("admin/blog_list.html", posts=posts)


@admin_bp.route("/blog/new", methods=["GET", "POST"])
def blog_new():
    form = PostForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        slug = form.slug.data.strip() or slugify(form.title.data)
        post = Post(
            title=form.title.data,
            slug=slug,
            excerpt=form.excerpt.data,
            content_html=form.content_html.data,
            category_id=form.category_id.data or None,
            status=form.status.data,
            author_id=current_user.id,
            meta_title=form.meta_title.data or form.title.data[:70],
            meta_description=form.meta_description.data or (form.excerpt.data or "")[:160],
            meta_keywords=form.meta_keywords.data,
        )
        if form.status.data == "published":
            post.published_at = datetime.utcnow()
        db.session.add(post)
        db.session.commit()
        flash("Post created.", "success")
        return redirect(url_for("admin.blog_list"))
    return render_template("admin/blog_form.html", form=form, post=None)


@admin_bp.route("/blog/<int:post_id>/edit", methods=["GET", "POST"])
def blog_edit(post_id):
    post = Post.query.get_or_404(post_id)
    form = PostForm(obj=post)
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        post.title = form.title.data
        post.slug = form.slug.data.strip() or slugify(form.title.data)
        post.excerpt = form.excerpt.data
        post.content_html = form.content_html.data
        post.category_id = form.category_id.data or None
        was_published = post.status == "published"
        post.status = form.status.data
        if post.status == "published" and not was_published:
            post.published_at = datetime.utcnow()
        post.meta_title = form.meta_title.data
        post.meta_description = form.meta_description.data
        post.meta_keywords = form.meta_keywords.data
        db.session.commit()
        flash("Post updated.", "success")
        return redirect(url_for("admin.blog_list"))
    return render_template("admin/blog_form.html", form=form, post=post)


@admin_bp.route("/blog/<int:post_id>/delete", methods=["POST"])
def blog_delete(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "success")
    return redirect(url_for("admin.blog_list"))


# --------------------------------------------------------------------
# Abhang manager
# --------------------------------------------------------------------
@admin_bp.route("/abhangs")
def abhang_list():
    abhangs = Abhang.query.order_by(Abhang.id.desc()).all()
    todays_abhang = get_todays_abhang()
    return render_template("admin/abhang_list.html", abhangs=abhangs, todays_abhang=todays_abhang)


@admin_bp.route("/abhangs/new", methods=["GET", "POST"])
def abhang_new():
    if request.method == "POST":
        text = request.form.get("text_marathi", "").strip()
        if not text:
            flash("Abhang text is required.", "error")
        else:
            abhang = Abhang(
                text_marathi=text,
                saint_name=request.form.get("saint_name", "").strip() or None,
                source=request.form.get("source", "").strip() or None,
                meaning=request.form.get("meaning", "").strip() or None,
                is_active=bool(request.form.get("is_active")),
            )
            db.session.add(abhang)
            db.session.commit()
            flash("Abhang added.", "success")
            return redirect(url_for("admin.abhang_list"))
    return render_template("admin/abhang_form.html", abhang=None)


@admin_bp.route("/abhangs/<int:abhang_id>/edit", methods=["GET", "POST"])
def abhang_edit(abhang_id):
    abhang = Abhang.query.get_or_404(abhang_id)
    if request.method == "POST":
        text = request.form.get("text_marathi", "").strip()
        if not text:
            flash("Abhang text is required.", "error")
        else:
            abhang.text_marathi = text
            abhang.saint_name = request.form.get("saint_name", "").strip() or None
            abhang.source = request.form.get("source", "").strip() or None
            abhang.meaning = request.form.get("meaning", "").strip() or None
            abhang.is_active = bool(request.form.get("is_active"))
            db.session.commit()
            flash("Abhang updated.", "success")
            return redirect(url_for("admin.abhang_list"))
    return render_template("admin/abhang_form.html", abhang=abhang)


@admin_bp.route("/abhangs/<int:abhang_id>/delete", methods=["POST"])
def abhang_delete(abhang_id):
    abhang = Abhang.query.get_or_404(abhang_id)
    db.session.delete(abhang)
    db.session.commit()
    flash("Abhang deleted.", "success")
    return redirect(url_for("admin.abhang_list"))


@admin_bp.route("/abhangs/<int:abhang_id>/set-today", methods=["POST"])
def abhang_set_today(abhang_id):
    abhang = set_todays_abhang(abhang_id)
    flash(f'Today\u2019s abhang set. It will stay on the homepage until midnight.', "success")
    return redirect(url_for("admin.abhang_list"))


@admin_bp.route("/abhangs/bulk", methods=["GET", "POST"])
def abhang_bulk():
    """
    Paste many abhangs at once, one per block, blocks separated by a blank
    line. Optional 'Saint Name | Source' line right after the text is
    parsed as attribution if it starts with '@'.

    Example block:
        पंढरीचा वास चंद्रभागे स्नान...
        @Sant Tukaram | Tukaram Gatha
    """
    if request.method == "POST":
        raw = request.form.get("bulk_text", "")
        # Normalize Windows (\r\n) and old-Mac (\r) line endings to \n first —
        # otherwise a blank line pasted from Notepad/Word ("\r\n\r\n") never
        # matches a plain "\n\n" split and everything collapses into one block.
        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        # Split on any run of 2+ newlines (handles single or multiple blank lines).
        blocks = [b.strip() for b in re.split(r"\n\s*\n", normalized) if b.strip()]
        created = 0
        for block in blocks:
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            attribution_line = None
            if lines[-1].strip().startswith("@"):
                attribution_line = lines.pop().strip()[1:]
            text = "\n".join(lines).strip()
            if not text:
                continue
            saint_name, source = None, None
            if attribution_line:
                parts = [p.strip() for p in attribution_line.split("|")]
                saint_name = parts[0] or None
                source = parts[1] if len(parts) > 1 else None
            db.session.add(Abhang(text_marathi=text, saint_name=saint_name, source=source, is_active=True))
            created += 1
        db.session.commit()
        flash(f"Added {created} abhangs.", "success")
        return redirect(url_for("admin.abhang_list"))
    return render_template("admin/abhang_bulk.html")


# --------------------------------------------------------------------
# Sant Charitra manager
# --------------------------------------------------------------------
@admin_bp.route("/saints")
def saint_list():
    saints = SantProfile.query.order_by(SantProfile.name).all()
    return render_template("admin/saint_list.html", saints=saints)


@admin_bp.route("/saints/new", methods=["GET", "POST"])
def saint_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            photo_data, photo_mimetype = read_uploaded_photo(request.files.get("photo"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/saint_form.html", saint=None)
        if not name:
            flash("Saint name is required.", "error")
        else:
            slug = request.form.get("slug", "").strip() or slugify(name)
            saint = SantProfile(
                name=name,
                slug=slug,
                alt_names=request.form.get("alt_names", "").strip() or None,
                photo_data=photo_data,
                photo_mimetype=photo_mimetype,
                photo_updated_at=datetime.utcnow() if photo_data else None,
                tradition=request.form.get("tradition", "").strip() or None,
                birth_info=request.form.get("birth_info", "").strip() or None,
                samadhi_info=request.form.get("samadhi_info", "").strip() or None,
                birthplace=request.form.get("birthplace", "").strip() or None,
                important_places=request.form.get("important_places", "").strip() or None,
                short_bio=request.form.get("short_bio", "").strip() or None,
                full_bio=request.form.get("full_bio", "").strip() or None,
                teachings=request.form.get("teachings", "").strip() or None,
                literary_works=request.form.get("literary_works", "").strip() or None,
                meta_description=request.form.get("meta_description", "").strip() or None,
                is_published=bool(request.form.get("is_published")),
            )
            db.session.add(saint)
            db.session.commit()
            flash("Saint profile added.", "success")
            return redirect(url_for("admin.saint_list"))
    return render_template("admin/saint_form.html", saint=None)


@admin_bp.route("/saints/<int:saint_id>/edit", methods=["GET", "POST"])
def saint_edit(saint_id):
    saint = SantProfile.query.get_or_404(saint_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            photo_data, photo_mimetype = read_uploaded_photo(request.files.get("photo"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/saint_form.html", saint=saint)
        if not name:
            flash("Saint name is required.", "error")
        else:
            saint.name = name
            saint.slug = request.form.get("slug", "").strip() or slugify(name)
            saint.alt_names = request.form.get("alt_names", "").strip() or None
            if photo_data:
                # A new file was uploaded — replace the stored photo.
                saint.photo_data = photo_data
                saint.photo_mimetype = photo_mimetype
                saint.photo_updated_at = datetime.utcnow()
            elif request.form.get("remove_photo"):
                # "Remove current photo" was ticked and no replacement was given.
                saint.photo_data = None
                saint.photo_mimetype = None
                saint.photo_updated_at = datetime.utcnow()
            # else: no file chosen and box not ticked -> keep existing photo as-is.
            saint.tradition = request.form.get("tradition", "").strip() or None
            saint.birth_info = request.form.get("birth_info", "").strip() or None
            saint.samadhi_info = request.form.get("samadhi_info", "").strip() or None
            saint.birthplace = request.form.get("birthplace", "").strip() or None
            saint.important_places = request.form.get("important_places", "").strip() or None
            saint.short_bio = request.form.get("short_bio", "").strip() or None
            saint.full_bio = request.form.get("full_bio", "").strip() or None
            saint.teachings = request.form.get("teachings", "").strip() or None
            saint.literary_works = request.form.get("literary_works", "").strip() or None
            saint.meta_description = request.form.get("meta_description", "").strip() or None
            saint.is_published = bool(request.form.get("is_published"))
            db.session.commit()
            flash("Saint profile updated.", "success")
            return redirect(url_for("admin.saint_list"))
    return render_template("admin/saint_form.html", saint=saint)


@admin_bp.route("/saints/<int:saint_id>/delete", methods=["POST"])
def saint_delete(saint_id):
    saint = SantProfile.query.get_or_404(saint_id)
    db.session.delete(saint)
    db.session.commit()
    flash("Saint profile deleted.", "success")
    return redirect(url_for("admin.saint_list"))


# --------------------------------------------------------------------
# Kirtankar / Maharaj manager
# --------------------------------------------------------------------
@admin_bp.route("/kirtankars")
def kirtankar_list():
    kirtankars = KirtankarProfile.query.order_by(KirtankarProfile.full_name).all()
    return render_template("admin/kirtankar_list.html", kirtankars=kirtankars)


@admin_bp.route("/kirtankars/new", methods=["GET", "POST"])
def kirtankar_new():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        try:
            photo_data, photo_mimetype = read_uploaded_photo(request.files.get("photo"))
            video_rows = _parse_kirtankar_video_rows(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/kirtankar_form.html", kirtankar=None)
        if not full_name:
            flash("Name is required.", "error")
        else:
            slug = request.form.get("slug", "").strip() or slugify(full_name)
            kirtankar = KirtankarProfile(
                full_name=full_name,
                slug=slug,
                honorific=clean_text(request.form.get("honorific")),
                photo_data=photo_data,
                photo_mimetype=photo_mimetype,
                photo_updated_at=datetime.utcnow() if photo_data else None,
                short_intro=clean_text(request.form.get("short_intro")),
                full_bio=clean_text(request.form.get("full_bio")),
                village=clean_text(request.form.get("village")),
                district=clean_text(request.form.get("district")),
                state=clean_text(request.form.get("state")),
                popular_kirtans=clean_text(request.form.get("popular_kirtans")),
                special_topics=clean_text(request.form.get("special_topics")),
                youtube_url=clean_text(request.form.get("youtube_url")),
                facebook_url=clean_text(request.form.get("facebook_url")),
                instagram_url=clean_text(request.form.get("instagram_url")),
                website_url=clean_text(request.form.get("website_url")),
                contact_info=clean_text(request.form.get("contact_info")),
                is_contact_public=bool(request.form.get("is_contact_public")),
                meta_description=clean_text(request.form.get("meta_description")),
                is_published=bool(request.form.get("is_published")),
            )
            db.session.add(kirtankar)
            db.session.flush()  # assigns kirtankar.id, needed for the video rows below
            for title, url, order_index in video_rows:
                db.session.add(KirtankarVideo(
                    kirtankar_id=kirtankar.id, title=title, youtube_url=url, order_index=order_index,
                ))
            db.session.commit()
            flash("Kirtankar profile added.", "success")
            return redirect(url_for("admin.kirtankar_list"))
    return render_template("admin/kirtankar_form.html", kirtankar=None)


@admin_bp.route("/kirtankars/<int:kirtankar_id>/edit", methods=["GET", "POST"])
def kirtankar_edit(kirtankar_id):
    kirtankar = KirtankarProfile.query.get_or_404(kirtankar_id)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        try:
            photo_data, photo_mimetype = read_uploaded_photo(request.files.get("photo"))
            video_rows = _parse_kirtankar_video_rows(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/kirtankar_form.html", kirtankar=kirtankar)
        if not full_name:
            flash("Name is required.", "error")
        else:
            kirtankar.full_name = full_name
            kirtankar.slug = request.form.get("slug", "").strip() or slugify(full_name)
            kirtankar.honorific = request.form.get("honorific", "").strip() or None
            if photo_data:
                # A new file was uploaded — replace the stored photo. photo_updated_at
                # changes the photo URL's cache-busting query string, so the browser
                # actually re-fetches the new image instead of showing the old one
                # from cache (the photo route serves it with a 1-year cache header).
                kirtankar.photo_data = photo_data
                kirtankar.photo_mimetype = photo_mimetype
                kirtankar.photo_updated_at = datetime.utcnow()
            elif request.form.get("remove_photo"):
                # "Remove current photo" was ticked and no replacement was given.
                kirtankar.photo_data = None
                kirtankar.photo_mimetype = None
                kirtankar.photo_updated_at = datetime.utcnow()
            # else: no file chosen and box not ticked -> keep existing photo as-is.
            kirtankar.short_intro = clean_text(request.form.get("short_intro"))
            kirtankar.full_bio = clean_text(request.form.get("full_bio"))
            kirtankar.village = clean_text(request.form.get("village"))
            kirtankar.district = clean_text(request.form.get("district"))
            kirtankar.state = clean_text(request.form.get("state"))
            kirtankar.popular_kirtans = clean_text(request.form.get("popular_kirtans"))
            kirtankar.special_topics = clean_text(request.form.get("special_topics"))
            kirtankar.youtube_url = clean_text(request.form.get("youtube_url"))
            kirtankar.facebook_url = clean_text(request.form.get("facebook_url"))
            kirtankar.instagram_url = clean_text(request.form.get("instagram_url"))
            kirtankar.website_url = clean_text(request.form.get("website_url"))
            kirtankar.contact_info = clean_text(request.form.get("contact_info"))
            kirtankar.is_contact_public = bool(request.form.get("is_contact_public"))
            kirtankar.meta_description = clean_text(request.form.get("meta_description"))
            kirtankar.is_published = bool(request.form.get("is_published"))
            # Replace the popular-kirtans video list wholesale with what was submitted.
            KirtankarVideo.query.filter_by(kirtankar_id=kirtankar.id).delete()
            for title, url, order_index in video_rows:
                db.session.add(KirtankarVideo(
                    kirtankar_id=kirtankar.id, title=title, youtube_url=url, order_index=order_index,
                ))
            db.session.commit()
            flash("Kirtankar profile updated.", "success")
            return redirect(url_for("admin.kirtankar_list"))
    return render_template("admin/kirtankar_form.html", kirtankar=kirtankar)


@admin_bp.route("/kirtankars/<int:kirtankar_id>/delete", methods=["POST"])
def kirtankar_delete(kirtankar_id):
    kirtankar = KirtankarProfile.query.get_or_404(kirtankar_id)
    db.session.delete(kirtankar)
    db.session.commit()
    flash("Kirtankar profile deleted.", "success")
    return redirect(url_for("admin.kirtankar_list"))


# --------------------------------------------------------------------
# Devotional Reading Library manager
# --------------------------------------------------------------------
@admin_bp.route("/reading")
def reading_list():
    texts = DevotionalText.query.order_by(DevotionalText.category, DevotionalText.order_index).all()
    return render_template("admin/reading_list.html", texts=texts)


@admin_bp.route("/reading/new", methods=["GET", "POST"])
def reading_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content_marathi", "").strip()
        try:
            audio_data, audio_mimetype = read_uploaded_audio(request.files.get("audio"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/reading_form.html", text=None)
        if not title or not content:
            flash("Title and text are both required.", "error")
        else:
            slug = request.form.get("slug", "").strip() or slugify(title)
            text = DevotionalText(
                title=title,
                slug=slug,
                category=request.form.get("category", "other"),
                content_marathi=content,
                source=request.form.get("source", "").strip() or None,
                audio_data=audio_data,
                audio_mimetype=audio_mimetype,
                order_index=request.form.get("order_index", 0, type=int),
                is_published=bool(request.form.get("is_published")),
            )
            db.session.add(text)
            db.session.commit()
            flash("Reading added.", "success")
            return redirect(url_for("admin.reading_list"))
    return render_template("admin/reading_form.html", text=None)


@admin_bp.route("/reading/<int:text_id>/edit", methods=["GET", "POST"])
def reading_edit(text_id):
    text = DevotionalText.query.get_or_404(text_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content_marathi", "").strip()
        try:
            audio_data, audio_mimetype = read_uploaded_audio(request.files.get("audio"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("admin/reading_form.html", text=text)
        if not title or not content:
            flash("Title and text are both required.", "error")
        else:
            text.title = title
            text.slug = request.form.get("slug", "").strip() or slugify(title)
            text.category = request.form.get("category", "other")
            text.content_marathi = content
            text.source = request.form.get("source", "").strip() or None
            if audio_data:
                # A new file was uploaded — replace the stored audio.
                text.audio_data = audio_data
                text.audio_mimetype = audio_mimetype
            elif request.form.get("remove_audio"):
                # "Remove current audio" was ticked and no replacement was given.
                text.audio_data = None
                text.audio_mimetype = None
            # else: no file chosen and box not ticked -> keep existing audio as-is.
            text.order_index = request.form.get("order_index", 0, type=int)
            text.is_published = bool(request.form.get("is_published"))
            db.session.commit()
            flash("Reading updated.", "success")
            return redirect(url_for("admin.reading_list"))
    return render_template("admin/reading_form.html", text=text)


@admin_bp.route("/reading/<int:text_id>/delete", methods=["POST"])
def reading_delete(text_id):
    text = DevotionalText.query.get_or_404(text_id)
    db.session.delete(text)
    db.session.commit()
    flash("Reading deleted.", "success")
    return redirect(url_for("admin.reading_list"))


# --------------------------------------------------------------------
# Contact messages inbox
# --------------------------------------------------------------------
@admin_bp.route("/messages")
def message_list():
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template("admin/message_list.html", messages=messages)


@admin_bp.route("/messages/<int:msg_id>/read", methods=["POST"])
def message_mark_read(msg_id):
    msg = ContactMessage.query.get_or_404(msg_id)
    msg.is_read = True
    db.session.commit()
    return redirect(url_for("admin.message_list"))


@admin_bp.route("/messages/<int:msg_id>/delete", methods=["POST"])
def message_delete(msg_id):
    msg = ContactMessage.query.get_or_404(msg_id)
    db.session.delete(msg)
    db.session.commit()
    flash("Message deleted.", "success")
    return redirect(url_for("admin.message_list"))
