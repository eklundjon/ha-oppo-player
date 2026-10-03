"""Regression tests for the power-off UI bounce (off -> on -> off).

Root cause: after a POF the player emits a stale power ON (a late QPW reply to
a query issued before the command), and the old handler flipped state back to
ON *and* kicked off a ~15-query re-sync, stretching the bounce to ~4s.

The fix is command-generation gating in the device: the last commanded/pushed
power state is authoritative; a *solicited* reply (OppoPowerResponse) that
contradicts it is dropped as stale, while an *unsolicited* push (UPW ->
OppoUpdatePowerStatusResponse) is a genuine change and is always honored.
"""
from __future__ import annotations

from datetime import timedelta

from custom_components.oppo_player.oppoudpsdk import OppoRemoteCode, PlayStatus, PowerStatus


async def test_power_off_ignores_stale_solicited_on(mock_device):
    device = mock_device
    # Device is on (unsolicited push).
    await device._handle_power_response(PowerStatus.ON, is_push=True)
    assert device.power_status == PowerStatus.ON

    # User commands power off; the real OFF lands (as a push here).
    await device.async_send_command(OppoRemoteCode.POF)
    await device._handle_power_response(PowerStatus.OFF, is_push=True)
    assert device.power_status == PowerStatus.OFF

    # A late QPW ON reply (solicited) arrives afterward. It must be dropped:
    # no flip back to ON, and — critically — no re-query burst.
    device._client.async_send_command.reset_mock()
    await device._handle_power_response(PowerStatus.ON, is_push=False)
    assert device.power_status == PowerStatus.OFF
    device._client.async_send_command.assert_not_awaited()


async def test_off_confirmed_by_solicited_reply_then_stale_on_ignored(mock_device):
    # The OFF can itself arrive as the solicited POF/QPW reply; it matches the
    # commanded target and is accepted. A trailing stale ON is still ignored.
    device = mock_device
    await device._handle_power_response(PowerStatus.ON, is_push=True)
    await device.async_send_command(OppoRemoteCode.POF)
    await device._handle_power_response(PowerStatus.OFF, is_push=False)
    assert device.power_status == PowerStatus.OFF
    await device._handle_power_response(PowerStatus.ON, is_push=False)
    assert device.power_status == PowerStatus.OFF


async def test_physical_power_on_push_after_off_is_honored(mock_device):
    # After commanding off, a genuine unsolicited power-on (physical remote)
    # must still wake the entity — the gate only drops solicited replies.
    device = mock_device
    await device.async_send_command(OppoRemoteCode.POF)
    await device._handle_power_response(PowerStatus.OFF, is_push=True)
    assert device.power_status == PowerStatus.OFF
    await device._handle_power_response(PowerStatus.ON, is_push=True)
    assert device.power_status == PowerStatus.ON


async def test_power_on_command_accepts_matching_solicited_reply(mock_device):
    device = mock_device
    await device.async_send_command(OppoRemoteCode.PON)  # target ON
    await device._handle_power_response(PowerStatus.ON, is_push=False)  # PON reply
    assert device.power_status == PowerStatus.ON


async def test_solicited_reply_trusted_before_any_command(mock_device):
    # Initial sync: with no power command issued yet, a solicited QPW reply is
    # authoritative (nothing to be stale relative to).
    device = mock_device
    await device._handle_power_response(PowerStatus.ON, is_push=False)
    assert device.power_status == PowerStatus.ON


async def test_power_off_clears_stale_playback_position(mock_device):
    # Regression for the stale-position glitch: on power-on the card briefly
    # showed the pre-off position. Powering off must clear volatile playback
    # state so nothing stale survives the power cycle.
    device = mock_device
    await device._handle_power_response(PowerStatus.ON, is_push=True)
    device.playback_status = PlayStatus.PLAY
    device.playback_attributes.total_elapsed_time = timedelta(seconds=1234)

    await device.async_send_command(OppoRemoteCode.POF)
    await device._handle_power_response(PowerStatus.OFF, is_push=True)

    assert device.playback_attributes.total_elapsed_time == timedelta(0)
    assert device.playback_status == PlayStatus.UNKNOWN
    # The power gate must survive the reset, so the bounce stays fixed: a
    # trailing stale solicited ON is still dropped.
    await device._handle_power_response(PowerStatus.ON, is_push=False)
    assert device.power_status == PowerStatus.OFF
