# tools/tool_runtime.py
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 300.0
_tool_loop = None
_tool_loop_lock = threading.Lock()
_worker_thread_local = threading.local()


def get_tool_timeout_seconds() -> float:
    return _DEFAULT_TIMEOUT_SECONDS


def _get_tool_loop():
    global _tool_loop
    with _tool_loop_lock:
        if _tool_loop is None or _tool_loop.is_closed():
            _tool_loop = asyncio.new_event_loop()
        return _tool_loop


def _get_worker_loop():
    loop = getattr(_worker_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _worker_thread_local.loop = loop
    return loop


def run_async(coro, timeout: float | None = None):
    timeout = get_tool_timeout_seconds() if timeout is None else timeout
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        worker_loop = None
        loop_ready = threading.Event()

        def _run_in_worker():
            nonlocal worker_loop
            worker_loop = asyncio.new_event_loop()
            loop_ready.set()
            try:
                asyncio.set_event_loop(worker_loop)
                return worker_loop.run_until_complete(coro)
            finally:
                pending = asyncio.all_tasks(worker_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    worker_loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                worker_loop.close()

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_run_in_worker)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if loop_ready.wait(timeout=1.0) and worker_loop is not None:
                for task in asyncio.all_tasks(worker_loop):
                    worker_loop.call_soon_threadsafe(task.cancel)
            raise
        finally:
            pool.shutdown(wait=False)

    if threading.current_thread() is not threading.main_thread():
        return _get_worker_loop().run_until_complete(coro)

    return _get_tool_loop().run_until_complete(coro)


def run_handler(entry: Any, args: dict, kwargs: dict | None = None, *, timeout: float | None = None) -> str:
    kwargs = kwargs or {}
    if entry.is_async:
        return run_async(entry.handler(args, **kwargs), timeout=timeout)
    return entry.handler(args, **kwargs)
