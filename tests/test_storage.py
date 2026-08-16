# tests/test_storage.py
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from powersite_autonomy.models import SiteCalibration
from powersite_autonomy.storage import Storage


def test_calibration_round_trip(tmp_path: Path) -> None:
    async def run() -> None:
        storage = Storage(str(tmp_path / "autonomy.db"))
        await storage.initialize()
        calibration = SiteCalibration(
            site_uid="sys_default",
            generated_at=datetime.now(UTC),
            history_days=30,
            hourly_load_profile_w=[100.0] * 24,
            hourly_load_sigma_w=[12.0] * 24,
            weekday_load_multiplier=[1.0] * 7,
        )
        await storage.save_calibration(calibration)
        loaded = await storage.latest_calibration("sys_default")
        assert loaded is not None
        assert loaded.history_days == 30

    asyncio.run(run())
