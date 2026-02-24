import sqlite3
import os
from datetime import datetime, date, timezone
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, g, jsonify, abort
)

app = Flask(__name__)
app.secret_key = "thesis-workflow-secret-key"

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thesis.db")

# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------
THESIS_STATUSES = [
    "Draft", "Submitted", "UnderReview", "ExternallyReviewed",
    "RevisionRequested", "Approved", "FinalSubmitted", "Completed", "Late",
]

THESIS_TRANSITIONS = {
    "Draft":               ["Submitted"],
    "Submitted":           ["UnderReview", "ExternallyReviewed"],
    "UnderReview":         ["RevisionRequested", "Approved"],
    "ExternallyReviewed":  ["Approved"],
    "RevisionRequested":   ["Submitted"],
    "Approved":            ["FinalSubmitted"],
    "FinalSubmitted":      ["Completed"],
    "Completed":           [],
    "Late":                [],
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
    """)
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
        today=date.today().isoformat(),
        now=lambda: datetime.now(timezone.utc),
    )

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
# Routes – Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    db = get_db()
    counts = {}
    for s in THESIS_STATUSES:
        row = db.execute(
            "SELECT COUNT(*) AS c FROM thesis WHERE status = ?", (s,)
        ).fetchone()
        counts[s] = row["c"]
    total = sum(counts.values())
    recent = db.execute(
        "SELECT t.*, s.name AS student_name "
        "FROM thesis t JOIN student s ON t.student_id = s.student_id "
        "ORDER BY t.updated_at DESC LIMIT 5"
    ).fetchall()
    return render_template("dashboard.html", counts=counts, total=total, recent=recent)

# ---------------------------------------------------------------------------
# Routes – Theses
# ---------------------------------------------------------------------------
@app.route("/theses")
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
    return render_template("thesis_detail.html", thesis=thesis,
                           milestones=milestones, submissions=submissions,
                           history=history, supervisors=supervisors, reviewers=reviewers,
                           all_committee=all_committee,
                           assigned_committee_ids=assigned_committee_ids,
                           can_approve=can_approve, approve_reason=approve_reason,
                           member_decisions=member_decisions,
                           decision_log=decision_log)


@app.route("/theses/<int:thesis_id>/edit", methods=["GET", "POST"])
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
def thesis_delete(thesis_id):
    db = get_db()
    db.execute("DELETE FROM thesis WHERE thesis_id = ?", (thesis_id,))
    db.commit()
    flash("Thesis deleted.", "success")
    return redirect(url_for("thesis_list"))


@app.route("/theses/<int:thesis_id>/transition", methods=["POST"])
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
def thesis_assign_supervisor(thesis_id):
    db = get_db()
    supervisor_id = request.form.get("supervisor_id") or None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("UPDATE thesis SET supervisor_id=?, updated_at=? WHERE thesis_id=?",
               (supervisor_id and int(supervisor_id), now, thesis_id))
    db.commit()
    flash("Supervisor assigned.", "success")
    return redirect(url_for("thesis_detail", thesis_id=thesis_id))


@app.route("/theses/<int:thesis_id>/assign-reviewer", methods=["POST"])
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
    # (title, abstract, student_id, supervisor_id, external_reviewer_id, submission_deadline, status)
    theses = [
        ("Machine Learning for Early Disease Detection", "Using ML algorithms to detect diseases from medical imaging data.", 1, 1, 1, "2026-06-30", "ExternallyReviewed"),
        ("Blockchain-Based Academic Credential Verification", "A decentralized system for verifying academic transcripts and diplomas.", 2, 2, None, "2026-08-15", "Approved"),
        ("Natural Language Processing for Legal Documents", "Automating analysis and summarization of legal contracts.", 3, 3, None, "2026-09-01", "Draft"),
        ("IoT-Enabled Smart Campus Energy Management", "Designing an IoT framework to optimize energy consumption across campus buildings.", 4, 1, 2, "2026-07-15", "Submitted"),
        ("Ethical AI: Bias Detection in Hiring Algorithms", "Investigating and mitigating bias in AI-powered recruitment tools.", 5, None, None, "2026-03-01", "RevisionRequested"),
    ]
    for title, abstract, sid, supid, erid, deadline, status in theses:
        cur = db.execute(
            "INSERT INTO thesis (title, abstract, student_id, supervisor_id, external_reviewer_id, "
            "submission_deadline, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, abstract, sid, supid, erid, deadline, status, now, now),
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

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
try:
    print(f"Initializing database at: {DATABASE}")
    init_db()
    migrate_db()
    seed()
    print("Database ready.")
except Exception as e:
    print(f"DB init error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Thesis Workflow Manager on http://127.0.0.1:{port}")
    app.run(debug=True, host="0.0.0.0", port=port)
