from src.auth import DEFAULT_ADMIN_PASSWORD, admin_password_from_env, verify_admin_password


def test_admin_password_defaults_for_local_testing(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    assert admin_password_from_env() == DEFAULT_ADMIN_PASSWORD
    assert verify_admin_password(DEFAULT_ADMIN_PASSWORD)


def test_admin_password_uses_env(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "custom-secret")

    assert verify_admin_password("custom-secret")
    assert not verify_admin_password("wrong")
