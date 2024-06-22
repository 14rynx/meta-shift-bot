import asyncio
import logging
import ssl
from datetime import datetime

import aiohttp
import certifi
from discord.ext import tasks

from points import get_total_score, get_collated_kills
from models import Entry

# Configure the logger
logger = logging.getLogger('discord.background')
logger.setLevel(logging.ERROR)

ssl_context = ssl.create_default_context(cafile=certifi.where())


@tasks.loop(count=1)
async def refresh_scores(rules, max_delay):
    """Background task to refresh all user scores periodically."""

    while True:
        entry = Entry.select().where(Entry.season == rules.season).order_by(Entry.points_expiry.asc()).first()
        logger.debug(f"Updating entry with expiry {entry.points_expiry}.")

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            worked = False
            for _ in range(5):
                try:
                    score_groups, _ = await asyncio.gather(
                        get_collated_kills(session, rules, int(entry.character_id)),
                        asyncio.sleep(1))
                    user_score = get_total_score(score_groups)
                    worked = True
                except (ValueError, AttributeError, TimeoutError, aiohttp.http_exceptions.BadHttpMessage):  # noqa
                    await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error
                    logger.warning(f"Updating character {entry.character_id} failed, retrying.")

        if worked:
            logger.debug(f"Entry {entry.character_id} updated to {user_score} points.")
            entry.points_expiry = datetime.utcnow() + max_delay
            entry.points = user_score
            entry.save()
        else:
            logger.exception(f"Updating character {entry.character_id} failed!")

        refresh_interval = max_delay.total_seconds() / (2 * rules.season.entries.count() + 1)
        await asyncio.sleep(refresh_interval)
