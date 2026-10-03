"""可审核的英雄联盟分析口径；模型仅选择口径，不提供 SQL 表达式。"""

import json
import re
import unicodedata
from difflib import get_close_matches
from pathlib import Path

from sqlalchemy import select

from app import db
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team

POSITIONS = {"a": "上单", "b": "打野", "c": "中单", "d": "下路/ADC", "e": "辅助"}
POSITION_ALIASES = {
    **{code: code for code in POSITIONS}, "上单": "a", "top": "a", "打野": "b", "jungle": "b",
    "中单": "c", "mid": "c", "下路": "d", "adc": "d", "辅助": "e", "support": "e",
}
GRAINS = {"player": "选手单局出场", "team": "战队单局出场", "match": "一局比赛（非 BO 系列）"}
DIMENSIONS = {
    "player": "选手", "team": "比赛所属战队", "hero": "英雄", "position": "位置",
    "opponent": "对手战队", "tournament": "赛事", "day": "比赛日", "month": "比赛月份",
    "year": "比赛年份", "match_id": "单局编号", "series_id": "BO 系列编号",
    "winner": "获胜战队",
}
SUBJECT_DIMENSIONS = {
    "player": {"player", "team", "hero", "position", "opponent", "tournament", "day", "month", "year", "match_id", "series_id"},
    "team": {"team", "opponent", "tournament", "day", "month", "year", "match_id", "series_id"},
    "match": {"winner", "tournament", "day", "month", "year", "match_id", "series_id"},
}


def metric(label, operation, column=None, unit="", definition=""):
    return {"label": label, "operation": operation, "column": column, "unit": unit, "definition": definition}


COMMON_METRICS = {
    "games": metric("出场局数", "count", unit="局", definition="当前事实粒度的记录数；选手/战队各一次单局出场计一条。"),
    "matches": metric("不同单局数", "distinct_matches", unit="局", definition="COUNT(DISTINCT match_id)，不会将十名选手误计为十局。"),
    "series": metric("已知 BO 系列数", "distinct_series", unit="个", definition="不同非空 series_id 数；系列归属未知的比赛不计入，不代表完整 BO 胜负。"),
    "avg_duration": metric("平均局时长", "avg", "game_time", "分钟", "使用比赛记录的完整时长，秒除以60；仅统计大于1秒的已知时长，缺失、零、负值和1秒占位不算零。"),
}
RESULT_METRICS = {
    "wins": metric("胜场", "wins", unit="局", definition="result=1 的单局出场数。"),
    "losses": metric("负场", "losses", unit="局", definition="result=0 的单局出场数。"),
    "known_results": metric("胜负已知局数", "known_results", unit="局", definition="仅 result 为0或1的记录；未知胜负不计入胜率分母。"),
    "win_rate": metric("胜率", "win_rate", unit="%", definition="100×胜场/胜负已知局数，分母为0时未知；百分比以0–100表示。"),
}
METRICS = {
    "player": {
        **COMMON_METRICS, **RESULT_METRICS,
        "avg_kda": metric("平均单局 KDA", "avg", "kda", definition="AVG(来源单局kda)，仅使用已知kda；不是总击杀助攻除以总死亡。"),
        "aggregate_kda": metric("汇总 KDA", "aggregate_kda", definition="Σ(击杀+助攻)/Σ死亡；只用三项齐全的出场，死亡合计为0时未知。"),
        "total_kills": metric("总击杀", "sum", "kills", "次"),
        "avg_kills": metric("场均击杀", "avg", "kills", "次/局"),
        "max_kills": metric("单局最高击杀", "max", "kills", "次"),
        "avg_deaths": metric("场均死亡", "avg", "deaths", "次/局"),
        "avg_assists": metric("场均助攻", "avg", "assists", "次/局"),
        "avg_damage": metric("场均伤害", "avg", "atk", "点/局"),
        "damage_per_min": metric("分均伤害", "rate_per_min", "atk", "点/分钟", "逐局总伤害×60/比赛记录的完整时长秒，再取均值；仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "damage_share": metric("平均伤害占比", "avg", "atk_p", "%"),
        "damage_taken_per_min": metric("分均承伤", "rate_per_min", "def_", "点/分钟", "逐局总承伤×60/比赛记录的完整时长秒，再取均值；仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "gold_per_min": metric("分均经济", "rate_per_min", "money", "金币/分钟", "逐局总经济×60/比赛记录的完整时长秒，再取均值；包含完整分秒，仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "avg_gold": metric("场均经济", "avg", "money", "金币/局"),
        "cs_per_min": metric("分均补刀", "rate_per_min", "hits", "刀/分钟", "逐局总补刀×60/比赛记录的完整时长秒，再取均值；仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "participation": metric("平均参团率", "avg", "part", "%"),
        "wards_per_min": metric("分均插眼", "avg", "wp_m", "个/分钟", "平均来源分均插眼，来源仅有整数精度且缺少可信插眼总量，无法按完整分秒重算；0不代表整局没有插眼，缺失值不算零。"),
        "mvp_count": metric("MVP 次数", "mvp_count", "mvp", "次"),
    },
    "team": {
        **COMMON_METRICS, **RESULT_METRICS,
        "avg_kills": metric("场均击杀", "avg", "kill", "次/局"),
        "avg_deaths": metric("场均死亡", "avg", "death", "次/局"),
        "avg_assists": metric("场均助攻", "avg", "assist", "次/局"),
        "avg_damage": metric("场均伤害", "avg", "attack", "点/局"),
        "avg_gold": metric("场均经济", "avg", "money", "金币/局"),
        "gold_per_min": metric("分均经济", "rate_per_min", "money", "金币/分钟", "逐局总经济×60/比赛记录的完整时长秒，再取均值；仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "damage_per_min": metric("分均伤害", "rate_per_min", "attack", "点/分钟", "逐局总伤害×60/比赛记录的完整时长秒，再取均值；仅计非负总量且时长大于1秒的样本，缺失和1秒占位不算零。"),
        "avg_towers": metric("场均推塔", "avg", "tower", "座/局"),
        "avg_dragons": metric("场均小龙", "avg", "small_dargon", "条/局"),
        "avg_barons": metric("场均大龙", "avg", "big_dargon", "条/局"),
        "avg_heralds": metric("场均先锋", "avg", "riftHeraldKills", "个/局"),
        "avg_elders": metric("场均远古龙", "avg", "elder", "条/局"),
        "avg_grubs": metric("场均巢虫", "avg", "void_grub", "只/局"),
        "first_blood_rate": metric("一血率", "binary_rate", "firstBloodKill", "%"),
        "first_tower_rate": metric("一塔率", "binary_rate", "firstTowerKill", "%"),
        "first_dragon_rate": metric("一龙率", "binary_rate", "firstDragonKill", "%"),
    },
    "match": {
        **COMMON_METRICS,
        "games": metric("比赛单局数", "count", unit="局", definition="一行一局，matches.match_id 为单局 resultID，不是 BO matchID。"),
    },
}
FILTER_KEYS = {"player", "team", "hero", "position", "opponent", "tournament", "tournament_contains", "date_start", "date_end", "verified_only"}
PLAN_KEYS = {"type", "subject", "dimensions", "metrics", "filters", "min_games", "order_by", "direction", "limit", "per_group_top_n"}
# 别名只落到当前数据库实际存在的名称；不把 SKT/T1 等历史战队名默默合并。
ENTITY_ALIASES = {"player": {"飞科": ["Faker"], "李相赫": ["Faker"]},
                  "hero": json.loads(Path(__file__).with_name("hero_aliases.json").read_text(encoding="utf-8"))["aliases"]}
UNSUPPORTED = {
    "版本": "目前没有补丁版本字段，不能从比赛日期猜版本。",
    "补丁": "目前没有补丁版本字段，不能从比赛日期猜版本。",
    "赔率": "当前数据不含赔率，不能据此分析盘口或赔率。",
    "盘口": "当前数据不含赔率，不能据此分析盘口或赔率。",
    "ban率": "当前数据不含完整禁用记录，不能计算英雄 ban 率。",
    "禁用率": "当前数据不含完整禁用记录，不能计算英雄 ban 率。",
    "bp率": "当前数据不含完整选禁记录，不能计算完整 BP 率。",
    "15分钟经济差": "目前没有15分钟经济快照，不能由终局经济推断前期经济差。",
    "15分钟补刀差": "目前没有15分钟补刀快照，不能由终局补刀推断前期补刀差。",
    "gd@15": "目前没有15分钟经济快照，不能由终局经济推断 GD@15。",
    "csd@15": "目前没有15分钟补刀快照，不能由终局补刀推断 CSD@15。",
    "系列赛胜率": "当前数据保存逐局记录，无法确认全部 BO 已结束，因此不推断系列赛胜率。",
}


class InvalidPlan(ValueError):
    pass


class UnsafePlan(InvalidPlan):
    pass


def normalize_name(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def bounded_strings(value, label, max_items=6):
    if not isinstance(value, list) or len(value) > max_items:
        raise InvalidPlan(f"{label}必须是最多{max_items}项的列表")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 160 for item in value):
        raise InvalidPlan(f"{label}包含无效名称")
    return list(dict.fromkeys(item.strip() for item in value))


def validate_plan(value):
    if not isinstance(value, dict):
        raise InvalidPlan("分析计划必须是 JSON 对象")
    if "sql" in value or "expression" in value or "joins" in value:
        raise UnsafePlan("分析计划不允许携带 SQL、表达式或自定义关联")
    kind = value.get("type", "query")
    if kind == "unsupported":
        if set(value) - {"type", "reason"} or not isinstance(value.get("reason"), str):
            raise InvalidPlan("不支持的问题需要提供明确原因")
        return {"type": "unsupported", "reason": value["reason"][:300]}
    if kind == "clarify":
        if set(value) - {"type", "question", "choices"}:
            raise InvalidPlan("澄清计划包含未知字段")
        question, choices = value.get("question"), value.get("choices")
        if not isinstance(question, str) or not question.strip() or len(question) > 300:
            raise InvalidPlan("澄清问题无效")
        if not isinstance(choices, list) or not 1 <= len(choices) <= 5:
            raise InvalidPlan("澄清选项需要1–5项")
        for choice in choices:
            if not isinstance(choice, dict) or set(choice) != {"label", "prompt"}:
                raise InvalidPlan("澄清选项需要 label/prompt")
            if any(not isinstance(choice[key], str) or not 1 <= len(choice[key]) <= size for key, size in [("label", 80), ("prompt", 1000)]):
                raise InvalidPlan("澄清选项文字过长或为空")
        return {"type": "clarify", "question": question, "choices": choices}
    if kind != "query" or set(value) - PLAN_KEYS:
        raise InvalidPlan("分析计划包含未知字段或类型")
    subject = value.get("subject")
    if not isinstance(subject, str) or subject not in METRICS:
        raise InvalidPlan("subject只能为player/team/match")
    metrics = bounded_strings(value.get("metrics"), "指标")
    dimensions = bounded_strings(value.get("dimensions", []), "维度", 3)
    if not metrics or any(item not in METRICS[subject] for item in metrics):
        raise InvalidPlan("指标不在当前分析对象的业务目录中")
    if any(item not in SUBJECT_DIMENSIONS[subject] for item in dimensions):
        raise InvalidPlan("维度不在当前分析对象的业务目录中")
    filters = value.get("filters", {})
    if not isinstance(filters, dict) or set(filters) - FILTER_KEYS:
        raise InvalidPlan("筛选包含未知字段")
    filters = dict(filters)
    for key in FILTER_KEYS - {"date_start", "date_end", "verified_only"}:
        if key in filters:
            filters[key] = bounded_strings(filters[key], f"{key}筛选")
    if subject != "player" and any(filters.get(key) for key in ("player", "hero", "position")):
        raise InvalidPlan("选手/英雄/位置筛选只用于选手出场分析，避免关联放大")
    if subject == "match" and filters.get("opponent"):
        raise InvalidPlan("对手筛选需使用选手或战队出场分析")
    from datetime import date
    for key in ("date_start", "date_end"):
        if filters.get(key) is not None:
            try:
                if not isinstance(filters[key], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filters[key]):
                    raise ValueError("日期必须明确为年月日")
                parsed = date.fromisoformat(filters[key])
                if not 1900 <= parsed.year <= 2100:
                    raise ValueError("日期超出业务范围")
            except (ValueError, TypeError) as error:
                raise InvalidPlan("日期格式应为YYYY-MM-DD") from error
    if filters.get("date_start") and filters.get("date_end") and filters["date_start"] > filters["date_end"]:
        raise InvalidPlan("起始日期不能晚于结束日期")
    if "verified_only" in filters and not isinstance(filters["verified_only"], bool):
        raise InvalidPlan("verified_only必须为布尔值")
    if filters.get("position"):
        try:
            filters["position"] = list(dict.fromkeys(POSITION_ALIASES[normalize_name(item)] for item in filters["position"]))
        except KeyError as error:
            raise InvalidPlan("位置只能为上单/打野/中单/下路/辅助或a–e") from error
    focused = (subject == "player" and 1 <= len(filters.get("player", [])) <= 2) or (subject == "team" and 1 <= len(filters.get("team", [])) <= 2)
    temporal = bool(set(dimensions) & {"day", "month", "year"})
    default_min = 10 if dimensions and not focused and not temporal and any(METRICS[subject][item]["operation"] in {"avg", "win_rate", "aggregate_kda", "binary_rate", "rate_per_min"} for item in metrics) else 1
    numbers = {"min_games": (value.get("min_games", default_min), 1, 10000), "limit": (value.get("limit", 100), 1, 100)}
    for label, (number, lower, upper) in numbers.items():
        if type(number) is not int or not lower <= number <= upper:
            raise InvalidPlan(f"{label}必须为{lower}–{upper}之间的整数")
    order = value.get("order_by")
    if order is None:
        order = next((item for item in dimensions if item in {"day", "month", "year"}), metrics[0])
    if order not in metrics + dimensions:
        raise InvalidPlan("排序只能使用本次选取的维度或指标")
    direction = value.get("direction", "asc" if order in {"day", "month", "year"} else "desc")
    if not isinstance(direction, str) or direction not in {"asc", "desc"}:
        raise InvalidPlan("排序方向只能为asc/desc")
    per_group = value.get("per_group_top_n")
    if per_group is not None:
        if not isinstance(per_group, dict) or set(per_group) != {"partition_by", "n"}:
            raise InvalidPlan("每组TopN需要partition_by和n")
        partition = bounded_strings(per_group["partition_by"], "TopN分组", 2)
        if not partition or any(item not in dimensions for item in partition) or set(partition) == set(dimensions):
            raise InvalidPlan("TopN分组必须是维度的非空真子集")
        if type(per_group["n"]) is not int or not 1 <= per_group["n"] <= 20:
            raise InvalidPlan("每组TopN应为1–20")
        per_group = {"partition_by": partition, "n": per_group["n"]}
        if len(partition) == 1:
            groups = len(filters.get(partition[0], []))
            if partition[0] == "position" and not groups:
                groups = len(POSITIONS)
            if groups:
                numbers["limit"] = (max(numbers["limit"][0], min(groups * per_group["n"], 100)), 1, 100)
    return {
        "type": "query", "subject": subject, "dimensions": dimensions, "metrics": metrics,
        "filters": filters, "min_games": numbers["min_games"][0], "limit": numbers["limit"][0],
        "order_by": order, "direction": direction, "per_group_top_n": per_group,
    }


def parse_plan(reply):
    stripped = reply.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if re.match(r"(?is)^(delete|drop|update|insert|alter|create|pragma|attach|replace|truncate|grant|revoke)\b", stripped):
        raise UnsafePlan("只允许受控的只读数据分析")
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise InvalidPlan("需要合法JSON分析计划，不允许直接提供SQL") from error
    return validate_plan(value)


def validate_context(context):
    if context is None:
        return None
    if not isinstance(context, dict) or set(context) != {"plan"} or len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > 8192:
        raise InvalidPlan("上下文只能包含不超过8KB的上一条分析计划")
    plan = validate_plan(context["plan"])
    if plan["type"] != "query":
        raise InvalidPlan("上下文必须是已完成的查询计划")
    return {"plan": plan}


def entity_catalog():
    fields = {"player": Player.name, "team": Team.team_name, "hero": Player.hero, "tournament": Match.tournament_name}
    return {
        key: list(db.session.execute(select(column).where(column.is_not(None), column != "").distinct().order_by(column).limit(10000)).scalars())
        for key, column in fields.items()
    }


def matching_entities(term, kind, catalog):
    names = catalog[kind]
    if term in names:
        return [term]
    normalized = normalize_name(term)
    exact = [name for name in names if normalize_name(name) == normalized]
    if exact:
        return exact
    aliases = ENTITY_ALIASES.get(kind, {}).get(normalized, [])
    actual_aliases = [name for name in names if normalize_name(name) in {normalize_name(alias) for alias in aliases}]
    if actual_aliases:
        return actual_aliases
    return [name for name in names if normalized in normalize_name(name)][:6]


def resolve_entities(plan, catalog, question):
    filters = dict(plan["filters"])
    labels = {"player": "选手", "team": "战队", "hero": "英雄", "tournament": "赛事", "opponent": "对手战队"}
    for key, label in labels.items():
        resolved = []
        for term in filters.get(key, []):
            if key == "tournament" and normalize_name(term) in {"lpl", "lck", "lec", "lcs", "cblol", "lta", "lms", "pcs", "vcs", "ljl", "世界赛", "全球总决赛", "worlds"}:
                terms = ["全球总决赛", "世界总决赛", "worlds"] if normalize_name(term) in {"世界赛", "全球总决赛", "worlds"} else [term]
                filters["tournament_contains"] = list(dict.fromkeys(filters.get("tournament_contains", []) + terms))
                continue
            kind = "team" if key == "opponent" else key
            choices = matching_entities(term, kind, catalog)
            if len(choices) != 1:
                if not choices:
                    choices = get_close_matches(term, catalog[kind], n=4, cutoff=0.5)
                return plan, {
                    "question": f"当前数据中的{label}“{term}”{'有多个匹配' if choices else '没有匹配'}，请明确名称。",
                    "choices": [{"label": name, "prompt": question.replace(term, name) if term in question else f"{question}\n明确{label}为{name}"} for name in choices[:5]],
                }
            resolved.extend(choices)
        if key in filters:
            filters[key] = list(dict.fromkeys(resolved))
    return {**plan, "filters": filters}, None


def candidate_entities(question, catalog):
    normalized = normalize_name(question)
    candidates = {}
    for kind, names in catalog.items():
        found = []
        for name in names:
            token = normalize_name(name)
            if re.search(r"(?<![a-z0-9_])" + re.escape(token) + r"(?![a-z0-9_])", normalized):
                found.append(name)
        for alias in ENTITY_ALIASES.get(kind, {}):
            if re.search(r"(?<![a-z0-9_])" + re.escape(alias) + r"(?![a-z0-9_])", normalized):
                found.extend(matching_entities(alias, kind, catalog))
        candidates[kind] = list(dict.fromkeys(found))[:12]
    return candidates


def semantic_catalog():
    return {
        "subjects": {subject: {
            "grain": GRAINS[subject], "dimensions": {key: DIMENSIONS[key] for key in sorted(SUBJECT_DIMENSIONS[subject])},
            "metrics": {key: {field: value for field, value in definition.items() if field in {"label", "unit", "definition"}} for key, definition in metrics.items()},
        } for subject, metrics in METRICS.items()},
        "positions": POSITIONS,
        "rules": [
            "历史战队名不自动合并；team是比赛当局所属战队，不能当成当前所属战队。",
            "时间筛选/趋势只用真实赛程日期date_source=schedule；updated_at不能作为比赛年份、赛季或补丁。",
            "赛事只能用实际tournament_name；缺失赛事归属不能据日期推断赛季/赛区。",
            "联赛/世界赛聚合用filters.tournament_contains文字片段数组，按真实赛事名文字匹配，不推断赛区；全球总决赛可用全球总决赛/世界总决赛/Worlds。",
            "胜率按已知胜负计算；平均单局KDA与汇总KDA是两个不同指标。",
            "AVG忽略缺失值；每项指标附有效样本数；一般均值榜单默认至少10局，单人查询可min_games=1。",
            "默认查询已收录全部数据并显示未核验占比；verified_only=true只看已核验数据。",
            "无补丁版本、赔率、完整禁用记录、转会官方日期、完整BO胜负，不猜缺失字段。",
            "比较两位选手用player维度和player筛选；比较战队用team维度和team筛选；直接交手同时筛选双方team和opponent。",
        ],
    }


def unsupported_question(question):
    normalized = normalize_name(question).replace(" ", "")
    for token, reason in UNSUPPORTED.items():
        if token in normalized:
            return reason
    return None
