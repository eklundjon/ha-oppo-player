"""Model detection (QVR generation + beacon variant) and capability filtering."""
from __future__ import annotations

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature

from custom_components.oppo_udp.models import (
    OppoModel,
    capabilities,
    detect_model,
    display_name,
    model_from_server_name,
)
from custom_components.oppo_udp.oppoudpsdk import SetInputSource

_DAC_INPUTS = {SetInputSource.OPTICAL_IN, SetInputSource.COAX_IN, SetInputSource.USB_IN}


# ── QVR generation detection (can't distinguish 203/205) ──────────────────────

@pytest.mark.parametrize(
    ("firmware", "expected"),
    [
        ("UDP20X-54-1127", OppoModel.UDP_20X),   # generic — 203/205 unknown from QVR
        ("udp20x-54-1127", OppoModel.UDP_20X),   # case-insensitive
        ("BDP83-14-0306", OppoModel.BDP_83),
        ("BDP103-70-0512", OppoModel.BDP_10X),
        ("BDP93-55-0410", OppoModel.BDP_10X),
        ("DV983H-05-0303", OppoModel.DVD),
        ("DV980H-01-0101", OppoModel.DVD),
        ("", OppoModel.UNKNOWN),
        (None, OppoModel.UNKNOWN),
        ("WHAT-99-9999", OppoModel.UNKNOWN),
    ],
)
def test_detect_model(firmware, expected):
    assert detect_model(firmware) is expected


# ── beacon Server Name -> exact variant ───────────────────────────────────────

@pytest.mark.parametrize(
    ("server_name", "expected"),
    [
        ("OPPO UDP-205", OppoModel.UDP_205),
        ("OPPO UDP-203", OppoModel.UDP_203),
        ("oppo udp-205", OppoModel.UDP_205),  # case-insensitive
        ("OPPO UDP-207", OppoModel.UDP_20X),  # a UDP we don't pin -> generic
        ("Some Other Device", OppoModel.UNKNOWN),
        ("", OppoModel.UNKNOWN),
        (None, OppoModel.UNKNOWN),
    ],
)
def test_model_from_server_name(server_name, expected):
    assert model_from_server_name(server_name) is expected


# ── capability filtering ──────────────────────────────────────────────────────

def test_udp205_has_all_inputs_including_dac():
    caps = capabilities(OppoModel.UDP_205)
    assert caps.features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert _DAC_INPUTS <= set(caps.sources)  # Optical/Coax/USB present
    assert SetInputSource.HDMI_IN_BYPASS in caps.sources


def test_udp203_excludes_dac_inputs_keeps_bypass():
    caps = capabilities(OppoModel.UDP_203)
    assert caps.features & MediaPlayerEntityFeature.SELECT_SOURCE
    assert not (_DAC_INPUTS & set(caps.sources))  # no Optical/Coax/USB
    # ...but the shared HDMI/disc inputs remain, including HDMI-in bypass.
    assert SetInputSource.HDMI_IN_BYPASS in caps.sources
    assert SetInputSource.BLURAY in caps.sources
    assert SetInputSource.HDMI_IN in caps.sources


def test_generic_udp20x_is_the_superset():
    # Until the beacon narrows it, a UDP-20x advertises the full input set.
    assert capabilities(OppoModel.UDP_20X).sources == capabilities(OppoModel.UDP_205).sources


def test_non_udp_models_have_no_source_selection():
    for model in (OppoModel.BDP_83, OppoModel.BDP_10X, OppoModel.DVD, OppoModel.UNKNOWN):
        caps = capabilities(model)
        assert not (caps.features & MediaPlayerEntityFeature.SELECT_SOURCE)
        assert caps.sources == ()
        assert not caps.has_push


def test_shuffle_is_bluray_onward_only():
    for model in (OppoModel.BDP_83, OppoModel.UDP_203, OppoModel.UDP_205):
        assert capabilities(model).features & MediaPlayerEntityFeature.SHUFFLE_SET
    for model in (OppoModel.DVD, OppoModel.UNKNOWN):
        assert not (capabilities(model).features & MediaPlayerEntityFeature.SHUFFLE_SET)


def test_core_features_present_for_every_model():
    core = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.REPEAT_SET
    )
    for model in OppoModel:
        assert capabilities(model).features & core == core


def test_display_name():
    assert display_name(OppoModel.UDP_205) == "UDP-205"
    assert display_name(OppoModel.UDP_20X) == "UDP-20x"
    assert display_name(OppoModel.UNKNOWN) == "OPPO Player"
