import json
from urllib.parse import urlparse, parse_qs

import discord

from docs import SpreadsheetConnector

with open('secrets.json', "r") as f:
    TOKEN = json.loads(f.read())["TOKEN"]

intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
client = discord.Client(intents=intent)


# Stolen from Stackoverflow: https://stackoverflow.com/a/7936523
def video_id(value: str) -> str:
    query = urlparse(value)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ('www.youtube.com', 'youtube.com'):
        if query.path == '/watch':
            p = parse_qs(query.query)
            return p['v'][0]
        if query.path[:7] == '/embed/':
            return query.path.split('/')[2]
        if query.path[:3] == '/v/':
            return query.path.split('/')[2]
    raise ValueError


@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')


@client.event
async def on_message(message):
    if message.author == client.user:  # It is our own message
        return

    if message.channel.id not in [1079429447368847391, 1081618378688561203, 1080949544356941874,
                                  1084968028837531648] and message.channel.type.name != "private":
        return

    try:
        if "help" in message.content:
            await message.author.send(f"To add into the competition, write a message like this:\n"
                                      "<video_url> <category (1/2/3)> <further notes>")
    except discord.errors.Forbidden:
        print(f"Could not PM {message.author.id}")

    try:
        link, category_str, *note_words = message.content.split(" ")
        category = int(category_str)

        videoid = video_id(link)
        cleaned_url = f"https://www.youtube.com/watch?v={videoid}"
    except ValueError:
        pass
    else:
        try:
            spreadsheet_connector = SpreadsheetConnector()

            note = " ".join(note_words)
            target_entry_id = f"{message.author.id}-{category}"
            operation = spreadsheet_connector.add_update(1, target_entry_id,
                                                         [message.author.name, cleaned_url, category, note])

            if message.channel.type.name != "private":
                try:
                    await message.delete()
                except discord.errors.Forbidden:
                    print(f"Could not delete a message in channel {message.channel.id}")
                try:
                    await message.channel.send(
                        f"{message.author.mention} your entry into the Meta Shift Video competition has been accepted. Thank you!")
                except discord.errors.Forbidden:
                    print(f"Could not write a message in channel {message.channel.id}")
            try:
                if operation == "added":
                    await message.author.send(
                        f"Personal confirmation that your video {cleaned_url} has been entered into the Meta Shift Competition under category {category}.")
                else:
                    await message.author.send(
                        f"Your video entry for category {category} in the Meta Shift Competition has been updated to {cleaned_url}.")
            except discord.errors.Forbidden:
                print(f"Could not PM {message.author.id}")
        except Exception as e:
            user = client.get_user(242164531151765505)  # Larynx
            await user.send(f"fThere was an unexpected Error:\n {e}")


client.run(TOKEN)
