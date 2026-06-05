import json
import mimetypes
import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    has_request_context,
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
METADATA_PATH = DATA_DIR / ".fileshare_index.json"
TEXT_PREVIEW_BYTE_LIMIT = 4096
TEXT_PREVIEW_LINE_LIMIT = 6
TEXT_PREVIEW_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-javascript",
    "application/x-python-code",
}
TEXT_PREVIEW_EXTENSIONS = {
    ".bash",
    ".cfg",
    ".css",
    ".csv",
    ".htm",
    ".html",
    ".ini",
    ".js",
    ".jsx",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".scm",
    ".scss",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".tsv",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}


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


def _iter_upload_files() -> list[Path]:
    uploads_dir = _uploads_dir()
    return [
        path
        for path in uploads_dir.iterdir()
        if path.is_file() and path.name != METADATA_PATH.name
    ]


def _load_metadata() -> dict[str, dict[str, str]]:
    if not METADATA_PATH.exists():
        return {}

    try:
        payload = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    files = payload.get("files", {})
    return files if isinstance(files, dict) else {}


def _save_metadata(records: dict[str, dict[str, str]]) -> None:
    _uploads_dir()
    temp_path = METADATA_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps({"files": records}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(METADATA_PATH)


def _stored_name(original_name: str) -> str:
    safe_name = secure_filename(original_name) or "file"
    return f"{uuid4().hex}__{safe_name}"


def _display_name(stored_name: str) -> str:
    if "__" in stored_name:
        return stored_name.split("__", 1)[1]
    return stored_name


def _guess_mime_type(original_name: str, stored_name: str = "") -> str:
    for candidate in (original_name, stored_name):
        mime_type, _ = mimetypes.guess_type(candidate)
        if mime_type:
            return mime_type
    return ""


def _is_text_previewable(mime_type: str, file_name: str) -> bool:
    suffix = Path(file_name).suffix.lower()
    return (
        mime_type.startswith("text/")
        or mime_type in TEXT_PREVIEW_MIME_TYPES
        or suffix in TEXT_PREVIEW_EXTENSIONS
    )


def _build_text_preview(file_path: Path) -> tuple[str, bool]:
    try:
        with file_path.open("rb") as file_handle:
            raw_bytes = file_handle.read(TEXT_PREVIEW_BYTE_LIMIT)
    except OSError:
        return "", False

    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    preview_lines = lines[:TEXT_PREVIEW_LINE_LIMIT]
    preview = "\n".join(preview_lines).rstrip()
    truncated = (
        len(lines) > TEXT_PREVIEW_LINE_LIMIT
        or len(raw_bytes) == TEXT_PREVIEW_BYTE_LIMIT
    )

    return preview, truncated


def _preview_details(
    file_path: Path, mime_type: str, display_name: str
) -> dict[str, object]:
    suffix = file_path.suffix.lower()

    if mime_type.startswith("image/"):
        return {
            "preview_kind": "image",
            "preview_text": "",
            "preview_truncated": False,
            "preview_label": "Image preview",
        }

    if mime_type.startswith("video/"):
        return {
            "preview_kind": "video",
            "preview_text": "",
            "preview_truncated": False,
            "preview_label": "Video preview",
        }

    if _is_text_previewable(mime_type, display_name):
        preview_text, truncated = _build_text_preview(file_path)
        return {
            "preview_kind": "text",
            "preview_text": preview_text,
            "preview_truncated": truncated,
            "preview_label": "Text preview",
        }

    preview_label = (
        "Blender file" if suffix == ".blend" else (mime_type or "unknown file type")
    )
    return {
        "preview_kind": "generic",
        "preview_text": "",
        "preview_truncated": False,
        "preview_label": preview_label,
    }


def _build_file_item(path: Path, record: dict[str, str]) -> dict[str, object]:
    stat = path.stat()
    original_name = record.get("original_name") or _display_name(path.name)
    mime_type = record.get("mime_type") or _guess_mime_type(original_name, path.name)
    preview_details = _preview_details(path, mime_type, original_name)
    share_token = record["share_token"]

    if has_request_context():
        share_url = url_for("fileshare.public_share", token=share_token, _external=True)
        download_url = url_for(
            "fileshare.public_download", token=share_token, _external=False
        )
        preview_url = url_for(
            "fileshare.public_file", token=share_token, _external=False
        )
    else:
        share_url = f"/files/share/{share_token}"
        download_url = f"/files/share/{share_token}/download"
        preview_url = f"/files/share/{share_token}/file"

    return {
        "stored_name": path.name,
        "display_name": original_name,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime),
        "mime_type": mime_type,
        "is_image": mime_type.startswith("image/"),
        **preview_details,
        "share_token": share_token,
        "share_url": share_url,
        "download_url": download_url,
        "preview_url": preview_url,
    }


def store_file_for_share(
    source_path: Path,
    original_name: str | None = None,
    mime_type: str = "",
) -> dict[str, object]:
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(source_path)

    uploads_dir = _uploads_dir()
    original_name = original_name or source_path.name
    target_path = uploads_dir / _stored_name(original_name)
    shutil.move(str(source_path), target_path)
    _upsert_metadata_for_file(target_path.name, original_name, mime_type)

    records = _load_metadata()
    return _build_file_item(target_path, records[target_path.name])


def _sync_metadata_with_files(file_names: list[str]) -> dict[str, dict[str, str]]:
    records = _load_metadata()
    changed = False

    for stored_name in file_names:
        record = records.get(stored_name)
        if record is None:
            records[stored_name] = {
                "share_token": uuid4().hex,
                "original_name": _display_name(stored_name),
                "mime_type": _guess_mime_type(_display_name(stored_name), stored_name),
            }
            changed = True
            continue

        if not record.get("original_name"):
            record["original_name"] = _display_name(stored_name)
            changed = True

        if not record.get("mime_type"):
            record["mime_type"] = _guess_mime_type(record["original_name"], stored_name)
            changed = True

    for stored_name in list(records):
        if stored_name not in file_names:
            del records[stored_name]
            changed = True

    if changed:
        _save_metadata(records)

    return records


def _record_for_token(token: str) -> tuple[str, dict[str, str]] | tuple[None, None]:
    records = _sync_metadata_with_files([path.name for path in _iter_upload_files()])

    for stored_name, record in records.items():
        if record.get("share_token") == token:
            return stored_name, record

    return None, None


def _upsert_metadata_for_file(
    stored_name: str,
    original_name: str,
    mime_type: str,
) -> None:
    records = _load_metadata()
    record = records.get(stored_name)

    if record is None:
        records[stored_name] = {
            "share_token": uuid4().hex,
            "original_name": original_name or _display_name(stored_name),
            "mime_type": mime_type or _guess_mime_type(original_name, stored_name),
        }
    else:
        record["original_name"] = (
            original_name or record.get("original_name") or _display_name(stored_name)
        )
        record["mime_type"] = (
            mime_type
            or record.get("mime_type")
            or _guess_mime_type(original_name, stored_name)
        )

    _save_metadata(records)


def _file_items() -> list[dict[str, object]]:
    uploads_dir = _uploads_dir()
    records = _sync_metadata_with_files([path.name for path in _iter_upload_files()])
    items: list[dict[str, object]] = []

    for path in _iter_upload_files():
        items.append(_build_file_item(path, records[path.name]))

    items.sort(key=lambda item: item["modified"], reverse=True)
    return items


def _share_page_metadata(
    display_name: str, size: int, modified: datetime, mime_type: str
) -> dict[str, str]:
    description = f"Shared file from My Tools: {display_name}"
    if size:
        description = f"{description} ({size} bytes)"
    description = f"{description} · Updated {modified.strftime('%Y-%m-%d %H:%M')}"

    metadata = {
        "page_title": display_name,
        "page_description": description,
        "og_type": "website",
        "twitter_card": "summary",
    }

    if mime_type.startswith("image/"):
        metadata["twitter_card"] = "summary_large_image"
    elif mime_type.startswith("video/"):
        metadata["og_type"] = "video.other"

    return metadata


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
            _upsert_metadata_for_file(
                target_path.name, upload.filename, upload.mimetype
            )
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


@fileshare_bp.route("/delete/<path:stored_name>", methods=["POST"])
@login_required
def delete_file(stored_name: str):
    file_path = _uploads_dir() / stored_name
    records = _load_metadata()

    if file_path.exists() and file_path.is_file():
        file_path.unlink()
        if stored_name in records:
            del records[stored_name]
            _save_metadata(records)
        flash("File deleted.")
    else:
        flash("File not found.")

    return redirect(url_for("fileshare.index", view="browse"))


@fileshare_bp.route("/download/<path:stored_name>")
@login_required
def download_file(stored_name: str):
    return send_from_directory(
        _uploads_dir(),
        stored_name,
        as_attachment=True,
        download_name=_display_name(stored_name),
    )


@fileshare_bp.route("/share/<token>")
def public_share(token: str):
    stored_name, record = _record_for_token(token)
    if not stored_name or not record:
        abort(404)

    file_path = _uploads_dir() / stored_name
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    stat = file_path.stat()
    mime_type = record.get("mime_type") or _guess_mime_type(
        record.get("original_name", ""), stored_name
    )
    preview_details = _preview_details(
        file_path, mime_type, record.get("original_name") or _display_name(stored_name)
    )
    file_item = {
        "stored_name": stored_name,
        "display_name": record.get("original_name") or _display_name(stored_name),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime),
        "mime_type": mime_type,
        "is_image": mime_type.startswith("image/"),
        **preview_details,
        "share_url": url_for("fileshare.public_share", token=token, _external=True),
        "download_url": url_for(
            "fileshare.public_download", token=token, _external=True
        ),
        "preview_url": url_for("fileshare.public_file", token=token, _external=True),
    }

    share_metadata = _share_page_metadata(
        file_item["display_name"],
        file_item["size"],
        file_item["modified"],
        file_item["mime_type"],
    )

    return render_template("fileshare/share.html", file=file_item, **share_metadata)


@fileshare_bp.route("/share/<token>/file")
def public_file(token: str):
    stored_name, record = _record_for_token(token)
    if not stored_name or not record:
        abort(404)

    file_path = _uploads_dir() / stored_name
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_from_directory(
        _uploads_dir(),
        stored_name,
        download_name=record.get("original_name") or _display_name(stored_name),
        mimetype=record.get("mime_type") or _guess_mime_type(
            record.get("original_name", ""), stored_name
        ),
    )


@fileshare_bp.route("/share/<token>/download")
def public_download(token: str):
    stored_name, record = _record_for_token(token)
    if not stored_name or not record:
        abort(404)

    file_path = _uploads_dir() / stored_name
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_from_directory(
        _uploads_dir(),
        stored_name,
        as_attachment=True,
        download_name=record.get("original_name") or _display_name(stored_name),
    )
