import pytest

from src.video_enhance import _parse_scale_arg, _default_bitrate_for_height


def test_parse_scale_arg_ok_variants():
    assert _parse_scale_arg("1080p") == "-2:1080:flags=lanczos"
    assert _parse_scale_arg("1920x1080") == "1920:1080:flags=lanczos"
    assert _parse_scale_arg("2x") == "iw*2.0:ih*2.0:flags=lanczos" or _parse_scale_arg(
        "2x"
    ).startswith("iw*")


def test_parse_scale_arg_invalid():
    with pytest.raises(Exception):
        _parse_scale_arg("weird")


def test_default_bitrate_for_height():
    assert _default_bitrate_for_height(720, "h264").endswith("M")
    assert _default_bitrate_for_height(1080, "hevc").endswith("M")
