"""Data coordinator for Pirkanmaan Jätehuolto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import random
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .api import BinEmptying, PirkkaApiClient, PirkkaApiError, PirkkaCannotConnect, PirkkaDataError, PirkkaInvalidAuth
from .const import (
    DEFAULT_JITTER_MINUTES,
    DEFAULT_MAX_REFRESH,
    DEFAULT_NO_DATE_REFRESH,
    DEFAULT_PAST_DATE_REFRESH,
    DEFAULT_POST_DATE_REFRESH_HOUR,
    DEFAULT_POST_DATE_REFRESH_MINUTE,
    DOMAIN,
    MAX_FAILURE_BACKOFF,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PirkkaCoordinatorData:
    """Coordinator payload for entities."""

    bins: dict[str, BinEmptying]
    error: str | None
    last_updated: datetime | None


class PirkkaDataUpdateCoordinator(DataUpdateCoordinator[PirkkaCoordinatorData]):
    """Coordinate API fetches and dynamic low-frequency scheduling."""

    def __init__(self, hass: HomeAssistant, api: PirkkaApiClient, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_NO_DATE_REFRESH,
            config_entry=entry,
        )
        self.api = api
        self._failure_count = 0

    async def _async_update_data(self) -> PirkkaCoordinatorData:
        """Fetch data and compute next update interval."""
        try:
            bins = await self.api.fetch_bins()
        except PirkkaInvalidAuth as err:
            _LOGGER.error("Autentikointi epäonnistui: %s", err)
            raise ConfigEntryAuthFailed from err
        except (PirkkaCannotConnect, PirkkaDataError, PirkkaApiError) as err:
            return self._handle_failure(str(err) or "Yhteysvirhe")
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Odottamaton virhe datan päivityksessä")
            return self._handle_failure(str(err) or "Odottamaton virhe")

        self._failure_count = 0
        bins_by_id = {bin_item.bin_id: bin_item for bin_item in bins}
        self.update_interval = self._compute_next_interval(bins_by_id)
        _LOGGER.debug(
            "Päivitys onnistui: %s astiaa, seuraava päivitys noin %s kuluttua",
            len(bins_by_id),
            self.update_interval,
        )
        return PirkkaCoordinatorData(
            bins=bins_by_id,
            error=None,
            last_updated=dt_util.utcnow(),
        )

    def _handle_failure(self, error_message: str) -> PirkkaCoordinatorData:
        """Handle temporary failures with backoff and cached data."""
        self._failure_count += 1

        next_backoff = min(
            timedelta(hours=2 * self._failure_count),
            MAX_FAILURE_BACKOFF,
        )

        _LOGGER.warning(
            "Päivitys epäonnistui (%s). Yritys #%s, seuraava yritys noin %s kuluttua.",
            error_message,
            self._failure_count,
            next_backoff,
        )

        if self.data is None:
            raise UpdateFailed(error_message)

        self.update_interval = next_backoff

        return PirkkaCoordinatorData(
            bins=self.data.bins,
            error=error_message,
            last_updated=self.data.last_updated,
        )

    def _compute_next_interval(self, bins: dict[str, BinEmptying]) -> timedelta:
        """Only refresh after the nearest known emptying date has passed."""
        now = dt_util.now()
        next_dates: list[date] = [
            bin_item.next_emptying
            for bin_item in bins.values()
            if bin_item.next_emptying is not None
        ]

        if not next_dates:
            base_interval = DEFAULT_NO_DATE_REFRESH
        else:
            earliest = min(next_dates)
            if earliest <= now.date():
                base_interval = DEFAULT_PAST_DATE_REFRESH
            else:
                refresh_at = datetime.combine(
                    earliest + timedelta(days=1),
                    time(
                        hour=DEFAULT_POST_DATE_REFRESH_HOUR,
                        minute=DEFAULT_POST_DATE_REFRESH_MINUTE,
                    ),
                    tzinfo=now.tzinfo,
                )
                delta = refresh_at - now
                if delta.total_seconds() <= 0:
                    base_interval = DEFAULT_PAST_DATE_REFRESH
                else:
                    base_interval = delta

        base_interval = min(base_interval, DEFAULT_MAX_REFRESH)

        jitter_minutes = random.randint(*DEFAULT_JITTER_MINUTES)
        return base_interval + timedelta(minutes=jitter_minutes)
