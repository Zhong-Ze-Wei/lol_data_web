"""公开旧战报最小投影：保守区分整族占位与个体真实零，原始文件不变。"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.models.sync import SyncTask
from app.services import history, ingestion
from app.services.history import repair_archived_results
from app.services.ingestion import ingest_result, normalize_result


# 仅摘录归档原件中业务校验所需字段；CI 无需本机 data/raw 或网络。
SLOT_FIELDS = ["name", "kills", "deaths", "assists", "kda", "part", "money_o", "money_M", "hits", "adc_m", "atk_o", "atk_p", "atk_m", "def_o", "def_p", "def_m", "wp_m", "hero_name", "hero_lv"]
PUBLIC_CASES = {
    3260: {
        'updated_at': "20210728115723",
        'max_mvp': {"match_id": "1613", "nickname": "Corn"}, 'max_beiguo': {"nickname": "Looper"},
        'info': {"game_time_m": "44", "game_time_s": "42", "red_name": "RYL", "blue_name": "M3", "red_result": "1", "blue_result": "0", "red_kill": "24", "blue_kill": "12", "red_money": "77503", "blue_money": "62565", "red_attack": "0", "blue_attack": "0", "red_tower": "0", "blue_tower": "0", "red_small_dargon": "0", "blue_small_dargon": "0", "red_big_dargon": "0", "blue_big_dargon": "0"},
        'players': [
            ["red", "a", "Cola", "2", "4", "16", "4.5", "75", "15658", "355", "269", "16140", "0", "0", "0", "0", "0", "0", "0", "迷失之牙", "0"],
            ["red", "b", "InSec", "2", "3", "12", "4.7", "58.33", "12040", "273", "97", "5820", "0", "0", "0", "0", "0", "0", "0", "傲之追猎者", "0"],
            ["red", "c", "Corn", "10", "1", "10", "20", "83.33", "18262", "415", "285", "17100", "0", "0", "0", "0", "0", "0", "0", "虚空行者", "0"],
            ["red", "d", "HYY", "7", "1", "13", "20", "83.33", "19027", "432", "357", "21420", "0", "0", "0", "0", "0", "0", "0", "英勇投弹手", "0"],
            ["red", "e", "Zero", "3", "3", "19", "7.3", "91.67", "12516", "284", "61", "3660", "0", "0", "0", "0", "0", "0", "0", "魂锁典狱长", "0"],
            ["blue", "a", "Looper", "2", "5", "6", "1.6", "66.67", "12447", "282", "235", "14100", "0", "0", "0", "0", "0", "0", "0", "黑暗之女", "0"],
            ["blue", "b", "Ruo", "2", "4", "6", "2", "66.67", "11078", "251", "131", "7860", "0", "0", "0", "0", "0", "0", "0", "盲僧", "0"],
            ["blue", "c", "dade", "4", "5", "7", "2.2", "91.67", "14796", "336", "312", "18720", "0", "0", "0", "0", "0", "0", "0", "未来守护者", "0"],
            ["blue", "d", "Candyseven", "4", "4", "4", "2", "66.67", "15736", "357", "360", "21600", "0", "0", "0", "0", "0", "0", "0", "圣枪游侠", "0"],
            ["blue", "e", "Lovecd", "0", "6", "9", "1.5", "75", "8508", "193", "54", "3240", "0", "0", "0", "0", "0", "0", "0", "弗雷尔卓德之心", "0"],
        ],
    },
    3657: {
        'updated_at': "20230414021502",
        'max_mvp': {"match_id": "1696", "nickname": "Rookie"}, 'max_beiguo': {"nickname": "Cool"},
        'info': {"game_time_m": "0", "game_time_s": "01", "red_name": "IG", "blue_name": "OMG", "red_result": "1", "blue_result": "0", "red_kill": "31", "blue_kill": "17", "red_money": "75726", "blue_money": "57620", "red_attack": "0", "blue_attack": "0", "red_tower": "0", "blue_tower": "0", "red_small_dargon": "0", "blue_small_dargon": "0", "red_big_dargon": "0", "blue_big_dargon": "0"},
        'players': [
            ["red", "a", "Zz1tai", "1", "4", "13", "3.5", "45.16", "14755", None, "295", "17700", "0", "0", "0", "0", "0", "0", "0", "仙灵女巫", "0"],
            ["red", "b", "KaKAO", "7", "4", "15", "5.5", "70.97", "15180", None, "110", "6600", "0", "0", "0", "0", "0", "0", "0", "虚空遁地兽", "0"],
            ["red", "c", "Rookie", "16", "2", "5", "10.5", "67.74", "19122", None, "318", "19080", "0", "0", "0", "0", "0", "0", "0", "九尾妖狐", "0"],
            ["red", "d", "KidKid", "7", "4", "11", "4.5", "58.06", "16101", None, "263", "15780", "0", "0", "0", "0", "0", "0", "0", "深渊巨口", "0"],
            ["red", "e", "Kitties", "0", "3", "19", "6.3", "61.29", "10568", None, "21", "1260", "0", "0", "0", "0", "0", "0", "0", "唤潮鲛姬", "0"],
            ["blue", "a", "Gogoing", "3", "6", "10", "2.2", "76.47", "11879", None, "205", "12300", "0", "0", "0", "0", "0", "0", "0", "扭曲树精", "0"],
            ["blue", "b", "LoveLing", "3", "5", "6", "1.8", "52.94", "9555", None, "83", "4980", "0", "0", "0", "0", "0", "0", "0", "雪原双子", "0"],
            ["blue", "c", "Cool", "4", "9", "6", "1.1", "58.82", "12743", None, "277", "16620", "0", "0", "0", "0", "0", "0", "0", "机械先驱", "0"],
            ["blue", "d", "Uzi", "7", "3", "7", "4.7", "82.35", "15334", None, "342", "20520", "0", "0", "0", "0", "0", "0", "0", "圣枪游侠", "0"],
            ["blue", "e", "Cloud", "0", "8", "9", "1.1", "52.94", "8109", None, "19", "1140", "0", "0", "0", "0", "0", "0", "0", "黑暗之女", "0"],
        ],
    },
    3781: {
        'updated_at': "20230414022708",
        'max_mvp': {"match_id": "1781", "nickname": "clearlove"}, 'max_beiguo': {"nickname": "AmazingJ"},
        'info': {"game_time_m": "0", "game_time_s": "01", "red_name": "EDG", "blue_name": "EPA", "red_result": "1", "blue_result": "0", "red_kill": "24", "blue_kill": "8", "red_money": "66235", "blue_money": "49149", "red_attack": "0", "blue_attack": "0", "red_tower": "0", "blue_tower": "0", "red_small_dargon": "0", "blue_small_dargon": "0", "red_big_dargon": "0", "blue_big_dargon": "0"},
        'players': [
            ["red", "a", "Koro1", "5", "1", "12", "17", "70.83", "15169", None, "280", "16800", "0", "0", "0", "0", "0", "0", "0", "战争之影", "0"],
            ["red", "b", "clearlove", "1", "1", "21", "22", "91.67", "11603", None, "110", "6600", "0", "0", "0", "0", "0", "0", "0", "德玛西亚皇子", "0"],
            ["red", "c", "PawN", "10", "0", "9", "19", "79.17", "14760", None, "266", "15960", "0", "0", "0", "0", "0", "0", "0", "沙漠皇帝", "0"],
            ["red", "d", "Deft", "7", "3", "16", "7.7", "95.83", "16310", None, "319", "19140", "0", "0", "0", "0", "0", "0", "0", "法外狂徒", "0"],
            ["red", "e", "Meiko", "1", "3", "16", "5.7", "70.83", "8393", None, "9", "540", "0", "0", "0", "0", "0", "0", "0", "魂锁典狱长", "0"],
            ["blue", "a", "AmazingJ", "1", "5", "3", "0.8", "50", "10445", None, "231", "13860", "0", "0", "0", "0", "0", "0", "0", "龙血武姬", "0"],
            ["blue", "b", "Drizzle", "0", "5", "6", "1.2", "75", "8223", None, "85", "5100", "0", "0", "0", "0", "0", "0", "0", "雪原双子", "0"],
            ["blue", "c", "Raphael", "2", "4", "2", "1", "50", "11304", None, "284", "17040", "0", "0", "0", "0", "0", "0", "0", "虚空行者", "0"],
            ["blue", "d", "ZangAo", "4", "5", "3", "1.4", "87.5", "12197", None, "288", "17280", "0", "0", "0", "0", "0", "0", "0", "战争女神", "0"],
            ["blue", "e", "X1u", "1", "5", "6", "1.4", "87.5", "6980", None, "44", "2640", "0", "0", "0", "0", "0", "0", "0", "黑暗之女", "0"],
        ],
    },
    18894: {
        'updated_at': "20220309185928",
        'max_mvp': {"match_id": "9057", "nickname": "Aluka"}, 'max_beiguo': {"nickname": "Wayoff"},
        'info': {"game_time_m": "0", "game_time_s": "01", "red_name": "LM", "blue_name": "PE", "red_result": "0", "blue_result": "1", "red_kill": "14", "blue_kill": "29", "red_money": "0", "blue_money": "0", "red_attack": "0", "blue_attack": "0", "red_tower": "0", "blue_tower": "0", "red_small_dargon": "0", "blue_small_dargon": "0", "red_big_dargon": "0", "blue_big_dargon": "0"},
        'players': [
            ["red", "a", "Yao", "0", "5", "7", "1.4", "50", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "熔岩巨兽", "0"],
            ["red", "b", "Wayoff", "4", "8", "3", "0.9", "50", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "恶魔小丑", "0"],
            ["red", "c", "Snowy", "6", "8", "6", "1.5", "85.71", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "符文法师", "0"],
            ["red", "d", "Happy", "4", "3", "5", "3", "64.29", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "皮城女警", "0"],
            ["red", "e", "龙神绝", "0", "5", "8", "1.6", "57.14", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "荆棘之兴", "0"],
            ["blue", "a", "Aluka", "10", "2", "12", "11", "75.86", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "机械公敌", "0"],
            ["blue", "b", "ziv", "3", "3", "14", "5.7", "58.62", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "皮城执法官", "0"],
            ["blue", "c", "", "7", "4", "10", "4.3", "58.62", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "审判天使", "0"],
            ["blue", "d", "NaMei", "9", "3", "9", "6", "62.07", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "惩戒之箭", "0"],
            ["blue", "e", "Sicca", "0", "2", "23", "11.5", "79.31", "0", None, "0", "0", "0", "0", "0", "0", "0", "0", "0", "仙灵女巫", "0"],
        ],
    },
}


def public_result(result_id):
    case = copy.deepcopy(PUBLIC_CASES[result_id])
    info = case.pop('info')
    for side, position, *values in case.pop('players'):
        for field, value in zip(SLOT_FIELDS, values):
            source = f'{side}_hero_{position}_' + field.removeprefix('hero_') if field.startswith('hero_') else f'{side}_star_{position}_{field}'
            info[source] = value
    return {'code': 200, 'data': dict(case, gameID='1', result_list=info)}


@pytest.fixture
def result():
    return json.loads((Path(__file__).parent / 'fixtures' / 'scoregg_result_66845.json').read_text(encoding='utf-8'))


def zero_metric_families(payload, *, damage=False, economy=False, cs=False):
    info = payload['data']['result_list']
    fields = []
    if damage:
        fields.extend(('atk_o', 'atk_p', 'atk_m', 'def_o', 'def_p', 'def_m'))
    if economy:
        fields.extend(('money_o', 'money_M'))
    if cs:
        fields.extend(('hits', 'adc_m'))
    for side in ('red', 'blue'):
        for position in 'abcde':
            for field in fields:
                info[f'{side}_star_{position}_{field}'] = '0'
        if damage:
            info[f'{side}_attack'] = '0'
        if economy:
            info[f'{side}_money'] = '0'
    return payload


def metric_groups(normalized):
    return {group['group']: group for group in normalized.get('invalid_metric_groups', [])}


def test_public_3260_damage_gap_keeps_real_economy_cs_and_match_identity():
    payload = public_result(3260)
    before = copy.deepcopy(payload)
    normalized = normalize_result(payload, 3260)
    assert set(metric_groups(normalized)) == {'damage'}
    assert len(normalized['players']) == 10
    cola = next(player for player in normalized['players'] if player['name'] == 'Cola')
    assert cola['money'] == 15658 and cola['hits'] == 269 and cola['adc_m'] == 16140
    assert cola['kda'] == 4.5 and cola['kills'] == 2 and cola['part'] == 75
    assert cola['wp_m'] == 0 and cola['hero_lv'] == 0
    assert all(cola[field] is None for field in ('atk', 'atk_p', 'atk_m', 'def_', 'def_p', 'def_m'))
    assert normalized['matches'][0]['game_time'] == 2682
    assert normalized['matches'][0]['win_team_name'] == 'RYL'
    assert all(team['attack'] is None for team in normalized['teams'])
    assert all(team['money'] > 0 for team in normalized['teams'])
    assert payload == before
    group = metric_groups(normalized)['damage']
    assert group['evidence']['red_star_a_atk_o'] == '0'
    assert group['evidence']['red_kill'] == '24'
    assert len(group['cleared_fields']) == 62
    assert '矛盾' in group['reason'] and normalized['source_incomplete']


def test_public_18894_full_metric_gap_preserves_kda_and_unproven_zero_fields():
    payload = public_result(18894)
    normalized = normalize_result(payload, 18894, allow_incomplete=True)
    assert set(metric_groups(normalized)) == {'damage', 'economy', 'cs'}
    assert normalized['matches'][0]['game_time'] is None
    assert len(normalized['players']) == 9  # 原件 jojo 昵称为空；统计十槽齐全也不制造身份。
    for player in normalized['players']:
        assert all(player[field] is None for field in ('atk', 'atk_p', 'atk_m', 'def_', 'def_p', 'def_m', 'money', 'money_M', 'hits', 'adc_m'))
        assert player['kda'] is not None and player['kills'] is not None and player['part'] is not None
        assert player['wp_m'] == 0 and player['hero_lv'] == 0
    assert all(team['money'] is None and team['attack'] is None for team in normalized['teams'])
    assert all(team['tower'] == 0 and team['small_dargon'] == 0 and team['big_dargon'] == 0 for team in normalized['teams'])
    assert normalized['matches'][0]['win_team_name'] == 'PE'


@pytest.mark.parametrize('result_id', [3657, 3781])
def test_public_unknown_duration_does_not_erase_positive_economy_cs(result_id):
    normalized = normalize_result(public_result(result_id), result_id, allow_incomplete=True)
    assert normalized['matches'][0]['game_time'] is None
    assert set(metric_groups(normalized)) == {'damage'}
    assert all(player['money'] > 0 and player['hits'] > 0 for player in normalized['players'])
    assert all(player['wp_m'] == 0 for player in normalized['players'])
    assert all(team['money'] > 0 for team in normalized['teams'])


def test_daily_valid_duration_saves_partial_metric_gap_instead_of_discarding_match(db):
    outcome = ingest_result(public_result(3260), 3260)
    assert outcome.status == 'source_incomplete'
    assert db.session.query(Match).one().verified is True
    assert db.session.query(Match).one().game_time == 2682
    assert db.session.query(Team).count() == 2 and db.session.query(Player).count() == 10
    task = db.session.query(SyncTask).one()
    assert task.status == 'source_incomplete' and task.failure_count == 0 and task.next_retry_at is None
    assert '伤害' in task.last_error


def test_strict_daily_unknown_duration_retains_pending_behavior(db):
    outcome = ingest_result(public_result(18894), 18894)
    assert outcome.status == 'pending'
    assert db.session.query(Match).count() == 0


def test_previously_verified_placeholder_zero_is_force_cleared_without_losing_known_values(db):
    payload = public_result(3260)
    assert ingest_result(payload, 3260).status == 'source_incomplete'
    for model, fields in [(Player, ('atk', 'atk_p', 'atk_m', 'def_', 'def_p', 'def_m')), (Team, ('attack',))]:
        db.session.query(model).filter_by(match_id=3260).update({field: 0 for field in fields}, synchronize_session=False)
    db.session.commit()
    assert ingest_result(payload, 3260).status == 'source_incomplete'
    assert all(player.atk is None and player.def_ is None and player.atk_m is None for player in db.session.query(Player))
    assert all(team.attack is None for team in db.session.query(Team))
    cola = db.session.query(Player).filter_by(name='Cola').one()
    assert cola.money == 15658 and cola.hits == 269 and cola.kda == 4.5
    assert db.session.query(Match).count() == 1 and db.session.query(Player).count() == 10


def test_local_zero_and_floor_ward_zero_remain_real_data(result):
    info = result['data']['result_list']
    for field in ('atk_o', 'def_o', 'money_o', 'hits'):
        info['red_star_e_' + field] = '0'
    for side in ('red', 'blue'):
        for position in 'abcde':
            info[f'{side}_star_{position}_wp_m'] = '0'
    normalized = normalize_result(result, 66845)
    assert not metric_groups(normalized)
    player = next(player for player in normalized['players'] if player['team_name'] == 'LGD' and player['position'] == 'e')
    assert player['atk'] == player['def_'] == player['money'] == player['hits'] == 0
    assert all(player['wp_m'] == 0 for player in normalized['players'])


@pytest.mark.parametrize('field', ['red_star_a_atk_o', 'red_star_a_def_o', 'red_attack'])
@pytest.mark.parametrize('value', [None, 'missing', '1'])
def test_damage_qualification_requires_all_explicit_raw_zero_fields(result, field, value):
    zero_metric_families(result, damage=True)
    if value == 'missing':
        result['data']['result_list'].pop(field)
    else:
        result['data']['result_list'][field] = value
    normalized = normalize_result(result, 66845, allow_incomplete=True)
    assert not metric_groups(normalized)
    untouched = next(player for player in normalized['players'] if player['team_name'] == 'LGD' and player['position'] == 'b')
    assert untouched['atk'] == 0 and untouched['def_'] == 0


@pytest.mark.parametrize('field', ['blue_star_b_money_o', 'blue_money'])
@pytest.mark.parametrize('value', [None, 'missing', '1'])
def test_economy_and_cs_qualification_requires_complete_cross_layer_zeros(result, field, value):
    zero_metric_families(result, economy=True, cs=True)
    if value == 'missing':
        result['data']['result_list'].pop(field)
    else:
        result['data']['result_list'][field] = value
    normalized = normalize_result(result, 66845)
    assert not metric_groups(normalized)
    assert normalized['players'][0]['money'] == 0 and normalized['players'][0]['hits'] == 0


def test_cs_is_not_erased_when_economy_missing_but_someone_has_positive_cs(result):
    zero_metric_families(result, economy=True)
    normalized = normalize_result(result, 66845)
    assert set(metric_groups(normalized)) == {'economy'}
    assert all(player['hits'] > 0 for player in normalized['players'])


def test_positive_source_dependent_metrics_are_not_erased_by_a_zero_total_bundle(result):
    zero_metric_families(result, damage=True, economy=True, cs=True)
    info = result['data']['result_list']
    for field, value in [('atk_p', '25'), ('def_p', '30'), ('atk_m', '8.5'), ('money_M', '9'), ('adc_m', '3.5')]:
        info['red_star_a_' + field] = value
    normalized = normalize_result(result, 66845)
    player = normalized['players'][0]
    assert player['atk'] is None and player['def_'] is None and player['money'] is None and player['hits'] is None
    assert [player[field] for field in ('atk_p', 'def_p', 'atk_m', 'money_M', 'adc_m')] == [25, 30, 8.5, 9, 3.5]
    cleared_sources = {item['source_field'] for group in metric_groups(normalized).values() for item in group['cleared_fields']}
    assert 'red_star_a_atk_p' not in cleared_sources
    assert 'red_star_a_money_M' not in cleared_sources


@pytest.mark.parametrize('problem', ['no_kills', 'missing_slot_kills', 'inconsistent_team_kills'])
def test_unproven_combat_or_cross_layer_conflict_rejects_group_inference(result, problem):
    zero_metric_families(result, damage=True, economy=True, cs=True)
    info = result['data']['result_list']
    if problem == 'no_kills':
        for side in ('red', 'blue'):
            info[side + '_kill'] = '0'
            for position in 'abcde':
                info[f'{side}_star_{position}_kills'] = '0'
    elif problem == 'missing_slot_kills':
        info.pop('red_star_a_kills')
    else:
        info['red_kill'] = '22'
    normalized = normalize_result(result, 66845, allow_incomplete=True)
    assert not metric_groups(normalized)
    assert normalized['players'][1]['atk'] == 0 and normalized['players'][1]['money'] == 0


def test_missing_name_still_uses_all_ten_raw_slots_without_manufacturing_a_player(db, result):
    zero_metric_families(result, damage=True, economy=True, cs=True)
    result['data']['result_list']['red_star_a_name'] = ''
    normalized = normalize_result(result, 66845, allow_incomplete=True)
    assert len(normalized['players']) == 9
    assert set(metric_groups(normalized)) == {'damage', 'economy', 'cs'}
    assert all(player['atk'] is None and player['money'] is None and player['hits'] is None for player in normalized['players'])
    assert metric_groups(normalized)['damage']['evidence']['red_star_a_kills'] == '1'
    assert all(item.get('position') != 'a' or item['team_name'] != 'LGD' for group in metric_groups(normalized).values() for item in group['cleared_fields'] if item['table'] == 'players')
    assert ingest_result(result, 66845, allow_incomplete=True).status == 'source_incomplete'
    assert db.session.query(Player).count() == 9


@pytest.mark.parametrize('field,value', [('kills', 'broken'), ('kills', '-1'), ('kills', '1.5'), ('atk_o', 'broken'), ('atk_o', '-1')])
def test_bad_metric_on_unconfirmed_identity_slot_preserves_other_nine_players(result, field, value):
    zero_metric_families(result, damage=True)
    info = result['data']['result_list']
    info['red_star_a_name'] = ''
    info['red_star_a_' + field] = value
    normalized = normalize_result(result, 66845, allow_incomplete=True)
    assert len(normalized['players']) == 9
    assert not metric_groups(normalized)
    assert normalized['source_incomplete']
    assert all(player['atk'] == 0 for player in normalized['players'])


def test_partial_metric_clears_rollback_with_the_whole_match(db, result, monkeypatch):
    assert ingest_result(result, 66845).status == 'imported'
    before_attack = db.session.query(Player).filter_by(team_name='LGD', position='a').one().atk
    finish = ingestion.finish_task
    def fail_partial_task(result_id, status, error=None, schedule=None, run_id=None):
        if status == 'source_incomplete':
            raise IntegrityError('atomic_gap_clear', {}, Exception('simulated rollback'))
        return finish(result_id, status, error, schedule, run_id)
    monkeypatch.setattr(ingestion, 'finish_task', fail_partial_task)
    zero_metric_families(result, damage=True)
    assert ingest_result(result, 66845).status == 'failed'
    assert db.session.query(Player).filter_by(team_name='LGD', position='a').one().atk == before_attack
    assert db.session.query(SyncTask).one().status == 'failed'


def test_raw_repair_retains_metric_evidence_hashes_and_is_idempotent(db, tmp_path):
    payload = public_result(3260)
    schedule = {'scheduled_at': datetime(2014, 10, 3, 17), 'tournament_name': '已核对赛程'}
    ingest_result(payload, 3260, schedule)
    db.session.query(Player).filter_by(match_id=3260).update({'atk': 0, 'def_': 0}, synchronize_session=False)
    db.session.query(Team).filter_by(match_id=3260).update({'attack': 0}, synchronize_session=False)
    db.session.commit()
    raw = tmp_path / 'raw' / 'scoregg' / '3260.json'
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    source_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    audit = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[3260])
    assert audit['request_count'] == 0 and audit['changed_records'] == 1 and audit['applied'] == 0
    evidence = audit['records'][0]
    assert evidence['sha256'] == source_hash
    assert evidence['invalid_metric_groups'][0]['group'] == 'damage'
    assert evidence['invalid_metric_groups'][0]['evidence']['red_star_a_atk_o'] == '0'
    assert db.session.query(Player).filter_by(name='Cola').one().atk == 0
    applied = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[3260], apply=True)
    assert applied['applied'] == 1 and applied['failed'] == applied['blocked'] == 0
    assert applied['records'][0]['status'] == 'source_incomplete'
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == source_hash
    assert db.session.query(Player).filter_by(name='Cola').one().atk is None
    assert db.session.query(Match).one().date == schedule['scheduled_at']
    journal = [json.loads(line) for line in Path(applied['journal_file']).read_text(encoding='utf-8').splitlines()]
    assert journal == [{'result_id': 3260, 'status': 'source_incomplete', 'error': applied['records'][0]['error']}]
    saved = json.loads(Path(applied['report_file']).read_text(encoding='utf-8'))
    assert saved['journal_file'] == applied['journal_file'] and saved['applied'] == 1
    repeated = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[3260])
    assert repeated['changed_records'] == 0 and repeated['changed_fields'] == 0


def test_multi_result_repair_archives_full_plan_once_and_final_report_once(db, result, tmp_path, monkeypatch):
    raw_dir = tmp_path / 'raw' / 'scoregg'
    raw_dir.mkdir(parents=True)
    for result_id in [70, 71, 72]:
        ingest_result(result, result_id)
        changed = zero_metric_families(copy.deepcopy(result), damage=True)
        (raw_dir / f'{result_id}.json').write_text(json.dumps(changed), encoding='utf-8')
    archive = history._archive
    writes = []
    def record_archive(path, value):
        writes.append(path)
        return archive(path, value)
    monkeypatch.setattr(history, '_archive', record_archive)
    repaired = repair_archived_results(tmp_path / 'raw', tmp_path / 'reports', result_ids=[70, 71, 72], apply=True)
    assert repaired['applied'] == 3 and repaired['request_count'] == 0
    assert len(writes) == 2  # 完整审计计划一次、最终完整报告一次，不按每局重写所有证据。
    journal = [json.loads(line) for line in Path(repaired['journal_file']).read_text(encoding='utf-8').splitlines()]
    assert [row['result_id'] for row in journal] == [70, 71, 72]
    assert all(row['status'] == 'source_incomplete' for row in journal)
