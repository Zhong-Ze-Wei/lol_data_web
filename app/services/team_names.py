"""按同一 BO 和双方来源 ID 选择赛程队名；不推断俱乐部沿革或转会。"""

import hashlib
import json


def _positive_id(value):
    text = str(value).strip() if value is not None else ''
    return int(text) if text.isascii() and text.isdigit() and int(text) > 0 else None


def _canonical_sha256(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _declared_bo(data, block_name):
    block = data.get(block_name)
    if block is None or block == []:
        return None, None
    if not isinstance(block, dict):
        return None, f'invalid_{block_name}_series_identity'
    value = block.get('match_id')
    if value is None or isinstance(value, str) and not value.strip():
        return None, None
    identifier = _positive_id(value)
    return identifier, None if identifier is not None else f'invalid_{block_name}_series_identity'


def resolve_bo_identity(data):
    """仅按来源明确声明 BO；主块缺失时可用备用，冲突或坏值不能绕过。"""
    primary, primary_error = _declared_bo(data, 'max_mvp')
    auxiliary, auxiliary_error = _declared_bo(data, 'max_beiguo')
    error = primary_error or auxiliary_error
    if error is None and primary is not None and auxiliary is not None and primary != auxiliary:
        error = 'auxiliary_series_identity_mismatch'
    identifier = (primary if primary is not None else auxiliary) if error is None else None
    source = ('max_mvp.match_id' if primary is not None else 'max_beiguo.match_id') if identifier is not None else None
    return {'series_id': identifier, 'source': source, 'primary_series_id': primary,
            'auxiliary_series_id': auxiliary, 'error': error}


def _result_flag(value):
    """与入库 numeric/_winner 相同的数值表示；只认可靠的 0/1。"""
    text = str(value).strip().replace(',', '').removesuffix('%')
    multiplier = 1000 if text.lower().endswith('k') else 1
    try:
        number = float(text[:-1] if multiplier == 1000 else text) * multiplier
    except (TypeError, ValueError):
        return None
    return int(number) if number in (0, 1) else None


def winner_identity_error(info, results=None):
    """缺胜方不推断；明确胜方须属于双方，并与已明确的红蓝结果一致。"""
    value = info.get('win_teamID')
    if value is None or isinstance(value, str) and not value.strip():
        return None
    winner = _positive_id(value)
    if winner is None:
        return 'invalid_winner_identity'
    identifiers = {side: _positive_id(info.get(f'{side}_teamID')) for side in ('red', 'blue')}
    if winner not in identifiers.values():
        return 'winner_team_identity_mismatch'
    if results is None:
        results = {side: _result_flag(info.get(f'{side}_result')) for side in identifiers}
    if set(results.values()) == {0, 1}:
        winning_side = next(side for side in results if results[side] == 1)
        if identifiers[winning_side] != winner:
            return 'winner_result_mismatch'
    return None


def resolve_team_names(data, schedule, detail_names, previous=None):
    """返回 red/blue 名称与证据；缺任一身份依据时保留详情名称。"""
    schedule = schedule or {}
    info = data['result_list']
    row = schedule.get('source_row')
    detail_ids = {side: _positive_id(info.get(f'{side}_teamID')) for side in ('red', 'blue')}
    identity = resolve_bo_identity(data)
    detail_series = identity['series_id']
    winner_error = winner_identity_error(info)
    provenance = {
        'policy_version': 2, 'selected_source': 'detail', 'status': 'unresolved',
        'reason': 'no_schedule_source', 'selected_names': dict(detail_names),
        'detail': {'names': dict(detail_names), 'team_ids': detail_ids, 'series_id': detail_series,
                   'series_id_source': identity['source'], 'primary_series_id': identity['primary_series_id'],
                   'auxiliary_series_id': identity['auxiliary_series_id'],
                   'canonical_data_sha256': _canonical_sha256(data), 'archive': schedule.get('detail_archive')},
        'schedule': None,
    }
    retained = (not isinstance(row, dict) and previous is not None
                and previous['selected_source'] == 'schedule' and previous['status'] == 'verified')
    if retained:
        prior = previous['schedule']
        row = {'matchID': prior['series_id'],
               **{f'teamID_{side}': value for side, value in prior['team_ids'].items()},
               **{f'team_short_name_{side}': value for side, value in prior['names'].items()}}
    elif not isinstance(row, dict):
        provenance['reason'] = identity['error'] or winner_error or 'no_schedule_source'
        return dict(detail_names), provenance
    labels = {side: row.get(f'team_short_name_{side}') for side in ('a', 'b')}
    schedule_ids = {side: _positive_id(row.get(f'teamID_{side}')) for side in ('a', 'b')}
    schedule_series = _positive_id(row.get('matchID'))
    auxiliary_ids = [_positive_id(info.get(f'teamID_{side}')) for side in ('a', 'b')]
    provenance['detail']['auxiliary_team_ids'] = auxiliary_ids
    provenance['schedule'] = dict(previous['schedule']) if retained else {
        'names': labels, 'team_ids': schedule_ids, 'series_id': schedule_series,
        'canonical_row_sha256': _canonical_sha256(row),
        'archive': schedule.get('source_archive'),
        'more_team_list': row.get('more_team_list'),
    }
    declared_series = (detail_series if retained and schedule.get('series_id') is None
                       else _positive_id(schedule.get('series_id')))
    if identity['error'] or winner_error:
        reason = identity['error'] or winner_error
    elif detail_series is None or schedule_series is None or declared_series is None:
        reason = 'missing_series_identity'
    elif not detail_series == schedule_series == declared_series:
        reason = 'series_identity_mismatch'
    elif None in detail_ids.values() or None in schedule_ids.values():
        reason = 'missing_team_identity'
    elif len(set(detail_ids.values())) != 2 or len(set(schedule_ids.values())) != 2:
        reason = 'duplicate_team_identity'
    elif set(detail_ids.values()) != set(schedule_ids.values()):
        reason = 'team_identity_mismatch'
    elif (any(identifier not in detail_ids.values() for identifier in auxiliary_ids if identifier is not None)
          or None not in auxiliary_ids and set(auxiliary_ids) != set(detail_ids.values())):
        reason = 'auxiliary_team_identity_mismatch'
    elif row.get('more_team_list'):
        reason = 'multiple_schedule_teams'
    elif any(not isinstance(name, str) or not name.strip() for name in labels.values()):
        reason = 'missing_schedule_label'
    elif labels['a'].strip() == labels['b'].strip():
        reason = 'duplicate_schedule_label'
    else:
        mapping = {side: next(slot for slot in schedule_ids if schedule_ids[slot] == team_id)
                   for side, team_id in detail_ids.items()}
        names = {side: labels[slot].strip() for side, slot in mapping.items()}
        reason = 'previous_verified_schedule_same_series_and_team_ids' if retained else 'same_series_and_team_ids'
        provenance.update(selected_source='schedule', status='verified', reason=reason,
                          selected_names=names, side_mapping=mapping)
        return names, provenance
    provenance['reason'] = reason
    return dict(detail_names), provenance
