from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homeside_exo.const import DOMAIN
from custom_components.homeside_exo.exosocket import ExoAuthError, ExoError

HOST = "192.0.2.10"
DATA = {"host": HOST, "user": "reader", "password": "pw", "scan_interval": 60}

FAKE = {344: (49.1, None), 446: (41.5, None), 96: (22.2, None), 332: (22.0, None),
        158: (-1.4, None), 311: (None, 47), 487: (2, None), 418: (False, None),
        406: (60.0, None), 141: (1.44, None), 274: ("2.44", None)}


async def fake_read(session, host, items, user=None, password=None, timeout=20.0):
    return {i: FAKE.get(i, (0.0, None)) for i in items}

READ = "custom_components.homeside_exo.coordinator.async_read"
FLOW_READ = "custom_components.homeside_exo.config_flow.async_read"
FLOW_TPL = "custom_components.homeside_exo.config_flow.async_get_templates"


async def tpl_ok(session, host, timeout=10.0):
    return ["MALL_FJV_Villa_2_244"]


async def tpl_other(session, host, timeout=10.0):
    return ["MALL_FJV_Flerbostad_9_999"]


async def test_user_flow_ok(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] is FlowResultType.FORM
    with patch(FLOW_READ, fake_read), patch(FLOW_TPL, tpl_ok), patch(READ, fake_read):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], DATA)
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["result"].unique_id == HOST
    assert r["result"].data["template"] == "MALL_FJV_Villa_2_244"


async def test_user_flow_unknown_template_warns(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(FLOW_READ, fake_read), patch(FLOW_TPL, tpl_other):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], DATA)
    assert r["type"] is FlowResultType.FORM
    assert r["step_id"] == "unsupported_template"
    assert r["description_placeholders"]["template"] == "MALL_FJV_Flerbostad_9_999"
    with patch(READ, fake_read):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["result"].data["template"] == "MALL_FJV_Flerbostad_9_999"


async def test_user_flow_template_unreadable_warns(hass):
    async def tpl_fail(*a, **k):
        raise ExoError("404")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(FLOW_READ, fake_read), patch(FLOW_TPL, tpl_fail):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], DATA)
    assert r["step_id"] == "unsupported_template"
    assert r["description_placeholders"]["template"] == "okänd"


@pytest.mark.parametrize("exc,key", [(ExoAuthError("x"), "invalid_auth"), (ExoError("x"), "cannot_connect")])
async def test_user_flow_errors(hass, exc, key):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(FLOW_READ, side_effect=exc):
        r = await hass.config_entries.flow.async_configure(r["flow_id"], DATA)
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": key}


async def setup(hass, entry=None):
    entry = entry or MockConfigEntry(domain=DOMAIN, data=DATA, unique_id=HOST)
    entry.add_to_hass(hass)
    with patch(READ, fake_read):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_sensors(hass):
    entry = await setup(hass)
    reg = er.async_get(hass)
    ents = er.async_entries_for_config_entry(reg, entry.entry_id)
    assert len(ents) == 29  # 28 värden + DUC-version, inga larm
    assert all(e.unique_id.startswith(f"{HOST}_") for e in ents)
    def st(idx):
        eid = reg.async_get_entity_id("sensor", DOMAIN, f"{HOST}_{idx}")
        return eid, hass.states.get(eid)
    eid, s = st(344); assert float(s.state) == 49.1 and s.attributes["unit_of_measurement"] == "°C"
    eid, s = st(487); assert s.state == "Auto"
    eid, s = st(418); assert s.state == "OK"
    eid, s = st(274); assert s.state == "2.44" and reg.async_get(eid).entity_category == "diagnostic"
    # Disabled by default: rum 2 och 311
    for idx in (204, 311):
        e = reg.async_get(reg.async_get_entity_id("sensor", DOMAIN, f"{HOST}_{idx}"))
        assert e.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_auth_failure_starts_reauth_and_reauth_works(hass):
    async def bad(*a, **k):
        raise ExoAuthError("Access denied (28)")
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id=HOST)
    entry.add_to_hass(hass)
    with patch(READ, bad):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1 and flows[0]["context"]["source"] == "reauth"
    with patch(FLOW_READ, fake_read), patch(READ, fake_read):
        r = await hass.config_entries.flow.async_configure(
            flows[0]["flow_id"], {"user": "reader", "password": "nytt"})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reauth_successful"
    assert entry.data["password"] == "nytt"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow_changes_interval(hass):
    entry = await setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.FORM
    with patch(READ, fake_read):
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"scan_interval": 120})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coord.update_interval.total_seconds() == 120


async def test_options_reject_too_low(hass):
    entry = await setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(Exception):
        await hass.config_entries.options.async_configure(r["flow_id"], {"scan_interval": 5})


async def test_unique_id_migration(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id=HOST)
    entry.add_to_hass(hass)
    reg = er.async_get(hass); dreg = dr.async_get(hass)
    old = reg.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_344",
                                  config_entry=entry, suggested_object_id="framledning")
    dev = dreg.async_get_or_create(config_entry_id=entry.entry_id,
                                   identifiers={(DOMAIN, entry.entry_id)})
    with patch(READ, fake_read):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert reg.async_get(old.entity_id).unique_id == f"{HOST}_344"   # samma entity_id behålls
    assert dreg.async_get(dev.id).identifiers == {(DOMAIN, HOST)}
    assert len(er.async_entries_for_config_entry(reg, entry.entry_id)) == 29  # inga dubbletter


async def test_update_failure_marks_unavailable(hass):
    entry = await setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async def boom(*a, **k): raise ExoError("TimeoutError")
    with patch(READ, boom):
        await coord.async_refresh()
        await hass.async_block_till_done()
    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{HOST}_344")
    assert hass.states.get(eid).state == "unavailable"
