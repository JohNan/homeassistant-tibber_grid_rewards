import json
import sys

def update_manifest(version):
    """Update the version in the manifest.json file."""
    manifest_path = "custom_components/tibber_grid_reward/manifest.json"
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
    
    manifest["version"] = version
    
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_manifest.py <version>")
        sys.exit(1)
    
    new_version = sys.argv[1]
    update_manifest(new_version)
    print(f"Successfully updated manifest.json to version {new_version}")
