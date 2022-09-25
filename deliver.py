import os
import sys
import subprocess

import logging
import shutil
import toml
import contextlib
import hashlib


def calc_file_md5(path):
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            md5.update(block)

    return md5.hexdigest()


def logging_setup(logging_stream=sys.stderr):
    """Inspired from Kadalu project"""
    root = logging.getLogger()

    if root.hasHandlers():
        return

    verbose = False
    try:
        if os.environ["NYDUS_TEST_VERBOSE"] == "YES":
            verbose = True
    except KeyError as _:
        pass

    # Errors should also be printed to screen.
    handler = logging.StreamHandler(logging_stream)

    if verbose:
        root.setLevel(logging.DEBUG)
        handler.setLevel(logging.DEBUG)
    else:
        root.setLevel(logging.INFO)
        handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s "
        "[%(module)s - %(lineno)s:%(funcName)s] "
        "- %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)


def execute(cmd, **kwargs):
    exc = None

    shell = kwargs.pop("shell", False)
    print_output = kwargs.pop("print_output", False)
    print_cmd = kwargs.pop("print_cmd", True)
    print_err = kwargs.pop("print_err", True)

    if print_cmd:
        logging.info("Executing command: %s" % cmd)

    try:
        output = subprocess.check_output(
            cmd, shell=shell, stderr=subprocess.STDOUT, **kwargs
        )
        output = output.decode("utf-8")
        if print_output:
            logging.info("%s" % output)
    except subprocess.CalledProcessError as exc:
        o = exc.output.decode() if exc.output is not None else ""
        if print_err:
            logging.error(
                "Command: %s\nReturn code: %d\nError output:\n%s"
                % (cmd, exc.returncode, o)
            )

        return False, o

    return True, output


@contextlib.contextmanager
def pushd(new_path: str):
    previous_dir = os.getcwd()
    os.chdir(new_path)
    try:
        yield
    finally:
        os.chdir(previous_dir)


class GitCmd:
    def __init__(self, workspace) -> None:
        self.workspace = workspace
        os.chdir(workspace)

    def clone(self, repo, branch):
        cmd = ["git", "clone", "--depth", "1", "--branch", branch, repo]
        cmd = " ".join(cmd)
        execute(cmd, shell=True)


logging_setup()

if __name__ == "__main__":
    deliveries_config = sys.argv[1]
    deliveries = toml.load(deliveries_config)

    workspace = deliveries["workspace"]
    version = deliveries["version"]
    projects: dict = deliveries["projects"]
    artifacts: dict = deliveries["artifacts"]
    package = deliveries["package"]

    os.makedirs(workspace, exist_ok=True)

    git = GitCmd(workspace)

    os.chdir(workspace)
    package_dir = os.path.join(workspace, f"{package}.{version}")

    os.makedirs(package_dir)

    for n, p in projects.items():
        repo = p["git"]
        try:
            branch = p["tag"]
        except KeyError:
            branch = p["branch"]

        git.clone(repo, branch)

        with pushd(n):
            builder = artifacts[n]["builder"]
            execute(builder, shell=True, print_output=True)
            bins_dir = artifacts[n]["bins_dir"]
            with pushd(bins_dir):
                bins = artifacts[n]["bins"]
                sub_dir = os.path.join(package_dir, n)
                os.makedirs(sub_dir, exist_ok=True)

                for b in bins:
                    md5 = calc_file_md5(b)
                    logging.info("%s md5 %s", b, md5.encode())
                    shutil.copyfile(b, os.path.join(sub_dir, b))

    execute(f"tar -zcf {package_dir}")
