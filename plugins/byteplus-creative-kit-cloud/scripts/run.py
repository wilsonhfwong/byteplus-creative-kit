"""Start the locked cloud runtime. One command per process; JSON results go to stdout."""
import os
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
workspace = Path(os.environ.get("BYTEPLUS_CREATIVE_WORKSPACE", "/workspace")).resolve()
data = Path(os.environ.get("BYTEPLUS_CREATIVE_DATA_DIR", str(workspace / ".byteplus-creative-kit"))).resolve()
os.environ.setdefault("BYTEPLUS_CREATIVE_DATA_DIR", str(data))
os.environ.setdefault("BYTEPLUS_CREATIVE_OUTPUT_DIR", str(workspace / "output" / "byteplus-creative-kit"))
os.environ.setdefault("UV_PROJECT_ENVIRONMENT", str(data / "venv"))
os.environ.setdefault("UV_CACHE_DIR", str(data / "uv-cache"))
uv = shutil.which("uv")
if not uv:
    sys.exit("BytePlus Cloud requires uv on PATH. Install uv in the cloud environment, then restart the plugin.")
os.execv(uv, [uv, "run", "--frozen", "--no-dev", "--project", str(root),
              "python", "-m", "byteplus_creative.cloud_cli", *sys.argv[1:]])
