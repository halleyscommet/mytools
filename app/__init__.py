import os
from datetime import timedelta
from flask import Flask, redirect, render_template, request, session, url_for
from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))
    app.permanent_session_lifetime = timedelta(days=7)

    from .auth import auth_bp
    from .fileshare import fileshare_bp
    from .fileshare.routes import MAX_UPLOAD_BYTES, format_upload_limit

    app.register_blueprint(auth_bp)
    app.register_blueprint(fileshare_bp)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.route("/")
    def index():
        if not session.get("authenticated"):
            return redirect(url_for("auth.login", next=request.path))
        return render_template("dashboard.html", session_id=session.get("session_id"))

    @app.errorhandler(413)
    def request_entity_too_large(error):
        upload_limit_label = format_upload_limit(app.config["MAX_CONTENT_LENGTH"])
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return (
                {"ok": False, "error": f"The upload limit is {upload_limit_label}."},
                413,
            )
        return (
            render_template(
                "fileshare/index.html",
                files=[],
                view="upload",
                session_id=session.get("session_id"),
                upload_limit_label=upload_limit_label,
                upload_error="That file is too large for the current limit.",
            ),
            413,
        )

    return app
