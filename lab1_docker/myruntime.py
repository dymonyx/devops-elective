import json
import argparse
import os
import subprocess

BASE_DIR = "/var/lib"
LOWER_DIR = "/opt/alpine-rootfs"
RUNTIME_NAME = "myruntime"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    process = config.get("process", {})
    return {
        "hostname": config.get("hostname", "N/A"),
        "process_cwd": process.get("cwd", "/"),
        "process_args": process.get("args", []),
    }


def build_paths(container_id):
    container_dir = os.path.join(BASE_DIR, RUNTIME_NAME, container_id)
    upperdir = os.path.join(container_dir, "upper")
    workdir = os.path.join(container_dir, "work")
    merged = os.path.join(container_dir, "merged")

    return {
        "container_dir": container_dir,
        "upperdir": upperdir,
        "workdir": workdir,
        "merged": merged,
    }


def create_container_dirs(paths):
    for path in (
        paths["container_dir"],
        paths["upperdir"],
        paths["workdir"],
        paths["merged"],
    ):
        os.makedirs(path, exist_ok=True)


def mount_overlay(paths):
    mount_options = (
        f"lowerdir={LOWER_DIR},"
        f"upperdir={paths['upperdir']},"
        f"workdir={paths['workdir']}"
    )

    mount_cmd = [
        "mount",
        "-t", "overlay",
        "overlay",
        "-o", mount_options,
        paths["merged"],
    ]

    subprocess.run(mount_cmd, capture_output=True, check=True, text=True)


def enter_rootfs(merged):
    os.chroot(merged)
    os.chdir("/")


def main():
    args = parse_args()
    config = load_config(args.config)
    paths = build_paths(args.id)

    create_container_dirs(paths)
    mount_overlay(paths)
    enter_rootfs(paths["merged"])

    os.system("ls /")


if __name__ == "__main__":
    main()
