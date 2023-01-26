"""A plugin that will set your RPC status to Hello World!"""


async def _plugin_entry(ctx):
    is_set = False

    while is_set is False:
        if ctx.state.process:

            # anything related to pypresence must use lock
            async with ctx.lock:
                await ctx.rpc.clear()
                await ctx._update(ctx.state.process, "Hello World!")

                is_set = True
