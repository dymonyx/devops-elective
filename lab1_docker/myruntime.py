import json
import argparse
import os
import shutil
import subprocess
import socket

BASE_DIR = "/var/lib"
RUNTIME_NAME = "myruntime"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    return config


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


def mount_overlay(paths, LOWER_DIR):
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


def run_process(process_args, process_cwd):
    if not process_args:
        raise ValueError("process.args is empty")
    os.chdir(process_cwd)
    os.execvp(process_args[0], process_args)


def create_uts_namespace(hostname):
    os.unshare(os.CLONE_NEWUTS)
    socket.sethostname(hostname)


def create_mount_namespace():
    os.unshare(os.CLONE_NEWNS)
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)


def create_pid_namespace():
    os.unshare(os.CLONE_NEWPID)
    child_pid = os.fork()
    return child_pid


def is_mounted(path):
    result = subprocess.run(
        ["mountpoint", "-q", path],
        capture_output=True,
        check=False,
        text=True
    )
    return result.returncode == 0


def mount_proc():
    if not os.path.ismount("/proc"):
        subprocess.run(
            ["mount", "-t", "proc", "proc", "/proc"],
            capture_output=True,
            check=True,
            text=True
        )


def clean_up(paths):
    if is_mounted(paths["merged"]):
        subprocess.run(
            ["umount", paths["merged"]],
            capture_output=True,
            check=True,
            text=True
        )

    if os.path.exists(paths["container_dir"]):
        shutil.rmtree(paths["container_dir"])


def main():
    args = parse_args()
    config = load_config(args.config)

    hostname = config.get("hostname", "N/A")
    process = config.get("process", {})
    process_cwd = process.get("cwd", "/")
    process_args = process.get("args", [])
    paths = build_paths(args.id)
    LOWER_DIR = config["root"]["path"]

    clean_up(paths)
    create_container_dirs(paths)

    create_mount_namespace()
    mount_overlay(paths, LOWER_DIR)

    create_uts_namespace(hostname)

    child_pid = create_pid_namespace()

    if child_pid == 0:
        enter_rootfs(paths["merged"])
        mount_proc()
        run_process(process_args, process_cwd)
    else:
        os.waitpid(child_pid, 0)


if __name__ == "__main__":
    main()
