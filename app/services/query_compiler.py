"""将经过业务校验的分析计划编译为可信 SQLAlchemy SELECT。"""

from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services.query_semantics import DIMENSIONS, GRAINS, METRICS, POSITIONS


def count_when(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def distinct_when(condition, column):
    return func.count(func.distinct(case((condition, column))))


def query_scope(plan, apply_time=True, apply_dimension_presence=True):
    matches = Match.__table__
    fact = {"player": Player.__table__, "team": Team.__table__, "match": matches}[plan["subject"]]
    relation = fact if fact is matches else fact.join(matches, fact.c.match_id == matches.c.match_id)
    team = fact.c.team_name if fact is not matches else None
    opponent = case(
        (matches.c.red_team_name == team, matches.c.blue_team_name),
        (matches.c.blue_team_name == team, matches.c.red_team_name),
    ) if team is not None else None
    filters, conditions = plan["filters"], []
    fields = {"player": fact.c.name if plan["subject"] == "player" else None,
              "hero": fact.c.hero if plan["subject"] == "player" else None,
              "position": fact.c.position if plan["subject"] == "player" else None,
              "tournament": matches.c.tournament_name, "opponent": opponent}
    for key, column in fields.items():
        if filters.get(key):
            conditions.append(column.in_(filters[key]))
    if filters.get("tournament_contains"):
        conditions.append(or_(*[func.lower(matches.c.tournament_name).contains(term.casefold(), autoescape=True) for term in filters["tournament_contains"]]))
    if filters.get("team"):
        conditions.append(team.in_(filters["team"]) if team is not None else or_(
            matches.c.red_team_name.in_(filters["team"]), matches.c.blue_team_name.in_(filters["team"])))
    if filters.get("verified_only"):
        conditions.append(matches.c.verified.is_(True))
    if apply_dimension_presence and "hero" in plan["dimensions"]:
        conditions.extend([fact.c.hero.is_not(None), fact.c.hero != ""])
    time_query = bool(filters.get("date_start") or filters.get("date_end") or set(plan["dimensions"]) & {"day", "month", "year"})
    if apply_time and time_query:
        conditions.extend([matches.c.date_source == "schedule", matches.c.date.is_not(None)])
        if filters.get("date_start"):
            conditions.append(matches.c.date >= datetime.combine(date.fromisoformat(filters["date_start"]), datetime.min.time()))
        if filters.get("date_end"):
            end = date.fromisoformat(filters["date_end"]) + timedelta(days=1)
            conditions.append(matches.c.date < datetime.combine(end, datetime.min.time()))
    return fact, matches, relation, conditions, opponent, time_query


def dimension_expression(key, fact, matches, opponent):
    physical = {"player": "name", "team": "team_name", "hero": "hero", "position": "position"}
    if key in physical:
        expression = fact.c[physical[key]]
        if key == "position":
            return case(*[(expression == code, label) for code, label in POSITIONS.items()], else_="未知位置")
        return func.coalesce(func.nullif(expression, ""), "未知")
    if key == "opponent":
        return func.coalesce(opponent, "未知")
    if key == "tournament":
        return func.coalesce(func.nullif(matches.c.tournament_name, ""), "未知赛事")
    if key == "winner":
        return func.coalesce(func.nullif(matches.c.win_team_name, ""), "未知")
    if key in {"match_id", "series_id"}:
        return matches.c[key]
    formats = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
    return func.strftime(formats[key], matches.c.date) if db.engine.dialect.name == "sqlite" else func.date_format(matches.c.date, formats[key])


def result_expressions(fact):
    win, loss = ("1", "0") if fact.name == "players" else (1, 0)
    known = fact.c.result.in_([win, loss])
    return known, fact.c.result == win, fact.c.result == loss


def metric_expression(key, definition, fact, matches):
    operation, physical = definition["operation"], definition["column"]
    column = fact.c[physical] if physical else None
    sample = func.count(column) if physical else func.count()
    if operation == "count":
        expression = func.count()
    elif operation == "distinct_matches":
        expression = func.count(func.distinct(matches.c.match_id))
    elif operation == "distinct_series":
        expression = func.count(func.distinct(matches.c.series_id))
        sample = count_when(matches.c.series_id.is_not(None))
    elif operation in {"avg", "sum", "max"}:
        expression = {"avg": func.avg, "sum": func.sum, "max": func.max}[operation](column)
        if key == "avg_duration":
            expression = expression / 60.0
    elif operation == "aggregate_kda":
        complete = and_(fact.c.kills.is_not(None), fact.c.deaths.is_not(None), fact.c.assists.is_not(None))
        numerator = func.sum(case((complete, fact.c.kills + fact.c.assists)))
        denominator = func.sum(case((complete, fact.c.deaths)))
        expression = numerator * 1.0 / func.nullif(denominator, 0)
        sample = count_when(complete)
    elif operation == "rate_per_min":
        valid = and_(column.is_not(None), fact.c.game_time.is_not(None), fact.c.game_time > 0)
        expression = func.avg(case((valid, column * 60.0 / fact.c.game_time)))
        sample = count_when(valid)
    elif operation in {"wins", "losses", "known_results", "win_rate"}:
        known, win, loss = result_expressions(fact)
        sample = count_when(known)
        expression = {"wins": count_when(win), "losses": count_when(loss), "known_results": sample,
                      "win_rate": count_when(win) * 100.0 / func.nullif(sample, 0)}[operation]
    elif operation == "binary_rate":
        sample = count_when(column.in_([0, 1]))
        expression = count_when(column == 1) * 100.0 / func.nullif(sample, 0)
    else:  # 已校验目录中的 MVP 计数。
        expression = count_when(column == 1)
    return expression.label(key), sample.label(f"{key}_samples")


def quality_expressions(fact, matches):
    quality = [
        func.count().label("sample_size"), func.count(func.distinct(matches.c.match_id)).label("matches"),
        distinct_when(matches.c.verified.is_(True), matches.c.match_id).label("verified_matches"),
        distinct_when(matches.c.verified.is_not(True), matches.c.match_id).label("unverified_matches"),
        distinct_when(matches.c.date_source == "schedule", matches.c.match_id).label("scheduled_matches"),
        distinct_when(matches.c.date_source == "updated_at", matches.c.match_id).label("updated_date_matches"),
        distinct_when(or_(matches.c.date.is_(None), matches.c.date_source.is_(None), matches.c.date_source == "unknown"), matches.c.match_id).label("unknown_date_matches"),
    ]
    if fact.name != "matches":
        known, _, _ = result_expressions(fact)
        quality.extend([count_when(known).label("known_results"), count_when(or_(fact.c.result.is_(None), ~known)).label("unknown_results")])
    if fact.name == "players":
        quality.append(count_when(or_(fact.c.hero.is_(None), fact.c.hero == "")).label("missing_hero_rows"))
    return quality


def compile_plan(plan):
    fact, matches, relation, conditions, opponent, time_query = query_scope(plan)
    dimensions = [dimension_expression(key, fact, matches, opponent).label(key) for key in plan["dimensions"]]
    metrics, samples, sample_expressions = [], [], {}
    for key in plan["metrics"]:
        expression, sample = metric_expression(key, METRICS[plan["subject"]][key], fact, matches)
        sample_expressions[key] = sample
        metrics.append(expression)
        if key not in {"games", "matches", "known_results", "wins", "losses"}:
            samples.append(sample)
    # 指标可能本身叫matches；不重复输出同名证据列。
    quality = [column for column in quality_expressions(fact, matches) if column.name not in plan["metrics"]]
    aggregate = select(*dimensions, *metrics, *samples, *quality).select_from(relation).where(*conditions)
    if dimensions:
        aggregate = aggregate.group_by(*dimensions).having(func.count() >= plan["min_games"])
    elif plan["min_games"] > 1:
        aggregate = aggregate.having(func.count() >= plan["min_games"])
    ordered_metric = METRICS[plan["subject"]].get(plan["order_by"])
    if dimensions and plan["min_games"] >= 10 and ordered_metric and ordered_metric["operation"] in {"avg", "win_rate", "aggregate_kda", "binary_rate", "rate_per_min"}:
        aggregate = aggregate.having(sample_expressions[plan["order_by"]] >= plan["min_games"])
    grouped = aggregate.subquery("analysis_groups")
    direction = plan["direction"]
    primary = grouped.c[plan["order_by"]]
    order = [primary.is_(None).asc(), primary.desc() if direction == "desc" else primary.asc()]
    order.extend(grouped.c[key].asc() for key in plan["dimensions"] if key != plan["order_by"])
    if plan["per_group_top_n"]:
        top = plan["per_group_top_n"]
        ranked = select(*grouped.c, func.row_number().over(
            partition_by=[grouped.c[key] for key in top["partition_by"]], order_by=order,
        ).label("group_rank")).subquery("ranked_groups")
        statement = select(*ranked.c).where(ranked.c.group_rank <= top["n"])
        statement = statement.order_by(*[ranked.c[key].asc() for key in top["partition_by"]], ranked.c.group_rank)
    else:
        statement = select(*grouped.c).order_by(*order)
    statement = statement.limit(plan["limit"])
    evidence = select(*quality_expressions(fact, matches),
                      func.min(case((matches.c.date_source == "schedule", matches.c.date))).label("date_start"),
                      func.max(case((matches.c.date_source == "schedule", matches.c.date))).label("date_end"),
                      distinct_when(matches.c.series_id.is_(None), matches.c.match_id).label("unknown_series_matches"),
                      distinct_when(or_(matches.c.tournament_name.is_(None), matches.c.tournament_name == ""), matches.c.match_id).label("unknown_tournament_matches"),
                      ).select_from(relation).where(*conditions)
    coverage = None
    if time_query or "hero" in plan["dimensions"]:
        _, _, _, broad_conditions, _, _ = query_scope(plan, apply_time=False, apply_dimension_presence=False)
        coverage = select(*quality_expressions(fact, matches)).select_from(relation).where(*broad_conditions)
    return {"statement": statement, "evidence": evidence, "coverage": coverage, "time_query": time_query}


def result_columns(plan):
    columns = [{"key": key, "label": DIMENSIONS[key], "type": "date" if key in {"day", "month", "year"} else "string", "unit": "", "definition": ""} for key in plan["dimensions"]]
    for key in plan["metrics"]:
        definition = METRICS[plan["subject"]][key]
        columns.append({"key": key, "label": definition["label"], "type": "number", "unit": definition["unit"], "definition": definition["definition"] or "仅对已知值计算，缺失值不算零。"})
    columns.append({"key": "sample_size", "label": "样本出场数" if plan["subject"] != "match" else "样本局数", "type": "number", "unit": "次" if plan["subject"] != "match" else "局", "definition": GRAINS[plan["subject"]]})
    for key in plan["metrics"]:
        if METRICS[plan["subject"]][key]["operation"] in {"avg", "aggregate_kda", "binary_rate", "rate_per_min", "win_rate"}:
            definition = "胜负已知出场数，胜率分母；未知胜负不计入。" if key == "win_rate" else "实际参与该指标计算的非空样本数。"
            columns.append({"key": f"{key}_samples", "label": f"{METRICS[plan['subject']][key]['label']}有效样本", "type": "number", "unit": "次", "definition": definition})
    if plan["per_group_top_n"]:
        columns.append({"key": "group_rank", "label": "组内排名", "type": "number", "unit": "", "definition": "按已选指标在当前分组内排序，同值按实体名称稳定排列。"})
    return columns


def chart_metadata(plan, rows):
    if not rows or not plan["dimensions"]:
        return None
    x = next((key for key in plan["dimensions"] if key in {"day", "month", "year"}), plan["dimensions"][0])
    if len(plan["dimensions"]) != 1:
        return {"type": "table", "x": x, "series": []}
    first_unit = METRICS[plan["subject"]][plan["metrics"][0]]["unit"]
    series = [{"key": key, "label": METRICS[plan["subject"]][key]["label"], "unit": first_unit}
              for key in plan["metrics"] if METRICS[plan["subject"]][key]["unit"] == first_unit]
    return {"type": "line" if x in {"day", "month", "year"} else "bar", "x": x, "series": series[:3]}
