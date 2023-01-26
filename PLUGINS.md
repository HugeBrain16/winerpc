# Enabling Plugins

in `config.json` file, edit the `plugins` list value to enable plugins  
for example if you have `greeter_status.py` plugin in `plugins` directory  
you can enable it by adding the plugin name without the `.py` in `plugins` list

```json
{
    ...
    "plugins": ["greeter_status"]
}
```

# Writing Your Own plugin

the plugin loader creates an asynchronous task for a coroutine called `_plugin_entry`  
`_plugin_entry` act as an entry point for the plugin

```py
async def _plugin_entry(ctx):
    # your code here
```

the `ctx` parameter is the `WineRPC` object that gets passed by the plugin loader

for plugin examples, check out [plugins](/plugins/) directory
