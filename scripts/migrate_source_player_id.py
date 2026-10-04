"""显式 SQLite 选手来源 ID 迁移；默认只读，不加载应用或 .env。"""

import argparse
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from scripts.migrate_team_name_provenance import MigrationError, migration_lock
from scripts.pipeline_lock import AlreadyRunning

FIELD = 'source_player_id'
INDEX = 'uq_player_match_source_player'
REQUIRED_COLUMNS = {'id', 'match_id', 'name', 'team_name', 'position'}


def _index_keys(connection, name):
    escaped = name.replace('"', '""')
    return [row for row in connection.execute(f'PRAGMA index_xinfo("{escaped}")') if row[5]]


def inspect_schema(connection):
    """完整检查列和索引形状；正确缺项待迁移，名称冲突不静默略过。"""
    table = connection.execute("SELECT type FROM sqlite_master WHERE name='players'").fetchone()
    if table != ('table',):
        raise MigrationError('目标数据库缺少 players 实体表')
    columns = {row[1].casefold(): row for row in connection.execute('PRAGMA table_xinfo(players)')}
    if REQUIRED_COLUMNS - columns.keys():
        raise MigrationError('players 缺少选手身份、队伍或位置字段，未执行迁移')
    if (columns['id'][2].upper() != 'INTEGER' or columns['id'][5] != 1
            or sum(bool(row[5]) for row in columns.values()) != 1):
        raise MigrationError('players.id 不是预期的 INTEGER 单列主键，未执行迁移')
    if columns['match_id'][2].upper() != 'INTEGER' or columns['match_id'][3] != 1:
        raise MigrationError('players.match_id 不是预期的非空 INTEGER，未执行迁移')
    foreign_keys = connection.execute('PRAGMA foreign_key_list(players)').fetchall()
    if not any(row[2:5] == ('matches', 'match_id', 'match_id') for row in foreign_keys):
        raise MigrationError('players 缺少预期的单局外键，未执行迁移')
    indexes = connection.execute('PRAGMA index_list(players)').fetchall()
    old_keys = ('match_id', 'team_name', 'position')
    if not any(row[2] and not row[4] and tuple(key[2] for key in _index_keys(connection, row[1])) == old_keys
               for row in indexes):
        raise MigrationError('players 缺少原有的单局队伍位置唯一约束，未执行迁移')
    column = columns.get(FIELD)
    if column is not None and (
        column[2].strip().upper() != 'VARCHAR(100)' or column[3] or column[5] or column[6]
        or column[4] is not None and column[4].strip().upper() != 'NULL'
    ):
        raise MigrationError(f'players.{FIELD} 已存在但不是预期的可空 VARCHAR(100) 列，未执行迁移')
    existing = connection.execute(
        'SELECT type,tbl_name FROM sqlite_master WHERE name=? COLLATE NOCASE', (INDEX,),
    ).fetchone()
    if existing is not None:
        if existing != ('index', 'players'):
            raise MigrationError(f'{INDEX} 已存在但不属于 players 的唯一索引，未执行迁移')
        definition = next((row for row in indexes if row[1].casefold() == INDEX), None)
        keys = _index_keys(connection, INDEX)
        if (definition is None or not definition[2] or definition[3] != 'c' or definition[4]
                or tuple(row[2] for row in keys) != ('match_id', FIELD)
                or any(row[1] < 0 or row[3] or row[4].upper() != 'BINARY' for row in keys)):
            raise MigrationError(f'{INDEX} 不是预期的非部分、非表达式双列唯一索引，未执行迁移')
    return 'already_current' if column is not None and existing is not None else 'needs_migration'


def backup_before_migration(connection, database):
    directory = database.parent / 'backups'
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    destination = directory / f'schema-source-player-id-{database.stem}-{stamp}-{uuid4().hex}.db'
    with destination.open('xb'):
        pass
    with closing(sqlite3.connect(destination)) as backup:
        connection.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise MigrationError(f'来源 ID 迁移前备份完整性检查失败，未修改目标数据库：{destination}')
    with destination.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'file': str(destination), 'sha256': digest}


def migrate(database, *, apply=False, wait_seconds=0):
    if not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 60:
        raise MigrationError('--wait-seconds 必须在 0–60 秒之间')
    database = Path(database).resolve()
    if not database.is_file():
        raise MigrationError('--database 必须指向已经存在的 SQLite 文件')
    with database.open('rb') as stream:
        if stream.read(16) != b'SQLite format 3\x00':
            raise MigrationError('目标文件不是 SQLite 数据库')
    report = {'database': str(database), 'field': FIELD, 'unique_index': INDEX, 'apply': apply}
    if not apply:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            return {**report, 'status': inspect_schema(connection)}
    with migration_lock(database, wait_seconds):
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            if inspect_schema(connection) == 'already_current':
                return {**report, 'status': 'already_current'}
            backup = backup_before_migration(connection, database)
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                inspect_schema(connection)
                columns = {row[1].casefold() for row in connection.execute('PRAGMA table_xinfo(players)')}
                if FIELD not in columns:
                    connection.execute(f'ALTER TABLE players ADD COLUMN {FIELD} VARCHAR(100)')
                # 不用 IF NOT EXISTS；列和具名索引必须在同一事务中成功且形状正确。
                connection.execute(f'CREATE UNIQUE INDEX {INDEX} ON players(match_id,{FIELD})')
                if inspect_schema(connection) != 'already_current':
                    raise MigrationError('来源 ID 列或唯一索引未正确完成，未提交迁移')
            return {**report, 'status': 'migrated', 'backup': backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='已存在的目标 SQLite；不读取 .env')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='取得采集锁、在线备份后事务新增列和唯一索引')
    mode.add_argument('--dry-run', action='store_true', help='仅只读检查（默认），不取锁或备份')
    parser.add_argument('--wait-seconds', type=float, default=0, help='等待采集锁0–60秒，默认不等待')
    args = parser.parse_args(argv)
    try:
        report = migrate(args.database, apply=args.apply, wait_seconds=args.wait_seconds)
    except AlreadyRunning:
        print(json.dumps({'status': 'already_running', 'error': '采集锁正在使用；未执行迁移'}, ensure_ascii=False))
        return 3
    except (MigrationError, OSError, sqlite3.DatabaseError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
