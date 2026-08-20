from pathlib import Path

from PIL import Image


def test_integration_icons_exist():
    """Test that integration icon and logo files exist and are valid PNGs."""
    base_dir = Path("custom_components/tibber_grid_reward")
    icon_files = ["icon.png", "logo.png", "icon@2x.png", "logo@2x.png"]

    for icon_name in icon_files:
        icon_path = base_dir / icon_name
        assert icon_path.exists(), f"Icon file {icon_name} missing from component directory"
        assert icon_path.stat().st_size > 0, f"Icon file {icon_name} is empty"

        # Verify it's a valid PNG image
        with Image.open(icon_path) as img:
            assert img.format == "PNG", f"Icon file {icon_name} is not a valid PNG image"


def test_root_icons_exist():
    """Test that root icon and logo files exist and are valid PNGs."""
    base_dir = Path(".")
    icon_files = ["icon.png", "logo.png", "icon@2x.png", "logo@2x.png"]

    for icon_name in icon_files:
        icon_path = base_dir / icon_name
        assert icon_path.exists(), f"Icon file {icon_name} missing from root directory"
        assert icon_path.stat().st_size > 0, f"Icon file {icon_name} is empty"

        # Verify it's a valid PNG image
        with Image.open(icon_path) as img:
            assert img.format == "PNG", f"Icon file {icon_name} is not a valid PNG image"
