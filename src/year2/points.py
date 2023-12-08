import asyncio
import logging
import math
from datetime import datetime, timedelta

from network import get_kill_page, get_item_metalevel, get_ship_slots, get_kill

# Configure the logger
logger = logging.getLogger('discord.points')
logger.setLevel(logging.WARNING)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

kill_cache = {}
character_cache = {}


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
        logger.info(f"Could not calculate score for kill {kill_id}")
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
        logger.info(f"Could not determine slots for kill {kill_id}")
        average_meta_level = sum(meta_levels.values()) / len(meta_levels.values())
    else:
        logger.info(f"Could not calculate meta level for kill {kill_id}")
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
        logger.warning(f"Could extract time for kill {kill_id}")
        kill_time = datetime.utcnow()

    # Figure out time bracket allowed for this kill to be merged
    base_time = 30
    scaling_time = 60
    attacker_scaling = 1.6

    try:
        attacker_points = []
        for attacker in kill.get("attackers", []):
            if "character_id" in attacker:
                attacker_points.append(rules.points(attacker.get("ship_type_id", 0)) ** attacker_scaling)

        attacker_adjusted_points = sum(attacker_points) ** (1 / attacker_scaling)
        time_bracket = timedelta(
            seconds=base_time + scaling_time * rarity_adjusted_victim_point / attacker_adjusted_points)
    except (ZeroDivisionError, ValueError, TypeError):
        logger.warning(f"Could not determine time_bracket for kill {kill_id}")
        time_bracket = timedelta(seconds=base_time + scaling_time)

    return kill_id, kill_time, kill_score, time_bracket


async def get_usable_kills(session, rules, character_id, start, end):
    """Fetch a single page of kills from a character"""
    usable_kills = {}
    over = False

    for page in range(1, 100):
        if over:
            break

        kills_and_hashes = await get_kill_page(session, character_id, page)

        # Check if the response is empty. If so we reached the last page and can stop
        if len(kills_and_hashes) == 0:
            over = True

        await asyncio.sleep(1 - len(kills_and_hashes) / 50)  # Sleep on smaller pages to not trigger 429 or zkill

        # Update per character cache and get kills from it if there are any
        if character_id in character_cache:
            character_cache[character_id].extend(kills_and_hashes)
        else:
            character_cache[character_id] = kills_and_hashes

        # If our page connects to the cache, pull the entire cache, which might end the fetch
        if set(kills_and_hashes) & set(character_cache[character_id]):
            kills_and_hashes = character_cache[character_id]

        # Find all kills that are already in cache
        tasks = []
        for kill_id, kill_hash in kills_and_hashes:
            if kill_id in kill_cache:
                kill_time, kill_score, time_bracket = kill_cache[kill_id]
                # If a kill is too far in the past, then we do not include it
                if start < kill_time < end:
                    usable_kills[kill_id] = (kill_time, kill_score, time_bracket)
                elif kill_time < start:
                    over = True
            else:
                tasks.append(get_kill_score(session, kill_id, kill_hash, rules, character_id))

        # Fill in the gaps and update cache
        for kill_id, kill_time, kill_score, time_bracket in await asyncio.gather(*tasks):
            kill_cache[kill_id] = (kill_time, kill_score, time_bracket)

            if start < kill_time < end:
                usable_kills[kill_id] = (kill_time, kill_score, time_bracket)
            elif kill_time < start:
                over = True
    return usable_kills


async def get_collated_kills(session, rules, character_id):
    """
    Fetch all kills of a character for some period from zkill and do point calculation
    """

    start = datetime.utcnow() - timedelta(days=90)
    end = datetime.utcnow() - timedelta(days=1)

    logger.info(f"Starting fetch for character {character_id}")
    usable_kills = await get_usable_kills(session, rules, character_id, start, end)

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
    score_groups = await get_collated_kills(session, rules, character_id)
    try:
        scores = [s for s, kills in score_groups]
        total_score = sum(sorted(scores, reverse=True)[:30])
    except ValueError:
        logger.error(f"Could not determine total score for character {character_id}")
        total_score = 0
    return round(total_score, 2)
