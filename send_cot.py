"""Stream CoT markers to a TAK server with pytak.

Usage:
    cp config.ini.example config.ini   # then edit COT_URL to your server IP
    python send_cot.py

Plain TCP:  COT_URL = tcp://SERVER_IP:8087
TLS (cert): COT_URL = tls://SERVER_IP:8089   (+ cert paths in config.ini)
"""
import asyncio
from configparser import ConfigParser

import pytak
from cot import make_cot


class Sender(pytak.QueueWorker):
    """Emits a moving marker every few seconds. Reuse the same uid to move it."""

    async def run(self):
        # Nudge the position slightly each tick so you can see it move on the map.
        lat, lon = -27.4705, 153.0260  # Brisbane-ish; change to your venue
        step = 0
        while True:
            data = make_cot(
                uid="py-bridge-alpha-01",
                lat=lat + step * 0.0002,
                lon=lon + step * 0.0002,
                callsign="PYBRIDGE-01",
                remarks=f"hello from pytak, tick {step}",
                stale_seconds=60,
            )
            await self.put_queue(data)
            self._logger.info("sent CoT tick %d", step)
            step += 1
            await asyncio.sleep(5)


async def main():
    config = ConfigParser()
    config.read("config.ini")
    cfg = config["bridge"]

    clitool = pytak.CLITool(cfg)
    await clitool.setup()
    clitool.add_tasks({Sender(clitool.tx_queue, cfg)})
    await clitool.run()


if __name__ == "__main__":
    asyncio.run(main())
