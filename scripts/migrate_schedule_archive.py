"""显式目标 SQLite 的赛程原件版本绑定迁移；默认只读，不加载应用配置。"""

import argparse
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.migrate_team_name_provenance import (
    MigrationError,
    backup_before_migration,
    migration_lock,
)
from scripts.pipeline_lock import AlreadyRunning

FIELDS = {'schedule_raw_file': 'TEXT', 'schedule_raw_sha256': 'VARCHAR(64)'}
REQUIRED_COLUMNS = {'series_id', 'tournament_id', 'stage_id', 'source_json'}


def inspect_schema(connection):
    table = connection.execute("SELECT type FROM sqlite_master WHERE name='history_series'").fetchone()
    if table != ('table',):
        raise MigrationError('目标数据库缺少 history_series 实体表')
    columns = {row[1].casefold(): row for row in connection.execute('PRAGMA table_xinfo(history_series)')}
    if REQUIRED_COLUMNS - columns.keys():
        raise MigrationError('history_series 缺少系列、赛事、阶段身份或赛程原行字段，未执行迁移')
    if columns['series_id'][2].upper() != 'INTEGER' or columns['series_id'][5] != 1:
        raise MigrationError('history_series.series_id 不是预期的 INTEGER 主键，未执行迁移')
    for name in ('tournament_id', 'stage_id'):
        if columns[name][2].upper() != 'INTEGER' or columns[name][3] != 1:
            raise MigrationError(f'history_series.{name} 不是预期的非空 INTEGER，未执行迁移')
    if columns['source_json'][2].upper() != 'TEXT':
        raise MigrationError('history_series.source_json 不是预期的 TEXT，未执行迁移')
    missing = []
    for name, expected_type in FIELDS.items():
        column = columns.get(name)
        if column is None:
            missing.append(name)
        elif (column[2].strip().upper() != expected_type or column[3] or column[5] or column[6]
              or column[4] is not None and column[4].strip().upper() != 'NULL'):
            raise MigrationError(f'history_series.{name} 已存在但不是预期的可空 {expected_type} 列，未执行迁移')
    return missing


def migrate(database, *, apply=False, wait_seconds=0):
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 60:
        raise MigrationError('--wait-seconds 必须在 0–60 秒之间')
    database = Path(database).resolve()
    if not database.is_file():
        raise MigrationError('--database 必须指向已经存在的 SQLite 文件')
    with database.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise MigrationError('目标文件不是 SQLite 数据库')
    report = {'database': str(database), 'fields': list(FIELDS), 'apply': apply}
    if not apply:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            missing = inspect_schema(connection)
            return {**report, 'status': 'needs_migration' if missing else 'already_current',
                    'missing_columns': missing}
    with migration_lock(database, wait_seconds):
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)) as connection:
            missing = inspect_schema(connection)
            if not missing:
                return {**report, 'status': 'already_current'}
            backup = backup_before_migration(connection, database)
            # 两列共享同一显式事务；任一 ALTER 或后续校验失败均回滚。
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                for name in missing:
                    connection.execute(f'ALTER TABLE history_series ADD COLUMN {name} {FIELDS[name]}')
                if inspect_schema(connection):
                    raise MigrationError('迁移后仍缺少赛程原件字段，未提交迁移')
            return {**report, 'status': 'migrated', 'added_columns': missing, 'backup': backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='显式目标 SQLite 文件；不会读取 .env')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='取得采集锁、备份后新增赛程原件绑定列')
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
