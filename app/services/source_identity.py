"""离线扫描公开战报的同源身份依据；不猜别名，不依赖选手数组顺序。"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path


def source_player_id(value):
    text = str(value).strip() if value is not None else ''
    return str(int(text)) if text.isdigit() and int(text) > 0 else None


def slot_identity(data, side, position):
    """星位与 teams 中的 ID、颜色必须唯一对应，才允许补回空昵称。"""
    info = data.get('result_list') or {}
    identifier = source_player_id(info.get(f'{side}_star_{position}_playerID'))
    if identifier is None:
        return None
    slots = [(color, pos) for color in ('red', 'blue') for pos in 'abcde'
             if source_player_id(info.get(f'{color}_star_{pos}_playerID')) == identifier]
    if slots != [(side, position)]:
        return None
    roster = data.get('teams')
    if not isinstance(roster, list):
        return None
    rows = [row for row in roster if isinstance(row, dict)
            and source_player_id(row.get('playerID')) == identifier]
    if len(rows) != 1 or rows[0].get('color') != side:
        return None
    return identifier, rows[0]


def build_source_name_index(raw_dir):
    """一次扫描 raw/scoregg，返回无冲突的 ID→昵称及原始 SHA 依据。零 HTTP。"""
    candidates = defaultdict(lambda: defaultdict(list))
    report = {'request_count': 0, 'checked': 0, 'accepted': 0, 'rejected': [],
              'names_by_source_id': {}, 'conflicts': {}}
    for raw in sorted((Path(raw_dir) / 'scoregg').glob('*.json')):
        if not raw.stem.isdigit():
            continue
        result_id = int(raw.stem)
        report['checked'] += 1
        try:
            encoded = raw.read_bytes()
            payload = json.loads(encoded)
            data = payload.get('data')
            if not isinstance(data, dict) or str(data.get('gameID')) != '1':
                raise ValueError('不是可确认的 LOL 战报')
            if payload.get('code', 200) not in (200, '200'):
                raise ValueError('来源状态失败')
            info = data.get('result_list')
            if not isinstance(info, dict):
                raise ValueError('缺少 result_list')
            for declared in (data.get('resultID'), info.get('resultID')):
                if declared not in (None, '') and int(declared) != result_id:
                    raise ValueError('显式 resultID 与归档文件名不一致')
            sha = hashlib.sha256(encoded).hexdigest()
            for side in ('red', 'blue'):
                for position in 'abcde':
                    identity = slot_identity(data, side, position)
                    if identity is None:
                        continue
                    identifier, roster_row = identity
                    for source_field, value in (
                        (f'result_list.{side}_star_{position}_name', info.get(f'{side}_star_{position}_name')),
                        (f'teams[playerID={identifier},color={side}].nickname', roster_row.get('nickname')),
                    ):
                        if not isinstance(value, str) or not value.strip() or '\ufffd' in value:
                            continue
                        name = value.strip()
                        candidates[identifier][name.casefold()].append({
                            'name': name, 'result_id': result_id, 'raw_file': str(raw.resolve()),
                            'raw_sha256': sha, 'source_field': source_field,
                            'team_color': side, 'position': position,
                        })
            report['accepted'] += 1
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            report['rejected'].append({'raw_file': str(raw), 'reason': str(exc)})
    for identifier, names in sorted(candidates.items()):
        if len(names) != 1:
            report['conflicts'][identifier] = sorted({ref['name'] for refs in names.values() for ref in refs})
            continue
        references = next(iter(names.values()))
        report['names_by_source_id'][identifier] = {
            'source_player_id': identifier, 'name': references[0]['name'],
            'references': references, 'reference_count': len(references),
        }
    return report


def recover_slot_name(data, side, position, names_by_source_id):
    identity = slot_identity(data, side, position)
    if identity is None or not names_by_source_id:
        return None
    identifier, _ = identity
    entry = names_by_source_id.get(identifier)
    if not isinstance(entry, dict) or entry.get('source_player_id') != identifier:
        return None
    name, references = entry.get('name'), entry.get('references')
    if (not isinstance(name, str) or not name.strip() or '\ufffd' in name
            or not isinstance(references, list) or not references):
        return None
    if any(not isinstance(ref, dict) or ref.get('name', '').casefold() != name.casefold()
           or not ref.get('raw_file') or not ref.get('raw_sha256') or not ref.get('result_id')
           for ref in references):
        return None
    # 全部候选已离线检查；单局审计保留两个不同战报的依据，避免重复复制整个索引。
    proof, seen_results = [], set()
    for ref in references:
        if ref['result_id'] not in seen_results:
            proof.append(ref)
            seen_results.add(ref['result_id'])
        if len(proof) == 2:
            break
    return {'source_player_id': identifier, 'name': name, 'team_color': side, 'position': position,
            'references': proof, 'reference_count': len(references)}
