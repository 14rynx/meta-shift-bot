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

from background import refresh_scores
from models import initialize_database, User, Season, Entry
from network import lookup, get_hash, get_character_name
from points import get_total_score, get_collated_kills, get_kill_score
from rules import RulesConnector
from utils import send_large_message

# Configure the logger
logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)

# Setting up discord
intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
client = discord.Client(intents=intent)
bot = commands.Bot(command_prefix='!', intents=intent)

# Initialize Database
initialize_database()

# Get current season
current_season = Season.get(name="Season 2")
rules = RulesConnector(current_season)

# Adding ssl context because aiohttp doesn't come with certificates
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Setup constants
max_delay = timedelta(hours=1)


async def update_scores_now(session, rules):
    for entry in current_season.entries:
        if entry.points_expiry < datetime.utcnow():
            try:
                score_groups, _ = await asyncio.gather(get_collated_kills(session, rules, int(entry.character_id)),
                                                       asyncio.sleep(1))
                user_score = get_total_score(score_groups)
            except (ValueError, AttributeError):
                await asyncio.sleep(1)  # Make sure zkill rate limit is not hit because of the error
            except aiohttp.http_exceptions.BadHttpMessage as error_instance:
                logger.error(f"Character {entry.character_id} will not be completed ever!")
                raise error_instance
            else:
                logger.info(f"{entry.character_id} scored {user_score} points")
                logger.debug(f"Character {entry.character_id} was completed.")
                entry.points_expiry = datetime.utcnow() + max_delay
                entry.points = user_score
                entry.save()


async def find_character_id(author_id: str, character_name_array: tuple):
    """Given a Discord ID and an input character, find a suitable character ID and possessive form.
    prefer the name given before fetching one via the discord user"""
    if len(character_name_array) > 0:
        character_name = " ".join(character_name_array)
        try:
            character_id = await lookup(character_name, 'characters')
        except ValueError:
            raise ValueError("Could not resolve that character!")
        possesive = f"[{character_name}](https://zkillboard.com/character/{character_id}/) currently has"

    else:
        if author_id is not None:
            try:
                user = User.get(user_id=author_id)
                entry = Entry.get(user=user, season=current_season)
                character_id = entry.character_id
                possesive = "You currently have"
            except (User.DoesNotExist, Entry.DoesNotExist):
                raise ValueError("You do not have any linked character!")
        else:
            return None, None

    return character_id, possesive


def find_kill_id(zkill_link: str) -> int:
    # TODO: Add more variants of parsing a link.
    try:
        kill_id = int(zkill_link.split("/")[-2])
    except IndexError:
        raise ValueError(f"Invalid zkill_link: {zkill_link}")

    return kill_id


@bot.event
async def on_ready():
    refresh_scores.start(rules, current_season, max_delay)


@bot.command()
async def link(ctx, *character_name):
    """Links your character to take part in the competition."""
    logger.info(f"{ctx.author.name} used !link {character_name}")

    # Figure out the character
    character_name = " ".join(character_name)
    try:
        character_id = await lookup(character_name, 'characters')
    except ValueError:
        await ctx.send(f"Could not resolve that character!")
        return

    user, _ = User.get_or_create(user_id=str(ctx.author.id))

    entry, created = Entry.get_or_create(character_id=character_id, user=user, season=current_season,
                                         defaults={"relinks": 5, "points": 0, "points_expiry": datetime.utcnow()})

    if created:
        await ctx.send(f"Linked [{character_name}](https://zkillboard.com/character/{character_id}/)")
    else:
        if entry.relinks > 0 or str(ctx.author.ids) in os.environ["PRIVILEGED_USERS"].split(" "):
            entry.relinks -= 1
            entry.character_id = character_id
            entry.save()
            await ctx.send(f"Updated your linked character to "
                           f"[{character_name}](https://zkillboard.com/character/{character_id}/) "
                           f"({entry.relinks} uses remaining)")
        else:
            await ctx.send("You ran out of relinks!")


@bot.command()
async def unlink(ctx):
    """Unlinks your character from the competition."""
    logger.info(f"{ctx.author.name} used !unlink")

    user, _ = User.get_or_create(id=str(ctx.author.id))

    try:
        entry = Entry.get(character_id=user.character_id, user=user, season=current_season)
    except Entry.DoesNotExist:  # noqa
        await ctx.send("You do not have any linked character for this season!")
        return

    entry.delete_instance()
    await ctx.send(f"Unlinked your character.")


@bot.command()
async def leaderboard(ctx, top=None):
    """Shows the current people with the most points."""

    try:
        # Log
        logger.info(f"{ctx.author.name} used !leaderboard {top}")

        # Execute command
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            # Get data
            await rules.update(session)
            await update_scores_now(session, rules)

            # Parse length of data to show
            if top is None:
                top = 10
            elif top in ["all", "csv"] and str(ctx.author.id) in os.environ["PRIVILEGED_USERS"].split(" "):
                top = current_season.entries.count()

            # Build output
            output = "# Leaderboard\n"
            for count, entry in enumerate(current_season.entries.order_by(Entry.points.desc()).limit(top)):
                if top == "csv":
                    output += (
                        f"{count + 1}, {(bot.get_user(entry.user.user_id)).name}, "
                        f"{await get_character_name(session, entry.character_id)}, {entry.points:.1f}"
                    )
                else:
                    output += (
                        f"{count + 1}: <@{entry.user.user_id}> [{await get_character_name(session, entry.character_id)}]"
                        f"(<https://zkillboard.com/character/{entry.character_id}/>) with {entry.points:.1f} points\n"
                    )

            # Send message
            await send_large_message(ctx, output, delimiter="\n", allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))
    except Exception as exception_instance:
        await ctx.send("Unknown error. Try again and ping Larynx if it keeps happening.")
        raise exception_instance


@bot.command()
async def ranking(ctx):
    """Shows the people around your current score."""

    try:
        # Log
        logger.info(f"{ctx.author.name} used !ranking")

        # Execute command
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            # Get data
            await rules.update(session)
            await update_scores_now(session, rules)

            # Fetch user scores from the database
            user_entries = current_season.entries.order_by(Entry.points.desc())
            users_leaderboard = [(entry.user.user_id, entry.character_id, entry.points) for entry in user_entries]
            author_ids = [entry[0] for entry in users_leaderboard]

            # Calculate which entries to show
            middle = author_ids.index(str(ctx.author.id))
            first = max(middle - 2, 0)
            last = min(middle + 3, len(users_leaderboard))

            # Build output
            output = "# Leaderboard\n (around your position)\n"
            count = first + 1
            for aid, cid, score in users_leaderboard[first:last]:
                output += (
                    f"{count}: <@{aid}> [{await get_character_name(session, cid)}]"
                    f"(<https://zkillboard.com/character/{cid}/>) with {score:.1f} points\n"
                )
                count += 1

            # Send message
            await send_large_message(ctx, output, delimiter="\n", allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))
    except Exception as exception_instance:
        await ctx.send("Unknown error. Try again and ping Larynx if it keeps happening.")
        raise exception_instance


@bot.command()
async def points(ctx, *character_name):
    """Shows the total points someone achieved, defaults to your linked character."""

    try:
        # Parse arguments and log
        character_id, predicate = await find_character_id(str(ctx.author.id), character_name)
        logger.info(f"{ctx.author.name} used !points {character_id}")

        # Execute command
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)
            score_groups = await get_collated_kills(session, rules, character_id)
            await ctx.send(f"{predicate} {get_total_score(score_groups)} points")

    except ValueError as instance:
        await ctx.send(str(instance))
    except Exception as exception_instance:
        await ctx.send("Unknown error. Try again and ping Larynx if it keeps happening.")
        raise exception_instance


@bot.command()
async def breakdown(ctx, *character_name):
    """Shows a breakdown of how someone achieved their points, defaults to your linked character."""

    try:
        # Parse arguments and log
        character_id, predicate = await find_character_id(str(ctx.author.id), character_name)
        logger.info(f"{ctx.author.name} used !breakdown {character_id}")

        # Execute command
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            # Get data
            groups = await get_collated_kills(session, rules, character_id)

            # Build output
            output = f"{predicate} {get_total_score(groups)} points with the following distribution:\n"
            point_strings = []
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

            # Send message
            await send_large_message(ctx, output, delimiter=",", allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError as instance:
        await ctx.send(str(instance))
    except Exception as exception_instance:
        await ctx.send("Unknown error. Try again and ping Larynx if it keeps happening.")
        raise exception_instance


@bot.command()
async def explain(ctx, zkill_link, *character_name):
    """Shows the total amount of points for some kill."""

    try:
        # Parse arguments and log
        kill_id = find_kill_id(zkill_link)
        character_id, _ = await find_character_id(None, character_name)
        logger.info(f"{ctx.author.name} used !explain {kill_id} {character_id}")

        # Execute command
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)
            kill_hash = await get_hash(session, kill_id)
            kill_id, kill_time, kill_score, time_bracket = await get_kill_score(session, kill_id, kill_hash, rules,
                                                                                main_character_id=character_id)
            if character_id is not None:
                explain_style = "when using the largest ship as the ship of the contestant"
            else:
                explain_style = "with the given character"

            await ctx.channel.send(f"This [kill](https://zkillboard.com/kill/{kill_id}/) is worth {kill_score:.1f} "
                                   f"{explain_style}, and will chain for {time_bracket.total_seconds():.1f} seconds.")

    except ValueError as instance:
        await ctx.send(str(instance))
    except Exception as exception_instance:
        await ctx.send("Unknown error. Try again and ping Larynx if it keeps happening.")
        raise exception_instance


bot.run(os.environ["TOKEN"])
