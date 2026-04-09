"""Docker container lifecycle management for headless RimWorld benchmarks."""

from __future__ import annotations

import asyncio
import logging
from subprocess import DEVNULL
from types import TracebackType

import httpx

logger = logging.getLogger(__name__)

CONTAINER_NAME = "rle-benchmark"
DEFAULT_IMAGE = "rle-headless:latest"
DEFAULT_PORT = 8765
HEALTH_TIMEOUT = 120.0
HEALTH_INTERVAL = 5.0


async def _probe_rimapi(url: str, timeout: float = 5.0) -> bool:
    """Check if RIMAPI is responsive at the given URL."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/api/v1/game/state", timeout=timeout)
            return resp.status_code < 500
    except (httpx.HTTPError, OSError):
        return False


async def wait_for_rimapi(url: str, timeout: float = HEALTH_TIMEOUT) -> None:
    """Poll RIMAPI until responsive. Shared by Docker and manual setups.

    Raises TimeoutError if RIMAPI doesn't respond within *timeout* seconds.
    """
    elapsed = 0.0
    while elapsed < timeout:
        if await _probe_rimapi(url):
            logger.info("RIMAPI responsive at %s", url)
            return
        await asyncio.sleep(HEALTH_INTERVAL)
        elapsed += HEALTH_INTERVAL
    msg = f"RIMAPI not responsive at {url} after {timeout}s"
    raise TimeoutError(msg)


async def _run(
    *args: str,
    check: bool = True,
) -> None:
    """Run a Docker CLI command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        err = stderr.decode().strip() if stderr else "unknown error"
        msg = f"docker {' '.join(args)} failed: {err}"
        raise RuntimeError(msg)


class DockerGameServer:
    """Manages HeadlessRim Docker container for automated benchmarks."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        port: int = DEFAULT_PORT,
        container_name: str = CONTAINER_NAME,
    ) -> None:
        self._image = image
        self._port = port
        self._container_name = container_name

    @property
    def url(self) -> str:
        """RIMAPI base URL for this container."""
        return f"http://localhost:{self._port}"

    async def start(self) -> None:
        """Start container and wait for RIMAPI healthcheck."""
        logger.info("Starting %s from image %s", self._container_name, self._image)
        await _run(
            "run", "-d",
            "-p", f"{self._port}:8765",
            "--name", self._container_name,
            "--shm-size=1g",
            self._image,
        )
        await wait_for_rimapi(self.url)

    async def stop(self) -> None:
        """Stop and remove container. Ignores errors if already stopped."""
        logger.info("Stopping %s", self._container_name)
        await _run("stop", self._container_name, check=False)
        await _run("rm", self._container_name, check=False)

    async def restart(self) -> None:
        """Restart for clean game state between scenarios."""
        logger.info("Restarting %s", self._container_name)
        await _run("restart", self._container_name)
        await wait_for_rimapi(self.url)

    async def is_healthy(self) -> bool:
        """Check if RIMAPI is responsive."""
        return await _probe_rimapi(self.url)

    async def __aenter__(self) -> DockerGameServer:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()
