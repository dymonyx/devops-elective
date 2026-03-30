import json
import argparse
import os
import shutil
import subprocess
import socket

BASE_DIR = "/var/lib"
RUNTIME_NAME = "myruntime"
CGROUP_BASE = "/sys/fs/cgroup/"


def parse_args():
    """Parses required CLI arguments for container startup."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def load_config(config_path):
    """Loads OCI config from a JSON file."""
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    return config


def build_paths(container_id):
    """Builds overlay layer paths for a specific container."""
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
    """Creates container and overlay layer directories."""
    for path in (
        paths["container_dir"],
        paths["upperdir"],
        paths["workdir"],
        paths["merged"],
    ):
        os.makedirs(path, exist_ok=True)


def mount_overlay(paths, lower_dir):
    """Mounts overlayfs to the container merged directory."""
    mount_options = (
        f"lowerdir={lower_dir},"
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
    """Enters merged rootfs via chroot and switches to root directory."""
    os.chroot(merged)
    os.chdir("/")


def run_process(process_args, process_cwd):
    """Starts the target process inside the container via exec."""
    if not process_args:
        raise ValueError("process.args is empty")
    os.chdir(process_cwd)
    os.execvp(process_args[0], process_args)


def create_uts_namespace(hostname):
    """Creates a UTS namespace and sets container hostname."""
    os.unshare(os.CLONE_NEWUTS)
    socket.sethostname(hostname)


def create_mount_namespace():
    """Creates a mount namespace and isolates mount propagation."""
    os.unshare(os.CLONE_NEWNS)
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)


def create_pid_namespace():
    """Creates a PID namespace and forks the child process (future PID=1)."""
    os.unshare(os.CLONE_NEWPID)
    child_pid = os.fork()
    return child_pid


def is_mounted(path):
    """Checks whether a path is an active mount point."""
    result = subprocess.run(
        ["mountpoint", "-q", path],
        capture_output=True,
        check=False,
        text=True
    )
    return result.returncode == 0


def mount_proc():
    """Mounts /proc inside the container when needed."""
    if not os.path.ismount("/proc"):
        subprocess.run(
            ["mount", "-t", "proc", "proc", "/proc"],
            capture_output=True,
            check=True,
            text=True
        )


def create_ram_cgroup(container_id):
    """Creates a cgroup for RAM memory limit."""
    cgroup_runtime_path = os.path.join(CGROUP_BASE, RUNTIME_NAME)
    os.makedirs(cgroup_runtime_path, exist_ok=True)
    with open(os.path.join(cgroup_runtime_path, "cgroup.subtree_control"), "w", encoding="utf-8") as f:
        f.write("+memory")
    cgroup_path = os.path.join(cgroup_runtime_path, container_id)
    os.makedirs(cgroup_path, exist_ok=True)
    with open(os.path.join(cgroup_path, "memory.max"), "w", encoding="utf-8") as f:
        f.write("100M")
    return cgroup_path


def clean_up(paths):
    """Cleans old container artifacts and unmounts merged dir."""
    if is_mounted(paths["merged"]):
        subprocess.run(
            ["umount", paths["merged"]],
            capture_output=True,
            check=True,
            text=True
        )

    if os.path.exists(paths["container_dir"]):
        shutil.rmtree(paths["container_dir"])


def clean_up_cgroup(container_id):
    """Cleans up cgroup artifacts for a specific container."""
    cgroup_path = os.path.join(CGROUP_BASE, RUNTIME_NAME, container_id)
    if os.path.exists(cgroup_path):
        os.rmdir(cgroup_path)


def main():
    args = parse_args()
    config = load_config(args.config)
    # set hostname
    hostname = config.get("hostname", "N/A")
    # get values for process from config
    process = config.get("process", {})
    process_cwd = process.get("cwd", "/")
    process_args = process.get("args", [])
    # get namespace types from config
    linux = config.get("linux", {})
    namespace_types = {ns.get("type") for ns in linux.get("namespaces", [])}
    # make paths for dirs for container
    paths = build_paths(args.id)
    lower_dir = config["root"]["path"]
    # clean up old container artifacts and create dirs for overlayfs
    clean_up(paths)
    clean_up_cgroup(args.id)
    create_container_dirs(paths)
    # create mount namespace and isolate mount propagation
    if "mount" in namespace_types:
        create_mount_namespace()
    mount_overlay(paths, lower_dir)
    # create UTS namespace and set hostname
    if "uts" in namespace_types:
        create_uts_namespace(hostname)
    # create RAM cgroup
    cgroup_path = create_ram_cgroup(args.id)
    # create PID namespace and fork the child process
    if "pid" in namespace_types:
        child_pid = create_pid_namespace()
    else:
        child_pid = -1

    if child_pid == 0:  # in the child process:
        enter_rootfs(paths["merged"])
        mount_proc()
        run_process(process_args, process_cwd)
    elif child_pid > 0:  # in the parent process:
        # add child process to cgroup and wait for it to finish
        with open(os.path.join(cgroup_path, "cgroup.procs"), "w", encoding="utf-8") as f:
            f.write(str(child_pid))
        os.waitpid(child_pid, 0)
        clean_up_cgroup(args.id)
    else:
        enter_rootfs(paths["merged"])
        mount_proc()
        run_process(process_args, process_cwd)


if __name__ == "__main__":
    main()
