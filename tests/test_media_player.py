"""Tests for the Oppo UDP-20x media_player entity."""
from __future__ import annotations

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)

from custom_components.oppo_udp.const import DOMAIN
from custom_components.oppo_udp.media_player import OppoUdpMediaPlayer
from custom_components.oppo_udp.models import OppoModel
from custom_components.oppo_udp.oppoudpsdk import DiscType, PlayStatus, PowerStatus
from tests.conftest import MOCK_HOST


def _player(manager):
    return OppoUdpMediaPlayer(MOCK_HOST, DOMAIN, "entry_id", manager)


def test_supported_features_only_advertises_implemented(mock_manager):
    # HA errors if an entity advertises a feature it can't fulfill. We implement
    # neither async_browse_media nor async_play_media, so those must be absent.
    features = _player(mock_manager).supported_features
    assert not (features & MediaPlayerEntityFeature.BROWSE_MEDIA)
    assert not (features & MediaPlayerEntityFeature.PLAY_MEDIA)
    # Sanity: features we do implement remain advertised.
    assert features & MediaPlayerEntityFeature.PLAY
    assert features & MediaPlayerEntityFeature.SEEK
    assert features & MediaPlayerEntityFeature.SELECT_SOURCE


def test_features_and_sources_filtered_for_non_udp_model(mock_manager):
    # A Blu-ray-gen player has no input selection; the entity must not advertise
    # SELECT_SOURCE or offer a source list — but core transport still works.
    mock_manager.device.firmware_version = "BDP83-14-0306"
    player = _player(mock_manager)
    assert not (player.supported_features & MediaPlayerEntityFeature.SELECT_SOURCE)
    assert player.source_list is None
    assert player.supported_features & MediaPlayerEntityFeature.PLAY


def test_discovered_203_narrows_inputs_over_firmware(mock_manager):
    # #QVR only says "UDP-20x"; the discovery beacon pins it to a 203, so the
    # DAC-only inputs (Optical/Coax/USB) must drop out of the source list.
    mock_manager.device.firmware_version = "UDP20X-54-1127"
    mock_manager.discovered_model = OppoModel.UDP_203
    sources = _player(mock_manager).source_list
    assert "Optical In" not in sources
    assert "Coax In" not in sources
    assert "Usb In" not in sources
    assert "Bluray" in sources and "Hdmi In Bypass" in sources


# ── state mapping ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("power", "play", "expected"),
    [
        (PowerStatus.DISCONNECTED, None, None),
        (PowerStatus.OFF, None, MediaPlayerState.OFF),
        (PowerStatus.UNKNOWN, None, MediaPlayerState.OFF),
        (PowerStatus.ON, PlayStatus.OFF, MediaPlayerState.OFF),
        (PowerStatus.ON, PlayStatus.PLAY, MediaPlayerState.PLAYING),
        (PowerStatus.ON, PlayStatus.DISC_MENU, MediaPlayerState.PLAYING),
        (PowerStatus.ON, PlayStatus.PAUSE, MediaPlayerState.PAUSED),
        (PowerStatus.ON, PlayStatus.STOP, MediaPlayerState.IDLE),
        (PowerStatus.ON, PlayStatus.HOME_MENU, MediaPlayerState.IDLE),
        (PowerStatus.ON, PlayStatus.SCREEN_SAVER, MediaPlayerState.IDLE),
        (PowerStatus.ON, PlayStatus.OPEN, MediaPlayerState.IDLE),
    ],
)
def test_state_mapping(mock_manager, power, play, expected):
    mock_manager.device.power_status = power
    mock_manager.device.playback_status = play
    assert _player(mock_manager).state == expected


def test_state_none_when_offline(mock_manager):
    mock_manager.online = False
    assert _player(mock_manager).state is None


# ── every service must call a method that EXISTS on the SDK device ─────────────

async def test_all_services_hit_valid_sdk_methods(mock_manager):
    """Regression guard for the AttributeError class of bug: drive every
    media_player service against a real OppoDevice and assert none calls a
    non-existent method. Would have caught async_set_repeat_mode /
    async_set_position before they reached hardware.
    """
    device = mock_manager.device
    device.disc_type = DiscType.CDDA  # MUSIC content path
    player = _player(mock_manager)
    client = device._client

    await player.async_media_play()
    await player.async_media_pause()
    await player.async_media_stop()
    await player.async_media_next_track()
    await player.async_media_previous_track()
    await player.async_turn_on()
    await player.async_turn_off()
    await player.async_mute_volume(True)
    await player.async_set_volume_level(0.5)
    await player.async_volume_up()
    await player.async_volume_down()
    await player.async_media_seek(30)              # async_seek_position
    await player.async_set_repeat(RepeatMode.ONE)  # async_repeat_mode
    await player.async_set_repeat(RepeatMode.ALL)
    await player.async_set_repeat(RepeatMode.OFF)
    await player.async_set_shuffle(True)
    await player.async_set_shuffle(False)
    await player.async_select_source(player.source_list[0])

    # All of the above delegate through client.async_send_command.
    assert client.async_send_command.await_count >= 15


async def test_repeat_video_uses_chapter(mock_manager):
    mock_manager.device.disc_type = DiscType.DVD_VIDEO
    # VIDEO content selects CHAPTER as the "one" mode; must not raise.
    await _player(mock_manager).async_set_repeat(RepeatMode.ONE)


async def test_shuffle_noop_for_video(mock_manager):
    device = mock_manager.device
    device.disc_type = DiscType.DVD_VIDEO
    await _player(mock_manager).async_set_shuffle(True)
    # Shuffle is music-only by design; a DVD sends nothing.
    assert device._client.async_send_command.await_count == 0
