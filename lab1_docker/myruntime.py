import json
import argparse
import os
import subprocess

BASE_DIR = "/var/lib"
LOWER_DIR = "/opt/alpine-rootfs"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    container_id = args.id

    with open(args.config, 'r', encoding="utf-8") as config_file:
        config = json.load(config_file)
    process = config.get("process", {})
    process_cwd = process.get("cwd", "N/A")
    process_args = process.get("args", [])
    hostname = config.get("hostname", "N/A")

    container_dir = os.path.join(BASE_DIR, "myruntime", container_id)
    upperdir = os.path.join(container_dir, "upper")
    workdir = os.path.join(container_dir, "work")
    merged = os.path.join(container_dir, "merged")

    for path in (container_dir, upperdir, workdir, merged):
        os.makedirs(path, exist_ok=True)

    mount_options = (
        f"lowerdir={LOWER_DIR},upperdir={upperdir},workdir={workdir}"
    )

    mount_cmd = [
        "mount",
        "-t", "overlay",
        "overlay",
        "-o", mount_options,
        merged,
    ]

    result = subprocess.run(
        mount_cmd, capture_output=True, check=True, text=True)

    os.chroot(merged)
    os.chdir("/")
    os.system("ls /")
