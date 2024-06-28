import asyncio
import logging
import math
from datetime import datetime, timedelta

from network import get_item_metalevel, get_ship_slots, get_kill, get_kill_pages

# Configure the logger
logger = logging.getLogger('discord.points')
logger.setLevel(logging.ERROR)

score_cache_dict = {}


async def get_average_meta_level(session, kill):
    """
    Get the average meta level of the fitted items on a kill.
    Deals with empty slots and averages them as meta level 0
    """
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
        logger.debug(f"Could not determine slots for kill {kill['killmail_id']}.")
        average_meta_level = sum(meta_levels.values()) / len(meta_levels.values())
    else:
        logger.debug(f"Could not calculate meta level for kill {kill['killmail_id']}.")
        average_meta_level = 5  # T2

    return average_meta_level


async def scale_score_on_meta_level(score, session, kill):
    """
    Adjust the score based on the meta levels / filled slots of the victim
    - Figure out the metalevel of items
    - Go through each slot, and find the module with the highest meta level in it to filter out ammo with meta level

    Meta-parameters:
    - neutral_input:  Meta level that results in no change
    - neutral_output: What no change means
    - expo:           How strongly meta level is exponential (bigger number -> smaller output changes around neutral)
    - scaling:        How much of the total score can be deducted at most
    """
    neutral_input = 5
    neutral_output = 1
    expo = 0.8
    scaling = 0.5

    meta_level = await get_average_meta_level(session, kill)

    # Linearly scale meta level into the range -1 ... something, with 0 for neutral element
    linear = (meta_level - neutral_input) / neutral_input
    # Apply exponentiation so that values of -1 and 1 stay the same, then scale the output
    exponential = linear * math.exp(abs(linear * expo)) * (scaling / math.exp(expo))
    # Move neutral element to desired output
    factor = exponential + neutral_output
    # Apply factor to score
    score *= factor

    return score


def stapling_time(kill, rules):
    """
    Figure out time bracket allowed for this kill to be stapled with other kills.
    Meta-Parameters
    - base_time:        Time each kills always gives
    - scaling_time:     Time that changes based on sizes of killer / attackers
    - attacker_scaling: How much having more people on a kill results in less time awarded
    """

    base_time = 60
    scaling_time = 60
    attacker_scaling = 1.6

    time_adjusted_victim_points = rules.time_adjusted(kill.get("victim", {}))

    try:
        attacker_points = []
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                attacker_points.append(rules.base(attacker) ** attacker_scaling)

        attacker_adjusted_points = sum(attacker_points) ** (1 / attacker_scaling)
        time_bracket = timedelta(
            seconds=base_time + scaling_time * time_adjusted_victim_points / attacker_adjusted_points)
    except (ZeroDivisionError, ValueError, TypeError):
        logger.info(f"Could not determine time_bracket for kill {kill['killmail_id']}")
        time_bracket = timedelta(seconds=base_time + scaling_time)

    return time_bracket


def kill_is_valid(kill):
    """
    Filter out any kills that are not allowed
    - Kills must not be in a tradehub system
    - Kills must not be in Zarzakh (Bubble Chesse)
    - Kills must not have CONCORD on it (it would have died either way)
    """

    if kill.get("solar_system_id", 0) in [30000142, 30002187, 30002510, 30002053, 30002659, 30002768, 30100000]:
        return False

    for attacker in kill.get("attackers", []):
        if attacker.get("ship_type_id", 0) == 3885:
            return False

    return True


async def get_kill_score(session, kill_id, kill_hash, rules, main_character_id=None):
    """Fetch a single kill from ESI and calculate it's score according to the competition rules"""
    kill = await get_kill(session, kill_id, kill_hash)

    kill_time = datetime.strptime(kill['killmail_time'], '%Y-%m-%dT%H:%M:%SZ')
    time_bracket = stapling_time(kill, rules)

    if not rules.season.start < kill_time < rules.season.end:
        return kill_id, kill_time, 0, time_bracket

    if not kill_is_valid(kill):
        return kill_id, kill_time, 0, time_bracket

    # ATTACKERS / VICTIM CALCULATION
    # Calculate points of each category
    rarity_adjusted_victim_points = rules.rarity_adjusted(kill.get("victim", {}))

    standard_points = []
    risk_adjusted_pilot_points = None

    # If we have a defined protagonist, we go through all the attackers and assign points
    # The protagonist must fly some ship, otherwise 0 points, and only player characters count
    # Helpers get added as "unknown ship" if we can't figure out what they fly.
    if main_character_id:
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                if int(attacker["character_id"]) == main_character_id:
                    if "ship_type_id" in attacker:
                        risk_adjusted_pilot_points = rules.risk_adjusted(attacker)
                else:
                    standard_points.append(rules.base(attacker))

    # If we don't have a clear protagonist, we have to assign one
    # First we collect all the points without protagonist, and use the risk adjusted point
    # To collect the difference (negative) if a guy were the protagonist
    else:
        risk_adjusted_pilot_points = 0
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                standard_point = rules.base(attacker)
                risk_point = rules.risk_adjusted(attacker)
                standard_points.append(standard_point)
                if risk_point and standard_point:
                    risk_adjusted_pilot_points = min(risk_adjusted_pilot_points, risk_point - standard_point)

    # Combine points into preliminary score
    try:
        kill_score = 10 * rarity_adjusted_victim_points / (risk_adjusted_pilot_points + sum(standard_points))
    except (ZeroDivisionError, ValueError, TypeError):
        logger.debug(f"Could not calculate score for kill {kill_id}")
        kill_score = 0

    logger.info(f"Kill {kill_id} is worth {kill_score} points.")
    kill_score = await scale_score_on_meta_level(kill_score, session, kill)

    return kill_id, kill_time, kill_score, time_bracket


async def get_kill_score_cached(session, kill_id, kill_hash, rules, main_character_id=None):
    """Cache kill score based on kill_id and main_character_id"""

    cache_key = (kill_id, main_character_id)

    if cache_key in score_cache_dict:
        return score_cache_dict[cache_key]

    result = await get_kill_score(session, kill_id, kill_hash, rules, main_character_id)
    score_cache_dict[cache_key] = result
    return result


async def get_kill_scores(session, rules, character_id):
    """Fetch all kills for a character in a given time frame"""

    kills = await get_kill_pages(session, character_id, start=rules.season.start)

    # Find all kills that are already in cache
    tasks = []
    for kill_id, kill_hash in kills.items():
        tasks.append(get_kill_score_cached(session, kill_id, kill_hash, rules, character_id))

    # Fetch scores
    usable_kills = []
    for values in await asyncio.gather(*tasks):
        usable_kills.append(values)

    return usable_kills


async def get_collated_scores(session, rules, character_id):
    """
    Fetch all kills of a character for some period from zkill and do point calculation
    """

    logger.info(f"Starting fetch for character {character_id}.")
    try:
        kill_scores = await get_kill_scores(session, rules, character_id)
    except ValueError as error_instance:
        logger.warning(f"Could not determine total score for character {character_id}")
        raise error_instance

    logger.debug(f"fetched {len(kill_scores)} kills for {character_id}")

    # Group kills based on their time bracket
    groups = {}
    last_time = None
    last_id = None
    for kill_id, kill_time, kill_score, time_bracket in sorted(kill_scores, key=lambda x: x[0]):
        if kill_score > 0:
            if last_time and kill_time - time_bracket < max(last_time):
                groups[last_id].append((kill_id, kill_score))
                last_time.append(kill_time)
            else:
                last_id = kill_id
                last_time = [kill_time]
                groups[last_id] = [(kill_id, kill_score)]

    # Now figure out the scores of the stapled kills.
    # Meta-parameter
    max_multiplier = 2  # How much more a kill can be worth if you kill multiple

    score_groups = []
    for last_id, kills in groups.items():
        stapled_score = 0
        for i, (kill_id, kill_score) in enumerate(kills):
            # Geometric sum style formula e.g. for 2 results in 1, 1.5, 1.75, 1.875 ... 2 - e
            multiplier = max_multiplier - max_multiplier ** -i
            logger.debug(f"Group {last_id} multiplier {multiplier}.")
            stapled_score += kill_score * multiplier
        score_groups.append((stapled_score, kills))

    return score_groups


def get_total_score(score_groups):
    """
    Sum up all the scores according to the competition rules
    """
    scores = [s for s, kills in score_groups]
    total_score = sum(sorted(scores, reverse=True)[:30])

    return round(total_score, 2)
