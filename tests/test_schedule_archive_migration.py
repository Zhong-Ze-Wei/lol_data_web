import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from scripts import migrate_schedule_archive as migration
from scripts.pipeline_lock import PipelineLock

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@pytest.fixture
def old_database(tmp_path):
    database = tmp_path / "old's history.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE history_tournaments (tournament_id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE history_stages (
                id INTEGER PRIMARY KEY, tournament_id INTEGER NOT NULL REFERENCES history_tournaments(tournament_id),
                raw_file TEXT, raw_sha256 VARCHAR(64)
            );
            CREATE TABLE history_series (
                series_id INTEGER PRIMARY KEY NOT NULL,
                tournament_id INTEGER NOT NULL REFERENCES history_tournaments(tournament_id),
                stage_id INTEGER NOT NULL REFERENCES history_stages(id),
                scheduled_at DATETIME, source_status VARCHAR(10), is_publist INTEGER,
                team_a_score INTEGER, team_b_score INTEGER, source_json TEXT,
                status VARCHAR(30) NOT NULL, result_ids TEXT NOT NULL DEFAULT '[]',
                raw_file TEXT, raw_sha256 VARCHAR(64), attempts INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0, last_error TEXT, next_retry_at DATETIME,
                discovered_at DATETIME, updated_at DATETIME NOT NULL
            );
            CREATE INDEX ix_history_series_tournament_id ON history_series(tournament_id);
            CREATE INDEX ix_history_series_status ON history_series(status);
            CREATE TABLE sync_tasks (result_id INTEGER PRIMARY KEY, series_id INTEGER REFERENCES history_series(series_id));
            INSERT INTO history_tournaments VALUES (1,'2016 LPL');
            INSERT INTO history_stages VALUES (11,1,'raw/history/stages/1/p_11.json','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
            INSERT INTO history_series (series_id,tournament_id,stage_id,scheduled_at,source_status,is_publist,
                source_json,status,result_ids,raw_file,raw_sha256,updated_at)
                VALUES (99,1,11,'2016-01-01 10:00:00','2',1,'{"matchID":99,"team_short_name_a":"旧队名"}',
                        'discovered','[66845]','raw/history/series/99.json',
                        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','2026-10-04 01:00:00'),
                       (100,1,11,NULL,'0',0,NULL,'queued','[]',NULL,NULL,'2026-10-04 01:00:00');
            INSERT INTO sync_tasks VALUES (66845,99);
        ''')
    return database


def database_state(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            'columns': connection.execute('PRAGMA table_xinfo(history_series)').fetchall(),
            'series': connection.execute('SELECT * FROM history_series ORDER BY series_id').fetchall(),
            'stages': connection.execute('SELECT * FROM history_stages ORDER BY id').fetchall(),
            'tasks': connection.execute('SELECT * FROM sync_tasks ORDER BY result_id').fetchall(),
            'indexes': connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name").fetchall(),
            'foreign_keys': connection.execute('PRAGMA foreign_key_list(history_series)').fetchall(),
            'task_foreign_keys': connection.execute('PRAGMA foreign_key_list(sync_tasks)').fetchall(),
            'foreign_key_errors': connection.execute('PRAGMA foreign_key_check').fetchall(),
        }


def test_dry_run_is_readonly_without_lock_or_backup(old_database):
    before = old_database.read_bytes()
    report = migration.migrate(old_database)
    assert report['status'] == 'needs_migration' and report['apply'] is False
    assert report['missing_columns'] == ['schedule_raw_file', 'schedule_raw_sha256']
    assert old_database.read_bytes() == before
    assert not (old_database.parent / '.sync.lock').exists()
    assert not (old_database.parent / 'backups').exists()


def test_apply_preserves_source_rows_resultlist_archive_indexes_and_foreign_keys(old_database):
    before = database_state(old_database)
    report = migration.migrate(old_database, apply=True)
    assert report['status'] == 'migrated'
    assert report['added_columns'] == ['schedule_raw_file', 'schedule_raw_sha256']
    backup = Path(report['backup']['file'])
    assert backup.parent == old_database.parent / 'backups'
    assert backup.name.startswith('schema-team-name-provenance-')
    assert backup not in set(backup.parent.glob('lol-data-*.db'))
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == report['backup']['sha256']
    assert database_state(backup) == before
    after = database_state(old_database)
    assert after['columns'][:-2] == before['columns']
    assert [column[1:] for column in after['columns'][-2:]] == [
        ('schedule_raw_file', 'TEXT', 0, None, 0, 0),
        ('schedule_raw_sha256', 'VARCHAR(64)', 0, None, 0, 0),
    ]
    assert after['series'] == [row + (None, None) for row in before['series']]
    for name in ('stages', 'tasks', 'indexes', 'foreign_keys', 'task_foreign_keys', 'foreign_key_errors'):
        assert after[name] == before[name]
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        connection.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('INSERT INTO sync_tasks VALUES (999,999)')


def test_repeat_apply_has_no_new_backup_or_ddl(old_database):
    first = migration.migrate(old_database, apply=True)
    after = old_database.read_bytes()
    second = migration.migrate(old_database, apply=True)
    assert second['status'] == 'already_current' and 'backup' not in second
    assert old_database.read_bytes() == after
    assert list((old_database.parent / 'backups').iterdir()) == [Path(first['backup']['file'])]
    assert migration.migrate(old_database)['missing_columns'] == []


@pytest.mark.parametrize('existing,value', [
    ('schedule_raw_file', 'raw/history/stages/1/previous.json'),
    ('schedule_raw_sha256', 'c' * 64),
])
def test_partial_existing_schema_adds_only_missing_column_without_rewriting_evidence(old_database, existing, value):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute(f'ALTER TABLE history_series ADD COLUMN {existing} {migration.FIELDS[existing]}')
        connection.execute(f'UPDATE history_series SET {existing}=? WHERE series_id=99', (value,))
        connection.commit()
    before = database_state(old_database)
    report = migration.migrate(old_database, apply=True)
    missing = 'schedule_raw_sha256' if existing == 'schedule_raw_file' else 'schedule_raw_file'
    assert report['added_columns'] == [missing]
    assert database_state(Path(report['backup']['file'])) == before
    after = database_state(old_database)
    assert after['columns'][:-1] == before['columns']
    assert after['series'] == [row + (None,) for row in before['series']]
    with closing(sqlite3.connect(old_database)) as connection:
        assert connection.execute(f'SELECT {existing},{missing} FROM history_series WHERE series_id=99').fetchone() == (value, None)


def test_online_backup_includes_committed_source_row_still_in_wal(old_database):
    with closing(sqlite3.connect(old_database)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE history_series SET source_json=? WHERE series_id=99", ('{"matchID":99,"revision":2}',))
        writer.commit()
        with closing(sqlite3.connect(old_database.as_uri() + '?immutable=1', uri=True)) as main_file:
            assert 'revision' not in main_file.execute('SELECT source_json FROM history_series WHERE series_id=99').fetchone()[0]
        report = migration.migrate(old_database, apply=True)
        with closing(sqlite3.connect(report['backup']['file'])) as backup:
            assert json.loads(backup.execute('SELECT source_json FROM history_series WHERE series_id=99').fetchone()[0])['revision'] == 2
            assert 'schedule_raw_file' not in {row[1] for row in backup.execute('PRAGMA table_info(history_series)')}


@pytest.mark.parametrize('field,definition', [
    ('schedule_raw_file', 'VARCHAR(64)'),
    ('schedule_raw_file', "TEXT NOT NULL DEFAULT ''"),
    ('schedule_raw_file', "TEXT DEFAULT 'previous.json'"),
    ('schedule_raw_file', "TEXT GENERATED ALWAYS AS ('previous.json') VIRTUAL"),
    ('schedule_raw_sha256', 'TEXT'),
    ('schedule_raw_sha256', "VARCHAR(64) DEFAULT 'abc'"),
])
def test_incompatible_existing_column_fails_before_backup_or_other_alter(old_database, field, definition):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute(f'ALTER TABLE history_series ADD COLUMN {field} {definition}')
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match='不是预期的可空'):
        migration.migrate(old_database, apply=True)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


def test_existing_nullable_columns_with_null_defaults_are_accepted(old_database):
    with closing(sqlite3.connect(old_database)) as connection:
        for name, definition in migration.FIELDS.items():
            connection.execute(f'ALTER TABLE history_series ADD COLUMN {name} {definition} DEFAULT NULL')
    assert migration.migrate(old_database, apply=True)['status'] == 'already_current'
    assert not (old_database.parent / 'backups').exists()


@pytest.mark.parametrize('schema', [
    'CREATE TABLE other (id INTEGER)',
    'CREATE VIEW history_series AS SELECT 1 AS series_id',
    'CREATE TABLE history_series (series_id INTEGER PRIMARY KEY,tournament_id INTEGER NOT NULL,stage_id INTEGER NOT NULL)',
    'CREATE TABLE history_series (series_id TEXT PRIMARY KEY,tournament_id INTEGER NOT NULL,stage_id INTEGER NOT NULL,source_json TEXT)',
    'CREATE TABLE history_series (series_id INTEGER PRIMARY KEY,tournament_id INTEGER,stage_id INTEGER NOT NULL,source_json TEXT)',
    'CREATE TABLE history_series (series_id INTEGER PRIMARY KEY,tournament_id INTEGER NOT NULL,stage_id INTEGER NOT NULL,source_json JSON)',
])
def test_wrong_history_series_structure_is_rejected_without_ddl(tmp_path, schema):
    database = tmp_path / 'wrong.sqlite'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(schema)
    before = database.read_bytes()
    with pytest.raises(migration.MigrationError):
        migration.migrate(database, apply=True)
    assert database.read_bytes() == before
    assert not (tmp_path / 'backups').exists()


def test_missing_or_non_sqlite_target_never_creates_database(tmp_path):
    missing = tmp_path / 'missing.sqlite'
    assert migration.main(['--database', str(missing), '--apply']) == 2
    assert not missing.exists() and not (tmp_path / '.sync.lock').exists()
    other = tmp_path / 'other.sqlite'
    other.write_bytes(b'not a SQLite file')
    assert migration.main(['--database', str(other), '--apply']) == 2
    assert other.read_bytes() == b'not a SQLite file'


def test_real_process_lock_contention_returns_three_without_backup_or_ddl(old_database):
    before = old_database.read_bytes()
    with PipelineLock(old_database.parent / '.sync.lock'):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'scripts.migrate_schedule_archive',
                                  '--database', str(old_database), '--apply', '--wait-seconds', '.01'],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
    assert process.returncode == 3, process.stderr
    assert json.loads(process.stdout)['status'] == 'already_running'
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


@pytest.mark.parametrize('seconds', [-1, 61, float('inf'), float('nan')])
def test_wait_is_finite_and_bounded(old_database, seconds):
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match='0–60'):
        migration.migrate(old_database, apply=True, wait_seconds=seconds)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / '.sync.lock').exists()


@pytest.mark.parametrize('failure', ['second_alter', 'post_validation'])
def test_ddl_failure_rolls_back_all_new_columns_and_preserves_complete_backup(old_database, monkeypatch, failure):
    before = database_state(old_database)
    if failure == 'second_alter':
        connect = sqlite3.connect

        class FailingSecondAlter(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == 'ALTER TABLE history_series ADD COLUMN schedule_raw_sha256 VARCHAR(64)':
                    assert 'schedule_raw_file' in {row[1] for row in super().execute('PRAGMA table_info(history_series)')}
                    raise sqlite3.OperationalError('second ALTER failed')
                return super().execute(sql, parameters)

        monkeypatch.setattr(migration.sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=FailingSecondAlter))
        expected_error = sqlite3.OperationalError
    else:
        inspect = migration.inspect_schema

        def fail_after_both_columns(connection):
            missing = inspect(connection)
            if not missing:
                raise migration.MigrationError('post-DDL validation failed')
            return missing

        monkeypatch.setattr(migration, 'inspect_schema', fail_after_both_columns)
        expected_error = migration.MigrationError
    with pytest.raises(expected_error):
        migration.migrate(old_database, apply=True)
    assert database_state(old_database) == before
    backups = list((old_database.parent / 'backups').glob('*.db'))
    assert len(backups) == 1 and database_state(backups[0]) == before
    with PipelineLock(old_database.parent / '.sync.lock'):
        pass  # 失败后真实 OS 锁可再次获取。


def test_nullable_text_and_sha_roundtrip_without_modifying_original_archive(old_database):
    migration.migrate(old_database, apply=True)
    before = database_state(old_database)
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('UPDATE history_series SET schedule_raw_file=?,schedule_raw_sha256=? WHERE series_id=99',
                           ('raw/history/stages/1/p_11-revision.json', 'c' * 64))
        assert connection.execute('SELECT schedule_raw_file,schedule_raw_sha256 FROM history_series WHERE series_id=99').fetchone() == (
            'raw/history/stages/1/p_11-revision.json', 'c' * 64)
        connection.execute('UPDATE history_series SET schedule_raw_file=NULL,schedule_raw_sha256=NULL WHERE series_id=99')
        connection.commit()
        assert connection.execute('SELECT typeof(schedule_raw_file),typeof(schedule_raw_sha256) FROM history_series WHERE series_id=99').fetchone() == ('null', 'null')
    assert database_state(old_database) == before


def test_cli_never_imports_application_config_or_dotenv(old_database):
    code = '''import importlib.abc,sys
class RejectApplicationConfig(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'app','config','dotenv'}:
            raise AssertionError('Migration imported application configuration')
sys.meta_path.insert(0,RejectApplicationConfig())
from scripts.migrate_schedule_archive import main
raise SystemExit(main(sys.argv[1:]))
'''
    for mode, status in (('--dry-run', 'needs_migration'), ('--apply', 'migrated')):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, '--database', str(old_database), mode],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
        assert process.returncode == 0, process.stderr
        assert json.loads(process.stdout)['status'] == status
