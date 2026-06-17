"""Lightweight Home Assistant + voluptuous stubs for offline adapter tests.

Home Assistant and voluptuous are not installed in the dev/test environment
(by design — the core stays pure and the adapter defers HA imports).  The
config-entry-plumbing slice, however, must exercise the *real* ``config_flow``,
``time``, and ``services`` modules, which import HA framework symbols at module
load time.

``install()`` registers just-enough fake ``homeassistant.*`` and ``voluptuous``
modules in ``sys.modules`` so those real modules import and run as pure Python.
It is idempotent and additive: modules that defer HA imports (watcher,
coordinator, profile_store) are unaffected.  The fakes are intentionally thin —
schema *validation* is a passthrough; the point is to test our wiring, not to
re-implement HA.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Optional


# ── voluptuous ────────────────────────────────────────────────────────────────

_UNDEFINED = object()


class _Marker:
    """Stand-in for vol.Required / vol.Optional schema-dict keys."""

    def __init__(self, schema: Any, msg: Any = None, default: Any = _UNDEFINED,
                 description: Any = None) -> None:
        self.schema = schema
        self.default = default

    def __hash__(self) -> int:
        return hash(self.schema)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _Marker):
            return self.schema == other.schema
        return self.schema == other

    def __str__(self) -> str:
        return str(self.schema)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.schema!r})"


class _Required(_Marker):
    pass


class _Optional(_Marker):
    pass


class _Schema:
    def __init__(self, schema: Any = None, **kwargs: Any) -> None:
        self.schema = schema

    def __call__(self, data: Any) -> Any:  # passthrough validation
        return data


def _build_voluptuous() -> ModuleType:
    mod = ModuleType("voluptuous")
    mod.Schema = _Schema
    mod.Required = _Required
    mod.Optional = _Optional
    mod.Marker = _Marker

    def coerce(type_: Any, msg: Any = None) -> Any:
        return type_

    def in_(container: Any, msg: Any = None) -> Any:
        return container

    mod.Coerce = coerce
    mod.In = in_

    class Invalid(Exception):
        pass

    class MultipleInvalid(Invalid):
        pass

    mod.Invalid = Invalid
    mod.MultipleInvalid = MultipleInvalid
    return mod


# ── homeassistant ───────────────────────────────────────────────────────────


class _ConfigFlow:
    """Minimal config-flow base; absorbs the ``domain=`` subclass kwarg."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__()

    def async_create_entry(self, *, title: str, data: dict) -> dict:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id: str, data_schema: Any = None,
                        **kwargs: Any) -> dict:
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}


class _ConfigEntry:
    pass


class _HomeAssistant:
    pass


class _ServiceCall:
    pass


class _TimeEntity:
    def async_write_ha_state(self) -> None:  # no-op
        pass

    def schedule_update_ha_state(self, force_refresh: bool = False) -> None:
        pass


class _SwitchEntity(_TimeEntity):
    pass


class _Store:
    """In-memory stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self, hass: Any, version: int, key: str) -> None:
        self._data: Optional[dict] = None

    async def async_load(self) -> Optional[dict]:
        return self._data

    async def async_save(self, data: dict) -> None:
        self._data = data


def _make_module(name: str, **attrs: Any) -> ModuleType:
    mod = ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install() -> None:
    """Idempotently install fake homeassistant + voluptuous modules."""
    if "voluptuous" not in sys.modules:
        sys.modules["voluptuous"] = _build_voluptuous()

    if "homeassistant" in sys.modules:
        return

    ha = _make_module("homeassistant")

    config_entries = _make_module(
        "homeassistant.config_entries",
        ConfigFlow=_ConfigFlow,
        ConfigEntry=_ConfigEntry,
    )
    data_entry_flow = _make_module(
        "homeassistant.data_entry_flow", FlowResult=dict
    )
    core = _make_module(
        "homeassistant.core",
        HomeAssistant=_HomeAssistant,
        ServiceCall=_ServiceCall,
    )
    const = _make_module(
        "homeassistant.const",
        UnitOfEnergy=type("UnitOfEnergy", (), {"WATT_HOUR": "Wh"}),
        UnitOfPower=type("UnitOfPower", (), {"WATT": "W"}),
    )

    # components.*
    _make_module("homeassistant.components")
    _make_module("homeassistant.components.time", TimeEntity=_TimeEntity)
    _make_module(
        "homeassistant.components.sensor",
        SensorEntity=_TimeEntity,
        SensorStateClass=type(
            "SensorStateClass", (), {"MEASUREMENT": "measurement", "TOTAL": "total"}
        ),
    )
    _make_module("homeassistant.components.switch", SwitchEntity=_SwitchEntity)
    _make_module("homeassistant.components.select", SelectEntity=_TimeEntity)
    _make_module("homeassistant.components.button", ButtonEntity=_TimeEntity)

    # helpers.*
    helpers = _make_module("homeassistant.helpers")

    class _EntitySelector:
        def __init__(self, config: Any = None) -> None:
            self.config = config

    class _EntitySelectorConfig(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

    class _NumberSelector:
        def __init__(self, config: Any = None) -> None:
            self.config = config

    class _NumberSelectorConfig(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

    selector = _make_module(
        "homeassistant.helpers.selector",
        EntitySelector=_EntitySelector,
        EntitySelectorConfig=_EntitySelectorConfig,
        NumberSelector=_NumberSelector,
        NumberSelectorConfig=_NumberSelectorConfig,
        NumberSelectorMode=type(
            "NumberSelectorMode", (), {"SLIDER": "slider", "BOX": "box"}
        ),
    )
    storage = _make_module("homeassistant.helpers.storage", Store=_Store)
    entity_platform = _make_module(
        "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
    )
    entity = _make_module(
        "homeassistant.helpers.entity",
        EntityCategory=type(
            "EntityCategory", (), {"DIAGNOSTIC": "diagnostic", "CONFIG": "config"}
        ),
    )

    def _track_state_change_event(hass: Any, entity_ids: Any, action: Any):
        return lambda: None

    def _track_time_interval(hass: Any, action: Any, interval: Any):
        return lambda: None

    event = _make_module(
        "homeassistant.helpers.event",
        async_track_state_change_event=_track_state_change_event,
        async_track_time_interval=_track_time_interval,
    )

    # util.dt — the single timezone authority.  now() is settable by tests.
    util = _make_module("homeassistant.util")
    dt_mod = ModuleType("homeassistant.util.dt")
    dt_mod._now_value = datetime.now(tz=timezone.utc)  # type: ignore[attr-defined]

    def _now() -> datetime:
        return dt_mod._now_value  # type: ignore[attr-defined]

    def _set_now(value: datetime) -> None:
        dt_mod._now_value = value  # type: ignore[attr-defined]

    dt_mod.now = _now  # type: ignore[attr-defined]
    dt_mod.set_now = _set_now  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_mod

    # Wire submodule attributes onto parent packages so ``from homeassistant
    # import config_entries`` and ``from homeassistant.util import dt`` resolve.
    ha.config_entries = config_entries
    ha.data_entry_flow = data_entry_flow
    ha.core = core
    ha.const = const
    ha.helpers = helpers
    ha.util = util
    helpers.selector = selector
    helpers.storage = storage
    helpers.entity_platform = entity_platform
    helpers.entity = entity
    helpers.event = event
    util.dt = dt_mod
