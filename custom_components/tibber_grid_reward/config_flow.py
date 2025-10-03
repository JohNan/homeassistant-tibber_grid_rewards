import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.httpx_client import get_async_client
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, AbortFlow

from .client import TibberAPI, TibberAuthError, TibberConnectionError
from .const import CONF_API_KEY, DOMAIN
from .public_client import TibberPublicAPI, TibberPublicAuthError, TibberPublicException


_LOGGER = logging.getLogger(__name__)


class NoHomesFound(AbortFlow):
    """Exception to indicate no homes were found."""

    def __init__(self) -> None:
        """Initialize."""
        super().__init__("no_homes")


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Tibber Grid Reward."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            try:
                token = user_input[CONF_API_KEY]
                client = get_async_client(self.hass)
                public_api = TibberPublicAPI(token, client)

                await public_api.get_homes()

                return self.async_create_entry(title="", data=user_input)
            except TibberPublicAuthError:
                errors["base"] = "invalid_auth"
            except (TibberPublicException, Exception):
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_API_KEY,
                        default=self.config_entry.options.get(CONF_API_KEY, ""),
                    ): str
                }
            ),
            errors=errors,
        )


class TibberGridRewardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    entry: config_entries.ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    def __init__(self):
        self.data = {}
        self.homes = {}
        self.flex_devices = {}
        self.validation_task: asyncio.Task | None = None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            self.data[CONF_USERNAME] = user_input[CONF_USERNAME]
            self.data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            self.data[CONF_API_KEY] = user_input[CONF_API_KEY]

            try:
                errors = await self._validate_credentials()
                if not errors:
                    return await self.async_step_select_home()
            except NoHomesFound as e:
                return self.async_abort(reason=e.reason)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_select_home(self, user_input=None):
        if user_input is not None:
            self.data["home_id"] = user_input["home_id"]
            _LOGGER.debug("Home selected: %s", self.data["home_id"])
            return await self.async_step_validate_grid_reward()

        return self.async_show_form(
            step_id="select_home",
            data_schema=vol.Schema({vol.Required("home_id"): vol.In(self.homes)}),
        )

    async def async_step_validate_grid_reward(self, user_input=None):
        if self.validation_task is None:
            _LOGGER.debug("Creating validation task")
            self.validation_task = self.hass.async_create_task(
                self._validate_grid_reward()
            )

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
            api = TibberAPI(
                self.data[CONF_USERNAME], self.data[CONF_PASSWORD], client
            )
            grid_reward_data = await api.validate_grid_reward(self.data["home_id"])
            _LOGGER.debug("Grid reward validation successful.")

            if grid_reward_data:
                devices = grid_reward_data.get("flexDevices", [])
                for device in devices:
                    device_type = device.get("__typename")
                    device_id = (
                        device.get("vehicleId")
                        if device_type == "GridRewardVehicle"
                        else device.get("batteryId")
                    )
                    if device_id:
                        self.flex_devices[device_id] = {
                            "type": (
                                "vehicle"
                                if device_type == "GridRewardVehicle"
                                else "battery"
                            ),
                            "name": device.get("shortName", device_id),
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
                {
                    "id": dev_id,
                    "type": self.flex_devices[dev_id]["type"],
                    "name": self.flex_devices[dev_id]["name"],
                }
                for dev_id in user_input["flex_devices"]
            ]
            if self.entry:
                self.hass.config_entries.async_update_entry(self.entry, data=self.data)
                return self.async_abort(reason="reconfigure_successful")

            title = self.homes[self.data["home_id"]]
            return self.async_create_entry(title=title, data=self.data)

        device_names = {
            dev_id: info["name"] for dev_id, info in self.flex_devices.items()
        }
        return self.async_show_form(
            step_id="select_devices",
            data_schema=vol.Schema(
                {vol.Required("flex_devices"): cv.multi_select(device_names)}
            ),
        )

    async def async_step_reauth(self, user_input=None):
        return await self.async_step_reconfigure(user_input)

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Handle a reconfiguration flow."""
        self.entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors = {}

        if user_input:
            self.data = {
                CONF_USERNAME: self.entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_API_KEY: user_input[CONF_API_KEY],
            }
            try:
                errors = await self._validate_credentials()
                if not errors:
                    return await self.async_step_select_home()
            except NoHomesFound as e:
                return self.async_abort(reason=e.reason)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=self.entry.data[CONF_USERNAME]
                    ): vol.In(
                        {self.entry.data[CONF_USERNAME]: self.entry.data[CONF_USERNAME]}
                    ),
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(
                        CONF_API_KEY, default=self._get_current_api_key()
                    ): str,
                }
            ),
            errors=errors,
        )

    def _get_current_api_key(self) -> str:
        if self.entry:
            return self.entry.data.get(CONF_API_KEY) or self.entry.options.get(
                CONF_API_KEY, ""
            )
        return ""

    async def _validate_credentials(self) -> dict[str, str]:
        try:
            _LOGGER.debug("Attempting to fetch homes and validate credentials.")
            client = get_async_client(self.hass)

            # Validate username/password for private API
            api = TibberAPI(
                self.data[CONF_USERNAME], self.data[CONF_PASSWORD], client
            )
            homes_data = await api.get_homes()
            _LOGGER.debug("Successfully fetched homes.")

            if not homes_data:
                _LOGGER.warning("No homes found on Tibber account.")
                raise NoHomesFound()

            # Validate API key for public API
            public_api = TibberPublicAPI(self.data[CONF_API_KEY], client)
            await public_api.get_homes()
            _LOGGER.debug("Successfully validated API key.")

            self.homes = {home["id"]: home["title"] for home in homes_data}
            return {}

        except TibberAuthError:
            _LOGGER.warning("Authentication failed for private API.")
            return {"base": "auth"}
        except TibberPublicAuthError:
            _LOGGER.warning("Authentication failed for public API.")
            return {"base": "invalid_auth"}
        except (TibberConnectionError, TibberPublicException):
            _LOGGER.error("Connection error during validation.")
            return {"base": "unknown"}
        except Exception:
            _LOGGER.exception("Unexpected exception in user step")
            return {"base": "unknown"}