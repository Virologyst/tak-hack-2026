"""Template: bridge an EXTERNAL data source into TAK as CoT.

This is the pattern that wins most TAK hackathons: take some feed the judges
care about (sensors, an API, ADS-B/AIS, ML detections, alerts) and turn each
item into a CoT marker on everyone's map.

Replace `fetch_items()` with your real source. Everything else stays.
"""
import asyncio
from configparser import ConfigParser

import pytak
from cot import make_cot


async def fetch_items():
    """STUB: return a list of things to plot. Swap for your real feed.

    Each item is a dict the bridge turns into a CoT marker.
    e.g. call an HTTP API, read a serial GPS, poll a database, run a model...
    """
    return [
        {"id": "sensor-01", "lat": -27.4705, "lon": 153.0260,
         "type": "a-u-G", "label": "Unknown contact", "note": "detected 0.82 conf"},
        {"id": "sensor-02", "lat": -27.4750, "lon": 153.0300,
         "type": "a-f-G-U-C", "label": "Friendly unit", "note": "on patrol"},
    ]


class FeedBridge(pytak.QueueWorker):
    async def run(self):
        while True:
            for item in await fetch_items():
                data = make_cot(
                    uid=item["id"],
                    lat=item["lat"],
                    lon=item["lon"],
                    cot_type=item.get("type", "a-u-G"),
                    callsign=item.get("label", item["id"]),
                    remarks=item.get("note", ""),
                    stale_seconds=120,
                )
                await self.put_queue(data)
            self._logger.info("published feed batch")
            await asyncio.sleep(10)  # poll interval


async def main():
    config = ConfigParser()
    config.read("config.ini")
    cfg = config["bridge"]

    clitool = pytak.CLITool(cfg)
    await clitool.setup()
    clitool.add_tasks({FeedBridge(clitool.tx_queue, cfg)})
    await clitool.run()


if __name__ == "__main__":
    asyncio.run(main())
