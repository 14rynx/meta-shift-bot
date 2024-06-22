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
logger.setLevel(logging.WARNING)

ssl_context = ssl.create_default_context(cafile=certifi.where())


@tasks.loop(count=1)
async def refresh_scores(rules, max_delay):
    """Background task to refresh all user scores periodically."""

    while True:
        refresh_interval = max_delay.total_seconds() / (rules.season.entries.count() + 1)

        for entry in rules.season.entries:
            if entry.points_expiry < datetime.utcnow():
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                    await rules.update(session)

                    try:
                        score_groups, _ = await asyncio.gather(
                            get_collated_kills(session, rules, int(entry.character_id)),
                            asyncio.sleep(1))
                        user_score = get_total_score(score_groups)
                    except (ValueError, AttributeError):
                        logger.error(f"Character {entry.character_id} failed!", exc_info=True)
                        await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error
                    except aiohttp.http_exceptions.BadHttpMessage as error_instance:
                        logger.error(f"Character {entry.character_id} will not be completed ever!")
                        raise error_instance
                    else:
                        logger.info(f"{entry.character_id} scored {user_score} points")
                        entry.points_expiry = datetime.utcnow() + max_delay
                        entry.points = user_score
                        entry.save()

            await asyncio.sleep(refresh_interval)

        # Wait again in case there are 0 entries
        await asyncio.sleep(refresh_interval)