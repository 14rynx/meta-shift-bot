import asyncio
import ssl
from datetime import datetime, timedelta

import aiohttp
import certifi

from year2.utils import gather_kills


async def get_item_group(type_id, session):
    async with session.get(f"https://esi.evetech.net/latest/universe/types/{type_id}/") as response:
        json = await response.json(content_type=None)
        if response.status == 200:
            if "group_id" in json:
                return int(json["group_id"])
            else:
                for attribute in json["dogma_attributes"]:
                    if attribute["attribute_id"] == 1766:
                        return int(attribute["value"])
        return 0


async def get_ship_points(type_id, session):
    group_rig_sizes = {
        659: 30,  # Supercarrier
        30: 30,  # Titan

        883: 25,  # Rorqual
        547: 25,  # Carrier
        485: 25,  # Dread
        1538: 25,  # FAX
        4594: 25,  # Lancer

        513: 25,  # Freighter
        902: 25,  # Jump Freighter

        27: 20,  # T1 Battleship
        898: 20,  # Black Ops
        941: 20,  # Indu Command Ship
        900: 20,  # Marauder

        1201: 16,  # Attack BC
        540: 16,  # Command BC
        419: 16,  # T1 / Faction BC

        906: 12,  # Combat Recon (Dscan)
        26: 12,  # T1 / Faction / Pirate Cruiser
        1972: 12,  # Monitor
        833: 12,  # Force Recon (Cyno)
        358: 12,  # HAC
        894: 12,  # HIC
        832: 12,  # T2 Logi
        963: 12,  # T3 Cruiser

        28: 12,  # T1 Hauler
        1202: 12,  # Blockade Runner
        380: 12,  # Deep Space Transport
        463: 12,  # Barge
        543: 12,  # Exhumer

        1305: 12,  # T3 Destroyer
        420: 12,  # T1 / Faction Destroyer
        541: 12,  # Dictor
        1534: 10,  # Command Destroyer

        324: 10,  # Assault Frigate
        831: 10,  # Interceptor
        830: 10,  # Covert Ops Frigate
        893: 10,  # Electronics Frigate
        1527: 10,  # Logi Frigate
        834: 10,  # Bomber
        25: 10,  # T1 / Faction / Pirate Frigate

        1283: 10,  # Mining Frigate
        1022: 10,  # Zephyr
        237: 10,  # Corvette
        31: 10,  # Shuttle
        29: 10  # Capsule - Could be anything dead
    }
    try:
        group = await get_item_group(type_id, session)
        return group_rig_sizes[group]
    except (TypeError, KeyError):
        return 10  # Anything else


async def get_partial_score(kill, session):
    victim_points = await get_ship_points(kill["victim"].get("ship_type_id", 0), session)
    tasks = [get_ship_points(attacker.get("ship_type_id", 0), session) for attacker in
             kill.get("attackers", [])]
    enemy_points = await asyncio.gather(*tasks)
    print(victim_points, enemy_points)
    return 10 * victim_points / sum(enemy_points)


async def get_score(character_id):
    until = datetime.utcnow() - timedelta(days=90)  # TODO: Fix according to timespan
    kills = await gather_kills(f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/", until)

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        tasks = [get_partial_score(kill, session) for kill in kills]
        scores = await asyncio.gather(*tasks)
        print(scores)

    return round(sum(scores), 2)
