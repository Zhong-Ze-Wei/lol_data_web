import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import Config


def backup_sqlite(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as backup:
            original.backup(backup)


def main():
    parser = argparse.ArgumentParser(description="Back up the local SQLite database before daily sync")
    parser.add_argument("--keep", type=int, default=7)
    args = parser.parse_args()
    if args.keep < 1:
        parser.error("--keep must be positive")
    if not Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"):
        print("MySQL 模式请使用数据库自身备份；跳过 SQLite 备份。")
        return
    source = Path(Config.SQLALCHEMY_DATABASE_URI.removeprefix("sqlite:///"))
    if not source.is_file():
        print("数据库尚未创建，跳过首次备份。")
        return
    directory = Path(Config.DATA_DIR) / "backups"
    destination = directory / f"lol-data-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
    backup_sqlite(source, destination)
    for old in sorted(directory.glob("lol-data-*.db"), reverse=True)[args.keep:]:
        old.unlink()
    print(f"数据库已备份：{destination.name}")


if __name__ == "__main__":
    main()
