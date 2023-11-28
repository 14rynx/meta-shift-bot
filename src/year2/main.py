import _gdbm
import asyncio
import os
import shelve
import ssl

import aiohttp
import certifi
import discord
from discord.ext import commands

from points import get_total_score, get_scores, get_kill_score
from rules import RulesConnector
from utils import lookup, get_hash

intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
client = discord.Client(intents=intent)

bot = commands.Bot(command_prefix='!', intents=intent)
rules = RulesConnector(1)

ssl_context = ssl.create_default_context(cafile=certifi.where())

try:
    os.mkdir("data")
except FileExistsError:
    pass


async def pass_trough(aid, session, rules, cid):
    return aid, cid, await get_total_score(session, rules, cid)


@bot.command()
async def link(ctx, *character_name):
    """Links your character to take part in the competition."""
    try:
        author_id = str(ctx.author.id)
        character_name = " ".join(character_name)
        character_id = await lookup(character_name, 'characters')

        with shelve.open('data/linked_characters', writeback=True) as linked_characters:
            if author_id not in linked_characters:
                linked_characters[author_id] = character_id
                await ctx.send(f"Linked [{character_name}](https://zkillboard.com/character/{character_id}/)")
            else:
                linked_characters[author_id] = character_id
                await ctx.send(
                    f"Updated your linked character to [{character_name}](https://zkillboard.com/character/{character_id}/)")
    except ValueError:
        await ctx.send(f"Could not resolve that character!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def unlink(ctx):
    """Unlinks your character from the competition."""
    try:
        with shelve.open('data/linked_characters', writeback=True) as linked_characters:

            author_id = str(ctx.author.id)
            del linked_characters[author_id]
            await ctx.send(f"Unlinked your character.")

    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
    except KeyError:
        await ctx.send(f"You do not have any linked character!")


@bot.command()
async def points(ctx):
    """Shows your current point total."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                author_id = str(ctx.author.id)
                await rules.update(session)
                character_id = linked_characters[author_id]
                await ctx.send(f"You currently have {await get_total_score(session, rules, character_id)} points")

    except ValueError:
        await ctx.send("Could not get all required responses from ESI / Zkill!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
    except KeyError:
        await ctx.send(f"You do not have any linked character!")


@bot.command()
async def leaderboard(ctx, top=None):
    """Shows the current people with the most points."""
    if top is None:
        top = 10

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                await rules.update(session)
                tasks = [pass_trough(author, session, rules, character_id) for author, character_id in
                         linked_characters.items()]
                board = await asyncio.gather(*tasks)

                output = "# Leaderboard\n"
                count = 1
                for aid, cid, score in sorted(board, reverse=True, key=lambda x: x[2])[:top]:
                    output += f"{count}: <@{aid}> with {score:.1f} points\n"
                    count += 1

                await ctx.send(output, allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError:
        await ctx.send("Could not get all required responses from ESI / Zkill!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def breakdown(ctx, *character_name):
    """Shows a breakdown of how you achieved your points."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                if character_name:
                    character_name = " ".join(character_name)
                    character_id = await lookup(character_name, 'characters')
                    output = (f"[{character_name}](https://zkillboard.com/character/{character_id}/)"
                              f"'s points distribution:\n")
                else:
                    author_id = str(ctx.author.id)
                    output = f"<@{author_id}>'s points distribution:\n"

                    character_id = linked_characters[author_id]
                await rules.update(session)

                point_strings = []
                groups = await get_scores(session, rules, character_id)
                for kill_id, scores in sorted(groups.items(), key=lambda group: sum(group[1]), reverse=True)[0:30]:
                    point_string = f"[**{sum(scores):.1f}**](<https://zkillboard.com/kill/{kill_id}/>)"
                    if len(scores) > 1:
                        summary = " + ".join([f"{s:.1f}" for s in scores])
                        point_string += f" ({summary})"
                    point_strings.append(point_string)
                output += ",   ".join(point_strings)
                await ctx.send(output, allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError:
        await ctx.send("Could not get all required responses from ESI / Zkill!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
    except KeyError:
        await ctx.send(f"You do not have any linked character!")


@bot.command()
async def explain(ctx, zkill_link):
    """Shows the total amount of points for some kill."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            kill_id = int(zkill_link.split("/")[-2])
            kill_hash = await get_hash(session, kill_id)
            kill_id, kill_time, kill_score, time_bracket = await get_kill_score(session, kill_id, kill_hash, rules)
            await ctx.channel.send(
                f"This [kill](https://zkillboard.com/kill/{kill_id}/) is worth {kill_score:.1f} points\n"
                f" when using the largest ship as the ship of the contestant.")

    except ValueError:
        await ctx.channel.send("Could not get all required responses from ESI / Zkill!")
    except IndexError:
        await ctx.send("Could not parse that link!")


# Run leaderboard command once to prefetch cache
class CtxDummy(object):
    async def send(self, text, **kwargs):
        return


if "SEED" in os.environ:
    asyncio.run(leaderboard(CtxDummy()))

bot.run(os.environ["TOKEN"])
