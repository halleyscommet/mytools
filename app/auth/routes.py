import os
from uuid import uuid4
from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template, flash

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _valid_passwords() -> list[str]:
    raw = os.environ.get("AUTH_PASSWORDS") or os.environ.get("AUTH_PASSWORD", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password in _valid_passwords():
            session["authenticated"] = True
            session["session_id"] = session.get("session_id") or uuid4().hex
            session.permanent = True
            next_url = request.args.get("next") or "/"
            return redirect(next_url)
        flash("Incorrect password.")
    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
