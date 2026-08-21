import struct
from pathlib import Path

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _verify_png_image(filepath: Path) -> None:
    """Verify that a file exists, is non-empty, and has valid PNG header and dimensions."""
    assert filepath.exists(), f"File missing: {filepath}"
    assert filepath.stat().st_size > 0, f"File is empty: {filepath}"

    with filepath.open("rb") as f:
        header = f.read(8)
        assert header == PNG_HEADER, f"File is not a valid PNG image: {filepath}"

        # Read IHDR chunk
        _, chunk_type = struct.unpack(">I4s", f.read(8))
        assert chunk_type == b"IHDR", f"Missing IHDR chunk in PNG: {filepath}"

        width, height = struct.unpack(">II", f.read(8))
        assert width > 0 and height > 0, f"Invalid dimensions for PNG: {filepath}"


def test_integration_icons_exist():
    """Test that integration icon and logo files exist and are valid PNGs."""
    base_dir = Path("custom_components/tibber_grid_reward")
    icon_files = ["icon.png", "logo.png", "icon@2x.png", "logo@2x.png"]

    for icon_name in icon_files:
        _verify_png_image(base_dir / icon_name)


def test_root_icons_exist():
    """Test that root icon and logo files exist and are valid PNGs."""
    base_dir = Path(".")
    icon_files = ["icon.png", "logo.png", "icon@2x.png", "logo@2x.png"]

    for icon_name in icon_files:
        _verify_png_image(base_dir / icon_name)
