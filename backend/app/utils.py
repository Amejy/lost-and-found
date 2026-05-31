import secrets
from pathlib import Path
from urllib.parse import quote

from flask import current_app
from werkzeug.utils import secure_filename


def allowed_file(filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("Unsupported file type. Please upload png, jpg, jpeg, or webp.")

    filename = secure_filename(file_storage.filename)
    extension = filename.rsplit(".", 1)[-1].lower()
    random_name = f"{secrets.token_hex(12)}.{extension}"

    if current_app.config.get("STORAGE_BACKEND", "local") == "supabase":
        supabase_url = current_app.config.get("SUPABASE_URL")
        supabase_key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")
        bucket = current_app.config.get("SUPABASE_BUCKET", "item-images")
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase storage is not configured.")

        from supabase import create_client

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

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    destination = upload_folder / random_name
    file_storage.save(destination)
    return random_name


def image_url(filename):
    if not filename:
        return None
    if current_app.config.get("STORAGE_BACKEND", "local") == "supabase":
        supabase_url = current_app.config.get("SUPABASE_URL", "").rstrip("/")
        bucket = current_app.config.get("SUPABASE_BUCKET", "item-images")
        return f"{supabase_url}/storage/v1/object/public/{bucket}/{quote(filename)}"
    return f"/uploads/{filename}"
