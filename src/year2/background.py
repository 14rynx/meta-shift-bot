import asyncio
import logging
import ssl
from datetime import datetime

import aiohttp
import certifi
from aiohttp.abc import HTTPException
from discord.ext import tasks

from models import Entry
from points import get_total_score, get_collated_scores

# Configure the logger
logger = logging.getLogger('discord.background')
logger.setLevel(logging.INFO)

ssl_context = ssl.create_default_context(cafile=certifi.where())


@tasks.loop()
async def refresh_scores(rules, max_delay):
    """Background task to refresh all user scores periodically."""

    while True:
        refresh_window = datetime.utcnow() + max_delay / 2

        refresh_entries = rules.season.entries.filter(Entry.points_expiry < refresh_window)

        logger.info(f"Updating {refresh_entries.count()} entries.")

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            try:
                await rules.update(session)
            except HTTPException:
                await asyncio.sleep(60)
                continue

            for entry in refresh_entries:
                try:
                    score_groups, _ = await asyncio.gather(
                        get_collated_scores(session, rules, int(entry.character_id)),
                        asyncio.sleep(2))
                    user_score = get_total_score(score_groups)
                except (ValueError, AttributeError, TimeoutError, aiohttp.http_exceptions.BadHttpMessage):  # noqa
                    await asyncio.sleep(2)  # Make sure zkill rate limit is not hit because of the error
                    logger.warning(f"Updating character {entry.character_id} failed, skipping.", exc_info=True)
                    continue
                else:
                    logger.debug(f"Entry {entry.character_id} updated to {user_score} points.")

                    if rules.season.end > datetime.utcnow():
                        entry.points_expiry = datetime.utcnow() + max_delay
                    else:
                        entry.points_expiry = datetime.utcnow() + max_delay + (datetime.utcnow() - rules.season.end)

                    entry.points = user_score
                    entry.save()
                    await asyncio.sleep(2)

        next_refresh_time = datetime.utcnow() + max_delay / 12
        await asyncio.sleep(max((next_refresh_time - datetime.utcnow()).total_seconds(), 0))
