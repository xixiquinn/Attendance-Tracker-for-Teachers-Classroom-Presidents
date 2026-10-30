"""Attendance Tracker: Flask + Firebase Firestore, with blocks (sections).

Firestore layout (one private space per login):
  users/{username}/blocks/{blockId}                      -> {name}
  users/{username}/blocks/{blockId}/students/{id}        -> {name}
  users/{username}/blocks/{blockId}/attendance/{date}    -> {studentId: "P" | "A" | "L" | "E"}
  users/{username}/blocks/{blockId}/activities/{id}      -> {title, date, done: [studentId, ...]}
"""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import timedelta

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, g, jsonify, redirect, request, send_file, session

from export_xlsx import build_workbook, build_workbook_multi
from import_xlsx import parse_spreadsheet

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def init_db():
    raw = os.environ.get("FIREBASE_CREDENTIALS")  # service-account JSON text
    if raw:
        cred = credentials.Certificate(json.loads(raw))
    elif os.path.exists("serviceAccountKey.json"):  # local development
        cred = credentials.Certificate("serviceAccountKey.json")
    else:  # e.g. Google Cloud Run's built-in service account
        cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    return firestore.client()


db = init_db()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NAME_RE = re.compile(r"^[a-z0-9_.-]{1,40}$")
BID_RE = re.compile(r"^[a-z0-9-]{1,50}$")
AID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_BLOCKS = 30


# ---------------------------------------------------------------- logins
def load_users():
    """USERS="juan:pass1,maria:pass2" -> {"juan": "pass1", "maria": "pass2"}"""
    users = {}
    for pair in os.environ.get("USERS", "").split(","):
        if ":" in pair:
            name, pw = pair.split(":", 1)
            name, pw = name.strip().lower(), pw.strip()
            if NAME_RE.match(name) and pw:
                users[name] = pw
    return users


USERS = load_users()
SHARED_PASSWORD = os.environ.get("APP_PASSWORD")  # optional: one shared login
AUTH_ON = bool(USERS or SHARED_PASSWORD)


def _secret():
    """Key that signs the login cookie. Set SECRET_KEY to choose your own; otherwise it is
    derived from your settings, so it is the same on every server instance (needed on Vercel)."""
    explicit = os.environ.get("SECRET_KEY")
    if explicit:
        return explicit
    seed = "|".join(["attendance-tracker", os.environ.get("USERS", ""), SHARED_PASSWORD or "",
                     os.environ.get("FIREBASE_CREDENTIALS", "")])
    return hashlib.sha256(seed.encode()).hexdigest()


app.secret_key = _secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL") or os.environ.get("RENDER")
                               or os.environ.get("FORCE_HTTPS")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
PUBLIC = {"/login", "/api/login", "/manifest.json", "/icon-180.png", "/icon-192.png", "/icon-512.png"}


def _fingerprint(name, password):
    """Ties a login cookie to the current password: change it or remove the user and the cookie stops working."""
    return hmac.new(app.secret_key.encode(), f"{name}:{password}".encode(), hashlib.sha256).hexdigest()[:20]


def current_user():
    if not AUTH_ON:
        return "local"  # no login configured (local testing only)
    name, fp = session.get("u"), session.get("k")
    if not name or not fp:
        return None
    password = USERS.get(name) if USERS else (SHARED_PASSWORD if name == "shared" else None)
    if password and hmac.compare_digest(str(fp), _fingerprint(name, password)):
        return name
    return None


@app.before_request
def require_login():
    g.user = current_user()
    if g.user or request.path in PUBLIC:
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Please log in."), 401
    return redirect("/login")


@app.get("/login")
def login_page():
    if g.user:
        return redirect("/")
    return app.send_static_file("login.html")


@app.post("/api/login")
def login():
    if not AUTH_ON:
        return jsonify(ok=True, user="local")
    body = request.get_json(silent=True) or {}
    name = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    user = None
    if USERS:
        expected = USERS.get(name)
        if expected and hmac.compare_digest(expected.encode(), password.encode()):
            user = name
    elif hmac.compare_digest(SHARED_PASSWORD.encode(), password.encode()):
        user = "shared"
    if not user:
        time.sleep(0.6)  # slows down password guessing
        return jsonify(error="Wrong username or password."), 401
    session.clear()
    session.permanent = True
    session["u"] = user
    session["k"] = _fingerprint(user, USERS[user] if USERS else SHARED_PASSWORD)
    return jsonify(ok=True, user=user)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


def user_doc():
    return db.collection("users").document(g.user)


def blocks_ref():
    return user_doc().collection("blocks")


# ---------------------------------------------------------------- helpers
def commit_ops(ops):
    """ops: [("set", ref, data) | ("delete", ref, None)], in batches (Firestore max 500)."""
    for i in range(0, len(ops), 400):
        batch = db.batch()
        for kind, ref, data in ops[i:i + 400]:
            batch.set(ref, data) if kind == "set" else batch.delete(ref)
        batch.commit()


def replace_collection(ref, new_docs):
    """Make the collection equal to new_docs ({doc_id: data}); only changed docs are written."""
    old = {d.id: d.to_dict() for d in ref.stream()}
    ops = [("set", ref.document(k), v) for k, v in new_docs.items() if old.get(k) != v]
    ops += [("delete", ref.document(k), None) for k in old.keys() - new_docs.keys()]
    commit_ops(ops)


def sort_key(s):
    return (0, int(s["id"]), "") if s["id"].isdigit() else (1, 0, s["id"])


def slugify(name):
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "block")[:40]


def unique_id(name, taken):
    base, bid, n = slugify(name), slugify(name), 2
    while bid in taken:
        bid, n = f"{base}-{n}", n + 1
    return bid


def clean_name(body):
    name = str((body or {}).get("name", "")).strip()
    return name if 1 <= len(name) <= 40 else None


def list_blocks():
    docs = list(blocks_ref().stream())
    if not docs:  # first use: create Block A-E
        ops = [("set", blocks_ref().document(f"block-{c.lower()}"), {"name": f"Block {c}"})
               for c in "ABCDE"]
        first = blocks_ref().document("block-a")  # move older single-class data into Block A
        for coll in ("students", "attendance"):
            for d in user_doc().collection(coll).stream():
                ops.append(("set", first.collection(coll).document(d.id), d.to_dict()))
                ops.append(("delete", d.reference, None))
        commit_ops(ops)
        docs = list(blocks_ref().stream())
    blocks = [{"id": d.id, "name": d.to_dict().get("name", d.id)} for d in docs]
    blocks.sort(key=lambda b: b["name"].lower())
    return blocks


def block_ref(bid):
    if BID_RE.match(bid):
        ref = blocks_ref().document(bid)
        if ref.get().exists:
            return ref
    return None


def load_block(ref):
    students = [{"id": d.id, "name": d.to_dict().get("name", "")}
                for d in ref.collection("students").stream()]
    students.sort(key=sort_key)
    records = {d.id: d.to_dict() for d in ref.collection("attendance").stream()}
    activities = []
    for d in ref.collection("activities").stream():
        x = d.to_dict()
        activities.append({"id": d.id, "title": x.get("title", ""), "date": x.get("date", ""),
                           "done": list(x.get("done", []))})
    activities.sort(key=lambda a: (a["date"] or "9999-99-99", a["title"].lower()))
    return students, records, activities


def clean_activities(raw, student_ids):
    """Validate the activity list; returns {id: doc} or None when the client sent none."""
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > 300:
        raise ValueError("bad activities")
    out = {}
    for a in raw:
        if not isinstance(a, dict):
            raise ValueError("bad activity")
        aid = str(a.get("id", "")).strip()
        title = str(a.get("title", "")).strip()[:80]
        date = str(a.get("date") or "")
        if not AID_RE.match(aid) or not title or (date and not DATE_RE.match(date)):
            raise ValueError(f"invalid activity: {title!r}")
        done = a.get("done") if isinstance(a.get("done"), list) else []
        out[aid] = {"title": title, "date": date,
                    "done": sorted({str(x) for x in done if str(x) in student_ids})}
    return out


def not_found():
    return jsonify(error="Block not found."), 404


# ---------------------------------------------------------------- pages / blocks
@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/blocks")
def get_blocks():
    return jsonify(user=g.user, blocks=list_blocks())


@app.post("/api/blocks")
def add_block():
    name = clean_name(request.get_json(silent=True))
    if not name:
        return jsonify(error="Enter a block name (1 to 40 characters)."), 400
    existing = list_blocks()
    if len(existing) >= MAX_BLOCKS:
        return jsonify(error=f"You can have at most {MAX_BLOCKS} blocks."), 400
    if any(b["name"].lower() == name.lower() for b in existing):
        return jsonify(error="A block with that name already exists."), 400
    bid = unique_id(name, {b["id"] for b in existing})
    blocks_ref().document(bid).set({"name": name})
    return jsonify(id=bid, name=name)


@app.patch("/api/blocks/<bid>")
def rename_block(bid):
    ref = block_ref(bid)
    if not ref:
        return not_found()
    name = clean_name(request.get_json(silent=True))
    if not name:
        return jsonify(error="Enter a block name (1 to 40 characters)."), 400
    if any(b["name"].lower() == name.lower() and b["id"] != bid for b in list_blocks()):
        return jsonify(error="A block with that name already exists."), 400
    ref.set({"name": name})
    return jsonify(id=bid, name=name)


@app.delete("/api/blocks/<bid>")
def delete_block(bid):
    ref = block_ref(bid)
    if not ref:
        return not_found()
    if len(list_blocks()) <= 1:
        return jsonify(error="You must keep at least one block."), 400
    ops = []
    for coll in ("students", "attendance", "activities"):
        ops += [("delete", d, None) for d in ref.collection(coll).list_documents()]
    ops.append(("delete", ref, None))
    commit_ops(ops)
    return jsonify(ok=True)


# ---------------------------------------------------------------- block data
@app.get("/api/blocks/<bid>/data")
def get_data(bid):
    ref = block_ref(bid)
    if not ref:
        return not_found()
    students, records, activities = load_block(ref)
    return jsonify(students=students, records=records, activities=activities)


@app.put("/api/blocks/<bid>/data")
def put_data(bid):
    ref = block_ref(bid)
    if not ref:
        return not_found()
    body = request.get_json(silent=True) or {}
    students, records = body.get("students"), body.get("records")
    if not isinstance(students, list) or not isinstance(records, dict):
        return jsonify(error="bad payload"), 400

    student_docs = {}
    for s in students:
        sid, name = str(s.get("id", "")).strip(), str(s.get("name", "")).strip()
        if not sid or not name or "/" in sid or sid in (".", ".."):
            return jsonify(error=f"invalid student: {sid!r}"), 400
        student_docs[sid] = {"name": name}

    record_docs = {}
    for day, marks in records.items():
        if not DATE_RE.match(day) or not isinstance(marks, dict):
            return jsonify(error=f"invalid date: {day!r}"), 400
        clean = {k: v for k, v in marks.items() if k in student_docs and v in "PALE" and len(v) == 1}
        if clean:
            record_docs[day] = clean

    try:
        activity_docs = clean_activities(body.get("activities"), set(student_docs))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    replace_collection(ref.collection("students"), student_docs)
    replace_collection(ref.collection("attendance"), record_docs)
    if activity_docs is not None:  # older pages that don't send activities leave them alone
        replace_collection(ref.collection("activities"), activity_docs)
    return jsonify(ok=True)


# ---------------------------------------------------------------- spreadsheets
@app.get("/api/blocks/<bid>/export.xlsx")
def export_block(bid):
    ref = block_ref(bid)
    if not ref:
        return not_found()
    students, records, activities = load_block(ref)
    name = ref.get().to_dict().get("name", bid)
    return send_file(build_workbook(students, records, name, activities), as_attachment=True,
                     download_name=f"attendance-{bid}.xlsx", mimetype=XLSX)


@app.get("/api/export-all.xlsx")
def export_all():
    items = []
    for b in list_blocks():
        students, records, activities = load_block(blocks_ref().document(b["id"]))
        items.append((b["name"], students, records, activities))
    return send_file(build_workbook_multi(items), as_attachment=True,
                     download_name="attendance-all-blocks.xlsx", mimetype=XLSX)


@app.post("/api/parse-import")
def parse_import():
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file received."), 400
    try:
        return jsonify(parse_spreadsheet(f.read(), f.filename or ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="Could not read that file. Please use .xlsx or .csv."), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
