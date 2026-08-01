"""Sensor platform for Pirkanmaan Jätehuolto."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BinEmptying
from .const import DOMAIN
from .coordinator import PirkkaCoordinatorData, PirkkaDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class PirkkaSensorEntityDescription(SensorEntityDescription):
    """Describe a Pirkka sensor entity."""


ERROR_SENSOR = PirkkaSensorEntityDescription(
    key="error",
    name="Error",
    icon="mdi:alert-circle-outline",
    entity_category=EntityCategory.DIAGNOSTIC,
)

LAST_UPDATED_SENSOR = PirkkaSensorEntityDescription(
    key="last_updated",
    name="Last updated",
    icon="mdi:clock-check-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from config entry."""
    coordinator: PirkkaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        PirkkaErrorSensor(coordinator, entry.entry_id),
        PirkkaLastUpdatedSensor(coordinator, entry.entry_id),
    ]
    entities.extend(
        PirkkaBinSensor(coordinator, entry.entry_id, bin_id)
        for bin_id in sorted(coordinator.data.bins)
    )

    async_add_entities(entities)


class PirkkaErrorSensor(CoordinatorEntity[PirkkaDataUpdateCoordinator], SensorEntity):
    """Diagnostic sensor for integration health."""

    entity_description = ERROR_SENSOR
    _attr_should_poll = False

    def __init__(self, coordinator: PirkkaDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize error sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_error"

    @property
    def native_value(self) -> str | None:
        """Return current integration error status."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.error


class PirkkaLastUpdatedSensor(CoordinatorEntity[PirkkaDataUpdateCoordinator], SensorEntity):
    """Diagnostic sensor for last successful update timestamp."""

    entity_description = LAST_UPDATED_SENSOR
    _attr_should_poll = False

    def __init__(self, coordinator: PirkkaDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize last updated sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_last_updated"

    @property
    def native_value(self) -> datetime | None:
        """Return last successful fetch timestamp."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.last_updated


class PirkkaBinSensor(CoordinatorEntity[PirkkaDataUpdateCoordinator], SensorEntity):
    """Represents one garbage bin with its next emptying date."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:trash-can-outline"

    def __init__(self, coordinator: PirkkaDataUpdateCoordinator, entry_id: str, bin_id: str) -> None:
        """Initialize bin sensor."""
        super().__init__(coordinator)
        self._bin_id = bin_id
        self._attr_unique_id = f"{entry_id}_{bin_id}"

    @property
    def _bin(self) -> BinEmptying | None:
        """Return backing bin data from coordinator."""
        payload: PirkkaCoordinatorData | None = self.coordinator.data
        if payload is None:
            return None
        return payload.bins.get(self._bin_id)

    @property
    def name(self) -> str | None:
        """Return entity name."""
        bin_item = self._bin
        if bin_item is None:
            return None
        return bin_item.name

    @property
    def available(self) -> bool:
        """Return availability."""
        return self._bin is not None

    @property
    def native_value(self):
        """Return next emptying date."""
        bin_item = self._bin
        if bin_item is None:
            return None
        return bin_item.next_emptying

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return optional attributes."""
        bin_item = self._bin
        if bin_item is None:
            return {}
        return {
            "astia_id": bin_item.bin_id,
        }
