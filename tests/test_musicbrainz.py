"""Parsing MusicBrainz disc ID lookups into MusicBrainzInfo."""
from __future__ import annotations

from unittest.mock import patch

from custom_components.oppo_player.musicbrainz import MusicBrainzInfo, _parse_response

DISC_ID = "abc123"


def _release(disc_ids):
    return {
        "id": "mbid-1",
        "title": "Album",
        "artist-credit": [{"artist": {"name": "Artist"}}],
        "medium-list": [
            {
                "disc-list": [{"id": d} for d in disc_ids],
                "track-list": [
                    {"position": "1", "recording": {"title": "One"}},
                    {"position": "2", "recording": {"title": "Two"}},
                ],
            }
        ],
    }


def test_matching_disc_gets_tracks_and_cover():
    response = {"disc": {"release-list": [_release([DISC_ID])]}}
    with patch(
        "custom_components.oppo_player.musicbrainz._get_image", return_value=b"jpeg"
    ):
        info = _parse_response(DISC_ID, response)
    assert info == MusicBrainzInfo(
        DISC_ID, "mbid-1", "Artist", "Album", {1: "One", 2: "Two"}, b"jpeg"
    )


def test_release_without_the_disc_keeps_album_and_artist():
    # No medium lists this disc ID, so there are no tracks or cover; the
    # release's album and artist still apply.
    response = {"disc": {"release-list": [_release(["other"])]}}
    with patch("custom_components.oppo_player.musicbrainz._get_image") as get_image:
        info = _parse_response(DISC_ID, response)
    get_image.assert_not_called()
    assert info == MusicBrainzInfo(DISC_ID, "mbid-1", "Artist", "Album", {}, None)


def test_cdstub_gives_album_and_artist():
    response = {"cdstub": {"artist": "Stub Artist", "title": "Stub Album"}}
    info = _parse_response(DISC_ID, response)
    assert info == MusicBrainzInfo(DISC_ID, artist="Stub Artist", title="Stub Album")


def test_response_without_disc_or_cdstub_is_empty_info():
    assert _parse_response(DISC_ID, {}) == MusicBrainzInfo(DISC_ID)
