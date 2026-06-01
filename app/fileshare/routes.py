import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from ..auth.routes import login_required

fileshare_bp = Blueprint("fileshare", __name__, url_prefix="/files")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def _upload_limit_bytes() -> int:
    raw_value = os.environ.get("MAX_UPLOAD_BYTES")
    if raw_value is None:
        return 2 * 1024 * 1024 * 1024

    try:
        return int(raw_value)
    except ValueError:
        return 2 * 1024 * 1024 * 1024


MAX_UPLOAD_BYTES = _upload_limit_bytes()


def format_upload_limit(byte_count: int) -> str:
    gigabytes = byte_count / (1024 * 1024 * 1024)
    if gigabytes.is_integer():
        return f"{int(gigabytes)} GB"
    return f"{gigabytes:.1f} GB"


def _uploads_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _stored_name(original_name: str) -> str:
    safe_name = secure_filename(original_name) or "file"
    return f"{uuid4().hex}__{safe_name}"


def _display_name(stored_name: str) -> str:
    if "__" in stored_name:
        return stored_name.split("__", 1)[1]
    return stored_name


def _file_items() -> list[dict[str, object]]:
    uploads_dir = _uploads_dir()
    items: list[dict[str, object]] = []

    for path in uploads_dir.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        items.append(
            {
                "stored_name": path.name,
                "display_name": _display_name(path.name),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
            }
        )

    items.sort(key=lambda item: item["modified"], reverse=True)
    return items


@fileshare_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    view = request.args.get("view", "upload")
    if view not in {"upload", "browse"}:
        view = "upload"

    if request.method == "POST":
        uploads = request.files.getlist("files")
        saved_count = 0

        for upload in uploads:
            if not upload or not upload.filename:
                continue
            target_path = _uploads_dir() / _stored_name(upload.filename)
            upload.save(target_path)
            saved_count += 1

        if saved_count:
            flash(f"Uploaded {saved_count} file{'s' if saved_count != 1 else ''}.")
        else:
            flash("Choose at least one file to upload.")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                {
                    "ok": True,
                    "redirect": url_for("fileshare.index", view="browse"),
                }
            )

        return redirect(url_for("fileshare.index", view="browse"))

    return render_template(
        "fileshare/index.html",
        files=_file_items(),
        view=view,
        session_id=session.get("session_id"),
        upload_limit_label=format_upload_limit(MAX_UPLOAD_BYTES),
    )


@fileshare_bp.route("/download/<path:stored_name>")
@login_required
def download_file(stored_name: str):
    return send_from_directory(
        _uploads_dir(),
        stored_name,
        as_attachment=True,
        download_name=_display_name(stored_name),
    )
