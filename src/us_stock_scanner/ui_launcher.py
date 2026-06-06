"""Launch Streamlit UI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app = Path(__file__).resolve().parent.parent.parent / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.address",
        "0.0.0.0",
        "--server.port",
        "8501",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    subprocess.run(cmd, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())