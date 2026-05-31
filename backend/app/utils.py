import os
import secrets
from pathlib import Path

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
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    destination = upload_folder / random_name
    file_storage.save(destination)
    return random_name


def image_url(filename):
    if not filename:
        return None
    return f"/uploads/{filename}"
