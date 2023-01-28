"""An example plugin"""


async def _plugin_entry(ctx):
    print("Greeter plugin loaded. Hello there!")


def _plugin_exit(task):
    print("Bye!")
