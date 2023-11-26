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
bot.remove_command('help')

rules = RulesConnector(1)

ssl_context = ssl.create_default_context(cafile=certifi.where())

try:
    os.mkdir("data")
except FileExistsError:
    pass


async def pass_trough(aid, session, rules, cid):
    return aid, cid, await get_total_score(session, rules, cid)


@bot.command()
async def help(ctx):
    await ctx.send(
        "\n".join([
            "# Functions:",
            "- `!link <character name or id>` to enter into the competition",
            "- `!unlink` to exit (no data is lost, you can reenter at any time)",
            "- `!points` to show your current standing",
            "- `!leaderboard` to see top 10",
            "- `!breakdown` to see your best kills",
            "- `!explain <zkill link>` to see how many point a kill is worth"
        ])
    )


@bot.command()
async def link(ctx, *args):
    try:
        author_id = str(ctx.author.id)
        character_name = " ".join(args)
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
async def leaderboard(ctx):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                await rules.update(session)
                tasks = [pass_trough(author, session, rules, character_id) for author, character_id in
                         linked_characters.items()]
                board = await asyncio.gather(*tasks)

                output = "# Leaderboard\n"
                count = 1
                for aid, cid, score in sorted(board, reverse=True, key=lambda x: x[2])[:30]:
                    output += f"{count}: <@{aid}> with {score:.1f} points\n"
                    count += 1

                await ctx.send(output, allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError:
        await ctx.send("Could not get all required responses from ESI / Zkill!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")


@bot.command()
async def breakdown(ctx, *args):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                if args:
                    author_id = await lookup(" ".join(args), 'characters')
                else:
                    author_id = str(ctx.author.id)
                character_id = linked_characters[author_id]
                await rules.update(session)

                ids_and_scores = await get_scores(session, rules, character_id)
                output = f"<@{author_id}>'s points distribution:\n"
                for kill_id, score in sorted(ids_and_scores.items(), key=lambda x: x[1], reverse=True)[0:30]:
                    output += f"[{score:.1f}](<https://zkillboard.com/kill/{kill_id}/>) "
                await ctx.send(output, allowed_mentions=discord.AllowedMentions(users=False))

    except ValueError:
        await ctx.send("Could not get all required responses from ESI / Zkill!")
    except _gdbm.error:
        await ctx.send("Currently busy with another command!")
    except KeyError:
        await ctx.send(f"You do not have any linked character!")


@bot.command()
async def explain(ctx, link):
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            await rules.update(session)

            kill_id = int(link.split("/")[-2])
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


asyncio.run(leaderboard(CtxDummy()))

bot.run(os.environ["TOKEN"])
