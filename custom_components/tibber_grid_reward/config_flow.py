import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.httpx_client import get_async_client
import homeassistant.helpers.config_validation as cv

from .client import TibberAPI, TibberAuthError, TibberConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class TibberGridRewardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self.data = {}
        self.homes = {}
        self.flex_devices = {}
        self.validation_task: asyncio.Task | None = None 

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input["username"])
            self._abort_if_unique_id_configured()

            self.data["username"] = user_input["username"]
            self.data["password"] = user_input["password"]
            
            try:
                _LOGGER.debug("Attempting to fetch homes.")
                client = get_async_client(self.hass)
                api = TibberAPI(self.data["username"], self.data["password"], client)
                homes_data = await api.get_homes()
                _LOGGER.debug("Successfully fetched homes.")

                if not homes_data:
                    _LOGGER.warning("No homes found on Tibber account.")
                    return self.async_abort(reason="no_homes")

                self.homes = {home["id"]: home["title"] for home in homes_data}
                return await self.async_step_select_home()

            except TibberAuthError:
                _LOGGER.warning("Authentication failed.")
                errors["base"] = "auth"
            except TibberConnectionError:
                _LOGGER.error("Connection error while fetching homes.")
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected exception in user step")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("username"): str, vol.Required("password"): str}),
            errors=errors,
        )

    async def async_step_select_home(self, user_input=None):
        if user_input is not None:
            self.data["home_id"] = user_input["home_id"]
            _LOGGER.debug("Home selected: %s", self.data['home_id'])
            return await self.async_step_validate_grid_reward()

        return self.async_show_form(
            step_id="select_home",
            data_schema=vol.Schema({vol.Required("home_id"): vol.In(self.homes)}),
        )

    async def async_step_validate_grid_reward(self, user_input=None):
        if self.validation_task is None:
            _LOGGER.debug("Creating validation task")
            self.validation_task = self.hass.async_create_task(self._validate_grid_reward())

        if self.validation_task.done():
            result = self.validation_task.result()
            _LOGGER.debug(f"Validation task with result: '{result}'")
            if result != "success":
                return self.async_abort(reason=result)

            return self.async_show_progress_done(next_step_id="select_devices")

        return self.async_show_progress(
            step_id="validate_grid_reward",
            progress_action="validating",
            progress_task=self.validation_task,
        )
    
    async def _validate_grid_reward(self):
        _LOGGER.debug("Starting grid reward validation.")
        try:
            client = get_async_client(self.hass)
            api = TibberAPI(self.data["username"], self.data["password"], client)
            grid_reward_data = await api.validate_grid_reward(self.data["home_id"])
            _LOGGER.debug("Grid reward validation successful.")

            if grid_reward_data:
                devices = grid_reward_data.get("flexDevices", [])
                for device in devices:
                    device_type = device.get("__typename")
                    device_id = device.get("vehicleId") if device_type == "GridRewardVehicle" else device.get("batteryId")
                    if device_id:
                        self.flex_devices[device_id] = {
                            "type": "vehicle" if device_type == "GridRewardVehicle" else "battery",
                            "name": device.get("shortName", device_id)
                        }
                if self.flex_devices:
                    _LOGGER.debug("Found %d flex devices.", len(self.flex_devices))
                    return "success"
                
                _LOGGER.warning("No flex devices found.")
                return "no_flex_device"
            
            _LOGGER.warning("No grid reward data found.")
            return "no_grid_rewards"
        except TibberConnectionError:
            _LOGGER.error("Connection error during validation.")
            return "unknown"
        except Exception:
            _LOGGER.exception("Unexpected exception during validation")
            return "unknown"

    async def async_step_validation_complete(self, task_result: str):
        if task_result != "success":
            return self.async_abort(reason=task_result)
        
        return await self.async_step_select_devices()

    async def async_step_select_devices(self, user_input=None):
        if user_input is not None:
            self.data["flex_devices"] = [
                {"id": dev_id, "type": self.flex_devices[dev_id]["type"], "name": self.flex_devices[dev_id]["name"]}
                for dev_id in user_input["flex_devices"]
            ]
            title = self.homes[self.data["home_id"]]
            return self.async_create_entry(title=title, data=self.data)

        device_names = {dev_id: info["name"] for dev_id, info in self.flex_devices.items()}
        return self.async_show_form(
            step_id="select_devices",
            data_schema=vol.Schema({
                vol.Required("flex_devices"): cv.multi_select(device_names)
            }),
        )

    async def async_step_reauth(self, user_input=None):
        return await self.async_step_user()

    @staticmethod
    @config_entries.HANDLERS.register("reconfigure")
    async def async_step_reconfigure(hass, config_entry):
        """Handle a reconfiguration flow."""
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": config_entry.entry_id},
            data=config_entry.data,
        )
