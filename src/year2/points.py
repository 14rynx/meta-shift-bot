import asyncio
import json
import math
from datetime import datetime, timedelta

from utils import get_item_metalevel, get_ship_slots, get_kill

known_kills = {}


async def get_kill_score(session, kill_id, kill_hash, rules, user_id=None):
    """Fetch a single kill from ESI and calculate it's score according to the competition rules"""
    kill = await get_kill(session, kill_id, kill_hash)

    # Calculate points of each category
    rarity_adjusted_victim_point = rules.rarity_adjusted_points(kill.get("victim", {}).get("ship_type_id", 0))

    standard_points = []
    risk_adjusted_pilot_point = None

    # If we have a defined protagonist, we go through all the attackers and assign points
    # The protagonist must fly some ship, otherwise 0 points, and only player characters count
    # Helpers get added as "unknown ship" if we can't figure out what they fly.
    if user_id:
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                if int(attacker["character_id"]) == user_id:
                    if "ship_type_id" in attacker:
                        risk_adjusted_pilot_point = rules.risk_adjusted_points(attacker["ship_type_id"])
                else:
                    standard_points.append(rules.points(attacker.get("ship_type_id", 0)))

    # If we don't have a clear protagonist, we have to assign one
    # First we collect all the points without protagonist, and use the risk adjusted point
    # To collect the difference (negative) if a guy were the protagonist
    else:
        risk_adjusted_pilot_point = 0
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                standard_point = rules.points(attacker.get("ship_type_id", 0))
                risk_point = rules.risk_adjusted_points(attacker.get("ship_type_id", 0))
                standard_points.append(standard_point)
                if risk_point and standard_point:
                    risk_adjusted_pilot_point = min(risk_adjusted_pilot_point, risk_point - standard_point)

    # Combine points into preliminary score
    try:
        kill_score = 10 * rarity_adjusted_victim_point / (risk_adjusted_pilot_point + sum(standard_points))

    except (ZeroDivisionError, ValueError, TypeError):
        kill_score = 0

    # Remove Tradehub Kills
    if kill.get("solar_system_id", 0) in [30000142, 30002187, 30002510, 30002053, 30002659]:
        kill_score = 0

    # Figure out the metalevel of items
    # Go through each slot, and find the module with the highest meta level in it to filter out ammo with meta level
    meta_levels = {}
    for item in kill.get("victim", {}).get("items", []):
        flag = int(item.get("flag", 0))
        meta_level = await get_item_metalevel(session, item["item_type_id"])
        quantity = int(item.get("quantity_destroyed", 0) + item.get("quantity_dropped", 0))
        if 11 <= flag <= 34 and quantity == 1:
            if flag in meta_levels:
                meta_levels[flag] = max(meta_level, meta_levels[flag])
            else:
                meta_levels[flag] = meta_level

    # Average the meta level in the best available way
    slots = (await get_ship_slots(session, kill["victim"]["ship_type_id"]))

    if sum(slots) > 0:
        average_meta_level = sum(meta_levels.values()) / sum(slots)
    elif len(meta_levels) > 0:
        average_meta_level = sum(meta_levels.values()) / len(meta_levels.values())
    else:
        average_meta_level = 5  # T2

    # Adjust score based on meta level
    # Parameters
    neutral_input = 5
    neutral_output = 1
    expo = 0.8
    scaling = 0.5

    # Linearly scale meta level into the range -1 ... something, with 0 for neutral element
    linear = (average_meta_level - neutral_input) / neutral_input

    # Apply exponentiation so that values of -1 and 1 stay the same, then scale the output
    exponential = linear * math.exp(abs(linear * expo)) * (scaling / math.exp(expo))

    # Move neutral element to desired output
    factor = exponential + neutral_output

    # Apply factor to score
    kill_score *= factor

    # Find time of killmail for cache
    if "killmail_time" in kill:
        kill_time = datetime.strptime(kill['killmail_time'], '%Y-%m-%dT%H:%M:%SZ')
    else:
        kill_time = datetime.utcnow()

    # Figure out time bracket allowed for this kill to be merged (To be used in future versions)
    standard_points = []
    for attacker in kill.get("attackers", []):
        if "character_id" in attacker:
            standard_points.append(rules.points(attacker.get("ship_type_id", 0)))
    victim_point = rules.points(kill.get("victim", {}).get("ship_type_id", 0))

    try:
        time_bracket = timedelta(seconds=90 * victim_point / sum(standard_points))
    except (ZeroDivisionError, ValueError, TypeError):
        time_bracket = timedelta(seconds=90)

    return kill_id, kill_time, kill_score, time_bracket


async def get_score_groups(session, rules, character_id):
    """
    Fetch all kills of a character for some period from zkill and do point calculation
    """
    start = datetime.utcnow() - timedelta(days=90)  # TODO: Fix according to timespan

    zkill_url = f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/"

    usable_kills = {}
    over = False

    page = 1
    while not over and page < 100:

        # Fetch kill information from zkillboard
        async with session.get(f"{zkill_url}page/{page}/") as response:
            kills = []
            for attempt in range(10):
                try:
                    kills = await response.json(content_type=None)
                    page += 1
                    break
                except json.decoder.JSONDecodeError:
                    await asyncio.sleep(0.1)

        # Extract data, which might be differently encoded depending on which zkill url is used
        if type(kills) is dict:
            kills_and_hashes = kills.items()
        else:
            kills_and_hashes = [[kill["killmail_id"], kill["zkb"]["hash"]] for kill in kills]

        # Filter out wired kills that do not actually exist !?
        kills_and_hashes = [(k, h) for k, h in kills_and_hashes if h != "CCP VERIFIED"]

        # Find all kills that are already in cache
        tasks = []
        for kill_id, kill_hash in kills_and_hashes:
            if kill_id in known_kills:
                kill_time, kill_score, time_bracket = known_kills[kill_id]
                # If a kill is too far in the past, then we do not include it
                if kill_time > start:
                    usable_kills[kill_id] = (kill_time, kill_score, time_bracket)
                else:
                    over = True
            else:
                tasks.append(get_kill_score(session, kill_id, kill_hash, rules, character_id))

        # Fill in the gaps and update cache
        for kill_id, kill_time, kill_score, time_bracket in await asyncio.gather(*tasks):
            known_kills[kill_id] = (kill_time, kill_score, time_bracket)

            if kill_time > start:
                usable_kills[kill_id] = (kill_time, kill_score, time_bracket)
            else:
                over = True

    # Collate kills based on their time bracket
    groups = {}
    last_time = None
    last_id = None
    for kill_id, (kill_time, kill_score, time_bracket) in sorted(usable_kills.items(), key=lambda x: x[0]):
        if kill_score > 0:
            if last_time and kill_time - time_bracket < max(last_time):
                groups[last_id].append((kill_id, kill_score))
                last_time.append(kill_time)
            else:
                last_id = kill_id
                last_time = [kill_time]
                groups[last_id] = [(kill_id, kill_score)]

    # Now rearrange scores with total_score: kills
    score_groups = [(sum([s for i, s in kills]), kills) for last_id, kills in groups.items()]
    return score_groups


async def get_total_score(session, rules, character_id):
    """
    Sum up all the scores according to the competition rules
    """
    score_groups = await get_score_groups(session, rules, character_id)
    try:
        scores = [s for s, kills in score_groups]
        total_score = sum(sorted(scores, reverse=True)[:30])
    except ValueError:
        total_score = 0
    return round(total_score, 2)
