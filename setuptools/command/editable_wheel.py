"""
Create a wheel that, when installed, will make the source package 'editable'
(add it to the interpreter's path, including metadata) per PEP 660. Replaces
'setup.py develop'. Based on the setuptools develop command.
"""

import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from setuptools import Command
from setuptools import namespaces


class editable_wheel(Command):
    """Build 'editable' wheel for development"""

    description = "create a PEP 660 'editable' wheel"

    user_options = [
        ("dist-dir=", "d", "directory to put final built distributions in"),
        ("dist-info-dir=", "I", "path to a pre-build .dist-info directory"),
    ]

    boolean_options = ["strict"]

    def initialize_options(self):
        self.dist_dir = None
        self.dist_info_dir = None
        self.project_dir = None
        self.strict = False

    def finalize_options(self):
        dist = self.distribution
        self.project_dir = dist.src_root or os.curdir
        self.dist_dir = Path(self.dist_dir or os.path.join(self.project_dir, "dist"))
        self.dist_dir.mkdir(exist_ok=True)

    @property
    def target(self):
        package_dir = self.distribution.package_dir or {}
        return _normalize_path(package_dir.get("") or self.project_dir)

    def run(self):
        self._ensure_dist_info()

        # Add missing dist_info files
        bdist_wheel = self.reinitialize_command("bdist_wheel")
        bdist_wheel.write_wheelfile(self.dist_info_dir)

        # Build extensions in-place
        self.reinitialize_command("build_ext", inplace=1)
        self.run_command("build_ext")

        self._create_wheel_file(bdist_wheel)

    def _ensure_dist_info(self):
        if self.dist_info_dir is None:
            dist_info = self.reinitialize_command("dist_info")
            dist_info.output_dir = self.dist_dir
            dist_info.finalize_options()
            dist_info.run()
            self.dist_info_dir = dist_info.dist_info_dir
        else:
            assert str(self.dist_info_dir).endswith(".dist-info")
            assert Path(self.dist_info_dir, "METADATA").exists()

    def _install_namespaces(self, installation_dir, pth_prefix):
        # XXX: Only required to support the deprecated namespace practice
        dist = self.distribution
        if not dist.namespace_packages:
            return

        installer = _NamespaceInstaller(dist, installation_dir, pth_prefix, self.target)
        installer.install_namespaces()

    def _create_wheel_file(self, bdist_wheel):
        from wheel.wheelfile import WheelFile

        dist_info = self.get_finalized_command("dist_info")
        tag = "-".join(bdist_wheel.get_tag())
        editable_name = dist_info.name
        build_tag = "0.editable"  # According to PEP 427 needs to start with digit
        archive_name = f"{editable_name}-{build_tag}-{tag}.whl"
        wheel_path = Path(self.dist_dir, archive_name)
        if wheel_path.exists():
            wheel_path.unlink()

        # Currently the wheel API receives a directory and dump all its contents
        # inside of a wheel. So let's use a temporary directory.
        with TemporaryDirectory(suffix=archive_name) as tmp:
            tmp_dist_info = Path(tmp, Path(self.dist_info_dir).name)
            shutil.copytree(self.dist_info_dir, tmp_dist_info)
            self._install_namespaces(tmp, editable_name)
            self._populate_wheel(editable_name, tmp)
            with WheelFile(wheel_path, "w") as wf:
                wf.write_files(tmp)

        return wheel_path

    def _populate_wheel(self, dist_id, unpacked_wheel_dir):
        pth = Path(unpacked_wheel_dir, f"__editable__.{dist_id}.pth")
        pth.write_text(f"{self.target}\n", encoding="utf-8")


class _NamespaceInstaller(namespaces.Installer):
    def __init__(self, distribution, installation_dir, editable_name, src_root):
        self.distribution = distribution
        self.src_root = src_root
        self.installation_dir = installation_dir
        self.editable_name = editable_name
        self.outputs = []

    def _get_target(self):
        """Installation target."""
        return os.path.join(self.installation_dir, self.editable_name)

    def _get_root(self):
        """Where the modules/packages should be loaded from."""
        return repr(str(self.src_root))


def _normalize_path(filename):
    """Normalize a file/dir name for comparison purposes"""
    # See pkg_resources.normalize_path
    file = os.path.abspath(filename) if sys.platform == 'cygwin' else filename
    return os.path.normcase(os.path.realpath(os.path.normpath(file)))