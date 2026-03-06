import random
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, session, jsonify, url_for, Response, make_response
from flask_mysqldb import MySQL
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape
import os
import json
import io
import csv
import time
import requests


import secrets
import hashlib
import base64
import base64
from datetime import timedelta
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Serializer for password reset links
serializer = URLSafeTimedSerializer(app.config.get('SECRET_KEY', 'hh-secret'))


# -----------------------------
# Payout helpers (mask + reversible obfuscation)
# -----------------------------
def mask_account(account: str) -> str:
    s = (account or '').strip()
    if not s:
        return ''
    # keep last 3-4 chars, mask the rest
    if len(s) <= 6:
        return s[0:2] + ('X' * max(0, len(s)-4)) + s[-2:]
    keep_prefix = 2
    keep_suffix = 4 if len(s) >= 10 else 3
    mid = 'X' * max(0, len(s) - keep_prefix - keep_suffix)
    return s[:keep_prefix] + mid + s[-keep_suffix:]

def _payout_crypto_key() -> bytes:
    sk = (app.config.get('SECRET_KEY') or 'hh-secret').encode('utf-8')
    return hashlib.sha256(sk).digest()

def encrypt_text(plain: str) -> str:
    """Reversible obfuscation for demo purposes.

    Stores sensitive payout account in DB in a non-plain form.
    """
    s = (plain or '').strip()
    if not s:
        return ''
    key = _payout_crypto_key()
    b = s.encode('utf-8')
    x = bytes([b[i] ^ key[i % len(key)] for i in range(len(b))])
    return 'x1:' + base64.urlsafe_b64encode(x).decode('ascii')

def decrypt_text(token: str) -> str:
    tok = (token or '').strip()
    if not tok:
        return ''
    if tok.startswith('x1:'):
        tok = tok[3:]
    try:
        x = base64.urlsafe_b64decode(tok.encode('ascii'))
    except Exception:
        return ''
    key = _payout_crypto_key()
    b = bytes([x[i] ^ key[i % len(key)] for i in range(len(x))])
    try:
        return b.decode('utf-8')
    except Exception:
        return ''

mysql = MySQL(app)
mail = Mail(app)

# --------------------
# Lightweight schema migrator (safe, idempotent)
# --------------------
def _ensure_schema():
    """Create/patch tables/columns needed for premium home + flash workflow.
    Runs at startup; ignores 'already exists' errors.
    """
    cur = mysql.connection.cursor()
    def _try(sql, params=None):
        try:
            cur.execute(sql, params or ())
            mysql.connection.commit()
        except Exception:
            try:
                mysql.connection.rollback()
            except Exception:
                pass

    # Flash workflow: columns on products
    _try("ALTER TABLE products ADD COLUMN is_flash TINYINT(1) NOT NULL DEFAULT 0")
    _try("ALTER TABLE products ADD COLUMN flash_end_at DATETIME NULL")
    _try("ALTER TABLE products ADD COLUMN dispatch_type ENUM('normal','flash','full') NOT NULL DEFAULT 'normal'")
    _try("ALTER TABLE products ADD COLUMN is_archive TINYINT(1) NOT NULL DEFAULT 0")
    _try("ALTER TABLE products ADD COLUMN specs_json TEXT NULL")

    # Flash requests queue (seller -> admin approve)
    _try("""CREATE TABLE IF NOT EXISTS flash_requests (
        id INT NOT NULL AUTO_INCREMENT,
        product_id VARCHAR(32) NOT NULL,
        seller_id INT NOT NULL,
        requested_price_usd DECIMAL(10,2) NOT NULL DEFAULT 0.00,
        requested_compare_at_usd DECIMAL(10,2) NOT NULL DEFAULT 0.00,
        requested_end_at DATETIME NOT NULL,
        status ENUM('pending','approved','rejected','cancelled') NOT NULL DEFAULT 'pending',
        seller_note VARCHAR(255) DEFAULT NULL,
        admin_note VARCHAR(255) DEFAULT NULL,
        reviewed_by INT DEFAULT NULL,
        reviewed_at DATETIME DEFAULT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_flash_req_status (status, created_at),
        KEY idx_flash_req_product (product_id),
        KEY idx_flash_req_seller (seller_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")

# Run schema checks once on boot
try:
    _ensure_schema()
except Exception:
    pass

# -----------------------------
# Money / Currency helpers
# -----------------------------
def _to_float(v):
    try:
        return float(v)
    except Exception:
        return 0.0

@app.template_filter("money")
def money_filter(usd_amount):
    """Render a canonical money span with USD as base for client-side currency switching."""
    usd = _to_float(usd_amount)
    # Keep a stable representation; UI formatting happens in JS (applyCurrencyUI)
    html = f'<span class="money" data-usd="{usd:.2f}"><span class="sym">$</span><span class="amt">{usd:.2f}</span></span>'
    return Markup(html)

# -----------------------------
# DB Helpers
# -----------------------------
def db_one(sql, params=()):
    cur = mysql.connection.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass

def db_all(sql, params=()):
    cur = mysql.connection.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        try:
            cur.close()
        except Exception:
            pass

def db_exec(sql, params=()):
    cur = mysql.connection.cursor()
    try:
        cur.execute(sql, params)
        mysql.connection.commit()
        return cur.rowcount
    finally:
        try:
            cur.close()
        except Exception:
            pass


# -----------------------------
# Schema helpers (avoid crashing on missing columns)
# -----------------------------

# -----------------------------
# Products.status compatibility helpers
# (Some existing DBs use ENUM without 'pending'. Avoid crashes.)
# -----------------------------
_PRODUCTS_STATUS_CACHE = {"values": None, "fetched_at": 0}

def _parse_enum_values(column_type: str):
    # column_type example: "enum('active','blocked')"
    if not column_type:
        return []
    s = column_type.strip()
    if not s.lower().startswith("enum("):
        return []
    inner = s[s.find("(")+1:s.rfind(")")]
    vals = []
    cur = ""
    in_q = False
    esc = False
    for ch in inner:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "'":
            in_q = not in_q
            if not in_q:
                vals.append(cur)
                cur = ""
            continue
        if in_q:
            cur += ch
    return [v for v in vals if v is not None]

def _product_allowed_statuses():
    # Cache for a short time to reduce INFORMATION_SCHEMA hits
    now = int(time.time())
    if _PRODUCTS_STATUS_CACHE["values"] is not None and (now - int(_PRODUCTS_STATUS_CACHE["fetched_at"] or 0)) < 300:
        return _PRODUCTS_STATUS_CACHE["values"] or []
    try:
        row = db_one(
            "SELECT DATA_TYPE, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products' AND COLUMN_NAME='status' LIMIT 1"
        )
        dtype = (_row_get(row, "DATA_TYPE", 0, "") or "").lower()
        ctype = (_row_get(row, "COLUMN_TYPE", 1, "") or "")
        if dtype == "enum":
            vals = _parse_enum_values(ctype)
        else:
            # varchar/text/int etc -> allow common values
            vals = ["pending", "active", "blocked", "archived", "disabled"]
        _PRODUCTS_STATUS_CACHE.update({"values": vals, "fetched_at": now})
        return vals or []
    except Exception:
        # safest fallback
        vals = ["active", "blocked", "pending"]
        _PRODUCTS_STATUS_CACHE.update({"values": vals, "fetched_at": now})
        return vals

def _product_status_default():
    allowed = [v.lower() for v in (_product_allowed_statuses() or [])]
    # prefer pending, else active, else first enum option, else active
    for cand in ["pending", "active", "draft"]:
        if cand in allowed:
            return cand
    return (allowed[0] if allowed else "active")

def _product_status_sanitize(v: str):
    val = (v or "").strip().lower()
    allowed = [x.lower() for x in (_product_allowed_statuses() or [])]
    if not allowed:
        return val or "active"
    if val in allowed:
        return val
    # Map common legacy -> allowed
    if val == "pending" and "active" in allowed:
        return "active"
    return allowed[0]


# -----------------------------
# Live FX Rates (Currency Switch)
# -----------------------------
_FX_CACHE = {"base": "USD", "rates": {}, "fetched_at": 0}
_FX_TTL_SECONDS = 6 * 60 * 60  # 6 hours

def _fallback_fx_rates():
    # Keep in sync with static/js/app.js defaults (used if live fetch fails)
    return {
        "USD": 1.0,
        "BDT": 118.0,
        "EUR": 0.92,
        "GBP": 0.79,
        "INR": 83.0,
        "JPY": 146.0,
    }

def get_fx_rates(base="USD"):
    """Fetch live FX rates (cached). Returns dict currency->rate."""
    now = int(time.time())
    if _FX_CACHE["rates"] and (now - int(_FX_CACHE["fetched_at"])) < _FX_TTL_SECONDS and _FX_CACHE.get("base") == base:
        return _FX_CACHE["rates"]

    rates = {}
    try:
        # Free endpoint (no API key): https://open.er-api.com
        r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=4)
        data = r.json() if r.ok else {}
        api_rates = (data.get("rates") or {})
        wanted = ["USD", "BDT", "EUR", "GBP", "INR", "JPY"]
        for c in wanted:
            if c == base:
                rates[c] = 1.0
            elif c in api_rates:
                rates[c] = float(api_rates[c])
        # If API didn't return something, fall back for missing
        fb = _fallback_fx_rates()
        for c,v in fb.items():
            rates.setdefault(c, float(v))
        _FX_CACHE.update({"base": base, "rates": rates, "fetched_at": now})
        return rates
    except Exception:
        # Network/API failure: fall back to defaults
        rates = _fallback_fx_rates()
        _FX_CACHE.update({"base": base, "rates": rates, "fetched_at": now})
        return rates

@app.get("/api/fx")
def api_fx_rates():
    base = (request.args.get("base") or "USD").upper().strip()
    if base not in ["USD"]:
        base = "USD"
    rates = get_fx_rates(base)
    return jsonify({"base": base, "rates": rates, "fetched_at": _FX_CACHE.get("fetched_at")})


def _db_bool(q, params=()):
    try:
        r = db_one(q, params)
        v = _row_get(r, 'COUNT(*)', 0, 0)
        return int(v or 0) > 0
    except Exception:
        return False

def db_has_table(table_name: str) -> bool:
    return _db_bool(
        """
        SELECT COUNT(*)
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )

def db_has_column(table_name: str, column_name: str) -> bool:
    return _db_bool(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )

# -----------------------------
# Auto schema patches (safe, best-effort)
# -----------------------------
_SCHEMA_PATCHED = False

@app.before_request
def _ensure_schema_once():
    global _SCHEMA_PATCHED
    if _SCHEMA_PATCHED:
        return
    _SCHEMA_PATCHED = True
    try:
        # password_resets: add OTP code columns if missing
        if not db_has_column("password_resets", "code_hash"):
            db_exec("ALTER TABLE password_resets ADD COLUMN code_hash varchar(64) NULL")
        if not db_has_column("password_resets", "code_expires_at"):
            db_exec("ALTER TABLE password_resets ADD COLUMN code_expires_at datetime NULL")
        # conversations: ensure seller_id nullable for support chat
        # (ignore if already nullable)
        try:
            db_exec("ALTER TABLE conversations MODIFY seller_id int NULL")
        except Exception:
            pass


        # -------------------------------------------------
        # Flash workflow schema (seller -> admin approvals)
        # Ensure required product columns + flash_requests table
        # -------------------------------------------------
        try:
            if not db_has_column("products", "is_flash"):
                db_exec("ALTER TABLE products ADD COLUMN is_flash TINYINT(1) NOT NULL DEFAULT 0")
            if not db_has_column("products", "flash_end_at"):
                db_exec("ALTER TABLE products ADD COLUMN flash_end_at DATETIME NULL")
            if not db_has_column("products", "dispatch_type"):
                db_exec("ALTER TABLE products ADD COLUMN dispatch_type ENUM('normal','flash','full') NOT NULL DEFAULT 'normal'")
            if not db_has_column("products", "is_archive"):
                db_exec("ALTER TABLE products ADD COLUMN is_archive TINYINT(1) NOT NULL DEFAULT 0")

            if not db_has_table("flash_requests"):
                db_exec("""CREATE TABLE IF NOT EXISTS flash_requests (
                    id INT NOT NULL AUTO_INCREMENT,
                    product_id VARCHAR(32) NOT NULL,
                    seller_id INT NOT NULL,
                    requested_price_usd DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                    requested_compare_at_usd DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                    requested_end_at DATETIME NOT NULL,
                    status ENUM('pending','approved','rejected','cancelled') NOT NULL DEFAULT 'pending',
                    seller_note VARCHAR(255) DEFAULT NULL,
                    admin_note VARCHAR(255) DEFAULT NULL,
                    reviewed_by INT DEFAULT NULL,
                    reviewed_at DATETIME DEFAULT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY idx_flash_req_status (status, created_at),
                    KEY idx_flash_req_product (product_id),
                    KEY idx_flash_req_seller (seller_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        except Exception:
            pass
    except Exception:
        pass

# -----------------------------
# Row getter (supports dict/tuple)
# -----------------------------
def _row_get(row, key, idx=None, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    if idx is not None:
        try:
            return row[idx]
        except Exception:
            return default
    return default


# ============================================================
# GLOBAL TEMPLATE CONTEXT (Premium, DB-driven)
# ============================================================
def _current_user():
    uid = session.get("user_id")
    role = (session.get("role") or "").lower()
    if not uid:
        return {"is_auth": False, "id": None, "role": None, "name": None}
    u = db_one("SELECT id, name, role FROM users WHERE id=%s", (int(uid),))
    return {
        "is_auth": True,
        "id": _row_get(u, "id", 0),
        "role": (_row_get(u, "role", 2, role) or role).lower(),
        "name": _row_get(u, "name", 1),
    }


@app.context_processor
def inject_globals():
    user = _current_user()
    # Categories are DB-driven (no hardcoding)
    cats = db_all(
        "SELECT name, slug, hero_image FROM categories WHERE is_active=1 ORDER BY sort_order ASC, name ASC"
    )
    categories = [
        {
            "name": _row_get(c, "name", 0),
            "slug": _row_get(c, "slug", 1),
            "hero": _row_get(c, "hero_image", 2),
        }
        for c in (cats or [])
    ]

    # Site settings (topbar copy)
    s_en = db_one("SELECT v FROM site_settings WHERE k='topbar_text_en'")
    s_bn = db_one("SELECT v FROM site_settings WHERE k='topbar_text_bn'")

    # Roles can come from either the normal user session OR the admin portal session.
    # Inject a consistent set of auth flags for templates.
    a = current_admin()
    is_admin = True if a else False
    if is_admin:
        role = (a.get("role") or "admin").lower()
        is_user = False
    else:
        role = (user.get("role") or "").lower() if user.get("is_auth") else "guest"
        is_user = True if user.get("is_auth") else False
    dashboard_url = "/"
    if role == "buyer":
        dashboard_url = "/buyer/dashboard"
    elif role == "seller":
        dashboard_url = "/seller/dashboard"
    elif role in ["admin", "superadmin"]:
        dashboard_url = "/admin"

    return {
        "current_user": user,
        "current_admin": a,
        "is_admin": is_admin,
        "is_user": is_user,
        "role": role,
        "categories": categories,
        "dashboard_url": dashboard_url,
        "topbar_text_en": (_row_get(s_en, "v", 0, "") if s_en else ""),
        "topbar_text_bn": (_row_get(s_bn, "v", 0, "") if s_bn else ""),
    }

# -----------------------------
# Auth helpers
# -----------------------------
def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect("/login")
            if role and session.get("role") != role:
                return redirect("/")
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect("/admin/login")
        return fn(*args, **kwargs)
    return wrapper


def current_admin():
    """Return current admin dict: {id, role, src}."""
    aid = session.get("admin_id")
    if not aid:
        return None
    src = session.get("admin_src") or "admins"
    if src == "users":
        u = db_one("SELECT id, role, name, email FROM users WHERE id=%s", (int(aid),))
        if not u:
            return None
        return {
            "id": _row_get(u, "id", 0),
            "role": (_row_get(u, "role", 1, "admin") or "admin").lower(),
            "name": _row_get(u, "name", 2),
            "email": _row_get(u, "email", 3),
            "src": "users",
        }
    a = db_one("SELECT id, role, name, email, phone, address, bio, photo_url FROM admins WHERE id=%s", (int(aid),))
    if not a:
        return None
    return {
        "id": _row_get(a, "id", 0),
        "role": (_row_get(a, "role", 1, "admin") or "admin").lower(),
        "name": _row_get(a, "name", 2),
        "email": _row_get(a, "email", 3),
        "phone": _row_get(a, "phone", 4, ''),
        "address": _row_get(a, "address", 5, ''),
        "bio": _row_get(a, "bio", 6, ''),
        "photo_url": _row_get(a, "photo_url", 7, ''),
        "src": "admins",
    }


def superadmin_required(fn):
    """Allow only superadmin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect("/admin/login")
        a = current_admin()
        if not a or (a.get("role") != "superadmin"):
            return redirect("/admin/dashboard")
        return fn(*args, **kwargs)
    return wrapper

def normalize_role_public(role):
    role = (role or "").strip().lower()
    if role in ("buyer", "seller"):
        return role
    return "buyer"

# -----------------------------
# OTP helpers
# -----------------------------
def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email, otp, name=None):
    msg = Message(
        subject="Handmade Heritage - Email Verification Code",
        recipients=[email],
    )
    msg.body = f"""Your verification code is: {otp}

Enter this code to verify your email.
If you didn't request this, you can ignore this email.
"""
    try:
        msg.html = render_template("emails/otp.html", code=otp, buyer_name=name or "Customer")
    except Exception:
        pass
    mail.send(msg)

# -----------------------------
# Order code / tracking generator
# -----------------------------
def make_order_code():
    # HH-YYYYMMDD-XXXXXX
    return "HH-" + datetime.now().strftime("%Y%m%d") + "-" + str(random.randint(100000, 999999))

# -----------------------------
# Member ID (deterministic, realistic-looking)
# -----------------------------
def make_member_id(user_row):
    """Create a stable member id without adding DB columns.

    Format: HH-<YEAR>-<6digits>-<CHK4>
    Example: HH-2026-000123-9A2F
    """
    uid = int(_row_get(user_row, 'id', 0, 0) or 0)
    created = _row_get(user_row, 'created_at', 5)
    try:
        year = int(getattr(created, 'year', None) or datetime.utcnow().year)
    except Exception:
        year = datetime.utcnow().year
    secret = str(app.config.get('SECRET_KEY', 'hh-secret'))
    raw = f"{uid}:{year}:{secret}".encode('utf-8')
    chk = hashlib.sha1(raw).hexdigest()[:4].upper()
    return f"HH-{year}-{uid:06d}-{chk}"

# ============================================================
# PAGES
# ============================================================
@app.get("/")
def home_page(): return render_template('public/home.html')

@app.get("/shop")
def shop_page(): return render_template('public/shop.html')


@app.get("/shop/category/<slug>")
def shop_category_redirect(slug):
    s = _normalize_category_slug(slug or "")
    return redirect(f"/shop?category={s}")

@app.get("/cart")
def cart_page():
    # Cart is for shoppers (guest/buyer) only
    if session.get("admin_id"):
        return redirect("/admin/dashboard")
    role = (session.get("role") or "buyer").lower()
    if role in ("seller", "admin", "superadmin"):
        return redirect("/")
    return render_template('public/cart.html')

@app.get("/checkout")
def checkout_page():
    if session.get("admin_id"):
        return redirect("/admin/dashboard")
    role = (session.get("role") or "buyer").lower()
    if role in ("seller", "admin", "superadmin"):
        return redirect("/")
    return render_template('public/checkout.html')

@app.get("/order-success")
def order_success_page(): return render_template('public/order_success.html')

@app.get("/track")
def track_page(): return render_template('public/track.html')

@app.get("/help")
def help_page(): return render_template('public/help.html')

@app.get("/shipping")
def shipping_page(): return render_template('public/shipping.html')

@app.get("/returns")
def returns_page(): return render_template('public/returns.html')

@app.get("/about")
def about_page(): return render_template('public/about.html')

@app.get("/artisans")
def artisans_page(): return render_template('public/artisans.html')

@app.get("/reviews")
def reviews_page(): return render_template('public/reviews.html')

@app.get("/privacy")
def privacy_page(): return render_template('public/privacy.html')

@app.get("/terms")
def terms_page(): return render_template('public/terms.html')

@app.get("/cookies")
def cookies_page(): return render_template('public/cookies.html')

@app.get("/contact")
def contact_page(): return render_template('public/contact.html')

@app.get("/login")
def login_page(): return render_template('auth/login.html')

@app.get("/register")
def register_buyer_page(): return render_template('auth/register_buyer.html')

@app.get("/register/seller")
def register_seller_page(): return render_template('auth/register_seller.html')

# ============================================================
# AUTH (Buyer/Seller) - OTP
# ============================================================
@app.post("/api/register")
def api_register():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")
    role = normalize_role_public(data.get("role"))

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required."}), 400

    existing = db_one("SELECT id FROM users WHERE email=%s", (email,))
    if existing:
        return jsonify({"error": "Email already exists."}), 400

    pw_hash = generate_password_hash(password)
    otp = generate_otp()

    db_exec(
        "INSERT INTO users(name,email,password,role,is_verified,otp,status) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (name, email, pw_hash, role, 0, otp, "active"),
    )

    try:
        send_otp_email(email, otp)
    except Exception:
        pass

    return jsonify({"success": True, "message": "Registered. Please verify OTP sent to your email."})

@app.post("/api/verify-otp")
def api_verify_otp():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()

    if not email or not otp:
        return jsonify({"error": "Email and OTP required."}), 400

    user = db_one("SELECT id, otp, is_verified FROM users WHERE email=%s", (email,))
    if not user:
        return jsonify({"error": "User not found."}), 404

    if int(_row_get(user, "is_verified", 2, 0) or 0) == 1:
        return jsonify({"success": True, "message": "Already verified."})

    if (_row_get(user, "otp", 1) or "") != otp:
        return jsonify({"error": "Invalid OTP."}), 400

    db_exec("UPDATE users SET is_verified=1, otp=NULL WHERE email=%s", (email,))
    return jsonify({"success": True, "message": "Email verified successfully."})

# Backward-compatible alias (older templates call /api/verify)
@app.post("/api/verify")
def api_verify_otp_alias():
    return api_verify_otp()

@app.post("/api/resend-otp")
def api_resend_otp():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email required."}), 400

    user = db_one("SELECT id, is_verified FROM users WHERE email=%s", (email,))
    if not user:
        return jsonify({"error": "User not found."}), 404

    if int(_row_get(user, "is_verified", 1, 0) or 0) == 1:
        return jsonify({"success": True, "message": "Already verified."})

    otp = generate_otp()
    db_exec("UPDATE users SET otp=%s WHERE email=%s", (otp, email))

    try:
        send_otp_email(email, otp)
    except Exception:
        pass

    return jsonify({"success": True, "message": "OTP resent."})

@app.post("/api/login")
def api_login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")

    if not email or not password:
        return jsonify({"error": "Email and password required."}), 400

    user = db_one("SELECT id, password, role, is_verified, status FROM users WHERE email=%s", (email,))
    if not user:
        return jsonify({"error": "Invalid credentials."}), 401

    if (_row_get(user, "status", 4, "active") or "").lower() != "active":
        return jsonify({"error": "Account disabled."}), 403

    if int(_row_get(user, "is_verified", 3, 0) or 0) != 1:
        return jsonify({"error": "Please verify OTP first."}), 403

    # Admin & Super Admin accounts must sign in via /admin/login
    role_raw = (_row_get(user, "role", 2, "buyer") or "buyer").lower()
    if role_raw in ("admin", "superadmin"):
        session.clear()
        return jsonify({"error": "Admin accounts must sign in from Admin Login.", "redirect": "/admin/login"}), 403

    if not check_password_hash(_row_get(user, "password", 1, ""), password):
        return jsonify({"error": "Invalid credentials."}), 401

    session["user_id"] = _row_get(user, "id", 0)
    session["role"] = _row_get(user, "role", 2, "buyer")

    # Role-based redirect (premium UX)
    role = (session.get("role") or "buyer").lower()

    if role == "seller":
        sp = db_one("SELECT verification_status FROM seller_profiles WHERE user_id=%s", (session.get("user_id"),))
        status = (_row_get(sp, "verification_status", 0, "pending") if sp else "pending") or "pending"
        if str(status).lower() != "approved":
            redirect_url = "/seller/kyc"
        else:
            redirect_url = "/seller/dashboard"
    else:
        # buyers (and any other non-admin roles)
        redirect_url = "/buyer/dashboard"


    return jsonify({"success": True, "redirect": redirect_url, "role": role})

@app.get("/logout")
def logout():
    session.clear()
    return redirect("/")


# ============================================================
# BUYER DASHBOARD (Premium)
# ============================================================
@app.get("/buyer/dashboard")
def buyer_dashboard():
    uid = _require_login()
    if not uid:
        return redirect("/login")
    role = (session.get("role") or "buyer").lower()
    if role != "buyer":
        return redirect("/")

    stats = {
        "orders": db_one("SELECT COUNT(*) AS c FROM orders WHERE buyer_id=%s", (uid,)),
        "wishlist": db_one("SELECT COUNT(*) AS c FROM wishlist_items WHERE user_id=%s", (uid,)),
    }

    orders = db_all(
        """SELECT id, order_code, status, payment_status, grand_total, payment_method, trnx_id, created_at
             FROM orders
             WHERE buyer_id=%s
             ORDER BY created_at DESC
             LIMIT 20""",
        (uid,),
    ) or []

    out_orders = []
    for o in orders:
        oid = int(_row_get(o, "id", 0, 0) or 0)
        code = _row_get(o, "order_code", 1, "")
        status = (_row_get(o, "status", 2, "") or "").lower()

        # Shipments table (see db.sql) uses `current_status` and `last_update`.
        # The previous query referenced non-existent columns and caused a 500 on /buyer/dashboard.
        ship = db_one(
            "SELECT carrier, tracking_code, current_status AS ship_status, last_update "
            "FROM shipments WHERE order_id=%s",
            (oid,),
        )
        tracking_code = _row_get(ship, "tracking_code", 1, "") if ship else ""
        carrier = _row_get(ship, "carrier", 0, "") if ship else ""

        items = db_all(
            "SELECT product_id, title, image_url, qty FROM order_items WHERE order_id=%s ORDER BY id ASC",
            (oid,),
        ) or []

        item_list = []
        for it in items:
            pid = str(_row_get(it, "product_id", 0, "") or "").strip()
            already = db_one("SELECT id FROM reviews WHERE buyer_id=%s AND product_id=%s AND status IN ('approved','pending') LIMIT 1", (uid, pid))
            item_list.append({
                "product_id": pid,
                "title": _row_get(it, "title", 1, ""),
                "image_url": _row_get(it, "image_url", 2, ""),
                "qty": int(_row_get(it, "qty", 3, 1) or 1),
                "can_review": True if status == "delivered" else False,
                "has_review": True if already else False,
            })

        out_orders.append({
            "id": oid,
            "order_code": code,
            "status": status,
            "payment_status": (_row_get(o, "payment_status", 3, "") or "").lower(),
            "grand_total": float(_row_get(o, "grand_total", 4, 0) or 0),
            "payment_method": _row_get(o, "payment_method", 5, ""),
            "trnx_id": _row_get(o, "trnx_id", 6, ""),
            "created_at": _row_get(o, "created_at", 7),
            "tracking_code": tracking_code,
            "carrier": carrier,
            "items": item_list,
        })

    return render_template("buyer/dashboard.html", stats=stats, orders=out_orders)


# ============================================================
# PROFILE (Premium Buyer/Seller)
# ============================================================
def _require_login():
    uid = session.get("user_id")
    if not uid:
        return None
    return int(uid)

def _get_or_create_profile(uid: int):
    p = db_one("SELECT user_id, display_name, phone, avatar_url, bio, city, country, address_line, language_pref, theme_pref FROM user_profiles WHERE user_id=%s", (uid,))
    if p:
        return p
    # Create minimal profile row
    u = db_one("SELECT name, email, role FROM users WHERE id=%s", (uid,))
    display = _row_get(u, "name", 0) if u else ""
    db_exec(
        "INSERT INTO user_profiles (user_id, display_name) VALUES (%s,%s)",
        (uid, display),
    )
    return db_one("SELECT user_id, display_name, phone, avatar_url, bio, city, country, address_line, language_pref, theme_pref FROM user_profiles WHERE user_id=%s", (uid,))

@app.get("/profile")
def profile_page():
    uid = _require_login()
    if not uid:
        return redirect("/login")
    u = db_one("SELECT id, name, email, role, status, created_at FROM users WHERE id=%s", (uid,))
    role = _row_get(u, "role", 3) if u else "buyer"
    profile = _get_or_create_profile(uid)

    seller = None
    if role == "seller":
        seller = db_one(
            "SELECT shop_name, tagline, instagram, website, address, verification_status, payout_method, payout_account_masked "
            "FROM seller_profiles WHERE user_id=%s",
            (uid,),
        )
    member_id = make_member_id(u) if u else ''
    return render_template('seller/profile.html' if role == "seller" else "buyer/profile.html",
        user=u,
        profile=profile,
        seller=seller,
        member_id=member_id,
    )

@app.get("/profile/edit")
def profile_edit_page():
    uid = _require_login()
    if not uid:
        return redirect("/login")
    u = db_one("SELECT id, name, email, role FROM users WHERE id=%s", (uid,))
    profile = _get_or_create_profile(uid)
    seller = None
    if _row_get(u, "role", 3) == "seller":
        seller = db_one(
            "SELECT shop_name, tagline, instagram, facebook, website FROM seller_profiles WHERE user_id=%s",
            (uid,),
        )
    return render_template('account/profile_edit.html', user=u, profile=profile, seller=seller)

@app.post("/profile/edit")
def profile_edit_save():
    uid = _require_login()
    if not uid:
        return redirect("/login")

    display_name = (request.form.get("display_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    bio = (request.form.get("bio") or "").strip()
    city = (request.form.get("city") or "").strip()
    country = (request.form.get("country") or "").strip()
    address_line = (request.form.get("address_line") or "").strip()
    language_pref = (request.form.get("language_pref") or "en").strip()
    theme_pref = (request.form.get("theme_pref") or "default").strip()

    avatar_url = None
    file = request.files.get("avatar")
    if file and file.filename:
        fn = secure_filename(file.filename)
        ext = os.path.splitext(fn)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
            # ignore invalid filetypes
            ext = ".png"
        out_name = f"u{uid}_{secrets.token_hex(6)}{ext}"
        out_dir = os.path.join(app.root_path, "static", "uploads", "avatars")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, out_name)
        file.save(out_path)
        avatar_url = f"/static/uploads/avatars/{out_name}"

    _get_or_create_profile(uid)
    if avatar_url:
        db_exec(
            "UPDATE user_profiles SET display_name=%s, phone=%s, avatar_url=%s, bio=%s, city=%s, country=%s, address_line=%s, language_pref=%s, theme_pref=%s, updated_at=NOW() WHERE user_id=%s",
            (display_name, phone, avatar_url, bio, city, country, address_line, language_pref, theme_pref, uid),
        )
    else:
        db_exec(
            "UPDATE user_profiles SET display_name=%s, phone=%s, bio=%s, city=%s, country=%s, address_line=%s, language_pref=%s, theme_pref=%s, updated_at=NOW() WHERE user_id=%s",
            (display_name, phone, bio, city, country, address_line, language_pref, theme_pref, uid),
        )

    # Optional: update seller public profile fields
    role = session.get("role")
    if role == "seller":
        shop_name = (request.form.get("shop_name") or "").strip()
        tagline = (request.form.get("tagline") or "").strip()
        instagram = (request.form.get("instagram") or "").strip()
        facebook = (request.form.get("facebook") or "").strip()
        website = (request.form.get("website") or "").strip()
        db_exec(
            "UPDATE seller_profiles SET shop_name=%s, tagline=%s, instagram=%s, facebook=%s, website=%s WHERE user_id=%s",
            (shop_name, tagline, instagram, facebook, website, uid),
        )



    # -----------------------------
    # Password change (optional)
    # -----------------------------
    current_pw = (request.form.get("current_password") or "")
    new_pw = (request.form.get("new_password") or "").strip()
    confirm_pw = (request.form.get("confirm_password") or "").strip()

    pw_flag = None
    if new_pw or confirm_pw:
        if not current_pw:
            pw_flag = "missing_current"
        elif new_pw != confirm_pw:
            pw_flag = "mismatch"
        elif len(new_pw) < 8:
            pw_flag = "weak"
        else:
            urow = db_one("SELECT password FROM users WHERE id=%s", (uid,))
            if not urow or (not check_password_hash(_row_get(urow, "password", 0, ""), current_pw)):
                pw_flag = "wrong_current"
            else:
                db_exec(
                    "UPDATE users SET password=%s, updated_at=NOW() WHERE id=%s",
                    (generate_password_hash(new_pw), uid),
                )
                pw_flag = "changed"

    if pw_flag and pw_flag != "changed":
        return redirect(f"/profile/edit?pw={pw_flag}")
    return redirect("/profile?pw=changed") if (locals().get('pw_flag') == 'changed') else redirect("/profile")


# ============================================================
# CART (session-based)
# ============================================================
def _get_cart():
    cart = session.get("cart")
    if not isinstance(cart, dict):
        cart = {}
        session["cart"] = cart
    return cart

@app.post("/api/cart/set")
def api_cart_set():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id") or "").strip()
    qty = data.get("qty")
    if not pid:
        return jsonify({"error": "product_id required"}), 400
    try:
        qty = int(qty)
    except Exception:
        qty = 1
    cart = _get_cart()
    if qty <= 0:
        cart.pop(pid, None)
    else:
        cart[pid] = qty
    session["cart"] = cart
    return jsonify({"success": True, "cart": cart})


@app.post("/api/cart/add")
def api_cart_add():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id") or "").strip()
    qty = int(data.get("qty") or 1)
    if not pid:
        return jsonify({"error": "product_id required"}), 400
    if qty < 1:
        qty = 1

    cart = _get_cart()
    cart[pid] = int(cart.get(pid, 0)) + qty
    session["cart"] = cart
    return jsonify({"success": True, "cart": cart})

@app.post("/api/cart/remove")
def api_cart_remove():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id") or "").strip()
    if not pid:
        return jsonify({"error": "product_id required"}), 400
    cart = _get_cart()
    if pid in cart:
        del cart[pid]
    session["cart"] = cart
    return jsonify({"success": True, "cart": cart})

@app.post("/api/cart/clear")
def api_cart_clear():
    session["cart"] = {}
    return jsonify({"success": True})

@app.get("/api/cart")
def api_cart_get():
    cart = _get_cart()
    items = []
    total = 0.0

    for pid, qty in cart.items():
        p = db_one("SELECT id, title, title_bn, price_usd, image_url FROM products WHERE id=%s", (pid,))
        if not p:
            continue
        price = float(_row_get(p, "price_usd", 3, 0) or 0)
        line = price * int(qty)
        total += line
        items.append({
            "id": _row_get(p, "id", 0),
            "title": _row_get(p, "title", 1),
            "bn": _row_get(p, "title_bn", 2),
            "usd": price,
            "img": _row_get(p, "image_url", 4),
            "qty": int(qty),
            "line_total": line,
        })
    return jsonify({"items": items, "total": total})

# ============================================================
# CHECKOUT / ORDER
# ============================================================
@app.post("/api/checkout")
@login_required()
def api_checkout():
    data = request.get_json(force=True) or {}
    shipping_name = (data.get("shipping_name") or "").strip()
    shipping_phone = (data.get("shipping_phone") or "").strip()
    shipping_address = (data.get("shipping_address") or "").strip()
    payment_method = (data.get("payment_method") or "cod").strip()
    trnx_id = (data.get("trnx_id") or "").strip()
    payment_note = (data.get("payment_note") or "").strip()

    if not shipping_name or not shipping_phone or not shipping_address:
        return jsonify({"error": "Shipping info required."}), 400

    cart = _get_cart()
    if not cart:
        return jsonify({"error": "Cart empty."}), 400

    subtotal = 0.0
    order_items = []
    for pid, qty in cart.items():
        p = db_one(
            "SELECT id, seller_id, title, image_url, price_usd FROM products WHERE id=%s AND status='active'",
            (pid,),
        )
        if not p:
            continue
        price = float(_row_get(p, "price_usd", 4, 0) or 0)
        q = int(qty)
        line = price * q
        subtotal += line
        order_items.append({
            "product_id": _row_get(p, "id", 0),
            "seller_id": _row_get(p, "seller_id", 1),
            "title": _row_get(p, "title", 2),
            "image_url": _row_get(p, "image_url", 3),
            "unit_price": price,
            "qty": q,
            "line_total": line,
        })

    if not order_items:
        return jsonify({"error": "No valid items."}), 400

    buyer_id = int(session.get("user_id"))
    ref = make_order_code()

    shipping_fee = 0.0
    tax_fee = 0.0
    discount = 0.0
    grand_total = max(0.0, float(subtotal) + float(shipping_fee) + float(tax_fee) - float(discount))

    # Escrow style: buyer pays to platform account.
    # If trx id is provided (online pay), mark as 'submitted' so admin can verify.
    pm = (payment_method or '').strip().lower()
    pay_status = 'unpaid'
    if pm and pm not in ['cod', 'cash', 'cash_on_delivery'] and (trnx_id or '').strip():
        pay_status = 'submitted'

    db_exec(
        "INSERT INTO orders(order_code,buyer_id,subtotal,shipping_fee,tax_fee,discount,grand_total,payment_method,trnx_id,payment_note,payment_status,status,shipping_name,shipping_phone,shipping_address,created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,NOW())",
        (ref, buyer_id, subtotal, shipping_fee, tax_fee, discount, grand_total, payment_method, trnx_id or None, payment_note or None, pay_status, shipping_name, shipping_phone, shipping_address),
    )

    order = db_one("SELECT id FROM orders WHERE order_code=%s", (ref,))
    order_id = int(_row_get(order, "id", 0) or 0)

    for it in order_items:
        db_exec(
            "INSERT INTO order_items(order_id,product_id,seller_id,title,image_url,unit_price,qty,line_total) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_id,
                it["product_id"],
                it["seller_id"],
                it["title"],
                it["image_url"],
                it["unit_price"],
                it["qty"],
                it["line_total"],
            ),
        )
        try:
            db_exec("UPDATE products SET sold_count = sold_count + %s WHERE id=%s", (it["qty"], it["product_id"]))
        except Exception:
            pass

    session["cart"] = {}
    return jsonify({"success": True, "order_code": ref})

# ============================================================
# NEW: Order Create API (TrnxID + Method + Total)  ✅ (Added Here)
# ============================================================
@app.post("/api/orders/create")
@login_required()
def api_order_create():
    data = request.get_json(force=True) or {}
    buyer_id = int(session.get("user_id"))
    order_code = make_order_code()  # HH-YYYYMMDD-XXXXXX

    payment = data.get("payment") or {}
    pricing = data.get("pricing") or {}

    trnx_id = (payment.get("trnx_id") or "").strip()
    method = (payment.get("method") or "").strip()
    total = pricing.get("total_usd")

    try:
        total = float(total)
    except Exception:
        total = None

    if not method or total is None:
        return jsonify({"error": "payment.method and pricing.total_usd required."}), 400

    pay_status = 'unpaid'
    pm = (method or '').strip().lower()
    if pm and pm not in ['cod','cash','cash_on_delivery'] and trnx_id:
        pay_status = 'submitted'

    db_exec(
        "INSERT INTO orders(order_code,buyer_id,subtotal,grand_total,payment_method,trnx_id,payment_status,status,created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',NOW())",
        (order_code, buyer_id, total, total, method, trnx_id or None, pay_status),
    )

    return jsonify({"success": True, "order_code": order_code})

@app.get("/api/order/<order_code>")
def api_order_track(order_code):
    order = db_one("SELECT * FROM orders WHERE order_code=%s", (order_code,))
    if not order:
        return jsonify({"error": "Not found"}), 404

    items = db_all(
        "SELECT title, qty, unit_price, line_total FROM order_items WHERE order_id=%s",
        (int(_row_get(order, "id", 0)),),
    )

    return jsonify({"order": order, "items": items})

@app.get("/api/track")
def api_track_manifest():
    """Return shipment + timeline for an order_code.

    Access rules:
      - If logged in as buyer and owns the order -> allow.
      - Otherwise require email matches buyer email (from track page input).
    """
    order_code = (request.args.get("code") or request.args.get("order_code") or "").strip()
    email = (request.args.get("email") or "").strip().lower()

    if not order_code:
        return jsonify({"error": "order_code required"}), 400

    o = db_one(
        "SELECT o.id, o.order_code, o.status, o.payment_status, o.created_at, u.email AS buyer_email, u.name AS buyer_name "
        "FROM orders o JOIN users u ON u.id=o.buyer_id WHERE o.order_code=%s",
        (order_code,),
    )
    if not o:
        return jsonify({"error": "Not found"}), 404

    buyer_email = (_row_get(o, "buyer_email", 5, "") or "").lower()
    buyer_name = _row_get(o, "buyer_name", 6, "") or "Customer"

    # Auth check
    if session.get("user_id") and (session.get("role") or "").lower() == "buyer":
        if int(session.get("user_id")) != int(db_one("SELECT buyer_id AS id FROM orders WHERE order_code=%s", (order_code,))["id"]):
            return jsonify({"error": "Unauthorized"}), 403
    else:
        if not email or email != buyer_email:
            return jsonify({"error": "Email mismatch"}), 403

    oid = int(_row_get(o, "id", 0, 0) or 0)
    ship = db_one("SELECT carrier, tracking_code, status, shipped_at, delivered_at, updated_at FROM shipments WHERE order_id=%s", (oid,))
    timeline = db_all(
        "SELECT status, note, created_at FROM order_tracking WHERE order_id=%s ORDER BY created_at ASC",
        (oid,),
    ) or []

    # Progress mapping
    st = (_row_get(o, "status", 2, "") or "").lower()
    progress_map = {
        "pending": 0.10,
        "confirmed": 0.20,
        "packed": 0.35,
        "shipped": 0.55,
        "out_for_delivery": 0.75,
        "delivered": 1.00,
        "cancelled": 0.0,
        "returned": 0.0,
        "refunded": 0.0,
    }
    progress = progress_map.get(st, 0.12)

    events = []
    for t in timeline:
        status = _row_get(t, "status", 0, "") or ""
        note = _row_get(t, "note", 1, "") or ""
        ts = _row_get(t, "created_at", 2)
        events.append({
            "title": status.replace("_", " ").title(),
            "desc": note,
            "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "location": "",
        })

    carrier = _row_get(ship, "carrier", 0, "") if ship else ""
    tracking_code = _row_get(ship, "tracking_code", 1, "") if ship else ""
    ship_status = _row_get(ship, "status", 2, "") if ship else ""

    return jsonify({
        "verified": True,
        "order_code": order_code,
        "status": st.replace("_", " ").title() if st else "Pending",
        "carrier": carrier or "Artisan Logistics",
        "tracking_code": tracking_code,
        "ship_status": ship_status,
        "from": "Dhaka Node",
        "eta": "—",
        "service": carrier or "Handmade Priority",
        "weight": "—",
        "value": "—",
        "progress": progress,
        "events": events,
        "buyer_name": buyer_name,
    })


# ============================================================
# ADMIN
# ============================================================
@app.get("/admin/login")
def admin_login_page(): return render_template("admin/login.html")

@app.post("/admin/login")
def admin_login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "")

    if not email or not password:
        return redirect("/admin/login")

    # 1) Try dedicated admins table first
    admin = db_one("SELECT id, password, status FROM admins WHERE email=%s", (email,))
    if admin and (_row_get(admin, "status", 2, "active") or "").lower() == "active":
        if check_password_hash(_row_get(admin, "password", 1, ""), password):
            session["admin_id"] = _row_get(admin, "id", 0)
            session["admin_src"] = "admins"
            return redirect("/admin/dashboard")

    # 2) Fallback: allow admin/superadmin stored in users table
    u = db_one("SELECT id, password, role, status, is_verified FROM users WHERE email=%s", (email,))
    if not u:
        return redirect("/admin/login")

    role = (_row_get(u, "role", 2, "") or "").lower()
    if role not in ["admin", "superadmin"]:
        return redirect("/admin/login")

    if (_row_get(u, "status", 3, "active") or "").lower() != "active":
        return redirect("/admin/login")

    # If OTP flow is used for all users, ensure verified for user-based admins
    try:
        if int(_row_get(u, "is_verified", 4, 1) or 0) != 1:
            return redirect("/admin/login")
    except Exception:
        pass

    if not check_password_hash(_row_get(u, "password", 1, ""), password):
        return redirect("/admin/login")

    session["admin_id"] = _row_get(u, "id", 0)
    session["admin_src"] = "users"
    return redirect("/admin/dashboard")


@app.get("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_src", None)
    return redirect("/admin/login")



# ----------------------------
# Seed one superadmin (DEV ONLY)
# ----------------------------
@app.get("/_seed_admin_once")
def _seed_admin_once():
    # IMPORTANT: Run once, then protect/remove for production
    email = "admin@hh.com"
    exists = db_one("SELECT id FROM admins WHERE email=%s", (email,))
    if exists:
        return "Admin already exists."

    hashed = generate_password_hash("Admin@1234")
    db_exec(
        "INSERT INTO admins (name, email, password, role, status) VALUES (%s,%s,%s,'superadmin','active')",
        ("Super Admin", email, hashed),
    )
    return "Created superadmin: admin@hh.com / Admin@1234"

@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    a = current_admin() or {"role": "admin"}
    # Superadmin gets a separate executive dashboard
    if (a.get("role") or "").lower() == "superadmin":
        return redirect("/superadmin/dashboard")

    # -------------------------------------------------
    # Admin overview (ops): human-friendly dashboard
    # -------------------------------------------------
    def _c(row, key='c'):
        try:
            return int(_row_get(row, key, 0, 0) or 0)
        except Exception:
            return 0

    # Snapshot cards (no "today" / no payout readiness)
    pay_submitted = _c(db_one("SELECT COUNT(*) c FROM orders WHERE payment_status='submitted'"))
    kyc_pending = 0
    try:
        kyc_pending = _c(db_one("SELECT COUNT(*) c FROM seller_profiles WHERE verification_status='pending'"))
    except Exception:
        kyc_pending = 0

    orders_attention = 0
    try:
        orders_attention = _c(
            db_one(
                "SELECT COUNT(*) c FROM orders "
                "WHERE status IN ('pending','confirmed','packed') OR payment_status='submitted'"
            )
        )
    except Exception:
        orders_attention = 0

    support_open = 0
    try:
        support_open = _c(
            db_one(
                "SELECT COUNT(*) c FROM conversations WHERE type IN ('buyer_support','seller_support','support')"
            )
        )
    except Exception:
        support_open = 0

    ops = {
        'kyc_pending': kyc_pending,
        'pay_submitted': pay_submitted,
        'orders_attention': orders_attention,
        'support_open': support_open,
    }

    # Backward compatible KPIs (older template keys)
    kpi = {
        'pay_submitted': pay_submitted,
        'orders_pending': 0,
        'orders_shipped': 0,
        'orders_delivered': 0,
        'payout_ready': 0,
    }
    try:
        kpi['orders_pending'] = _c(db_one("SELECT COUNT(*) c FROM orders WHERE status IN ('pending','confirmed','packed')"))
        kpi['orders_shipped'] = _c(db_one("SELECT COUNT(*) c FROM orders WHERE status IN ('shipped','out_for_delivery')"))
        kpi['orders_delivered'] = _c(db_one("SELECT COUNT(*) c FROM orders WHERE status='delivered'"))
    except Exception:
        pass

    # KYC queue preview
    try:
        kyc_queue = db_all(
            "SELECT sp.user_id, sp.verification_status, sp.updated_at, sp.created_at, u.name, u.email "
            "FROM seller_profiles sp JOIN users u ON u.id=sp.user_id "
            "WHERE sp.verification_status='pending' "
            "ORDER BY sp.updated_at DESC, sp.created_at DESC LIMIT 8"
        )
    except Exception:
        kyc_queue = []

    # Recent activity (audit)
    try:
        activity = db_all(
            "SELECT l.created_at, l.actor_role, l.action, l.entity_type, l.entity_id, l.details, "
            "COALESCE(ad.email, u.email) actor_email "
            "FROM audit_logs l "
            "LEFT JOIN admins ad ON (l.actor_role IN ('admin','superadmin') AND ad.id=l.actor_id) "
            "LEFT JOIN users  u  ON (u.id=l.actor_id) "
            "ORDER BY l.created_at DESC LIMIT 12"
        )
    except Exception:
        activity = []

    # Recent support threads (with unread count for this admin)
    viewer_role = 'admin'
    viewer_id = int((a.get('id') or 0) if isinstance(a, dict) else 0)
    try:
        threads = db_all(
            """
            SELECT
              c.id,
              c.type,
              COALESCE(c.last_message_at, c.created_at) AS last_at,
              (
                SELECT COUNT(*)
                FROM messages m
                LEFT JOIN conversation_reads cr
                  ON cr.conversation_id=c.id AND cr.viewer_role=%s AND cr.viewer_id=%s
                WHERE m.conversation_id=c.id
                  AND m.id > COALESCE(cr.last_read_message_id,0)
                  AND NOT (m.sender_role=%s AND m.sender_id=%s)
              ) AS unread_count,
              (
                SELECT m2.message_text
                FROM messages m2
                WHERE m2.conversation_id=c.id
                ORDER BY m2.id DESC
                LIMIT 1
              ) AS last_message,
              ub.name AS buyer_name,
              ub.email AS buyer_email,
              us.name AS seller_name,
              us.email AS seller_email,
              o.order_code
            FROM conversations c
            LEFT JOIN users ub ON ub.id=c.buyer_id
            LEFT JOIN users us ON us.id=c.seller_id
            LEFT JOIN orders o ON o.id=c.order_id
            WHERE c.type IN ('buyer_support','seller_support','support')
            ORDER BY last_at DESC, c.id DESC
            LIMIT 6
            """,
            (viewer_role, viewer_id, viewer_role, viewer_id),
        )
    except Exception:
        threads = []

    return render_template(
        "admin/dashboard_admin.html",
        admin=a,
        ops=ops,
        kpi=kpi,
        kyc_queue=kyc_queue,
        activity=activity,
        threads=threads,
    )


@app.get("/superadmin/dashboard")
@superadmin_required
def superadmin_dashboard():
    a = current_admin() or {"role": "superadmin"}

    # --- KPIs (30 days) ---
    # GMV excludes cancelled/returned/refunded
    gmv = db_one(
        "SELECT COALESCE(SUM(grand_total),0) s FROM orders "
        "WHERE status NOT IN ('cancelled','returned','refunded') "
        "AND created_at >= (NOW() - INTERVAL 30 DAY)"
    )
    orders_30d = db_one(
        "SELECT COUNT(*) c FROM orders WHERE created_at >= (NOW() - INTERVAL 30 DAY)"
    )
    active_buyers = db_one(
        "SELECT COUNT(DISTINCT buyer_id) c FROM orders WHERE created_at >= (NOW() - INTERVAL 30 DAY)"
    )
    pending_verifications = db_one(
        "SELECT COUNT(*) c FROM orders WHERE payment_status='submitted'"
    )

    pending_payouts = db_one(
        "SELECT COALESCE(SUM(net_payable),0) s FROM payouts WHERE status='pending'"
    )
    paid_payouts_30d = db_one(
        "SELECT COALESCE(SUM(net_payable),0) s FROM payouts WHERE status='paid' AND paid_at >= (NOW() - INTERVAL 30 DAY)"
    )

    def _num(row, key='c'):
        try:
            return float(_row_get(row, key, 0, 0) or 0)
        except Exception:
            return 0.0

    kpis = {
        "gmv_30d": _num(gmv, 's'),
        "orders_30d": int(_row_get(orders_30d, 'c', 0, 0) or 0),
        "active_buyers_30d": int(_row_get(active_buyers, 'c', 0, 0) or 0),
        "pending_payment_verifications": int(_row_get(pending_verifications, 'c', 0, 0) or 0),
        "pending_payouts": _num(pending_payouts, 's'),
        "paid_payouts_30d": _num(paid_payouts_30d, 's'),
    }

    # --- Settings snapshot ---
    s = db_one("SELECT v FROM site_settings WHERE k='commission_pct'")
    try:
        commission_pct = float(_row_get(s, 'v', 0, 10) or 10)
    except Exception:
        commission_pct = 10
    settings = {"commission_pct": commission_pct}

    # --- Recent snapshots ---
    recent_payments = db_all(
        """
        SELECT o.id AS order_id, o.order_code, o.grand_total AS amount, o.payment_method, o.trnx_id,
               o.verified_at,
               u.name AS buyer_name
        FROM orders o
        LEFT JOIN users u ON u.id=o.buyer_id
        WHERE o.payment_status='verified'
        ORDER BY o.verified_at DESC
        LIMIT 8
        """
    )

    recent_payouts = db_all(
        """
        SELECT p.order_id, p.gross_amount, p.commission_amount, p.net_payable AS net_amount, p.payout_ref,
               u.name AS seller_name
        FROM payouts p
        LEFT JOIN users u ON u.id=p.seller_id
        WHERE p.status='paid'
        ORDER BY p.paid_at DESC
        LIMIT 8
        """
    )

    # Back-compat: some templates might reference kpi
    return render_template(
        "superadmin/overview.html",
        admin=a,
        kpi=kpis,
        kpis=kpis,
        settings=settings,
        recent_payments=recent_payments,
        recent_payouts=recent_payouts,
    )

# ------------------------------------------------------------
# SUPERADMIN: Settings / Admin management / Audit
# ------------------------------------------------------------
@app.get("/superadmin/settings")
@superadmin_required
def superadmin_settings_page():
    s = db_one("SELECT v FROM site_settings WHERE k='commission_pct'")
    try:
        commission_pct = float(_row_get(s, 'v', 0, 10) or 10)
    except Exception:
        commission_pct = 10
    return render_template("superadmin/settings.html", commission_pct=commission_pct, admin=current_admin())


@app.post("/superadmin/settings")
@superadmin_required
def superadmin_settings_post():
    a = current_admin() or {"role": "superadmin", "id": 0}
    raw = (request.form.get("commission_pct") or "").strip()
    try:
        v = float(raw)
    except Exception:
        v = 10
    v = max(0.0, min(100.0, v))

    db_exec(
        "INSERT INTO site_settings (k,v) VALUES ('commission_pct',%s) ON DUPLICATE KEY UPDATE v=VALUES(v)",
        (str(v),),
    )
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id") or 0), a.get("role") or "superadmin", "settings_update", "site_settings", 0, f"commission_pct={v}"),
    )
    return redirect("/superadmin/settings")


@app.get("/superadmin/admins")
@superadmin_required
def superadmin_admins_page():
    rows = db_all("SELECT id, name, email, role, status FROM admins ORDER BY FIELD(role,'superadmin','admin'), id ASC")
    admins = []
    for r in rows:
        admins.append({
            "id": _row_get(r, 'id', 0),
            "name": _row_get(r, 'name', 1),
            "email": _row_get(r, 'email', 2),
            "role": (_row_get(r, 'role', 3, 'admin') or 'admin'),
            "is_active": ((_row_get(r, 'status', 4, 'active') or 'active').lower() == 'active'),
        })
    return render_template("superadmin/admins.html", admins=admins, admin=current_admin())


@app.post("/superadmin/admins/create")
@superadmin_required
def superadmin_admins_create():
    a = current_admin() or {"role": "superadmin", "id": 0}
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    name = (request.form.get("name") or "Admin").strip()
    role = (request.form.get("role") or "admin").strip().lower()
    if role not in ["admin", "superadmin"]:
        role = "admin"
    if not email or not password:
        return redirect("/superadmin/admins")

    exists = db_one("SELECT id FROM admins WHERE email=%s", (email,))
    if exists:
        return redirect("/superadmin/admins")

    hashed = generate_password_hash(password)
    db_exec(
        "INSERT INTO admins (name,email,password,role,status) VALUES (%s,%s,%s,%s,'active')",
        (name, email, hashed, role),
    )
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id") or 0), a.get("role") or "superadmin", "admin_created", "admin", 0, email),
    )
    return redirect("/superadmin/admins")


@app.post("/superadmin/admins/<int:admin_id>/toggle")
@superadmin_required
def superadmin_admins_toggle(admin_id):
    a = current_admin() or {"role": "superadmin", "id": 0}
    row = db_one("SELECT status FROM admins WHERE id=%s", (int(admin_id),))
    if not row:
        return redirect("/superadmin/admins")
    cur = (_row_get(row, 'status', 0, 'active') or 'active').lower()
    nxt = 'disabled' if cur == 'active' else 'active'
    db_exec("UPDATE admins SET status=%s WHERE id=%s", (nxt, int(admin_id)))
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id") or 0), a.get("role") or "superadmin", "admin_toggle", "admin", int(admin_id), nxt),
    )
    return redirect("/superadmin/admins")


@app.post("/superadmin/admins/<int:admin_id>/role")
@superadmin_required
def superadmin_admins_role(admin_id):
    a = current_admin() or {"role": "superadmin", "id": 0}
    role = (request.form.get("role") or "admin").strip().lower()
    if role not in ["admin", "superadmin"]:
        role = "admin"
    db_exec("UPDATE admins SET role=%s WHERE id=%s", (role, int(admin_id)))
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id") or 0), a.get("role") or "superadmin", "admin_role", "admin", int(admin_id), role),
    )
    return redirect("/superadmin/admins")


@app.get("/superadmin/audit")
@superadmin_required
def superadmin_audit_page():
    flt = (request.args.get('filter') or '').strip().lower()
    q = (request.args.get('q') or '').strip()

    where = "WHERE 1=1 "
    params = []
    if flt == 'payments':
        where += "AND action LIKE 'payment_%' "
    elif flt == 'payouts':
        where += "AND action LIKE 'payout_%' "

    if q:
        where += "AND (action LIKE %s OR entity_type LIKE %s OR details LIKE %s OR CAST(entity_id AS CHAR) LIKE %s) "
        like = f"%{q}%"
        params.extend([like, like, like, like])

    rows = db_all(
        f"""
        SELECT l.id, l.actor_id, l.actor_role, l.action, l.entity_type, l.entity_id, l.details, l.created_at,
               COALESCE(ad.email, u.email) AS actor_email
        FROM audit_logs l
        LEFT JOIN admins ad ON (l.actor_role IN ('admin','superadmin') AND ad.id=l.actor_id)
        LEFT JOIN users  u  ON (u.id=l.actor_id)
        {where}
        ORDER BY l.created_at DESC
        LIMIT 300
        """,
        tuple(params),
    )

    logs = []
    for r in rows:
        logs.append({
            "created_at": _row_get(r, 'created_at', 7),
            "actor_id": _row_get(r, 'actor_id', 1),
            "actor_email": _row_get(r, 'actor_email', 8),
            "action": _row_get(r, 'action', 3),
            "entity_type": _row_get(r, 'entity_type', 4),
            "entity_id": _row_get(r, 'entity_id', 5),
            "meta_json": _row_get(r, 'details', 6),
        })

    return render_template('superadmin/audit.html', logs=logs, flt=flt, q=q, admin=current_admin())

@app.get("/admin/products")
@admin_required
def admin_products_page():
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    params = []
    where = "WHERE 1=1 "
    if status in ["pending", "active", "blocked"]:
        where += "AND p.status=%s "
        params.append(status)
    if q:
        where += "AND (p.title LIKE %s OR p.title_bn LIKE %s OR p.id LIKE %s) "
        like = f"%{q}%"
        params.extend([like, like, like])

    rows = db_all(
        "SELECT p.id, p.title, p.title_bn, p.category_slug, p.price_usd, p.compare_at_usd, p.image_url, p.maker, p.rating, p.badge, "
        "p.sold_count, p.status, p.is_featured, p.is_trending, p.created_at, u.name AS seller_name, u.email AS seller_email "
        "FROM products p LEFT JOIN users u ON u.id=p.seller_id "
        f"{where} "
        "ORDER BY FIELD(p.status,'pending','active','blocked'), p.created_at DESC",
        tuple(params),
    )
    return render_template("admin/products.html", rows=rows, status=status, q=q)


# ------------------------------------------------------------
# Admin: Payments (manual verification; buyer pays to platform)
# ------------------------------------------------------------
@app.get("/admin/payments")
@admin_required
def admin_payments_queue():
    # Payment submitted by buyer, waiting for admin verification
    rows = db_all(
        """
        SELECT o.id, o.order_code, o.buyer_id, o.grand_total, o.payment_method, o.trnx_id, o.payment_status, o.created_at,
               o.shipping_name, o.shipping_phone, o.shipping_address,
               u.name AS buyer_name, u.email AS buyer_email,
               COALESCE(up.phone, o.shipping_phone) AS buyer_phone
        FROM orders o
        JOIN users u ON u.id=o.buyer_id
        LEFT JOIN user_profiles up ON up.user_id=u.id
        WHERE o.payment_status IN ('submitted')
        ORDER BY o.created_at DESC
        """
    )
    return render_template("admin/payments_queue.html", rows=rows, admin=current_admin())


@app.post("/admin/payments/<int:order_id>/verify")
@admin_required
def admin_payment_verify(order_id):
    a = current_admin()
    # Mark as verified (escrow: platform received money)
    db_exec(
        "UPDATE orders SET payment_status='verified', verified_by=%s, verified_at=NOW() WHERE id=%s",
        (int(a.get("id")), int(order_id)),
    )
    # Audit
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id")), a.get("role"), "payment_verified", "order", int(order_id), ""),
    )

    # Auto: generate shipment + tracking and email buyer immediately on verification
    order = db_one("SELECT id, order_code, buyer_id, shipping_name, shipping_phone, shipping_address FROM orders WHERE id=%s", (int(order_id),))
    if order:
        buyer = db_one(
            "SELECT u.id, u.name, u.email, COALESCE(up.phone, %s) AS phone "
            "FROM users u LEFT JOIN user_profiles up ON up.user_id=u.id WHERE u.id=%s",
            (str(_row_get(order,'shipping_phone','') or ''), int(_row_get(order,'buyer_id',0))),
        )
        # Create shipment with an auto tracking code (no manual input required)
        carrier = "HandmadeHeritage"
        # If shipment already exists with tracking_code, keep it (avoid duplicates)
        ship = db_one("SELECT id, tracking_code FROM shipments WHERE order_id=%s", (int(order_id),))
        tracking_code = _row_get(ship,'tracking_code','') if ship else ''
        if not tracking_code:
            # Ensure uniqueness (shipments.tracking_code is UNIQUE)
            for _ in range(12):
                rand4 = ''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(4))
                candidate = f"HH-TRK-{int(order_id)}-{rand4}"
                exists = db_one("SELECT id FROM shipments WHERE tracking_code=%s", (candidate,))
                if not exists:
                    tracking_code = candidate
                    break
        if tracking_code:
            try:
                if ship:
                    db_exec(
                        "UPDATE shipments SET carrier=%s, tracking_code=%s, status='shipped', shipped_at=NOW(), updated_at=NOW() WHERE order_id=%s",
                        (carrier, tracking_code, int(order_id)),
                    )
                else:
                    db_exec(
                        "INSERT INTO shipments (order_id, carrier, tracking_code, status, shipped_at, created_at, updated_at) VALUES (%s,%s,%s,'shipped',NOW(),NOW(),NOW())",
                        (int(order_id), carrier, tracking_code),
                    )
                # Timeline
                db_exec(
                    "INSERT INTO order_tracking (order_id, status, note, created_at) VALUES (%s,'tracking_added',%s,NOW())",
                    (int(order_id), f"{carrier}: {tracking_code}"),
                )
            except Exception:
                pass

            # Send buyer email (HTML + fallback)
            try:
                if buyer and _row_get(buyer,'email',''):
                    _send_tracking_email(
                        to_email=_row_get(buyer,'email',''),
                        buyer_name=_row_get(buyer,'name','') or 'Customer',
                        order_code=_row_get(order,'order_code',''),
                        carrier=carrier,
                        tracking_code=tracking_code,
                    )
            except Exception:
                pass

    return redirect("/admin/payments")


@app.post("/admin/payments/<int:order_id>/reject")
@admin_required
def admin_payment_reject(order_id):
    a = current_admin()
    reason = (request.form.get("reason") or "").strip()
    db_exec(
        "UPDATE orders SET payment_status='failed', payment_note=%s WHERE id=%s",
        (reason, int(order_id)),
    )
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id")), a.get("role"), "payment_rejected", "order", int(order_id), reason),
    )
    return redirect("/admin/payments")


# -----------------------------
# Admin: Orders + tracking
# -----------------------------
@app.get("/admin/orders")
@app.get("/admin/ops/orders")
@admin_required
def admin_orders():
    status = (request.args.get("status") or "").strip().lower()
    where = "WHERE 1=1 "
    params = []
    if status:
        where += "AND status=%s "
        params.append(status)
    rows = db_all(
        f"""
        SELECT id, order_code, buyer_id, grand_total, payment_status, status, created_at
        FROM orders
        {where}
        ORDER BY created_at DESC
        LIMIT 200
        """,
        tuple(params),
    )
    return render_template("admin/orders_list.html", rows=rows, status=status, admin=current_admin())


@app.get("/admin/orders/<int:order_id>")
@app.get("/admin/ops/orders/<int:order_id>")
@admin_required
def admin_order_view(order_id):
    o = db_one("SELECT * FROM orders WHERE id=%s", (int(order_id),))
    if not o:
        return redirect("/admin/orders")
    items = db_all(
        "SELECT id, title, qty, unit_price, line_total, seller_id FROM order_items WHERE order_id=%s",
        (int(order_id),),
    )
    timeline = db_all(
        """
        SELECT status, note, updated_by_role, updated_by_id, created_at
        FROM order_tracking
        WHERE order_id=%s
        ORDER BY created_at ASC
        """,
        (int(order_id),),
    )

    audit = db_all(
        "SELECT action, details, created_at, actor_role, actor_id FROM audit_logs WHERE entity_type='order' AND entity_id=%s ORDER BY created_at DESC LIMIT 200",
        (int(order_id),),
    ) or []

    return render_template("admin/order_view.html", order=o, items=items, timeline=timeline, audit=audit, admin=current_admin())



def _ensure_payouts_for_order(order_id):
    """Create one payout per seller for the order (if not exists).

    Rule: Only generate payout when payment is verified AND order delivered.
    Snapshot payout method + masked account at creation time.
    """
    o = db_one("SELECT id, payment_status, status FROM orders WHERE id=%s", (int(order_id),))
    if not o:
        return
    if (_row_get(o, 'payment_status', 0, '') or '') != 'verified':
        return
    if (_row_get(o, 'status', 1, '') or '') != 'delivered':
        return

    # Commission percent from site_settings, default 10
    s = db_one("SELECT v FROM site_settings WHERE k='commission_pct'")
    try:
        commission_pct = float(_row_get(s, 'v', 0, 10) or 10)
    except Exception:
        commission_pct = 10.0

    has_payout_mask = db_has_column('payouts', 'payout_account_masked')

    # Aggregate per seller
    rows = db_all(
        """
        SELECT seller_id, COALESCE(SUM(line_total),0) gross
        FROM order_items
        WHERE order_id=%s AND seller_id IS NOT NULL
        GROUP BY seller_id
        """,
        (int(order_id),),
    )

    for r in (rows or []):
        seller_id = int(_row_get(r, 'seller_id', 0, 0) or 0)
        gross = float(_row_get(r, 'gross', 1, 0) or 0)
        if seller_id <= 0 or gross <= 0:
            continue

        exists = db_one(
            "SELECT id FROM payouts WHERE order_id=%s AND seller_id=%s",
            (int(order_id), seller_id),
        )
        if exists:
            continue

        # Pull seller payout info for snapshot
        sp = db_one(
            "SELECT verification_status, payout_method, payout_account_masked FROM seller_profiles WHERE user_id=%s",
            (seller_id,),
        )
        sp_status = (_row_get(sp, 'verification_status', 0, '') or '').lower() if sp else ''
        sp_method = (_row_get(sp, 'payout_method', 1, '') or '').strip().lower() if sp else ''
        sp_masked = (_row_get(sp, 'payout_account_masked', 2, '') or '').strip() if sp else ''

        payout_status = 'pending'
        if sp_status != 'approved' or (not sp_method) or (not sp_masked):
            payout_status = 'blocked'

        commission = round(gross * (commission_pct / 100.0), 2)
        net = round(gross - commission, 2)

        if has_payout_mask:
            db_exec(
                """
                INSERT INTO payouts (order_id, seller_id, gross_amount, commission_amount, net_payable, status, payout_method, payout_account_masked)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (int(order_id), seller_id, gross, commission, net, payout_status, sp_method or None, sp_masked or None),
            )
        else:
            db_exec(
                """
                INSERT INTO payouts (order_id, seller_id, gross_amount, commission_amount, net_payable, status, payout_method)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (int(order_id), seller_id, gross, commission, net, payout_status, sp_method or None),
            )


@app.post("/admin/orders/<int:order_id>/status")
@app.post("/admin/ops/orders/<int:order_id>/status")
@admin_required
def admin_order_update_status(order_id):
    a = current_admin()
    new_status = (request.form.get("status") or "").strip().lower()
    note = (request.form.get("note") or "").strip()

    allowed = [
        "paid",
        "pending",
        "confirmed",
        "packed",
        "shipped",
        "out_for_delivery",
        "delivered",
        "cancelled",
        "returned",
        "refunded",
    ]
    if new_status not in allowed:
        return redirect(f"/admin/orders/{int(order_id)}")

    # Fetch order + buyer for email
    o = db_one(
        "SELECT o.id, o.order_code, o.status, o.payment_status, u.email AS buyer_email, u.name AS buyer_name "
        "FROM orders o JOIN users u ON u.id=o.buyer_id WHERE o.id=%s",
        (int(order_id),),
    )
    if not o:
        return redirect("/admin/orders")

    order_code = _row_get(o, "order_code", 1, "")
    buyer_email = _row_get(o, "buyer_email", 4, "")
    buyer_name = _row_get(o, "buyer_name", 5, "")

    # "paid" updates payment_status only
    if new_status == "paid":
        db_exec("UPDATE orders SET payment_status='verified' WHERE id=%s", (int(order_id),))
        track_status = "paid"
    else:
        db_exec("UPDATE orders SET status=%s WHERE id=%s", (new_status, int(order_id)))
        track_status = new_status

    db_exec(
        """INSERT INTO order_tracking (order_id, status, note, updated_by_role, updated_by_id)
             VALUES (%s,%s,%s,%s,%s)""",
        (int(order_id), track_status, note, a.get("role"), int(a.get("id"))),
    )
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get("id")), a.get("role"), "order_status_update", "order", int(order_id), f"{track_status} | {note}"),
    )

    # If delivered, generate seller payouts (escrow release readiness)
    if track_status == "delivered":
        _ensure_payouts_for_order(order_id)

    # Notify buyer by email on every admin update (as requested)
    try:
        if buyer_email:
            _send_order_status_email(
                to_email=buyer_email,
                buyer_name=buyer_name,
                order_code=order_code,
                new_status=track_status,
                note=note,
            )
    except Exception:
        pass

    return redirect(f"/admin/orders/{int(order_id)}")



# -----------------------------
# Admin: Payouts (pay seller after delivery)
# -----------------------------
@app.get("/admin/payouts")
@admin_required
def admin_payouts():
    status = (request.args.get("status") or "pending").strip().lower()
    # show blocked also from admin? keep optional
    if status not in ["pending", "paid", "blocked"]:
        status = "pending"

    has_payout_mask = db_has_column('payouts','payout_account_masked')
    mask_select = "p.payout_account_masked" if has_payout_mask else "sp.payout_account_masked"
    join_sp = "" if has_payout_mask else "LEFT JOIN seller_profiles sp ON sp.user_id=p.seller_id"

    rows = db_all(
        f"""
        SELECT p.id, p.order_id, o.order_code, p.seller_id, u.name seller_name, u.email seller_email, up.phone seller_phone,
               p.gross_amount, p.commission_amount, p.net_payable,
               p.status, p.payout_ref, p.payout_method, p.payout_proof_url, p.paid_at,
               {mask_select} AS payout_account_masked
        FROM payouts p
        JOIN orders o ON o.id=p.order_id
        JOIN users u ON u.id=p.seller_id
        LEFT JOIN user_profiles up ON up.user_id=u.id
        {join_sp}
        WHERE p.status=%s
        ORDER BY p.id DESC
        """,
        (status,),
    )
    return render_template("admin/payouts_queue.html", rows=rows, status=status, admin=current_admin())


@app.post("/admin/payouts/<int:payout_id>/mark_paid")
@admin_required
def admin_payout_mark_paid(payout_id):
    a = current_admin()
    ref = (request.form.get("payout_ref") or "").strip()
    if not ref:
        return redirect('/admin/payouts')

    # Validate payout status
    pr = db_one("SELECT status, payout_method FROM payouts WHERE id=%s", (int(payout_id),))
    if not pr:
        return redirect('/admin/payouts')
    st = (_row_get(pr, 'status', 0, '') or '').lower()
    existing_method = (_row_get(pr, 'payout_method', 1, '') or '').strip()
    if st != 'pending':
        return redirect('/admin/payouts')

    # Optional proof upload (screenshot/PDF/JPG)
    f = request.files.get('proof') or request.files.get('proof_file')
    proof_url = None
    if f and getattr(f, 'filename', ''):
        import os
        from werkzeug.utils import secure_filename
        name = secure_filename(f.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']:
            ext = '.png'
        folder = os.path.join(app.root_path, 'static', 'uploads', 'payouts')
        os.makedirs(folder, exist_ok=True)
        fname = f"payout_{int(payout_id)}_{int(a.get('id') or 0)}{ext}"
        path = os.path.join(folder, fname)
        f.save(path)
        proof_url = '/static/uploads/payouts/' + fname

    # Keep original payout_method snapshot (no dropdown needed).
    db_exec(
        "UPDATE payouts SET status='paid', payout_ref=%s, payout_proof_url=COALESCE(%s,payout_proof_url), paid_by=%s, paid_at=NOW() WHERE id=%s",
        (ref, proof_url, int(a.get('id') or 0), int(payout_id)),
    )
    db_exec(
        "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
        (int(a.get('id') or 0), a.get('role'), 'payout_mark_paid', 'payout', int(payout_id), f"{existing_method} | {ref} | {proof_url or ''}"),
    )
    return redirect('/admin/payouts')


# -----------------------------
# Order-based Chat (Buyer <-> Seller)
# -----------------------------
@app.get("/order/<order_code>/chat/<int:seller_id>")
@login_required()
def order_chat(order_code, seller_id):
    u = _current_user()
    o = db_one("SELECT id, buyer_id FROM orders WHERE order_code=%s", (order_code,))
    if not o:
        return redirect("/")

    order_id = int(_row_get(o, 'id', 0, 0) or 0)
    buyer_id = int(_row_get(o, 'buyer_id', 1, 0) or 0)
    role = (u.get('role') or '').lower()

    # Validate access: buyer (owner) or seller (matches items)
    if role == 'buyer' and int(u.get('id')) != buyer_id:
        return redirect("/")
    if role == 'seller':
        # seller must be in items
        has = db_one(
            "SELECT 1 x FROM order_items WHERE order_id=%s AND seller_id=%s LIMIT 1",
            (order_id, int(u.get('id'))),
        )
        if not has:
            return redirect("/")

    # Ensure this seller_id is part of the order
    chk = db_one(
        "SELECT 1 x FROM order_items WHERE order_id=%s AND seller_id=%s LIMIT 1",
        (order_id, int(seller_id)),
    )
    if not chk:
        return redirect("/")

    conv = db_one(
        "SELECT id FROM conversations WHERE order_id=%s AND buyer_id=%s AND seller_id=%s",
        (order_id, buyer_id, int(seller_id)),
    )
    if not conv:
        db_exec(
            "INSERT INTO conversations (type, order_id, buyer_id, seller_id, last_message_at) VALUES ('order',%s,%s,%s,NOW())",
            (order_id, buyer_id, int(seller_id)),
        )
        conv = db_one(
            "SELECT id FROM conversations WHERE order_id=%s AND buyer_id=%s AND seller_id=%s",
            (order_id, buyer_id, int(seller_id)),
        )

    conv_id = int(_row_get(conv, 'id', 0, 0) or 0)

    # Seller must use Messages hub (no order-page chat UI)
    if role == 'seller':
        return redirect(f"/messages?conv={conv_id}")

    msgs = db_all(
        """
        SELECT id, sender_role, sender_id, message_text, status, created_at
        FROM messages
        WHERE conversation_id=%s
        ORDER BY id ASC
        LIMIT 500
        """,
        (conv_id,),
    )

    # Mark as seen for the current viewer
    try:
        db_exec(
            "UPDATE messages SET status='seen' WHERE conversation_id=%s AND sender_role<>%s",
            (conv_id, role),
        )
    except Exception:
        pass

    return render_template(
        "chat/order_chat.html",
        conv_id=conv_id,
        order_code=order_code,
        seller_id=int(seller_id),
        role=role,
        user_id=int(u.get('id')),
        messages=msgs,
    )


@app.get("/api/chat/<int:conv_id>/messages")
@login_required()
def api_chat_messages(conv_id):
    msgs = db_all(
        """
        SELECT id, sender_role, sender_id, message_text, status, created_at
        FROM messages
        WHERE conversation_id=%s
        ORDER BY id ASC
        LIMIT 500
        """,
        (int(conv_id),),
    )
    return jsonify({"messages": msgs})


@app.post("/api/chat/<int:conv_id>/send")
@login_required()
def api_chat_send(conv_id):
    u = _current_user()
    role = (u.get('role') or '').lower()
    text = (request.form.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400

    # Authorize participant
    c = db_one("SELECT order_id, buyer_id, seller_id FROM conversations WHERE id=%s", (int(conv_id),))
    if not c:
        return jsonify({"ok": False, "error": "not_found"}), 404
    buyer_id = int(_row_get(c, 'buyer_id', 1, 0) or 0)
    seller_id = int(_row_get(c, 'seller_id', 2, 0) or 0)
    if role == 'buyer' and int(u.get('id')) != buyer_id:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if role == 'seller' and int(u.get('id')) != seller_id:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    db_exec(
        """
        INSERT INTO messages (conversation_id, sender_role, sender_id, message_text, status)
        VALUES (%s,%s,%s,%s,'sent')
        """,
        (int(conv_id), role, int(u.get('id')), text),
    )
    db_exec("UPDATE conversations SET last_message_at=NOW() WHERE id=%s", (int(conv_id),))
    return jsonify({"ok": True})

@app.post("/admin/products/<pid>/status")
@admin_required
def admin_product_set_status(pid):
    new_status = (request.form.get("status") or "").strip()
    # Some DBs have ENUM without 'pending'. Sanitize to avoid 1265 truncation.
    safe_status = _product_status_sanitize(new_status)
    db_exec("UPDATE products SET status=%s WHERE id=%s", (safe_status, pid))
    return redirect(request.referrer or "/admin/products")

@app.post("/admin/products/<pid>/toggle")
@admin_required
def admin_product_toggle(pid):
    field = (request.form.get("field") or "").strip()
    if field not in ["is_featured", "is_trending"]:
        return redirect(request.referrer or "/admin/products")
    db_exec(f"UPDATE products SET {field} = IF({field}=1,0,1) WHERE id=%s", (pid,))
    return redirect(request.referrer or "/admin/products")
# --------------------
# Admin -> Flash Dispatch approvals
# --------------------
@app.get("/admin/flash-requests")
@admin_required
def admin_flash_requests():
    status = (request.args.get("status") or "pending").strip().lower()
    if status not in ["pending", "approved", "rejected", "cancelled", "all"]:
        status = "pending"
    params = []
    where = "WHERE 1=1 "
    if status != "all":
        where += "AND fr.status=%s "
        params.append(status)

    rows = db_all(
        "SELECT fr.id, fr.product_id, fr.seller_id, fr.requested_price_usd, fr.requested_compare_at_usd, fr.requested_end_at, fr.status, "
        "fr.seller_note, fr.admin_note, fr.created_at, "
        "u.name AS seller_name, u.email AS seller_email, "
        "p.title AS product_title, p.image_url AS product_image, p.stock AS product_stock "
        "FROM flash_requests fr "
        "LEFT JOIN users u ON u.id=fr.seller_id "
        "LEFT JOIN products p ON p.id=fr.product_id "
        f"{where} "
        "ORDER BY fr.created_at DESC"
    , tuple(params))

    # pending count for sidebar badge (optional)
    pending_count = db_one("SELECT COUNT(*) AS c FROM flash_requests WHERE status='pending'")
    return render_template("admin/flash_requests.html", items=rows, status=status, pending_count=_row_get(pending_count, 'c', 0, 0))

@app.post("/admin/flash-requests/<int:rid>/approve")
@admin_required
def admin_flash_requests_approve(rid: int):
    a = current_admin() or {}
    admin_id = int(a.get("id") or 0)

    fr = db_one("SELECT * FROM flash_requests WHERE id=%s", (rid,))
    if not fr or (_row_get(fr, "status", 6, "pending") != "pending"):
        return redirect(request.referrer or "/admin/flash-requests")

    pid = _row_get(fr, "product_id", 1)
    seller_id = int(_row_get(fr, "seller_id", 2, 0) or 0)
    req_price = float(_row_get(fr, "requested_price_usd", 3, 0) or 0)
    req_compare = float(_row_get(fr, "requested_compare_at_usd", 4, 0) or 0)
    req_end = _row_get(fr, "requested_end_at", 5)

    # Validate business rules
    if req_price <= 0 or req_compare <= 0 or req_compare <= req_price:
        db_exec(
            "UPDATE flash_requests SET status='rejected', admin_note=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
            ("Invalid pricing in request.", admin_id or None, rid),
        )
        return redirect("/admin/flash-requests?status=pending")

    # apply to product
    db_exec(
        "UPDATE products SET price_usd=%s, compare_at_usd=%s, is_flash=1, flash_end_at=%s, dispatch_type='flash' "
        "WHERE id=%s AND seller_id=%s",
        (req_price, req_compare, req_end, pid, seller_id),
    )

    db_exec(
        "UPDATE flash_requests SET status='approved', admin_note=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
        ((request.form.get("admin_note") or "").strip() or None, admin_id or None, rid),
    )
    return redirect("/admin/flash-requests?status=pending")

@app.post("/admin/flash-requests/<int:rid>/reject")
@admin_required
def admin_flash_requests_reject(rid: int):
    a = current_admin() or {}
    admin_id = int(a.get("id") or 0)

    note = (request.form.get("admin_note") or "").strip()
    db_exec(
        "UPDATE flash_requests SET status='rejected', admin_note=%s, reviewed_by=%s, reviewed_at=NOW() "
        "WHERE id=%s AND status='pending'",
        (note or "Rejected", admin_id or None, rid),
    )
    return redirect("/admin/flash-requests?status=pending")
@app.get("/admin/kyc")
@admin_required
def admin_kyc_page():
    rows = db_all(
        "SELECT sp.*, u.name, u.email FROM seller_profiles sp "
        "JOIN users u ON u.id=sp.user_id "
        "ORDER BY sp.updated_at DESC, sp.created_at DESC"
    )
    return render_template("admin/kyc.html", rows=rows)

@app.post("/admin/kyc/<int:uid>/approve")
@admin_required
def admin_kyc_approve(uid):
    a = current_admin() or {"role": "admin", "id": 0}
    db_exec("UPDATE seller_profiles SET verification_status='approved', notes=NULL WHERE user_id=%s", (uid,))
    # Audit
    try:
        db_exec(
            "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (int(a.get("id") or 0), a.get("role") or "admin", "kyc_approved", "seller", int(uid), "approved"),
        )
    except Exception:
        pass
    return redirect(request.referrer or "/admin/kyc")

@app.post("/admin/kyc/<int:uid>/reject")
@admin_required
def admin_kyc_reject(uid):
    a = current_admin() or {"role": "admin", "id": 0}
    reason = (request.form.get("reason") or "").strip()
    note = (request.form.get("note") or "").strip()
    packed = ""
    if reason:
        packed = reason
    if note:
        packed = (packed + ": " if packed else "") + note
    db_exec(
        "UPDATE seller_profiles SET verification_status='rejected', notes=%s WHERE user_id=%s",
        (packed or None, uid),
    )
    # Audit
    try:
        db_exec(
            "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (int(a.get("id") or 0), a.get("role") or "admin", "kyc_rejected", "seller", int(uid), packed or "rejected"),
        )
    except Exception:
        pass
    return redirect(request.referrer or "/admin/kyc")



@app.get("/admin/orders")
@admin_required
def admin_orders_page():
    rows = db_all(
        "SELECT o.id, o.order_code, o.currency, o.grand_total, o.payment_method, o.trnx_id, "
        "o.payment_status, o.status, o.shipping_name, o.shipping_phone, o.shipping_address, o.created_at, "
        "u.name AS buyer_name, u.email AS buyer_email, COALESCE(up.phone, o.shipping_phone) AS buyer_phone "
        "FROM orders o JOIN users u ON u.id=o.buyer_id "
        "LEFT JOIN user_profiles up ON up.user_id=u.id "
        "ORDER BY o.created_at DESC, o.id DESC"
    )

    orders = []
    for r in (rows or []):
        orders.append({
            "id": _row_get(r, "id", 0),
            "order_code": _row_get(r, "order_code", 1),
            "currency": _row_get(r, "currency", 2),
            "grand_total": _row_get(r, "grand_total", 3),
            "payment_method": _row_get(r, "payment_method", 4),
            "trnx_id": _row_get(r, "trnx_id", 5),
            "payment_status": _row_get(r, "payment_status", 6),
            "status": _row_get(r, "status", 7),
            "shipping_name": _row_get(r, "shipping_name", 8),
            "shipping_phone": _row_get(r, "shipping_phone", 9),
            "created_at": _row_get(r, "created_at", 10),
            "buyer_name": _row_get(r, "buyer_name", 11),
            "buyer_email": _row_get(r, "buyer_email", 12),
        })

    return render_template("admin/orders.html", orders=orders)

@app.get("/admin/admins")
@admin_required
def admin_admins_page():
    admins = db_all("SELECT id, name, email, role, status, created_at FROM admins ORDER BY id DESC")
    return render_template("admin/admins.html", admins=admins)


# ============================================================
# NEW: Admin Approve Order API (Confirm + Email) ✅ (Added Here)
# ============================================================
@app.post("/api/admin/approve-order")
@admin_required
def api_approve_order():
    data = request.get_json(force=True) or {}
    oid = data.get("order_id")

    if not oid:
        return jsonify({"error": "order_id required"}), 400

    # Mark payment as verified (realistic manual verification flow)
    db_exec("UPDATE orders SET payment_status='paid', status='paid' WHERE id=%s", (oid,))

    # Get Customer Info for Email
    row = db_one(
        "SELECT u.email, u.name, o.order_code, o.trnx_id "
        "FROM orders o JOIN users u ON o.buyer_id = u.id "
        "WHERE o.id=%s",
        (oid,),
    )

    if row:
        email = _row_get(row, "email", 0)
        name = _row_get(row, "name", 1)
        code = _row_get(row, "order_code", 2)

        # World-Class Email
        try:
            msg = Message(subject=f"Payment Verified: Order {code}", recipients=[email])
            msg.html = (
                f"<h3>Hello {name},</h3>"
                f"<p>Your payment has been verified! Order <b>{code}</b> is now confirmed.</p>"
            )
            mail.send(msg)
        except Exception:
            pass

    return jsonify({"success": True})

# ============================================================
# Products API (optional)
# ============================================================
@app.get("/api/products")
def api_products():
    """Unified products API used by Home + Shop.
    Supports filters: category, q, limit, flash=1, dispatch=full, archive=1, sort=trending|new|best, discover=1
    """
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    flash = (request.args.get("flash") or "").strip()
    dispatch = (request.args.get("dispatch") or "").strip()
    archive = (request.args.get("archive") or "").strip()
    sort = (request.args.get("sort") or "").strip()
    discover = (request.args.get("discover") or "").strip()
    min_price = (request.args.get("min") or "").strip()
    max_price = (request.args.get("max") or "").strip()


    try:
        limit = int((request.args.get("limit") or "30").strip() or 30)
    except Exception:
        limit = 30
    limit = max(1, min(60, limit))

    where = ["p.status='active'"]
    params = []

    if category:
        where.append("p.category_slug=%s")
        params.append(category)

    if q:
        where.append("(p.title LIKE %s OR p.title_bn LIKE %s OR p.description LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])

    if archive in ("1", "true", "yes"):
        # curated archive OR truly archived products
        where.append("(p.is_archive=1 OR p.status='archived')")

    if flash in ("1", "true", "yes"):
        where.append("p.is_flash=1")
        where.append("p.flash_end_at IS NOT NULL AND p.flash_end_at > NOW()")
        where.append("p.stock > 0")
        where.append("p.compare_at_usd IS NOT NULL AND p.compare_at_usd > p.price_usd")

    if dispatch.lower() == "full":
        # manual full dispatch OR expired flash promoted to full feed
        where.append("(p.dispatch_type='full' OR (p.is_flash=1 AND p.flash_end_at IS NOT NULL AND p.flash_end_at <= NOW()))")

    # ordering
    order_by = "p.created_at DESC"
    if sort == "new":
        order_by = "p.created_at DESC"
    elif sort == "best":
        order_by = "p.sold_count DESC, p.created_at DESC"
    elif sort == "trending":
        order_by = "(p.view_count + (p.sold_count*2)) DESC, p.created_at DESC"
    elif discover in ("1", "true", "yes"):
        # under-exposed discovery
        order_by = "p.view_count ASC, p.rating DESC, p.created_at DESC"

    sql = (
        "SELECT p.id, p.title, p.title_bn, p.category_slug, p.price_usd, p.compare_at_usd, "
        "p.image_url, p.maker, p.rating, p.badge, p.description, p.created_at, "
        "p.is_flash, p.flash_end_at, p.dispatch_type, p.is_archive, p.stock "
        "FROM products p "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY {order_by} "
        "LIMIT %s"
    )
    params.append(limit)

    rows = db_all(sql, tuple(params))
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "compare": float(_row_get(r, "compare_at_usd", 5, 0) or 0) if _row_get(r, "compare_at_usd", 5) is not None else None,
            "img": _row_get(r, "image_url", 6),
            "maker": _row_get(r, "maker", 7),
            "rating": float(_row_get(r, "rating", 8, 0) or 0),
            "badge": _row_get(r, "badge", 9),
            "desc": _row_get(r, "description", 10),
            "created_at": str(_row_get(r, "created_at", 11) or ""),
            "is_flash": int(_row_get(r, "is_flash", 12, 0) or 0),
            "flash_end_at": str(_row_get(r, "flash_end_at", 13) or "") if _row_get(r, "flash_end_at", 13) else "",
            "dispatch_type": _row_get(r, "dispatch_type", 14, "normal"),
            "is_archive": int(_row_get(r, "is_archive", 15, 0) or 0),
            "stock": int(_row_get(r, "stock", 16, 0) or 0),
        })
    return jsonify(out)


@app.get("/api/products/featured")
def api_featured_products():
    limit = int(request.args.get("limit", 8))
    limit = max(1, min(limit, 24))
    rows = db_all(
        "SELECT id, title, title_bn, category_slug, price_usd, image_url, maker, rating, badge "
        "FROM products WHERE is_featured=1 AND status='active' ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "img": _row_get(r, "image_url", 5),
            "maker": _row_get(r, "maker", 6),
            "rating": float(_row_get(r, "rating", 7, 0) or 0),
            "badge": _row_get(r, "badge", 8),
        })
    return jsonify(out)

@app.get("/api/products/trending")
def api_trending_products():
    limit = int(request.args.get("limit", 8))
    limit = max(1, min(limit, 24))
    rows = db_all(
        "SELECT id, title, title_bn, category_slug, price_usd, image_url, maker, rating, badge, sold_count "
        "FROM products WHERE status='active' ORDER BY is_trending DESC, sold_count DESC, rating DESC, created_at DESC LIMIT %s",
        (limit,),
    )
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "img": _row_get(r, "image_url", 5),
            "maker": _row_get(r, "maker", 6),
            "rating": float(_row_get(r, "rating", 7, 0) or 0),
            "badge": _row_get(r, "badge", 8),
            "sold": int(_row_get(r, "sold_count", 9, 0) or 0),
        })
    return jsonify(out)


@app.get("/api/products/best-selling")
def api_best_selling_products():
    limit = int(request.args.get("limit", 8))
    limit = max(1, min(limit, 24))
    rows = db_all(
        "SELECT id, title, title_bn, category_slug, price_usd, image_url, maker, rating, badge, sold_count "
        "FROM products WHERE status='active' ORDER BY sold_count DESC, rating DESC, created_at DESC LIMIT %s",
        (limit,),
    )
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "img": _row_get(r, "image_url", 5),
            "maker": _row_get(r, "maker", 6),
            "rating": float(_row_get(r, "rating", 7, 0) or 0),
            "badge": _row_get(r, "badge", 8),
            "sold": int(_row_get(r, "sold_count", 9, 0) or 0),
        })
    return jsonify(out)


@app.get("/api/categories")
def api_categories():
    # derive categories from products.category_slug (no extra table needed)
    rows = db_all(
        "SELECT DISTINCT category_slug FROM products "
        "WHERE category_slug IS NOT NULL AND category_slug <> '' "
        "ORDER BY category_slug ASC"
    )
    cats = []
    for r in rows:
        slug = _row_get(r, "category_slug", 0)
        if not slug:
            continue
        name = str(slug).replace("-", " ").replace("_", " ").title()
        cats.append({"slug": slug, "name": name})
    return jsonify(cats)

@app.get("/api/products/by-category/<slug>")
def api_products_by_category(slug):
    limit = int(request.args.get("limit", 12))
    limit = max(1, min(limit, 48))
    rows = db_all(
        "SELECT id, title, title_bn, category_slug, price_usd, image_url, maker, rating, badge "
        "FROM products WHERE category_slug=%s AND status='active' ORDER BY created_at DESC LIMIT %s",
        (slug, limit),
    )
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "img": _row_get(r, "image_url", 5),
            "maker": _row_get(r, "maker", 6),
            "rating": float(_row_get(r, "rating", 7, 0) or 0),
            "badge": _row_get(r, "badge", 8),
        })
    return jsonify(out)

# ============================================================
# PASSWORD RESET (Forgot Password)
# ============================================================

def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()

def _send_password_reset_email(to_email, reset_url, reset_code=None, name=None):
    msg = Message(
        subject="Handmade Heritage - Reset your password",
        recipients=[to_email],
    )
    msg.body = f"""We received a request to reset your password.

Reset link: {reset_url}

If you didn't request this, you can ignore this email.
"""
    try:
        msg.html = render_template("emails/reset_password.html", reset_url=reset_url, reset_code=reset_code, buyer_name=name or "Customer")
    except Exception:
        pass
    mail.send(msg)

def _send_tracking_email(to_email, buyer_name, order_code, carrier, tracking_code):
    """Send tracking info email (HTML with text fallback)."""
    try:
        track_url = url_for("track_page", _external=True) + f"?code={order_code}"
    except Exception:
        track_url = ""
    msg = Message(
        subject=f"Your order {order_code} has been shipped",
        recipients=[to_email],
    )
    msg.body = f"Tracking for order {order_code}: {carrier} {tracking_code}. {('Track: ' + track_url) if track_url else ''}"
    try:
        msg.html = render_template(
            "emails/tracking_added.html",
            buyer_name=buyer_name or "Customer",
            order_code=order_code,
            carrier=carrier,
            tracking_code=tracking_code,
            track_url=track_url,
        )
    except Exception:
        pass
    mail.send(msg)

def _send_order_status_email(to_email, buyer_name, order_code, new_status, note=""):
    """Notify buyer when admin updates payment/order status."""
    status_label = (new_status or "").replace("_", " ").title()
    subj = f"Order {order_code} update: {status_label}"
    msg = Message(subject=subj, recipients=[to_email])
    msg.body = f"""Your order {order_code} has been updated.

New status: {status_label}
{('Note: ' + note) if note else ''}

You can track your order here: {url_for('track_page', _external=True)}?code={order_code}
"""
    try:
        msg.html = render_template(
            "emails/order_status.html",
            buyer_name=buyer_name or "Customer",
            order_code=order_code,
            status_label=status_label,
            note=note,
            track_url=url_for("track_page", _external=True) + f"?code={order_code}",
        )
    except Exception:
        pass
    mail.send(msg)



@app.get("/forgot")
def forgot_password_page():
    return render_template('auth/forgot.html')

@app.post("/api/forgot")
def api_forgot_password():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()

    # Always respond success to avoid email enumeration
    generic_ok = {"success": True, "message": "If the email exists, a reset link has been sent."}

    if not email:
        return jsonify(generic_ok)

    user = db_one("SELECT id, status, is_verified FROM users WHERE email=%s", (email,))
    if not user:
        return jsonify(generic_ok)

    if (_row_get(user, "status", 1, "active") or "").lower() != "active":
        return jsonify(generic_ok)

    if int(_row_get(user, "is_verified", 2, 0) or 0) != 1:
        return jsonify(generic_ok)

    # Create a signed token (short-lived) and store its hash in DB for one-time use
    signed = serializer.dumps(
        {"u": int(_row_get(user, "id", 0)), "r": secrets.token_urlsafe(32)},
        salt="hh-reset",
    )

    token_hash = _hash_token(signed)

    # Also generate a 6-digit reset code (OTP) for premium UX
    reset_code = str(random.randint(100000, 999999))
    code_hash = _hash_code(reset_code)

    # Store with expiry (15 minutes)
    expires_at = datetime.utcnow() + timedelta(minutes=15)
    db_exec(
        "INSERT INTO password_resets (user_id, token_hash, expires_at, code_hash, code_expires_at) VALUES (%s,%s,%s,%s,%s)",
        (int(_row_get(user, "id", 0)), token_hash, expires_at, code_hash, expires_at),
    )

    reset_url = url_for("reset_password_page", token=signed, _external=True)
    _send_password_reset_email(email, reset_url, reset_code=reset_code)

    return jsonify(generic_ok)

@app.get("/reset/<token>")
def reset_password_page(token):
    return render_template('auth/reset_password.html', token=token)

@app.post("/api/reset")
def api_reset_password():
    data = request.get_json(force=True) or {}
    token = (data.get("token") or "").strip()
    password = (data.get("password") or "").strip()
    confirm = (data.get("confirm") or "").strip()
    code = (data.get("code") or "").strip()

    if not token or not password or not confirm or not code:
        return jsonify({"error": "All fields are required."}), 400

    if password != confirm:
        return jsonify({"error": "Passwords do not match."}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    try:
        payload = serializer.loads(token, salt="hh-reset", max_age=60 * 20)  # allow 20 minutes
    except SignatureExpired:
        return jsonify({"error": "Reset link expired."}), 400
    except BadSignature:
        return jsonify({"error": "Invalid reset link."}), 400

    uid = int(payload.get("u") or 0)
    if uid <= 0:
        return jsonify({"error": "Invalid reset link."}), 400

    # One-time use check against DB
    token_hash = _hash_token(token)
    row = db_one(
        "SELECT id, used_at, expires_at, code_hash, code_expires_at FROM password_resets WHERE user_id=%s AND token_hash=%s ORDER BY id DESC LIMIT 1",
        (uid, token_hash),
    )
    if not row:
        return jsonify({"error": "Reset link already used or invalid."}), 400

    used_at = _row_get(row, "used_at", 1)
    expires_at = _row_get(row, "expires_at", 2)

    try:
        if expires_at and datetime.utcnow() > expires_at:
            return jsonify({"error": "Reset link expired."}), 400
    except Exception:
        pass

    # Validate the 6-digit reset code (OTP)
    code_hash_db = _row_get(row, "code_hash", 3)
    code_exp = _row_get(row, "code_expires_at", 4)

    if not code_hash_db:
        return jsonify({"error": "Reset code not available. Please request again."}), 400

    if _hash_code(code) != code_hash_db:
        return jsonify({"error": "Invalid reset code."}), 400

    try:
        if code_exp and datetime.utcnow() > code_exp:
            return jsonify({"error": "Reset code expired."}), 400
    except Exception:
        pass

    if used_at:
        return jsonify({"error": "Reset link already used."}), 400

    hashed = generate_password_hash(password)
    db_exec("UPDATE users SET password=%s WHERE id=%s", (hashed, uid))
    db_exec("UPDATE password_resets SET used_at=%s WHERE id=%s", (datetime.utcnow(), int(_row_get(row, "id", 0))))

    return jsonify({"success": True, "message": "Password updated. Please login."})

# ============================================================
# PRODUCT DETAILS + WISHLIST
# ============================================================

@app.get("/product")
def product_details_page():
    pid = (request.args.get("id") or "").strip()
    if not pid:
        return redirect("/shop")
    p = db_one("SELECT * FROM products WHERE id=%s", (pid,))
    if not p:
        return redirect("/shop")

    # Approved reviews visible to everyone
    reviews = db_all(
        """SELECT r.id, r.rating, r.title, r.body, r.is_verified_purchase, r.created_at, u.name AS buyer_name
             FROM reviews r
             JOIN users u ON u.id=r.buyer_id
             WHERE r.product_id=%s AND r.status='approved'
             ORDER BY r.created_at DESC
             LIMIT 50""",
        (pid,),
    )

    # Can current buyer review? (only after delivery)
    can_review = False
    if session.get("user_id") and (session.get("role") or "").lower() == "buyer":
        buyer_id = int(session.get("user_id"))
        ok = db_one(
            """SELECT o.id
                 FROM orders o
                 JOIN order_items oi ON oi.order_id=o.id
                 WHERE o.buyer_id=%s AND oi.product_id=%s AND o.status='delivered'
                 LIMIT 1""",
            (buyer_id, pid),
        )
        can_review = True if ok else False

    specs = {}
    try:
        if p.get("specs_json"):
            specs = json.loads(p.get("specs_json") or "{}") or {}
    except Exception:
        specs = {}
    return render_template('public/product.html', product=p, reviews=reviews, can_review=can_review, specs=specs)


@app.post("/api/reviews/create")
def api_create_review():
    # Buyer-only, verified purchase (delivered)
    if not _require_role("buyer"):
        return jsonify({"error": "Buyer login required"}), 401

    data = request.get_json(force=True) or {}
    product_id = (data.get("product_id") or "").strip()
    rating = int(data.get("rating") or 0)
    title = (data.get("title") or "").strip()[:140]
    body = (data.get("body") or "").strip()

    if not product_id or rating < 1 or rating > 5:
        return jsonify({"error": "Invalid review"}), 400

    u = _current_user()
    buyer_id = int(u.get("id"))

    # Check delivered purchase
    ok = db_one(
        """SELECT o.id
             FROM orders o
             JOIN order_items oi ON oi.order_id=o.id
             WHERE o.buyer_id=%s AND oi.product_id=%s AND o.status='delivered'
             LIMIT 1""",
        (buyer_id, product_id),
    )
    if not ok:
        return jsonify({"error": "You can review only after delivery"}), 403

    # Upsert: one review per buyer per product
    existing = db_one("SELECT id FROM reviews WHERE buyer_id=%s AND product_id=%s LIMIT 1", (buyer_id, product_id))
    if existing:
        db_exec(
            "UPDATE reviews SET rating=%s, title=%s, body=%s, is_verified_purchase=1, status='approved' WHERE id=%s",
            (rating, title, body, int(_row_get(existing,'id',0))),
        )
        rid = int(_row_get(existing,'id',0))
    else:
        db_exec(
            "INSERT INTO reviews (product_id, buyer_id, rating, title, body, is_verified_purchase, status) VALUES (%s,%s,%s,%s,%s,1,'pending')",
            (product_id, buyer_id, rating, title, body),
        )
        rid = int(db_one("SELECT LAST_INSERT_ID() AS id")["id"])

    return jsonify({"success": True, "review_id": rid})


def _require_role(*roles):
    r = (session.get("role") or "").lower()
    return r in [x.lower() for x in roles]



# ============================================================
# SELLER (KYC + Dashboard + Products)
# ============================================================
def _seller_upload_dir():
    p = os.path.join(app.root_path, "static", "uploads", "seller_kyc")
    os.makedirs(p, exist_ok=True)
    return p

def _require_seller_login():
    if not _require_login():
        return False
    return _require_role("seller")

@app.get("/seller/kyc")
def seller_kyc_page():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    sp = db_one("SELECT * FROM seller_profiles WHERE user_id=%s", (uid,))
    return render_template("seller/kyc.html", profile=sp)

@app.post("/api/seller/kyc")
def api_seller_kyc():
    if not _require_seller_login():
        return jsonify({"error":"Unauthorized"}), 401

    uid = int(session.get("user_id"))
    nid_number = (request.form.get("nid_number") or "").strip()
    tax_id = (request.form.get("tax_id") or "").strip()
    address = (request.form.get("address") or "").strip()

    payout_method = (request.form.get("payout_method") or "").strip().lower()
    payout_account = (request.form.get("payout_account") or "").strip()

    # basic validation
    if not nid_number:
        return jsonify({"error":"NID number is required."}), 400
    if not payout_method or not payout_account:
        return jsonify({"error":"Payout method and payout account are required."}), 400

    nid_front = request.files.get("nid_front")
    nid_back = request.files.get("nid_back")

    def _save(f):
        if not f or not getattr(f, "filename", ""):
            return None
        filename = secure_filename(f.filename)
        if not filename:
            return None
        ext = os.path.splitext(filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".pdf"]:
            return None
        token = secrets.token_hex(8)
        out = f"{uid}_{token}{ext}"
        full = os.path.join(_seller_upload_dir(), out)
        f.save(full)
        return "/static/uploads/seller_kyc/" + out

    nid_front_path = _save(nid_front)
    nid_back_path = _save(nid_back)

    payout_account_masked = mask_account(payout_account)
    payout_account_encrypted = encrypt_text(payout_account)

    has_enc = db_has_column('seller_profiles', 'payout_account_encrypted')

    existing = db_one("SELECT id FROM seller_profiles WHERE user_id=%s", (uid,))
    if existing:
        if has_enc:
            db_exec(
                "UPDATE seller_profiles SET nid_number=%s, tax_id=%s, address=%s, "
                "payout_method=%s, payout_account_masked=%s, payout_account_encrypted=%s, "
                "nid_front_path=COALESCE(%s,nid_front_path), "
                "nid_back_path=COALESCE(%s,nid_back_path), "
                "verification_status='pending' "
                "WHERE user_id=%s",
                (nid_number or None, tax_id or None, address or None, payout_method, payout_account_masked, payout_account_encrypted, nid_front_path, nid_back_path, uid)
            )
        else:
            db_exec(
                "UPDATE seller_profiles SET nid_number=%s, tax_id=%s, address=%s, "
                "payout_method=%s, payout_account_masked=%s, "
                "nid_front_path=COALESCE(%s,nid_front_path), "
                "nid_back_path=COALESCE(%s,nid_back_path), "
                "verification_status='pending' "
                "WHERE user_id=%s",
                (nid_number or None, tax_id or None, address or None, payout_method, payout_account_masked, nid_front_path, nid_back_path, uid)
            )
    else:
        if has_enc:
            db_exec(
                "INSERT INTO seller_profiles(user_id,nid_number,tax_id,address,payout_method,payout_account_masked,payout_account_encrypted,nid_front_path,nid_back_path,verification_status) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (uid, nid_number or None, tax_id or None, address or None, payout_method, payout_account_masked, payout_account_encrypted, nid_front_path, nid_back_path)
            )
        else:
            db_exec(
                "INSERT INTO seller_profiles(user_id,nid_number,tax_id,address,payout_method,payout_account_masked,nid_front_path,nid_back_path,verification_status) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (uid, nid_number or None, tax_id or None, address or None, payout_method, payout_account_masked, nid_front_path, nid_back_path)
            )

    return jsonify({"success":True, "message":"KYC submitted. Verification pending."})

@app.get("/seller/dashboard")
def seller_dashboard():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    sp = db_one("SELECT verification_status FROM seller_profiles WHERE user_id=%s", (uid,))
    status = (_row_get(sp, "verification_status", 0, "pending") if sp else "pending") or "pending"
    if str(status).lower() != "approved":
        return redirect("/seller/kyc")

    stats = {
        "products": db_one("SELECT COUNT(*) AS c FROM products WHERE seller_id=%s", (uid,)),
        "orders": db_one(
            "SELECT COUNT(DISTINCT oi.order_id) AS c FROM order_items oi WHERE oi.seller_id=%s",
            (uid,),
        ),
        "revenue_paid": db_one(
            "SELECT COALESCE(SUM(oi.line_total),0) AS c "
            "FROM order_items oi JOIN orders o ON o.id=oi.order_id "
            "WHERE oi.seller_id=%s AND o.payment_status='paid'",
            (uid,),
        ),
    }
    return render_template("seller/dashboard.html", stats=stats, status=status)


@app.get("/seller/orders")
def seller_orders():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    sp = db_one("SELECT verification_status FROM seller_profiles WHERE user_id=%s", (uid,))
    status = (_row_get(sp, "verification_status", 0, "pending") if sp else "pending") or "pending"
    if str(status).lower() != "approved":
        return redirect("/seller/kyc")

    rows = db_all(
        "SELECT o.id, o.order_code, o.currency, o.created_at, o.status, o.payment_status, "
        "u.name AS buyer_name, u.email AS buyer_email, "
        "COUNT(oi.id) AS item_count, COALESCE(SUM(oi.line_total),0) AS total "
        "FROM order_items oi "
        "JOIN orders o ON o.id=oi.order_id "
        "JOIN users u ON u.id=o.buyer_id "
        "WHERE oi.seller_id=%s "
        "GROUP BY o.id, o.order_code, o.currency, o.created_at, o.status, o.payment_status, u.name, u.email "
        "ORDER BY o.created_at DESC, o.id DESC",
        (uid,),
    )

    out = []
    for r in (rows or []):
        out.append({
            "order_id": _row_get(r, "id", 0),
            "order_code": _row_get(r, "order_code", 1),
            "currency": _row_get(r, "currency", 2),
            "created_at": _row_get(r, "created_at", 3),
            "status": _row_get(r, "status", 4),
            "payment_status": _row_get(r, "payment_status", 5),
            "buyer_name": _row_get(r, "buyer_name", 6),
            "buyer_email": _row_get(r, "buyer_email", 7),
            "item_count": int(_row_get(r, "item_count", 8, 0) or 0),
            "total": _row_get(r, "total", 9, 0),
        })

    return render_template("seller/orders.html", rows=out)

@app.get("/seller/products")
def seller_products():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    sp = db_one("SELECT verification_status FROM seller_profiles WHERE user_id=%s", (uid,))
    status = (_row_get(sp, "verification_status", 0, "pending") if sp else "pending") or "pending"
    if str(status).lower() != "approved":
        return redirect("/seller/kyc")

    items = db_all("SELECT * FROM products WHERE seller_id=%s ORDER BY created_at DESC", (uid,))
    return render_template("seller/products.html", items=items)

def _gen_pid():
    return "P" + secrets.token_hex(6).upper()

def _normalize_category_slug(v: str) -> str:
    s = (v or "").strip()
    m = {
        "Pottery": "pottery",
        "Textiles": "textiles",
        "Jewelry": "jewelry",
        "Adornments": "jewelry",
        "Jute": "jute",
        "Home Decor": "home_decor",
        "Home": "home_decor",
        "Gifts": "gifts",
    }
    if s in m:
        return m[s]
    return s.lower().replace(" ", "_")



@app.get("/seller/products/new")
def seller_products_new():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    sp = db_one("SELECT verification_status FROM seller_profiles WHERE user_id=%s", (uid,))
    status = (_row_get(sp, "verification_status", 0, "pending") if sp else "pending") or "pending"
    if str(status).lower() != "approved":
        return redirect("/seller/kyc")
    return render_template("seller/product_form.html", mode="new", product=None)

@app.post("/seller/products/new")
def seller_products_create():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    pid = _gen_pid()
    title = (request.form.get("title") or "").strip()
    title_bn = (request.form.get("title_bn") or "").strip()
    price_usd = float((request.form.get("price_usd") or "0").strip() or 0)
    cat = _normalize_category_slug(request.form.get("category") or "")
    img = (request.form.get("image_url") or "").strip()
    desc = (request.form.get("description") or "").strip()

    # Category-wise specifications (saved as JSON)
    specs = {}
    for k, v in request.form.items():
        if k.startswith("spec_"):
            vv = (v or "").strip()
            if vv:
                specs[k[5:]] = vv
    specs_json = json.dumps(specs, ensure_ascii=False) if specs else None

    if not title or price_usd <= 0:
        return redirect("/seller/products/new")

    db_exec(
        "INSERT INTO products(id,title,title_bn,price_usd,category_slug,image_url,description,specs_json,seller_id,status,created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        (pid, title, title_bn or None, price_usd, cat or None, img or None, desc or None, specs_json, uid, _product_status_default())
    )
    return redirect("/seller/products")

@app.get("/seller/products/<pid>/edit")
def seller_products_edit(pid):
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    p = db_one("SELECT * FROM products WHERE id=%s AND seller_id=%s", (pid, uid))
    if not p:
        return redirect("/seller/products")

    fr = db_one(
        "SELECT * FROM flash_requests WHERE product_id=%s AND seller_id=%s ORDER BY created_at DESC LIMIT 1",
        (pid, uid),
    )
    specs = {}
    try:
        if p.get("specs_json"):
            specs = json.loads(p.get("specs_json") or "{}") or {}
    except Exception:
        specs = {}
    return render_template("seller/product_form.html", mode="edit", product=p, flash_req=fr, specs=specs)


@app.post("/seller/products/<pid>/edit")
def seller_products_update(pid):
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    title = (request.form.get("title") or "").strip()
    title_bn = (request.form.get("title_bn") or "").strip()
    price_usd = float((request.form.get("price_usd") or "0").strip() or 0)
    cat = _normalize_category_slug(request.form.get("category") or "")
    img = (request.form.get("image_url") or "").strip()
    desc = (request.form.get("description") or "").strip()

    db_exec(
        "UPDATE products SET title=%s, title_bn=%s, price_usd=%s, category_slug=%s, image_url=%s, description=%s, specs_json=%s "
        "WHERE id=%s AND seller_id=%s",
        (title, title_bn or None, price_usd, cat or None, img or None, desc or None, specs_json, pid, uid)
    )
    return redirect("/seller/products")

# --------------------
# Seller -> Flash Dispatch requests (no DB manual edits)
# --------------------
@app.post("/seller/flash/request")
def seller_flash_request():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    pid = (request.form.get("product_id") or "").strip()
    if not pid:
        return redirect("/seller/products")

    # verify ownership
    p = db_one("SELECT id, seller_id, status FROM products WHERE id=%s AND seller_id=%s", (pid, uid))
    if not p:
        return redirect("/seller/products")

    try:
        req_price = float((request.form.get("requested_price_usd") or "0").strip() or 0)
        req_compare = float((request.form.get("requested_compare_at_usd") or "0").strip() or 0)
    except Exception:
        req_price, req_compare = 0, 0

    # duration can be preset hours or explicit end date
    duration = (request.form.get("duration") or "").strip()
    end_at_raw = (request.form.get("requested_end_at") or "").strip()
    seller_note = (request.form.get("seller_note") or "").strip()

    # basic validation
    if req_price <= 0 or req_compare <= 0 or req_compare <= req_price:
        return redirect(f"/seller/products/{pid}/edit")

    end_at = None
    try:
        if duration in ("6", "12", "24", "48"):
            hrs = int(duration)
            end_at = datetime.now() + timedelta(hours=hrs)
        elif end_at_raw:
            # expected: YYYY-MM-DDTHH:MM from <input type=datetime-local>
            end_at = datetime.strptime(end_at_raw, "%Y-%m-%dT%H:%M")
    except Exception:
        end_at = None

    if not end_at or end_at <= datetime.now():
        return redirect(f"/seller/products/{pid}/edit")

    # prevent spamming: one active pending request at a time
    existing = db_one(
        "SELECT id FROM flash_requests WHERE product_id=%s AND seller_id=%s AND status='pending' ORDER BY created_at DESC LIMIT 1",
        (pid, uid),
    )
    if existing:
        return redirect(f"/seller/products/{pid}/edit")

    db_exec(
        "INSERT INTO flash_requests(product_id, seller_id, requested_price_usd, requested_compare_at_usd, requested_end_at, status, seller_note, created_at) "
        "VALUES(%s,%s,%s,%s,%s,'pending',%s,NOW())",
        (pid, uid, req_price, req_compare, end_at.strftime("%Y-%m-%d %H:%M:%S"), seller_note or None),
    )
    return redirect(f"/seller/products/{pid}/edit")

@app.post("/seller/flash/cancel")
def seller_flash_cancel():
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    rid = (request.form.get("request_id") or "").strip()
    pid = (request.form.get("product_id") or "").strip()
    if not rid or not pid:
        return redirect("/seller/products")
    # only cancel pending
    db_exec(
        "UPDATE flash_requests SET status='cancelled' WHERE id=%s AND seller_id=%s AND product_id=%s AND status='pending'",
        (int(rid), uid, pid),
    )
    return redirect(f"/seller/products/{pid}/edit")


@app.post("/seller/products/<pid>/delete")
def seller_products_delete(pid):
    if not _require_seller_login():
        return redirect("/login")
    uid = int(session.get("user_id"))
    db_exec("DELETE FROM products WHERE id=%s AND seller_id=%s", (pid, uid))
    return redirect("/seller/products")

@app.get("/wishlist")
def wishlist_page():
    return render_template('buyer/wishlist.html')

@app.get("/api/wishlist")
def api_wishlist_get():
    if not _require_login():
        return jsonify({"items": []})

    uid = int(session.get("user_id"))
    rows = db_all(
        "SELECT p.id, p.title, p.title_bn, p.category_slug, p.price_usd, p.image_url, p.maker, p.rating, p.badge "
        "FROM wishlist_items w JOIN products p ON p.id=w.product_id "
        "WHERE w.user_id=%s ORDER BY w.created_at DESC",
        (uid,),
    )
    out = []
    for r in rows:
        out.append({
            "id": _row_get(r, "id", 0),
            "title": _row_get(r, "title", 1),
            "bn": _row_get(r, "title_bn", 2),
            "cat": _row_get(r, "category_slug", 3),
            "usd": float(_row_get(r, "price_usd", 4, 0) or 0),
            "img": _row_get(r, "image_url", 5),
            "maker": _row_get(r, "maker", 6),
            "rating": float(_row_get(r, "rating", 7, 0) or 0),
            "badge": _row_get(r, "badge", 8),
        })
    return jsonify({"items": out})

@app.post("/api/wishlist/toggle")
def api_wishlist_toggle():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id") or "").strip()
    if not pid:
        return jsonify({"error": "product_id required"}), 400

    if not _require_login():
        return jsonify({"success": True, "guest": True})

    uid = int(session.get("user_id"))
    exists = db_one("SELECT id FROM wishlist_items WHERE user_id=%s AND product_id=%s", (uid, pid))
    if exists:
        db_exec("DELETE FROM wishlist_items WHERE user_id=%s AND product_id=%s", (uid, pid))
        return jsonify({"success": True, "wished": False})
    else:
        db_exec("INSERT INTO wishlist_items (user_id, product_id) VALUES (%s,%s)", (uid, pid))
        return jsonify({"success": True, "wished": True})

# ============================================================
# ADMIN FIXES: /admin redirect + create admin + update order
# ============================================================

@app.get("/admin")
def admin_home_redirect():
    return redirect("/admin/dashboard")

@app.post("/admin/admins/create")
@admin_required
def admin_admins_create():
    data = request.form or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "admin").strip()

    if not name or not email or not password:
        return redirect("/admin/admins")

    # ✅ CHECK FROM ADMINS TABLE (NOT users)
    me = db_one("SELECT role FROM admins WHERE id=%s", (int(session.get("admin_id")),))
    if not me or (me["role"] != "superadmin"):
        return redirect("/admin/admins")

    hashed = generate_password_hash(password)

    try:
        db_exec(
            "INSERT INTO admins (name,email,password,role,status) VALUES (%s,%s,%s,%s,'active')",
            (name, email, hashed, role),
        )

        db_exec(
            "INSERT INTO admin_logs (admin_id, action, meta) VALUES (%s,%s,%s)",
            (int(session["admin_id"]), "create_admin", f"email={email};role={role}")
        )
    except Exception:
        pass

    return redirect("/admin/admins")


@app.post("/admin/orders/update")
@admin_required
def admin_orders_update():
    oid = (request.form.get("order_id") or "").strip()
    status = (request.form.get("status") or "").strip()
    if not oid or not status:
        return redirect("/admin/orders")

    db_exec("UPDATE orders SET status=%s WHERE id=%s", (status, oid))

    try:
        db_exec(
            "INSERT INTO admin_logs (admin_id, action, meta) VALUES (%s,%s,%s)",
            (int(session.get("admin_id")), "update_order_status", f"order_id={oid};status={status}"),
        )
    except Exception:
        pass

    return redirect("/admin/orders")

# ============================================================
# MESSAGING: Buyer↔Seller + User↔Admin Support Chat
# ============================================================

# ============================================================
# MESSAGING HUB (Messenger-style unified inbox)
# - Additive: does NOT remove existing chat routes
# - Uses real DB data only
# - RBAC enforced strictly
# ============================================================

# Viewer helpers (supports user sessions + admin sessions)
def _viewer():
    """Return (role, id) where role is one of buyer/seller/admin/superadmin."""
    if session.get("admin_id"):
        a = current_admin()
        if not a:
            return (None, None)
        role = (a.get("role") or "admin").lower()
        if role not in ("admin", "superadmin"):
            role = "admin"
        return (role, int(a.get("id")))

    if session.get("user_id"):
        u = _current_user()
        role = (u.get("role") or "").lower()
        if role not in ("buyer", "seller"):
            return (None, None)
        return (role, int(u.get("id")))

    return (None, None)


def _viewer_scope_where(viewer_role):
    """Return a (where_sql, params_builder) for conversation scope."""
    if viewer_role == "buyer":
        return (
            "((c.type IN (\'buyer_seller\',\'order\') AND c.buyer_id=%s) OR (c.type IN (\'buyer_support\',\'support\') AND c.buyer_id=%s))",
            lambda vid: (int(vid), int(vid)),
        )
    if viewer_role == "seller":
        return (
            "((c.type IN (\'buyer_seller\',\'order\') AND c.seller_id=%s) OR (c.type=\'seller_support\' AND c.buyer_id=%s))",
            lambda vid: (int(vid), int(vid)),
        )
    if viewer_role == "admin":
        return (
            "(c.type IN (\'buyer_support\',\'seller_support\',\'support\'))",
            lambda vid: tuple(),
        )
    if viewer_role == "superadmin":
        return (
            "(c.type IN (\'buyer_seller\',\'order\',\'buyer_support\',\'seller_support\',\'support\'))",
            lambda vid: tuple(),
        )
    return ("(1=0)", lambda vid: tuple())


def _viewer_can_access_conversation(conv_row, viewer_role, viewer_id):
    ctype = (_row_get(conv_row, "type", 1) or "").lower()
    buyer_id = int(_row_get(conv_row, "buyer_id", 3, 0) or 0)
    seller_id = int(_row_get(conv_row, "seller_id", 4, 0) or 0)

    if viewer_role == "buyer":
        if ctype in ("buyer_seller", "order"):
            return buyer_id == int(viewer_id)
        if ctype in ("buyer_support", "support"):
            return buyer_id == int(viewer_id)
        return False

    if viewer_role == "seller":
        if ctype in ("buyer_seller", "order"):
            return seller_id == int(viewer_id)
        if ctype == "seller_support":
            return buyer_id == int(viewer_id)
        return False

    if viewer_role == "admin":
        return ctype in ("buyer_support", "seller_support", "support")

    if viewer_role == "superadmin":
        return ctype in ("buyer_seller", "order", "buyer_support", "seller_support", "support")

    return False


def _mark_conversation_read(conversation_id, viewer_role, viewer_id):
    last = db_one(
        "SELECT id FROM messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1",
        (int(conversation_id),),
    )
    last_id = int(_row_get(last, "id", 0, 0) or 0)
    if last_id <= 0:
        return
    try:
        db_exec(
            """
            INSERT INTO conversation_reads (conversation_id, viewer_role, viewer_id, last_read_message_id, last_read_at)
            VALUES (%s,%s,%s,%s,NOW())
            ON DUPLICATE KEY UPDATE
              last_read_message_id=GREATEST(last_read_message_id, VALUES(last_read_message_id)),
              last_read_at=NOW()
            """,
            (int(conversation_id), viewer_role, int(viewer_id), int(last_id)),
        )
    except Exception:
        pass


# -----------------------------
# Messages hub pages
# -----------------------------
@app.get("/messages")
def messages_hub_page():
    if not session.get("user_id"):
        return redirect("/login")
    u = _current_user()
    role = (u.get("role") or "").lower()
    if role not in ("buyer", "seller"):
        return redirect("/")

    start = (request.args.get("start") or "").strip().lower()
    seller_id = int(request.args.get("seller_id") or 0)
    order_code = (request.args.get("order_code") or "").strip()
    conv_id = int(request.args.get("conv") or 0)

    return render_template(
        "chat/messages_hub.html",
        hub_role=role,
        start=start,
        seller_id=seller_id,
        order_code=order_code,
        open_conv_id=conv_id,
    )


@app.get("/admin/messages")
@admin_required
def admin_messages_page():
    a = current_admin()
    if not a:
        return redirect("/admin/login")
    if (a.get("role") or "admin").lower() == "superadmin":
        return redirect("/superadmin/messages")
    tab = (request.args.get("tab") or "buyer_support").strip().lower()
    if tab not in ("buyer_support", "seller_support"):
        tab = "buyer_support"
    return render_template("admin/messages_hub.html", tab=tab, admin=a)


@app.get("/superadmin/messages")
@superadmin_required
def superadmin_messages_page():
    tab = (request.args.get("tab") or "buyer_seller").strip().lower()
    if tab != "buyer_seller":
        return redirect('/superadmin/support-inbox')
    return render_template("superadmin/messages_hub.html", tab="buyer_seller", readonly=True, admin=current_admin())


# -----------------------------
# Messages hub APIs
# -----------------------------
@app.get("/api/messages/unread-count")
def api_messages_unread_count():
    viewer_role, viewer_id = _viewer()
    if not viewer_role or not viewer_id:
        return jsonify({"count": 0})

    where_sql, params_builder = _viewer_scope_where(viewer_role)
    scope_params = params_builder(viewer_id)

    sql = f"""
    SELECT COALESCE(SUM(t.unread_cnt),0) AS unread_total
    FROM (
      SELECT c.id,
        (
          SELECT COUNT(*)
          FROM messages m
          WHERE m.conversation_id=c.id
            AND m.id > COALESCE(cr.last_read_message_id,0)
            AND NOT (m.sender_role=%s AND m.sender_id=%s)
        ) AS unread_cnt
      FROM conversations c
      LEFT JOIN conversation_reads cr
        ON cr.conversation_id=c.id AND cr.viewer_role=%s AND cr.viewer_id=%s
      WHERE {where_sql}
    ) t
    """

    params = (viewer_role, int(viewer_id), viewer_role, int(viewer_id), *scope_params)
    try:
        row = db_one(sql, params)
        unread = int(_row_get(row, "unread_total", 0, 0) or 0)
    except Exception:
        unread = 0
    return jsonify({"count": unread})


@app.get("/api/messages/threads")
def api_messages_threads():
    viewer_role, viewer_id = _viewer()
    if not viewer_role or not viewer_id:
        return jsonify({"threads": []})

    tab = (request.args.get("tab") or "").strip().lower()

    where_sql, params_builder = _viewer_scope_where(viewer_role)
    scope_params = params_builder(viewer_id)

    # Tab narrowing for admin/superadmin
    extra = ""
    extra_params = tuple()
    if viewer_role == "admin":
        if tab in ("buyer_support", "seller_support"):
            extra = " AND c.type=%s"
            extra_params = (tab,)
    if viewer_role == "superadmin":
        if tab in ("buyer_seller", "buyer_support", "seller_support"):
            if tab == "buyer_seller":
                extra = " AND c.type IN ('buyer_seller','order')"
            else:
                extra = " AND c.type=%s"
                extra_params = (tab,)

    sql = f"""
      SELECT
        c.id,
        c.type,
        c.order_id,
        c.buyer_id,
        c.seller_id,
        COALESCE(c.last_message_at, c.created_at) AS last_at,
        COALESCE(cr.last_read_message_id, 0) AS last_read_id,
        (
          SELECT COUNT(*)
          FROM messages m
          WHERE m.conversation_id=c.id
            AND m.id > COALESCE(cr.last_read_message_id,0)
            AND NOT (m.sender_role=%s AND m.sender_id=%s)
        ) AS unread_count,
        (
          SELECT m2.message_text
          FROM messages m2
          WHERE m2.conversation_id=c.id
          ORDER BY m2.id DESC
          LIMIT 1
        ) AS last_message,
        ub.name AS buyer_name,
        ub.email AS buyer_email,
        us.name AS seller_name,
        us.email AS seller_email,
        o.order_code
      FROM conversations c
      LEFT JOIN conversation_reads cr
        ON cr.conversation_id=c.id AND cr.viewer_role=%s AND cr.viewer_id=%s
      LEFT JOIN users ub ON ub.id=c.buyer_id
      LEFT JOIN users us ON us.id=c.seller_id
      LEFT JOIN orders o ON o.id=c.order_id
      WHERE {where_sql}{extra}
      ORDER BY last_at DESC, c.id DESC
      LIMIT 200
    """

    params = (viewer_role, int(viewer_id), viewer_role, int(viewer_id), *scope_params, *extra_params)
    try:
        rows = db_all(sql, params)
    except Exception:
        rows = []

    threads = []
    for r in (rows or []):
        ctype = (_row_get(r, 'type', 1) or '').lower()
        tid = int(_row_get(r, 'id', 0) or 0)
        unread = int(_row_get(r, 'unread_count', 7, 0) or 0)
        last_msg = _row_get(r, 'last_message', 8) or ''
        order_code = _row_get(r, 'order_code', 14) or None

        # Title depends on viewer role and conversation type
        title = 'Support'
        subtitle = ''
        if ctype in ('buyer_support','seller_support','support'):
            if viewer_role in ('buyer','seller'):
                title = 'Support (Admin)'
            else:
                # admin/superadmin: show user identity; for seller_support buyer_id is seller user
                title = _row_get(r, 'buyer_name', 9) or 'User'
                subtitle = _row_get(r, 'buyer_email', 10) or ''
        else:
            if viewer_role == 'buyer':
                title = _row_get(r, 'seller_name', 11) or 'Seller'
                subtitle = _row_get(r, 'seller_email', 12) or ''
            elif viewer_role == 'seller':
                title = _row_get(r, 'buyer_name', 9) or 'Buyer'
                subtitle = _row_get(r, 'buyer_email', 10) or ''
            else:
                # superadmin viewing buyer/seller
                title = f"{_row_get(r,'buyer_name',9) or 'Buyer'} ↔ {_row_get(r,'seller_name',11) or 'Seller'}"
                subtitle = (order_code and f"Order: {order_code}") or ''

        threads.append({
            'id': tid,
            'type': ctype,
            'order_id': int(_row_get(r, 'order_id', 2, 0) or 0) if _row_get(r,'order_id',2) else None,
            'order_code': order_code,
            'buyer_id': int(_row_get(r,'buyer_id',3,0) or 0),
            'seller_id': int(_row_get(r,'seller_id',4,0) or 0) if _row_get(r,'seller_id',4) else None,
            'last_at': str(_row_get(r,'last_at',5) or ''),
            'unread': unread,
            'last_message': last_msg,
            'title': title,
            'subtitle': subtitle,
        })

    return jsonify({'threads': threads})


@app.get('/api/messages/thread/<int:conversation_id>')
def api_messages_thread(conversation_id):
    viewer_role, viewer_id = _viewer()
    if not viewer_role or not viewer_id:
        return jsonify({'error': 'auth'}), 401

    conv = db_one('SELECT id, type, order_id, buyer_id, seller_id FROM conversations WHERE id=%s', (int(conversation_id),))
    if not conv:
        return jsonify({'error': 'not_found'}), 404

    if not _viewer_can_access_conversation(conv, viewer_role, viewer_id):
        return jsonify({'error': 'forbidden'}), 403

    rows = db_all(
        'SELECT id, sender_role, sender_id, message_text, created_at FROM messages WHERE conversation_id=%s ORDER BY id ASC LIMIT 1000',
        (int(conversation_id),),
    )

    messages = []
    for r in (rows or []):
        messages.append({
            'id': int(_row_get(r,'id',0) or 0),
            'sender_role': _row_get(r,'sender_role',1) or '',
            'sender_id': int(_row_get(r,'sender_id',2) or 0),
            'text': _row_get(r,'message_text',3) or '',
            'created_at': str(_row_get(r,'created_at',4) or ''),
        })

    # mark read pointer (new)
    _mark_conversation_read(conversation_id, viewer_role, viewer_id)

    ctype = (_row_get(conv,'type',1) or '').lower()

    meta = {}
    if viewer_role == 'superadmin' and ctype in ('buyer_seller','order'):
        b = db_one('SELECT id, name, email FROM users WHERE id=%s', (int(_row_get(conv,'buyer_id',3,0) or 0),))
        s = db_one('SELECT id, name, email FROM users WHERE id=%s', (int(_row_get(conv,'seller_id',4,0) or 0),))
        meta = {
            'buyer': {
                'user_id': int(_row_get(b,'id',0,0) or 0) if b else int(_row_get(conv,'buyer_id',3,0) or 0),
                'name': (_row_get(b,'name',1) or '') if b else '',
                'email': (_row_get(b,'email',2) or '') if b else '',
            },
            'seller': {
                'user_id': int(_row_get(s,'id',0,0) or 0) if s else int(_row_get(conv,'seller_id',4,0) or 0),
                'name': (_row_get(s,'name',1) or '') if s else '',
                'email': (_row_get(s,'email',2) or '') if s else '',
            },
        }

    return jsonify({'conversation_id': int(conversation_id), 'messages': messages, 'type': ctype, 'meta': meta})


@app.post('/api/messages/thread/<int:conversation_id>/send')
def api_messages_thread_send(conversation_id):
    viewer_role, viewer_id = _viewer()
    if not viewer_role or not viewer_id:
        return jsonify({'error': 'auth'}), 401

    data = request.get_json(force=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'empty'}), 400

    conv = db_one('SELECT id, type, order_id, buyer_id, seller_id FROM conversations WHERE id=%s', (int(conversation_id),))
    if not conv:
        return jsonify({'error': 'not_found'}), 404

    ctype = (_row_get(conv,'type',1) or '').lower()

    if not _viewer_can_access_conversation(conv, viewer_role, viewer_id):
        return jsonify({'error': 'forbidden'}), 403

    # Superadmin is read-only in messages hub
    if viewer_role == 'superadmin':
        return jsonify({'error': 'readonly'}), 403

    # Admin cannot write buyer<->seller conversations
    if viewer_role == 'admin' and ctype in ('buyer_seller','order'):
        return jsonify({'error': 'forbidden'}), 403

    sender_role = viewer_role
    sender_id = int(viewer_id)
    # For admin/superadmin, store sender_role as 'admin' so existing UIs remain consistent
    if viewer_role in ('admin','superadmin'):
        sender_role = 'admin'

    db_exec(
        "INSERT INTO messages (conversation_id, sender_role, sender_id, message_text, status) VALUES (%s,%s,%s,%s,'sent')",
        (int(conversation_id), sender_role, sender_id, text),
    )
    try:
        db_exec('UPDATE conversations SET last_message_at=NOW() WHERE id=%s', (int(conversation_id),))
    except Exception:
        pass

    return jsonify({'ok': True})


@app.post('/api/messages/start')
def api_messages_start():
    """Start (or get) a conversation for the hub.
    Supported payloads:
      {"kind":"seller", "seller_id":123}
      {"kind":"order", "order_code":"ABC", "seller_id":123}
      {"kind":"support"}
    """
    viewer_role, viewer_id = _viewer()
    if not viewer_role or not viewer_id:
        return jsonify({'error': 'auth'}), 401

    data = request.get_json(force=True) or {}
    kind = (data.get('kind') or '').strip().lower()

    # Buyer starts seller chat
    if kind == 'seller':
        if viewer_role != 'buyer':
            return jsonify({'error': 'forbidden'}), 403
        seller_id = int(data.get('seller_id') or 0)
        if seller_id <= 0:
            return jsonify({'error': 'seller_id required'}), 400
        conv = db_one(
            "SELECT id FROM conversations WHERE type='buyer_seller' AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1",
            (int(viewer_id), int(seller_id)),
        )
        if not conv:
            db_exec(
                "INSERT INTO conversations (type, buyer_id, seller_id, status, priority, last_message_at) VALUES ('buyer_seller',%s,%s,'open','normal',NOW())",
                (int(viewer_id), int(seller_id)),
            )
            conv = db_one(
                "SELECT id FROM conversations WHERE type='buyer_seller' AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1",
                (int(viewer_id), int(seller_id)),
            )
        return jsonify({'conversation_id': int(_row_get(conv,'id',0) or 0)})

    # Buyer/seller starts support
    if kind == 'support':
        if viewer_role not in ('buyer','seller'):
            return jsonify({'error': 'forbidden'}), 403
        ctype = 'seller_support' if viewer_role == 'seller' else 'buyer_support'
        conv = db_one(
            "SELECT id FROM conversations WHERE type=%s AND buyer_id=%s AND status<>'closed' ORDER BY id DESC LIMIT 1",
            (ctype, int(viewer_id)),
        )
        if not conv:
            db_exec(
                "INSERT INTO conversations (type, buyer_id, status, priority, last_message_at) VALUES (%s,%s,'open','normal',NOW())",
                (ctype, int(viewer_id)),
            )
            conv = db_one(
                "SELECT id FROM conversations WHERE type=%s AND buyer_id=%s ORDER BY id DESC LIMIT 1",
                (ctype, int(viewer_id)),
            )
        return jsonify({'conversation_id': int(_row_get(conv,'id',0) or 0)})

    # Buyer order chat deep link (creates if missing)
    if kind == 'order':
        if viewer_role != 'buyer':
            return jsonify({'error': 'forbidden'}), 403
        order_code = (data.get('order_code') or '').strip()
        seller_id = int(data.get('seller_id') or 0)
        if not order_code or seller_id <= 0:
            return jsonify({'error': 'order_code and seller_id required'}), 400
        o = db_one('SELECT id, buyer_id FROM orders WHERE order_code=%s', (order_code,))
        if not o:
            return jsonify({'error': 'order_not_found'}), 404
        order_id = int(_row_get(o,'id',0,0) or 0)
        buyer_id = int(_row_get(o,'buyer_id',1,0) or 0)
        if buyer_id != int(viewer_id):
            return jsonify({'error': 'forbidden'}), 403

        conv = db_one(
            'SELECT id FROM conversations WHERE type=\'order\' AND order_id=%s AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1',
            (order_id, buyer_id, seller_id),
        )
        if not conv:
            db_exec(
                "INSERT INTO conversations (type, order_id, buyer_id, seller_id, last_message_at) VALUES ('order',%s,%s,%s,NOW())",
                (order_id, buyer_id, seller_id),
            )
            conv = db_one(
                'SELECT id FROM conversations WHERE type=\'order\' AND order_id=%s AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1',
                (order_id, buyer_id, seller_id),
            )
        return jsonify({'conversation_id': int(_row_get(conv,'id',0) or 0)})

    return jsonify({'error': 'bad_kind'}), 400



def _chat_user_required():
    if not session.get("user_id"):
        return redirect("/login")
    return None


def _support_type_for_current_user():
    u = _current_user()
    role = (u.get("role") or "").lower()
    return "seller_support" if role == "seller" else "buyer_support"


@app.get("/support/chat")

def support_chat_page():
    need = _chat_user_required()
    if need:
        return need
    return render_template('support/support_chat.html')

@app.post("/api/support/chat/send")

def api_support_send():
    need = _chat_user_required()
    if need:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(force=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Message required"}), 400

    u = _current_user()
    uid = int(u.get("id"))
    role = (u.get("role") or "buyer").lower()
    ctype = _support_type_for_current_user()

    conv = db_one(
        "SELECT id FROM conversations WHERE type=%s AND buyer_id=%s AND status<>'closed' ORDER BY id DESC LIMIT 1",
        (ctype, uid),
    )
    if not conv:
        db_exec(
            "INSERT INTO conversations (type, buyer_id, status, priority, last_message_at) VALUES (%s,%s,'open','normal',NOW())",
            (ctype, uid),
        )
        conv = db_one(
            "SELECT id FROM conversations WHERE type=%s AND buyer_id=%s ORDER BY id DESC LIMIT 1",
            (ctype, uid),
        )

    cid = int(_row_get(conv, "id", 0))

    # Use message_text (DB schema), but keep API output as 'body'
    db_exec(
        "INSERT INTO messages (conversation_id, sender_role, sender_id, message_text, status) VALUES (%s,%s,%s,%s,'sent')",
        (cid, role, uid, body),
    )
    db_exec("UPDATE conversations SET last_message_at=NOW() WHERE id=%s", (cid,))
    return jsonify({"success": True, "conversation_id": cid})

@app.get("/api/support/chat/messages")

def api_support_messages():
    need = _chat_user_required()
    if need:
        return jsonify({"error": "Login required"}), 401

    after = int(request.args.get("after_id") or 0)
    u = _current_user()
    uid = int(u.get("id"))
    ctype = _support_type_for_current_user()

    conv = db_one(
        "SELECT id FROM conversations WHERE type=%s AND buyer_id=%s ORDER BY id DESC LIMIT 1",
        (ctype, uid),
    )
    if not conv:
        return jsonify({"messages": [], "conversation_id": None})

    cid = int(_row_get(conv, "id", 0))
    rows = db_all(
        "SELECT id, sender_role, sender_id, message_text, created_at FROM messages WHERE conversation_id=%s AND id>%s ORDER BY id ASC",
        (cid, after),
    )
    msgs = []
    for r in rows:
        msgs.append({
            "id": int(_row_get(r, "id", 0) or 0),
            "role": _row_get(r, "sender_role", 1),
            "sender_id": int(_row_get(r, "sender_id", 2) or 0),
            "body": _row_get(r, "message_text", 3) or "",
            "created_at": str(_row_get(r, "created_at", 4) or ""),
        })
    return jsonify({"messages": msgs, "conversation_id": cid})

@app.get("/chat/seller/<int:seller_id>")
def buyer_seller_chat_page(seller_id):
    need = _chat_user_required()
    if need:
        return need
    if not _require_role("buyer"):
        return redirect("/")
    return render_template('chat/chat_seller.html', seller_id=seller_id)

@app.post("/api/chat/seller/send")
def api_chat_seller_send():
    need = _chat_user_required()
    if need:
        return jsonify({"error": "Login required"}), 401
    if not _require_role("buyer"):
        return jsonify({"error": "Buyer only"}), 403

    data = request.get_json(force=True) or {}
    seller_id = int(data.get("seller_id") or 0)
    body = (data.get("body") or "").strip()
    if seller_id <= 0 or not body:
        return jsonify({"error": "seller_id and body required"}), 400

    buyer_id = int(session.get("user_id"))
    conv = db_one(
        "SELECT id FROM conversations WHERE type='buyer_seller' AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1",
        (buyer_id, seller_id),
    )
    if not conv:
        db_exec(
            "INSERT INTO conversations (type, buyer_id, seller_id, status, priority) VALUES ('buyer_seller',%s,%s,'open','normal')",
            (buyer_id, seller_id),
        )
        conv = db_one(
            "SELECT id FROM conversations WHERE type='buyer_seller' AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1",
            (buyer_id, seller_id),
        )

    cid = int(_row_get(conv, "id", 0))
    db_exec(
        "INSERT INTO messages (conversation_id, sender_role, sender_id, message_text, status) VALUES (%s,'buyer',%s,%s,'sent')",
        (cid, buyer_id, body),
    )
    db_exec("UPDATE conversations SET last_message_at=NOW() WHERE id=%s", (cid,))
    return jsonify({"success": True, "conversation_id": cid})

@app.get("/api/chat/seller/messages")
def api_chat_seller_messages():
    need = _chat_user_required()
    if need:
        return jsonify({"error": "Login required"}), 401
    if not _require_role("buyer"):
        return jsonify({"error": "Buyer only"}), 403

    seller_id = int(request.args.get("seller_id") or 0)
    after = int(request.args.get("after_id") or 0)
    buyer_id = int(session.get("user_id"))
    conv = db_one(
        "SELECT id FROM conversations WHERE type='buyer_seller' AND buyer_id=%s AND seller_id=%s ORDER BY id DESC LIMIT 1",
        (buyer_id, seller_id),
    )
    if not conv:
        return jsonify({"messages": [], "conversation_id": None})

    cid = int(_row_get(conv, "id", 0))
    rows = db_all(
        "SELECT id, sender_role, sender_id, message_text, created_at FROM messages WHERE conversation_id=%s AND id>%s ORDER BY id ASC",
        (cid, after),
    )
    msgs = []
    for r in rows:
        msgs.append({
            "id": int(_row_get(r, "id", 0) or 0),
            "role": _row_get(r, "sender_role", 1),
            "sender_id": int(_row_get(r, "sender_id", 2) or 0),
            "body": _row_get(r, "message_text", 3),
            "created_at": str(_row_get(r, "created_at", 4) or ""),
        })
    return jsonify({"messages": msgs, "conversation_id": cid})

# ----------------------------
# ADMIN SUPPORT INBOX
# ----------------------------

@app.get("/admin/support")
@admin_required
def admin_support_inbox():
    # Legacy endpoint — support is handled in Messages Hub
    return redirect('/admin/messages?tab=buyer_support')

@app.get("/admin/support/<int:cid>")
@admin_required
def admin_support_thread(cid):
    conv = db_one(
        "SELECT c.id, c.status, c.priority, c.category, c.created_at, u.name, u.email, u.id AS buyer_id "
        "FROM conversations c JOIN users u ON u.id=c.buyer_id WHERE c.id=%s AND c.type IN ('support','buyer_support','seller_support')",
        (cid,),
    )
    if not conv:
        return redirect("/admin/support")
    return render_template("admin/support_thread.html", conv=conv)

@app.post("/api/admin/support/send")
@admin_required
def api_admin_support_send():
    data = request.get_json(force=True) or {}
    cid = int(data.get("conversation_id") or 0)
    body = (data.get("body") or "").strip()
    if cid <= 0 or not body:
        return jsonify({"error": "conversation_id and body required"}), 400

    db_exec(
        "INSERT INTO messages (conversation_id, sender_role, sender_id, message_text, status) VALUES (%s,'admin',%s,%s,'sent')",
        (cid, int(session.get("admin_id")), body),
    )
    return jsonify({"success": True})

@app.post("/api/admin/support/close")
@admin_required
def api_admin_support_close():
    data = request.get_json(force=True) or {}
    cid = int(data.get("conversation_id") or 0)
    if cid <= 0:
        return jsonify({"error": "conversation_id required"}), 400
    db_exec("UPDATE conversations SET status='closed' WHERE id=%s AND type IN ('support','buyer_support','seller_support')", (cid,))
    return jsonify({"success": True})

@app.get("/api/admin/support/messages")
@admin_required
def api_admin_support_messages():
    cid = int(request.args.get("conversation_id") or 0)
    after = int(request.args.get("after_id") or 0)
    if cid <= 0:
        return jsonify({"messages": []})

    rows = db_all(
        "SELECT id, sender_role, sender_id, message_text, created_at FROM messages WHERE conversation_id=%s AND id>%s ORDER BY id ASC",
        (cid, after),
    )
    msgs = []
    for r in rows:
        msgs.append({
            "id": int(_row_get(r, "id", 0) or 0),
            "role": _row_get(r, "sender_role", 1),
            "sender_id": int(_row_get(r, "sender_id", 2) or 0),
            "body": _row_get(r, "message_text", 3),
            "created_at": str(_row_get(r, "created_at", 4) or ""),
        })
    return jsonify({"messages": msgs})




# ============================================================
# SUPERADMIN: Unified Support Inbox (Phase-2)
# Tabs:
#  1) buyer_seller + order chats (READ-ONLY)
#  2) buyer_support (READ/WRITE via admin endpoints)
#  3) seller_support (READ/WRITE via admin endpoints)
# ============================================================

@app.get("/superadmin/support-inbox")
@superadmin_required
def superadmin_support_inbox():
    # Support box: only user→admin conversations
    tab = (request.args.get("tab") or "buyer_support").strip().lower()
    if tab not in ["buyer_support", "seller_support"]:
        tab = "buyer_support"

    # If schema is not migrated yet, do not crash
    if not (db_has_table('conversations') and db_has_column('conversations','type')):
        return render_template(
            "superadmin/support_inbox.html",
            tab=tab,
            rows=[],
            readonly=False,
            admin=current_admin(),
        )

    join_col = "buyer_id" if tab == "buyer_support" else "seller_id"

    # Optional columns (keep backward compatible)
    has_status = db_has_column('conversations','status')
    has_priority = db_has_column('conversations','priority')
    status_sel = "c.status" if has_status else "'open' AS status"
    priority_sel = "c.priority" if has_priority else "'normal' AS priority"
    order_by = "c.status ASC," if has_status else ""

    rows = db_all(
        f"""
        SELECT c.id, c.type,
               {status_sel},
               {priority_sel},
               COALESCE(c.last_message_at, c.created_at) AS last_at,
               u.name, u.email
        FROM conversations c
        JOIN users u ON u.id=c.{join_col}
        WHERE c.type=%s
        ORDER BY {order_by} last_at DESC, c.id DESC
        LIMIT 500
        """,
        (tab,),
    )

    return render_template("superadmin/support_inbox.html", tab=tab, rows=rows, readonly=False, admin=current_admin())


@app.get("/superadmin/support-inbox/<int:cid>")
@superadmin_required
def superadmin_support_thread(cid):
    if not (db_has_table('conversations') and db_has_column('conversations','type')):
        return redirect('/superadmin/support-inbox')

    c = db_one("SELECT id, type FROM conversations WHERE id=%s", (int(cid),))
    if not c:
        return redirect("/superadmin/support-inbox")

    ctype = (_row_get(c, "type", 1) or "").lower()
    # Superadmin: read-only for buyer<->seller chats, but can reply in support threads
    readonly = True

    if ctype in ("buyer_seller", "order"):
        head = db_one(
            """
            SELECT c.id, c.type, c.order_id, c.buyer_id, c.seller_id,
                   COALESCE(c.last_message_at, c.created_at) AS last_at,
                   ub.name AS buyer_name,
                   us.name AS seller_name,
                   o.order_code
            FROM conversations c
            LEFT JOIN users ub ON ub.id=c.buyer_id
            LEFT JOIN users us ON us.id=c.seller_id
            LEFT JOIN orders o ON o.id=c.order_id
            WHERE c.id=%s
            """,
            (int(cid),),
        )
    else:
        join_col = 'buyer_id' if ctype == 'buyer_support' else 'seller_id'
        has_status = db_has_column('conversations','status')
        has_priority = db_has_column('conversations','priority')
        status_sel = 'c.status' if has_status else "'open' AS status"
        priority_sel = 'c.priority' if has_priority else "'normal' AS priority"
        head = db_one(
            f"""
            SELECT c.id, c.type, {status_sel}, {priority_sel},
                   COALESCE(c.last_message_at, c.created_at) AS last_at,
                   u.name, u.email
            FROM conversations c
            JOIN users u ON u.id=c.{join_col}
            WHERE c.id=%s
            """,
            (int(cid),),
        )

    if not head:
        return redirect("/superadmin/support-inbox")

    if ctype in ("buyer_support", "seller_support"):
        readonly = False

    return render_template("superadmin/support_thread.html", head=head, readonly=readonly, admin=current_admin())


@app.get('/superadmin/seller-payouts')
@superadmin_required
def superadmin_seller_payouts():
    """Seller payout list (method + masked account)."""
    q = (request.args.get('q') or '').strip()
    kyc = (request.args.get('kyc') or 'all').strip().lower()
    where = "WHERE u.role='seller' "
    params = []
    if q:
        where += "AND (u.name LIKE %s OR u.email LIKE %s OR sp.shop_name LIKE %s) "
        like = f"%{q}%"
        params.extend([like, like, like])

    # Optional KYC filter (all|pending|approved|rejected)
    if kyc in ("pending", "approved", "rejected"):
        where += "AND COALESCE(sp.verification_status,'pending')=%s "
        params.append(kyc)

    has_enc = db_has_column('seller_profiles','payout_account_encrypted')

    rows = db_all(
        f"""
        SELECT u.id, u.name, u.email,
               COALESCE(sp.shop_name,'') AS shop_name,
               COALESCE(sp.verification_status,'pending') AS verification_status,
               COALESCE(sp.payout_method,'') AS payout_method,
               COALESCE(sp.payout_account_masked,'') AS payout_account_masked,
               {"COALESCE(sp.payout_account_encrypted,'')" if has_enc else "''"} AS payout_account_encrypted
        FROM users u
        LEFT JOIN seller_profiles sp ON sp.user_id=u.id
        {where}
        ORDER BY u.id DESC
        LIMIT 800
        """,
        tuple(params),
    )

    sellers = []
    for r in rows:
        sellers.append({
            'id': int(_row_get(r, 'id', 0) or 0),
            'name': _row_get(r, 'name', 1),
            'email': _row_get(r, 'email', 2),
            'shop_name': _row_get(r, 'shop_name', 3),
            'verification_status': _row_get(r, 'verification_status', 4),
            'payout_method': _row_get(r, 'payout_method', 5),
            'payout_account_masked': _row_get(r, 'payout_account_masked', 6),
            'has_full': bool(_row_get(r, 'payout_account_encrypted', 7)),
        })

    return render_template('superadmin/seller_payouts.html', sellers=sellers, q=q, kyc=kyc, admin=current_admin())



@app.get('/superadmin/seller-payouts/<int:seller_id>/reveal')
@superadmin_required
def superadmin_reveal_seller_payout(seller_id):
    """Superadmin-only: reveal full payout account (decrypt)."""
    # Backward compatible: if DB not migrated, do not crash
    if not db_has_column('seller_profiles','payout_account_encrypted'):
        return jsonify({'error':'DB is missing payout_account_encrypted. Please run DB ALTER.'}), 400

    sp = db_one("SELECT payout_account_encrypted FROM seller_profiles WHERE user_id=%s", (int(seller_id),))
    enc = (_row_get(sp, 'payout_account_encrypted', 0, '') or '').strip() if sp else ''
    if not enc:
        return jsonify({'error':'No saved payout details.'}), 404

    plain = decrypt_text(enc)
    if not plain:
        return jsonify({'error':'Unable to decrypt payout details.'}), 400

    a = current_admin() or {}
    try:
        db_exec(
            "INSERT INTO audit_logs (actor_id, actor_role, action, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (int(a.get('id') or 0), a.get('role'), 'seller_payout_reveal', 'seller', int(seller_id), 'revealed payout account'),
        )
    except Exception:
        pass

    return jsonify({'success': True, 'account': plain})
# ============================================================
# MISSING ROUTES FOR SUPERADMIN DASHBOARD BUTTONS
# (Risk center, KYC review, flagged chat, escrow ledger, exports)
# ============================================================

@app.get("/superadmin/risk")
@superadmin_required
def superadmin_risk_center():
    """Lightweight risk signals (Phase-1)."""
    dup = db_one(
        """
        SELECT COUNT(*) FROM (
          SELECT trnx_id FROM orders
          WHERE trnx_id IS NOT NULL AND trnx_id<>''
          GROUP BY trnx_id HAVING COUNT(*)>1
        ) x
        """
    )
    dup_trx = int(_row_get(dup, "COUNT(*)", 0, 0) or 0)

    high_cancel = db_one(
        """
        SELECT COUNT(*) FROM (
          SELECT oi.seller_id
          FROM orders o
          JOIN order_items oi ON oi.order_id=o.id
          GROUP BY oi.seller_id
          HAVING SUM(CASE WHEN o.status='cancelled' THEN 1 ELSE 0 END) >= 3
        ) t
        """
    )
    high_cancel_sellers = int(_row_get(high_cancel, "COUNT(*)", 0, 0) or 0)

    # Refund ratio signal (only if refunded exists in your order status enum)
    high_refund = db_one(
        """
        SELECT COUNT(*) FROM (
          SELECT oi.seller_id,
                 SUM(CASE WHEN o.status='refunded' THEN 1 ELSE 0 END) AS refunds,
                 COUNT(*) AS total
          FROM orders o
          JOIN order_items oi ON oi.order_id=o.id
          GROUP BY oi.seller_id
          HAVING (refunds / NULLIF(total,0)) >= 0.25 AND total >= 4
        ) t
        """
    )
    high_refund_sellers = int(_row_get(high_refund, "COUNT(*)", 0, 0) or 0)

    # Unverified sellers with volume (only if schema supports verification_status)
    unverified_high_volume = 0
    if db_has_table('seller_profiles') and db_has_column('seller_profiles','verification_status'):
        unverified = db_one(
            """
            SELECT COUNT(*) FROM (
              SELECT oi.seller_id
              FROM order_items oi
              JOIN orders o ON o.id=oi.order_id
              LEFT JOIN seller_profiles sp ON sp.user_id=oi.seller_id
              GROUP BY oi.seller_id
              HAVING SUM(oi.qty) >= 10 AND COALESCE(sp.verification_status,'pending') <> 'approved'
            ) t
            """
        )
        unverified_high_volume = int(_row_get(unverified, "COUNT(*)", 0, 0) or 0)


    risk = {
        "dup_trx": dup_trx,
        "high_cancel_sellers": high_cancel_sellers,
        "high_refund_sellers": high_refund_sellers,
        "unverified_high_volume": unverified_high_volume,
    }
    return render_template("superadmin/risk.html", risk=risk, admin=current_admin())


@app.get("/admin/sellers")
@admin_required
def admin_sellers_directory():
    """Admin/SuperAdmin seller directory + KYC filter."""
    kyc = (request.args.get("kyc") or "").strip().lower()
    q = (request.args.get("q") or "").strip()

    where = "WHERE u.role='seller' "
    params = []
    if kyc in ["pending", "approved", "rejected"]:
        where += "AND COALESCE(sp.verification_status,'pending')=%s "
        params.append(kyc)
    if q:
        where += "AND (u.name LIKE %s OR u.email LIKE %s OR sp.shop_name LIKE %s) "
        like = f"%{q}%"
        params.extend([like, like, like])

    rows = db_all(
        f"""
        SELECT u.id, u.name, u.email,
               COALESCE(sp.shop_name,'') AS shop_name,
               COALESCE(sp.verification_status,'pending') AS verification_status,
               COALESCE(sp.payout_method,'') AS payout_method,
               COALESCE(sp.payout_account_masked,'') AS payout_account
        FROM users u
        LEFT JOIN seller_profiles sp ON sp.user_id=u.id
        {where}
        ORDER BY u.id DESC
        LIMIT 500
        """,
        tuple(params),
    )
    sellers = []
    for r in rows:
        sellers.append({
            "id": int(_row_get(r, "id", 0) or 0),
            "name": _row_get(r, "name", 1),
            "email": _row_get(r, "email", 2),
            "shop_name": _row_get(r, "shop_name", 3),
            "verification_status": _row_get(r, "verification_status", 4),
            "payout_method": _row_get(r, "payout_method", 5),
            "payout_account": _row_get(r, "payout_account", 6),
        })

    return render_template("admin/sellers.html", sellers=sellers, kyc=kyc, q=q, admin=current_admin())


@app.get("/admin/accounts")
@admin_required
def admin_accounts():
    """Admin directory for buyer/seller accounts + search + block/unblock."""
    role = (request.args.get("role") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    q = (request.args.get("q") or "").strip()

    where = "WHERE u.role IN ('buyer','seller') "
    params = []

    if role in ["buyer", "seller"]:
        where += "AND u.role=%s "
        params.append(role)

    if status in ["active", "blocked"]:
        where += "AND u.status=%s "
        params.append(status)

    if q:
        like = f"%{q}%"
        where += "AND (u.name LIKE %s OR u.email LIKE %s OR CAST(u.id AS CHAR) LIKE %s) "
        params.extend([like, like, like])

    users = db_all(
        f"""SELECT u.id, u.name, u.email, u.role, u.status, u.created_at
            FROM users u
            {where}
            ORDER BY u.created_at DESC
            LIMIT 200""",
        tuple(params)
    )

    return render_template(
        "admin/accounts.html",
        title="Accounts",
        users=users,
        q=q,
        role=role,
        status=status,
        admin=current_admin()
    )

@app.post("/admin/accounts/<int:user_id>/toggle")
@admin_required
def admin_toggle_account(user_id):
    # Only buyer/seller can be blocked from this screen (keep admin moderation in SuperAdmin panel).
    u = db_one("SELECT id, role, status FROM users WHERE id=%s", (user_id,))
    if not u:
        return make_response("Not found", 404)

    if u.get("role") not in ["buyer", "seller"]:
        return make_response("Forbidden", 403)

    new_status = "blocked" if (u.get("status") or "active") == "active" else "active"
    db_exec("UPDATE users SET status=%s WHERE id=%s", (new_status, user_id))

    nxt = request.args.get("next")
    if not nxt:
        try:
            ref = request.referrer or ""
            if "/admin/accounts" in ref:
                nxt = ref
        except Exception:
            nxt = None
    return redirect(nxt or "/admin/accounts")


@app.get("/admin/sellers/<int:uid>")
@admin_required
def admin_seller_details(uid):
    """Admin view: seller profile + KYC docs + quick stats + approve/reject."""
    a = current_admin()

    # NOTE: `users` table doesn't store phone (it's in `user_profiles.phone`).
    # Use a LEFT JOIN so this stays schema-safe even if a profile row doesn't exist.
    u = db_one(
        """
        SELECT u.id, u.name, u.email,
               COALESCE(up.phone, '') AS phone,
               u.role, u.created_at
        FROM users u
        LEFT JOIN user_profiles up ON up.user_id = u.id
        WHERE u.id=%s
        """,
        (int(uid),),
    )
    if not u or (_row_get(u, 'role', 4, '') or '').lower() != 'seller':
        return redirect(request.referrer or "/admin/sellers")

    sp = None
    try:
        sp = db_one(
            """
            SELECT * FROM seller_profiles WHERE user_id=%s
            """,
            (int(uid),),
        )
    except Exception:
        sp = None

    # Quick stats (best-effort)
    stats = {
        "orders_total": 0,
        "orders_completed": 0,
        "gross_sales": 0.0,
    }
    try:
        r = db_one("SELECT COUNT(*) AS c FROM orders WHERE seller_id=%s", (int(uid),))
        stats["orders_total"] = int(_row_get(r, 'c', 0, 0) or 0)
        r = db_one("SELECT COUNT(*) AS c FROM orders WHERE seller_id=%s AND status='delivered'", (int(uid),))
        stats["orders_completed"] = int(_row_get(r, 'c', 0, 0) or 0)
        r = db_one("SELECT COALESCE(SUM(grand_total),0) AS s FROM orders WHERE seller_id=%s AND status='delivered'", (int(uid),))
        stats["gross_sales"] = float(_row_get(r, 's', 0, 0) or 0)
    except Exception:
        pass

    # Recent orders preview
    recent_orders = []
    try:
        rows = db_all(
            """
            SELECT id, order_code, grand_total, payment_status, status, created_at
            FROM orders
            WHERE seller_id=%s
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """,
            (int(uid),),
        )
        for r in rows or []:
            recent_orders.append({
                "id": _row_get(r, 'id', 0),
                "order_code": _row_get(r, 'order_code', 1),
                "grand_total": _row_get(r, 'grand_total', 2),
                "payment_status": _row_get(r, 'payment_status', 3),
                "status": _row_get(r, 'status', 4),
                "created_at": _row_get(r, 'created_at', 5),
            })
    except Exception:
        pass

    seller = {
        "id": _row_get(u, 'id', 0),
        "name": _row_get(u, 'name', 1),
        "email": _row_get(u, 'email', 2),
        "phone": _row_get(u, 'phone', 3, ''),
        "created_at": _row_get(u, 'created_at', 5),
    }

    return render_template(
        "admin/seller_details.html",
        admin=a,
        seller=seller,
        profile=sp,
        stats=stats,
        recent_orders=recent_orders,
    )


@app.get("/admin/chat/flags")
@admin_required
def admin_flagged_conversations():
    """Phase-1: flagged conversations overview (read-only).

    If you later add a 'flagged' column, replace the WHERE clause.
    For now we show recent order chats as an oversight panel.
    """
    rows = db_all(
        """
        SELECT c.id, c.order_id, o.order_code, c.buyer_id, u.name AS buyer_name,
               c.seller_id, us.name AS seller_name, c.created_at
        FROM conversations c
        LEFT JOIN orders o ON o.id=c.order_id
        LEFT JOIN users u ON u.id=c.buyer_id
        LEFT JOIN users us ON us.id=c.seller_id
        ORDER BY c.created_at DESC
        LIMIT 200
        """
    )
    convs = []
    for r in rows:
        convs.append({
            "id": int(_row_get(r, "id", 0) or 0),
            "order_id": int(_row_get(r, "order_id", 1) or 0),
            "order_code": _row_get(r, "order_code", 2),
            "buyer_name": _row_get(r, "buyer_name", 4),
            "seller_name": _row_get(r, "seller_name", 6),
            "created_at": _row_get(r, "created_at", 7),
        })

    return render_template("admin/chat_flags.html", conversations=convs, admin=current_admin())


@app.get("/superadmin/ledger")
@superadmin_required
def superadmin_escrow_ledger():
    """Finance ledger (read-only): payouts + orders snapshot.

    Notes:
      - No buttons inside the page (export is in left sidebar).
      - Uses payouts as the source of truth when available.
    """
    # Date range filters (human-friendly)
    rng = (request.args.get("range") or "30d").strip().lower()
    start_s = (request.args.get("start") or "").strip()
    end_s = (request.args.get("end") or "").strip()

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None

    now = datetime.utcnow()
    start_dt = None
    end_dt = None
    if rng in ("today", "1d"):
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        rng = "today"
    elif rng in ("7d", "week"):
        start_dt = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        rng = "7d"
    elif rng in ("30d", "month30"):
        start_dt = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        rng = "30d"
    elif rng in ("this_month", "month"):
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        rng = "month"
    elif rng in ("custom",):
        sdt = _parse_date(start_s)
        edt = _parse_date(end_s)
        if sdt:
            start_dt = sdt.replace(hour=0, minute=0, second=0, microsecond=0)
        if edt:
            end_dt = edt.replace(hour=23, minute=59, second=59, microsecond=0)

    # KPI summary (best-effort, schema-safe)
    paid_total = 0.0
    pending_total = 0.0
    commission_total = 0.0

    date_expr_summary = "COALESCE(paid_at, created_at)" if db_has_column('payouts','paid_at') else "created_at"
    date_where_summary = ""
    date_params_summary = []
    if start_dt and end_dt:
        end_next = (end_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_where_summary = f" AND {date_expr_summary} >= %s AND {date_expr_summary} < %s "
        date_params_summary = [start_dt, end_next]

    if db_has_table('payouts'):
        if db_has_column('payouts', 'net_payable'):
            r = db_one(
                f"SELECT COALESCE(SUM(net_payable),0) AS s FROM payouts WHERE status='paid' {date_where_summary}",
                tuple(date_params_summary),
            )
            paid_total = float(_row_get(r, 's', 0, 0) or 0)
            r = db_one(
                f"SELECT COALESCE(SUM(net_payable),0) AS s FROM payouts WHERE status='pending' {date_where_summary}",
                tuple(date_params_summary),
            )
            pending_total = float(_row_get(r, 's', 0, 0) or 0)
        if db_has_column('payouts', 'commission_amount'):
            r = db_one(
                f"SELECT COALESCE(SUM(commission_amount),0) AS s FROM payouts WHERE status='paid' {date_where_summary}",
                tuple(date_params_summary),
            )
            commission_total = float(_row_get(r, 's', 0, 0) or 0)

    # Ledger rows (payout-level)
    has_gross = db_has_column('payouts','gross_amount')
    has_comm = db_has_column('payouts','commission_amount')
    has_net = db_has_column('payouts','net_payable')
    has_method = db_has_column('payouts','payout_method')
    has_ref = db_has_column('payouts','payout_ref')
    has_paid_at = db_has_column('payouts','paid_at')

    gross_sel = 'p.gross_amount' if has_gross else 'NULL AS gross_amount'
    comm_sel = 'p.commission_amount' if has_comm else 'NULL AS commission_amount'
    net_sel = 'p.net_payable' if has_net else 'NULL AS net_payable'
    method_sel = 'p.payout_method' if has_method else "'' AS payout_method"
    ref_sel = 'p.payout_ref' if has_ref else "'' AS payout_ref"
    date_sel = 'COALESCE(p.paid_at, p.created_at)' if has_paid_at else 'p.created_at'

    date_where = ""
    date_params = []
    if start_dt and end_dt:
        # use next day for upper bound to keep SQL simple
        end_next = (end_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_where = f" AND {date_sel} >= %s AND {date_sel} < %s "
        date_params = [start_dt, end_next]

    ledger = []
    if db_has_table('payouts'):
        rows = db_all(
            f"""
            SELECT p.id AS payout_id,
                   {date_sel} AS entry_at,
                   p.status,
                   p.order_id,
                   o.order_code,
                   p.seller_id,
                   u.name AS seller_name,
                   u.email AS seller_email,
                   {gross_sel},
                   {comm_sel},
                   {net_sel},
                   {method_sel},
                   {ref_sel}
            FROM payouts p
            LEFT JOIN orders o ON o.id=p.order_id
            LEFT JOIN users u ON u.id=p.seller_id
            WHERE 1=1 {date_where}
            ORDER BY entry_at DESC, p.id DESC
            LIMIT 500
            """
        , tuple(date_params))
        for r in rows or []:
            ledger.append({
                'payout_id': int(_row_get(r,'payout_id',0) or 0),
                'entry_at': _row_get(r,'entry_at',1),
                'status': _row_get(r,'status',2),
                'order_id': _row_get(r,'order_id',3),
                'order_code': _row_get(r,'order_code',4),
                'seller_id': _row_get(r,'seller_id',5),
                'seller_name': _row_get(r,'seller_name',6),
                'seller_email': _row_get(r,'seller_email',7),
                'gross_amount': _row_get(r,'gross_amount',8),
                'commission_amount': _row_get(r,'commission_amount',9),
                'net_payable': _row_get(r,'net_payable',10),
                'payout_method': _row_get(r,'payout_method',11),
                'payout_ref': _row_get(r,'payout_ref',12),
            })

    # --- Format + adapt keys for template ---
    def _fmt_money(v):
        try:
            x = float(v or 0)
        except Exception:
            x = 0.0
        return f"{x:,.2f}"

    paid_gross = 0.0
    if db_has_table('payouts') and db_has_column('payouts', 'gross_amount'):
        r = db_one(
            f"SELECT COALESCE(SUM(gross_amount),0) AS s FROM payouts WHERE status='paid' {date_where_summary}",
            tuple(date_params_summary),
        )
        paid_gross = float(_row_get(r, 's', 0, 0) or 0)

    paid_cnt = 0
    pending_cnt = 0
    if db_has_table('payouts'):
        r = db_one(
            f"SELECT COUNT(*) AS c FROM payouts WHERE status='paid' {date_where_summary}",
            tuple(date_params_summary),
        )
        paid_cnt = int(_row_get(r, 'c', 0, 0) or 0)
        r = db_one(
            f"SELECT COUNT(*) AS c FROM payouts WHERE status='pending' {date_where_summary}",
            tuple(date_params_summary),
        )
        pending_cnt = int(_row_get(r, 'c', 0, 0) or 0)

    summary = {
        'pending_net': _fmt_money(pending_total),
        'paid_net': _fmt_money(paid_total),
        'paid_commission': _fmt_money(commission_total),
        'paid_gross': _fmt_money(paid_gross),
        'paid_count': paid_cnt,
        'pending_count': pending_cnt,
    }

    out = []
    for r in ledger:
        out.append({
            'date': r.get('entry_at'),
            'order_id': r.get('order_id'),
            'order_code': r.get('order_code'),
            'seller_name': r.get('seller_name'),
            'seller_email': r.get('seller_email'),
            'gross': _fmt_money(r.get('gross_amount')),
            'commission': _fmt_money(r.get('commission_amount')),
            'net': _fmt_money(r.get('net_payable')),
            'status': (r.get('status') or 'pending').title(),
        })

    def _dstr(dt):
        try:
            return dt.strftime("%Y-%m-%d") if dt else ""
        except Exception:
            return ""

    return render_template(
        'superadmin/ledger.html',
        summary=summary,
        ledger=out,
        admin=current_admin(),
        rng=rng,
        start=_dstr(start_dt),
        end=_dstr(end_dt),
    )


@app.get("/superadmin/reports/export")
@superadmin_required
def superadmin_export_reports():
    rtype = (request.args.get("type") or "").strip().lower()
    if rtype != "finance_csv":
        return ("Unknown export type", 400)

    rows = db_all(
        """
        SELECT o.order_code, o.created_at, o.grand_total, o.payment_method, o.trnx_id,
               o.payment_status, o.status
        FROM orders o
        ORDER BY o.created_at DESC
        LIMIT 5000
            """,
            tuple(date_params),
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["order_code", "created_at", "amount", "payment_method", "trx_id", "payment_status", "order_status"])
    for r in rows:
        writer.writerow([
            _row_get(r, "order_code", 0),
            _row_get(r, "created_at", 1),
            _row_get(r, "grand_total", 2),
            _row_get(r, "payment_method", 3),
            _row_get(r, "trnx_id", 4),
            _row_get(r, "payment_status", 5),
            _row_get(r, "status", 6),
        ])

    csv_data = output.getvalue()
    resp = make_response(csv_data)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=finance_report.csv"
    return resp

# -----------------------------
# Admin / SuperAdmin Profile
# -----------------------------
@app.get('/admin/profile')
@admin_required
def admin_profile_get():
    a = current_admin()
    if not a:
        return redirect('/admin/login')
    if (a.get('role') or '').lower() == 'superadmin':
        return redirect('/superadmin/profile')
    # refresh full row (admins table OR user-based admin)
    if (a.get('src') or '') == 'users':
        u = db_one('SELECT id,name,email,role,status,created_at,updated_at FROM users WHERE id=%s', (int(a.get('id')),))
        row = {
            'id': _row_get(u, 'id', 0) if u else a.get('id'),
            'name': _row_get(u, 'name', 1, a.get('name')) if u else a.get('name'),
            'email': _row_get(u, 'email', 2, a.get('email')) if u else a.get('email'),
            'role': (_row_get(u, 'role', 3, a.get('role')) if u else a.get('role')),
            'status': (_row_get(u, 'status', 4, 'active') if u else 'active'),
            # fields that exist on admins table but not users
            'phone': '',
            'address': '',
            'bio': '',
            'photo_url': '',
        }
    else:
        row = db_one('SELECT id,name,email,phone,address,bio,photo_url,role,status FROM admins WHERE id=%s', (int(a.get('id')),))
        # Ensure template never crashes
        if not row:
            row = {
                'id': a.get('id'), 'name': a.get('name'), 'email': a.get('email'),
                'phone': a.get('phone',''), 'address': a.get('address',''), 'bio': a.get('bio',''),
                'photo_url': a.get('photo_url',''), 'role': a.get('role','admin'), 'status': 'active'
            }
    return render_template('admin/profile.html', admin=current_admin(), row=row)


@app.post('/admin/profile')
@admin_required
def admin_profile_post():
    a = current_admin()
    if not a:
        return redirect('/admin/login')
    if (a.get('role') or '').lower() == 'superadmin':
        return redirect('/superadmin/profile')

    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    address = (request.form.get('address') or '').strip()
    bio = (request.form.get('bio') or '').strip()

    photo_url = None
    f = request.files.get('photo')
    if f and getattr(f,'filename',''):
        fn = secure_filename(f.filename)
        base, dot, ext = fn.rpartition('.')
        ext = (ext or '').lower()
        token = secrets.token_hex(6)
        out_name = f"admin_{int(a.get('id'))}_{token}.{ext}" if ext else f"admin_{int(a.get('id'))}_{token}"
        up_dir = os.path.join(app.root_path, 'static', 'uploads', 'admins')
        os.makedirs(up_dir, exist_ok=True)
        out_path = os.path.join(up_dir, out_name)
        f.save(out_path)
        photo_url = f"/static/uploads/admins/{out_name}"

    # Update based on where this admin account is stored
    if (a.get('src') or '') == 'users':
        # users table only has name (no phone/address/bio/photo)
        db_exec('UPDATE users SET name=%s WHERE id=%s', (name or a.get('name'), int(a.get('id'))))
    else:
        db_exec(
            'UPDATE admins SET name=%s, phone=%s, address=%s, bio=%s, photo_url=COALESCE(%s, photo_url) WHERE id=%s',
            (name or a.get('name'), phone, address, bio, photo_url, int(a.get('id'))),
        )
    return redirect('/admin/profile')


@app.get('/superadmin/profile')
@superadmin_required
def superadmin_profile_get():
    a = current_admin()
    if not a:
        return redirect('/admin/login')
    if (a.get('src') or '') == 'users':
        u = db_one('SELECT id,name,email,role,status FROM users WHERE id=%s', (int(a.get('id')),))
        row = {
            'id': _row_get(u, 'id', 0) if u else a.get('id'),
            'name': _row_get(u, 'name', 1, a.get('name')) if u else a.get('name'),
            'email': _row_get(u, 'email', 2, a.get('email')) if u else a.get('email'),
            'role': (_row_get(u, 'role', 3, a.get('role')) if u else a.get('role')),
            'status': (_row_get(u, 'status', 4, 'active') if u else 'active'),
            'phone': '', 'address': '', 'bio': '', 'photo_url': '',
        }
    else:
        row = db_one('SELECT id,name,email,phone,address,bio,photo_url,role,status FROM admins WHERE id=%s', (int(a.get('id')),))
        if not row:
            row = {
                'id': a.get('id'), 'name': a.get('name'), 'email': a.get('email'),
                'phone': a.get('phone',''), 'address': a.get('address',''), 'bio': a.get('bio',''),
                'photo_url': a.get('photo_url',''), 'role': a.get('role','superadmin'), 'status': 'active'
            }
    return render_template('superadmin/profile.html', admin=current_admin(), row=row)


@app.post('/superadmin/profile')
@superadmin_required
def superadmin_profile_post():
    a = current_admin()
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    address = (request.form.get('address') or '').strip()
    bio = (request.form.get('bio') or '').strip()

    # If this superadmin is stored in users table, only update the name.
    if (a.get('src') or '') == 'users':
        db_exec('UPDATE users SET name=%s WHERE id=%s', (name or a.get('name'), int(a.get('id'))))
        return redirect('/superadmin/profile')

    photo_url = None
    f = request.files.get('photo')
    if f and getattr(f,'filename',''):
        fn = secure_filename(f.filename)
        base, dot, ext = fn.rpartition('.')
        ext = (ext or '').lower()
        token = secrets.token_hex(6)
        out_name = f"superadmin_{int(a.get('id'))}_{token}.{ext}" if ext else f"superadmin_{int(a.get('id'))}_{token}"
        up_dir = os.path.join(app.root_path, 'static', 'uploads', 'admins')
        os.makedirs(up_dir, exist_ok=True)
        out_path = os.path.join(up_dir, out_name)
        f.save(out_path)
        photo_url = f"/static/uploads/admins/{out_name}"

    db_exec(
        'UPDATE admins SET name=%s, phone=%s, address=%s, bio=%s, photo_url=COALESCE(%s, photo_url) WHERE id=%s',
        (name or a.get('name'), phone, address, bio, photo_url, int(a.get('id'))),
    )
    return redirect('/superadmin/profile')


@app.post('/admin/profile/password')
@admin_required
def admin_profile_password_post():
    """Admin password change."""
    a = current_admin()
    if not a:
        return redirect('/admin/login')
    if (a.get('role') or '').lower() == 'superadmin':
        return redirect('/superadmin/profile')

    current_pw = (request.form.get('current_password') or '').strip()
    new_pw = (request.form.get('new_password') or '').strip()
    confirm_pw = (request.form.get('confirm_password') or '').strip()
    if not current_pw or not new_pw or new_pw != confirm_pw:
        return redirect('/admin/profile')

    if (a.get('src') or '') == 'users':
        row = db_one('SELECT password FROM users WHERE id=%s', (int(a.get('id')),))
        if not row or not check_password_hash(_row_get(row, 'password', 0, '') or '', current_pw):
            return redirect('/admin/profile')
        db_exec('UPDATE users SET password=%s WHERE id=%s', (generate_password_hash(new_pw), int(a.get('id'))))
        return redirect('/admin/profile')

    row = db_one('SELECT password FROM admins WHERE id=%s', (int(a.get('id')),))
    if not row or not check_password_hash(_row_get(row, 'password', 0, '') or '', current_pw):
        return redirect('/admin/profile')

    db_exec('UPDATE admins SET password=%s WHERE id=%s', (generate_password_hash(new_pw), int(a.get('id'))))
    return redirect('/admin/profile')


@app.post('/superadmin/profile/password')
@superadmin_required
def superadmin_profile_password_post():
    """Superadmin password change."""
    a = current_admin()
    if not a:
        return redirect('/admin/login')

    current_pw = (request.form.get('current_password') or '').strip()
    new_pw = (request.form.get('new_password') or '').strip()
    confirm_pw = (request.form.get('confirm_password') or '').strip()
    if not current_pw or not new_pw or new_pw != confirm_pw:
        return redirect('/superadmin/profile')

    if (a.get('src') or '') == 'users':
        row = db_one('SELECT password FROM users WHERE id=%s', (int(a.get('id')),))
        if not row or not check_password_hash(_row_get(row, 'password', 0, '') or '', current_pw):
            return redirect('/superadmin/profile')
        db_exec('UPDATE users SET password=%s WHERE id=%s', (generate_password_hash(new_pw), int(a.get('id'))))
        return redirect('/superadmin/profile')

    row = db_one('SELECT password FROM admins WHERE id=%s', (int(a.get('id')),))
    if not row or not check_password_hash(_row_get(row, 'password', 0, '') or '', current_pw):
        return redirect('/superadmin/profile')

    db_exec('UPDATE admins SET password=%s WHERE id=%s', (generate_password_hash(new_pw), int(a.get('id'))))
    return redirect('/superadmin/profile')


# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)