"""ScoreGG 的有限预算 HTTP 客户端与 LOL 赛程发现。"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

import requests


class SourceError(Exception):
    """上游请求或结构失败；调用方持久记录，而不是把它当成零值。"""


class BudgetExceeded(SourceError):
    pass


class SourceHTTPError(SourceError):
    def __init__(self, url, status_code, response=None):
        self.url = url
        self.status_code = status_code
        self.response = response
        super().__init__(f'{url}: HTTP {status_code}')


@dataclass
class RequestBudget:
    max_requests: int = 400
    max_seconds: float = 900
    clock: object = time.monotonic
    count: int = 0

    def __post_init__(self):
        if self.max_requests < 1 or self.max_seconds <= 0:
            raise ValueError('请求数和时间预算必须为正数')
        self.started = self.clock()

    def check(self, wait=0):
        if self.count >= self.max_requests:
            raise BudgetExceeded(f'请求预算已用完 ({self.count}/{self.max_requests})')
        if self.clock() - self.started + wait >= self.max_seconds:
            raise BudgetExceeded(f'运行时间预算已用完 ({self.max_seconds}s)')

    def reserve(self):
        self.check()
        self.count += 1

    def remaining_seconds(self):
        return max(0.01, self.max_seconds - (self.clock() - self.started))


class ScoreGGClient:
    def __init__(self, budget=None, session=None, timeout=(5, 20), retries=2,
                 backoff=1, sleep=time.sleep, min_interval=0):
        self.budget = budget or RequestBudget()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.min_interval = min_interval
        self.last_request_at = None
        self.session.headers.update({'User-Agent': 'LOLData/1.0 (+bounded-public-match-sync)'})

    def _retry_delay(self, response, attempt):
        header = response.headers.get('Retry-After') if response is not None else None
        if header:
            try:
                delay = float(header)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(header).timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    delay = self.backoff * 2 ** attempt
            if delay > 30:
                raise SourceError(f'上游限流，Retry-After={header}；稍后重试')
            return max(0, delay)
        return min(30, self.backoff * 2 ** attempt)

    def get(self, url):
        return self._request('GET', url)

    def _request(self, method, url, *, data=None, on_response=None):
        for attempt in range(self.retries + 1):
            if self.last_request_at is not None and self.min_interval:
                delay = self.min_interval - (self.budget.clock() - self.last_request_at)
                if delay > 0:
                    self.budget.check(wait=delay)
                    self.sleep(delay)
            self.budget.reserve()
            self.last_request_at = self.budget.clock()
            response = None
            try:
                remaining = self.budget.remaining_seconds()
                timeout = (min(self.timeout[0], remaining), min(self.timeout[1], remaining))
                if method == 'GET':
                    response = self.session.get(url, timeout=timeout)
                else:
                    response = self.session.post(url, data=data, timeout=timeout, allow_redirects=False)
                if on_response is not None:
                    on_response(response)
                if (response.status_code == 429 or response.status_code >= 500
                        or method == 'POST' and 300 <= response.status_code < 400):
                    raise requests.HTTPError(f'HTTP {response.status_code}', response=response)
                response.raise_for_status()
                return response
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                retryable = response is None or response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == self.retries:
                    if response is not None:
                        raise SourceHTTPError(url, response.status_code, response) from exc
                    raise SourceError(f'{url}: {type(exc).__name__}: {exc}') from exc
                delay = self._retry_delay(response, attempt)
                self.budget.check(wait=delay)
                self.sleep(delay)
        raise SourceError(f'{url}: 重试次数耗尽')

    def get_json(self, url):
        try:
            return self.get(url).json()
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as exc:
            raise SourceError(f'{url}: 上游未返回有效 JSON') from exc

    def get_result(self, result_id):
        return self.get_json(f'https://img.scoregg.com/match/result/{int(result_id)}.json')

    def get_result_ids(self, series_id):
        payload = self.get_result_list(series_id)
        return result_ids_from_list(payload, series_id)

    def get_result_list(self, series_id):
        return self.get_json(f'https://img.scoregg.com/match/resultlist/{int(series_id)}.json')

    def get_match_metadata(self, series_id, *, on_response=None):
        """官网 BO 页声明的匿名元数据 POST；仍共享请求数、限速和重试预算。"""
        return self._request('POST', 'https://ho.scoregg.com/services/api_url.php', data={
            'api_path': '/services/match/match_info_new.php', 'method': 'post',
            'platform': 'web', 'api_version': '9.9.9', 'language_id': '1', 'matchID': int(series_id),
        }, on_response=on_response)


def _source_integer(value, field, *, minimum=0):
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or int(text) < minimum:
        raise SourceError(f'官网 metadata {field} 不是合法整数')
    return int(text)


def _fallback_schedule(schedule):
    """只有已归档、明确结束的双方赛程才允许向官方元数据补问单局 ID。"""
    row = schedule.get('source_row')
    archive = schedule.get('source_archive')
    if (not isinstance(row, dict) or not archive or str(schedule.get('status')) != '2'
            or str(row.get('status')) != '2' or str(row.get('is_publist')) != '1'):
        return None
    required = ('matchID', 'teamID_a', 'teamID_b', 'start_time')
    if any(row.get(key) in (None, '') for key in required) or schedule.get('tournament_id') is None:
        return None
    if row.get('more_team_list') or row.get('gameID') not in (None, '', 1, '1'):
        raise SourceError('CDN HTTP404 后的持久赛程不是可核验双方 LOL，未请求 metadata')
    identity = {key: _source_integer(row[key], key, minimum=1) for key in required}
    identity['tournamentID'] = _source_integer(schedule['tournament_id'], 'tournamentID', minimum=1)
    if row.get('game_count') not in (None, ''):
        identity['game_count'] = _source_integer(row['game_count'], 'schedule.game_count')
    if identity['matchID'] != schedule['series_id'] or identity['teamID_a'] == identity['teamID_b']:
        raise SourceError('CDN HTTP404 后的持久赛程 BO/双方身份矛盾，未请求 metadata')
    if schedule.get('scheduled_at') is None or _schedule_date(row) != schedule['scheduled_at']:
        raise SourceError('CDN HTTP404 后的持久赛程日期不一致，未请求 metadata')
    encoded = Path(archive['raw_file']).read_bytes()
    rows = json.loads(encoded)
    if (hashlib.sha256(encoded).hexdigest() != archive['sha256'] or not isinstance(rows, list)
            or sum(item == row for item in rows) != 1):
        raise SourceError('CDN HTTP404 后的赛程原件 SHA/唯一原行不成立，未请求 metadata')
    return identity


def metadata_result_list(payload, schedule):
    """校验真实 metadata，返回可用清单；不把基本指标伪装成完整战报。"""
    identity = _fallback_schedule(schedule)
    if identity is None:
        raise SourceError('官网 metadata 清单缺少可核验的结束赛程来源')
    if not isinstance(payload, dict) or payload.get('code') not in (200, '200'):
        raise SourceError('官网 metadata 返回失败状态')
    data = payload.get('data')
    if not isinstance(data, dict) or str(data.get('gameID')) != '1':
        raise SourceError('官网 metadata 未确认 LOL')
    for field in ('matchID', 'tournamentID', 'start_time'):
        if _source_integer(data.get(field), field, minimum=1) != identity[field]:
            raise SourceError(f'官网 metadata {field} 与赛程来源不一致')
    teams = {_source_integer(data.get(f'teamID_{side}'), f'teamID_{side}', minimum=1) for side in ('a', 'b')}
    if teams != {identity['teamID_a'], identity['teamID_b']}:
        raise SourceError('官网 metadata 双方 ID 与赛程来源不一致')
    if str(data.get('status')) != '2' or data.get('more_team_list'):
        raise SourceError('官网 metadata 未确认双方系列已结束')
    for side in ('a', 'b'):
        tid = _source_integer(data[f'teamID_{side}'], f'teamID_{side}', minimum=1)
        old_side = 'a' if tid == identity['teamID_a'] else 'b'
        old_score = schedule['source_row'].get(f'team_{old_side}_win')
        if old_score not in (None, '') and _source_integer(data.get(f'team_{side}_win'), f'team_{side}_win') != _source_integer(old_score, 'schedule_score'):
            raise SourceError('官网 metadata 最终比分与赛程来源不一致')
    if data.get('win_teamID') not in (None, '', 0, '0'):
        winner = _source_integer(data['win_teamID'], 'win_teamID', minimum=1)
        scores = {_source_integer(data[f'teamID_{side}'], f'teamID_{side}', minimum=1):
                  _source_integer(data.get(f'team_{side}_win'), f'team_{side}_win') for side in ('a', 'b')}
        if winner not in teams or (len(set(scores.values())) == 2 and scores[winner] != max(scores.values())):
            raise SourceError('官网 metadata 系列胜方与双方/最终比分不一致')
    rows = data.get('result_list')
    if not isinstance(rows, list):
        raise SourceError('官网 metadata result_list 必须为列表')
    count = _source_integer(data.get('result_count'), 'result_count')
    games = _source_integer(data.get('game_count'), 'game_count')
    if identity.get('game_count', 0) > 0 and games != identity['game_count']:
        raise SourceError('官网 metadata BO 格式局数与赛程来源不一致')
    if count != len(rows) or count > games:
        raise SourceError('官网 metadata result_count/game_count 与清单数量不一致')
    seen = set()
    wins = {tid: 0 for tid in teams}
    for row in rows:
        if not isinstance(row, dict):
            raise SourceError('官网 metadata 清单含非法单局结构')
        rid = _source_integer(row.get('resultID'), 'resultID', minimum=1)
        if rid in seen:
            raise SourceError('官网 metadata 清单含重复 resultID')
        seen.add(rid)
        if row.get('matchID') is not None and _source_integer(row['matchID'], 'result.matchID', minimum=1) != identity['matchID']:
            raise SourceError('官网 metadata 单局 BO 与系列身份不一致')
        row_teams = {_source_integer(row.get(f'teamID_{side}'), f'result.teamID_{side}', minimum=1) for side in ('a', 'b')}
        if row_teams != teams:
            raise SourceError('官网 metadata 单局双方与系列身份不一致')
        outcomes = {field: _source_integer(row.get(field), field, minimum=1) for field in ('win_teamID', 'los_teamID')}
        for identifier in outcomes.values():
            if identifier not in teams:
                raise SourceError('官网 metadata 单局胜负方不属于双方')
        if outcomes['win_teamID'] == outcomes['los_teamID']:
            raise SourceError('官网 metadata 单局胜负方相同')
        wins[outcomes['win_teamID']] += 1
        if row.get('url') not in (None, '', 'result'):
            raise SourceError('官网 metadata 单局声明不同详情入口，当前采集器不猜路径')
    expected = sum(_source_integer(data.get(f'team_{side}_win'), f'team_{side}_win') for side in ('a', 'b'))
    if expected > games:
        raise SourceError('官网 metadata 最终比分超过 BO 最大局数')
    for side in ('a', 'b'):
        if wins[_source_integer(data[f'teamID_{side}'], f'teamID_{side}', minimum=1)] > _source_integer(data[f'team_{side}_win'], f'team_{side}_win'):
            raise SourceError('官网 metadata 单局胜局超过明确最终比分')
    return {'code': 200, 'data': rows}, bool(rows) and count == expected


def _new_response_archive(path, response):
    if response is None:
        return None
    encoded = response.content
    with path.open('xb') as file:
        file.write(encoded)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != hashlib.sha256(encoded).hexdigest():
        raise OSError('来源响应归档后 SHA 不一致')
    return {'raw_file': str(path), 'sha256': digest, 'bytes': len(encoded),
            'basis': 'requests_response_content_application_body'}


def metadata_result_list_after_404(client, schedule, raw_dir, original_error):
    """只在真实 CDN404 后补问一次来源；两种来源及每次响应分别不可覆盖归档。"""
    expected_url = f"https://img.scoregg.com/match/resultlist/{schedule['series_id']}.json"
    if (original_error.status_code != 404 or original_error.url != expected_url
            or _fallback_schedule(schedule) is None):
        raise original_error
    directory = Path(raw_dir) / 'history' / 'resultlist-fallback' / str(schedule['series_id']) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    evidence = {'source': 'scoregg_match_metadata', 'series_id': schedule['series_id'],
                'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'planned',
                'cdn': {'url': original_error.url, 'http_status': 404,
                        'response': _new_response_archive(directory / 'cdn-404.body', original_error.response)},
                'metadata': {'url': 'https://ho.scoregg.com/services/api_url.php', 'method': 'POST',
                             'api_path': '/services/match/match_info_new.php', 'responses': []},
                'schedule_archive': schedule['source_archive'],
                'schedule_row_sha256': hashlib.sha256(json.dumps(schedule['source_row'], ensure_ascii=False,
                                                                 sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}

    def persist():
        path = directory / f'evidence-{uuid4().hex}.json'
        with path.open('x', encoding='utf-8') as file:
            json.dump(evidence, file, ensure_ascii=False, indent=2)
        return str(path)

    persist()

    def received(response):
        number = len(evidence['metadata']['responses']) + 1
        archive = _new_response_archive(directory / f'metadata-{number:02d}.body', response)
        evidence['metadata']['responses'].append({'http_status': response.status_code, 'response': archive})
        persist()

    try:
        response = client.get_match_metadata(schedule['series_id'], on_response=received)
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise SourceError('官网 metadata 未返回有效 JSON') from exc
        resultlist, complete = metadata_result_list(payload, schedule)
        evidence['status'] = 'validated'
        evidence['result_ids'] = result_ids_from_list(resultlist, schedule['series_id'])
        evidence['list_complete'] = complete
        evidence['raw_file'] = evidence['metadata']['responses'][-1]['response']['raw_file']
        evidence['sha256'] = evidence['metadata']['responses'][-1]['response']['sha256']
        evidence['evidence_file'] = persist()
        return resultlist, evidence
    except (SourceError, OSError, ValueError) as exc:
        evidence['status'] = 'budget_exhausted' if isinstance(exc, BudgetExceeded) else 'failed'
        evidence['error'] = str(exc)
        evidence_file = persist()
        if isinstance(exc, BudgetExceeded):
            raise
        raise SourceError(f'CDN HTTP404 后官网 metadata 失败: {exc}；依据 {evidence_file}') from exc


def result_ids_from_list(payload, series_id):
        if not isinstance(payload, dict) or payload.get('code') not in (200, '200'):
            raise SourceError(f'series {series_id}: resultlist 返回失败状态')
        rows = payload.get('data')
        if not isinstance(rows, list):
            raise SourceError(f'series {series_id}: resultlist.data 必须为列表')
        try:
            return sorted({int(row['resultID']) for row in rows})
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f'series {series_id}: 缺少合法 resultID') from exc


def tournament_catalog(page):
    """历史目录不以日期过滤；0000 日期仍有可用阶段和单局。"""
    rows = page.get('tournament_list')
    if not isinstance(rows, list):
        raise SourceError('官网缺少 tournament_list')
    catalog = {}
    for row in rows:
        try:
            tid = int(row['tournamentID'])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError('赛事目录缺少有效 tournamentID') from exc
        if tid < 1 or not row.get('name'):
            raise SourceError(f'tournament {tid}: 赛事 ID/名称无效')
        if tid in catalog and catalog[tid] != row:
            raise SourceError(f'tournament {tid}: 赛事目录含冲突记录')
        catalog[tid] = row
    return list(catalog.values())


def tournament_stages(rounds, tournament_id):
    if not isinstance(rounds, list):
        raise SourceError(f'tournament {tournament_id}: 阶段结构不是列表')
    entries = []
    for parent in rounds:
        try:
            parent_id = int(parent['roundID'])
            children = parent.get('round_son') or []
            if not isinstance(children, list):
                raise ValueError('round_son 不是列表')
            for child in children or [None]:
                key = str(int(child['id'])) if child is not None else f'p_{parent_id}'
                entries.append({'cache_key': key, 'parent_round_id': parent_id,
                                'name': child.get('name') if child else parent.get('name'),
                                'source': parent})
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f'tournament {tournament_id}: 阶段 ID/结构无效') from exc
    return entries


def history_schedule(row, tournament_id, tournament_name):
    try:
        sid = int(row['matchID'])
        if sid < 1:
            raise ValueError('matchID 必须为正数')
        scheduled = _schedule_date(row) if row.get('match_date') not in (None, '', '0000-00-00') else None
        publication = row.get('is_publist')
        if publication not in (None, '', 0, 1, '0', '1'):
            raise ValueError('is_publist 不在 0/1 范围')
        return {'series_id': sid, 'tournament_id': tournament_id, 'tournament_name': tournament_name,
                'scheduled_at': scheduled, 'status': str(row['status']) if row.get('status') is not None else None,
                'is_publist': int(publication) if publication not in (None, '') else None,
                'series_score': {'team_a': row.get('team_a_win'), 'team_b': row.get('team_b_win')},
                'source_row': row}
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError(f'tournament {tournament_id}: 系列赛 ID/日期/发布状态无效') from exc


def parse_tournament_page(html):
    marker = re.search(r'\bvar\s+t_data\s*=\s*', html)
    if marker is None:
        raise SourceError('官网赛程页缺少 t_data；需要检查上游结构')
    try:
        payload, _ = json.JSONDecoder().raw_decode(html[marker.end():].lstrip())
    except json.JSONDecodeError as exc:
        raise SourceError('官网 t_data 不是有效 JSON') from exc
    if not isinstance(payload, dict) or str(payload.get('gameID')) != '1':
        raise SourceError('官网赛程入口未确认是 LOL (gameID=1)')
    return payload


def _schedule_date(row):
    date = row.get('match_date')
    clock = row.get('match_time') or '00:00'
    if not date:
        raise SourceError(f"series {row.get('matchID')}: 缺少实际赛程日期")
    try:
        return datetime.fromisoformat(f'{date}T{clock}')
    except ValueError as exc:
        raise SourceError(f"series {row.get('matchID')}: 无效赛程日期 {date} {clock}") from exc


def _schedule_identity(schedule):
    """只比较采集和队名选择实际依赖的业务值；A/B 换位按来源 ID 对齐。"""
    row = schedule['source_row']
    teams = []
    for side in ('a', 'b'):
        identifier = str(row.get(f'teamID_{side}') or '').strip()
        identifier = int(identifier) if identifier.isascii() and identifier.isdigit() else identifier
        name = row.get(f'team_short_name_{side}')
        score = row.get(f'team_{side}_win')
        teams.append((identifier, name.strip() if isinstance(name, str) else name,
                      str(score).strip() if score not in (None, '') else None))
    if all(isinstance(team[0], int) and team[0] > 0 for team in teams) and teams[0][0] != teams[1][0]:
        teams.sort(key=lambda team: team[0])
    publication = schedule.get('is_publist')
    return (schedule['tournament_id'], schedule['scheduled_at'], schedule['status'],
            str(publication) if publication not in (None, '') else None,
            tuple(teams), bool(row.get('more_team_list')))


def _check_selected_schedule_sources(schedules, sources, errors):
    """只核验已选 BO 的全部已读声明；窗外其他 BO 不进入本次任务范围。"""
    selected_ids = set(schedules)
    identities = {}
    conflicted = set()
    for source in sources:
        seen = set()
        for row in source['rows']:
            identifier = str(row.get('matchID'))
            if not identifier.isascii() or not identifier.isdigit():
                continue
            sid = int(identifier)
            if sid not in selected_ids or sid in conflicted:
                continue
            previous = identities.get(sid)
            try:
                identity = _schedule_identity({
                    'tournament_id': source['tournament_id'], 'scheduled_at': _schedule_date(row),
                    'status': str(row.get('status', '')), 'is_publist': row.get('is_publist'), 'source_row': row})
                reason = '赛程原行重复或业务身份/状态冲突' if (
                    sid in seen or previous is not None and previous[0] != identity) else None
            except SourceError as exc:
                reason = str(exc)
            if reason:
                conflicted.add(sid)
                schedules.pop(sid)
                errors.append({'tournament_id': source['tournament_id'], 'series_id': sid,
                               'error': f'series {sid}: {reason}；不选择任一来源',
                               'source_url': source['source_url'],
                               'previous_source_url': previous[1] if previous else None})
            else:
                identities[sid] = (identity, source['source_url'])
            seen.add(sid)
    return sorted(conflicted)


def discover_series(client, now, window_days=14, tournament_ids=None, max_tournaments=12,
                    discovery_requests=None):
    """只读取活跃/近期赛事的阶段；matchID 是 BO 系列，不能充当 resultID。"""
    begin_count = client.budget.count if discovery_requests is not None else 0
    page = parse_tournament_page(client.get('https://www.scoregg.com/match_pc?tournamentID=1007').text)
    tours = page.get('tournament_list')
    if not isinstance(tours, list):
        raise SourceError('官网缺少 tournament_list')
    lower = now.date() - timedelta(days=window_days)
    selected = []
    excluded_tournaments = []
    errors = []
    for tour in tours:
        # 真实官网归档包含 2016 CBLOL 的 0000-00-00；它不是本次近期赛程的失败。
        if tour.get('start_date') in (None, '', '0000-00-00') or tour.get('end_date') in (None, '', '0000-00-00'):
            excluded_tournaments.append({'tournament_id': tour.get('tournamentID'),
                                         'name': tour.get('name'), 'reason': '赛事起止日期未知，未进入近期发现'})
            continue
        try:
            start = datetime.fromisoformat(tour['start_date']).date()
            end = datetime.fromisoformat(tour['end_date']).date()
            tid = int(tour['tournamentID'])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({'tournament_id': tour.get('tournamentID'), 'error': f'赛事日期或 ID 无效: {exc}'})
            continue
        if tournament_ids is not None and tid not in tournament_ids:
            continue
        if start <= now.date() and end >= lower:
            selected.append((start, tid, tour))
    selected.sort(reverse=True, key=lambda item: item[0])
    schedules = {}
    schedule_sources = []
    latest = None
    latest_published = None
    unpublished_stages = []
    deferred_tournaments = [item[1] for item in selected[max_tournaments:]]
    discovery_limited = False
    for _, tid, tour in selected[:max_tournaments]:
        if discovery_requests is not None and client.budget.count - begin_count >= discovery_requests:
            discovery_limited = True
            deferred_tournaments.append(tid)
            continue
        try:
            rounds = client.get_json(f'https://img.scoregg.com/tr/{tid}.json')
            if not isinstance(rounds, list):
                raise SourceError(f'tournament {tid}: 阶段结构不是列表')
            tournament_page = page if tid == 1007 else None
            for stage in reversed(rounds):
                children = stage.get('round_son') or []
                keys = [str(child['id']) for child in reversed(children)] if children else [f"p_{stage['roundID']}"]
                for key in keys:
                    if discovery_requests is not None and client.budget.count - begin_count >= discovery_requests:
                        discovery_limited = True
                        if tid not in deferred_tournaments:
                            deferred_tournaments.append(tid)
                        break
                    try:
                        source_url = f'https://img.scoregg.com/tr_round/{key}.json'
                        rows = client.get_json(source_url)
                    except SourceHTTPError as exc:
                        # 官方父阶段占位存在但缓存尚未发布：只有官网统计阶段也未发布才可待发布。
                        if exc.status_code != 404 or children or str(stage.get('is_now_week')) == '1':
                            raise
                        if tournament_page is None:
                            tournament_page = parse_tournament_page(client.get(f'https://www.scoregg.com/match_pc?tournamentID={tid}').text)
                        published = tournament_page.get('week_player_select_list')
                        if not isinstance(published, list):
                            raise SourceError(f'tournament {tid}: 缺少已发布阶段列表，不能把 404 判为待发布') from exc
                        if str(stage['roundID']) in {str(item['id']) for item in published}:
                            raise
                        unpublished_stages.append({'tournament_id': tid, 'round_id': stage['roundID'],
                                                   'name': stage.get('name'), 'cache': key,
                                                   'reason': 'HTTP404，非当前父阶段且官网已发布统计阶段不含它；次日重新发现'})
                        continue
                    if not isinstance(rows, list):
                        raise SourceError(f'round {key}: 赛程结构不是列表')
                    source_index = len(schedule_sources)
                    source = {'tournament_id': tid, 'source_url': source_url, 'source_cache_key': key,
                              'source_parent_round_id': stage.get('roundID'),
                              'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                              'rows': rows, 'selected_series_ids': []}
                    schedule_sources.append(source)
                    for row in rows:
                        date = _schedule_date(row)
                        latest_published = date if latest_published is None or date > latest_published else latest_published
                        if lower <= date.date() <= now.date():
                            if date <= now and str(row.get('status')) == '2':
                                latest = date if latest is None or date > latest else latest
                            sid = int(row['matchID'])
                            schedule = {
                                'series_id': sid, 'tournament_id': tid,
                                'tournament_name': tour.get('name'), 'scheduled_at': date,
                                'date_source': 'schedule', 'status': str(row.get('status', '')),
                                # 官网模板以此决定展示“数据更新中”还是战报链接，与完赛 status 是两回事。
                                'is_publist': row.get('is_publist'),
                                'series_score': [row.get('team_a_win'), row.get('team_b_win')],
                                'source_row': row,
                                'source_index': source_index, 'source_url': source_url,
                                'source_cache_key': key, 'source_parent_round_id': stage.get('roundID'),
                                'retrieved_at_utc': source['retrieved_at_utc'],
                            }
                            source['selected_series_ids'].append(sid)
                            schedules[sid] = schedule
        except BudgetExceeded:
            raise
        except (SourceError, KeyError, TypeError, ValueError) as exc:
            errors.append({'tournament_id': tid, 'error': str(exc)})
    conflicted_series = _check_selected_schedule_sources(schedules, schedule_sources, errors)
    return sorted(schedules.values(), key=lambda item: item['scheduled_at'], reverse=True), {
        'selected_tournaments': len(selected[:max_tournaments]),
        'discovered_series': len(schedules),
        'latest_schedule_date': latest.isoformat() if latest else None,
        'latest_published_schedule_date': latest_published.isoformat() if latest_published else None,
        'source_stale': not schedules,
        'discovery_errors': errors,
        'excluded_tournaments': excluded_tournaments,
        'unpublished_stages': unpublished_stages,
        'discovery_limited': discovery_limited,
        'deferred_tournaments': deferred_tournaments,
        'conflicted_series_ids': conflicted_series,
        # 临时完整 parsed 来源仅供 pipeline 处理前归档，不直接写入运行报告。
        '_schedule_sources': schedule_sources,
    }


def get_match_data(result_id, client=None, schedule=None):
    """兼容旧调用名称；返回结构化数据，失败明确抛异常。"""
    from app.services.ingestion import normalize_result

    return normalize_result((client or ScoreGGClient()).get_result(result_id), result_id, schedule)
