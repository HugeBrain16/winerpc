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

you can also define `_plugin_exit` as a function or coroutine, which will be executed when the plugin has finished executing  
The callback function or coroutine takes only one argument (you can name the parameter `task` or whatever you like), which is the task that initiates the plugin's execution

for plugin examples, check out [plugins](/plugins/) directory
