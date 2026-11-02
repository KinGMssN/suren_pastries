from pathlib import Path


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
    assert "POSTGRES_USER=" in example
    assert "POSTGRES_PASSWORD=" in example
    assert "POSTGRES_DB=suren_pastries" in example
    assert "POSTGRES_PORT=5432" in example
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")
