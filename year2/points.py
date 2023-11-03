import asyncio
from datetime import datetime, timedelta

from year2.rules import RulesConnector
from year2.utils import gather_kills


async def get_partial_score(kill, rules, user_id):
    victim_point = rules.victim_points(kill.get("victim", {}).get("ship_type_id", 0))

    helper_points = []
    killer_point = None

    for attacker in kill["attackers"]:
        if "character_id" in attacker:
            if int(attacker["character_id"]) == user_id:
                killer_point = rules.killer_points(attacker.get("ship_type_id", 0))
            else:
                helper_points.append(rules.helper_points(attacker.get("ship_type_id", 0)))

    if victim_point is None or killer_point is None or None in helper_points:
        return 0

    # Limit the available functions for eval()
    allowed_globals = {'__builtins__': None, 'sorted': sorted, 'sum': sum, 'vp': victim_point, 'hps': helper_points,
                       'kp': killer_point}

    return eval(rules.kill_formula, allowed_globals)


async def get_score(character_id):
    until = datetime.utcnow() - timedelta(days=90)  # TODO: Fix according to timespan
    kills = await gather_kills(f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/", until)

    rules = RulesConnector(1)  # TODO: Season selector

    tasks = [get_partial_score(kill, rules, character_id) for kill in kills]
    points = await asyncio.gather(*tasks)

    # Write any ships where the point amount was unknown back to the spreadsheet so rules can be improved
    await rules.writeback()

    # Limit the available functions for eval()
    allowed_globals = {'__builtins__': None, 'sorted': sorted, 'sum': sum, 'points': points}

    return round(eval(rules.sum_formula, allowed_globals), 2)
