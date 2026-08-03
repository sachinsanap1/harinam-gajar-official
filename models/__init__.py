import re
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,15})"
)


def extract_youtube_id(url):
    """Pulls the 11-char video ID out of any common YouTube URL shape."""
    if not url:
        return None
    m = _YOUTUBE_ID_RE.search(url)
    return m.group(1) if m else None

db = SQLAlchemy()


# --------------------------------------------------------------------------
# Users & roles (admin panel auth)
# --------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="editor")
    # roles: super_admin, admin, editor, moderator, viewer
    is_active_account = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_active(self):
        return self.is_active_account

    def has_role(self, *roles):
        return self.role in roles


# --------------------------------------------------------------------------
# YouTube content — synced automatically, never hand-entered
# --------------------------------------------------------------------------
class Video(db.Model):
    __tablename__ = "videos"

    id = db.Column(db.Integer, primary_key=True)
    youtube_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(20), default="video")  # video, short, live, upcoming
    title = db.Column(db.String(300))
    description = db.Column(db.Text)
    thumbnail_url = db.Column(db.String(400))
    published_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer, default=0)
    view_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    tags = db.Column(db.String(500))  # comma separated
    playlist_id = db.Column(db.String(64), nullable=True, index=True)
    is_featured = db.Column(db.Boolean, default=False)
    is_live_now = db.Column(db.Boolean, default=False)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_short(self):
        return self.kind == "short" or (self.duration_seconds and self.duration_seconds <= 60)

    @property
    def url(self):
        return f"https://www.youtube.com/watch?v={self.youtube_id}"


# --------------------------------------------------------------------------
# Blog / CMS
# --------------------------------------------------------------------------
post_tags = db.Table(
    "post_tags",
    db.Column("post_id", db.Integer, db.ForeignKey("posts.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    posts = db.relationship("Post", backref="category", lazy=True)


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    slug = db.Column(db.String(280), unique=True, nullable=False, index=True)
    excerpt = db.Column(db.String(400))
    content_html = db.Column(db.Text, nullable=False)
    featured_image = db.Column(db.String(400))
    status = db.Column(db.String(20), default="draft")  # draft, scheduled, published
    published_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    author = db.relationship("User")
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    tags = db.relationship("Tag", secondary=post_tags, backref="posts")

    # SEO
    meta_title = db.Column(db.String(70))
    meta_description = db.Column(db.String(160))
    meta_keywords = db.Column(db.String(300))

    comments = db.relationship("Comment", backref="post", lazy=True, cascade="all, delete-orphan")


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180))
    body = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------
# Site-wide editable settings (Admin > Settings writes here, never to code)
# --------------------------------------------------------------------------
class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        row = Setting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = Setting.query.get(key)
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            db.session.add(row)
        db.session.commit()


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(30))
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------
# Abhang of the Day — rotates automatically, admin can override any day
# --------------------------------------------------------------------------
class Abhang(db.Model):
    __tablename__ = "abhangs"

    id = db.Column(db.Integer, primary_key=True)
    text_marathi = db.Column(db.Text, nullable=False)
    saint_name = db.Column(db.String(120))         # e.g. Sant Tukaram — optional, leave blank if unknown
    source = db.Column(db.String(200))              # e.g. Tukaram Gatha, Abhang No. 1234 — for attribution
    meaning = db.Column(db.Text)                      # short plain-language meaning, optional, admin-written
    is_active = db.Column(db.Boolean, default=True)    # inactive abhangs are skipped by the daily rotation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------
# Sant Charitra — saint profiles. Historically responsible: free-text fields
# rather than forced exact dates, since precise dates are often disputed.
# --------------------------------------------------------------------------
class SantProfile(db.Model):
    __tablename__ = "sant_profiles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    alt_names = db.Column(db.String(300))            # comma separated alternative names
    photo_url = db.Column(db.String(400))              # legacy — old entries only, no longer editable via admin
    photo_data = db.Column(db.LargeBinary, nullable=True)   # uploaded photo bytes (Vercel has no writable disk)
    photo_mimetype = db.Column(db.String(100), nullable=True)
    photo_updated_at = db.Column(db.DateTime, nullable=True)  # bumped on new upload, used to cache-bust the photo URL
    tradition = db.Column(db.String(100))              # e.g. Warkari, Nath, Mahanubhav — admin free text
    birth_info = db.Column(db.String(300))                # free text — "believed to be c. 1275 (dates debated)"
    samadhi_info = db.Column(db.String(300))
    birthplace = db.Column(db.String(200))
    important_places = db.Column(db.Text)                    # free text list, one per line
    short_bio = db.Column(db.String(400))
    full_bio = db.Column(db.Text)
    teachings = db.Column(db.Text)
    literary_works = db.Column(db.Text)                          # books/granthas, one per line
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    meta_description = db.Column(db.String(160))


# --------------------------------------------------------------------------
# Kirtankar / Maharaj profiles
# --------------------------------------------------------------------------
class KirtankarProfile(db.Model):
    __tablename__ = "kirtankar_profiles"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False, index=True)
    honorific = db.Column(db.String(60))                # e.g. ह.भ.प., Maharaj
    photo_url = db.Column(db.String(400))
    photo_data = db.Column(db.LargeBinary, nullable=True)
    photo_mimetype = db.Column(db.String(100), nullable=True)
    photo_updated_at = db.Column(db.DateTime, nullable=True)  # bumped on new upload, used to cache-bust the photo URL
    short_intro = db.Column(db.String(400))
    full_bio = db.Column(db.Text)
    village = db.Column(db.String(120))
    district = db.Column(db.String(120))
    state = db.Column(db.String(120))
    popular_kirtans = db.Column(db.Text)                 # free text list, one per line
    special_topics = db.Column(db.Text)
    youtube_url = db.Column(db.String(300))
    facebook_url = db.Column(db.String(300))
    instagram_url = db.Column(db.String(300))
    website_url = db.Column(db.String(300))
    contact_info = db.Column(db.String(300))               # only shown publicly if is_contact_public
    is_contact_public = db.Column(db.Boolean, default=False)
    view_count = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    meta_description = db.Column(db.String(160))

    videos = db.relationship(
        "KirtankarVideo", backref="kirtankar", lazy=True,
        order_by="KirtankarVideo.order_index",
        cascade="all, delete-orphan",
    )


# --------------------------------------------------------------------------
# Popular kirtans — one YouTube link per named kirtan, shown under
# "लोकप्रिय कीर्तने" on a kirtankar's profile page.
# --------------------------------------------------------------------------
class KirtankarVideo(db.Model):
    __tablename__ = "kirtankar_videos"

    id = db.Column(db.Integer, primary_key=True)
    kirtankar_id = db.Column(db.Integer, db.ForeignKey("kirtankar_profiles.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    youtube_url = db.Column(db.String(400), nullable=False)
    order_index = db.Column(db.Integer, default=0)

    @property
    def youtube_video_id(self):
        return extract_youtube_id(self.youtube_url)

    @property
    def thumbnail_url(self):
        vid = self.youtube_video_id
        return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None


# --------------------------------------------------------------------------
# Devotional Reading Library — Haripath, Aarti, Stotra, etc.
# --------------------------------------------------------------------------
class DevotionalText(db.Model):
    __tablename__ = "devotional_texts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)   # haripath, aarti, stotra, namasmaran, prayer, other
    content_marathi = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(200))
    audio_url = db.Column(db.String(400))                  # Cloudinary secure_url (or a legacy external URL)
    audio_public_id = db.Column(db.String(300), nullable=True)  # Cloudinary asset id — needed to replace/delete it
    audio_data = db.Column(db.LargeBinary, nullable=True)   # legacy — old entries uploaded before the Cloudinary switch
    audio_mimetype = db.Column(db.String(100), nullable=True)
    order_index = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
