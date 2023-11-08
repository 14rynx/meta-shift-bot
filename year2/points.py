import asyncio
import json
import ssl
import time
from datetime import datetime, timedelta

import aiohttp
import certifi

known_kills = {}


async def get_kill(session, kill_id, kill_hash):
    """Fetch a kill from ESI based on its id and hash"""
    async with session.get(
            f"https://esi.evetech.net/latest/killmails/{kill_id}/{kill_hash}/?datasource=tranquility") as resp:
        try:
            return await resp.json(content_type=None)
        except json.decoder.JSONDecodeError:
            return await get_kill(session, kill_id, kill_hash)


async def get_kill_score(session, kill_id, kill_hash, rules, user_id):
    """Fetch a single kill from ESI and calculate it's score according to the competition rules"""
    kill = await get_kill(session, kill_id, kill_hash)

    victim_point = rules.victim_points(kill.get("victim", {}).get("ship_type_id", 0))

    helper_points = []
    killer_point = None

    for attacker in kill.get("attackers", []):
        if "character_id" in attacker:
            if int(attacker["character_id"]) == user_id:
                killer_point = rules.killer_points(attacker.get("ship_type_id", 0))
            else:
                helper_points.append(rules.helper_points(attacker.get("ship_type_id", 0)))

    try:
        kill_score = 10 * victim_point / (killer_point + sum(helper_points))
    except (ZeroDivisionError, ValueError, TypeError):
        kill_score = 0

    # Find time of killmail for cache
    if "killmail_time" in kill:
        kill_time = datetime.strptime(kill['killmail_time'], '%Y-%m-%dT%H:%M:%SZ')
    else:
        kill_time = datetime.utcnow()

    return kill_id, kill_time, kill_score


async def get_scores(rules, character_id):
    """
    Fetch all kills of a character for some period from zkill and do point calculation
    """
    start = datetime.utcnow() - timedelta(days=90)  # TODO: Fix according to timespan

    # Fetch the newest rules if needed
    await rules.update()

    zkill_url = f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/"

    ids_and_scores = {}
    over = False

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
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
                        time.sleep(1)

            # Extract data, which might be differently encoded depending on which zkill url is used
            if type(kills) is dict:
                kills_and_hashes = kills.items()
            else:
                kills_and_hashes = [[kill["killmail_id"], kill["zkb"]["hash"]] for kill in kills]

            # Find all kills that are already in cache
            tasks = []
            for kill_id, kill_hash in kills_and_hashes:
                if kill_id in known_kills:
                    kill_time, kill_score = known_kills[kill_id]
                    # If a kill is too far in the past, then we do not include it
                    if kill_time > start:
                        ids_and_scores[kill_id] = kill_score
                    else:
                        over = True
                else:
                    tasks.append(get_kill_score(session, kill_id, kill_hash, rules, character_id))

            # Fill in the gaps and update cache
            for kill_id, kill_time, kill_score in await asyncio.gather(*tasks):
                known_kills[kill_id] = (kill_time, kill_score)

                if kill_time > start:
                    ids_and_scores[kill_id] = kill_score
                else:
                    over = True

    return ids_and_scores


async def get_total_score(rules, character_id):
    """
    Sum up all the scores according to the competition rules
    """
    ids_and_scores = await get_scores(rules, character_id)
    try:
        total_score = round(sum(sorted(ids_and_scores.values(), reverse=True)[:30]), 2)
    except ValueError:
        total_score = 0
    return total_score
