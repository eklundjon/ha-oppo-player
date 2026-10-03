"""OPPO multicast discovery: beacon parsing + subscription (no real socket)."""
from __future__ import annotations

from custom_components.oppo_player.discovery import OppoDiscovery, _field
from custom_components.oppo_player.models import OppoModel

BEACON_205 = b"Notify: OPPO Player Start\r\nServer Name: OPPO UDP-205\r\n"
BEACON_203 = b"Notify: OPPO Player Start\nServer Name: OPPO UDP-203\n"


def test_field_parsing():
    text = "Notify: OPPO Player Start\nServer Name: OPPO UDP-205\n"
    assert _field(text, "Server Name") == "OPPO UDP-205"
    assert _field(text, "server name") == "OPPO UDP-205"  # case-insensitive
    assert _field(text, "Missing") is None


def test_handle_maps_source_ip_to_model(hass):
    disc = OppoDiscovery(hass)
    disc._handle(BEACON_205, ("192.168.1.50", 7624))
    disc._handle(BEACON_203, ("192.168.1.51", 7624))
    assert disc.model_for("192.168.1.50") is OppoModel.UDP_205
    assert disc.model_for("192.168.1.51") is OppoModel.UDP_203


def test_handle_ignores_non_beacon(hass):
    disc = OppoDiscovery(hass)
    disc._handle(b"random junk with no server name", ("192.168.1.50", 7624))
    assert disc.model_for("192.168.1.50") is None


def test_model_for_unknown_or_missing_ip(hass):
    disc = OppoDiscovery(hass)
    assert disc.model_for("10.0.0.1") is None
    assert disc.model_for(None) is None


def test_subscribe_fires_on_new_and_changed_model(hass):
    disc = OppoDiscovery(hass)
    calls: list[int] = []
    unsub = disc.subscribe("192.168.1.50", lambda: calls.append(1))
    assert calls == []  # nothing heard yet

    disc._handle(BEACON_205, ("192.168.1.50", 7624))
    assert calls == [1]
    # A repeat beacon (unchanged model) must not re-fire.
    disc._handle(BEACON_205, ("192.168.1.50", 7624))
    assert calls == [1]

    unsub()
    disc._handle(BEACON_203, ("192.168.1.50", 7624))  # changed, but unsubscribed
    assert calls == [1]


def test_subscribe_fires_immediately_if_already_known(hass):
    disc = OppoDiscovery(hass)
    disc._handle(BEACON_205, ("192.168.1.50", 7624))
    calls: list[int] = []
    disc.subscribe("192.168.1.50", lambda: calls.append(1))
    assert calls == [1]


def test_device_listener_fires_for_existing_and_new(hass):
    disc = OppoDiscovery(hass)
    disc._handle(BEACON_205, ("192.168.1.50", 7624))  # known before we listen
    seen: list[tuple[str, OppoModel]] = []
    unsub = disc.add_device_listener(lambda ip, model: seen.append((ip, model)))
    assert seen == [("192.168.1.50", OppoModel.UDP_205)]  # replayed on register

    disc._handle(BEACON_203, ("192.168.1.51", 7624))  # a new one
    assert ("192.168.1.51", OppoModel.UDP_203) in seen

    unsub()
    disc._handle(BEACON_205, ("192.168.1.52", 7624))  # no longer listening
    assert len(seen) == 2
