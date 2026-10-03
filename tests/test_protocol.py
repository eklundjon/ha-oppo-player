"""Protocol/enum audit.

Locks the vendored SDK's enum *values* to the exact wire strings the player
sends (per docs/PROTOCOL.md). This class of bug — right code, wrong string,
e.g. HOME_MENU — is invisible to a coverage check and froze the entity on
hardware, so it gets its own guard.
"""
from __future__ import annotations

import pytest

from custom_components.oppo_player.oppoudpsdk import DiscType, PlayStatus, RepeatMode
from custom_components.oppo_player.oppoudpsdk.response.response import _parse_enum


@pytest.mark.parametrize(
    "raw",
    [
        "PLAY", "PAUSE", "STOP", "HOME MENU", "MEDIA CENTER",
        "SCREEN SAVER", "DISC MENU", "SETUP", "OPEN", "CLOSE",
    ],
)
def test_playstatus_parses_wire_strings(raw):
    assert PlayStatus(raw)


def test_home_menu_value_has_space():
    # Regression for the frozen-entity bug: the player emits "HOME MENU".
    assert PlayStatus.HOME_MENU.value == "HOME MENU"


def test_menu_statuses_use_spaces_not_underscores():
    for member in (
        PlayStatus.HOME_MENU,
        PlayStatus.MEDIA_CENTER,
        PlayStatus.SCREEN_SAVER,
        PlayStatus.DISC_MENU,
    ):
        assert " " in member.value and "_" not in member.value


@pytest.mark.parametrize(
    "raw",
    ["BD-MV", "DVD-VIDEO", "DVD-AUDIO", "SACD", "CDDA", "UHBD", "NO-DISC"],
)
def test_disctype_parses_wire_strings(raw):
    assert DiscType(raw)


def test_playstatus_unknown_wire_value():
    # The player sends the 6-char truncation "UNKNOW" (cf. DiscType "UNKNOW-DISC").
    assert PlayStatus.UNKNOWN.value == "UNKNOW"
    assert PlayStatus("UNKNOW") is PlayStatus.UNKNOWN


# ── defensive parsing: an unrecognized wire string must never raise ─────────────

def test_parse_enum_falls_back_to_unknown():
    # HOME_MENU / UNKNOW class: a status the enum doesn't list degrades to
    # UNKNOWN instead of raising and dropping the whole state update.
    assert _parse_enum(PlayStatus, "SOMETHING NEW") is PlayStatus.UNKNOWN


def test_parse_enum_returns_default_without_unknown_member():
    # RepeatMode has no UNKNOWN member, so it degrades to the default (None).
    assert _parse_enum(RepeatMode, "BOGUS") is None


def test_parse_enum_passes_through_valid_values():
    assert _parse_enum(PlayStatus, "PLAY") is PlayStatus.PLAY
