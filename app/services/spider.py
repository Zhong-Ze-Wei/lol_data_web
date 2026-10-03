"""ScoreGG 的有限预算 HTTP 客户端与 LOL 赛程发现。"""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests


class SourceError(Exception):
    """上游请求或结构失败；调用方持久记录，而不是把它当成零值。"""


class BudgetExceeded(SourceError):
    pass


class SourceHTTPError(SourceError):
    def __init__(self, url, status_code):
        self.url = url
        self.status_code = status_code
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
                 backoff=1, sleep=time.sleep):
        self.budget = budget or RequestBudget()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
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
        for attempt in range(self.retries + 1):
            self.budget.reserve()
            response = None
            try:
                remaining = self.budget.remaining_seconds()
                response = self.session.get(
                    url, timeout=(min(self.timeout[0], remaining), min(self.timeout[1], remaining)),
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f'HTTP {response.status_code}', response=response)
                response.raise_for_status()
                return response
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                retryable = response is None or response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == self.retries:
                    if response is not None:
                        raise SourceHTTPError(url, response.status_code) from exc
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
        payload = self.get_json(f'https://img.scoregg.com/match/resultlist/{int(series_id)}.json')
        if not isinstance(payload, dict) or payload.get('code') not in (200, '200'):
            raise SourceError(f'series {series_id}: resultlist 返回失败状态')
        rows = payload.get('data')
        if not isinstance(rows, list):
            raise SourceError(f'series {series_id}: resultlist.data 必须为列表')
        try:
            return sorted({int(row['resultID']) for row in rows})
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f'series {series_id}: 缺少合法 resultID') from exc


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
                        rows = client.get_json(f'https://img.scoregg.com/tr_round/{key}.json')
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
                            }
                            if sid in schedules and schedules[sid]['tournament_id'] != tid:
                                raise SourceError(f'series {sid} 被不同赛事引用，停止错误关联')
                            schedules[sid] = schedule
        except BudgetExceeded:
            raise
        except (SourceError, KeyError, TypeError, ValueError) as exc:
            errors.append({'tournament_id': tid, 'error': str(exc)})
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
    }


def get_match_data(result_id, client=None, schedule=None):
    """兼容旧调用名称；返回结构化数据，失败明确抛异常。"""
    from app.services.ingestion import normalize_result

    return normalize_result((client or ScoreGGClient()).get_result(result_id), result_id, schedule)
