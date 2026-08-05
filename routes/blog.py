import unicodedata
from datetime import datetime
from flask import Blueprint, render_template, request, abort
from models import Post, Category, Tag

blog_bp = Blueprint("blog", __name__, url_prefix="/blog")


def _published_query():
    return Post.query.filter(
        Post.status == "published",
        (Post.published_at.is_(None)) | (Post.published_at <= datetime.utcnow()),
    )


@blog_bp.route("/")
def list_posts():
    page = request.args.get("page", 1, type=int)
    category_slug = request.args.get("category")
    tag_slug = request.args.get("tag")
    # NFC-normalize — see routes/admin.py's slugify() for why Devanagari
    # slugs need this to match reliably.
    if category_slug:
        category_slug = unicodedata.normalize("NFC", category_slug).strip()
    if tag_slug:
        tag_slug = unicodedata.normalize("NFC", tag_slug).strip()

    query = _published_query()
    if category_slug:
        query = query.join(Category).filter(Category.slug == category_slug)
    if tag_slug:
        query = query.join(Post.tags).filter(Tag.slug == tag_slug)

    pagination = query.order_by(Post.published_at.desc()).paginate(page=page, per_page=9)
    categories = Category.query.all()
    return render_template("blog/list.html", pagination=pagination, categories=categories)


@blog_bp.route("/<slug>")
def detail(slug):
    slug = unicodedata.normalize("NFC", slug).strip()
    post = _published_query().filter(Post.slug == slug).first()
    if not post:
        abort(404)
    related = (
        _published_query()
        .filter(Post.category_id == post.category_id, Post.id != post.id)
        .limit(3)
        .all()
    )
    return render_template("blog/detail.html", post=post, related=related)
