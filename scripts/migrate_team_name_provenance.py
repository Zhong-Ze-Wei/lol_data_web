"""显式目标 SQLite 的队名来源字段迁移；默认只读检查，不加载应用配置。"""

import argparse
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from scripts.pipeline_lock import AlreadyRunning, PipelineLock

FIELD = 'team_name_provenance'
REQUIRED_COLUMNS = {'id', 'match_id', 'source', 'verified', 'red_team_name', 'blue_team_name', 'win_team_name'}


class MigrationError(ValueError):
    pass


def inspect_schema(connection):
    table = connection.execute("SELECT type FROM sqlite_master WHERE name='matches'").fetchone()
    if table != ('table',):
        raise MigrationError('目标数据库缺少 matches 实体表')
    columns = {row[1].casefold(): row for row in connection.execute('PRAGMA table_xinfo(matches)')}
    if REQUIRED_COLUMNS - columns.keys():
        raise MigrationError('matches 缺少单局身份、来源或队名字段，未执行迁移')
    if columns['id'][2].upper() != 'INTEGER' or columns['id'][5] != 1:
        raise MigrationError('matches.id 不是预期的 INTEGER 主键，未执行迁移')
    if columns['match_id'][2].upper() != 'INTEGER' or columns['match_id'][3] != 1:
        raise MigrationError('matches.match_id 不是预期的非空 INTEGER，未执行迁移')
    column = columns.get(FIELD)
    if column is None:
        return 'needs_migration'
    if (column[2].strip().upper() != 'JSON' or column[3] or column[5] or column[6]
            or column[4] is not None and column[4].strip().upper() != 'NULL'):
        raise MigrationError(f'matches.{FIELD} 已存在但不是预期的可空 JSON 列，未执行迁移')
    return 'already_current'


def backup_before_migration(connection, database):
    directory = database.parent / 'backups'
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    destination = directory / f'schema-team-name-provenance-{database.stem}-{stamp}-{uuid4().hex}.db'
    with destination.open('xb'):
        pass
    with closing(sqlite3.connect(destination)) as backup:
        connection.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise MigrationError(f'迁移前备份完整性检查失败，未修改目标数据库：{destination}')
    digest = hashlib.sha256()
    with destination.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'file': str(destination), 'sha256': digest.hexdigest()}


@contextmanager
def migration_lock(database, wait_seconds):
    deadline = time.monotonic() + wait_seconds
    while True:
        lock = PipelineLock(database.parent / '.sync.lock')
        try:
            lock.__enter__()
            break
        except AlreadyRunning:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(.25, remaining))
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def migrate(database, *, apply=False, wait_seconds=0):
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 60:
        raise MigrationError('--wait-seconds 必须在 0–60 秒之间')
    database = Path(database).resolve()
    if not database.is_file():
        raise MigrationError('--database 必须指向已经存在的 SQLite 文件')
    with database.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise MigrationError('目标文件不是 SQLite 数据库')
    report = {'database': str(database), 'field': FIELD, 'apply': apply}
    if not apply:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            return {**report, 'status': inspect_schema(connection)}
    with migration_lock(database, wait_seconds):
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)) as connection:
            status = inspect_schema(connection)
            if status == 'already_current':
                return {**report, 'status': status}
            backup = backup_before_migration(connection, database)
            # DDL 也在显式事务中；失败回滚，已完成的旧 schema 备份继续保留。
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(f'ALTER TABLE matches ADD COLUMN {FIELD} JSON')
                inspect_schema(connection)
            return {**report, 'status': 'migrated', 'backup': backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='显式目标 SQLite 文件；不会读取 .env')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='取得采集锁、备份后新增可空 JSON 列')
    mode.add_argument('--dry-run', action='store_true', help='仅只读检查（默认）')
    parser.add_argument('--wait-seconds', type=float, default=0, help='等待采集锁的时间上限，0–60秒，默认不等待')
    args = parser.parse_args(argv)
    try:
        report = migrate(args.database, apply=args.apply, wait_seconds=args.wait_seconds)
    except AlreadyRunning:
        print(json.dumps({'status': 'already_running', 'error': '采集锁正在使用；未执行数据库迁移'}, ensure_ascii=False))
        return 3
    except (MigrationError, OSError, sqlite3.DatabaseError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
