from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path
    session_ttl_seconds: int
    google_service_account_file: Path | None


def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    credential_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if credential_path:
        credential_path = Path(credential_path).expanduser()
        if not credential_path.is_absolute():
            credential_path = PROJECT_ROOT / credential_path
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", "data/classroom_quiz.sqlite3")),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "300")),
        google_service_account_file=credential_path,
    )
