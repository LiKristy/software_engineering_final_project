from app.config import get_settings


def test_google_service_account_file_is_optional_and_external(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    assert get_settings().google_service_account_file is None

    key_path = tmp_path / "service-account.json"
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(key_path))
    assert get_settings().google_service_account_file == key_path


def test_example_configuration_does_not_contain_credential_material():
    from pathlib import Path

    content = Path(".env.example").read_text(encoding="utf-8")
    assert '"private' + '_key"' not in content
    assert "-----BEGIN " + "PRIVATE KEY-----" not in content
    assert "access_token=" not in content.lower()


def test_settings_load_google_credential_path_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    (tmp_path / ".env").write_text("GOOGLE_SERVICE_ACCOUNT_FILE=/outside/service-account.json\n", encoding="utf-8")
    assert str(get_settings().google_service_account_file) == "/outside/service-account.json"
