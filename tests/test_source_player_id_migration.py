import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from scripts import migrate_source_player_id as migration
from scripts.pipeline_lock import PipelineLock

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


@pytest.fixture
def old_database(tmp_path):
    database = tmp_path / "old player's data.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE matches (id INTEGER PRIMARY KEY,match_id INTEGER NOT NULL UNIQUE);
            CREATE TABLE players (
                id INTEGER PRIMARY KEY NOT NULL, date DATETIME, name VARCHAR(100),
                pic VARCHAR(255), hero VARCHAR(255), hero_lv INTEGER, kda FLOAT,
                kills INTEGER, deaths INTEGER, assists INTEGER, part FLOAT,
                atk INTEGER, atk_p FLOAT, atk_m FLOAT, def_ INTEGER, def_p FLOAT,
                def_m FLOAT, adc_m FLOAT, money INTEGER, money_M FLOAT, wp_m FLOAT,
                hits INTEGER, mvp INTEGER, beiguo VARCHAR(100),
                team_name VARCHAR(100), position VARCHAR(100), game_time INTEGER,
                result VARCHAR(10), match_id INTEGER NOT NULL REFERENCES matches(match_id),
                CONSTRAINT uq_player_match_team_position UNIQUE(match_id,team_name,position)
            );
            CREATE INDEX ix_player_name_date_id ON players(name,date,id);
            CREATE INDEX ix_player_position_date ON players(position,date);
            INSERT INTO matches VALUES(1,35121),(2,28972),(3,28973);
            INSERT INTO players VALUES(
                51,'2022-10-14 03:00:00','Wunder','image','Gragas',15,1.5,
                1,2,2,50.5,12000,21.4,300.2,22000,30.1,550.3,7.1,
                14000,350.5,1.2,210,0,'0','FNC','a',1783,'0',35121
            );
        ''')
    return database


def state(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            'columns': connection.execute('PRAGMA table_xinfo(players)').fetchall(),
            'rows': connection.execute('SELECT * FROM players ORDER BY id').fetchall(),
            'matches': connection.execute('SELECT * FROM matches ORDER BY id').fetchall(),
            'indexes': connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name").fetchall(),
            'foreign_keys': connection.execute('PRAGMA foreign_key_list(players)').fetchall(),
            'foreign_key_errors': connection.execute('PRAGMA foreign_key_check').fetchall(),
        }


def test_default_is_readonly_without_lock_backup_or_importing_application(old_database):
    before = old_database.read_bytes()
    report = migration.migrate(old_database)
    assert report['status'] == 'needs_migration' and report['apply'] is False
    assert old_database.read_bytes() == before
    assert not (old_database.parent / '.sync.lock').exists()
    assert not (old_database.parent / 'backups').exists()
    code = '''import sys
from scripts.migrate_source_player_id import migrate
migrate(sys.argv[1])
assert 'app' not in sys.modules and 'config' not in sys.modules and 'dotenv' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', code, str(old_database)], cwd=ROOT,
                            capture_output=True, text=True, timeout=10, **HIDDEN)
    assert result.returncode == 0, result.stderr


def test_apply_preserves_every_old_field_PK_FK_and_index_with_restorable_backup(old_database):
    before = state(old_database)
    report = migration.migrate(old_database, apply=True)
    assert report['status'] == 'migrated'
    backup = Path(report['backup']['file'])
    assert backup.name.startswith('schema-source-player-id-')
    assert backup not in set(backup.parent.glob('lol-data-*.db'))
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == report['backup']['sha256']
    assert state(backup) == before
    after = state(old_database)
    assert after['columns'][:-1] == before['columns']
    assert after['columns'][-1][1:] == ('source_player_id', 'VARCHAR(100)', 0, None, 0, 0)
    assert after['rows'] == [row + (None,) for row in before['rows']]
    assert {row for row in after['indexes'] if row[0] != migration.INDEX} == set(before['indexes'])
    for key in ('matches', 'foreign_keys', 'foreign_key_errors'):
        assert after[key] == before[key]


def test_repeat_is_noop_and_dry_verifies_exact_structure(old_database):
    first = migration.migrate(old_database, apply=True)
    before = old_database.read_bytes()
    assert migration.migrate(old_database)['status'] == 'already_current'
    second = migration.migrate(old_database, apply=True)
    assert second['status'] == 'already_current' and 'backup' not in second
    assert old_database.read_bytes() == before
    assert list((old_database.parent / 'backups').iterdir()) == [Path(first['backup']['file'])]


def test_ten_unknown_positions_have_distinct_IDs_old_NULLs_and_same_ID_other_match_allowed(old_database):
    migration.migrate(old_database, apply=True)
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        with connection:
            for index in range(10):
                connection.execute('INSERT INTO players(id,match_id,team_name,position,source_player_id) VALUES(?,?,?,?,?)',
                                   (100 + index, 35121, 'FNC' if index < 5 else 'EDG', None, str(1000 + index)))
            connection.execute("INSERT INTO players(id,match_id,team_name,position) VALUES(200,35121,'FNC',NULL)")
            connection.execute("INSERT INTO players(id,match_id,team_name,position) VALUES(201,35121,'FNC',NULL)")
            connection.execute("INSERT INTO players(id,match_id,team_name,source_player_id) VALUES(202,28972,'T1','1000')")
        assert connection.execute('SELECT COUNT(*) FROM players WHERE match_id=35121 AND source_player_id IS NOT NULL').fetchone() == (10,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO players(id,match_id,team_name,source_player_id) VALUES(203,35121,'EDG','1000')")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO players(id,match_id,team_name,position) VALUES(204,35121,'FNC','a')")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO players(id,match_id,source_player_id) VALUES(205,999,'9999')")


def test_correct_existing_column_only_adds_unique_index(old_database):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('ALTER TABLE players ADD COLUMN source_player_id VARCHAR(100) DEFAULT NULL')
    before = state(old_database)
    assert migration.migrate(old_database)['status'] == 'needs_migration'
    migration.migrate(old_database, apply=True)
    after = state(old_database)
    assert after['columns'] == before['columns'] and after['rows'] == before['rows']


def test_duplicate_existing_source_ID_fails_atomic_index_creation(old_database):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('ALTER TABLE players ADD COLUMN source_player_id VARCHAR(100)')
        connection.execute("UPDATE players SET source_player_id='63'")
        connection.execute("INSERT INTO players(id,match_id,team_name,position,source_player_id) VALUES(52,35121,'FNC','b','63')")
        connection.commit()
    before = old_database.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        migration.migrate(old_database, apply=True)
    assert old_database.read_bytes() == before
    assert migration.migrate(old_database)['status'] == 'needs_migration'


def test_index_DDL_failure_rolls_back_new_column_and_all_old_rows(old_database, monkeypatch):
    before = state(old_database)
    encoded = old_database.read_bytes()
    original = migration.sqlite3.connect

    class FailIndex(sqlite3.Connection):
        def execute(self, statement, *arguments):
            if statement.startswith('CREATE UNIQUE INDEX'):
                raise sqlite3.OperationalError('injected real index DDL failure')
            return super().execute(statement, *arguments)

    def connect(database, *arguments, **keywords):
        if str(database).endswith('?mode=rw'):
            keywords['factory'] = FailIndex
        return original(database, *arguments, **keywords)

    monkeypatch.setattr(migration.sqlite3, 'connect', connect)
    with pytest.raises(sqlite3.OperationalError, match='real index DDL failure'):
        migration.migrate(old_database, apply=True)
    assert state(old_database) == before and old_database.read_bytes() == encoded


def test_online_backup_includes_uncheckpointed_WAL_commit(old_database):
    with closing(sqlite3.connect(old_database)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO players(id,match_id,name,team_name,position) VALUES(52,28972,'Zeus','T1','a')")
        writer.commit()
        with closing(sqlite3.connect(old_database.as_uri() + '?immutable=1', uri=True)) as main_file:
            assert main_file.execute('SELECT COUNT(*) FROM players').fetchone() == (1,)
        report = migration.migrate(old_database, apply=True)
        with closing(sqlite3.connect(report['backup']['file'])) as backup:
            assert backup.execute('SELECT id,name FROM players ORDER BY id').fetchall() == [(51, 'Wunder'), (52, 'Zeus')]
            assert 'source_player_id' not in {row[1] for row in backup.execute('PRAGMA table_info(players)')}
            assert backup.execute('PRAGMA integrity_check').fetchall() == [('ok',)]


@pytest.mark.parametrize('definition', ['TEXT', 'INTEGER', 'VARCHAR(99)', 'VARCHAR(100) NOT NULL DEFAULT 1',
                                         "VARCHAR(100) DEFAULT 'fake'", "VARCHAR(100) GENERATED ALWAYS AS ('1') VIRTUAL"])
def test_incompatible_existing_column_is_rejected_without_backup(old_database, definition):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute(f'ALTER TABLE players ADD COLUMN source_player_id {definition}')
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match='可空 VARCHAR'):
        migration.migrate(old_database, apply=True)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


@pytest.mark.parametrize('sql', [
    'CREATE INDEX uq_player_match_source_player ON players(match_id,source_player_id)',
    'CREATE UNIQUE INDEX uq_player_match_source_player ON players(source_player_id,match_id)',
    'CREATE UNIQUE INDEX uq_player_match_source_player ON players(match_id,source_player_id) WHERE source_player_id IS NOT NULL',
    'CREATE UNIQUE INDEX uq_player_match_source_player ON players(match_id,lower(source_player_id))',
    'CREATE UNIQUE INDEX uq_player_match_source_player ON players(match_id,source_player_id COLLATE NOCASE)',
    'CREATE UNIQUE INDEX uq_player_match_source_player ON players(match_id DESC,source_player_id)',
    'CREATE INDEX uq_player_match_source_player ON matches(match_id)',
    'CREATE TABLE uq_player_match_source_player(id INTEGER)',
])
def test_same_named_wrong_index_or_object_never_silently_skips(old_database, sql):
    with closing(sqlite3.connect(old_database)) as connection:
        connection.execute('ALTER TABLE players ADD COLUMN source_player_id VARCHAR(100)')
        connection.execute(sql)
    before = old_database.read_bytes()
    with pytest.raises(migration.MigrationError, match=migration.INDEX):
        migration.migrate(old_database)
    with pytest.raises(migration.MigrationError, match=migration.INDEX):
        migration.migrate(old_database, apply=True)
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()


@pytest.mark.parametrize('seconds', [-1, 61, float('inf'), float('nan')])
def test_wait_is_finite_and_bounded_without_lock_creation(old_database, seconds):
    with pytest.raises(migration.MigrationError, match='0–60'):
        migration.migrate(old_database, apply=True, wait_seconds=seconds)
    assert not (old_database.parent / '.sync.lock').exists()


def test_missing_or_non_sqlite_path_is_never_created(tmp_path):
    missing = tmp_path / 'missing.sqlite'
    assert migration.main(['--database', str(missing), '--apply']) == 2
    assert not missing.exists() and not (tmp_path / '.sync.lock').exists()
    other = tmp_path / 'text.db'
    other.write_bytes(b'not sqlite')
    assert migration.main(['--database', str(other)]) == 2
    assert other.read_bytes() == b'not sqlite'


@pytest.mark.parametrize('schema', [
    'CREATE TABLE other(id INTEGER)',
    'CREATE VIEW players AS SELECT 1 AS id',
    'CREATE TABLE players(id TEXT PRIMARY KEY,match_id INTEGER NOT NULL REFERENCES matches(match_id),'
    'name TEXT,team_name TEXT,position TEXT,UNIQUE(match_id,team_name,position))',
    'CREATE TABLE players(id INTEGER PRIMARY KEY,match_id INTEGER REFERENCES matches(match_id),'
    'name TEXT,team_name TEXT,position TEXT,UNIQUE(match_id,team_name,position))',
    'CREATE TABLE players(id INTEGER PRIMARY KEY,match_id INTEGER NOT NULL,'
    'name TEXT,team_name TEXT,position TEXT,UNIQUE(match_id,team_name,position))',
    'CREATE TABLE players(id INTEGER PRIMARY KEY,match_id INTEGER NOT NULL REFERENCES matches(match_id),'
    'name TEXT,team_name TEXT,position TEXT)',
])
def test_incompatible_base_table_never_gets_column_or_backup(tmp_path, schema):
    database = tmp_path / 'wrong.sqlite'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE matches(match_id INTEGER UNIQUE NOT NULL)')
        connection.execute(schema)
    before = database.read_bytes()
    with pytest.raises(migration.MigrationError):
        migration.migrate(database, apply=True)
    assert database.read_bytes() == before
    assert not (tmp_path / 'backups').exists()


def test_failed_final_structure_verification_rolls_back_both_DDLs(old_database, monkeypatch):
    before = state(old_database)
    encoded = old_database.read_bytes()
    original = migration.inspect_schema

    def reject_created_index(connection):
        status = original(connection)
        if status == 'already_current':
            raise migration.MigrationError('injected final structure rejection')
        return status

    monkeypatch.setattr(migration, 'inspect_schema', reject_created_index)
    with pytest.raises(migration.MigrationError, match='final structure rejection'):
        migration.migrate(old_database, apply=True)
    assert state(old_database) == before and old_database.read_bytes() == encoded


def test_real_temp_process_lock_contention_returns_three_without_ddl(old_database):
    before = old_database.read_bytes()
    with PipelineLock(old_database.parent / '.sync.lock'):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'scripts.migrate_source_player_id',
                                 '--database', str(old_database), '--apply', '--wait-seconds', '.01'],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=10, **HIDDEN)
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout)['status'] == 'already_running'
    assert old_database.read_bytes() == before
    assert not (old_database.parent / 'backups').exists()
