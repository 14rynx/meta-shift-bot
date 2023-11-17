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
    for dogma_attribute in (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
        "dogma_attributes"]:
        if int(dogma_attribute.get("attribute_id", 0)) in [1692, 633]:
            return float(dogma_attribute.get("value", 0.0))
    return 0.0


@async_lru.alru_cache(maxsize=500)
async def get_ship_slots(session, type_id):
    slot_sum = 0
    for dogma_attribute in (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
        "dogma_attributes"]:
        if int(dogma_attribute.get("attribute_id", 0)) in [12, 13, 14]:
            slot_sum += int(dogma_attribute.get("value", 0))
    return slot_sum


@async_lru.alru_cache(maxsize=10000)
async def get_system_security(session, system_id):
    return (await repeated_get(session, f"https://esi.evetech.net/latest/universe/systems/{system_id}/"))[
        "security_status"]


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

            print("Retry", x, response.status, url)
            if x % 2:
                await asyncio.sleep(0.5 * x ** 3)
            else:
                await asyncio.sleep(0.5)

        raise ValueError(f"Could not fetch data from url {url}!")
