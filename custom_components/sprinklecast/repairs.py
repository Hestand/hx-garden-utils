"""Repair flows for leftover Smart Water files."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import LEGACY_DOMAIN
from .legacy import (
    ISSUE_FOLDER,
    ISSUE_LOADED,
    async_import_smart_water,
    legacy_folder,
    remove_legacy_folder,
)

_FIXABLE = frozenset({ISSUE_FOLDER, ISSUE_LOADED})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Offer to delete a leftover Smart Water folder."""
    if issue_id in _FIXABLE:
        return RemoveSmartWaterFolderFlow()
    from homeassistant.components.repairs import ConfirmRepairFlow

    return ConfirmRepairFlow()


class RemoveSmartWaterFolderFlow(RepairsFlow):
    """Delete ``custom_components/smart_water`` and ask for a restart."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        """Open the confirm step. The manager passes the issue id here."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Delete the old folder. A loaded component still needs a restart."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
            )
        await self.hass.async_add_executor_job(remove_legacy_folder, self.hass)
        folder = legacy_folder(self.hass)
        if folder.exists() or folder.is_symlink():
            return self.async_abort(reason="delete_failed")
        if LEGACY_DOMAIN in self.hass.config.components:
            return self.async_abort(reason="restart_required")
        await async_import_smart_water(self.hass)
        return self.async_create_entry(
            data={},
            description=(
                "The Smart Water folder was removed. Restart Home Assistant "
                "so nothing from that folder stays loaded."
            ),
        )
