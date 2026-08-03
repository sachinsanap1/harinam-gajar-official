import re
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import (
    db, Video, Post, Category, Abhang, User,
    SantProfile, KirtankarProfile, DevotionalText, SantVachan, ContactMessage,
)
from forms import PostForm
from services.youtube_sync import full_sync, YouTubeSyncError, get_sync_status
from services.abhang_rotation import set_todays_abhang, get_todays_abhang
from services.vachan_rotation import set_todays_vachan, get_todays_vachan

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def slugify(text):
    text = text.lower().strip()
    # Keep word chars, spaces, hyphens, AND the Devanagari block explicitly —
    # \w alone strips Marathi matras/virama (combining marks), garbling slugs
    # like "श्री" -> "शर". Whitelisting U+0900-U+097F keeps them intact.
    text = re.sub(r"[^\w\s\u0900-\u097F-]", "", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


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
        if not name:
            flash("Saint name is required.", "error")
        else:
            slug = request.form.get("slug", "").strip() or slugify(name)
            saint = SantProfile(
                name=name,
                slug=slug,
                alt_names=request.form.get("alt_names", "").strip() or None,
                photo_url=request.form.get("photo_url", "").strip() or None,
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
        if not name:
            flash("Saint name is required.", "error")
        else:
            saint.name = name
            saint.slug = request.form.get("slug", "").strip() or slugify(name)
            saint.alt_names = request.form.get("alt_names", "").strip() or None
            saint.photo_url = request.form.get("photo_url", "").strip() or None
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
        if not full_name:
            flash("Name is required.", "error")
        else:
            slug = request.form.get("slug", "").strip() or slugify(full_name)
            kirtankar = KirtankarProfile(
                full_name=full_name,
                slug=slug,
                honorific=request.form.get("honorific", "").strip() or None,
                photo_url=request.form.get("photo_url", "").strip() or None,
                short_intro=request.form.get("short_intro", "").strip() or None,
                full_bio=request.form.get("full_bio", "").strip() or None,
                village=request.form.get("village", "").strip() or None,
                district=request.form.get("district", "").strip() or None,
                state=request.form.get("state", "").strip() or None,
                popular_kirtans=request.form.get("popular_kirtans", "").strip() or None,
                special_topics=request.form.get("special_topics", "").strip() or None,
                youtube_url=request.form.get("youtube_url", "").strip() or None,
                facebook_url=request.form.get("facebook_url", "").strip() or None,
                instagram_url=request.form.get("instagram_url", "").strip() or None,
                website_url=request.form.get("website_url", "").strip() or None,
                contact_info=request.form.get("contact_info", "").strip() or None,
                is_contact_public=bool(request.form.get("is_contact_public")),
                meta_description=request.form.get("meta_description", "").strip() or None,
                is_published=bool(request.form.get("is_published")),
            )
            db.session.add(kirtankar)
            db.session.commit()
            flash("Kirtankar profile added.", "success")
            return redirect(url_for("admin.kirtankar_list"))
    return render_template("admin/kirtankar_form.html", kirtankar=None)


@admin_bp.route("/kirtankars/<int:kirtankar_id>/edit", methods=["GET", "POST"])
def kirtankar_edit(kirtankar_id):
    kirtankar = KirtankarProfile.query.get_or_404(kirtankar_id)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Name is required.", "error")
        else:
            kirtankar.full_name = full_name
            kirtankar.slug = request.form.get("slug", "").strip() or slugify(full_name)
            kirtankar.honorific = request.form.get("honorific", "").strip() or None
            kirtankar.photo_url = request.form.get("photo_url", "").strip() or None
            kirtankar.short_intro = request.form.get("short_intro", "").strip() or None
            kirtankar.full_bio = request.form.get("full_bio", "").strip() or None
            kirtankar.village = request.form.get("village", "").strip() or None
            kirtankar.district = request.form.get("district", "").strip() or None
            kirtankar.state = request.form.get("state", "").strip() or None
            kirtankar.popular_kirtans = request.form.get("popular_kirtans", "").strip() or None
            kirtankar.special_topics = request.form.get("special_topics", "").strip() or None
            kirtankar.youtube_url = request.form.get("youtube_url", "").strip() or None
            kirtankar.facebook_url = request.form.get("facebook_url", "").strip() or None
            kirtankar.instagram_url = request.form.get("instagram_url", "").strip() or None
            kirtankar.website_url = request.form.get("website_url", "").strip() or None
            kirtankar.contact_info = request.form.get("contact_info", "").strip() or None
            kirtankar.is_contact_public = bool(request.form.get("is_contact_public"))
            kirtankar.meta_description = request.form.get("meta_description", "").strip() or None
            kirtankar.is_published = bool(request.form.get("is_published"))
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
                audio_url=request.form.get("audio_url", "").strip() or None,
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
        if not title or not content:
            flash("Title and text are both required.", "error")
        else:
            text.title = title
            text.slug = request.form.get("slug", "").strip() or slugify(title)
            text.category = request.form.get("category", "other")
            text.content_marathi = content
            text.source = request.form.get("source", "").strip() or None
            text.audio_url = request.form.get("audio_url", "").strip() or None
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
# Daily Sant Vachan manager
# --------------------------------------------------------------------
@admin_bp.route("/vachans")
def vachan_list():
    vachans = SantVachan.query.order_by(SantVachan.id.desc()).all()
    todays_vachan = get_todays_vachan()
    return render_template("admin/vachan_list.html", vachans=vachans, todays_vachan=todays_vachan)


@admin_bp.route("/vachans/new", methods=["GET", "POST"])
def vachan_new():
    if request.method == "POST":
        quote_text = request.form.get("quote_text", "").strip()
        if not quote_text:
            flash("Quote text is required.", "error")
        else:
            vachan = SantVachan(
                quote_text=quote_text,
                saint_name=request.form.get("saint_name", "").strip() or None,
                meaning=request.form.get("meaning", "").strip() or None,
                image_url=request.form.get("image_url", "").strip() or None,
                is_active=bool(request.form.get("is_active")),
            )
            db.session.add(vachan)
            db.session.commit()
            flash("Sant Vachan added.", "success")
            return redirect(url_for("admin.vachan_list"))
    return render_template("admin/vachan_form.html", vachan=None)


@admin_bp.route("/vachans/<int:vachan_id>/edit", methods=["GET", "POST"])
def vachan_edit(vachan_id):
    vachan = SantVachan.query.get_or_404(vachan_id)
    if request.method == "POST":
        quote_text = request.form.get("quote_text", "").strip()
        if not quote_text:
            flash("Quote text is required.", "error")
        else:
            vachan.quote_text = quote_text
            vachan.saint_name = request.form.get("saint_name", "").strip() or None
            vachan.meaning = request.form.get("meaning", "").strip() or None
            vachan.image_url = request.form.get("image_url", "").strip() or None
            vachan.is_active = bool(request.form.get("is_active"))
            db.session.commit()
            flash("Sant Vachan updated.", "success")
            return redirect(url_for("admin.vachan_list"))
    return render_template("admin/vachan_form.html", vachan=vachan)


@admin_bp.route("/vachans/<int:vachan_id>/delete", methods=["POST"])
def vachan_delete(vachan_id):
    vachan = SantVachan.query.get_or_404(vachan_id)
    db.session.delete(vachan)
    db.session.commit()
    flash("Sant Vachan deleted.", "success")
    return redirect(url_for("admin.vachan_list"))


@admin_bp.route("/vachans/<int:vachan_id>/set-today", methods=["POST"])
def vachan_set_today(vachan_id):
    set_todays_vachan(vachan_id)
    flash("Today's Sant Vachan set. It will stay on the homepage until midnight.", "success")
    return redirect(url_for("admin.vachan_list"))


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
