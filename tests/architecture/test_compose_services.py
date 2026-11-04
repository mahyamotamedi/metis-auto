"""compose.yaml (sprint T-4, draft ADR services-extra-and-adapters): the services
profile starts the demo, Redis, Postgres and MLflow; every published port is bound
to 127.0.0.1; every service except the test runner has a health check; the `db`
profile still starts Postgres alone; the Postgres and Redis passwords come only from
the environment, never from the file. Static (PyYAML); nothing is started or pulled.
Each rule is shown on a planted violation first."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVICES = {"redis", "mlflow", "demo", "postgres"}
NO_HEALTHCHECK = {"app"}  # the test runner exits; it is not a service


def problems(doc: dict) -> list[str]:
    found = []
    services = doc["services"]
    for name, s in services.items():
        for port in s.get("ports", []):
            text = str(port)
            if not text.startswith("127.0.0.1:"):
                found.append(f"{name}: port {text!r} is not loopback-only")
        if name not in NO_HEALTHCHECK and "healthcheck" not in s:
            found.append(f"{name}: no health check")
    for name in SERVICES - set(services):
        found.append(f"{name}: missing")
    for name in SERVICES & set(services):
        if "services" not in (services[name].get("profiles") or []):
            found.append(f"{name}: not in the services profile")
    if "db" not in (services.get("postgres", {}).get("profiles") or []):
        found.append("postgres: left the db profile")
    blob = yaml.safe_dump(doc)
    for secret in ("POSTGRES_PASSWORD: metis", "password: ", "requirepass redis"):
        if secret in blob:
            found.append(f"a literal password ({secret})")
    env = services.get("postgres", {}).get("environment", {})
    if "METIS_DB_PASSWORD" not in str(env.get("POSTGRES_PASSWORD", "")):
        found.append("postgres: password not from METIS_DB_PASSWORD")
    return found


def good() -> dict:
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


def test_planted_public_port_is_caught():
    doc = good()
    doc["services"]["redis"]["ports"] = ["6379:6379"]
    assert any("redis" in p and "loopback" in p for p in problems(doc))
    doc["services"]["redis"]["ports"] = ["0.0.0.0:6379:6379"]
    assert any("loopback" in p for p in problems(doc))


def test_planted_missing_healthcheck_and_profile_are_caught():
    doc = good()
    del doc["services"]["mlflow"]["healthcheck"]
    doc["services"]["demo"]["profiles"] = []
    doc["services"]["postgres"]["profiles"] = ["services"]
    found = problems(doc)
    assert "mlflow: no health check" in found
    assert "demo: not in the services profile" in found
    assert "postgres: left the db profile" in found


def test_planted_literal_password_is_caught():
    doc = good()
    doc["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"] = "hunter2"
    assert "postgres: password not from METIS_DB_PASSWORD" in problems(doc)


def test_compose_file_follows_the_rules():
    assert problems(good()) == []


def test_the_demo_uses_redis_and_postgres_through_configuration_only():
    env = good()["services"]["demo"]["environment"]
    assert env["METIS__CACHE__STORE"] == "redis"
    assert env["METIS__EVENTS__SINK"] == "postgres"
    # secrets are passed through from the host environment, never written here
    assert env["METIS_DB_PASSWORD"] == "${METIS_DB_PASSWORD:-}"
    assert env["METIS_REDIS_PASSWORD"] == "${METIS_REDIS_PASSWORD:-}"


def test_the_demo_image_target_exists_in_the_dockerfile():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "AS demo" in text and "requirements-services.lock" in text
