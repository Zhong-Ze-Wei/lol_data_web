import copy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services import ingestion
from app.services.ingestion import InvalidResult, ingest_result, normalize_result
from app.services.team_names import resolve_team_names


@pytest.fixture
def named_source():
    payload = json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_text('utf-8'))
    payload['data']['result_list'].update(red_teamID='17', blue_teamID='1')
    schedule = {
        'series_id': 58146,
        'source_row': {'matchID': '58146', 'teamID_a': '1', 'teamID_b': '17',
                       'team_short_name_a': '历史EDG', 'team_short_name_b': '历史LGD'},
        'source_archive': {'raw_file': 'stages/1/2.json', 'sha256': 'a' * 64},
        'detail_archive': {'raw_file': 'scoregg/66845.json', 'sha256': 'b' * 64},
    }
    return payload, schedule


def resolve(payload, schedule):
    info = payload['data']['result_list']
    return resolve_team_names(payload['data'], schedule, {side: info.get(f'{side}_name') for side in ('red', 'blue')})


def test_schedule_names_follow_ids_instead_of_a_b_or_current_club_labels(named_source):
    payload, schedule = named_source
    frozen = copy.deepcopy((payload, schedule))
    names, proof = resolve(payload, schedule)
    assert names == {'red': '历史LGD', 'blue': '历史EDG'}
    assert proof['selected_source'] == 'schedule' and proof['status'] == 'verified'
    assert proof['side_mapping'] == {'red': 'b', 'blue': 'a'}
    assert proof['detail']['names'] == {'red': 'LGD', 'blue': 'EDG'}
    assert proof['schedule']['archive'] == schedule['source_archive']
    assert proof['detail']['archive'] == schedule['detail_archive']
    canonical = json.dumps(schedule['source_row'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert proof['schedule']['canonical_row_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert (payload, schedule) == frozen


@pytest.mark.parametrize(('target', 'field', 'value', 'reason'), [
    ('detail_mvp', 'match_id', None, 'missing_series_identity'),
    ('row', 'matchID', None, 'missing_series_identity'),
    ('schedule', 'series_id', None, 'missing_series_identity'),
    ('row', 'matchID', '58147', 'series_identity_mismatch'),
    ('schedule', 'series_id', 58147, 'series_identity_mismatch'),
    ('row', 'teamID_a', None, 'missing_team_identity'),
    ('row', 'teamID_a', '0', 'missing_team_identity'),
    ('row', 'teamID_a', '-1', 'missing_team_identity'),
    ('row', 'teamID_a', True, 'missing_team_identity'),
    ('row', 'teamID_a', '1.0', 'missing_team_identity'),
    ('row', 'teamID_a', '１７', 'missing_team_identity'),
    ('info', 'red_teamID', None, 'missing_team_identity'),
    ('row', 'teamID_a', '17', 'duplicate_team_identity'),
    ('info', 'blue_teamID', '17', 'duplicate_team_identity'),
    ('row', 'teamID_a', '704', 'team_identity_mismatch'),
    ('row', 'team_short_name_a', '', 'missing_schedule_label'),
    ('row', 'team_short_name_a', 1, 'missing_schedule_label'),
    ('row', 'team_short_name_a', ' 历史LGD ', 'duplicate_schedule_label'),
])
def test_incomplete_or_conflicting_identity_keeps_original_detail_names(named_source, target, field, value, reason):
    payload, schedule = named_source
    sources = {'detail_mvp': payload['data']['max_mvp'], 'row': schedule['source_row'],
               'schedule': schedule, 'info': payload['data']['result_list']}
    sources[target][field] = value
    names, proof = resolve(payload, schedule)
    assert names == {'red': 'LGD', 'blue': 'EDG'}
    assert proof['selected_source'] == 'detail' and proof['status'] == 'unresolved'
    assert proof['reason'] == reason and 'side_mapping' not in proof


def test_absent_real_schedule_row_does_not_create_a_name_association(named_source):
    payload, schedule = named_source
    schedule.pop('source_row')
    names, proof = resolve(payload, schedule)
    assert names == {'red': 'LGD', 'blue': 'EDG'}
    assert proof['reason'] == 'no_schedule_source' and proof['schedule'] is None


@pytest.mark.parametrize('contradiction', ['auxiliary_teams', 'partial_auxiliary_team', 'auxiliary_series', 'more_teams'])
def test_explicit_auxiliary_or_multiple_team_conflict_keeps_detail_labels(named_source, contradiction):
    payload, schedule = named_source
    if contradiction == 'auxiliary_teams':
        payload['data']['result_list'].update(teamID_a='704', teamID_b='17')
    elif contradiction == 'partial_auxiliary_team':
        payload['data']['result_list']['teamID_a'] = '704'
    elif contradiction == 'auxiliary_series':
        payload['data']['max_beiguo']['match_id'] = '999'
    else:
        schedule['source_row']['more_team_list'] = [{'teamID': '999'}]
    names, proof = resolve(payload, schedule)
    assert names == {'red': 'LGD', 'blue': 'EDG'}
    assert proof['selected_source'] == 'detail' and proof['status'] == 'unresolved'


def test_legacy_null_natural_keys_are_cleared_before_becoming_verified(db, named_source):
    payload, schedule = named_source
    original_ingest(db, payload)
    db.session.query(Match).update({'verified': False, 'source': 'legacy'})
    db.session.add(Team(match_id=66845, team_name=None, attack=999999))
    db.session.add(Player(match_id=66845, team_name=None, position='a', name='不可信旧值', atk=999999))
    db.session.add(Player(match_id=66845, team_name='历史LGD', position=None, name='不可信空位置', atk=999999))
    db.session.commit()
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    assert db.session.query(Match).one().verified
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 10
    assert not db.session.query(Player).filter_by(atk=999999).count()


def test_explicit_detail_bo_mismatch_is_still_rejected(named_source):
    payload, schedule = named_source
    payload['data']['max_mvp']['match_id'] = '123'
    with pytest.raises(InvalidResult, match='BO'):
        normalize_result(payload, 66845, schedule)


def test_verified_schedule_can_supply_missing_detail_label(named_source):
    payload, schedule = named_source
    payload['data']['result_list']['red_name'] = None
    match = normalize_result(payload, 66845, schedule)['matches'][0]
    assert match['red_team_name'] == '历史LGD'
    assert match['team_name_provenance']['detail']['names']['red'] is None


def test_all_business_names_and_winner_use_same_policy(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    match = db.session.query(Match).one()
    proof = match.team_name_provenance
    assert proof['selected_names'] == {'red': match.red_team_name, 'blue': match.blue_team_name}
    winning_team = db.session.query(Team).filter_by(result=1).one()
    assert match.win_team_name == winning_team.team_name
    assert {team.team_name for team in db.session.query(Team)} == {'历史LGD', '历史EDG'}
    assert {player.team_name for player in db.session.query(Player)} == {'历史LGD', '历史EDG'}


def original_ingest(db, payload):
    assert ingest_result(payload, 66845).status == 'imported'
    return {player.position: (player.id, player.pic) for player in db.session.query(Player).filter_by(team_name='LGD')}


def test_verified_rename_preserves_row_ids_and_known_optional_values(db, named_source):
    payload, schedule = named_source
    players = original_ingest(db, payload)
    teams = {row.team_name: row.id for row in db.session.query(Team)}
    payload['data']['result_list'].pop('red_star_a_pic')
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    player = db.session.query(Player).filter_by(team_name='历史LGD', position='a').one()
    assert (player.id, player.pic) == players['a']
    assert db.session.query(Team).filter_by(team_name='历史LGD').one().id == teams['LGD']
    assert db.session.query(Team).filter_by(team_name='历史EDG').one().id == teams['EDG']
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 10
    assert db.session.query(Player).filter_by(team_name='历史LGD', position='a').one().id == players['a'][0]


def test_label_swap_is_atomic_without_unique_key_collision(db, named_source):
    payload, schedule = named_source
    players = original_ingest(db, payload)
    schedule['source_row'].update(team_short_name_a='LGD', team_short_name_b='EDG')
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    assert db.session.query(Player).filter_by(team_name='EDG', position='a').one().id == players['a'][0]
    assert db.session.query(Match).one().red_team_name == 'EDG'
    assert db.session.query(Player).count() == 10


def test_different_player_in_same_slot_does_not_inherit_previous_photo(db, named_source):
    payload, schedule = named_source
    players = original_ingest(db, payload)
    payload['data']['result_list'].update(red_star_a_name='另一位选手')
    payload['data']['result_list'].pop('red_star_a_pic')
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    player = db.session.query(Player).filter_by(team_name='历史LGD', position='a').one()
    assert player.name == '另一位选手' and player.pic is None
    assert player.id != players['a'][0]


def test_changed_player_with_unchanged_canonical_team_does_not_inherit_photo_or_damage(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    old = db.session.query(Player).filter_by(team_name='历史LGD', position='a').one()
    old_id = old.id
    assert old.pic and old.atk > 0
    payload['data']['result_list']['red_star_a_name'] = '另一位选手'
    payload['data']['result_list'].pop('red_star_a_pic')
    payload['data']['result_list'].pop('red_star_a_atk_o')
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    player = db.session.query(Player).filter_by(team_name='历史LGD', position='a').one()
    assert player.name == '另一位选手' and player.pic is None and player.atk is None
    assert player.id != old_id
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 10


def test_unverified_legacy_rows_do_not_carry_optional_data_into_renamed_rows(db, named_source):
    payload, schedule = named_source
    original_ingest(db, payload)
    db.session.query(Match).update({'verified': False, 'source': 'legacy'})
    db.session.commit()
    payload['data']['result_list'].pop('red_star_a_pic')
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    assert db.session.query(Player).filter_by(team_name='历史LGD', position='a').one().pic is None


def test_rename_rollback_restores_names_ids_and_provenance(db, named_source, monkeypatch):
    payload, schedule = named_source
    players = original_ingest(db, payload)
    original = ingestion.bulk_upsert

    def fail_team(model, rows, keys, session=None, preserve_nulls=True):
        if model is Team:
            raise IntegrityError('rename failure', {}, Exception('failure'))
        return original(model, rows, keys, session, preserve_nulls)

    monkeypatch.setattr(ingestion, 'bulk_upsert', fail_team)
    assert ingest_result(payload, 66845, schedule).status == 'failed'
    assert db.session.query(Match).one().team_name_provenance['selected_source'] == 'detail'
    assert db.session.query(Match).one().red_team_name == 'LGD'
    assert db.session.query(Player).filter_by(team_name='LGD', position='a').one().id == players['a'][0]
    assert {row.team_name for row in db.session.query(Team)} == {'LGD', 'EDG'}


def test_no_schedule_refresh_retains_previously_verified_historical_labels(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    before = copy.deepcopy(db.session.query(Match).one().team_name_provenance)
    player_ids = {player.id for player in db.session.query(Player)}
    payload['data']['result_list']['red_star_a_kills'] = '9'
    assert ingest_result(payload, 66845).status == 'imported'
    match = db.session.query(Match).one()
    assert match.red_team_name == '历史LGD' and match.blue_team_name == '历史EDG'
    assert match.team_name_provenance['reason'] == 'previous_verified_schedule_same_series_and_team_ids'
    assert match.team_name_provenance['schedule'] == before['schedule']
    assert match.team_name_provenance['detail']['canonical_data_sha256'] != before['detail']['canonical_data_sha256']
    assert {player.id for player in db.session.query(Player)} == player_ids
    assert db.session.query(Player).filter_by(team_name='历史LGD', position='a').one().kills == 9


def test_explicit_conflicting_schedule_does_not_inherit_previous_label_proof(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    schedule['source_row']['teamID_a'] = '704'
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    match = db.session.query(Match).one()
    assert match.red_team_name == 'LGD' and match.blue_team_name == 'EDG'
    assert match.team_name_provenance['reason'] == 'team_identity_mismatch'


def test_changed_detail_identity_does_not_reuse_previous_schedule(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    payload['data']['result_list']['red_teamID'] = '999'
    assert ingest_result(payload, 66845).status == 'imported'
    match = db.session.query(Match).one()
    assert match.red_team_name == 'LGD' and match.team_name_provenance['status'] == 'unresolved'


def test_prior_proof_can_rekey_changed_labels_when_new_detail_names_also_changed(db, named_source):
    payload, schedule = named_source
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    before = {player.id for player in db.session.query(Player)}
    schedule['source_row']['team_short_name_b'] = '赛程更正LGD'
    payload['data']['result_list']['red_name'] = '详情更正LGD'
    assert ingest_result(payload, 66845, schedule).status == 'imported'
    assert {player.id for player in db.session.query(Player)} == before
    assert db.session.query(Match).one().red_team_name == '赛程更正LGD'
