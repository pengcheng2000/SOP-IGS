"""Back up the existing SQLite database before applying the additive sample-photo upgrade."""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.bootstrap import bootstrap
from app.config import get_settings
from app.db import engine

if __name__ == '__main__':
    settings = get_settings()
    if engine.dialect.name == 'sqlite' and Path(engine.url.database).is_file():
        directory = settings.data_root / 'backups'
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f'before-sample-photos-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.db'
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        print(f'Database backup: {backup}')
    bootstrap()
    print('Sample photo migration complete.')
