import json
import logging
import ssl

import aiohttp
import async_lru
import certifi

# Configure the logger
logger = logging.getLogger('discord.utils')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


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


@async_lru.alru_cache(maxsize=1000)
async def get_character_name(session, character_id):
    async with session.get(f"https://esi.evetech.net/latest/characters/{character_id}/") as response:
        if response.status == 200:
            return (await response.json(content_type=None))["name"]
        return f"CID: {character_id}"


@async_lru.alru_cache(maxsize=40000)
async def get_item_metalevel(session, type_id):
    try:
        for dogma_attribute in \
                (await repeated_get(session, f"https://esi.evetech.net/latest/universe/types/{type_id}/"))[
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
        if response.status == 200:
            try:
                return await response.json(content_type=None)
            except Exception as e:
                logger.error(f"Error {e} with ESI {response.status}: {await response.text()}")
        raise ValueError(f"Could not fetch data from url {url}!")


async def send_large_message(ctx, message, max_chars=2000, delimiter="\n", **kwargs):
    while len(message) > 0:
        # Check if the message content is shorter than the max_chars
        if len(message) <= max_chars:
            await ctx.send(message, **kwargs)
            break

        # Find the last delimiter character before max_chars
        last_newline_index = message.rfind(delimiter, 0, max_chars)

        # If there is no delimiter before max_chars, split at max_chars
        if last_newline_index == -1:
            await ctx.send(message[:max_chars], **kwargs)
            message = message[max_chars:]

        # Split at the last delimiter before max_chars
        else:
            await ctx.send(message[:last_newline_index], **kwargs)
            message = message[last_newline_index + 1:]
