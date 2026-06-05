from __future__ import annotations

import mimetypes
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from yt_dlp import YoutubeDL

from ..auth.routes import login_required
from ..fileshare.routes import MAX_UPLOAD_BYTES, format_upload_limit, store_file_for_share

yt_dlp_bp = Blueprint("yt_dlp", __name__, url_prefix="/yt-dlp")


def _is_valid_source_url(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _download_video(source_url: str) -> dict[str, object]:
    with TemporaryDirectory(prefix="yt-dlp-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        output_template = temp_dir / "%(title).200B.%(ext)s"
        options = {
            "format": "bestvideo*+bestaudio/best",
            "noplaylist": True,
            "outtmpl": str(output_template),
            "paths": {"home": temp_dir_name},
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "max_filesize": MAX_UPLOAD_BYTES,
        }

        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source_url, download=True)

        downloaded_files = [
            path
            for path in temp_dir.iterdir()
            if path.is_file() and not path.name.endswith(".part")
        ]
        if not downloaded_files:
            raise RuntimeError("yt-dlp did not produce a downloadable file.")

        downloaded_file = max(downloaded_files, key=lambda path: path.stat().st_size)
        file_size = downloaded_file.stat().st_size
        if file_size > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"The downloaded file is {file_size} bytes, which exceeds the upload limit of {MAX_UPLOAD_BYTES} bytes."
            )

        display_name = info.get("title") if isinstance(info, dict) else None
        stored_item = store_file_for_share(
            downloaded_file,
            original_name=downloaded_file.name,
            mime_type=mimetypes.guess_type(downloaded_file.name)[0] or "",
        )

        if display_name and isinstance(stored_item, dict):
            stored_item["display_name"] = display_name

        return stored_item


@yt_dlp_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        source_url = request.form.get("url", "").strip()

        if not source_url:
            flash("Paste a video URL first.")
            return redirect(url_for("yt_dlp.index"))

        if not _is_valid_source_url(source_url):
            flash("Enter a valid http or https URL.")
            return redirect(url_for("yt_dlp.index"))

        try:
            stored_item = _download_video(source_url)
        except Exception as error:  # pragma: no cover - surfaced to the user
            flash(f"yt-dlp failed: {error}")
            return redirect(url_for("yt_dlp.index"))

        flash(f"Downloaded {stored_item['display_name']} into file share.")
        return redirect(url_for("fileshare.index", view="browse"))

    return render_template(
        "yt_dlp/index.html",
        session_id=session.get("session_id"),
        upload_limit_label=format_upload_limit(MAX_UPLOAD_BYTES),
    )