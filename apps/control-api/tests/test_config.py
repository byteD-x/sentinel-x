import pytest

from sentinel_x_control_api.config import Settings


def test_light_profile_keeps_local_defaults():
    settings = Settings(_env_file=None)
    assert settings.sentinel_profile == "light"
    assert settings.sentinel_kill_switch is True


def test_full_profile_fails_closed_when_required_configuration_is_missing():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(sentinel_profile="full", _env_file=None)


def test_full_profile_requires_postgres_and_security_configuration():
    values = {
        "sentinel_profile": "full",
        "database_url": "sqlite:///wrong",
        "local_session_signing_key": "session-secret",
        "action_gateway_url": "http://gateway",
        "alert_ingress_hmac_key": "alert-secret",
    }
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(_env_file=None, **values)

    values["database_url"] = "postgresql://control:secret@db/sentinel"
    settings = Settings(_env_file=None, **values)
    assert settings.sentinel_profile == "full"
