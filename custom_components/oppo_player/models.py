"""Model detection and per-generation capability filtering.

Two detection sources feed this layer:

* ``#QVR`` firmware string (``UDP20X-…``, ``BDP83-…``, ``DV983H-…``) identifies
  the broad *generation* (``detect_model``). It cannot tell a UDP-203 from a
  UDP-205 — both report ``UDP20X-`` — so it yields the generic ``UDP_20X``.
* the UDP multicast beacon's ``Server Name`` (``OPPO UDP-205``) identifies the
  exact model (``model_from_server_name``); the discovery layer supplies it.

The entity resolves the most specific model it has (discovered > generation) and
looks up ``capabilities`` to narrow the HA features/inputs it advertises — e.g.
only the UDP-205 exposes the Optical/Coax/USB DAC inputs (docs/PROTOCOL.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from homeassistant.components.media_player import MediaPlayerEntityFeature

from .oppoudpsdk import SetInputSource


class OppoModel(Enum):
    """OPPO player model/generation, in protocol-capability order."""

    DVD = "DVD"              # DV-98xH: plain text, pull-only
    BDP_83 = "BDP-83"        # BD gen 1: @OK/@ER, QPL, no 3D
    BDP_10X = "BDP-9x/10x"   # BD gen 2-3: adds 3D
    UDP_203 = "UDP-203"      # UHD, no DAC audio inputs
    UDP_205 = "UDP-205"      # UHD flagship, adds Optical/Coax/USB DAC inputs
    UDP_20X = "UDP-20x"      # UHD, variant not yet known (QVR only)
    UNKNOWN = "Unknown"


# QVR prefix (token before the first '-') -> generation, matched by ``startswith``
# so firmware variants land in the right bucket. #QVR can't distinguish 203/205,
# so UDP maps to the generic UDP_20X; the beacon refines it. Specific first.
_PREFIX_MAP: tuple[tuple[str, OppoModel], ...] = (
    ("UDP2", OppoModel.UDP_20X),
    ("BDP10", OppoModel.BDP_10X),
    ("BDP9", OppoModel.BDP_10X),
    ("BDP8", OppoModel.BDP_83),
    ("DV9", OppoModel.DVD),
    ("DV8", OppoModel.DVD),
)


def detect_model(firmware_version: str | None) -> OppoModel:
    """Map a ``#QVR`` firmware string (e.g. ``UDP20X-54-1127``) to a generation.

    UDP-20x firmware yields the generic ``UDP_20X`` (203 vs 205 is indistinguishable
    from firmware); an empty/unrecognized string yields ``UNKNOWN``.
    """
    if not firmware_version:
        return OppoModel.UNKNOWN
    prefix = firmware_version.strip().upper().split("-", 1)[0]
    for token, model in _PREFIX_MAP:
        if prefix.startswith(token):
            return model
    return OppoModel.UNKNOWN


def model_from_server_name(server_name: str | None) -> OppoModel:
    """Map a discovery ``Server Name`` (e.g. ``OPPO UDP-205``) to an exact model.

    A UDP-20x we can't pin to 203/205 yields the generic ``UDP_20X``; a name we
    don't recognize yields ``UNKNOWN``.
    """
    if not server_name:
        return OppoModel.UNKNOWN
    text = server_name.strip().upper()
    if "UDP-205" in text or "UDP205" in text:
        return OppoModel.UDP_205
    if "UDP-203" in text or "UDP203" in text:
        return OppoModel.UDP_203
    if "UDP" in text:
        return OppoModel.UDP_20X
    return OppoModel.UNKNOWN


def display_name(model: OppoModel) -> str:
    """Human label for device_info; a friendly fallback when undetected."""
    return "OPPO Player" if model is OppoModel.UNKNOWN else model.value


# Features every supported generation has: transport, volume, seek, repeat.
_BASE_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.REPEAT_SET
)
# Blu-ray onward add shuffle (SHF); UDP-20x additionally exposes input select.
_BD_FEATURES = _BASE_FEATURES | MediaPlayerEntityFeature.SHUFFLE_SET
_UDP_FEATURES = _BD_FEATURES | MediaPlayerEntityFeature.SELECT_SOURCE

# Inputs shared by both UDP-20x models; the 205 adds the DAC audio inputs.
_AUDIO_INPUTS = (SetInputSource.OPTICAL_IN, SetInputSource.COAX_IN, SetInputSource.USB_IN)
_UDP203_SOURCES = tuple(s for s in SetInputSource if s not in _AUDIO_INPUTS)
_UDP205_SOURCES = tuple(SetInputSource)  # all inputs, incl. the DAC audio ones


@dataclass(frozen=True)
class ModelCapabilities:
    """What HA features/inputs a model supports."""

    features: MediaPlayerEntityFeature
    sources: tuple[SetInputSource, ...]  # empty ⇒ no source selection
    has_push: bool  # verbose U** push vs poll-only (future: parser/polling)


MODEL_CAPS: dict[OppoModel, ModelCapabilities] = {
    OppoModel.UDP_205: ModelCapabilities(_UDP_FEATURES, _UDP205_SOURCES, has_push=True),
    OppoModel.UDP_203: ModelCapabilities(_UDP_FEATURES, _UDP203_SOURCES, has_push=True),
    # Generic UDP-20x (variant undiscovered, e.g. serial): superset of inputs so
    # a 205 is fully usable; a 203 may show DAC inputs until the beacon narrows it.
    OppoModel.UDP_20X: ModelCapabilities(_UDP_FEATURES, _UDP205_SOURCES, has_push=True),
    OppoModel.BDP_10X: ModelCapabilities(_BD_FEATURES, (), has_push=False),
    OppoModel.BDP_83: ModelCapabilities(_BD_FEATURES, (), has_push=False),
    OppoModel.DVD: ModelCapabilities(_BASE_FEATURES, (), has_push=False),
    # Unknown/undetected: advertise only the safe shared core.
    OppoModel.UNKNOWN: ModelCapabilities(_BASE_FEATURES, (), has_push=False),
}


def capabilities(model: OppoModel) -> ModelCapabilities:
    """Capabilities for a resolved model."""
    return MODEL_CAPS[model]
