import os
import sys
from pathlib import Path
from typing import Optional

def find_gbak() -> Optional[Path]:
    """
    Attempts to find the gbak binary on the current platform.
    """
    if sys.platform == "win32":
        # Common Windows paths for Firebird
        search_paths = [
            Path("C:/Program Files/Firebird/bin/gbak.exe"),
            Path("C:/Program Files (x86)/Firebird/bin/gbak.exe"),
        ]
        # Also check PATH
        for path in os.environ.get("PATH", "").split(os.pathsep):
            potential = Path(path) / "gbak.exe"
            if potential.exists():
                return potential
    else:
        # Common Linux/POSIX paths
        search_paths = [
            Path("/usr/bin/gbak"),
            Path("/usr/local/bin/gbak"),
            Path("/opt/firebird/bin/gbak"),
        ]
        # Also check PATH
        for path in os.environ.get("PATH", "").split(os.pathsep):
            potential = Path(path) / "gbak"
            if potential.exists():
                return potential

    for path in search_paths:
        if path.exists():
            return path
    
    return None

if __name__ == "__main__":
    # Test the detection
    found = find_gbak()
    if found:
        print(f"Found gbak at: {found}")
    else:
        print("gbak not found")
