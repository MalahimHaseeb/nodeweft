import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from common.templating import TemplateError, render_value

from app.engine.errors import NodeError

HEADER_NAME = re.compile(r"^[A-Za-z0-9\-]{1,64}$")


def render_for_item(value: Any, context: dict) -> Any:
    try:
        return render_value(value, context)
    except TemplateError as error:
        raise NodeError(f"Template problem: {error}") from None


async def map_bounded(function: Callable[[Any], Awaitable[Any]], items: list, limit: int) -> list:
    semaphore = asyncio.Semaphore(max(1, limit))

    async def guarded(item: Any) -> Any:
        async with semaphore:
            return await function(item)

    tasks = [asyncio.create_task(guarded(item)) for item in items]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        raise


def get_field(item: dict, path: str) -> tuple[bool, Any]:
    current: Any = item
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            return False, None
    return True, current
