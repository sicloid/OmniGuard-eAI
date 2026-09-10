"""Create local development credentials once; never print or overwrite secrets."""

import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = (
    "eclipse-mosquitto:2.0.22@sha256:"
    "212f89e1eaeb2c322d6441b64396e3346026674db8fa9c27beac293405c32b3c"
)


def main():
    directory = ROOT / ".secrets"
    if directory.is_symlink():
        raise SystemExit("Refusing symlink secret directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    for name in ("mqtt_password", "postgres_password", "grafana_password"):
        path = directory / name
        if path.is_symlink():
            raise SystemExit(f"Refusing secret symlink: {name}")
        if not path.exists():
            with path.open("x") as stream:
                stream.write(secrets.token_hex(32) + "\n")
            # Parent is 0700; files must be readable by non-root container users.
            path.chmod(0o444)
    password_file = directory / "mqtt_password_file"
    if password_file.is_symlink():
        raise SystemExit("Refusing password-file symlink")
    if not password_file.exists():
        password = (directory / "mqtt_password").read_text().strip()
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                IMAGE,
                "sh",
                "-ec",
                "umask 077; cat > /tmp/passwd; mosquitto_passwd -U /tmp/passwd; cat /tmp/passwd",
            ],
            input=f"omniguard:{password}\n",
            text=True,
            capture_output=True,
            check=True,
        )
        with password_file.open("x") as stream:
            stream.write(result.stdout)
        password_file.chmod(0o444)
    print("Local secrets ready in platform/.secrets (credentials not printed).")


if __name__ == "__main__":
    os.umask(0o077)
    main()
