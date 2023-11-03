import json
import os
import shelve

import discord

from year2.rules import RulesConnector
from year2.points import get_score
from year2.utils import lookup

with open('../secrets.json', "r") as f:
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
    "- `!leaderboard` to see top 10"
])


@client.event
async def on_ready():
    try:
        os.mkdir("data")
    except FileExistsError:
        pass
    print(f'We have logged in as {client.user}')


@client.event
async def on_message(message):
    author_id = str(message.author.id)

    if message.author == client.user:  # It is our own message
        return

    if message.content.startswith("!help"):
        await message.channel.send(help_message)

    if message.content.startswith("!link"):
        character_name = " ".join(message.content.split(" ")[1:])
        character_id = lookup(character_name, 'characters')

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
            if author_id not in linked_characters:
                await message.channel.send(f"You do not have any linked character!")
            else:
                character_id = linked_characters[author_id]
                await message.channel.send(f"You currently have {await get_score(character_id)} points")

    if message.content.startswith("!leaderboard"):
        with shelve.open('data/linked_characters', writeback=True) as linked_characters:
            leaderboard = {}
            for author, character_id in linked_characters.items():
                leaderboard[author] = await get_score(character_id)

        output = "# Leaderboard\n"
        count = 1
        for author_id, points in sorted(leaderboard.items(), key=lambda x: x[1]):
            output += f"{count}: <@{author_id}> with {points} points\n"
            count += 1

        await message.channel.send(output)


client.run(TOKEN)
