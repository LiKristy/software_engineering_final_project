from app.config import get_settings


def test_google_service_account_file_is_optional_and_external(monkeypatch, tmp_path):
    import app.config as config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
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
    assert "GOOGLE_SERVICE_ACCOUNT_FILE=credential/service-account.json" in content


def test_settings_load_google_credential_path_from_dotenv(monkeypatch, tmp_path):
    import app.config as config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    (tmp_path / ".env").write_text("GOOGLE_SERVICE_ACCOUNT_FILE=/outside/service-account.json\n", encoding="utf-8")
    assert str(get_settings().google_service_account_file) == "/outside/service-account.json"


def test_relative_credential_path_is_project_root_relative_from_other_cwd(monkeypatch, tmp_path):
    import app.config as config

    project = tmp_path / "project"
    other_directory = tmp_path / "elsewhere"
    credential = project / "credential" / "service-account.json"
    credential.parent.mkdir(parents=True)
    credential.write_text("{}", encoding="utf-8")
    (project / ".env").write_text(
        "GOOGLE_SERVICE_ACCOUNT_FILE=credential/service-account.json\n", encoding="utf-8"
    )
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)

    assert get_settings().google_service_account_file == credential
