# OPPO UDP-20x for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![HA Version][ha-shield]][ha]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

This is a Home Assistant integration for the OPPO UDP-203 and UDP-205 UHD Blu-ray players. It gives you a media player entity (power, transport, volume, input, what's playing) and a remote entity for sending any button on the OPPO remote.

**Before you start:**

- **An OPPO UDP-203 or UDP-205**, reachable over your network or wired to Home Assistant through its RS-232 port.
- **Home Assistant 2025.2 or later.**
- **Switch the player on for setup.** Setup checks that the player answers before it saves anything.
- **For network control, set the player's standby mode to Network Standby.** Otherwise the player drops off the network when it's off, and Home Assistant can't turn it back on.

> **Upgrading from 0.2.x, or moving from simbaja/ha_oppoudp?** Version 0.3.0 moved this integration to its own domain, `oppo_player`. Your player doesn't move over by itself; it takes a delete, a restart and one click. See [Moving to oppo_player](#moving-to-oppo_player).

This is a fork of [simbaja/ha_oppoudp](https://github.com/simbaja/ha_oppoudp). See [Why this fork](#why-this-fork) for how they differ.

## Features

- **Media player.** Power, play/pause/stop, next/previous, seek, volume and mute, repeat and shuffle, and input selection. Shows the disc type, title, chapter or track, and playback position.
- **CD info and cover art.** For audio CDs, track names, artist, album and cover art come from MusicBrainz when the disc doesn't carry them.
- **Remote.** `remote.send_command` sends any OPPO remote code, so you can script menus, eject, subtitles and the rest (see [Sending remote commands](#sending-remote-commands)).
- **Four ways to connect.** Native network control, or the player's RS-232 port through a local USB serial adapter, an RFC2217 serial gateway, or an ESPHome serial proxy.
- **Discovery.** When an OPPO player joins your network, Home Assistant notices it and offers to add it.
- **Model-aware.** A UDP-203 isn't offered the UDP-205's Optical, Coaxial and USB DAC inputs.
- **Reconfigure.** Change the player's address or how it's connected without deleting it, so you keep your entities and history.

## Install

**HACS (recommended)**

This repository isn't in the HACS default store, so add it as a custom repository. The badge does that for you:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eklundjon&repository=ha-oppo-player&category=integration)

Or, in HACS, open the menu, choose **Custom repositories**, and add `https://github.com/eklundjon/ha-oppo-player` with the type **Integration**. Then download **Oppo UDP-20x** and restart Home Assistant.

If you already have a player set up under the old `oppo_udp` integration (this one before 0.3.0, or simbaja/ha_oppoudp), see [Moving to oppo_player](#moving-to-oppo_player).

**Manual**

1. Copy the `custom_components/oppo_player` folder into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

## Add the player

If the player gets its address from your router (DHCP), Home Assistant may find it for you: look for it under **Settings → Devices & Services → Discovered**. A player with a fixed IP address won't be found this way, so add it by hand.

Otherwise:

1. Go to **Settings → Devices & Services → Add Integration** and search for **Oppo**.
2. Choose how the player is connected:

| Option | Use it when | You enter |
|--------|-------------|-----------|
| Network (recommended) | The player is on your network, or a TCP serial gateway (for example a Global Caché iTach) is wired to its RS-232 port | The player's IP address and port 23, or the gateway's address and serial port |
| RFC2217 serial gateway | A serial-to-network gateway is wired to the player's RS-232 port | The gateway's address and port |
| ESPHome serial proxy | An ESPHome device is wired to the player's RS-232 port | The ESPHome device's address and port |
| Local serial | A USB serial adapter connects Home Assistant to the player's RS-232 port | The device path (for example `/dev/ttyUSB0`). The player's port runs at 9600 baud. |

Setup fails with *Failed to connect* if the player doesn't answer. Check that it's switched on and that the address is right.

To change the address or connection later, open the integration and choose **Reconfigure**.

## Sending remote commands

The remote entity sends the three-letter codes from OPPO's control protocol. For example, to open the tray:

```yaml
action: remote.send_command
target:
  entity_id: remote.192_168_1_50_remote  # your player's remote entity
data:
  command: EJT
```

The entities are named after the player's address unless you rename the device.

Some useful codes: `EJT` (eject), `HOM` (home menu), `MNU` (pop-up menu), `TTL` (top menu), `OSD` (info), `SUB` (subtitle), `AUD` (audio), `NUP`/`NDN`/`NLT`/`NRT` (arrows), `SEL` (select), `RET` (back). The full list is in [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Why this fork

The original integration, [simbaja/ha_oppoudp](https://github.com/simbaja/ha_oppoudp) by Jack Simbach, went quiet in 2025 and this fork picked it up. It's active again: its 2026.8.0 release (August 2026) fixed seek, repeat and shuffle, and Home Assistant deprecation warnings. If you control your player over the network and it works for you, it's a reasonable choice.

This fork has gone further:

- **More ways to connect.** The original supports network control only. This fork can also connect through the RS-232 port, locally or through a gateway or ESPHome.
- **Discovery.** Home Assistant finds the player when it joins your network.
- **The right inputs for your model.** The original offers every input on both models. Here a UDP-203 isn't offered the UDP-205's DAC inputs.
- **Fixes the original doesn't have yet:**
  - The player stays up to date while it's sitting on its Home menu. In the original, the media player stops updating there.
  - An unexpected status from the player no longer breaks updates.
  - Reloading the integration no longer leaves duplicate update handlers behind.
  - The media player no longer advertises media browsing and "play media", which never worked.
- **Steadier power handling.** Turning the player off doesn't bounce it back on, and the old playback position is cleared.
- **Reconfigure.** Change the address or connection without deleting and re-adding the player.
- **The OPPO library is built in.** The original depends on the `oppoudpsdk` package, which hasn't been released since January 2025, so fixes to it can't ship. This fork carries its own copy and fixes it directly.
- **Tested.** An automated test suite runs on every change, against both the oldest supported and the latest Home Assistant.
- **Its own domain.** This fork installs as `oppo_player`, so it doesn't overwrite the original's files, or those of other forks that also use `oppo_udp`. Don't connect both integrations to the same player, though.

## Moving to oppo_player

Up to version 0.2.x this integration used the domain `oppo_udp`, the same as simbaja/ha_oppoudp and at least one other fork. Since they all install to the same folder, they overwrite each other. From 0.3.0 it uses its own domain, `oppo_player`.

When HACS installs 0.3.0, it adds the new `custom_components/oppo_player` folder but leaves the old `custom_components/oppo_udp` folder where it is. Nothing breaks: your player keeps running on the old code until you move it. But the old code no longer gets updates, so move it soon. If Home Assistant spots the player on your network, it shows a card under **Discovered** as a reminder. To move it:

1. **Remove the old code.**
   - If you're upgrading this integration from 0.2.x, delete the `custom_components/oppo_udp` folder, for example with the File editor or Samba add-on. HACS no longer tracks that folder.
   - If you're coming from simbaja/ha_oppoudp, open it in HACS and choose **Remove**. That deletes its files; your player, entities and history stay.
2. **Restart Home Assistant.** The old integration's entry now shows as not loaded, and **Settings** shows a repair, "Integration oppo_udp not found". Both are expected. **Don't choose "Remove previous configurations" in that repair.** It deletes your player's old settings, and then there's nothing left to import. Leave the repair alone; the import clears it.
3. Go to **Settings → Devices & Services → Add Integration**, search for **Oppo**, and choose **Import a player from the old Oppo UDP-20x integration**. If HA has discovered the player, the import is also offered under **Discovered**.

The player keeps its entity IDs, names, areas and history, and the old entry is removed. If the import says the old integration is still installed, the `oppo_udp` folder is still there, or Home Assistant hasn't restarted since you deleted it.

Going back is harder: once a player is imported, the original integration can't read its settings. To switch back, delete the player here and add it again in the original.

## Troubleshooting

To turn on debug logging, open the integration's page under **Settings → Devices & Services** and choose **Enable debug logging**. Reproduce the problem, then choose **Disable debug logging** and Home Assistant downloads the log. Or add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.oppo_player: debug
```

When you [open an issue](https://github.com/eklundjon/ha-oppo-player/issues), please include your player model, how it's connected, your Home Assistant version, and the debug log.

## More documentation

- [docs/PROTOCOL.md](docs/PROTOCOL.md): OPPO's control protocol, all the commands, and how the different OPPO generations compare.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the integration is put together.

## Credits

Originally created by [Jack Simbach](https://github.com/simbaja) as [simbaja/ha_oppoudp](https://github.com/simbaja/ha_oppoudp). MIT licensed.

The icon and logo are drawn from the OPPO wordmark on [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:OPPO_logo.svg) (a public-domain text logo), in the colors OPPO Digital used. OPPO is a trademark of its owner; this project isn't affiliated with OPPO.

[ha]: https://www.home-assistant.io
[ha-shield]: https://img.shields.io/badge/Home%20Assistant-2025.2+-blue.svg?style=for-the-badge&logo=homeassistant
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/eklundjon/ha-oppo-player.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/eklundjon/ha-oppo-player.svg?style=for-the-badge&include_prereleases
[releases]: https://github.com/eklundjon/ha-oppo-player/releases
