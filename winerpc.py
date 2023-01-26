#!/usr/bin/python3
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import binary2strings as b2s
import psutil
from pypresence import AioPresence

__version__ = "1.0.0-rc3"

# needs these wine processes,
# to check if wineserver is running
WINEPROCS = [
    "start.exe",
    "wineserver",
    "explorer.exe",
]


def log(cat: str, msg: str):
    print(f"[{cat}]: {msg}")


@dataclass
class App:
    exe: str | List[str]
    title: str
    icon: Optional[str] = None


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

        with open(self.server, "rb") as file:
            for string, _, _, _ in b2s.extract_all_strings(file.read(), min_chars=4):
                version = re.match(r"^Wine\s\d+\.\d+", string)

                if version:
                    return version.string


class AppDB:
    def __init__(self, fname: str | os.PathLike):
        with open(fname, "r") as file:
            self._apps = json.load(file)
        self.apps: List[App] = []

        for app in self._apps:
            self.apps.append(
                App([exe.lower() for exe in app["exe"]], app["title"], app.get("icon"))
            )
        log("INFO", f"Loaded {len(self.apps)} apps from database.")

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

        self.state = State()
        self.apps = AppDB(self.config["app_list_path"])

    async def _update(self, app: App, state: Optional[str] = None):
        self.state.process = app

        await self.rpc.update(
            details=f"Playing {app.title}",
            start=time.time(),
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

    async def _event(self):
        while True:
            await asyncio.sleep(15)

    def get_process_basename(self, process: psutil.Process) -> str:
        proc = os.path.basename(process.exe().replace("\\", os.sep))

        if proc in ("wine-preloader", "wine64-preloader") and process.cmdline():
            proc = os.path.basename(process.cmdline()[0].replace("\\", os.sep))

        return proc

    async def _scan(self):
        apps: List[App] = []

        for proc in self.process_iter():
            try:
                exe = self.get_process_basename(proc).lower()
                app = self.apps.get(exe)

                if app and not self.apps._get(exe, apps):
                    apps.append(app)
            except psutil.AccessDenied:
                continue

        if apps:
            if self.state.mode is not StateMode.RUNNING:
                self.state.mode = StateMode.RUNNING
                log("INFO", "New process is running: " + apps[0].title)

                await self._update(apps[0])
            else:
                if self.state.process is not apps[0]:
                    log("INFO", "Process updated to: " + apps[0].title)

                    await self.rpc.clear()
                    await self._update(apps[0])
        else:
            if self.state.mode is StateMode.RUNNING:
                log("INFO", "Process stopped: " + self.state.process.title)
                self.state.process = None
                self.state.mode = StateMode.SCANNING

                await self.rpc.clear()

    async def _watcher(self):
        while True:
            procs = []
            for proc in self.process_iter():
                try:
                    exe = self.get_process_basename(proc)

                    if exe in WINEPROCS and exe not in procs:
                        if exe == "wineserver" and not self.state.server:
                            self.state.server = proc.exe()
                        procs.append(exe)
                except psutil.AccessDenied:
                    continue

            if len(procs) < len(WINEPROCS):
                if self.state.mode is StateMode.RUNNING:
                    await self.rpc.clear()

                if self.state.mode is not StateMode.INACTIVE:
                    self.state.process = None
                    self.state.mode = StateMode.INACTIVE
                    self.state.server = None
                    log("INFO", "Watcher is in INACTIVE state.")
            else:
                if self.state.mode not in [StateMode.SCANNING, StateMode.RUNNING]:
                    self.state.mode = StateMode.SCANNING
                    log(
                        "INFO",
                        "Watcher is in SCANNING state, scanning for running apps...",
                    )

                await self._scan()

            await asyncio.sleep(1)

    async def _start(self):
        log("INFO", "Connecting to Discord RPC Socket...")
        try:
            await self.rpc.connect()
        except ConnectionRefusedError:
            log(
                "ERROR",
                "Couldn't connect to Discord RPC Socket.",
            )
            sys.exit(1)
        log("INFO", "Starting watcher task...")
        self.loop.create_task(self._watcher())
        await self._event()

    def start(self):
        self.loop.run_until_complete(self._start())


if __name__ == "__main__":
    with open("config.json", "r", encoding="UTF-8") as conf:
        winerpc = WineRPC(json.load(conf))
        winerpc.start()
