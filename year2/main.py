import asyncio
import json
import os
import shelve
import ssl

import aiohttp
import certifi
import discord

from points import get_total_score, get_scores
from rules import RulesConnector
from utils import lookup

with open('secrets.json', "r") as f:
    TOKEN = json.loads(f.read())["TOKEN"]

intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
client = discord.Client(intents=intent)

help_message = "\n".join([
    "# Functions:",
    "- `!link <character name or id>` to enter into the competition",
    "- `!unlink` to exit (no data is lost, you can reenter at any time)",
    "- `!points` to show your current standing",
    "- `!leaderboard` to see top 10",
    "- `!breakdown` to see your best kills"
])

rules = RulesConnector(1)


@client.event
async def on_ready():
    try:
        os.mkdir("data")
    except FileExistsError:
        pass

    print(f'We have logged in as {client.user}')


@client.event
async def on_message(message):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        author_id = str(message.author.id)

        if message.author == client.user:  # It is our own message
            return

        if message.content.startswith("!help"):
            await message.channel.send(help_message)

        if message.content.startswith("!link"):
            character_name = " ".join(message.content.split(" ")[1:])
            try:
                character_id = await lookup(character_name, 'characters')
            except ValueError:
                await message.channel.send(f"Could not resolve that character!")
                return

            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                if author_id not in linked_characters:
                    linked_characters[author_id] = character_id
                    await message.channel.send(f"Linked https://zkillboard.com/character/{character_id}/")
                else:
                    linked_characters[author_id] = character_id
                    await message.channel.send(
                        f"Updated your linked character to https://zkillboard.com/character/{character_id}/")

        if message.content.startswith("!unlink"):
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                if author_id not in linked_characters:
                    await message.channel.send(f"You were not linked in the first place!")
                else:
                    del linked_characters[author_id]
                    await message.channel.send(f"Unlinked your character.")

        if message.content.startswith("!points"):
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                await rules.update(session)

                if author_id not in linked_characters:
                    await message.channel.send(f"You do not have any linked character!")
                else:
                    character_id = linked_characters[author_id]
                    await message.channel.send(
                        f"You currently have {await get_total_score(session, rules, character_id)} points")

        if message.content.startswith("!leaderboard"):
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                await rules.update(session)

                async def pass_trough(aid, session, rules, cid):
                    return aid, await get_total_score(session, rules, cid)

                tasks = [pass_trough(author, session, rules, character_id) for author, character_id in
                         linked_characters.items()]
                leaderboard = {author: score for author, score in await asyncio.gather(*tasks)}

            output = "# Leaderboard\n"
            count = 1
            for author_id, points in sorted(leaderboard.items(), reverse=True, key=lambda x: x[1])[:30]:
                output += f"{count}: <@{author_id}> with {points} points\n"
                count += 1

            await message.channel.send(
                output,
                allowed_mentions=discord.AllowedMentions(roles=False, everyone=False, users=False)
            )

        if message.content.startswith("!breakdown"):
            with shelve.open('data/linked_characters', writeback=True) as linked_characters:
                if author_id not in linked_characters:
                    await message.channel.send(f"You do not have any linked character!")
                else:
                    character_id = linked_characters[author_id]
                    await rules.update(session)
                    ids_and_scores = await get_scores(session, rules, character_id)

                    output = "# Your current best kills\n"
                    for kill_id, score in sorted(ids_and_scores.items(), key=lambda x: x[1], reverse=True)[0:30]:
                        output += f"{score:.3f} https://zkillboard.com/kill/{kill_id}/\n"
                    await message.channel.send(output)


client.run(TOKEN)
