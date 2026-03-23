import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "fixed_tunnel_config.json"
RUN_BAT_PATH = ROOT / "run_fixed_public.bat"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def main() -> int:
    print("Cloudflare fixed public tunnel setup")
    print("")
    tunnel_name = ask("Tunnel name", "global-news-agent")
    hostname = ask("Public hostname", "news.example.com")
    tunnel_id = ask("Tunnel ID", "")
    credentials_file = ask("Credentials file path", str(Path.home() / ".cloudflared" / f"{tunnel_id}.json") if tunnel_id else "")
    local_service = ask("Local service URL", "http://127.0.0.1:8008")

    payload = {
        "tunnel_name": tunnel_name,
        "hostname": hostname,
        "tunnel_id": tunnel_id,
        "credentials_file": credentials_file,
        "local_service": local_service,
    }
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    RUN_BAT_PATH.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'cd /d "{ROOT}"',
                "python server.py",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    yaml_path = ROOT / "cloudflared_fixed.yml"
    yaml_path.write_text(
        "\n".join(
            [
                f"tunnel: {tunnel_id or 'REPLACE_WITH_TUNNEL_ID'}",
                f"credentials-file: {credentials_file or 'REPLACE_WITH_CREDENTIALS_FILE'}",
                "ingress:",
                f"  - hostname: {hostname}",
                f"    service: {local_service}",
                "  - service: http_status:404",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("")
    print(f"Saved config: {CONFIG_PATH}")
    print(f"Saved tunnel YAML: {yaml_path}")
    print("")
    print("Next commands:")
    print("1. cloudflared tunnel login")
    print(f"2. cloudflared tunnel create {tunnel_name}")
    print(f"3. cloudflared tunnel route dns {tunnel_name} {hostname}")
    print(f"4. cloudflared tunnel --config \"{yaml_path}\" run {tunnel_name}")
    print("")
    print("After tunnel creation, make sure the YAML contains the real tunnel ID and credentials file path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
