import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app import create_app, db
from app.models.match import Match
from scripts import migrate_team_name_provenance as migration
from scripts.pipeline_lock import PipelineLock

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@pytest.fixture
def old_database(tmp_path):
    database = tmp_path / "old's data.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE matches (
                id INTEGER PRIMARY KEY NOT NULL, match_id INTEGER UNIQUE NOT NULL,
                series_id INTEGER, tournament_id INTEGER, tournament_name VARCHAR(200),
                date DATETIME, date_source VARCHAR(30), source VARCHAR(30) NOT NULL,
                verified BOOLEAN NOT NULL, game_time INTEGER,
                red_team_name VARCHAR(100), blue_team_name VARCHAR(100),
                win_team_name VARCHAR(100), mvp VARCHAR(100)
            );
            CREATE INDEX ix_matches_red_team_name ON matches(red_team_name);
            CREATE INDEX ix_matches_date ON matches(date);
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(match_id),
                team_name TEXT, UNIQUE(match_id, team_name)
            );
            INSERT INTO matches (id,match_id,source,verified,red_team_name,blue_team_name,win_team_name)
                VALUES (1,66845,'scoregg',1,'QG','WE','QG'), (2,18894,'legacy',0,'LM','PE','PE');
            INSERT INTO teams VALUES (1,66845,'QG'), (2,66845,'WE');
        ''')
    return database


def database_state(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            'columns': connection.execute('PRAGMA table_xinfo(matches)').fetchall(),
            'rows': connection.execute('SELECT * FROM matches ORDER BY id').fetchall(),
            'teams': connection.execute('SELECT * FROM teams ORDER BY id').fetchall(),
            'indexes': connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name").fetchall(),
            'foreign_keys': connection.execute('PRAGMA foreign_key_list(teams)').fetchall(),
            'foreign_key_errors': connection.execute('PRAGMA foreign_key_check').fetchall(),
        }


def test_dry_run_is_readonly_without_lock_or_backup(old_database):
    before = old_database.read_bytes()
    report = migration.migrate(old_database)
    assert report['status'] == 'needs_migration' and report['apply'] is False
    assert old_database.read_bytes() == before
    assert not (old_database.parent / '.sync.lock').exists()
    assert not (old_database.parent / 'backups').exists()


def test_apply_preserves_old_data_indexes_and_foreign_keys_with_restorable_backup(old_database):
    before = database_state(old_database)
    report = migration.migrate(old_database, apply=True)
    assert report['status'] == 'migrated'
    backup = Path(report['backup']['file'])
    assert backup.parent == old_database.parent / 'backups'
    assert backup.name.startswith('schema-team-name-provenance-')
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == report['backup']['sha256']
    assert database_state(backup) == before
    after = database_state(old_database)
    assert after['columns'][:-1] == before['columns']
    assert after['columns'][-1][1:] == ('team_name_provenance', 'JSON', 0, None, 0, 0)
    assert after['rows'] == [row + (None,) for row in before['rows']]
    for key in ('teams', 'indexes', 'foreign_keys', 'foreign_key_errors'):
        assert after[key] == before[key]
    with closing(sqlite3.connect(backup)) as restored:
        assert restored.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        restored.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            restored.execute("INSERT INTO teams VALUES (3,999,'unknown')")


def test_migration_is_idempotent_without_new_backup_or_ddl(old_database):
    first = migration.migrate(old_database, apply=True)
    after_first = old_database.read_bytes()
    second = migration.migrate(old_database, apply=True)
    assert second['status'] == 'already_current' and 'backup' not in second
    assert old_database.read_bytes() == after_first
    assert list((old_database.parent / 'backups').iterdir()) == [Path(first['backup']['file'])]
    assert migration.migrate(old_database)['status'] == 'already_current'


def test_schema_backup_survives_the_existing_daily_backup_rotation(old_database, monkeypatch):
    from scripts import backup_database

    database = old_database.with_name('lol-data.db')
    database.write_bytes(old_database.read_bytes())
    report = migration.migrate(database, apply=True)
    schema_backup = Path(report['backup']['file'])
    original_backup = schema_backup.read_bytes()
    assert schema_backup not in set(schema_backup.parent.glob('lol-data-*.db'))
    expired_daily_backup = schema_backup.parent / 'lol-data-20000101-000000.db'
    expired_daily_backup.write_bytes(b'old daily backup placeholder')
    monkeypatch.setattr(backup_database.Config, 'DATA_DIR', database.parent)
    monkeypatch.setattr(backup_database.Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{database.as_posix()}')
    monkeypatch.setattr(sys, 'argv', ['backup_database', '--keep', '1'])
    backup_database.main()
    assert not expired_daily_backup.exists()
    assert schema_backup.read_bytes() == original_backup
    assert len(list(schema_backup.parent.glob('lol-data-*.db'))) == 1


def test_online_backup_includes_committed_rows_still_in_wal(old_database):
    with closing(sqlite3.connect(old_database)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO matches (id,match_id,source,verified) VALUES (3,3260,'scoregg',1)")
        writer.commit()
        # 此临时库的主文件尚未包含新行；在线备份必须读取已提交的 WAL。
        with closing(sqlite3.connect(old_database.as_uri() + '?immutable=1', uri=True)) as main_file:
            assert main_file.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 2
        report = migration.migrate(old_database, apply=True)
        with closing(sqlite3.connect(report['backup']['file'])) as backup:
            assert backup.execute('SELECT match_id FROM matches ORDER BY id').fetchall() == [(66845,), (18894,), (3260,)]
            assert 'team_name_provenance' not in {row[1] for row in backup.execute('PRAGMA table_info(matches)')}


@pytest.mark.parametrize('definition', [
    'TEXT', "JSON NOT NULL DEFAULT '{}'", "JSON DEFAULT '{}'", "JSON GENERATED ALWAYS AS ('{}') VIRTUAL",
])
def test_same_named_incompatible_column_fails_without_backup_or_database_change(old_database, definition):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute(f'ALTER TABLE matches ADD COLUMN team_name_provenance {definition}')
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match='不是预期的可空 JSON'):
        migration.migrate(old_database, apply=True)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


def test_existing_nullable_json_with_null_default_is_accepted(old_database):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('ALTER TABLE matches ADD COLUMN team_name_provenance json DEFAULT NULL')
    assert migration.migrate(old_database, apply=True)['status'] == 'already_current'
    assert not (old_database.parent / 'backups').exists()


@pytest.mark.parametrize('schema', [
    'CREATE TABLE other (id INTEGER)',
    'CREATE VIEW matches AS SELECT 1 AS id',
    'CREATE TABLE matches (id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL)',
    'CREATE TABLE matches (id TEXT PRIMARY KEY,match_id INTEGER NOT NULL,source TEXT,verified INTEGER,'
    'red_team_name TEXT,blue_team_name TEXT,win_team_name TEXT)',
])
def test_wrong_matches_structure_is_rejected_without_ddl(tmp_path, schema):
    database = tmp_path / 'wrong.sqlite'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(schema)
    before = database.read_bytes()
    with pytest.raises(migration.MigrationError):
        migration.migrate(database, apply=True)
    assert database.read_bytes() == before
    assert not (tmp_path / 'backups').exists()


def test_missing_or_non_sqlite_target_never_creates_a_database(tmp_path):
    missing = tmp_path / 'missing.sqlite'
    assert migration.main(['--database', str(missing), '--apply']) == 2
    assert not missing.exists() and not (tmp_path / '.sync.lock').exists()
    other = tmp_path / 'other.db'
    other.write_bytes(b'not a SQLite file')
    assert migration.main(['--database', str(other), '--apply']) == 2
    assert other.read_bytes() == b'not a SQLite file'


def test_real_process_lock_contention_returns_three_without_changing_target(old_database):
    before = old_database.read_bytes()
    with PipelineLock(old_database.parent / '.sync.lock'):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'scripts.migrate_team_name_provenance',
                                  '--database', str(old_database), '--apply', '--wait-seconds', '.01'],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
    assert process.returncode == 3, process.stderr
    assert json.loads(process.stdout)['status'] == 'already_running'
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


def test_bounded_wait_acquires_lock_after_other_process_finishes(old_database):
    code = '''import sys,time
from scripts.pipeline_lock import PipelineLock
with PipelineLock(sys.argv[1]):
    print('locked',flush=True)
    time.sleep(.35)
'''
    process = subprocess.Popen([sys.executable, '-c', code, str(old_database.parent / '.sync.lock')],
                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **HIDDEN)
    try:
        assert process.stdout.readline().strip() == 'locked'
        report = migration.migrate(old_database, apply=True, wait_seconds=2)
        assert report['status'] == 'migrated'
    finally:
        _, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr


@pytest.mark.parametrize('seconds', [-1, 61, float('inf'), float('nan')])
def test_lock_wait_is_finite_and_bounded(old_database, seconds):
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match='0–60'):
        migration.migrate(old_database, apply=True, wait_seconds=seconds)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / '.sync.lock').exists()


def test_failure_after_ddl_rolls_back_target_and_keeps_complete_old_schema_backup(old_database, monkeypatch):
    before = database_state(old_database)
    inspect = migration.inspect_schema
    calls = []

    def fail_after_adding_column(connection):
        status = inspect(connection)
        calls.append(status)
        if status == 'already_current':
            raise migration.MigrationError('post-DDL validation failed')
        return status

    monkeypatch.setattr(migration, 'inspect_schema', fail_after_adding_column)
    with pytest.raises(migration.MigrationError, match='post-DDL validation failed'):
        migration.migrate(old_database, apply=True)
    assert calls == ['needs_migration', 'already_current']
    assert database_state(old_database) == before
    backups = list((old_database.parent / 'backups').glob('*.db'))
    assert len(backups) == 1 and database_state(backups[0]) == before
    with PipelineLock(old_database.parent / '.sync.lock'):
        pass  # 失败路径也释放真正的 OS 采集锁。


def test_nullable_json_roundtrip_on_migrated_old_database(old_database):
    migration.migrate(old_database, apply=True)
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{old_database.as_posix()}',
                      'DATA_DIR': old_database.parent, 'AI_API_KEY': '', 'AUTO_CREATE_DB': False})
    evidence = {'red': {'result_name': 'JDG', 'schedule_name': 'QG', 'team_id': 57}}
    with app.app_context():
        assert db.session.get(Match, 1).team_name_provenance is None
        match = db.session.get(Match, 1)
        match.team_name_provenance = evidence
        db.session.commit()
        db.session.expire_all()
        assert db.session.get(Match, 1).team_name_provenance == evidence
        match.team_name_provenance = None
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
    with closing(sqlite3.connect(old_database)) as connection:
        assert connection.execute('SELECT team_name_provenance,typeof(team_name_provenance) FROM matches WHERE id=1').fetchone() == (None, 'null')
        assert connection.execute('SELECT red_team_name,blue_team_name FROM matches WHERE id=1').fetchone() == ('QG', 'WE')


def test_migration_cli_never_imports_app_config_or_dotenv(old_database):
    code = '''import importlib.abc,sys
class RejectApplicationConfig(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'app','config','dotenv'}:
            raise AssertionError('Migration imported application configuration')
sys.meta_path.insert(0,RejectApplicationConfig())
from scripts.migrate_team_name_provenance import main
raise SystemExit(main(sys.argv[1:]))
'''
    for mode, status in (('--dry-run', 'needs_migration'), ('--apply', 'migrated')):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, '--database', str(old_database), mode],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
        assert process.returncode == 0, process.stderr
        assert json.loads(process.stdout)['status'] == status


def test_existing_pipeline_imports_remain_compatible():
    from scripts import pipeline
    from scripts.pipeline_lock import AlreadyRunning

    assert pipeline.PipelineLock is PipelineLock
    assert pipeline.AlreadyRunning is AlreadyRunning
