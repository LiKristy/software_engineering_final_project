from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    max_upload_bytes: int
    session_ttl_seconds: int


def get_settings() -> Settings:
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", "data/classroom_quiz.sqlite3")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "10485760")),
        session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "300")),
    )
