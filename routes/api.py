"""
Abhang API.

Public (read-only):
  GET  /api/abhangs            list active abhangs (paginated)
  GET  /api/abhangs/<id>       single abhang
  GET  /api/abhangs/today      today's rotating abhang

Admin-only (write) — requires an active admin session (log in via
/admin/login in the same browser first). Exempted from CSRF since these
are called as a JSON API rather than an HTML form:
  POST   /api/abhangs          create one           {"text_marathi": "...", "saint_name": "...", "source": "..."}
  PUT    /api/abhangs/<id>     update one            same body, any subset of fields
  DELETE /api/abhangs/<id>     delete one
  POST   /api/abhangs/bulk     create many at once   {"items": [{...}, {...}, ...]}
"""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import db, Abhang
from services.abhang_rotation import get_todays_abhang

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _serialize(abhang):
    return {
        "id": abhang.id,
        "text_marathi": abhang.text_marathi,
        "saint_name": abhang.saint_name,
        "source": abhang.source,
        "is_active": abhang.is_active,
        "created_at": abhang.created_at.isoformat() if abhang.created_at else None,
    }


def _require_admin():
    if not current_user.is_authenticated or not current_user.has_role("super_admin", "admin", "editor"):
        return jsonify({"error": "Admin login required."}), 403
    return None


# --------------------------------------------------------------------
# Public reads
# --------------------------------------------------------------------
@api_bp.route("/abhangs")
def list_abhangs():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    pagination = Abhang.query.filter_by(is_active=True).order_by(Abhang.id).paginate(page=page, per_page=per_page)
    return jsonify({
        "page": pagination.page,
        "pages": pagination.pages,
        "total": pagination.total,
        "items": [_serialize(a) for a in pagination.items],
    })


@api_bp.route("/abhangs/today")
def today_abhang():
    abhang = get_todays_abhang()
    if not abhang:
        return jsonify({"error": "No active abhangs stored yet."}), 404
    return jsonify(_serialize(abhang))


@api_bp.route("/abhangs/<int:abhang_id>")
def get_abhang(abhang_id):
    abhang = Abhang.query.get_or_404(abhang_id)
    return jsonify(_serialize(abhang))


# --------------------------------------------------------------------
# Admin-only writes
# --------------------------------------------------------------------
@api_bp.route("/abhangs", methods=["POST"])
@login_required
def create_abhang():
    denied = _require_admin()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    text = (data.get("text_marathi") or "").strip()
    if not text:
        return jsonify({"error": "text_marathi is required."}), 400

    abhang = Abhang(
        text_marathi=text,
        saint_name=(data.get("saint_name") or "").strip() or None,
        source=(data.get("source") or "").strip() or None,
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(abhang)
    db.session.commit()
    return jsonify(_serialize(abhang)), 201


@api_bp.route("/abhangs/bulk", methods=["POST"])
@login_required
def bulk_create_abhangs():
    denied = _require_admin()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    created = []
    for item in items:
        text = (item.get("text_marathi") or "").strip()
        if not text:
            continue
        abhang = Abhang(
            text_marathi=text,
            saint_name=(item.get("saint_name") or "").strip() or None,
            source=(item.get("source") or "").strip() or None,
            is_active=bool(item.get("is_active", True)),
        )
        db.session.add(abhang)
        created.append(abhang)
    db.session.commit()
    return jsonify({"created": len(created), "items": [_serialize(a) for a in created]}), 201


@api_bp.route("/abhangs/<int:abhang_id>", methods=["PUT"])
@login_required
def update_abhang(abhang_id):
    denied = _require_admin()
    if denied:
        return denied
    abhang = Abhang.query.get_or_404(abhang_id)
    data = request.get_json(silent=True) or {}
    if "text_marathi" in data:
        abhang.text_marathi = data["text_marathi"].strip()
    if "saint_name" in data:
        abhang.saint_name = (data["saint_name"] or "").strip() or None
    if "source" in data:
        abhang.source = (data["source"] or "").strip() or None
    if "is_active" in data:
        abhang.is_active = bool(data["is_active"])
    db.session.commit()
    return jsonify(_serialize(abhang))


@api_bp.route("/abhangs/<int:abhang_id>", methods=["DELETE"])
@login_required
def delete_abhang(abhang_id):
    denied = _require_admin()
    if denied:
        return denied
    abhang = Abhang.query.get_or_404(abhang_id)
    db.session.delete(abhang)
    db.session.commit()
    return jsonify({"deleted": abhang_id})
