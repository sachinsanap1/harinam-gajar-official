from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Video, Post, Category, ContactMessage, SantProfile, KirtankarProfile, DevotionalText, Abhang
from forms import ContactForm
from services.abhang_rotation import get_todays_abhang
from services.vachan_rotation import get_todays_vachan

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    featured = Video.query.filter_by(is_featured=True).order_by(Video.published_at.desc()).first()
    latest_videos = (
        Video.query.filter(Video.kind.in_(["video", "live"]))
        .order_by(Video.published_at.desc())
        .limit(6)
        .all()
    )
    latest_shorts = Video.query.filter_by(kind="short").order_by(Video.published_at.desc()).limit(8).all()
    popular_videos = (
        Video.query.filter(Video.kind.in_(["video", "live"]))
        .order_by(Video.view_count.desc())
        .limit(6)
        .all()
    )
    live_now = Video.query.filter_by(is_live_now=True).first()
    latest_posts = (
        Post.query.filter_by(status="published").order_by(Post.published_at.desc()).limit(3).all()
    )
    todays_abhang = get_todays_abhang()
    todays_vachan = get_todays_vachan()
    featured_saints = (
        SantProfile.query.filter_by(is_published=True).order_by(SantProfile.created_at.desc()).limit(4).all()
    )
    featured_kirtankars = (
        KirtankarProfile.query.filter_by(is_published=True).order_by(KirtankarProfile.view_count.desc()).limit(4).all()
    )
    reading_highlights = (
        DevotionalText.query.filter_by(is_published=True).order_by(DevotionalText.order_index).limit(8).all()
    )
    return render_template(
        "home.html",
        featured=featured,
        latest_videos=latest_videos,
        latest_shorts=latest_shorts,
        popular_videos=popular_videos,
        live_now=live_now,
        latest_posts=latest_posts,
        todays_abhang=todays_abhang,
        todays_vachan=todays_vachan,
        featured_saints=featured_saints,
        featured_kirtankars=featured_kirtankars,
        reading_highlights=reading_highlights,
    )


@main_bp.route("/live")
def live():
    live_now = Video.query.filter_by(is_live_now=True).first()
    upcoming = Video.query.filter_by(kind="upcoming").order_by(Video.published_at.asc()).all()
    past = (
        Video.query.filter(Video.kind == "video", Video.is_live_now.is_(False))
        .order_by(Video.published_at.desc())
        .limit(12)
        .all()
    )
    return render_template("live.html", live_now=live_now, upcoming=upcoming, past=past)


@main_bp.route("/shorts")
def shorts():
    shorts = Video.query.filter_by(kind="short").order_by(Video.published_at.desc()).all()
    return render_template("shorts.html", shorts=shorts)


@main_bp.route("/videos")
def videos():
    page = request.args.get("page", 1, type=int)
    pagination = (
        Video.query.filter(Video.kind.in_(["video", "live"]))
        .order_by(Video.published_at.desc())
        .paginate(page=page, per_page=12)
    )
    return render_template("videos.html", pagination=pagination)


@main_bp.route("/contact", methods=["GET", "POST"])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        msg = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            subject=form.subject.data,
            message=form.message.data,
        )
        db.session.add(msg)
        db.session.commit()
        flash("Your message has been sent. We'll get back to you soon.", "success")
        return redirect(url_for("main.contact"))
    return render_template("contact.html", form=form)


@main_bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    videos_results = Video.query.filter(Video.title.ilike(f"%{q}%")).limit(10).all() if q else []
    posts_results = (
        Post.query.filter(Post.status == "published", Post.title.ilike(f"%{q}%")).limit(10).all()
        if q else []
    )
    saints_results = (
        SantProfile.query.filter(SantProfile.is_published == True, SantProfile.name.ilike(f"%{q}%")).limit(10).all()
        if q else []
    )
    kirtankars_results = (
        KirtankarProfile.query.filter(KirtankarProfile.is_published == True, KirtankarProfile.full_name.ilike(f"%{q}%")).limit(10).all()
        if q else []
    )
    reading_results = (
        DevotionalText.query.filter(DevotionalText.is_published == True, DevotionalText.title.ilike(f"%{q}%")).limit(10).all()
        if q else []
    )
    abhang_results = (
        Abhang.query.filter(Abhang.is_active == True, Abhang.text_marathi.ilike(f"%{q}%")).limit(10).all()
        if q else []
    )
    return render_template(
        "search.html",
        q=q,
        videos_results=videos_results,
        posts_results=posts_results,
        saints_results=saints_results,
        kirtankars_results=kirtankars_results,
        reading_results=reading_results,
        abhang_results=abhang_results,
    )
