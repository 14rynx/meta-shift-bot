import asyncio
import logging
import ssl
from datetime import datetime

import aiohttp
import certifi
from discord.ext import tasks

from points import get_total_score, get_collated_kills

# Configure the logger
logger = logging.getLogger('discord.background')
logger.setLevel(logging.INFO)

ssl_context = ssl.create_default_context(cafile=certifi.where())


@tasks.loop(count=1)
async def refresh_scores(rules, max_delay):
    """Background task to refresh all user scores periodically."""

    while True:
        refresh_interval = max_delay.total_seconds() / (2 * rules.season.entries.count() + 1)

        for entry in rules.season.entries:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                await rules.update(session)

                worked = False
                for x in range(5):
                    try:
                        score_groups, _ = await asyncio.gather(
                            get_collated_kills(session, rules, int(entry.character_id)),
                            asyncio.sleep(1))
                        user_score = get_total_score(score_groups)
                        worked = True
                    except (ValueError, AttributeError, aiohttp.http_exceptions.BadHttpMessage):
                        await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error

                if worked:
                    logger.info(f"{entry.character_id} scored {user_score} points")
                    entry.points_expiry = datetime.utcnow() + max_delay
                    entry.points = user_score
                    entry.save()
                else:
                    logger.error(f"Character {entry.character_id} failed!")

            await asyncio.sleep(refresh_interval)

        # Wait again in case there are 0 entries
        await asyncio.sleep(refresh_interval)
