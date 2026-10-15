"""Write image metadata without including the Git checkout in the image."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

now = datetime.now(timezone.utc)
version = Path("VERSION").read_text(encoding="utf-8-sig").strip()
commit = os.environ.get("SOURCE_COMMIT", "unknown")
Path("BUILD_INFO").write_text(json.dumps({
    "build_type": "docker-source-community",
    "version": version,
    "build_timestamp": now.strftime("%Y%m%d-%H%M%S"),
    "build_date": now.isoformat(),
    "build_unix": int(now.timestamp()),
    "git_commit": commit,
    "full_version": f"{version}-source-{commit[:12]}",
}, indent=2) + "\n", encoding="utf-8")
