import asyncio
import json
import logging
import ssl
from datetime import datetime

import aiohttp
import async_lru
import certifi

# Configure the logger
logger = logging.getLogger('discord.network')
logger.setLevel(logging.ERROR)

kill_cache = {}


async def lookup(string, return_type):
    """Tries to find an ID related to the input.

    Parameters
    ----------
    string : str
        The character / corporation / alliance name
    return_type : str
        what kind of id should be tried to match
        can be characters, corporations and alliances

    Raises
    ------
    ValueError, JSONDecodeError ...
    """
    try:
        return int(string)
    except ValueError:
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                async with session.post(
                        'https://esi.evetech.net/latest/universe/ids/?datasource=tranquility&language=en',
                        json=[string]) as response:
                    results = (await response.json())[return_type]
                    return int(max(results, key=lambda x: x["id"])["id"])
        except (ValueError, json.JSONDecodeError, KeyError):
            raise ValueError("Could not parse that character!")


@async_lru.alru_cache(maxsize=40000)
async def get_item_name(session, type_id):
    try:
        return (await get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))["name"]
    except ValueError:
        return f"Type ID: {type_id}"


@async_lru.alru_cache(maxsize=1000)
async def get_character_name(session, character_id):
    async with session.get(f"https://esi.evetech.net/latest/characters/{character_id}/") as response:
        if response.status == 200:
            return (await response.json(content_type=None))["name"]
        return f"CID: {character_id}"


@async_lru.alru_cache(maxsize=100000)
async def get_item_metalevel(session, type_id):
    try:
        for dogma_attribute in \
                (await get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
                    "dogma_attributes"]:
            if int(dogma_attribute.get("attribute_id", 0)) in [1692, 633]:
                return float(dogma_attribute.get("value", 5.0))
    except KeyError:
        pass
    return 5.0


@async_lru.alru_cache(maxsize=500)
async def get_ship_slots(session, type_id):
    low_slots = 0
    mid_slots = 0
    high_slots = 0
    for dogma_attribute in (await get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
        "dogma_attributes"]:
        attribute_id = int(dogma_attribute.get("attribute_id", 0))
        attribute_value = int(dogma_attribute.get("value", 0))
        if attribute_id == 12:
            low_slots = attribute_value
        elif attribute_id == 13:
            mid_slots = attribute_value
        elif attribute_id == 14:
            high_slots = attribute_value
    return low_slots, mid_slots, high_slots


@async_lru.alru_cache(maxsize=40000)
async def get_hash(session, kill_id):
    return (await get(session, f"https://zkillboard.com/api/kills/killID/{kill_id}/"))[0]["zkb"]["hash"]


@async_lru.alru_cache(maxsize=40000)
async def get_kill(session, kill_id, kill_hash):
    """Fetch a kill from ESI based on its id and hash"""
    return await get(session, f"https://esi.evetech.net/latest/killmails/{kill_id}/{kill_hash}/")


async def get(session, url) -> dict:
    async with session.get(url) as response:
        if response.status == 200:
            try:
                return await response.json(content_type=None)
            except Exception as e:
                logger.error(f"Error {e} with ESI {response.status}: {await response.text()}")
        raise ValueError(f"Could not fetch data from ESI!")


async def get_kill_page(session, character_id, page):
    url = f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/page/{page}/"

    async with session.get(url) as response:
        kills = []
        for attempt in range(3):
            if response.status == 200:
                try:
                    kills = await response.json(content_type=None)
                except Exception as instance:
                    logger.error(f"Could not parse JSON: {await response.text()}", exc_info=True)
                else:
                    break
            elif response.status == 429:
                logger.warning(f"To many requests with user {character_id} on page {page}")
                raise ValueError(f"Could not fetch data from character {character_id}!")

            await asyncio.sleep(0.5 * (attempt + 2) ** 3)  # Exponential backoff

        # Extract data, which might be differently encoded depending on how zkill does it
        if type(kills) is not dict:
            kills = {kill["killmail_id"]: kill["zkb"]["hash"] for kill in kills}

        # Filter out wired kills that do not actually exist !?
        kills = {k: h for k, h in kills.items() if h != "CCP VERIFIED"}

    return kills


async def get_kill_pages(session, character_id, start):
    """Fetch all kills for a character up to a certain start time.
    Start time is inexact, some kills before might be returned"""
    over = False

    for page in range(1, 100):
        if over:
            break

        kills = await get_kill_page(session, character_id, page)

        # Check if the response is empty. If so we reached the last page and can stop
        if len(kills) == 0:
            over = True
            continue

        # Check if the last kill (smallest id) is old enough
        kill_id, kill_hash = min(kills.items(), key=lambda x: x[0])
        first_kill = await get_kill(session, kill_id, kill_hash)
        first_kill_time = datetime.strptime(first_kill.get('killmail_time'), '%Y-%m-%dT%H:%M:%SZ')

        logger.debug(f"Page {page}: first kill_id {kill_id}, time {first_kill_time}-")
        if first_kill_time < start:
            over = True

        # If the last kill is already in the stored data we have reached far enough
        # (Kills getting added later on far in the past are ignored)
        if character_id in kill_cache and kill_id in kill_cache[character_id]:
            over = True

        # Update per character cache and get kills from it if there are any
        if character_id in kill_cache:
            kill_cache[character_id].update(kills)
        else:
            kill_cache[character_id] = kills

        # Sleep on smaller pages to not trigger 429 on zkillboard.com
        await asyncio.sleep(2)

    if character_id in kill_cache:
        return kill_cache[character_id]
    return {}
