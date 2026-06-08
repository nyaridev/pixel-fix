from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-region"
webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

try:
    from .pixel_fix import (
        IMAGE_EXTENSIONS,
        PixelFixCancelled,
        discover_images,
        fix_image,
    )
except ImportError:
    from pixel_fix import (
        IMAGE_EXTENSIONS,
        PixelFixCancelled,
        discover_images,
        fix_image,
    )


APP_NAME = "Pixel Fix"
APP_VERSION = "1.0.0"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"
WINDOW_SIZE = 720


class PixelFixApi:
    def __init__(self, show_custom_title_bar: bool) -> None:
        self._window: webview.Window | None = None
        self._show_custom_title_bar = show_custom_title_bar
        self._images: list[Path] = []
        self._base_directory: Path | None = None
        self._worker_queue: queue.Queue[tuple] = queue.Queue()
        self._worker_running = False
        self._cancel_event: threading.Event | None = None
        self._completed_images = 0
        self._changed_images = 0
        self._failed_images = 0
        self._cancelled_images = 0
        self._max_threads = max(1, os.cpu_count() or 1)
        self._default_threads = max(1, int(self._max_threads * 0.9))
        self._drop_handler: DOMEventHandler | None = None

    def _bind_window(self, window: webview.Window) -> None:
        self._window = window

    def _register_drop_handler(self) -> None:
        if self._window is None:
            return

        try:
            self._drop_handler = DOMEventHandler(self._handle_dom_drop, True, True)
            self._window.dom.document.events.drop += self._drop_handler
        except Exception:
            # Some webview backends may not expose DOM events. The JS fallback still
            # works when the engine provides absolute file paths directly.
            self._drop_handler = None

    def _handle_dom_drop(self, event: dict[str, Any]) -> None:
        if self._window is None:
            return

        paths = self._extract_drop_paths(event)
        if not paths:
            self._window.evaluate_js(
                "window.pixelFixHandleDropResolutionFailed && "
                "window.pixelFixHandleDropResolutionFailed();"
            )
            return

        self._window.evaluate_js(
            f"window.pixelFixHandlePythonDrop({json.dumps(paths)});"
        )

    def _extract_drop_paths(self, event: dict[str, Any]) -> list[str]:
        transfer = event.get("dataTransfer") or event.get("domTransfer") or {}
        files = transfer.get("files") or []
        paths: list[str] = []

        for file_info in files:
            if not isinstance(file_info, dict):
                continue

            path = (
                file_info.get("pywebviewFullPath")
                or file_info.get("path")
                or file_info.get("fullPath")
            )
            if path:
                paths.append(str(path))

        return paths

    def get_initial_state(self) -> dict[str, Any]:
        return {
            "appTitle": APP_TITLE,
            "version": APP_VERSION,
            "showCustomTitleBar": self._show_custom_title_bar,
            "maxThreads": self._max_threads,
            "defaultThreads": self._default_threads,
            "directory": "",
            "recursive": False,
            "images": [],
            "status": "Select a folder to begin.",
            "running": False,
            "progress": self._progress_state(),
        }

    def choose_directory(self, recursive: bool) -> dict[str, Any]:
        if self._window is None:
            return self._error_state("Window is not ready.")

        selection = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not selection:
            return self._state("Directory selection cancelled.")

        return self.scan_directory(str(selection[0]), recursive)

    def scan_directory(self, directory: str, recursive: bool) -> dict[str, Any]:
        if self._worker_running:
            return self._error_state("Wait for the current task to finish first.")

        path = Path(directory)
        self._base_directory = path
        self._images = discover_images(path, recursive)
        status = (
            "Ready."
            if self._images
            else "No supported images found in the selected location."
        )
        return self._state(status)

    def load_dropped_paths(
        self, dropped_paths: list[str], recursive: bool
    ) -> dict[str, Any]:
        if self._worker_running:
            return self._error_state("Wait for the current task to finish first.")

        paths = [Path(path) for path in dropped_paths if path]
        directories = [path for path in paths if path.is_dir()]
        files = [
            path
            for path in paths
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]

        if directories:
            return self.scan_directory(str(directories[0]), recursive)

        if files:
            self._base_directory = None
            self._images = sorted(files, key=lambda path: str(path).lower())
            return self._state("Ready.")

        return self._error_state(
            "Dropped paths were not readable. Use Browse if this keeps happening."
        )

    def clear_images(self) -> dict[str, Any]:
        if self._worker_running:
            return self._error_state("Wait for the current task to finish first.")

        self._base_directory = None
        self._images = []
        self._completed_images = 0
        self._changed_images = 0
        self._failed_images = 0
        self._cancelled_images = 0
        self._drain_worker_queue()
        return self._state("Imported images cleared.")

    def start(self, thread_count: int) -> dict[str, Any]:
        if self._worker_running:
            return self._error_state("Already running.")

        if not self._images:
            return self._error_state("No images are loaded.")

        thread_count = min(max(1, int(thread_count)), len(self._images))
        self._worker_running = True
        self._cancel_event = threading.Event()
        self._completed_images = 0
        self._changed_images = 0
        self._failed_images = 0
        self._cancelled_images = 0
        self._drain_worker_queue()

        coordinator = threading.Thread(
            target=self._run_workers,
            args=(tuple(self._images), thread_count, self._cancel_event),
            daemon=True,
        )
        coordinator.start()

        return self._state(
            f"Fixing {len(self._images)} image(s) with {thread_count} thread(s)..."
        )

    def cancel(self) -> dict[str, Any]:
        if not self._worker_running or self._cancel_event is None:
            return self._state("No task is running.")

        self._cancel_event.set()
        return self._state("Cancelling current task...")

    def poll(self) -> dict[str, Any]:
        latest_status: str | None = None
        done_event: tuple | None = None

        while True:
            try:
                event = self._worker_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "progress":
                _, result = event
                self._completed_images += 1
                if result.changed:
                    self._changed_images += 1
                latest_status = f"{result.message}: {result.path.name}"
            elif event_type == "error":
                _, path, message = event
                self._completed_images += 1
                self._failed_images += 1
                latest_status = f"Failed: {Path(path).name} ({message})"
            elif event_type == "cancelled_image":
                _, path = event
                self._cancelled_images += 1
                latest_status = f"Cancelled while processing {Path(path).name}"
            elif event_type == "done":
                done_event = event

        if done_event is not None:
            _, cancelled = done_event
            self._worker_running = False
            if cancelled:
                latest_status = (
                    "Cancelled. "
                    f"Completed {self._completed_images}/{len(self._images)} image(s), "
                    f"updated {self._changed_images}, failed {self._failed_images}."
                )
            else:
                latest_status = (
                    f"Done. Updated {self._changed_images} of {len(self._images)} image(s); "
                    f"{self._failed_images} failed."
                )

        if latest_status is None and self._worker_running:
            latest_status = (
                f"{self._completed_images}/{len(self._images)} complete - processing..."
            )

        return self._state(latest_status)

    def minimize(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def _run_workers(
        self,
        images: tuple[Path, ...],
        thread_count: int,
        cancel_event: threading.Event,
    ) -> None:
        pending_images: queue.Queue[Path] = queue.Queue()
        for path in images:
            pending_images.put(path)

        workers = [
            threading.Thread(
                target=self._image_worker,
                args=(pending_images, cancel_event),
                daemon=True,
            )
            for _ in range(thread_count)
        ]

        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self._worker_queue.put(("done", cancel_event.is_set()))

    def _image_worker(
        self,
        pending_images: queue.Queue[Path],
        cancel_event: threading.Event,
    ) -> None:
        while not cancel_event.is_set():
            try:
                path = pending_images.get_nowait()
            except queue.Empty:
                return

            try:
                result = fix_image(path, cancel_event=cancel_event)
                self._worker_queue.put(("progress", result))
            except PixelFixCancelled:
                self._worker_queue.put(("cancelled_image", path))
                return
            except Exception as exc:
                self._worker_queue.put(("error", path, str(exc)))
            finally:
                pending_images.task_done()

    def _state(self, status: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "appTitle": APP_TITLE,
            "version": APP_VERSION,
            "showCustomTitleBar": self._show_custom_title_bar,
            "directory": str(self._base_directory) if self._base_directory else "",
            "images": [self._image_item(path) for path in self._images],
            "imageCount": len(self._images),
            "running": self._worker_running,
            "status": status or "Ready.",
            "progress": self._progress_state(),
        }

    def _error_state(self, message: str) -> dict[str, Any]:
        state = self._state(message)
        state["ok"] = False
        return state

    def _progress_state(self) -> dict[str, int]:
        total = len(self._images)
        return {
            "completed": self._completed_images,
            "total": total,
            "changed": self._changed_images,
            "failed": self._failed_images,
            "cancelled": self._cancelled_images,
        }

    def _image_item(self, path: Path) -> dict[str, str]:
        return {"path": str(path), "display": self._display_path(path)}

    def _display_path(self, path: Path) -> str:
        if self._base_directory is None:
            return str(path)

        try:
            return str(path.relative_to(self._base_directory))
        except ValueError:
            return str(path)

    def _drain_worker_queue(self) -> None:
        while True:
            try:
                self._worker_queue.get_nowait()
            except queue.Empty:
                return


def gui_index_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "gui" / "index.html"

    return Path(__file__).resolve().parent / "gui" / "index.html"


def create_webview_window(
    show_custom_title_bar: bool,
) -> tuple[webview.Window, PixelFixApi]:
    api = PixelFixApi(show_custom_title_bar)
    window = webview.create_window(
        APP_TITLE,
        url=gui_index_path().as_uri(),
        js_api=api,
        width=WINDOW_SIZE,
        height=WINDOW_SIZE,
        min_size=(560, 560),
        resizable=True,
        frameless=show_custom_title_bar,
        easy_drag=False,
    )
    api._bind_window(window)
    return window, api


def register_drop_handler(api: PixelFixApi) -> None:
    api._register_drop_handler()


def main() -> None:
    try:
        _window, api = create_webview_window(show_custom_title_bar=True)
    except TypeError:
        _window, api = create_webview_window(show_custom_title_bar=False)

    webview.start(register_drop_handler, [api], debug=False)


if __name__ == "__main__":
    main()
