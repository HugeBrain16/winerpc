#!/usr/bin/python3
import asyncio
import importlib
import importlib.util
import inspect
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import psutil
from pypresence import AioPresence

__version__ = "1.0.0-dev8"
logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.DEBUG)


@dataclass
class App:
    exe: str | List[str]
    title: str
    icon: Optional[str] = None
    pid: Optional[int] = None
    start_time: Optional[float] = None


class StateMode(Enum):
    INACTIVE = 0
    SCANNING = 1  # Scan for running wine program listed in appdb
    RUNNING = 2


@dataclass
class State:
    process: Optional[App] = None
    mode: StateMode = StateMode.INACTIVE
    server: Optional[str] = None

    def get_server_version(self) -> Optional[str]:
        """get running wine server version"""
        if not self.server:
            return

        for string in io.StringIO(
            subprocess.check_output(["strings", self.server]).decode()
        ).readlines():
            version = re.match(r"^Wine\s\d+\.\d+", string)

            if version:
                return version.string.strip()


class AppDB:
    def __init__(self, fname: str | os.PathLike):
        with open(fname, "r") as file:
            self._apps = json.load(file)
        self.apps: List[App] = []

        for app in self._apps:
            self.apps.append(
                App([exe.lower() for exe in app["exe"]], app["title"], app.get("icon"))
            )
        logging.info(f"Loaded {len(self.apps)} apps from database.")

    @staticmethod
    def _get(exe: str, apps: List[App]) -> Optional[App]:
        for app in apps:
            if exe in [e.lower() for e in app.exe]:
                return app

    def get(self, exe: str) -> Optional[App]:
        return self._get(exe, self.apps)


class WineRPC:
    def __init__(self, config: dict):
        self.rpc = AioPresence(config["app_id"])
        self.loop = asyncio.new_event_loop()
        self.rpc.loop = self.loop
        self.config = config
        self.lock = asyncio.Lock()

        self.state = State()
        self.apps = AppDB(self.config["app_list_path"])

    @staticmethod
    def load_plugin(name: str):
        if os.path.isfile(os.path.join("plugins", f"{name}.py")):
            spec = importlib.util.spec_from_file_location(
                name, os.path.join("plugins", f"{name}.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            if hasattr(mod, "_plugin_entry"):
                if inspect.iscoroutinefunction(getattr(mod, "_plugin_entry")):
                    return mod

    async def _update(self, app: App, state: Optional[str] = None):
        self.state.process = app

        await self.rpc.update(
            details=f"Playing {app.title}",
            start=app.start_time if app.start_time else time.time(),
            small_image="https://static.wikia.nocookie.net/logopedia/images/8/87/Wine_2008.png",
            small_text=self.state.get_server_version(),
            state=state,
            large_image=app.icon,
            large_text=app.title,
        )

    def process_iter(self, reverse: bool = True):
        """Iterates process from new to old"""
        return sorted(
            psutil.process_iter(), key=lambda p: p.create_time(), reverse=reverse
        )

    def get_process_basename(self, process: psutil.Process) -> str:
        proc = os.path.basename(process.exe().replace("\\", os.sep))

        if proc in ("wine-preloader", "wine64-preloader") and process.cmdline():
            proc = os.path.basename(process.cmdline()[0].replace("\\", os.sep))

        return proc

    async def _scan(self):
        while self.state.mode in [StateMode.SCANNING, StateMode.RUNNING]:
            apps: List[App] = []

            for proc in self.process_iter():
                try:
                    exe = self.get_process_basename(proc).lower()
                    app = self.apps.get(exe)

                    if app and not self.apps._get(exe, apps):
                        app.pid = proc.pid
                        app.start_time = proc.create_time()
                        apps.append(app)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue

            if apps:
                if self.state.mode is not StateMode.RUNNING:
                    self.state.mode = StateMode.RUNNING
                    logging.info("New process is running: " + apps[0].title)

                    async with self.lock:
                        await self._update(apps[0])
                elif self.state.process is not apps[0]:
                    logging.info("Process updated to: " + apps[0].title)

                    async with self.lock:
                        await self.rpc.clear()
                        await self._update(apps[0])
            elif self.state.mode is StateMode.RUNNING:
                logging.info("Process stopped: " + self.state.process.title)
                self.state.process = None
                self.state.server = None
                self.state.mode = StateMode.INACTIVE

                async with self.lock:
                    await self.rpc.clear()

            await asyncio.sleep(1)

    async def _watcher(self):
        while True:
            for proc in self.process_iter():
                try:
                    exe = self.get_process_basename(proc)

                    if exe == "wineserver" and not self.state.server:
                        self.state.server = proc.exe()
                        logging.debug(
                            f"Using wineserver: {self.state.get_server_version()}"
                        )
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue

            if self.state.server:
                if self.state.mode is not StateMode.SCANNING:
                    self.state.mode = StateMode.SCANNING
                    logging.debug(
                        "Watcher is in SCANNING state, scanning for running apps..."
                    )

                await self._scan()
            else:
                if self.state.mode is StateMode.RUNNING:
                    async with self.lock:
                        await self.rpc.clear()

                if self.state.mode is not StateMode.INACTIVE:
                    self.state.process = None
                    self.state.mode = StateMode.INACTIVE
                    self.state.server = None
                    logging.debug("Watcher is in INACTIVE state.")

            await asyncio.sleep(1)

    async def _start(self):
        logging.info("Connecting to Discord RPC Socket...")
        try:
            await self.rpc.connect()
        except ConnectionRefusedError:
            logging.error("Couldn't connect to Discord RPC Socket.")
            sys.exit(1)
        logging.info("Starting watcher task...")
        self.loop.create_task(self._watcher())
        for plugin in self.config["plugins"]:
            plug = self.load_plugin(plugin)

            if plug:
                logging.info("Loading plugin: " + plugin)
                task = self.loop.create_task(plug._plugin_entry(self))
                on_exit = getattr(plug, "_plugin_exit", None)

                if on_exit and callable(on_exit):
                    task.add_done_callback(on_exit)
            else:
                logging.warning("Plugin Not Found: " + plugin)

        await self._watcher()

    def start(self):
        self.loop.run_until_complete(self._start())


if __name__ == "__main__":
    with open("config.json", "r", encoding="UTF-8") as conf:
        winerpc = WineRPC(json.load(conf))
        winerpc.start()
