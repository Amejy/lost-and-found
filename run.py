import os

import flask.cli

from backend.app import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    # For local testing we keep a quiet single-process server path so the
    # startup experience is predictable and does not emit the Flask banner.
    flask.cli.show_server_banner = lambda *args, **kwargs: None
    app.run(
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
    )
