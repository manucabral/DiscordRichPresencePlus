"""
Module responsible for managing all Rich Presence Plus system.
"""

import os
import sys
import typing
import importlib.util
import threading
import concurrent.futures
import time
from .constants import Constants
from .logger import get_logger, RPPLogger
from .presence import Presence
from .runtime import Runtime


class Manager:
    """
    Manager class for Rich Presence Plus.
    """

    def __init__(
        self,
        presences_folder: str = Constants.PRESENCES_FOLDER,
        runtime=None,
        runtime_interval=Constants.RUNTIME_INTERVAL,
        dev_mode=Constants.DEV_MODE,
    ):
        self.log: RPPLogger = get_logger("Manager")
        self.dev_mode: bool = dev_mode
        self.web_enabled: bool = False
        self.folder: str = presences_folder
        self.runtime: Runtime = runtime
        self.runtime_interval: int = runtime_interval
        self.presence_interval: int = Constants.PRESENCE_INTERVAL
        self.executor: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=Constants.MAX_PRESENCES)
        )
        self.stop_event: threading.Event = threading.Event()
        self.presences: typing.List[Presence] = []

        self.check_folder(presences_folder)

    def check_folder(self, folder: str) -> None:
        """
        Check if the folder exists, if not, create it.
        """
        if not os.path.exists(folder):
            os.makedirs(folder)

    def load(self) -> None:
        """
        Load all presences from the presences folder.
        """
        root_path = os.path.abspath(self.folder)
        if root_path not in sys.path:
            sys.path.append(root_path)
        for root, _, files in os.walk(self.folder):
            for file in files:
                if file.startswith("__"):
                    continue
                if file == "main.py":
                    self.load_presence(root, file)

    def load_presence(self, root: str, file: str) -> None:
        """
        Load a presence from a file.
        """
        self.log.info(f"Loading presence from {root}")
        module_name = file[:-3]
        relative_path = os.path.relpath(root, self.folder)
        module_path = os.path.join(relative_path, module_name).replace(os.sep, ".")
        try:
            spec = importlib.util.find_spec(module_path)
            if spec is None:
                raise ImportError(f"Module {module_path} not found")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            """
            if self.checkRestrictedModules(module):
                return
            """
            for attr in dir(module):
                obj = getattr(module, attr)
                if (
                    isinstance(obj, type)
                    and obj is not Presence
                    and issubclass(obj, Presence)
                ):
                    instance = obj()
                    instance.path = root
                    instance.set_dev_mode(self.dev_mode)
                    if instance.web:
                        self.web_enabled = True
                    if instance.enabled:
                        self.presences.append(instance)
        except Exception as exc:
            self.log.error(f"Error loading {module_path}: {exc}")
            return

    def stop_presences(self) -> None:
        """
        Stop all presences.
        """
        for presence in self.presences:
            presence.on_close()

    def __presence_thread(self, presence: Presence) -> None:
        """
        Run the presence in a thread.
        """
        if presence.web and not self.runtime.connected:
            self.log.warning(
                f"{presence.name} uses web features but runtime is not connected"
            )
        while not self.stop_event.is_set():
            time.sleep(presence.update_interval)
            presence.on_update(runtime=self.runtime)

    def __runtime_thread(self) -> None:
        """
        Run the runtime in a thread.
        """
        self.log.info(f"Starting runtime thread with interval {self.runtimeInterval}")
        while not self.stop_event.is_set():
            time.sleep(self.runtime_interval)
            try:
                self.runtime.update()
            except Exception:
                self.log.warning("Failed to update runtime")

    def __main_thread(self) -> None:
        """
        Run the main thread.
        """
        while not self.stop_event.is_set():
            time.sleep(self.presence_interval)
            for presence in self.presences:
                presence.update()
        self.stop_presences()

    def run_presences(self) -> None:
        """
        Run all presences.
        """
        for presence in self.presences:
            presence.on_load()
            self.executor.submit(self.__presence_thread, presence)
        self.executor.submit(self.__main_thread)
        self.log.info("Presences started.")

    def start(self) -> None:
        """
        Start all presences.
        """
        if not self.presences:
            self.log.error("No presences loaded.")
            return

        try:
            self.run_presences()
            if self.runtime.connected and self.web_enabled:
                self.executor.submit(self.__runtime_thread)
            while not self.stop_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.log.info("Stopping presences...")
            self.stop_event.set()
        finally:
            self.executor.shutdown(wait=True)
            self.stop_presences()
            self.log.info("Presences stopped.")
