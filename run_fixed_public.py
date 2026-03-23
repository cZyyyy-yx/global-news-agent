import json
import os
import subprocess
import sys
import time
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "fixed_tunnel_config.json"
CLOUDFLARED = ROOT / "cloudflared.exe"


def main() -> int:
    if not CONFIG_PATH.exists():
        print("fixed_tunnel_config.json not found. Run setup_named_tunnel.py first.")
        return 1
    if not CLOUDFLARED.exists():
        print("cloudflared.exe not found.")
        return 1

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tunnel_name = config.get("tunnel_name", "").strip()
    if not tunnel_name:
        print("tunnel_name missing in fixed_tunnel_config.json")
        return 1

    yaml_path = ROOT / "cloudflared_fixed.yml"
    if not yaml_path.exists():
        print("cloudflared_fixed.yml not found. Run setup_named_tunnel.py first.")
        return 1

    local_url = config.get("local_service", f"http://127.0.0.1:{server.PORT}")
    env = os.environ.copy()
    env.setdefault("NEWS_AGENT_HOST", "0.0.0.0")

    server_proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env)
    time.sleep(2)
    tunnel_proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--config", str(yaml_path), "run", tunnel_name],
        cwd=ROOT,
    )
    print(f"Local server: {local_url}")
    print(f"Fixed public host: {config.get('hostname', '')}")
    try:
        server_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel_proc.terminate()
        server_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
