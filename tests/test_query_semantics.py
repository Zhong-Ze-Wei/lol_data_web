import json
from datetime import datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.services import ai_assistant
from app.services.ai_assistant import AIUnavailable, execute_readonly_batch, validate_sql
from app.services.query_compiler import compile_plan
from app.services.query_semantics import METRICS, InvalidPlan, UnsafePlan, entity_catalog, parse_plan, resolve_entities, validate_plan
from app.services.stat_metrics import per_minute_number


def plan(**overrides):
    value = {"type": "query", "subject": "player", "dimensions": ["player"],
             "metrics": ["games"], "filters": {}, "min_games": 1,
             "order_by": "games", "direction": "desc", "limit": 100, "per_group_top_n": None}
    value.update(overrides)
    return validate_plan(value)


def rows(value):
    compiled = compile_plan(value)
    return execute_readonly_batch([compiled["statement"], compiled["evidence"]])


@pytest.fixture
def sample_data(db):
    definitions = [
        (1, "T1", "GEN", "2024-01-10", "schedule", True, "2024 LCK Spring", 1800),
        (2, "T1", "GEN", "2024-02-10", "schedule", False, "2024 LCK Spring", 2400),
        (3, "T1", "HLE", "2024-02-15", "updated_at", True, "2024 LCK Spring", None),
        (4, "SKT", "HLE", None, "unknown", False, None, 1900),
        (5, "BLG", "GEN", "2026-05-01", "schedule", True, "2026 LPL Summer", 2000),
    ]
    for match_id, red, blue, day, date_source, verified, tournament, duration in definitions:
        db.session.add(Match(match_id=match_id, series_id=100 if match_id < 3 else None,
                             red_team_name=red, blue_team_name=blue,
                             win_team_name=red if match_id in {1, 5} else blue if match_id == 2 else None,
                             date=datetime.fromisoformat(day) if day else None,
                             date_source=date_source, verified=verified, tournament_name=tournament,
                             game_time=duration))
        for team_name in (red, blue):
            known_result = match_id in {1, 2, 5}
            result = int(team_name == (red if match_id in {1, 5} else blue)) if known_result else None
            db.session.add(Team(match_id=match_id, team_name=team_name, result=result,
                                game_time=duration, kill=15, death=10, attack=60000, money=55000,
                                tower=6, small_dargon=3, firstBloodKill=result))
            for position in "abcde":
                name = "Faker" if team_name in {"T1", "SKT"} and position == "c" else "Chovy" if team_name == "GEN" and position == "c" else f"{team_name}-{position}"
                kills, deaths, assists, kda = (10, 1, 0, 10.0) if match_id == 1 else (2, 2, 2, 2.0) if match_id == 2 else (None, None, None, None)
                db.session.add(Player(match_id=match_id, team_name=team_name, position=position,
                                      name=name, date=datetime(1999, 1, 1),
                                      hero="阿狸" if position == "c" else "艾希" if position == "a" else "艾克",
                                      result=str(result) if result is not None else None,
                                      kills=kills, deaths=deaths, assists=assists, kda=kda,
                                      atk_m=400.5 if match_id in {1, 2} else None,
                                      money_M=380.1, adc_m=8.2, part=70.5, game_time=duration))
    db.session.commit()
    return definitions


@pytest.fixture
def ai(app, monkeypatch):
    app.config["AI_API_KEY"] = "not-a-real-key"
    reply = Mock()
    monkeypatch.setattr(ai_assistant, "model_reply", reply)
    return reply


def test_fact_grain_does_not_multiply_player_rows_by_team_rows(sample_data):
    result, evidence = rows(plan(dimensions=[], metrics=["games", "matches", "series"]))
    assert result[0]["games"] == 50
    assert result[0]["matches"] == 5
    assert result[0]["series"] == 1
    assert evidence[0]["sample_size"] == 50
    assert evidence[0]["matches"] == 5


def test_win_rate_excludes_unknown_results_and_kda_definitions_are_distinct(sample_data):
    result, evidence = rows(plan(metrics=["games", "win_rate", "avg_kda", "aggregate_kda"], filters={"player": ["Faker"]}))
    row = result[0]
    assert row["games"] == 4
    assert row["known_results"] == 2
    assert row["unknown_results"] == 2
    assert row["win_rate"] == 50
    assert row["avg_kda"] == 6
    assert row["aggregate_kda"] == pytest.approx(14 / 3)
    assert row["avg_kda_samples"] == 2
    assert row["aggregate_kda_samples"] == 2
    assert evidence[0]["unknown_results"] == 2


def test_win_rate_sample_column_exposes_the_actual_denominator_to_the_ui(client, ai, sample_data):
    ai.side_effect = [json.dumps(plan(metrics=["win_rate"], filters={"player": ["Faker"]}, order_by="win_rate")), "胜率为50%，分母为2次已知胜负出场。"]
    response = client.post("/api/ai/query", json={"prompt": "Faker胜率及分母"})
    assert response.status_code == 200
    result = response.json["result"]
    denominator = next(column for column in result["columns"] if column["key"] == "win_rate_samples")
    assert denominator["label"] == "胜率有效样本"
    assert denominator["unit"] == "次"
    assert "胜负已知出场数" in denominator["definition"]
    assert "胜率分母" in denominator["definition"]
    assert result["data"][0]["win_rate_samples"] == 2
    assert result["data"][0]["sample_size"] == 4


def test_zero_deaths_and_missing_metrics_remain_unknown(db, sample_data):
    db.session.execute(text("UPDATE players SET deaths=0, kills=2, assists=3 WHERE name='Faker'"))
    db.session.commit()
    result, _ = rows(plan(metrics=["aggregate_kda", "damage_per_min"], filters={"player": ["Faker"], "team": ["SKT"]}, order_by="aggregate_kda"))
    assert result[0]["aggregate_kda"] is None
    assert result[0]["damage_per_min"] is None
    assert result[0]["damage_per_min_samples"] == 0


def test_direct_head_to_head_uses_two_team_appearances_per_game(sample_data):
    result, evidence = rows(plan(subject="team", dimensions=["team"], metrics=["games", "wins", "win_rate"],
                                 filters={"team": ["T1", "GEN"], "opponent": ["T1", "GEN"]}))
    assert {row["team"]: row["games"] for row in result} == {"T1": 2, "GEN": 2}
    assert all(row["win_rate"] == 50 for row in result)
    assert evidence[0]["matches"] == 2
    assert evidence[0]["sample_size"] == 4


def test_dates_use_match_schedule_and_exclude_updated_at_even_when_verified(sample_data):
    value = plan(dimensions=["month"], metrics=["games"], filters={"player": ["Faker"], "date_start": "2024-01-01", "date_end": "2024-12-31"}, order_by="month", direction="asc")
    result, evidence = rows(value)
    assert [(row["month"], row["games"]) for row in result] == [("2024-01", 1), ("2024-02", 1)]
    assert evidence[0]["scheduled_matches"] == 2
    assert evidence[0]["updated_date_matches"] == 0
    assert evidence[0]["unverified_matches"] == 1
    assert str(evidence[0]["date_start"]).startswith("2024-01")


def test_hero_pool_and_historical_team_name_split(sample_data):
    result, _ = rows(plan(dimensions=["player", "team", "hero"], metrics=["games"], filters={"player": ["Faker"]}))
    assert {(row["team"], row["hero"]): row["games"] for row in result} == {("T1", "阿狸"): 3, ("SKT", "阿狸"): 1}


def test_unknown_hero_rows_are_reported_separately_not_ranked_as_a_champion(client, ai, db, sample_data):
    db.session.execute(text("UPDATE players SET hero=NULL WHERE name='Faker' AND match_id IN (3,4)"))
    db.session.commit()
    ai.side_effect = [json.dumps(plan(dimensions=["hero"], filters={"player": ["Faker"]})), "阿狸有2局已知英雄的出场。"]
    result = client.post("/api/ai/query", json={"prompt": "Faker英雄池"}).json["result"]
    assert result["data"][0]["hero"] == "阿狸"
    assert result["data"][0]["games"] == 2
    assert len(result["data"]) == 1
    assert result["evidence"]["excluded_missing_hero_rows"] == 2


def test_each_position_top_n_keeps_minimum_sample_threshold(db):
    names = [("top_best", "a", 10, 8), ("top_second", "a", 10, 4), ("mid_best", "c", 10, 7), ("mid_second", "c", 10, 3), ("tiny_mid", "c", 2, 99)]
    next_id = 1000
    for name, position, games, kda in names:
        for _ in range(games):
            next_id += 1
            db.session.add(Match(match_id=next_id, red_team_name="A", blue_team_name="B"))
            db.session.add(Player(match_id=next_id, name=name, team_name="A", position=position, kda=kda))
    db.session.commit()
    result, _ = rows(plan(dimensions=["position", "player"], metrics=["avg_kda"], min_games=10,
                          order_by="avg_kda", per_group_top_n={"partition_by": ["position"], "n": 1}))
    assert {row["player"] for row in result} == {"top_best", "mid_best"}
    assert all(row["sample_size"] == 10 and row["group_rank"] == 1 for row in result)


def test_five_position_top_three_is_not_cut_off_by_default_ten_rows(db):
    next_id = 2000
    for position in "abcde":
        for rank in range(3):
            next_id += 1
            db.session.add(Match(match_id=next_id))
            db.session.add(Player(match_id=next_id, name=f"{position}_{rank}", team_name="A", position=position, kda=rank + 1))
    db.session.commit()
    value = plan(dimensions=["position", "player"], metrics=["avg_kda"], order_by="avg_kda", limit=10,
                 per_group_top_n={"partition_by": ["position"], "n": 3})
    result, _ = rows(value)
    assert value["limit"] == 15
    assert len(result) == 15
    assert {row["position"] for row in result} == {"上单", "打野", "中单", "下路/ADC", "辅助"}


def test_average_ranking_requires_ten_known_metric_samples_not_just_ten_rows(db):
    next_id = 3000
    for name, known in [("complete", True), ("mostly_missing", False)]:
        for index in range(10):
            next_id += 1
            db.session.add(Match(match_id=next_id))
            db.session.add(Player(match_id=next_id, name=name, team_name="A", position="c",
                                  kda=2 if known else 99 if index == 0 else None))
    db.session.commit()
    result, _ = rows(plan(dimensions=["player"], metrics=["avg_kda"], order_by="avg_kda", min_games=10))
    assert [row["player"] for row in result] == ["complete"]
    assert result[0]["avg_kda_samples"] == 10


def test_ascending_average_rank_places_null_last(db, sample_data):
    db.session.add(Match(match_id=99))
    db.session.add(Team(match_id=99, team_name="NULL_ONLY", game_time=None))
    db.session.commit()
    result, _ = rows(plan(subject="team", dimensions=["team"], metrics=["avg_duration"], order_by="avg_duration", direction="asc"))
    assert result[-1]["team"] == "NULL_ONLY"
    assert result[-1]["avg_duration"] is None
    assert result[0]["avg_duration"] is not None


def test_lpl_name_fragment_filters_only_actual_tournament_names(sample_data):
    result, _ = rows(plan(dimensions=["tournament"], metrics=["games"], filters={"tournament_contains": ["LPL"]}))
    assert result[0]["tournament"] == "2026 LPL Summer"
    assert result[0]["games"] == 10
    assert len(result) == 1


def test_team_per_minute_metrics_exclude_missing_duration(sample_data):
    result, _ = rows(plan(subject="team", dimensions=["team"], metrics=["gold_per_min", "damage_per_min"], filters={"team": ["T1"]}, order_by="gold_per_min"))
    assert result[0]["gold_per_min"] == pytest.approx((55000 * 60 / 1800 + 55000 * 60 / 2400) / 2)
    assert result[0]["gold_per_min_samples"] == 2
    assert result[0]["damage_per_min_samples"] == 2


def test_player_rates_recalculate_real_source_outliers_without_changing_raw_values(db):
    # 历史来源的两条已确认异常：分均值比可核对总量高几个数量级。
    db.session.add_all([
        Match(match_id=3260, game_time=2682),
        Match(match_id=4325, game_time=3033),
        Player(match_id=3260, name="Cola", team_name="A", position="a",
               hits=269, adc_m=16140, game_time=1),
        Player(match_id=4325, name="TrAce", team_name="B", position="a",
               atk=16940, atk_m=1016400, game_time=3600),
    ])
    db.session.commit()
    result, _ = rows(plan(metrics=["damage_per_min", "cs_per_min"], order_by="damage_per_min"))
    by_name = {row["player"]: row for row in result}
    assert by_name["Cola"]["cs_per_min"] == pytest.approx(269 * 60 / 2682)
    assert by_name["Cola"]["cs_per_min_samples"] == 1
    assert by_name["TrAce"]["damage_per_min"] == pytest.approx(16940 * 60 / 3033)
    assert by_name["TrAce"]["damage_per_min_samples"] == 1
    assert Player.query.filter_by(name="Cola").one().adc_m == 16140
    assert Player.query.filter_by(name="TrAce").one().atk_m == 1016400


@pytest.mark.parametrize("total, duration, expected", [
    (269, 2682, 269 * 60 / 2682), (16940, 3033, 16940 * 60 / 3033),
    (0, 1801, 0), (None, 1801, None), (-1, 1801, None),
    (100, None, None), (100, -1, None), (100, 0, None), (100, 1, None),
])
def test_single_row_dto_rate_uses_the_same_business_values(total, duration, expected):
    actual = per_minute_number(total, duration)
    assert actual is None if expected is None else actual == pytest.approx(expected)


def test_player_rate_metrics_use_full_seconds_and_independent_valid_samples(db):
    for match_id, duration, values in [
        (10, 1801, {"atk": 18010, "def_": None, "money": 0, "hits": 180}),
        (11, 3601, {"atk": None, "def_": 7202, "money": 36010, "hits": None}),
        (12, 1801, {"atk": -1, "def_": -1, "money": -1, "hits": -1}),
    ]:
        db.session.add(Match(match_id=match_id, game_time=duration))
        db.session.add(Player(match_id=match_id, name="rate_check", team_name="A", position="c",
                              game_time=1, atk_m=999999, def_m=999999,
                              money_M=999999, adc_m=999999, **values))
    db.session.commit()
    result, _ = rows(plan(metrics=["games", "damage_per_min", "damage_taken_per_min", "gold_per_min", "cs_per_min"]))
    row = result[0]
    assert row["games"] == 3
    assert row["damage_per_min"] == pytest.approx(18010 * 60 / 1801)
    assert row["damage_taken_per_min"] == pytest.approx(7202 * 60 / 3601)
    assert row["gold_per_min"] == pytest.approx((0 + 36010 * 60 / 3601) / 2)
    assert row["cs_per_min"] == pytest.approx(180 * 60 / 1801)
    assert {key: row[f"{key}_samples"] for key in ["damage_per_min", "damage_taken_per_min", "gold_per_min", "cs_per_min"]} == {
        "damage_per_min": 1, "damage_taken_per_min": 1, "gold_per_min": 2, "cs_per_min": 1,
    }


@pytest.mark.parametrize("duration", [None, -10, 0, 1])
@pytest.mark.parametrize("subject", ["player", "team"])
def test_unknown_or_placeholder_match_duration_is_not_a_zero_rate(db, duration, subject):
    db.session.add(Match(match_id=20, game_time=duration))
    if subject == "player":
        db.session.add(Player(match_id=20, name="check", team_name="A", position="c",
                              game_time=1800, atk=60000, def_=50000, money=12000, hits=300,
                              atk_m=999, def_m=999, money_M=999, adc_m=999))
        metrics = ["damage_per_min", "damage_taken_per_min", "gold_per_min", "cs_per_min", "avg_duration"]
    else:
        db.session.add(Team(match_id=20, team_name="A", game_time=1800, attack=60000, money=55000))
        metrics = ["damage_per_min", "gold_per_min", "avg_duration"]
    db.session.commit()
    result, _ = rows(plan(subject=subject, dimensions=[], metrics=metrics, order_by="damage_per_min"))
    assert result[0]["sample_size"] == 1
    for key in metrics:
        assert result[0][key] is None
        assert result[0][f"{key}_samples"] == 0


def test_team_rates_use_match_duration_and_exclude_negative_total(db):
    db.session.add_all([
        Match(match_id=30, game_time=1801),
        Match(match_id=31, game_time=3601),
        Team(match_id=30, team_name="A", game_time=60, attack=36020, money=0),
        Team(match_id=31, team_name="A", game_time=1, attack=-1, money=72020),
    ])
    db.session.commit()
    result, _ = rows(plan(subject="team", dimensions=["team"], metrics=["damage_per_min", "gold_per_min"], order_by="gold_per_min"))
    assert result[0]["damage_per_min"] == pytest.approx(36020 * 60 / 1801)
    assert result[0]["damage_per_min_samples"] == 1
    assert result[0]["gold_per_min"] == pytest.approx((0 + 72020 * 60 / 3601) / 2)
    assert result[0]["gold_per_min_samples"] == 2


@pytest.mark.parametrize("subject", ["player", "team", "match"])
def test_average_duration_uses_authoritative_match_and_excludes_one_second(db, subject):
    for match_id, duration in [(40, 1801), (41, 3601), (42, 1), (43, None)]:
        db.session.add(Match(match_id=match_id, game_time=duration))
        db.session.add(Player(match_id=match_id, name="check", team_name="A", position="c", game_time=60))
        db.session.add(Team(match_id=match_id, team_name="A", game_time=120))
    db.session.commit()
    result, _ = rows(plan(subject=subject, dimensions=[], metrics=["avg_duration"], order_by="avg_duration"))
    assert result[0]["sample_size"] == 4
    assert result[0]["avg_duration"] == pytest.approx((1801 + 3601) / 2 / 60)
    assert result[0]["avg_duration_samples"] == 2


def test_rate_ranking_minimum_samples_excludes_placeholder_duration_games(db):
    match_id = 100
    for name, duration in [("complete", 1801), ("placeholder", 1)]:
        for index in range(10):
            match_id += 1
            db.session.add(Match(match_id=match_id, game_time=duration if index else 1801))
            db.session.add(Player(match_id=match_id, name=name, team_name="A", position="c",
                                  game_time=1801, atk=18010, atk_m=999999))
    db.session.commit()
    result, _ = rows(plan(metrics=["damage_per_min"], order_by="damage_per_min", min_games=10))
    assert [row["player"] for row in result] == ["complete"]
    assert result[0]["damage_per_min_samples"] == 10


def test_rate_endpoint_exposes_corrected_formula_and_valid_sample_denominator(client, ai, db):
    db.session.add_all([
        Match(match_id=50, game_time=1801),
        Match(match_id=51, game_time=1),
        Player(match_id=50, name="check", team_name="A", position="c", atk=18010, atk_m=999999),
        Player(match_id=51, name="check", team_name="A", position="c", atk=18010, atk_m=999999),
    ])
    db.session.commit()
    ai.side_effect = [json.dumps(plan(metrics=["damage_per_min"], order_by="damage_per_min")), "有效样本1次，分均伤害600。"]
    response = client.post("/api/ai/query", json={"prompt": "比较分均伤害并说明有效样本"})
    assert response.status_code == 200
    result = response.json["result"]
    assert result["data"][0]["damage_per_min"] == pytest.approx(600)
    assert result["data"][0]["damage_per_min_samples"] == 1
    assert result["data"][0]["sample_size"] == 2
    column = next(item for item in result["columns"] if item["key"] == "damage_per_min")
    denominator = next(item for item in result["columns"] if item["key"] == "damage_per_min_samples")
    assert "完整时长秒" in column["definition"]
    assert "1秒占位" in column["definition"]
    assert "总量已知且非负" in denominator["definition"]
    assert "每项指标独立计数" in denominator["definition"]


def test_wards_keep_source_precision_and_do_not_infer_zero_total_wards(client, ai, db):
    db.session.add(Match(match_id=60, game_time=1801))
    db.session.add(Player(match_id=60, name="check", team_name="A", position="e", wp_m=0))
    db.session.commit()
    ai.side_effect = [json.dumps(plan(metrics=["wards_per_min"], order_by="wards_per_min")), "来源分均插眼为0，不能判断整局没有插眼。"]
    response = client.post("/api/ai/query", json={"prompt": "分均插眼"})
    assert response.status_code == 200
    result = response.json["result"]
    assert result["data"][0]["wards_per_min"] == 0
    assert result["data"][0]["wards_per_min_samples"] == 1
    definition = next(item for item in result["columns"] if item["key"] == "wards_per_min")["definition"]
    assert "整数精度" in definition
    assert "0不代表整局没有插眼" in definition


def test_tournament_fragment_wildcards_are_literal_not_a_wide_query(sample_data):
    result, _ = rows(plan(dimensions=["tournament"], filters={"tournament_contains": ["%"]}))
    assert result == []


def test_name_alias_must_resolve_to_an_actual_entity(sample_data):
    value, clarification = resolve_entities(plan(filters={"player": ["李相赫"]}), entity_catalog(), "李相赫平均KDA")
    assert clarification is None
    assert value["filters"]["player"] == ["Faker"]


@pytest.mark.parametrize("term", ["阿狸", "狐狸", "Ahri"])
def test_official_hero_aliases_resolve_only_to_current_database_names(term):
    catalog = {"hero": ["九尾妖狐", "发条魔灵"], "player": [], "team": [], "tournament": []}
    value, clarification = resolve_entities(plan(filters={"hero": [term]}), catalog, f"{term}出场数")
    assert clarification is None
    assert value["filters"]["hero"] == ["九尾妖狐"]


def test_ambiguous_entity_is_not_silently_selected():
    value = plan(filters={"team": ["T1"]})
    _, clarification = resolve_entities(value, {"team": ["T1 Main", "T1 Academy"], "player": [], "hero": [], "tournament": []}, "T1胜率")
    assert len(clarification["choices"]) == 2
    assert clarification["choices"][0]["prompt"] in {"T1 Main胜率", "T1 Academy胜率"}


@pytest.mark.parametrize("name", ["Cola", "COLA"])
def test_exact_player_name_resolves_case_variants_without_merging(name):
    catalog = {"player": ["COLA", "Cola", "TrAce"], "team": [], "hero": [], "tournament": []}
    value, clarification = resolve_entities(plan(filters={"player": [name]}), catalog, f"{name}出场数")
    assert clarification is None
    assert value["filters"]["player"] == [name]


def test_normalized_case_variant_remains_ambiguous_until_exact_name_is_chosen():
    catalog = {"player": ["COLA", "Cola", "TrAce"], "team": [], "hero": [], "tournament": []}
    _, clarification = resolve_entities(plan(filters={"player": ["cola"]}), catalog, "cola出场数")
    assert {choice["label"] for choice in clarification["choices"]} == {"COLA", "Cola"}
    for choice in clarification["choices"]:
        value, repeated = resolve_entities(plan(filters={"player": [choice["label"]]}), catalog, choice["prompt"])
        assert repeated is None
        assert value["filters"]["player"] == [choice["label"]]


def test_selecting_exact_clarification_choice_ends_the_case_variant_loop(client, ai, db):
    for match_id, name, attack in [(70, "COLA", 99999), (71, "Cola", 18010)]:
        db.session.add(Match(match_id=match_id, game_time=1801, verified=True))
        db.session.add(Player(match_id=match_id, name=name, team_name="A", position="c", atk=attack))
    db.session.commit()
    ai.side_effect = [
        json.dumps(plan(filters={"player": ["cola"]}, metrics=["damage_per_min"], order_by="damage_per_min")),
        json.dumps(plan(filters={"player": ["Cola"]}, metrics=["damage_per_min"], order_by="damage_per_min")),
        "Cola 的分均伤害为600，未合并COLA。",
    ]
    first = client.post("/api/ai/query", json={"prompt": "cola分均伤害"})
    assert first.json["result"]["status"] == "needs_clarification"
    choice = next(item for item in first.json["result"]["clarification"]["choices"] if item["label"] == "Cola")
    second = client.post("/api/ai/query", json={"prompt": choice["prompt"]})
    assert second.status_code == 200
    assert second.json["result"]["status"] == "ok"
    assert second.json["result"]["data"][0]["player"] == "Cola"
    assert second.json["result"]["data"][0]["damage_per_min"] == pytest.approx(600)
    assert second.json["result"]["data"][0]["sample_size"] == 1
    assert second.json["result"]["context"]["plan"]["filters"]["player"] == ["Cola"]
    assert ai.call_count == 3


def test_nonexistent_entity_requires_clarification(sample_data):
    _, clarification = resolve_entities(plan(filters={"player": ["NoSuchPerson"]}), entity_catalog(), "NoSuchPerson胜率")
    assert clarification is not None
    assert "没有匹配" in clarification["question"]


@pytest.mark.parametrize("overrides", [
    {"metrics": ["patch"]}, {"dimensions": ["league"]}, {"limit": 1001},
    {"limit": True}, {"filters": {"position": ["f"]}}, {"filters": {"date_start": "9999-01-01"}},
    {"filters": {"date_start": "20260101"}}, {"filters": {"date_start": "2026-W01-1"}},
    {"filters": {"date_start": "2025-01-01", "date_end": "2024-01-01"}},
    {"subject": "team", "filters": {"player": ["Faker"]}},
    {"per_group_top_n": {"partition_by": ["player"], "n": 3}},
])
def test_catalog_and_plan_guards(overrides):
    with pytest.raises(InvalidPlan):
        plan(**overrides)


@pytest.mark.parametrize("reply", ["DROP TABLE matches", "DELETE FROM players", '{"sql":"SELECT * FROM players"}'])
def test_dangerous_plans_are_directly_rejected(reply):
    with pytest.raises(UnsafePlan):
        parse_plan(reply)


def test_sql_is_compiled_from_catalog_not_provider_expressions(app, sample_data):
    value = plan(metrics=["avg_kda", "win_rate"], filters={"player": ["Faker"]}, order_by="avg_kda")
    compiled = compile_plan(value)
    from app import db
    sql = str(compiled["statement"].compile(dialect=db.engine.dialect, compile_kwargs={"literal_binds": True}))
    assert "JOIN teams" not in sql
    assert "JOIN matches" in sql
    assert "LIMIT 100" in validate_sql(sql, "sqlite")


@pytest.mark.parametrize("subject, metric_name", [(subject, key) for subject, metrics in METRICS.items() for key in metrics])
def test_every_catalog_metric_compiles_against_actual_database_columns(subject, metric_name, sample_data):
    result, _ = rows(plan(subject=subject, dimensions=[], metrics=[metric_name], order_by=metric_name))
    assert metric_name in result[0]


def test_two_call_budget_repairs_plan_then_uses_deterministic_summary(client, ai, sample_data):
    ai.side_effect = ["not JSON", json.dumps(plan(filters={"player": ["Faker"]}, metrics=["avg_kda"], order_by="avg_kda"))]
    response = client.post("/api/ai/query", json={"prompt": "Faker平均KDA"})
    assert response.status_code == 200
    assert ai.call_count == 2
    assert response.json["result"]["evidence"]["repaired"] is True
    assert response.json["result"]["data"][0]["avg_kda"] == 6
    assert "6.00" in response.json["result"]["answer"]


@pytest.mark.parametrize("verified_only, expected", [(False, 5), (True, 3)])
def test_real_provider_global_count_null_order_is_normalized_without_a_repair(client, ai, sample_data, verified_only, expected):
    provider_plan = {"type": "query", "subject": "match", "dimensions": [], "metrics": ["matches"],
                     "filters": {"verified_only": verified_only}, "min_games": 1, "order_by": None,
                     "direction": "desc", "limit": 1, "per_group_top_n": None}
    ai.side_effect = [json.dumps(provider_plan), f"当前收录范围共{expected}局。"]
    response = client.post("/api/ai/query", json={"prompt": "已核验总局数" if verified_only else "总局数"})
    assert response.status_code == 200
    result = response.json["result"]
    assert result["data"][0]["matches"] == expected
    assert result["context"]["plan"]["order_by"] == "matches"
    assert result["evidence"]["repaired"] is False
    assert result["evidence"]["model_calls"] == 2
    assert ai.call_count == 2


def test_null_group_sort_uses_business_default_but_invalid_sort_is_rejected():
    assert plan(dimensions=["month"], order_by=None)["order_by"] == "month"
    for value in ("", "no_such_metric"):
        with pytest.raises(InvalidPlan):
            plan(order_by=value)


def test_invalid_repair_stops_after_two_calls(client, ai, sample_data):
    ai.return_value = "not JSON"
    assert client.post("/api/ai/query", json={"prompt": "Faker平均KDA"}).status_code == 422
    assert ai.call_count == 2


def test_database_field_failure_is_repaired_once_without_a_third_model_call(client, ai, sample_data, monkeypatch):
    from sqlalchemy.exc import OperationalError
    initial = plan(metrics=["avg_kda"], filters={"player": ["Faker"]}, order_by="avg_kda")
    ai.side_effect = [json.dumps(initial), json.dumps(initial)]
    actual = ai_assistant.execute_readonly_batch
    calls = 0
    def fail_first(statements, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("SELECT", {}, Exception("no such column: internal_schema_column"))
        return actual(statements, timeout)
    monkeypatch.setattr(ai_assistant, "execute_readonly_batch", fail_first)
    response = client.post("/api/ai/query", json={"prompt": "Faker平均KDA"})
    assert response.status_code == 200
    assert response.json["result"]["evidence"]["repaired"] is True
    assert response.json["result"]["data"][0]["avg_kda"] == 6
    assert ai.call_count == 2
    assert "internal_schema_column" not in ai.call_args_list[1].args[1]


def test_query_timeout_does_not_spend_a_paid_repair_call(client, ai, sample_data, monkeypatch):
    from sqlalchemy.exc import OperationalError
    ai.return_value = json.dumps(plan(filters={"player": ["Faker"]}))
    monkeypatch.setattr(ai_assistant, "execute_readonly_batch", Mock(side_effect=OperationalError("SELECT", {}, Exception("interrupted"))))
    response = client.post("/api/ai/query", json={"prompt": "Faker出场次数"})
    assert response.status_code == 422
    assert ai.call_count == 1


@pytest.mark.parametrize("reply", ["DELETE FROM players", "SELECT * FROM sqlite_master", '```sql\nSELECT * FROM sqlite_master\n```', '{"type":"query","sql":"DROP TABLE matches"}'])
def test_unsafe_query_does_not_spend_a_repair_call(client, ai, sample_data, reply):
    ai.return_value = reply
    response = client.post("/api/ai/query", json={"prompt": "Faker平均KDA"})
    assert response.status_code == 422
    assert ai.call_count == 1


def test_business_ambiguity_and_missing_metrics_do_not_call_model(client, ai):
    response = client.post("/api/ai/query", json={"prompt": "谁最强？"})
    assert response.json["result"]["status"] == "needs_clarification"
    assert len(response.json["result"]["clarification"]["choices"]) == 3
    unsupported = client.post("/api/ai/query", json={"prompt": "哪个补丁版本英雄ban率最高"})
    assert unsupported.json["result"]["status"] == "unsupported"
    ai.assert_not_called()


def test_second_model_failure_keeps_actual_data_and_metadata(client, ai, sample_data):
    ai.side_effect = [json.dumps(plan(metrics=["avg_kda"], filters={"player": ["Faker"]}, order_by="avg_kda")), AIUnavailable("network unavailable")]
    response = client.post("/api/ai/query", json={"prompt": "Faker平均KDA"})
    assert response.status_code == 200
    result = response.json["result"]
    assert result["data"][0]["avg_kda"] == 6
    assert result["evidence"]["model_calls"] == 2
    assert any("文字解读暂时不可用" in text for text in result["assumptions"])


def test_followup_context_is_bounded_and_reuses_only_a_canonical_plan(client, ai, sample_data):
    previous = plan(metrics=["avg_kda"], filters={"player": ["Faker"]}, order_by="avg_kda")
    new = plan(metrics=["avg_kda"], filters={"player": ["Faker"], "date_start": "2024-01-01", "date_end": "2024-12-31"}, order_by="avg_kda")
    ai.side_effect = [json.dumps(new), "真实日期样本的平均KDA为6。"]
    response = client.post("/api/ai/query", json={"prompt": "那只看2024年", "context": {"plan": previous}})
    assert response.status_code == 200
    planning_input = json.loads(ai.call_args_list[0].args[1])
    assert planning_input["context"]["plan"]["filters"]["player"] == ["Faker"]
    result = response.json["result"]
    assert result["context"]["plan"]["filters"] == new["filters"]
    assert result["evidence"]["rows"] == 2
    assert result["evidence"]["excluded_updated_date_matches"] == 1
    assert result["evidence"]["excluded_unknown_date_matches"] == 1
    assert result["evidence"]["requested_date_start"] == "2024-01-01"


@pytest.mark.parametrize("context", [{"sql": "DROP TABLE players"}, {"plan": {"sql": "DELETE FROM players"}}, {"plan": {}, "extra": "x"}, {"plan": {"type": "query", "padding": "a" * 8500}}])
def test_bad_context_is_rejected_before_paid_model_call(client, ai, context):
    response = client.post("/api/ai/query", json={"prompt": "那只看今年", "context": context})
    assert response.status_code == 400
    ai.assert_not_called()


def test_small_samples_return_empty_instead_of_lowering_threshold(client, ai, sample_data):
    ai.return_value = json.dumps(plan(filters={"player": ["Faker"]}, min_games=10, metrics=["avg_kda"], order_by="avg_kda"))
    response = client.post("/api/ai/query", json={"prompt": "Faker至少10场的平均KDA"})
    result = response.json["result"]
    assert result["status"] == "empty"
    assert result["data"] == []
    assert result["evidence"]["rows"] == 4
    assert "没有降低" in result["answer"]
    assert result["context"]["plan"]["min_games"] == 10
    assert ai.call_count == 1


def test_catalog_endpoint_exposes_business_labels_not_arbitrary_sql(client):
    response = client.get("/api/ai/catalog")
    assert response.status_code == 200
    definition = response.json["result"]["subjects"]["player"]["metrics"]["avg_kda"]
    assert definition["label"] == "平均单局 KDA"
    assert "operation" not in definition


def test_shared_query_timeout_restores_the_connection(db):
    from sqlalchemy.exc import OperationalError
    with pytest.raises(OperationalError):
        execute_readonly_batch(["WITH RECURSIVE q(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM q WHERE n<1000000) SELECT SUM(n) FROM q"], timeout=0)
    db.session.add(Match(match_id=99999))
    db.session.commit()
    assert Match.query.count() == 1
