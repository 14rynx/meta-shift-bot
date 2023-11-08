import json
import ssl

import aiohttp
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
        except (ValueError, json.JSONDecodeError):
            raise ValueError


async def get_item_name(session, type_id):
    async with session.get(f"https://esi.evetech.net/latest/universe/types/{type_id}/") as response:
        if response.status == 200:
            return (await response.json(content_type=None))["name"]
        return f"Could not Fetch Item Name, Type ID: {type_id}"


async def get_system_security(session, system_id):
    async with session.get(f"https://esi.evetech.net/latest/universe/systems/{system_id}/") as response:
        if response.status == 200:
            return (await response.json(content_type=None))["security_status"]
        return 0.0
