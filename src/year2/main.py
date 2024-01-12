import _gdbm
import asyncio
import logging
import os
import shelve
import ssl
from datetime import datetime, timedelta

import aiohttp
import certifi
import discord
from discord.ext import commands

from network import lookup, get_hash, get_character_name
from points import get_total_score, get_collated_kills, get_kill_score
from rules import RulesConnector
from utils import send_large_message

# Configure the logger
logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Setting up discord
intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
client = discord.Client(intents=intent)

bot = commands.Bot(command_prefix='!', intents=intent)
rules = RulesConnector(1)

# Adding ssl context because aiohttp doesn't come with certificates
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Initialize high level cache
score_cache = []
score_cache_last_updated = None
score_cache_size = None


@bot.command()
async def link(ctx, *character_name):
    """Links your character to take part in the competition."""
    logger.info(f"{ctx.author.name} used !link {character_name}")

    author_id = str(ctx.author.id)
    character_name = " ".join(character_name)
    try:
        character_id = await lookup(character_name, 'characters')
    except ValueError:
        await ctx.send(f"Could not resolve that character!")
        return

    try:
        with shelve.open('data/relinks', writeback=True) as relinks:
            if author_id not in relinks:
                relinks[author_id] = 5
                author_relinks = 5
            else:
                if author_id not in os.environ["PRIVILEGED_USERS"].split(" "):
                    author_relinks = relinks[author_id] - 1
                    if author_relinks > 0:
                        relinks[author_id] = author_relinks
                    else:
                        await ctx.send("You ran out of relinks!")
                        return
                else:
                    author_relinks = "Infinite"

        with shelve.open('data/linked_characters', writeback=True) as linked_characters:
            if author_id not in linked_characters:
                linked_characters[author_id] = character_id
                await ctx.send(f"Linked [{character_name}](https://zkillboard.com/character/{character_id}/)")
            else:
                linked_characters[author_id] = character_id
                await ctx.send(f"Updated your linked character to "
                               f"[{character_name}](https://zkillboard.com/character/{character_id}/) "
                               f"({author_relinks} uses remaining)")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
        return


@bot.command()
async def unlink(ctx):
    """Unlinks your character from the competition."""
    logger.info(f"{ctx.author.name} used !unlink")

    author_id = str(ctx.author.id)
    try:
        with shelve.open('data/linked_characters', writeback=True) as linked_characters:
            del linked_characters[author_id]
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
    except KeyError:
        await ctx.send(f"You do not have any linked character!")
    else:
        await ctx.send(f"Unlinked your character.")


async def get_user_scores(session, rules, ctx):
    global score_cache
    global score_cache_last_updated
    global score_cache_size

    # Find out how many users are registered
    with shelve.open('data/linked_characters', writeback=True) as lc:
        amount = len(lc.items()) - 1

        # Update cache if new users have been added, cache is more than 1h old or has never been fetched
        if (score_cache_last_updated is None
                or score_cache_last_updated < datetime.utcnow() - timedelta(hours=1)
                or score_cache_size < amount):

            users_done = []
            user_scores = []
            await ctx.send(f"Refetching ranking, this will take approximately {amount} seconds.")

            while len(users_done) < amount:
                for author, character_id in lc.items():
                    if character_id not in users_done:
                        try:
                            user_score, _ = await asyncio.gather(get_total_score(session, rules, character_id),
                                                                 asyncio.sleep(1))
                            logger.debug(f"Character {character_id} was completed.")
                        except (ValueError, AttributeError):
                            await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error
                        except aiohttp.http_exceptions.BadHttpMessage:
                            amount -= 1
                            logger.error(f"Character {character_id} will not be completed ever.")
                        else:
                            users_done.append(character_id)
                            user_scores.append([author, character_id, user_score])

                logger.info(f"Completion {len(users_done)}/{len(lc.items())}")
                await asyncio.sleep(1)

            score_cache = user_scores
            score_cache_last_updated = datetime.utcnow()
            score_cache_size = amount
    return score_cache


@bot.command()
async def leaderboard(ctx, top=None):
    """Shows the current people with the most points."""

    logger.info(f"{ctx.author.name} used !leaderboard")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            user_scores = await get_user_scores(session, rules, ctx)

            if top is None:
                top = 10
            elif top == "all" and str(ctx.author.id) in os.environ["PRIVILEGED_USERS"].split(" "):
                top = len(user_scores)

            output = "# Leaderboard\n"
            for count, (aid, cid, score) in enumerate(sorted(user_scores, reverse=True, key=lambda x: x[2])[:top]):
                output += (
                    f"{count + 1}: <@{aid}> [{await get_character_name(session, cid)}]"
                    f"(<https://zkillboard.com/character/{cid}/>) with {score:.1f} points\n"
                )

            await send_large_message(ctx, output, delimiter="\n", allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))


@bot.command()
async def ranking(ctx):
    """Shows the people around your current score."""

    logger.info(f"{ctx.author.name} used !ranking")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            # Get data
            user_scores = await get_user_scores(session, rules, ctx)
            users_leaderboard = sorted(user_scores, reverse=True, key=lambda x: x[2])
            author_ids = [aid for aid, _, _ in users_leaderboard]

            # Calculate which entries to show
            middle = author_ids.index(str(ctx.author.id))
            first = max(middle - 2, 0)
            last = min(middle + 3, len(users_leaderboard))

            # Build output
            output = "# Leaderboard\n (around your position)\n"
            count = first + 1
            for aid, cid, score in sorted(user_scores, reverse=True, key=lambda x: x[2])[first:last]:
                output += (f"{count}: <@{aid}> [{await get_character_name(session, cid)}](<https://zkillboard.com/"
                           f"character/{cid}/>) with {score:.1f} points\n")
                count += 1

            await ctx.send(output, allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))


async def parse_character(author_id: str, character_name_array: tuple):
    """Given a discord id and an input character, find a suitable character id and possesive form"""
    if len(character_name_array) > 0:
        character_name = " ".join(character_name_array)
        character_id = await lookup(character_name, 'characters')
        possesive = f"[{character_name}](https://zkillboard.com/character/{character_id}/) currently has"
    else:
        if author_id is not None:
            try:
                with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                    character_id = linked_characters[author_id]
                possesive = "You currently have"
            except KeyError:
                raise ValueError("You do not have any linked character!")
            except _gdbm.error:
                raise ValueError("Currently busy with another command!")
        else:
            return None, None

    return character_id, possesive


@bot.command()
async def points(ctx, *character_name):
    """Shows the total points someone achieved, defaults to your linked character."""

    logger.info(f"{ctx.author.name} used !points")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)
            character_id, predicate = await parse_character(str(ctx.author.id), character_name)
            await ctx.send(f"{predicate} {await get_total_score(session, rules, character_id)} points")

    except ValueError as instance:
        await ctx.send(str(instance))


@bot.command()
async def breakdown(ctx, *character_name):
    """Shows a breakdown of how someone achieved their points, defaults to your linked character."""

    logger.info(f"{ctx.author.name} used !breakdown")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)
            character_id, predicate = await parse_character(str(ctx.author.id), character_name)
            output = f"{predicate} the point distribution:\n"

            point_strings = []
            groups = await get_collated_kills(session, rules, character_id)
            for total_score, kills in sorted(groups, reverse=True)[0:30]:
                if len(kills) == 1:
                    point_string = f"[**{total_score:.1f}**](<https://zkillboard.com/kill/{kills[0][0]}/>)"
                else:
                    point_string = f"**{total_score:.1f}** ("
                    links = [f"[{s:.1f}](<https://zkillboard.com/kill/{i}/>)" for i, s in kills]
                    point_string += ", ".join(links)
                    point_string += ")"
                point_strings.append(point_string)
            output += ", ".join(point_strings)

            if len(point_strings) == 0:
                output += "- no points for this character so far."
            await send_large_message(ctx, output, delimiter=",", allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))


def parse_kill_id(zkill_link: str) -> int:
    # TODO: Add more variants of parsing a link.
    try:
        kill_id = int(zkill_link.split("/")[-2])
    except IndexError:
        raise ValueError(f"Invalid zkill_link: {zkill_link}")

    return kill_id


@bot.command()
async def explain(ctx, zkill_link, *character_name):
    """Shows the total amount of points for some kill."""

    logger.info(f"{ctx.author.name} used !explain")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)
            kill_id = parse_kill_id(zkill_link)
            kill_hash = await get_hash(session, kill_id)
            character_id, _ = await parse_character(None, character_name)
            kill_id, kill_time, kill_score, time_bracket = await get_kill_score(session, kill_id, kill_hash, rules,
                                                                                main_character_id=character_id)
            if character_id is not None:
                await ctx.channel.send(f"This [kill](https://zkillboard.com/kill/{kill_id}/) is worth {kill_score:.1f} "
                                       f"with the given character, and will chain for {time_bracket.total_seconds():.1f} seconds.")
            else:
                await ctx.channel.send(f"This [kill](https://zkillboard.com/kill/{kill_id}/) is worth {kill_score:.1f} "
                                       f"points when using the largest ship as the ship of the contestant, "
                                       f"and will chain for {time_bracket.total_seconds():.1f} seconds.")

    except ValueError as instance:
        await ctx.send(str(instance))


bot.run(os.environ["TOKEN"])
