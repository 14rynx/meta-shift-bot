from datetime import datetime, timedelta

from year2.utils import gather_kills


async def get_points(character_id):
    until = datetime.utcnow() - timedelta(days=90)  # TODO: Fix according to timespan
    kills = await gather_kills(f"https://zkillboard.com/api/kills/characterID/{character_id}/kills/", until)

    points = 0
    for kill in kills:
        points += int(kill["victim"].get("damage_taken", 0))
    return points
