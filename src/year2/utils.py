import asyncio
import json
import ssl

import aiohttp
import async_lru
import certifi


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
                    return max(results, key=lambda x: x["id"])["id"]
        except (ValueError, json.JSONDecodeError, KeyError):
            raise ValueError


@async_lru.alru_cache(maxsize=40000)
async def get_item_name(session, type_id):
    try:
        return (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))["name"]
    except ValueError:
        return f"Type ID: {type_id}"


@async_lru.alru_cache(maxsize=40000)
async def get_item_metalevel(session, type_id):
    try:
        for dogma_attribute in (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
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
    for dogma_attribute in (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
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


async def get_hash(session, kill_id):
    return (await repeated_get(session, f"https://zkillboard.com/api/kills/killID/{kill_id}/"))[0]["zkb"]["hash"]


async def get_kill(session, kill_id, kill_hash):
    """Fetch a kill from ESI based on its id and hash"""
    return await repeated_get(session, f"https://esi.evetech.net/latest/killmails/{kill_id}/{kill_hash}/")


async def repeated_get(session, url) -> dict:
    async with session.get(url) as response:
        for x in range(6):
            try:
                if response.status == 200:
                    return await response.json(content_type=None)
            except json.decoder.JSONDecodeError:
                pass

            print("Retry", x + 1, response.status, url)
            await asyncio.sleep(0.5 * (x + 2) ** 3)

        raise ValueError(f"Could not fetch data from url {url}!")
