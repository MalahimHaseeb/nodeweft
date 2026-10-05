import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import boto3

from common.errors import ServiceUnavailableError

from app.settings import ExecutionSettings

logger = logging.getLogger(__name__)

RunHandler = Callable[[str], Awaitable[None]]


class LocalRunQueue:
    def __init__(self, handler: RunHandler, worker_count: int):
        self._handler = handler
        self._worker_count = max(1, worker_count)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._work()) for _ in range(self._worker_count)]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def enqueue(self, run_id: str) -> None:
        try:
            self._queue.put_nowait(run_id)
        except asyncio.QueueFull:
            raise ServiceUnavailableError("The run queue is full, try again shortly") from None

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._handler(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker failed on run %s", run_id)
            finally:
                self._queue.task_done()


class SqsRunQueue:
    def __init__(self, handler: RunHandler, settings: ExecutionSettings):
        if not settings.sqs_queue_url:
            raise ValueError("SQS_QUEUE_URL is required when RUN_QUEUE_BACKEND=sqs")
        self._handler = handler
        self._settings = settings
        self._client = boto3.client("sqs", region_name=settings.aws_region)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def enqueue(self, run_id: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.send_message,
                QueueUrl=self._settings.sqs_queue_url,
                MessageBody=json.dumps({"run_id": run_id}),
            )
        except Exception:
            logger.exception("Could not send run %s to SQS", run_id)
            raise ServiceUnavailableError("Could not queue the run") from None

    async def _poll(self) -> None:
        visibility = self._settings.run_timeout_seconds + 60
        while True:
            try:
                response = await asyncio.to_thread(
                    self._client.receive_message,
                    QueueUrl=self._settings.sqs_queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                    VisibilityTimeout=visibility,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SQS receive failed")
                await asyncio.sleep(5)
                continue

            for message in response.get("Messages", []):
                try:
                    run_id = json.loads(message["Body"])["run_id"]
                    await self._handler(str(run_id))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Could not process SQS message")
                try:
                    await asyncio.to_thread(
                        self._client.delete_message,
                        QueueUrl=self._settings.sqs_queue_url,
                        ReceiptHandle=message["ReceiptHandle"],
                    )
                except Exception:
                    logger.exception("Could not delete SQS message")


def build_queue(settings: ExecutionSettings, handler: RunHandler):
    if settings.run_queue_backend == "sqs":
        return SqsRunQueue(handler, settings)
    return LocalRunQueue(handler, settings.local_worker_count)
