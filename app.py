import sqlite3
import os
from functools import wraps
from datetime import datetime, date, timezone, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, g, jsonify, abort, session
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "thesis-workflow-secret-key")
app.permanent_session_lifetime = timedelta(days=30)

DATABASE = os.environ.get(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "thesis.db"),
)

# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------
THESIS_STATUSES = [
    "Draft", "Submitted", "UnderReview", "ExternallyReviewed",
    "RevisionRequested", "Approved", "FinalSubmitted", "Completed", "Late",
    "Cancelled",
]

THESIS_TRANSITIONS = {
    "Draft":               ["Submitted", "Cancelled"],
    "Submitted":           ["UnderReview", "ExternallyReviewed", "Cancelled"],
    "UnderReview":         ["RevisionRequested", "Approved", "Cancelled"],
    "ExternallyReviewed":  ["Approved", "Cancelled"],
    "RevisionRequested":   ["Submitted", "Cancelled"],
    "Approved":            ["FinalSubmitted"],
    "FinalSubmitted":      ["Completed"],
    "Completed":           [],
    "Late":                ["Cancelled"],
    "Cancelled":           [],
}

COMMITTEE_DECISIONS = ["Approve", "Reject", "Minor Revision"]

MILESTONE_STATUSES = ["Planned", "InProgress", "Submitted", "Accepted"]

MILESTONE_TRANSITIONS = {
    "Planned":    ["InProgress"],
    "InProgress": ["Submitted"],
    "Submitted":  ["Accepted", "InProgress"],
    "Accepted":   [],
}

SUBMISSION_KINDS = ["proposal", "interim", "final"]

# ---------------------------------------------------------------------------
# Thesis status classification for dashboards (Part D)
# ---------------------------------------------------------------------------
ONGOING_STATUSES = {"Draft", "Submitted", "UnderReview", "ExternallyReviewed",
                    "RevisionRequested", "Late"}
TERMINATED_STATUSES = {"Approved", "FinalSubmitted", "Completed"}
STOPPED_STATUSES = {"Cancelled"}

# ---------------------------------------------------------------------------
# Topic taxonomy (30 topics from ONGOING3 workbook)
# ---------------------------------------------------------------------------
TOPIC_TAXONOMY = [
    "Advanced data management", "Blockchain", "Business Analytics",
    "Computer Graphics and Augmented Reality", "Computer Science Education",
    "Computer Security", "Cutting edge technologies for software development",
    "Data protection and privacy", "Data visualisation", "Data warehousing",
    "Development methods and their applications", "Distributed computing",
    "Formal methods", "Geometric modeling", "High performance computing",
    "Human Computer Interaction", "Image processing and computer vision",
    "Internet of Things", "Large-scale computing", "Machine learning",
    "Methods and techniques for high-quality system development",
    "Mobile development", "Multi-agent systems", "Natural language processing",
    "Network analysis", "Principles and paradigms of programming languages",
    "Software engineering", "Software quality assurance",
    "Software systems design and modelling", "Speech processing and recognition",
]

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    db.commit()
    db.close()


def migrate_db():
    """Add columns/tables that may be missing from an older schema."""
    db = sqlite3.connect(DATABASE)
    cols = [row[1] for row in db.execute("PRAGMA table_info(thesis)").fetchall()]
    if "external_reviewer_id" not in cols:
        db.execute("ALTER TABLE thesis ADD COLUMN external_reviewer_id INTEGER REFERENCES external_reviewer(id)")
    if "submission_deadline" not in cols:
        db.execute("ALTER TABLE thesis ADD COLUMN submission_deadline TEXT")
    # Ensure new tables exist (idempotent via IF NOT EXISTS in SCHEMA, but
    # re-run the full schema script to pick up any new CREATE TABLE statements)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS committee_member (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS thesis_committee (
            thesis_id           INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
            committee_member_id INTEGER NOT NULL REFERENCES committee_member(id) ON DELETE CASCADE,
            PRIMARY KEY (thesis_id, committee_member_id)
        );
        CREATE TABLE IF NOT EXISTS decision_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            thesis_id           INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
            committee_member_id INTEGER NOT NULL REFERENCES committee_member(id),
            decision            TEXT NOT NULL,
            comment             TEXT,
            created_at          TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            role  TEXT NOT NULL CHECK(role IN ('Admin', 'Professor', 'Student'))
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            title                   TEXT NOT NULL,
            description             TEXT,
            created_by_professor_id INTEGER NOT NULL REFERENCES users(id),
            status                  TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Published','Archived')),
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bidding_rounds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date   TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'Planned' CHECK(status IN ('Planned','Open','Closed')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bid_groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id),
            round_id   INTEGER NOT NULL REFERENCES bidding_rounds(id),
            status     TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Assigned','Rejected')),
            motivation_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(round_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS bids (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bid_group_id    INTEGER REFERENCES bid_groups(id),
            proposal_id     INTEGER NOT NULL REFERENCES proposals(id),
            student_id      INTEGER NOT NULL REFERENCES users(id),
            round_id        INTEGER NOT NULL REFERENCES bidding_rounds(id),
            rank            INTEGER NOT NULL DEFAULT 1,
            motivation_text TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Accepted','Rejected')),
            created_at      TEXT NOT NULL,
            UNIQUE(round_id, proposal_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS assignments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id    INTEGER NOT NULL REFERENCES bidding_rounds(id),
            proposal_id INTEGER NOT NULL REFERENCES proposals(id),
            bid_id      INTEGER NOT NULL REFERENCES bids(id),
            student_id  INTEGER NOT NULL REFERENCES users(id),
            thesis_id   INTEGER NOT NULL REFERENCES thesis(thesis_id),
            assigned_by INTEGER NOT NULL REFERENCES users(id),
            assigned_at TEXT NOT NULL,
            UNIQUE(round_id, proposal_id)
        );
        CREATE TABLE IF NOT EXISTS proposal_rounds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER NOT NULL REFERENCES proposals(id),
            round_id    INTEGER NOT NULL REFERENCES bidding_rounds(id),
            added_by    INTEGER NOT NULL REFERENCES users(id),
            added_at    TEXT NOT NULL,
            UNIQUE(proposal_id, round_id)
        );
    """)
    # Migrate bids: add round_id column if missing, backfill with most recent round
    bid_cols = [row[1] for row in db.execute("PRAGMA table_info(bids)").fetchall()]
    if "round_id" not in bid_cols:
        db.execute("ALTER TABLE bids ADD COLUMN round_id INTEGER REFERENCES bidding_rounds(id)")
        fallback_round = db.execute(
            "SELECT id FROM bidding_rounds ORDER BY "
            "CASE status WHEN 'Open' THEN 0 WHEN 'Closed' THEN 1 ELSE 2 END, "
            "created_at DESC LIMIT 1"
        ).fetchone()
        if fallback_round:
            db.execute("UPDATE bids SET round_id = ? WHERE round_id IS NULL", (fallback_round[0],))
    if "status" not in bid_cols:
        db.execute("ALTER TABLE bids ADD COLUMN status TEXT NOT NULL DEFAULT 'Pending'")
    if "rank" not in bid_cols:
        db.execute("ALTER TABLE bids ADD COLUMN rank INTEGER NOT NULL DEFAULT 1")
    if "bid_group_id" not in bid_cols:
        db.execute("ALTER TABLE bids ADD COLUMN bid_group_id INTEGER REFERENCES bid_groups(id)")

    # Ensure bid_groups table exists
    db.execute("""CREATE TABLE IF NOT EXISTS bid_groups (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES users(id),
        round_id   INTEGER NOT NULL REFERENCES bidding_rounds(id),
        status     TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Assigned','Rejected')),
        motivation_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(round_id, student_id)
    )""")

    # Migrate thesis: add ER-6 columns
    thesis_cols = [row[1] for row in db.execute("PRAGMA table_info(thesis)").fetchall()]
    new_thesis_cols = [
        ("is_challenging", "INTEGER DEFAULT 0"),
        ("is_external", "INTEGER DEFAULT 0"),
        ("external_supervisor_name", "TEXT"),
        ("additional_supervisor_id", "INTEGER"),
        ("primary_topic", "TEXT"),
        ("secondary_topic", "TEXT"),
        ("start_date", "TEXT"),
        ("expected_end", "TEXT"),
        ("terminated_at", "TEXT"),
        ("three_month_review_done", "INTEGER DEFAULT 0"),
        ("assignment_source", "TEXT"),
        ("notes", "TEXT"),
        ("reviewer_id", "INTEGER"),
    ]
    for col_name, col_type in new_thesis_cols:
        if col_name not in thesis_cols:
            db.execute(f"ALTER TABLE thesis ADD COLUMN {col_name} {col_type}")

    # Migrate users: add password_hash
    user_cols = [row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "password_hash" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    # Ensure topics table exists and is seeded
    db.execute("""CREATE TABLE IF NOT EXISTS topics (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )""")
    existing_topics = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    if existing_topics == 0:
        for topic in TOPIC_TAXONOMY:
            db.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (topic,))

    # Migrate bidding_rounds: add proposal_collection_end
    round_cols = [row[1] for row in db.execute("PRAGMA table_info(bidding_rounds)").fetchall()]
    if "proposal_collection_end" not in round_cols:
        db.execute("ALTER TABLE bidding_rounds ADD COLUMN proposal_collection_end TEXT")

    db.commit()
    db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS student (
    student_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS supervisor (
    supervisor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    department    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_reviewer (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS committee_member (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS thesis (
    thesis_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    abstract             TEXT,
    student_id           INTEGER NOT NULL REFERENCES student(student_id),
    supervisor_id        INTEGER REFERENCES supervisor(supervisor_id),
    external_reviewer_id INTEGER REFERENCES external_reviewer(id),
    submission_deadline  TEXT,
    status               TEXT NOT NULL DEFAULT 'Draft',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis_committee (
    thesis_id           INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
    committee_member_id INTEGER NOT NULL REFERENCES committee_member(id) ON DELETE CASCADE,
    PRIMARY KEY (thesis_id, committee_member_id)
);

CREATE TABLE IF NOT EXISTS decision_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id           INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
    committee_member_id INTEGER NOT NULL REFERENCES committee_member(id),
    decision            TEXT NOT NULL,
    comment             TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS milestone (
    milestone_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id     INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
    type          TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Planned',
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS submission (
    submission_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id            INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
    kind                 TEXT NOT NULL,
    submitted_at         TEXT NOT NULL,
    comment              TEXT,
    attachment_path_or_url TEXT
);

CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id   INTEGER NOT NULL REFERENCES thesis(thesis_id) ON DELETE CASCADE,
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    changed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role  TEXT NOT NULL CHECK(role IN ('Admin', 'Professor', 'Student'))
);

CREATE TABLE IF NOT EXISTS proposals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT NOT NULL,
    description             TEXT,
    created_by_professor_id INTEGER NOT NULL REFERENCES users(id),
    status                  TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Published','Archived')),
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bidding_rounds (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    start_date              TEXT NOT NULL,
    end_date                TEXT NOT NULL,
    proposal_collection_end TEXT,
    status                  TEXT NOT NULL DEFAULT 'Planned' CHECK(status IN ('Planned','Open','Closed')),
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bid_groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    round_id   INTEGER NOT NULL REFERENCES bidding_rounds(id),
    status     TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Assigned','Rejected')),
    motivation_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(round_id, student_id)
);

CREATE TABLE IF NOT EXISTS bids (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bid_group_id    INTEGER REFERENCES bid_groups(id),
    proposal_id     INTEGER NOT NULL REFERENCES proposals(id),
    student_id      INTEGER NOT NULL REFERENCES users(id),
    round_id        INTEGER NOT NULL REFERENCES bidding_rounds(id),
    rank            INTEGER NOT NULL DEFAULT 1,
    motivation_text TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Accepted','Rejected')),
    created_at      TEXT NOT NULL,
    UNIQUE(round_id, proposal_id, student_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id    INTEGER NOT NULL REFERENCES bidding_rounds(id),
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    bid_id      INTEGER NOT NULL REFERENCES bids(id),
    student_id  INTEGER NOT NULL REFERENCES users(id),
    thesis_id   INTEGER NOT NULL REFERENCES thesis(thesis_id),
    assigned_by INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    UNIQUE(round_id, proposal_id)
);

CREATE TABLE IF NOT EXISTS proposal_rounds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    round_id    INTEGER NOT NULL REFERENCES bidding_rounds(id),
    added_by    INTEGER NOT NULL REFERENCES users(id),
    added_at    TEXT NOT NULL,
    UNIQUE(proposal_id, round_id)
);

CREATE TABLE IF NOT EXISTS topics (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
@app.context_processor
def inject_helpers():
    return dict(
        thesis_statuses=THESIS_STATUSES,
        thesis_transitions=THESIS_TRANSITIONS,
        milestone_statuses=MILESTONE_STATUSES,
        milestone_transitions=MILESTONE_TRANSITIONS,
        submission_kinds=SUBMISSION_KINDS,
        committee_decisions=COMMITTEE_DECISIONS,
        topic_taxonomy=TOPIC_TAXONOMY,
        today=date.today().isoformat(),
        now=lambda: datetime.now(timezone.utc),
    )


@app.context_processor
def inject_current_user():
    user = None
    if "user_id" in session:
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return dict(current_user=user)


def get_current_user():
    """Return the current logged-in user row, or None."""
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def get_open_round():
    """Return the currently Open bidding round, or None."""
    db = get_db()
    return db.execute("SELECT * FROM bidding_rounds WHERE status = 'Open' LIMIT 1").fetchone()


def get_round_phase(rnd):
    """Determine the current phase of a bidding round.
    Returns: 'proposal_collection', 'bidding', or None.
    """
    if not rnd or rnd["status"] != "Open":
        return None
    today_str = date.today().isoformat()
    pce = rnd["proposal_collection_end"]
    if pce and today_str <= pce:
        return "proposal_collection"
    return "bidding"


# ---------------------------------------------------------------------------
# Analytics helpers (ER-6)
# ---------------------------------------------------------------------------
def _compute_faculty_effort(db, user_filter_id=None, status_set=None):
    """Compute faculty effort table.
    status_set: 'ongoing', 'terminated', or None (all).
    user_filter_id: filter to single professor.
    """
    if status_set == "ongoing":
        status_clause = "AND t.status IN ('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late')"
    elif status_set == "terminated":
        status_clause = "AND t.status IN ('Approved','FinalSubmitted','Completed')"
    else:
        status_clause = ""

    prof_clause = ""
    params = []
    if user_filter_id:
        prof_clause = "AND u.id = ?"
        params = [user_filter_id]

    query = f"""
        SELECT u.id, u.name,
            SUM(CASE WHEN sup.email = u.email THEN 1 ELSE 0 END) AS primary_sup,
            SUM(CASE WHEN t.additional_supervisor_id = u.id THEN 1 ELSE 0 END) AS additional_sup,
            SUM(CASE WHEN sup.email = u.email OR t.additional_supervisor_id = u.id THEN 1 ELSE 0 END) AS supervisor,
            SUM(CASE WHEN sup.email = u.email AND COALESCE(t.is_challenging, 0) = 0 THEN 1 ELSE 0 END) AS primary_senza,
            SUM(CASE WHEN t.additional_supervisor_id = u.id AND COALESCE(t.is_challenging, 0) = 0 THEN 1 ELSE 0 END) AS additional_senza,
            SUM(CASE WHEN (sup.email = u.email OR t.additional_supervisor_id = u.id) AND COALESCE(t.is_challenging, 0) = 0 THEN 1 ELSE 0 END) AS supervisor_senza,
            (SELECT COUNT(*) FROM thesis t2 WHERE t2.reviewer_id = u.id {status_clause.replace('t.', 't2.')}) AS correlazioni
        FROM users u
        LEFT JOIN supervisor sup ON sup.email = u.email
        LEFT JOIN thesis t ON (t.supervisor_id = sup.supervisor_id OR t.additional_supervisor_id = u.id) {status_clause}
        WHERE u.role = 'Professor' {prof_clause}
        GROUP BY u.id, u.name
        ORDER BY u.name
    """
    rows = db.execute(query, params).fetchall()
    result = []
    for r in rows:
        ps = r["primary_sup"] or 0
        ad = r["additional_sup"] or 0
        co = r["correlazioni"] or 0
        effort = ps * 2.0 + ad * 1.0 + co * 0.3
        result.append({
            "name": r["name"],
            "primary_sup": ps,
            "additional_sup": ad,
            "supervisor": r["supervisor"] or 0,
            "primary_senza": r["primary_senza"] or 0,
            "additional_senza": r["additional_senza"] or 0,
            "supervisor_senza": r["supervisor_senza"] or 0,
            "correlazioni": co,
            "effort": round(effort, 2),
        })
    return result


def _compute_summary_stats(db, professor_id=None, status_set=None):
    """Compute summary statistics (external %, challenging %, etc.)."""
    if status_set == "ongoing":
        where = "WHERE status IN ('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late')"
    elif status_set == "terminated":
        where = "WHERE status IN ('Approved','FinalSubmitted','Completed')"
    else:
        where = "WHERE 1=1"

    if professor_id:
        where += f" AND thesis_id IN (SELECT a.thesis_id FROM assignments a JOIN proposals p ON a.proposal_id = p.id WHERE p.created_by_professor_id = {int(professor_id)})"

    row = db.execute(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(is_external, 0) = 1 THEN 1 ELSE 0 END) AS external_count,
            SUM(CASE WHEN COALESCE(is_challenging, 0) = 1 THEN 1 ELSE 0 END) AS challenging_count,
            SUM(CASE WHEN COALESCE(is_challenging, 0) = 0 THEN 1 ELSE 0 END) AS not_challenging_count
        FROM thesis {where}
    """).fetchone()
    total = row["total"] or 0
    ext = row["external_count"] or 0
    ch = row["challenging_count"] or 0
    nch = row["not_challenging_count"] or 0
    bidding_count = db.execute(f"""
        SELECT COUNT(*) AS c FROM thesis
        {where} AND thesis_id IN (SELECT thesis_id FROM assignments)
    """).fetchone()["c"]
    return {
        "total": total,
        "external_count": ext,
        "external_pct": round(100.0 * ext / total, 2) if total else 0,
        "challenging_count": ch,
        "challenging_pct": round(100.0 * ch / total, 2) if total else 0,
        "not_challenging_count": nch,
        "not_challenging_pct": round(100.0 * nch / total, 2) if total else 0,
        "via_bidding": bidding_count,
    }


def format_date_mmm_yy(date_str):
    """Convert YYYY-MM-DD to mmm-YY format like 'dic-23', 'mar-25'."""
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        month_names = {
            1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
            7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"
        }
        return f"{month_names[d.month]}-{d.strftime('%y')}"
    except (ValueError, KeyError):
        return date_str[:10] if date_str else ""


app.jinja_env.filters["mmm_yy"] = format_date_mmm_yy
app.jinja_env.filters["word_count"] = lambda s: len(s.split()) if s else 0


def duration_months(start_str, end_str=None):
    """Compute duration in months between two dates."""
    if not start_str:
        return ""
    try:
        start = datetime.strptime(start_str[:10], "%Y-%m-%d")
        end = datetime.strptime(end_str[:10], "%Y-%m-%d") if end_str else datetime.now()
        return max(0, round((end - start).days / 30.0))
    except ValueError:
        return ""


app.jinja_env.filters["duration_months"] = lambda start, end=None: duration_months(start, end)
app.jinja_env.filters["duration_days"] = lambda start, end: (datetime.strptime(end[:10], "%Y-%m-%d") - datetime.strptime(start[:10], "%Y-%m-%d")).days if start and end else ""


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------
ROLE_HIERARCHY = {"Admin": 3, "Professor": 2, "Student": 1}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(role_name):
    """Allow access only if the logged-in user's role is >= the required role."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in to access this page.", "danger")
                return redirect(url_for("login"))
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            if not user or ROLE_HIERARCHY.get(user["role"], 0) < ROLE_HIERARCHY.get(role_name, 99):
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ---------------------------------------------------------------------------
# Routes – Auth
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        remember = request.form.get("remember")
        if email and password:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                if remember:
                    session.permanent = True
                flash(f"Logged in as {user['name']} ({user['role']}).", "success")
                return redirect(url_for("dashboard"))
            flash("Invalid email or password.", "danger")
        else:
            flash("Email and password are required.", "danger")
    db = get_db()
    users = db.execute("SELECT id, name, email, role FROM users ORDER BY role, name").fetchall()
    return render_template("login.html", users=users)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes – Admin (placeholder)
# ---------------------------------------------------------------------------
@app.route("/admin")
@role_required("Admin")
def admin_panel():
    return render_template("admin.html")

# ---------------------------------------------------------------------------
# Auto-Late enforcement
# ---------------------------------------------------------------------------
NON_LATE_TERMINAL = {"Approved", "FinalSubmitted", "Completed", "Late"}

@app.before_request
def enforce_deadlines():
    """Mark overdue theses as Late automatically."""
    db = get_db()
    today = date.today().isoformat()
    overdue = db.execute(
        "SELECT thesis_id, status FROM thesis "
        "WHERE submission_deadline IS NOT NULL AND submission_deadline < ? "
        "AND status NOT IN ('Approved','FinalSubmitted','Completed','Late')",
        (today,),
    ).fetchall()
    if overdue:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        for t in overdue:
            db.execute("UPDATE thesis SET status='Late', updated_at=? WHERE thesis_id=?",
                       (now, t["thesis_id"]))
            db.execute(
                "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
                "VALUES (?, ?, 'Late', ?)", (t["thesis_id"], t["status"], now),
            )
        db.commit()

# ---------------------------------------------------------------------------
# Routes – Dashboard (role-specific)
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    user = get_current_user()
    if user["role"] == "Student":
        return _student_dashboard(user)
    elif user["role"] == "Professor":
        return _professor_dashboard(user)
    else:
        return _admin_dashboard(user)


def _student_dashboard(user):
    db = get_db()
    # My theses (via assignments) with full detail
    my_theses = db.execute(
        "SELECT t.*, s.name AS student_name, "
        "COALESCE(sup.name, '—') AS supervisor_name, "
        "sup.email AS supervisor_email, "
        "rv.name AS reviewer_name, "
        "asup.name AS additional_supervisor_name "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
        "LEFT JOIN users rv ON t.reviewer_id = rv.id "
        "LEFT JOIN users asup ON t.additional_supervisor_id = asup.id "
        "JOIN assignments a ON a.thesis_id = t.thesis_id "
        "WHERE a.student_id = ? ORDER BY t.updated_at DESC",
        (user["id"],),
    ).fetchall()
    # My bids
    bids = db.execute(
        "SELECT b.*, p.title AS proposal_title, p.status AS proposal_status, "
        "u.name AS professor_name, "
        "br.name AS round_name, br.status AS round_status "
        "FROM bids b "
        "JOIN proposals p ON b.proposal_id = p.id "
        "JOIN users u ON p.created_by_professor_id = u.id "
        "JOIN bidding_rounds br ON b.round_id = br.id "
        "WHERE b.student_id = ? ORDER BY br.created_at DESC, b.created_at DESC",
        (user["id"],),
    ).fetchall()
    # Available proposals (published, not already assigned, in open round)
    open_round = get_open_round()
    available = []
    if open_round:
        available = db.execute(
            "SELECT p.*, u.name AS professor_name, p.description AS abstract, "
            "EXISTS(SELECT 1 FROM bids WHERE proposal_id = p.id "
            "  AND student_id = ? AND round_id = ?) AS already_bid "
            "FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE p.status = 'Published' "
            "AND NOT EXISTS (SELECT 1 FROM assignments WHERE proposal_id = p.id) "
            "ORDER BY p.updated_at DESC",
            (user["id"], open_round["id"]),
        ).fetchall()
    # Current bid group status
    bid_group = None
    bid_group_bids = []
    if open_round:
        bid_group = db.execute(
            "SELECT * FROM bid_groups WHERE student_id = ? AND round_id = ?",
            (user["id"], open_round["id"]),
        ).fetchone()
    # Also check closed rounds for recent results
    if not bid_group:
        bid_group = db.execute(
            "SELECT bg.*, br.name AS round_name, br.status AS round_status "
            "FROM bid_groups bg "
            "JOIN bidding_rounds br ON bg.round_id = br.id "
            "WHERE bg.student_id = ? AND bg.status != 'Pending' "
            "ORDER BY bg.created_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    if bid_group:
        bid_group_bids = db.execute(
            "SELECT b.*, p.title AS proposal_title, u.name AS professor_name "
            "FROM bids b "
            "JOIN proposals p ON b.proposal_id = p.id "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE b.bid_group_id = ? ORDER BY b.rank",
            (bid_group["id"],),
        ).fetchall()
    round_phase = get_round_phase(open_round) if open_round else None
    return render_template("dashboard_student.html",
                           my_theses=my_theses, bids=bids,
                           available=available, open_round=open_round,
                           round_phase=round_phase,
                           bid_group=bid_group, bid_group_bids=bid_group_bids)


def _professor_dashboard(user):
    db = get_db()
    # My proposals with bid counts
    proposals = db.execute(
        "SELECT p.*, "
        "(SELECT COUNT(*) FROM bids b WHERE b.proposal_id = p.id) AS bid_count "
        "FROM proposals p WHERE p.created_by_professor_id = ? "
        "ORDER BY p.updated_at DESC",
        (user["id"],),
    ).fetchall()
    # My theses (via assignments from my proposals) with full Excel columns
    my_theses = db.execute(
        "SELECT t.*, s.name AS student_name, s.email AS student_email, "
        "COALESCE(sup.name, '—') AS supervisor_name, "
        "rv.name AS reviewer_name, "
        "asup.name AS additional_supervisor_name, "
        "p.description AS proposal_abstract "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
        "LEFT JOIN users rv ON t.reviewer_id = rv.id "
        "LEFT JOIN users asup ON t.additional_supervisor_id = asup.id "
        "JOIN assignments a ON a.thesis_id = t.thesis_id "
        "JOIN proposals p ON a.proposal_id = p.id "
        "WHERE p.created_by_professor_id = ? ORDER BY t.start_date ASC",
        (user["id"],),
    ).fetchall()
    ongoing = [t for t in my_theses if t["status"] in ONGOING_STATUSES]
    terminated = [t for t in my_theses if t["status"] in TERMINATED_STATUSES]
    stopped = [t for t in my_theses if t["status"] in STOPPED_STATUSES]
    # Stats
    open_round = get_open_round()
    proposals_in_round = []
    if open_round:
        proposals_in_round = db.execute(
            "SELECT p.title, p.id FROM proposals p "
            "JOIN proposal_rounds pr ON pr.proposal_id = p.id AND pr.round_id = ? "
            "WHERE p.created_by_professor_id = ?",
            (open_round["id"], user["id"]),
        ).fetchall()
    total_bids = sum(p["bid_count"] for p in proposals)
    # Faculty effort for this professor
    effort = _compute_faculty_effort(db, user_filter_id=user["id"])
    # Topic distribution for this professor's theses
    topic_dist = db.execute(
        "SELECT t.primary_topic, COUNT(*) AS cnt FROM thesis t "
        "JOIN assignments a ON a.thesis_id = t.thesis_id "
        "JOIN proposals p ON a.proposal_id = p.id "
        "WHERE p.created_by_professor_id = ? AND t.primary_topic IS NOT NULL "
        "GROUP BY t.primary_topic ORDER BY cnt DESC",
        (user["id"],),
    ).fetchall()
    # Summary stats for this professor
    summary = _compute_summary_stats(db, professor_id=user["id"])
    # Reviewer workload (Part C): theses where this professor is the reviewer
    reviewer_theses = db.execute(
        "SELECT t.*, s.name AS student_name, "
        "COALESCE(sup.name, '—') AS supervisor_name "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
        "WHERE t.reviewer_id = ? AND t.status IN "
        "('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late') "
        "ORDER BY t.start_date ASC",
        (user["id"],),
    ).fetchall()
    return render_template("dashboard_professor.html",
                           proposals=proposals, ongoing=ongoing,
                           terminated=terminated, stopped=stopped,
                           open_round=open_round,
                           proposals_in_round=proposals_in_round,
                           effort=effort, topic_dist=topic_dist,
                           summary=summary,
                           reviewer_theses=reviewer_theses,
                           stats={"active_theses": len(ongoing),
                                  "proposals": len(proposals),
                                  "bids": total_bids,
                                  "reviewer_count": len(reviewer_theses)})


def _admin_dashboard(user):
    db = get_db()
    # Full Excel-like thesis query with all columns
    all_theses = db.execute(
        "SELECT t.*, s.name AS student_name, s.email AS student_email, "
        "COALESCE(sup.name, '—') AS supervisor_name, "
        "rv.name AS reviewer_name, "
        "asup.name AS additional_supervisor_name, "
        "p.description AS proposal_abstract "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
        "LEFT JOIN users rv ON t.reviewer_id = rv.id "
        "LEFT JOIN users asup ON t.additional_supervisor_id = asup.id "
        "LEFT JOIN assignments a ON a.thesis_id = t.thesis_id "
        "LEFT JOIN proposals p ON a.proposal_id = p.id "
        "ORDER BY t.start_date ASC"
    ).fetchall()
    ongoing = [t for t in all_theses if t["status"] in ONGOING_STATUSES]
    terminated = [t for t in all_theses if t["status"] in TERMINATED_STATUSES]
    stopped = [t for t in all_theses if t["status"] in STOPPED_STATUSES]
    proposals = db.execute(
        "SELECT p.*, u.name AS professor_name, "
        "(SELECT COUNT(*) FROM bids b WHERE b.proposal_id = p.id) AS bid_count "
        "FROM proposals p JOIN users u ON p.created_by_professor_id = u.id "
        "ORDER BY p.updated_at DESC"
    ).fetchall()
    rounds = db.execute("SELECT * FROM bidding_rounds ORDER BY created_at DESC").fetchall()
    open_round = get_open_round()
    # Reviewer assignment stats (Part A/B)
    reviewer_assigned_count = db.execute(
        "SELECT COUNT(*) AS c FROM thesis WHERE reviewer_id IS NOT NULL "
        "AND status IN ('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late')"
    ).fetchone()["c"]
    reviewer_missing_count = db.execute(
        "SELECT COUNT(*) AS c FROM thesis WHERE reviewer_id IS NULL "
        "AND status IN ('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late')"
    ).fetchone()["c"]
    # Session phase
    round_phase = get_round_phase(open_round) if open_round else None
    # Faculty effort tables
    effort_ongoing = _compute_faculty_effort(db, status_set="ongoing")
    effort_terminated = _compute_faculty_effort(db, status_set="terminated")
    # Topic distribution
    topic_dist = db.execute(
        "SELECT primary_topic, COUNT(*) AS cnt FROM thesis "
        "WHERE primary_topic IS NOT NULL "
        "GROUP BY primary_topic ORDER BY cnt DESC"
    ).fetchall()
    # Summary stats
    summary_ongoing = _compute_summary_stats(db, status_set="ongoing")
    summary_terminated = _compute_summary_stats(db, status_set="terminated")
    # 3-month review compliance
    overdue_3m = db.execute(
        "SELECT COUNT(*) AS c FROM thesis "
        "WHERE three_month_review_done = 0 AND start_date IS NOT NULL "
        "AND julianday('now') - julianday(start_date) > 90 "
        "AND status IN ('Draft','Submitted','UnderReview','ExternallyReviewed','RevisionRequested','Late')"
    ).fetchone()["c"]
    return render_template("dashboard_admin.html",
                           ongoing=ongoing, terminated=terminated,
                           stopped=stopped,
                           proposals=proposals, rounds=rounds,
                           open_round=open_round,
                           round_phase=round_phase,
                           effort_ongoing=effort_ongoing,
                           effort_terminated=effort_terminated,
                           topic_dist=topic_dist,
                           summary_ongoing=summary_ongoing,
                           summary_terminated=summary_terminated,
                           overdue_3m=overdue_3m,
                           stats={"ongoing": len(ongoing),
                                  "terminated": len(terminated),
                                  "stopped": len(stopped),
                                  "proposals": len(proposals),
                                  "reviewer_assigned": reviewer_assigned_count,
                                  "reviewer_missing": reviewer_missing_count,
                                  "round_phase": round_phase})

# ---------------------------------------------------------------------------
# Routes – Theses
# ---------------------------------------------------------------------------
@app.route("/theses")
@login_required
def thesis_list():
    db = get_db()
    status_filter = request.args.get("status", "")
    query = (
        "SELECT t.*, s.name AS student_name, "
        "COALESCE(sup.name, '—') AS supervisor_name "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
    )
    params = []
    if status_filter and status_filter in THESIS_STATUSES:
        query += "WHERE t.status = ? "
        params.append(status_filter)
    query += "ORDER BY t.updated_at DESC"
    theses = db.execute(query, params).fetchall()
    return render_template("thesis_list.html", theses=theses, status_filter=status_filter)


@app.route("/theses/new", methods=["GET", "POST"])
@role_required("Professor")
def thesis_create():
    db = get_db()
    students = db.execute("SELECT * FROM student ORDER BY name").fetchall()
    supervisors = db.execute("SELECT * FROM supervisor ORDER BY name").fetchall()
    reviewers = db.execute("SELECT * FROM external_reviewer ORDER BY name").fetchall()
    committee_members = db.execute("SELECT * FROM committee_member ORDER BY name").fetchall()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        abstract = request.form.get("abstract", "").strip()
        student_id = request.form.get("student_id")
        supervisor_id = request.form.get("supervisor_id") or None
        external_reviewer_id = request.form.get("external_reviewer_id") or None
        submission_deadline = request.form.get("submission_deadline", "").strip() or None
        committee_ids = request.form.getlist("committee_member_ids")
        if not title or not student_id:
            flash("Title and student are required.", "danger")
            return render_template("thesis_form.html", students=students,
                                   supervisors=supervisors, reviewers=reviewers,
                                   committee_members=committee_members, thesis=None,
                                   selected_committee_ids=[])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        cur = db.execute(
            "INSERT INTO thesis (title, abstract, student_id, supervisor_id, "
            "external_reviewer_id, submission_deadline, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Draft', ?, ?)",
            (title, abstract, int(student_id), supervisor_id and int(supervisor_id),
             external_reviewer_id and int(external_reviewer_id), submission_deadline, now, now),
        )
        thesis_id = cur.lastrowid
        for cid in committee_ids:
            db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)",
                       (thesis_id, int(cid)))
        db.execute(
            "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
            "VALUES (?, NULL, 'Draft', ?)", (thesis_id, now),
        )
        db.commit()
        flash("Thesis created.", "success")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    return render_template("thesis_form.html", students=students,
                           supervisors=supervisors, reviewers=reviewers,
                           committee_members=committee_members, thesis=None,
                           selected_committee_ids=[])


def get_committee_approval_status(db, thesis_id):
    """Return (can_approve, reason, member_decisions).

    member_decisions is a list of dicts:
        {id, name, email, decision, comment, created_at}
    where decision/comment/created_at may be None if the member hasn't decided yet.
    """
    members = db.execute(
        "SELECT cm.* FROM committee_member cm "
        "JOIN thesis_committee tc ON cm.id = tc.committee_member_id "
        "WHERE tc.thesis_id = ? ORDER BY cm.name", (thesis_id,)
    ).fetchall()
    if not members:
        return True, None, []

    member_decisions = []
    all_decided = True
    has_reject = False
    for m in members:
        latest = db.execute(
            "SELECT decision, comment, created_at FROM decision_log "
            "WHERE thesis_id = ? AND committee_member_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (thesis_id, m["id"]),
        ).fetchone()
        md = {"id": m["id"], "name": m["name"], "email": m["email"],
              "decision": latest["decision"] if latest else None,
              "comment": latest["comment"] if latest else None,
              "created_at": latest["created_at"] if latest else None}
        if not latest:
            all_decided = False
        elif latest["decision"] == "Reject":
            has_reject = True
        member_decisions.append(md)

    if not all_decided:
        return False, "All committee decisions must be submitted before approval.", member_decisions
    if has_reject:
        return False, "Approval blocked: one or more committee members selected Reject.", member_decisions
    return True, None, member_decisions


@app.route("/theses/<int:thesis_id>")
@login_required
def thesis_detail(thesis_id):
    db = get_db()
    thesis = db.execute(
        "SELECT t.*, s.name AS student_name, s.email AS student_email, "
        "sup.name AS supervisor_name, sup.email AS supervisor_email, sup.department, "
        "er.name AS reviewer_name, er.email AS reviewer_email "
        "FROM thesis t "
        "JOIN student s ON t.student_id = s.student_id "
        "LEFT JOIN supervisor sup ON t.supervisor_id = sup.supervisor_id "
        "LEFT JOIN external_reviewer er ON t.external_reviewer_id = er.id "
        "WHERE t.thesis_id = ?", (thesis_id,)
    ).fetchone()
    if not thesis:
        abort(404)
    milestones = db.execute(
        "SELECT * FROM milestone WHERE thesis_id = ? ORDER BY due_date", (thesis_id,)
    ).fetchall()
    submissions = db.execute(
        "SELECT * FROM submission WHERE thesis_id = ? ORDER BY submitted_at DESC", (thesis_id,)
    ).fetchall()
    history = db.execute(
        "SELECT * FROM status_history WHERE thesis_id = ? ORDER BY changed_at DESC", (thesis_id,)
    ).fetchall()
    supervisors = db.execute("SELECT * FROM supervisor ORDER BY name").fetchall()
    reviewers = db.execute("SELECT * FROM external_reviewer ORDER BY name").fetchall()
    all_committee = db.execute("SELECT * FROM committee_member ORDER BY name").fetchall()
    assigned_committee_ids = [
        r["committee_member_id"] for r in
        db.execute("SELECT committee_member_id FROM thesis_committee WHERE thesis_id = ?", (thesis_id,)).fetchall()
    ]
    can_approve, approve_reason, member_decisions = get_committee_approval_status(db, thesis_id)
    decision_log = db.execute(
        "SELECT dl.*, cm.name AS member_name FROM decision_log dl "
        "JOIN committee_member cm ON dl.committee_member_id = cm.id "
        "WHERE dl.thesis_id = ? ORDER BY dl.created_at DESC", (thesis_id,)
    ).fetchall()
    # Professors for reviewer assignment (Part B)
    professors = db.execute("SELECT id, name FROM users WHERE role = 'Professor' ORDER BY name").fetchall()
    # Current reviewer info
    prof_reviewer = None
    if thesis["reviewer_id"] if "reviewer_id" in thesis.keys() else False:
        prof_reviewer = db.execute("SELECT * FROM users WHERE id = ?",
                                   (thesis["reviewer_id"],)).fetchone()
    return render_template("thesis_detail.html", thesis=thesis,
                           milestones=milestones, submissions=submissions,
                           history=history, supervisors=supervisors, reviewers=reviewers,
                           all_committee=all_committee,
                           assigned_committee_ids=assigned_committee_ids,
                           can_approve=can_approve, approve_reason=approve_reason,
                           member_decisions=member_decisions,
                           decision_log=decision_log,
                           professors=professors, prof_reviewer=prof_reviewer)


@app.route("/theses/<int:thesis_id>/edit", methods=["GET", "POST"])
@role_required("Professor")
def thesis_edit(thesis_id):
    db = get_db()
    thesis = db.execute("SELECT * FROM thesis WHERE thesis_id = ?", (thesis_id,)).fetchone()
    if not thesis:
        abort(404)
    students = db.execute("SELECT * FROM student ORDER BY name").fetchall()
    supervisors = db.execute("SELECT * FROM supervisor ORDER BY name").fetchall()
    reviewers = db.execute("SELECT * FROM external_reviewer ORDER BY name").fetchall()
    committee_members = db.execute("SELECT * FROM committee_member ORDER BY name").fetchall()
    selected_committee_ids = [
        r["committee_member_id"] for r in
        db.execute("SELECT committee_member_id FROM thesis_committee WHERE thesis_id = ?", (thesis_id,)).fetchall()
    ]
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        abstract = request.form.get("abstract", "").strip()
        student_id = request.form.get("student_id")
        supervisor_id = request.form.get("supervisor_id") or None
        external_reviewer_id = request.form.get("external_reviewer_id") or None
        submission_deadline = request.form.get("submission_deadline", "").strip() or None
        committee_ids = request.form.getlist("committee_member_ids")
        if not title or not student_id:
            flash("Title and student are required.", "danger")
            return render_template("thesis_form.html", students=students,
                                   supervisors=supervisors, reviewers=reviewers,
                                   committee_members=committee_members, thesis=thesis,
                                   selected_committee_ids=selected_committee_ids)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        db.execute(
            "UPDATE thesis SET title=?, abstract=?, student_id=?, supervisor_id=?, "
            "external_reviewer_id=?, submission_deadline=?, updated_at=? WHERE thesis_id=?",
            (title, abstract, int(student_id), supervisor_id and int(supervisor_id),
             external_reviewer_id and int(external_reviewer_id), submission_deadline, now, thesis_id),
        )
        db.execute("DELETE FROM thesis_committee WHERE thesis_id = ?", (thesis_id,))
        for cid in committee_ids:
            db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)",
                       (thesis_id, int(cid)))
        db.commit()
        flash("Thesis updated.", "success")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    return render_template("thesis_form.html", students=students,
                           supervisors=supervisors, reviewers=reviewers,
                           committee_members=committee_members, thesis=thesis,
                           selected_committee_ids=selected_committee_ids)


@app.route("/theses/<int:thesis_id>/delete", methods=["POST"])
@role_required("Admin")
def thesis_delete(thesis_id):
    db = get_db()
    db.execute("DELETE FROM thesis WHERE thesis_id = ?", (thesis_id,))
    db.commit()
    flash("Thesis deleted.", "success")
    return redirect(url_for("thesis_list"))


@app.route("/theses/<int:thesis_id>/transition", methods=["POST"])
@role_required("Professor")
def thesis_transition(thesis_id):
    db = get_db()
    thesis = db.execute("SELECT * FROM thesis WHERE thesis_id = ?", (thesis_id,)).fetchone()
    if not thesis:
        abort(404)
    new_status = request.form.get("new_status")
    allowed = THESIS_TRANSITIONS.get(thesis["status"], [])
    if new_status not in allowed:
        flash(f"Cannot transition from {thesis['status']} to {new_status}.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    if new_status == "ExternallyReviewed" and not thesis["external_reviewer_id"]:
        flash("Cannot move to ExternallyReviewed: no External Reviewer assigned.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    if new_status == "Approved":
        can_approve, reason, _ = get_committee_approval_status(db, thesis_id)
        if not can_approve:
            flash(f"Cannot approve: {reason}", "danger")
            return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET status=?, updated_at=? WHERE thesis_id=?",
               (new_status, now, thesis_id))
    db.execute(
        "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
        "VALUES (?, ?, ?, ?)", (thesis_id, thesis["status"], new_status, now),
    )
    db.commit()
    flash(f"Status changed to {new_status}.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/assign", methods=["POST"])
@role_required("Professor")
def thesis_assign_supervisor(thesis_id):
    db = get_db()
    supervisor_id = request.form.get("supervisor_id") or None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET supervisor_id=?, updated_at=? WHERE thesis_id=?",
               (supervisor_id and int(supervisor_id), now, thesis_id))
    db.commit()
    flash("Supervisor assigned.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/assign-professor-reviewer", methods=["POST"])
@role_required("Admin")
def thesis_assign_professor_reviewer(thesis_id):
    """Admin assigns a professor as reviewer for a thesis. Reviewer ≠ supervisor."""
    db = get_db()
    thesis = db.execute("SELECT * FROM thesis WHERE thesis_id = ?", (thesis_id,)).fetchone()
    if not thesis:
        abort(404)
    reviewer_user_id = request.form.get("reviewer_id") or None
    if reviewer_user_id:
        reviewer_user_id = int(reviewer_user_id)
        # Validate reviewer ≠ supervisor
        if thesis["supervisor_id"]:
            sup = db.execute("SELECT email FROM supervisor WHERE supervisor_id = ?",
                             (thesis["supervisor_id"],)).fetchone()
            rev_user = db.execute("SELECT email FROM users WHERE id = ?", (reviewer_user_id,)).fetchone()
            if sup and rev_user and sup["email"] == rev_user["email"]:
                flash("Reviewer cannot be the same person as the supervisor.", "danger")
                return redirect(url_for("thesis_detail", thesis_id=thesis_id))
        # Validate reviewer ≠ additional supervisor
        if thesis["additional_supervisor_id"] and thesis["additional_supervisor_id"] == reviewer_user_id:
            flash("Reviewer cannot be the same person as the additional supervisor.", "danger")
            return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET reviewer_id=?, updated_at=? WHERE thesis_id=?",
               (reviewer_user_id, now, thesis_id))
    db.commit()
    flash("Professor reviewer assigned." if reviewer_user_id else "Professor reviewer removed.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/assign-reviewer", methods=["POST"])
@role_required("Professor")
def thesis_assign_reviewer(thesis_id):
    db = get_db()
    reviewer_id = request.form.get("external_reviewer_id") or None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET external_reviewer_id=?, updated_at=? WHERE thesis_id=?",
               (reviewer_id and int(reviewer_id), now, thesis_id))
    db.commit()
    flash("External Reviewer assigned.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/committee", methods=["POST"])
@role_required("Professor")
def thesis_update_committee(thesis_id):
    db = get_db()
    committee_ids = request.form.getlist("committee_member_ids")
    db.execute("DELETE FROM thesis_committee WHERE thesis_id = ?", (thesis_id,))
    for cid in committee_ids:
        db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)",
                   (thesis_id, int(cid)))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET updated_at=? WHERE thesis_id=?", (now, thesis_id))
    db.commit()
    flash("Committee updated.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/decision", methods=["POST"])
@role_required("Professor")
def committee_decision_submit(thesis_id):
    db = get_db()
    member_id = request.form.get("committee_member_id")
    decision = request.form.get("decision", "").strip()
    comment = request.form.get("comment", "").strip()
    if not member_id or decision not in COMMITTEE_DECISIONS:
        flash("Invalid decision submission.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    assigned = db.execute(
        "SELECT 1 FROM thesis_committee WHERE thesis_id = ? AND committee_member_id = ?",
        (thesis_id, int(member_id)),
    ).fetchone()
    if not assigned:
        flash("This member is not on the committee for this thesis.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute(
        "INSERT INTO decision_log (thesis_id, committee_member_id, decision, comment, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (thesis_id, int(member_id), decision, comment or None, now),
    )
    db.commit()
    flash(f"Decision '{decision}' recorded.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))

# ---------------------------------------------------------------------------
# Routes – Milestones
# ---------------------------------------------------------------------------
@app.route("/theses/<int:thesis_id>/milestones/add", methods=["POST"])
@role_required("Professor")
def milestone_add(thesis_id):
    db = get_db()
    mtype = request.form.get("type", "").strip()
    due_date = request.form.get("due_date", "").strip()
    notes = request.form.get("notes", "").strip()
    if not mtype or not due_date:
        flash("Milestone type and due date are required.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    db.execute(
        "INSERT INTO milestone (thesis_id, type, due_date, status, notes) VALUES (?, ?, ?, 'Planned', ?)",
        (thesis_id, mtype, due_date, notes),
    )
    db.commit()
    flash("Milestone added.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/milestones/<int:milestone_id>/edit", methods=["POST"])
@role_required("Professor")
def milestone_edit(milestone_id):
    db = get_db()
    ms = db.execute("SELECT * FROM milestone WHERE milestone_id = ?", (milestone_id,)).fetchone()
    if not ms:
        abort(404)
    mtype = request.form.get("type", "").strip()
    due_date = request.form.get("due_date", "").strip()
    notes = request.form.get("notes", "").strip()
    if not mtype or not due_date:
        flash("Milestone type and due date are required.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=ms["thesis_id"]))
    db.execute(
        "UPDATE milestone SET type=?, due_date=?, notes=? WHERE milestone_id=?",
        (mtype, due_date, notes, milestone_id),
    )
    db.commit()
    flash("Milestone updated.", "success")
    return redirect(url_for("thesis_detail", thesis_id=ms["thesis_id"]))


@app.route("/milestones/<int:milestone_id>/delete", methods=["POST"])
@role_required("Professor")
def milestone_delete(milestone_id):
    db = get_db()
    ms = db.execute("SELECT * FROM milestone WHERE milestone_id = ?", (milestone_id,)).fetchone()
    if not ms:
        abort(404)
    db.execute("DELETE FROM milestone WHERE milestone_id = ?", (milestone_id,))
    db.commit()
    flash("Milestone deleted.", "success")
    return redirect(url_for("thesis_detail", thesis_id=ms["thesis_id"]))


@app.route("/milestones/<int:milestone_id>/transition", methods=["POST"])
@role_required("Professor")
def milestone_transition(milestone_id):
    db = get_db()
    ms = db.execute("SELECT * FROM milestone WHERE milestone_id = ?", (milestone_id,)).fetchone()
    if not ms:
        abort(404)
    new_status = request.form.get("new_status")
    allowed = MILESTONE_TRANSITIONS.get(ms["status"], [])
    if new_status not in allowed:
        flash(f"Cannot transition milestone from {ms['status']} to {new_status}.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=ms["thesis_id"]))
    db.execute("UPDATE milestone SET status=? WHERE milestone_id=?",
               (new_status, milestone_id))
    db.commit()
    flash(f"Milestone status changed to {new_status}.", "success")
    return redirect(url_for("thesis_detail", thesis_id=ms["thesis_id"]))

# ---------------------------------------------------------------------------
# Routes – Submissions
# ---------------------------------------------------------------------------
@app.route("/theses/<int:thesis_id>/submissions/add", methods=["POST"])
@login_required
def submission_add(thesis_id):
    db = get_db()
    kind = request.form.get("kind", "").strip()
    comment = request.form.get("comment", "").strip()
    attachment = request.form.get("attachment_path_or_url", "").strip()
    if kind not in SUBMISSION_KINDS:
        flash("Invalid submission kind.", "danger")
        return redirect(url_for("thesis_detail", thesis_id=thesis_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute(
        "INSERT INTO submission (thesis_id, kind, submitted_at, comment, attachment_path_or_url) "
        "VALUES (?, ?, ?, ?, ?)",
        (thesis_id, kind, now, comment, attachment or None),
    )
    db.commit()
    flash("Submission added.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))

# ---------------------------------------------------------------------------
# Routes – Proposals
# ---------------------------------------------------------------------------
@app.route("/proposals")
@login_required
def proposals_list():
    db = get_db()
    user = get_current_user()
    if user["role"] == "Admin":
        proposals = db.execute(
            "SELECT p.*, u.name AS professor_name FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id ORDER BY p.updated_at DESC"
        ).fetchall()
    elif user["role"] == "Professor":
        proposals = db.execute(
            "SELECT p.*, u.name AS professor_name FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE p.created_by_professor_id = ? ORDER BY p.updated_at DESC",
            (user["id"],),
        ).fetchall()
    else:
        proposals = db.execute(
            "SELECT p.*, u.name AS professor_name FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE p.status = 'Published' ORDER BY p.updated_at DESC"
        ).fetchall()
    open_round = get_open_round()
    return render_template("proposals_list.html", proposals=proposals,
                           open_round=open_round)


@app.route("/proposals/new", methods=["GET", "POST"])
@role_required("Professor")
def proposal_create():
    user = get_current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("Title is required.", "danger")
            return render_template("proposal_form.html", proposal=None)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        db = get_db()
        cur = db.execute(
            "INSERT INTO proposals (title, description, created_by_professor_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'Draft', ?, ?)",
            (title, description, user["id"], now, now),
        )
        db.commit()
        flash("Proposal created as Draft.", "success")
        return redirect(url_for("proposal_detail", proposal_id=cur.lastrowid))
    return render_template("proposal_form.html", proposal=None)


@app.route("/proposals/<int:proposal_id>")
@login_required
def proposal_detail(proposal_id):
    db = get_db()
    user = get_current_user()
    proposal = db.execute(
        "SELECT p.*, u.name AS professor_name, u.email AS professor_email "
        "FROM proposals p JOIN users u ON p.created_by_professor_id = u.id "
        "WHERE p.id = ?", (proposal_id,)
    ).fetchone()
    if not proposal:
        abort(404)
    # Access control: students can only see Published proposals
    if user["role"] == "Student" and proposal["status"] != "Published":
        flash("You do not have permission to view this proposal.", "danger")
        return redirect(url_for("proposals_list"))
    # Professors can only see their own proposals (unless admin)
    if user["role"] == "Professor" and proposal["created_by_professor_id"] != user["id"]:
        if proposal["status"] != "Published":
            flash("You do not have permission to view this proposal.", "danger")
            return redirect(url_for("proposals_list"))
    # Bids: visible to proposal owner and admin
    bids = []
    if user["role"] == "Admin" or (user["role"] == "Professor" and proposal["created_by_professor_id"] == user["id"]):
        bids = db.execute(
            "SELECT b.*, u.name AS student_name, u.email AS student_email, "
            "br.name AS round_name, br.status AS round_status "
            "FROM bids b JOIN users u ON b.student_id = u.id "
            "JOIN bidding_rounds br ON b.round_id = br.id "
            "WHERE b.proposal_id = ? ORDER BY br.created_at DESC, b.created_at DESC",
            (proposal_id,)
        ).fetchall()
    # Check if student already bid in the current open round
    open_round = get_open_round()
    student_has_bid = False
    if user["role"] == "Student" and open_round:
        existing = db.execute(
            "SELECT 1 FROM bids WHERE round_id = ? AND proposal_id = ? AND student_id = ?",
            (open_round["id"], proposal_id, user["id"]),
        ).fetchone()
        student_has_bid = existing is not None
    # Check if proposal is assigned (any round)
    assignment = db.execute(
        "SELECT a.*, u.name AS student_name, br.name AS round_name "
        "FROM assignments a "
        "JOIN users u ON a.student_id = u.id "
        "JOIN bidding_rounds br ON a.round_id = br.id "
        "WHERE a.proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    return render_template("proposal_detail.html", proposal=proposal, bids=bids,
                           open_round=open_round, student_has_bid=student_has_bid,
                           assignment=assignment)


@app.route("/proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@role_required("Professor")
def proposal_edit(proposal_id):
    db = get_db()
    user = get_current_user()
    proposal = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not proposal:
        abort(404)
    if proposal["created_by_professor_id"] != user["id"] and user["role"] != "Admin":
        flash("You can only edit your own proposals.", "danger")
        return redirect(url_for("proposals_list"))
    if proposal["status"] != "Draft":
        flash("Only Draft proposals can be edited.", "danger")
        return redirect(url_for("proposal_detail", proposal_id=proposal_id))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("Title is required.", "danger")
            return render_template("proposal_form.html", proposal=proposal)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        db.execute(
            "UPDATE proposals SET title=?, description=?, updated_at=? WHERE id=?",
            (title, description, now, proposal_id),
        )
        db.commit()
        flash("Proposal updated.", "success")
        return redirect(url_for("proposal_detail", proposal_id=proposal_id))
    return render_template("proposal_form.html", proposal=proposal)


@app.route("/proposals/<int:proposal_id>/publish", methods=["POST"])
@role_required("Professor")
def proposal_publish(proposal_id):
    db = get_db()
    user = get_current_user()
    proposal = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not proposal:
        abort(404)
    if proposal["created_by_professor_id"] != user["id"] and user["role"] != "Admin":
        flash("You can only publish your own proposals.", "danger")
        return redirect(url_for("proposals_list"))
    if proposal["status"] != "Draft":
        flash("Only Draft proposals can be published.", "danger")
        return redirect(url_for("proposal_detail", proposal_id=proposal_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE proposals SET status='Published', updated_at=? WHERE id=?", (now, proposal_id))
    db.commit()
    flash("Proposal published.", "success")
    return redirect(url_for("proposal_detail", proposal_id=proposal_id))


@app.route("/proposals/<int:proposal_id>/archive", methods=["POST"])
@role_required("Professor")
def proposal_archive(proposal_id):
    db = get_db()
    user = get_current_user()
    proposal = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not proposal:
        abort(404)
    if proposal["created_by_professor_id"] != user["id"] and user["role"] != "Admin":
        flash("You can only archive your own proposals.", "danger")
        return redirect(url_for("proposals_list"))
    if proposal["status"] != "Published":
        flash("Only Published proposals can be archived.", "danger")
        return redirect(url_for("proposal_detail", proposal_id=proposal_id))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE proposals SET status='Archived', updated_at=? WHERE id=?", (now, proposal_id))
    db.commit()
    flash("Proposal archived.", "success")
    return redirect(url_for("proposal_detail", proposal_id=proposal_id))


@app.route("/proposals/<int:proposal_id>/bid", methods=["POST"])
@login_required
def proposal_bid(proposal_id):
    """Legacy single-bid route — redirects to the new bidding page."""
    flash("Please use the Bidding page to submit your 3 proposal choices.", "danger")
    return redirect(url_for("student_bidding"))


# ---------------------------------------------------------------------------
# Routes – Student Bidding (select 3 proposals)
# ---------------------------------------------------------------------------
@app.route("/bidding/student", methods=["GET", "POST"])
@login_required
def student_bidding():
    user = get_current_user()
    if user["role"] != "Student":
        flash("Only students can access this page.", "danger")
        return redirect(url_for("dashboard"))
    db = get_db()
    open_round = get_open_round()
    if not open_round:
        # No open round — check for most recent bid group result
        latest_group = db.execute(
            "SELECT bg.*, br.name AS round_name "
            "FROM bid_groups bg JOIN bidding_rounds br ON bg.round_id = br.id "
            "WHERE bg.student_id = ? ORDER BY bg.created_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        latest_bids = []
        if latest_group:
            latest_bids = db.execute(
                "SELECT b.*, p.title AS proposal_title, u.name AS professor_name "
                "FROM bids b JOIN proposals p ON b.proposal_id = p.id "
                "JOIN users u ON p.created_by_professor_id = u.id "
                "WHERE b.bid_group_id = ? ORDER BY b.rank",
                (latest_group["id"],),
            ).fetchall()
        return render_template("student_bidding.html", open_round=None,
                               available=[], existing_group=latest_group,
                               existing_bids=latest_bids)
    # Check if student already submitted a bid group for this round
    existing_group = db.execute(
        "SELECT * FROM bid_groups WHERE student_id = ? AND round_id = ?",
        (user["id"], open_round["id"]),
    ).fetchone()
    existing_bids = []
    if existing_group:
        existing_bids = db.execute(
            "SELECT b.*, p.title AS proposal_title, u.name AS professor_name "
            "FROM bids b "
            "JOIN proposals p ON b.proposal_id = p.id "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE b.bid_group_id = ? ORDER BY b.rank",
            (existing_group["id"],),
        ).fetchall()
    # Available proposals: published, in current round, not assigned
    available = db.execute(
        "SELECT p.*, u.name AS professor_name, p.description AS abstract "
        "FROM proposals p "
        "JOIN users u ON p.created_by_professor_id = u.id "
        "JOIN proposal_rounds pr ON pr.proposal_id = p.id AND pr.round_id = ? "
        "WHERE p.status = 'Published' "
        "AND NOT EXISTS (SELECT 1 FROM assignments WHERE proposal_id = p.id) "
        "ORDER BY p.title",
        (open_round["id"],),
    ).fetchall()

    # Determine bidding phase
    round_phase = get_round_phase(open_round)

    if request.method == "POST" and not existing_group:
        # Block submissions during proposal collection phase
        if round_phase == "proposal_collection":
            flash("Bidding has not started yet. Proposals are still being collected.", "danger")
            return redirect(url_for("student_bidding"))
        proposal_1 = request.form.get("proposal_1")
        proposal_2 = request.form.get("proposal_2")
        proposal_3 = request.form.get("proposal_3")
        motivation = request.form.get("motivation_text", "").strip()
        if not all([proposal_1, proposal_2, proposal_3]):
            flash("You must select exactly 3 proposals.", "danger")
            return redirect(url_for("student_bidding"))
        choices = [int(proposal_1), int(proposal_2), int(proposal_3)]
        if len(set(choices)) != 3:
            flash("You must select 3 different proposals.", "danger")
            return redirect(url_for("student_bidding"))
        if not motivation:
            flash("Motivation text is required.", "danger")
            return redirect(url_for("student_bidding"))
        # Validate all proposals exist and are available
        for pid in choices:
            p = db.execute(
                "SELECT 1 FROM proposals p "
                "JOIN proposal_rounds pr ON pr.proposal_id = p.id AND pr.round_id = ? "
                "WHERE p.id = ? AND p.status = 'Published' "
                "AND NOT EXISTS (SELECT 1 FROM assignments WHERE proposal_id = p.id)",
                (open_round["id"], pid),
            ).fetchone()
            if not p:
                flash("One or more selected proposals are not available.", "danger")
                return redirect(url_for("student_bidding"))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        # Create bid group
        bg_cur = db.execute(
            "INSERT INTO bid_groups (student_id, round_id, status, motivation_text, created_at) "
            "VALUES (?, ?, 'Pending', ?, ?)",
            (user["id"], open_round["id"], motivation, now),
        )
        bg_id = bg_cur.lastrowid
        # Create individual bids
        for rank, pid in enumerate(choices, 1):
            db.execute(
                "INSERT INTO bids (bid_group_id, proposal_id, student_id, round_id, rank, "
                "motivation_text, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)",
                (bg_id, pid, user["id"], open_round["id"], rank, motivation, now),
            )
        db.commit()
        flash("Your bidding choices have been submitted successfully!", "success")
        return redirect(url_for("student_bidding"))

    return render_template("student_bidding.html", open_round=open_round,
                           available=available, existing_group=existing_group,
                           existing_bids=existing_bids, round_phase=round_phase)


# ---------------------------------------------------------------------------
# Routes – Bidding Governance (unified admin page)
# ---------------------------------------------------------------------------
@app.route("/admin/governance")
@role_required("Admin")
def bidding_governance():
    """Unified bidding governance page combining rounds + bidding management."""
    db = get_db()
    rounds = db.execute("SELECT * FROM bidding_rounds ORDER BY created_at DESC").fetchall()
    open_round = get_open_round()
    round_phase = get_round_phase(open_round) if open_round else None

    # Proposals in current round + available to add
    in_round = []
    available = []
    if open_round:
        in_round = db.execute(
            "SELECT p.*, u.name AS professor_name, pr.id AS pr_id, "
            "(SELECT COUNT(*) FROM bids b WHERE b.proposal_id = p.id AND b.round_id = ?) AS bid_count "
            "FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "JOIN proposal_rounds pr ON pr.proposal_id = p.id AND pr.round_id = ? "
            "ORDER BY p.title",
            (open_round["id"], open_round["id"]),
        ).fetchall()
        in_round_ids = {p["id"] for p in in_round}
        all_published = db.execute(
            "SELECT p.*, u.name AS professor_name FROM proposals p "
            "JOIN users u ON p.created_by_professor_id = u.id "
            "WHERE p.status = 'Published' "
            "AND NOT EXISTS (SELECT 1 FROM assignments WHERE proposal_id = p.id) "
            "ORDER BY p.title"
        ).fetchall()
        available = [p for p in all_published if p["id"] not in in_round_ids]

    # Bidding overview for active round: bid groups
    bid_groups = []
    if open_round:
        bid_groups = db.execute(
            "SELECT bg.*, u.name AS student_name, u.email AS student_email, "
            "(SELECT COUNT(*) FROM bids WHERE bid_group_id = bg.id) AS bid_count "
            "FROM bid_groups bg "
            "JOIN users u ON bg.student_id = u.id "
            "WHERE bg.round_id = ? ORDER BY bg.created_at DESC",
            (open_round["id"],),
        ).fetchall()

    # Closed rounds for assignment links
    closed_rounds = [r for r in rounds if r["status"] == "Closed"]

    return render_template("bidding_governance.html",
                           rounds=rounds, open_round=open_round,
                           round_phase=round_phase,
                           in_round=in_round, available=available,
                           bid_groups=bid_groups,
                           closed_rounds=closed_rounds)


@app.route("/rounds")
@role_required("Admin")
def rounds_list():
    """Legacy redirect — now part of unified governance."""
    return redirect(url_for("bidding_governance"))


@app.route("/rounds/new", methods=["GET", "POST"])
@role_required("Admin")
def round_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        proposal_collection_end = request.form.get("proposal_collection_end", "").strip() or None
        if not name or not start_date or not end_date:
            flash("Name, start date, and end date are required.", "danger")
            return render_template("round_form.html")
        if end_date < start_date:
            flash("End date must be on or after start date.", "danger")
            return render_template("round_form.html")
        if proposal_collection_end:
            if proposal_collection_end < start_date or proposal_collection_end > end_date:
                flash("Proposal collection end must be between start and end dates.", "danger")
                return render_template("round_form.html")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        db = get_db()
        db.execute(
            "INSERT INTO bidding_rounds (name, start_date, end_date, proposal_collection_end, status, created_at) "
            "VALUES (?, ?, ?, ?, 'Planned', ?)",
            (name, start_date, end_date, proposal_collection_end, now),
        )
        db.commit()
        flash("Bidding round created as Planned.", "success")
        return redirect(url_for("bidding_governance"))
    return render_template("round_form.html")


@app.route("/rounds/<int:round_id>/open", methods=["POST"])
@role_required("Admin")
def round_open(round_id):
    db = get_db()
    rnd = db.execute("SELECT * FROM bidding_rounds WHERE id = ?", (round_id,)).fetchone()
    if not rnd:
        abort(404)
    if rnd["status"] != "Planned":
        flash("Only Planned rounds can be opened.", "danger")
        return redirect(url_for("bidding_governance"))
    # Check no other round is currently Open
    existing_open = db.execute("SELECT id FROM bidding_rounds WHERE status = 'Open'").fetchone()
    if existing_open:
        flash("Another round is already open. Close it first.", "danger")
        return redirect(url_for("bidding_governance"))
    db.execute("UPDATE bidding_rounds SET status='Open' WHERE id=?", (round_id,))
    db.commit()
    flash("Bidding round opened.", "success")
    return redirect(url_for("bidding_governance"))


@app.route("/rounds/<int:round_id>/close", methods=["POST"])
@role_required("Admin")
def round_close(round_id):
    db = get_db()
    rnd = db.execute("SELECT * FROM bidding_rounds WHERE id = ?", (round_id,)).fetchone()
    if not rnd:
        abort(404)
    if rnd["status"] != "Open":
        flash("Only Open rounds can be closed.", "danger")
        return redirect(url_for("bidding_governance"))
    db.execute("UPDATE bidding_rounds SET status='Closed' WHERE id=?", (round_id,))
    db.commit()
    flash("Bidding round closed.", "success")
    return redirect(url_for("bidding_governance"))


# ---------------------------------------------------------------------------
# Routes – Round Assignments (Admin)
# ---------------------------------------------------------------------------
@app.route("/rounds/<int:round_id>/assignments")
@role_required("Admin")
def round_assignments(round_id):
    db = get_db()
    rnd = db.execute("SELECT * FROM bidding_rounds WHERE id = ?", (round_id,)).fetchone()
    if not rnd:
        abort(404)
    # Get all bid groups (student submissions) for this round
    bid_groups = db.execute(
        "SELECT bg.*, u.name AS student_name, u.email AS student_email "
        "FROM bid_groups bg "
        "JOIN users u ON bg.student_id = u.id "
        "WHERE bg.round_id = ? ORDER BY bg.created_at",
        (round_id,),
    ).fetchall()
    student_data = []
    for bg in bid_groups:
        bids = db.execute(
            "SELECT b.*, p.title AS proposal_title, p.id AS proposal_id, "
            "prof.name AS professor_name "
            "FROM bids b "
            "JOIN proposals p ON b.proposal_id = p.id "
            "JOIN users prof ON p.created_by_professor_id = prof.id "
            "WHERE b.bid_group_id = ? ORDER BY b.rank",
            (bg["id"],),
        ).fetchall()
        # Check if student already has an assignment in this round
        assignment = db.execute(
            "SELECT a.*, p.title AS proposal_title, u.name AS student_name "
            "FROM assignments a "
            "JOIN proposals p ON a.proposal_id = p.id "
            "JOIN users u ON a.student_id = u.id "
            "WHERE a.round_id = ? AND a.student_id = ?",
            (round_id, bg["student_id"]),
        ).fetchone()
        student_data.append({
            "bid_group": bg,
            "bids": bids,
            "assignment": assignment,
        })
    # Also keep legacy proposal-based view for bids without bid_groups
    proposals_with_bids = db.execute(
        "SELECT DISTINCT p.id, p.title, p.description, u.name AS professor_name "
        "FROM proposals p "
        "JOIN bids b ON b.proposal_id = p.id AND b.round_id = ? AND b.bid_group_id IS NULL "
        "JOIN users u ON p.created_by_professor_id = u.id "
        "ORDER BY p.title",
        (round_id,),
    ).fetchall()
    proposal_data = []
    for p in proposals_with_bids:
        bids = db.execute(
            "SELECT b.*, u.name AS student_name, u.email AS student_email "
            "FROM bids b JOIN users u ON b.student_id = u.id "
            "WHERE b.proposal_id = ? AND b.round_id = ? AND b.bid_group_id IS NULL "
            "ORDER BY LENGTH(b.motivation_text) DESC",
            (p["id"], round_id),
        ).fetchall()
        assignment = db.execute(
            "SELECT a.*, u.name AS student_name "
            "FROM assignments a JOIN users u ON a.student_id = u.id "
            "WHERE a.round_id = ? AND a.proposal_id = ?",
            (round_id, p["id"]),
        ).fetchone()
        recommended_bid_id = bids[0]["id"] if bids else None
        proposal_data.append({
            "proposal": p,
            "bids": bids,
            "assignment": assignment,
            "recommended_bid_id": recommended_bid_id,
        })
    return render_template("round_assignments.html", round=rnd,
                           student_data=student_data, proposal_data=proposal_data)


@app.route("/rounds/<int:round_id>/assign/<int:proposal_id>", methods=["POST"])
@role_required("Admin")
def round_assign(round_id, proposal_id):
    db = get_db()
    admin_user = get_current_user()
    rnd = db.execute("SELECT * FROM bidding_rounds WHERE id = ?", (round_id,)).fetchone()
    if not rnd or rnd["status"] != "Closed":
        flash("Round must be Closed before assignments can be made.", "danger")
        return redirect(url_for("rounds_list"))
    proposal = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not proposal:
        abort(404)
    existing_assignment = db.execute(
        "SELECT 1 FROM assignments WHERE round_id = ? AND proposal_id = ?",
        (round_id, proposal_id),
    ).fetchone()
    if existing_assignment:
        flash("This proposal is already assigned in this round.", "danger")
        return redirect(url_for("round_assignments", round_id=round_id))
    bid_id = request.form.get("bid_id")
    if not bid_id:
        flash("No bid selected.", "danger")
        return redirect(url_for("round_assignments", round_id=round_id))
    bid = db.execute(
        "SELECT b.*, u.name AS student_name, u.email AS student_email "
        "FROM bids b JOIN users u ON b.student_id = u.id "
        "WHERE b.id = ? AND b.round_id = ? AND b.proposal_id = ?",
        (int(bid_id), round_id, proposal_id),
    ).fetchone()
    if not bid:
        flash("Invalid bid selection.", "danger")
        return redirect(url_for("round_assignments", round_id=round_id))
    professor = db.execute(
        "SELECT * FROM users WHERE id = ?", (proposal["created_by_professor_id"],)
    ).fetchone()
    # Find or create student record (lookup by email)
    student_row = db.execute(
        "SELECT student_id FROM student WHERE email = ?", (bid["student_email"],)
    ).fetchone()
    if student_row:
        student_record_id = student_row["student_id"]
    else:
        cur = db.execute(
            "INSERT INTO student (name, email) VALUES (?, ?)",
            (bid["student_name"], bid["student_email"]),
        )
        student_record_id = cur.lastrowid
    # Find or create supervisor record (lookup by email)
    supervisor_row = db.execute(
        "SELECT supervisor_id FROM supervisor WHERE email = ?", (professor["email"],)
    ).fetchone()
    if supervisor_row:
        supervisor_record_id = supervisor_row["supervisor_id"]
    else:
        cur = db.execute(
            "INSERT INTO supervisor (name, email, department) VALUES (?, ?, ?)",
            (professor["name"], professor["email"], "General"),
        )
        supervisor_record_id = cur.lastrowid
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_str = date.today().isoformat()
    # Create thesis with ER-6 fields
    thesis_cur = db.execute(
        "INSERT INTO thesis (title, abstract, student_id, supervisor_id, status, "
        "start_date, assignment_source, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'Draft', ?, 'NEW', ?, ?)",
        (proposal["title"], proposal["description"], student_record_id, supervisor_record_id,
         today_str, now, now),
    )
    thesis_id = thesis_cur.lastrowid
    db.execute(
        "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
        "VALUES (?, NULL, 'Draft', ?)", (thesis_id, now),
    )
    # Create assignment
    db.execute(
        "INSERT INTO assignments (round_id, proposal_id, bid_id, student_id, thesis_id, assigned_by, assigned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (round_id, proposal_id, int(bid_id), bid["student_id"], thesis_id, admin_user["id"], now),
    )
    # Mark winning bid as Accepted, competing bids as Rejected
    db.execute("UPDATE bids SET status = 'Accepted' WHERE id = ?", (int(bid_id),))
    db.execute(
        "UPDATE bids SET status = 'Rejected' WHERE proposal_id = ? AND round_id = ? AND id != ?",
        (proposal_id, round_id, int(bid_id)),
    )
    # If bid belongs to a bid_group, mark group as Assigned and other bids in group as Rejected
    bid_row = db.execute("SELECT bid_group_id FROM bids WHERE id = ?", (int(bid_id),)).fetchone()
    if bid_row and bid_row["bid_group_id"]:
        bg_id = bid_row["bid_group_id"]
        db.execute("UPDATE bid_groups SET status = 'Assigned' WHERE id = ?", (bg_id,))
        db.execute(
            "UPDATE bids SET status = 'Rejected' WHERE bid_group_id = ? AND id != ?",
            (bg_id, int(bid_id)),
        )
    db.commit()
    flash(f"Assigned '{proposal['title']}' to {bid['student_name']}. Thesis #{thesis_id} created.", "success")
    return redirect(url_for("round_assignments", round_id=round_id))


@app.route("/rounds/<int:round_id>/reject-group/<int:bid_group_id>", methods=["POST"])
@role_required("Admin")
def round_reject_group(round_id, bid_group_id):
    """Reject an entire bid group (student's 3 choices)."""
    db = get_db()
    bg = db.execute("SELECT * FROM bid_groups WHERE id = ? AND round_id = ?",
                    (bid_group_id, round_id)).fetchone()
    if not bg:
        abort(404)
    if bg["status"] != "Pending":
        flash("This bid group has already been processed.", "danger")
        return redirect(url_for("round_assignments", round_id=round_id))
    db.execute("UPDATE bid_groups SET status = 'Rejected' WHERE id = ?", (bid_group_id,))
    db.execute("UPDATE bids SET status = 'Rejected' WHERE bid_group_id = ?", (bid_group_id,))
    db.commit()
    student = db.execute("SELECT name FROM users WHERE id = ?", (bg["student_id"],)).fetchone()
    flash(f"Rejected all bids from {student['name']}.", "success")
    return redirect(url_for("round_assignments", round_id=round_id))


# ---------------------------------------------------------------------------
# Routes – My Bids (Student)
# ---------------------------------------------------------------------------
@app.route("/bids/mine")
@login_required
def my_bids():
    user = get_current_user()
    if user["role"] != "Student":
        flash("Only students can view their bids.", "danger")
        return redirect(url_for("dashboard"))
    db = get_db()
    bids = db.execute(
        "SELECT b.*, p.title AS proposal_title, p.status AS proposal_status, "
        "u.name AS professor_name, "
        "br.name AS round_name, br.status AS round_status "
        "FROM bids b "
        "JOIN proposals p ON b.proposal_id = p.id "
        "JOIN users u ON p.created_by_professor_id = u.id "
        "JOIN bidding_rounds br ON b.round_id = br.id "
        "WHERE b.student_id = ? ORDER BY br.created_at DESC, b.created_at DESC",
        (user["id"],),
    ).fetchall()
    open_round = get_open_round()
    return render_template("my_bids.html", bids=bids, open_round=open_round)


# ---------------------------------------------------------------------------
# Routes – Professor Bidding Management (Part B)
# ---------------------------------------------------------------------------
@app.route("/bidding/manage")
@role_required("Professor")
def bidding_manage():
    db = get_db()
    user = get_current_user()
    open_round = get_open_round()
    in_round = []
    available = []
    if open_round:
        in_round = db.execute(
            "SELECT p.*, pr.id AS pr_id, "
            "(SELECT COUNT(*) FROM bids b WHERE b.proposal_id = p.id AND b.round_id = ?) AS bid_count "
            "FROM proposals p "
            "JOIN proposal_rounds pr ON pr.proposal_id = p.id AND pr.round_id = ? "
            "WHERE p.created_by_professor_id = ? ORDER BY p.title",
            (open_round["id"], open_round["id"], user["id"]),
        ).fetchall()
        in_round_ids = {p["id"] for p in in_round}
        all_published = db.execute(
            "SELECT p.* FROM proposals p "
            "WHERE p.created_by_professor_id = ? AND p.status = 'Published' "
            "AND NOT EXISTS (SELECT 1 FROM assignments WHERE proposal_id = p.id) "
            "ORDER BY p.title",
            (user["id"],),
        ).fetchall()
        available = [p for p in all_published if p["id"] not in in_round_ids]
    return render_template("bidding_manage.html",
                           open_round=open_round, in_round=in_round,
                           available=available)


@app.route("/bidding/manage/add/<int:proposal_id>", methods=["POST"])
@role_required("Professor")
def bidding_manage_add(proposal_id):
    db = get_db()
    user = get_current_user()
    open_round = get_open_round()
    if not open_round:
        flash("No bidding round is currently open.", "danger")
        return redirect(url_for("bidding_manage"))
    proposal = db.execute("SELECT * FROM proposals WHERE id = ? AND created_by_professor_id = ?",
                          (proposal_id, user["id"])).fetchone()
    if not proposal or proposal["status"] != "Published":
        flash("Invalid proposal.", "danger")
        return redirect(url_for("bidding_manage"))
    existing = db.execute("SELECT 1 FROM proposal_rounds WHERE proposal_id = ? AND round_id = ?",
                          (proposal_id, open_round["id"])).fetchone()
    if existing:
        flash("Proposal is already in this round.", "danger")
        return redirect(url_for("bidding_manage"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("INSERT INTO proposal_rounds (proposal_id, round_id, added_by, added_at) VALUES (?, ?, ?, ?)",
               (proposal_id, open_round["id"], user["id"], now))
    db.commit()
    flash(f"'{proposal['title']}' added to {open_round['name']}.", "success")
    return redirect(url_for("bidding_manage"))


@app.route("/bidding/manage/remove/<int:proposal_id>", methods=["POST"])
@role_required("Professor")
def bidding_manage_remove(proposal_id):
    db = get_db()
    user = get_current_user()
    open_round = get_open_round()
    if not open_round:
        flash("No bidding round is currently open.", "danger")
        return redirect(url_for("bidding_manage"))
    # Only remove if no bids yet
    has_bids = db.execute(
        "SELECT 1 FROM bids WHERE proposal_id = ? AND round_id = ?",
        (proposal_id, open_round["id"]),
    ).fetchone()
    if has_bids:
        flash("Cannot remove: this proposal already has bids in this round.", "danger")
        return redirect(url_for("bidding_manage"))
    db.execute("DELETE FROM proposal_rounds WHERE proposal_id = ? AND round_id = ? AND added_by = ?",
               (proposal_id, open_round["id"], user["id"]))
    db.commit()
    flash("Proposal removed from round.", "success")
    return redirect(url_for("bidding_manage"))


# ---------------------------------------------------------------------------
# Routes – Admin Bidding Management (legacy redirects)
# ---------------------------------------------------------------------------
@app.route("/admin/bidding")
@role_required("Admin")
def admin_bidding():
    """Legacy redirect — now part of unified governance."""
    return redirect(url_for("bidding_governance"))


@app.route("/admin/bidding/add/<int:proposal_id>", methods=["POST"])
@role_required("Admin")
def admin_bidding_add(proposal_id):
    db = get_db()
    user = get_current_user()
    open_round = get_open_round()
    if not open_round:
        flash("No bidding round is currently open.", "danger")
        return redirect(url_for("bidding_governance"))
    proposal = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not proposal or proposal["status"] != "Published":
        flash("Invalid proposal.", "danger")
        return redirect(url_for("bidding_governance"))
    existing = db.execute("SELECT 1 FROM proposal_rounds WHERE proposal_id = ? AND round_id = ?",
                          (proposal_id, open_round["id"])).fetchone()
    if existing:
        flash("Proposal is already in this round.", "danger")
        return redirect(url_for("bidding_governance"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("INSERT INTO proposal_rounds (proposal_id, round_id, added_by, added_at) VALUES (?, ?, ?, ?)",
               (proposal_id, open_round["id"], user["id"], now))
    db.commit()
    flash(f"Proposal added to {open_round['name']}.", "success")
    return redirect(url_for("bidding_governance"))


@app.route("/admin/bidding/remove/<int:proposal_id>", methods=["POST"])
@role_required("Admin")
def admin_bidding_remove(proposal_id):
    db = get_db()
    open_round = get_open_round()
    if not open_round:
        flash("No bidding round is currently open.", "danger")
        return redirect(url_for("bidding_governance"))
    has_bids = db.execute("SELECT 1 FROM bids WHERE proposal_id = ? AND round_id = ?",
                          (proposal_id, open_round["id"])).fetchone()
    if has_bids:
        flash("Cannot remove: proposal has bids.", "danger")
        return redirect(url_for("bidding_governance"))
    db.execute("DELETE FROM proposal_rounds WHERE proposal_id = ? AND round_id = ?",
               (proposal_id, open_round["id"]))
    db.commit()
    flash("Proposal removed from round.", "success")
    return redirect(url_for("bidding_governance"))


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def seed():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")

    existing = db.execute("SELECT COUNT(*) FROM student").fetchone()[0]
    if existing > 0:
        db.close()
        return

    students = [
        ("Alice Johnson", "alice@university.edu"),
        ("Bob Smith", "bob@university.edu"),
        ("Carol Lee", "carol@university.edu"),
        ("David Kim", "david@university.edu"),
        ("Eva Martinez", "eva@university.edu"),
    ]
    for name, email in students:
        db.execute("INSERT INTO student (name, email) VALUES (?, ?)", (name, email))

    supervisors = [
        ("Dr. Sarah Chen", "s.chen@university.edu", "Computer Science"),
        ("Prof. Michael Brown", "m.brown@university.edu", "Data Science"),
        ("Dr. Laura Wilson", "l.wilson@university.edu", "Information Systems"),
    ]
    for name, email, dept in supervisors:
        db.execute("INSERT INTO supervisor (name, email, department) VALUES (?, ?, ?)",
                   (name, email, dept))

    external_reviewers = [
        ("Dr. James Porter", "j.porter@review-board.org"),
        ("Prof. Amina Yusuf", "a.yusuf@external-review.edu"),
    ]
    for name, email in external_reviewers:
        db.execute("INSERT INTO external_reviewer (name, email) VALUES (?, ?)", (name, email))

    committee_members = [
        ("Dr. Helen Zhao", "h.zhao@university.edu"),
        ("Prof. Robert Tanaka", "r.tanaka@university.edu"),
        ("Dr. Fatima Al-Rashid", "f.alrashid@university.edu"),
        ("Prof. Erik Johansson", "e.johansson@university.edu"),
    ]
    for name, email in committee_members:
        db.execute("INSERT INTO committee_member (name, email) VALUES (?, ?)", (name, email))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # (title, abstract, student_id, supervisor_id, external_reviewer_id, submission_deadline, status,
    #  is_challenging, is_external, external_supervisor_name, primary_topic, secondary_topic,
    #  start_date, expected_end, terminated_at, three_month_review_done, assignment_source, notes)
    theses = [
        ("Machine Learning for Early Disease Detection",
         "Using ML algorithms to detect diseases from medical imaging data.",
         1, 1, 1, "2026-06-30", "ExternallyReviewed",
         1, 1, "Dr. Marco Rossi", "Machine learning", "Image processing and computer vision",
         "2025-09-01", "2026-06-30", None, 1, "OLD", None),
        ("Blockchain-Based Academic Credential Verification",
         "A decentralized system for verifying academic transcripts and diplomas.",
         2, 2, None, "2026-08-15", "Approved",
         1, 0, None, "Blockchain", "Computer Security",
         "2025-06-01", "2026-08-15", "2026-02-20", 1, "OLD", None),
        ("Natural Language Processing for Legal Documents",
         "Automating analysis and summarization of legal contracts using NLP and transformer architectures.",
         3, 3, None, "2026-09-01", "Draft",
         0, 0, None, "Natural language processing", "Software engineering",
         "2026-01-15", "2026-09-01", None, 0, "NEW", None),
        ("IoT-Enabled Smart Campus Energy Management",
         "Designing an IoT framework to optimize energy consumption across campus buildings.",
         4, 1, 2, "2026-07-15", "Submitted",
         1, 1, "Prof. Luigi Bianchi", "Internet of Things", "Distributed computing",
         "2025-10-01", "2026-07-15", None, 1, "OLD", None),
        ("Ethical AI: Bias Detection in Hiring Algorithms",
         "Investigating and mitigating bias in AI-powered recruitment tools using fairness-aware ML.",
         5, None, None, "2026-03-01", "RevisionRequested",
         0, 0, None, "Machine learning", "Data protection and privacy",
         "2025-11-01", "2026-03-01", None, 0, "NEW", None),
    ]
    for (title, abstract, sid, supid, erid, deadline, status,
         is_ch, is_ext, ext_sup, ptopic, stopic, sdate, edate, term_at,
         three_m, asrc, notes) in theses:
        cur = db.execute(
            "INSERT INTO thesis (title, abstract, student_id, supervisor_id, external_reviewer_id, "
            "submission_deadline, status, is_challenging, is_external, external_supervisor_name, "
            "primary_topic, secondary_topic, start_date, expected_end, terminated_at, "
            "three_month_review_done, assignment_source, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, abstract, sid, supid, erid, deadline, status,
             is_ch, is_ext, ext_sup, ptopic, stopic, sdate, edate, term_at,
             three_m, asrc, notes, now, now),
        )
        tid = cur.lastrowid
        db.execute(
            "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
            "VALUES (?, NULL, 'Draft', ?)", (tid, now),
        )
        if status != "Draft":
            transitions_path = {
                "Submitted": ["Submitted"],
                "UnderReview": ["Submitted", "UnderReview"],
                "ExternallyReviewed": ["Submitted", "ExternallyReviewed"],
                "RevisionRequested": ["Submitted", "UnderReview", "RevisionRequested"],
                "Approved": ["Submitted", "UnderReview", "Approved"],
                "FinalSubmitted": ["Submitted", "UnderReview", "Approved", "FinalSubmitted"],
                "Completed": ["Submitted", "UnderReview", "Approved", "FinalSubmitted", "Completed"],
            }
            prev = "Draft"
            for s in transitions_path.get(status, []):
                db.execute(
                    "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
                    "VALUES (?, ?, ?, ?)", (tid, prev, s, now),
                )
                prev = s

    # Milestones for thesis 1 (UnderReview)
    milestones_t1 = [
        (1, "Literature Review", "2026-02-01", "Submitted", "Comprehensive review completed"),
        (1, "Methodology Design", "2026-03-15", "InProgress", "Designing experiment pipeline"),
        (1, "Data Collection", "2026-05-01", "Planned", None),
        (1, "Final Defense", "2026-08-01", "Planned", None),
    ]
    for tid, mtype, due, status, notes in milestones_t1:
        db.execute(
            "INSERT INTO milestone (thesis_id, type, due_date, status, notes) VALUES (?, ?, ?, ?, ?)",
            (tid, mtype, due, status, notes),
        )

    # Milestones for thesis 2 (Approved)
    milestones_t2 = [
        (2, "Literature Review", "2026-01-15", "Accepted", "Approved by supervisor"),
        (2, "Prototype Development", "2026-03-01", "Submitted", "Smart contract prototype ready"),
        (2, "Testing & Evaluation", "2026-05-01", "Planned", None),
    ]
    for tid, mtype, due, status, notes in milestones_t2:
        db.execute(
            "INSERT INTO milestone (thesis_id, type, due_date, status, notes) VALUES (?, ?, ?, ?, ?)",
            (tid, mtype, due, status, notes),
        )

    # Submissions
    submissions = [
        (1, "proposal", now, "Initial proposal for ML disease detection research.", "https://docs.google.com/document/d/abc123"),
        (1, "interim", now, "Interim report covering literature review and initial experiments.", None),
        (2, "proposal", now, "Blockchain credential verification proposal.", "https://docs.google.com/document/d/def456"),
        (4, "proposal", now, "IoT smart campus proposal with architecture diagrams.", "https://drive.google.com/file/d/ghi789"),
    ]
    for tid, kind, sub_at, comment, attachment in submissions:
        db.execute(
            "INSERT INTO submission (thesis_id, kind, submitted_at, comment, attachment_path_or_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (tid, kind, sub_at, comment, attachment),
        )

    # Committee assignments
    # Thesis 1: committee members 1, 2, 3
    for cid in [1, 2, 3]:
        db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)", (1, cid))
    # Thesis 2: committee members 1, 2 (both approved — thesis is Approved)
    for cid in [1, 2]:
        db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)", (2, cid))
    # Thesis 4: committee members 2, 4
    for cid in [2, 4]:
        db.execute("INSERT INTO thesis_committee (thesis_id, committee_member_id) VALUES (?, ?)", (4, cid))

    # Decision logs
    # Thesis 1: member 1 approved, member 2 approved, member 3 pending (no decision yet)
    db.execute("INSERT INTO decision_log (thesis_id, committee_member_id, decision, comment, created_at) "
               "VALUES (?, ?, ?, ?, ?)", (1, 1, "Approve", "Strong methodology and clear objectives.", now))
    db.execute("INSERT INTO decision_log (thesis_id, committee_member_id, decision, comment, created_at) "
               "VALUES (?, ?, ?, ?, ?)", (1, 2, "Approve", "Good literature review. Approved.", now))
    # Thesis 2: both members approved
    db.execute("INSERT INTO decision_log (thesis_id, committee_member_id, decision, comment, created_at) "
               "VALUES (?, ?, ?, ?, ?)", (2, 1, "Approve", "Excellent prototype.", now))
    db.execute("INSERT INTO decision_log (thesis_id, committee_member_id, decision, comment, created_at) "
               "VALUES (?, ?, ?, ?, ?)", (2, 2, "Approve", "Solid technical foundation.", now))

    # Seed topics
    for topic in TOPIC_TAXONOMY:
        db.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (topic,))

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Seed users
# ---------------------------------------------------------------------------
def seed_users():
    db = sqlite3.connect(DATABASE)
    existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        db.close()
        return
    default_pw = generate_password_hash("password123")
    users = [
        ("Admin User", "admin@university.edu", "Admin"),
        ("Prof. Sarah Chen", "prof.chen@university.edu", "Professor"),
        ("Prof. Michael Brown", "prof.brown@university.edu", "Professor"),
        ("Alice Johnson", "alice.student@university.edu", "Student"),
        ("Bob Smith", "bob.student@university.edu", "Student"),
        ("Carol Lee", "carol.student@university.edu", "Student"),
        ("Diana Park", "diana.student@university.edu", "Student"),
    ]
    for name, email, role in users:
        db.execute("INSERT INTO users (name, email, role, password_hash) VALUES (?, ?, ?, ?)",
                   (name, email, role, default_pw))
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Seed proposals, rounds, bids
# ---------------------------------------------------------------------------
def seed_proposals():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    existing = db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    if existing > 0:
        db.close()
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # Proposals: Prof. Sarah Chen = user 2, Prof. Michael Brown = user 3
    proposals = [
        ("Federated Learning for Healthcare Data Privacy",
         "Investigate federated learning approaches that enable collaborative model training across hospitals without sharing raw patient data. The project explores privacy-preserving distributed machine learning techniques.",
         2, "Published"),
        ("Explainable AI for Financial Risk Assessment",
         "Develop interpretable machine learning models for credit scoring that satisfy regulatory transparency requirements. Apply SHAP and LIME to banking datasets.",
         2, "Draft"),
        ("Digital Twin Simulation for Smart City Infrastructure",
         "Build a digital twin framework to simulate and optimize urban traffic, energy, and water systems in real time. Integrate IoT sensor feeds with 3D city models.",
         3, "Published"),
        ("Secure Multi-Party Computation for Genomic Data",
         "Design protocols for privacy-preserving genomic analysis using secure multi-party computation and homomorphic encryption techniques.",
         2, "Published"),
        ("Graph Neural Networks for Social Network Analysis",
         "Apply graph neural networks to detect communities, predict links, and identify influence patterns in large-scale social networks.",
         3, "Published"),
        ("Automated Software Testing with Reinforcement Learning",
         "Use reinforcement learning agents to generate test cases and explore state spaces for improved software quality assurance.",
         3, "Published"),
        ("Edge Computing for Real-Time Video Analytics",
         "Develop an edge computing framework for processing video streams in real time for surveillance and autonomous driving applications.",
         2, "Published"),
    ]
    for title, desc, prof_id, status in proposals:
        db.execute(
            "INSERT INTO proposals (title, description, created_by_professor_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, desc, prof_id, status, now, now),
        )

    # Round 1 (Closed) — completed round with assignment
    db.execute(
        "INSERT INTO bidding_rounds (name, start_date, end_date, proposal_collection_end, status, created_at) "
        "VALUES (?, ?, ?, ?, 'Closed', ?)",
        ("Spring 2026 Bidding Round", "2026-02-15", "2026-04-15", "2026-03-01", now),
    )
    # Round 2 (Open) — current active round with two-phase dates
    db.execute(
        "INSERT INTO bidding_rounds (name, start_date, end_date, proposal_collection_end, status, created_at) "
        "VALUES (?, ?, ?, ?, 'Open', ?)",
        ("Summer 2026 Bidding Round", "2026-05-01", "2026-07-01", "2026-05-20", now),
    )

    # Bid groups for Round 1 (Closed):
    # Alice chose proposals 1, 3, 4 → Admin assigned proposal 1
    # Bob chose proposals 1, 3, 5 → Admin rejected (or pending)
    alice_motivation = "I have a strong background in ML and healthcare informatics. My internship at a hospital gave me insight into data privacy challenges. I am also interested in IoT and security topics."
    bob_motivation = "I am passionate about federated learning and distributed systems. I have completed coursework in privacy-preserving ML and smart city tech."

    # Alice's bid group (Round 1) — Assigned
    db.execute(
        "INSERT INTO bid_groups (student_id, round_id, status, motivation_text, created_at) "
        "VALUES (?, ?, 'Assigned', ?, ?)", (4, 1, alice_motivation, now))
    alice_bg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Bob's bid group (Round 1) — Rejected
    db.execute(
        "INSERT INTO bid_groups (student_id, round_id, status, motivation_text, created_at) "
        "VALUES (?, ?, 'Rejected', ?, ?)", (5, 1, bob_motivation, now))
    bob_bg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Alice's 3 bids in Round 1
    bids_data = [
        (alice_bg_id, 1, 4, 1, 1, "Accepted", alice_motivation),   # proposal 1, rank 1 → Accepted
        (alice_bg_id, 3, 4, 1, 2, "Rejected", alice_motivation),   # proposal 3, rank 2
        (alice_bg_id, 4, 4, 1, 3, "Rejected", alice_motivation),   # proposal 4, rank 3
    ]
    # Bob's 3 bids in Round 1
    bids_data += [
        (bob_bg_id, 1, 5, 1, 1, "Rejected", bob_motivation),   # proposal 1, rank 1
        (bob_bg_id, 3, 5, 1, 2, "Rejected", bob_motivation),   # proposal 3, rank 2
        (bob_bg_id, 5, 5, 1, 3, "Rejected", bob_motivation),   # proposal 5, rank 3
    ]
    for bg_id, prop_id, student_id, round_id, rank, status, motivation in bids_data:
        db.execute(
            "INSERT INTO bids (bid_group_id, proposal_id, student_id, round_id, rank, status, motivation_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bg_id, prop_id, student_id, round_id, rank, status, motivation, now),
        )

    # Carol's bid group for Round 2 (Open) — Pending
    carol_motivation = "I am fascinated by smart city technologies and graph analytics. I have experience with Python data science stack and would love to work on cutting-edge research."
    db.execute(
        "INSERT INTO bid_groups (student_id, round_id, status, motivation_text, created_at) "
        "VALUES (?, ?, 'Pending', ?, ?)", (6, 2, carol_motivation, now))
    carol_bg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    carol_bids = [
        (carol_bg_id, 3, 6, 2, 1, "Pending", carol_motivation),   # Digital Twin, rank 1
        (carol_bg_id, 5, 6, 2, 2, "Pending", carol_motivation),   # Graph Neural Networks, rank 2
        (carol_bg_id, 6, 6, 2, 3, "Pending", carol_motivation),   # Automated Testing, rank 3
    ]
    for bg_id, prop_id, student_id, round_id, rank, status, motivation in carol_bids:
        db.execute(
            "INSERT INTO bids (bid_group_id, proposal_id, student_id, round_id, rank, status, motivation_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bg_id, prop_id, student_id, round_id, rank, status, motivation, now),
        )

    # Create thesis from assignment of proposal 1 to Alice
    # Alice = student_id 1 in student table, supervisor = 1 (Dr. Sarah Chen)
    thesis_cur = db.execute(
        "INSERT INTO thesis (title, abstract, student_id, supervisor_id, status, "
        "is_challenging, is_external, primary_topic, secondary_topic, "
        "start_date, expected_end, three_month_review_done, assignment_source, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Federated Learning for Healthcare Data Privacy",
         "Investigate federated learning approaches that enable collaborative model training across hospitals without sharing raw patient data. The project explores privacy-preserving distributed machine learning techniques.",
         1, 1,
         1, 0, "Machine learning", "Data protection and privacy",
         "2026-02-20", "2026-08-20", 0, "NEW",
         now, now),
    )
    assigned_thesis_id = thesis_cur.lastrowid
    db.execute(
        "INSERT INTO status_history (thesis_id, old_status, new_status, changed_at) "
        "VALUES (?, NULL, 'Draft', ?)", (assigned_thesis_id, now),
    )

    # Assignment record: round 1, proposal 1, bid 1 (Alice), admin (user 1)
    db.execute(
        "INSERT INTO assignments (round_id, proposal_id, bid_id, student_id, thesis_id, assigned_by, assigned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 1, 1, 4, assigned_thesis_id, 1, now),
    )

    # Assign professor reviewers to theses (Part B/G seed)
    # Thesis 1 (sup: Dr. Sarah Chen/user 2) → reviewer: Prof. Michael Brown (user 3)
    db.execute("UPDATE thesis SET reviewer_id = 3 WHERE thesis_id = 1")
    # Thesis 2 (sup: Prof. Michael Brown/user 3) → reviewer: Prof. Sarah Chen (user 2)
    db.execute("UPDATE thesis SET reviewer_id = 2 WHERE thesis_id = 2")
    # Thesis 4 (sup: Dr. Sarah Chen/user 2) → reviewer: Prof. Michael Brown (user 3)
    db.execute("UPDATE thesis SET reviewer_id = 3 WHERE thesis_id = 4")
    # Thesis 3 and 5 intentionally left without reviewer (to show "missing" in admin stats)
    # Assigned thesis also gets reviewer
    db.execute("UPDATE thesis SET reviewer_id = 3 WHERE thesis_id = ?", (assigned_thesis_id,))

    # Proposal-round associations
    # Round 1 (Closed): proposals 1, 3, 4, 5 participated
    # Round 2 (Open): proposals 3, 4, 5, 6, 7 available
    proposal_rounds = [
        (1, 1, 1),  # proposal 1 in round 1, added by admin
        (3, 1, 3),  # proposal 3 in round 1, added by Prof Brown
        (4, 1, 2),  # proposal 4 in round 1, added by Prof Chen
        (5, 1, 3),  # proposal 5 in round 1, added by Prof Brown
        (3, 2, 3),  # proposal 3 in round 2, added by Prof Brown
        (4, 2, 2),  # proposal 4 in round 2, added by Prof Chen
        (5, 2, 3),  # proposal 5 in round 2, added by Prof Brown
        (6, 2, 3),  # proposal 6 in round 2, added by Prof Brown
        (7, 2, 2),  # proposal 7 in round 2, added by Prof Chen
    ]
    for pid, rid, uid in proposal_rounds:
        db.execute(
            "INSERT INTO proposal_rounds (proposal_id, round_id, added_by, added_at) VALUES (?, ?, ?, ?)",
            (pid, rid, uid, now),
        )

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Startup: ensure DB is ready (works under both gunicorn and direct run)
# ---------------------------------------------------------------------------
def _startup():
    """Initialise database, run migrations, and seed demo data."""
    init_db()
    migrate_db()
    seed()
    seed_users()
    seed_proposals()

_startup()

# ---------------------------------------------------------------------------
# Entry point (local development only — production uses gunicorn)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Thesis Workflow Manager on http://127.0.0.1:{port}")
    app.run(debug=True, host="0.0.0.0", port=port)
