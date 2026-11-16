from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_path: Path
    max_upload_bytes: int
    session_ttl_seconds: int
    google_service_account_file: Path | None


def get_settings() -> Settings:
    load_dotenv(Path.cwd() / ".env", override=False)
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", "data/classroom_quiz.sqlite3")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "10485760")),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "300")),
        google_service_account_file=(
            Path(os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]).expanduser()
            if os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            else None
        ),
    )
