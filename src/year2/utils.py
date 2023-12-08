async def send_large_message(ctx, message, max_chars=2000, delimiter="\n", **kwargs):
    while len(message) > 0:
        # Check if the message content is shorter than the max_chars
        if len(message) <= max_chars:
            await ctx.send(message, **kwargs)
            break

        # Find the last delimiter character before max_chars
        last_newline_index = message.rfind(delimiter, 0, max_chars)

        # If there is no delimiter before max_chars, split at max_chars
        if last_newline_index == -1:
            await ctx.send(message[:max_chars], **kwargs)
            message = message[max_chars:]

        # Split at the last delimiter before max_chars
        else:
            await ctx.send(message[:last_newline_index], **kwargs)
            message = message[last_newline_index + 1:]
