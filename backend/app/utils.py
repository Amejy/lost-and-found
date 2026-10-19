import secrets
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import current_app
from werkzeug.utils import secure_filename


def allowed_file(filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def _supabase_is_configured():
    """Return true only when the Supabase settings can create a real client.

    A deployment may have ``STORAGE_BACKEND=supabase`` left over while its
    Supabase URL or service key has not been added to the hosting provider.
    Treat that as local storage instead of allowing an invalid URL to turn a
    normal report submission into a 500 response.
    """
    if current_app.config.get("STORAGE_BACKEND", "local").lower() != "supabase":
        return False

    supabase_url = (current_app.config.get("SUPABASE_URL") or "").strip()
    supabase_key = (current_app.config.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    parsed_url = urlparse(supabase_url)
    return bool(supabase_key and parsed_url.scheme in {"http", "https"} and parsed_url.netloc)


def _save_locally(file_storage, random_name):
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    destination = upload_folder / random_name
    file_storage.save(destination)
    return random_name


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("Unsupported file type. Please upload png, jpg, jpeg, or webp.")

    filename = secure_filename(file_storage.filename)
    extension = filename.rsplit(".", 1)[-1].lower()
    random_name = f"{secrets.token_hex(12)}.{extension}"

    if _supabase_is_configured():
        supabase_url = current_app.config["SUPABASE_URL"].strip()
        supabase_key = current_app.config["SUPABASE_SERVICE_ROLE_KEY"].strip()
        bucket = current_app.config.get("SUPABASE_BUCKET", "item-images")

        from supabase import create_client

        try:
            client = create_client(supabase_url, supabase_key)
            client.storage.from_(bucket).upload(
                file=file_storage.stream,
                path=random_name,
                file_options={
                    "upsert": "false",
                    "content-type": file_storage.mimetype or "application/octet-stream",
                },
            )
            return random_name
        except Exception as exc:
            # The report can still be saved when a third-party storage service
            # is temporarily unavailable. The application log retains the
            # underlying error for the deployment owner to investigate.
            current_app.logger.warning("Supabase upload failed; using local storage: %s", exc)

    if current_app.config.get("STORAGE_BACKEND", "local").lower() == "supabase":
        current_app.logger.warning(
            "Supabase storage is not configured with a valid URL and service key; using local storage."
        )
    return _save_locally(file_storage, random_name)


def image_url(filename):
    if not filename:
        return None
    if _supabase_is_configured():
        supabase_url = current_app.config.get("SUPABASE_URL", "").rstrip("/")
        bucket = current_app.config.get("SUPABASE_BUCKET", "item-images")
        return f"{supabase_url}/storage/v1/object/public/{bucket}/{quote(filename)}"
    return f"/uploads/{filename}"
