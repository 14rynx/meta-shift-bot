import asyncio
import logging
import ssl
from datetime import datetime

import aiohttp
import certifi
from discord.ext import tasks

from models import Entry
from points import get_total_score, get_collated_scores

# Configure the logger
logger = logging.getLogger('discord.background')
logger.setLevel(logging.ERROR)

ssl_context = ssl.create_default_context(cafile=certifi.where())


@tasks.loop(count=1)
async def refresh_scores(rules, max_delay):
    """Background task to refresh all user scores periodically."""

    while True:
        next_refresh_time = datetime.utcnow() + max_delay / 12

        refresh_entries = rules.season.entries.filter(Entry.points_expiry < datetime.utcnow() + max_delay / 2)

        logger.info(f"Updating {refresh_entries.count()} entries.")

        for entry in refresh_entries:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                await rules.update(session)

                worked = False
                for _ in range(5):
                    if worked:
                        break

                    try:
                        score_groups, _ = await asyncio.gather(
                            get_collated_scores(session, rules, int(entry.character_id)),
                            asyncio.sleep(1))
                        user_score = get_total_score(score_groups)
                        worked = True
                    except (ValueError, AttributeError, TimeoutError, aiohttp.http_exceptions.BadHttpMessage):  # noqa
                        await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error
                        logger.warning(f"Updating character {entry.character_id} failed, retrying.")

            if worked:
                logger.debug(f"Entry {entry.character_id} updated to {user_score} points.")
                if rules.season.end < datetime.utcnow():
                    entry.points_expiry = datetime.utcnow() + max_delay
                else:
                    entry.points_expiry = datetime.utcnow() + max_delay + (datetime.utcnow() - rules.season.end)
                entry.points = user_score
                entry.save()
            else:
                logger.exception(f"Updating character {entry.character_id} failed!")

        await asyncio.sleep(max((next_refresh_time - datetime.utcnow()).total_seconds(), 0))
