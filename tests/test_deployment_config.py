import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_compose_requires_local_database_credentials_and_loopback_binding():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '${POSTGRES_USER:?Set POSTGRES_USER in .env}' in compose
    assert '${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}' in compose
    assert '${POSTGRES_DB:?Set POSTGRES_DB in .env}' in compose
    assert '"127.0.0.1:${POSTGRES_PORT:-5432}:5432"' in compose
    assert "suren_user" not in compose
    assert "suren_pass" not in compose


def test_environment_example_lists_only_configuration_placeholders():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL=" in example
    assert "SECRET_KEY=" in example
    assert "POSTGRES_USER=" in example
    assert "POSTGRES_PASSWORD=" in example
    assert "POSTGRES_DB=suren_pastries" in example
    assert "POSTGRES_PORT=5432" in example
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_vercel_deployment_uses_wsgi_and_publishes_static_assets():
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert "wsgi.py" in vercel["functions"]
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    assert (ROOT / "public" / "static" / "css" / "main.css").is_file()
    assert "gunicorn" not in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert not (ROOT / "Procfile").exists()
    assert not (ROOT / "runtime.txt").exists()


def test_static_assets_remain_available_to_local_flask_development(client):
    response = client.get("/static/css/main.css")

    assert response.status_code == 200
    assert response.mimetype == "text/css"
    assert response.headers["Cache-Control"] == (
        "public, max-age=31536000, immutable"
    )
    assert "?v=" in client.get("/home").get_data(as_text=True)


def test_vercel_requires_external_postgresql():
    environment = os.environ.copy()
    environment["VERCEL"] = "1"
    environment["SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
    environment["DATABASE_URL"] = "sqlite:///local.db"

    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DATABASE_URL must use PostgreSQL on Vercel." in result.stderr
