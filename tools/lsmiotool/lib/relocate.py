#
# Copyright 2026 Serdar Bulut
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

"""ARCHER2 relocation of the lsmiotool worker tree off /home (bmtool `bmtool:112-142`).

ARCHER2 compute nodes cannot read /home. When the worker that the job script will exec lives
under /home (or any BM_HOME_PREFIXES entry), the files it needs are mirrored with
`rsync -a --delete --exclude=*.log --exclude=*.err` below `<ARCHER2_WORK_ROOT>/tools`, and
the relocated worker path is returned for the job script instead.

Layouts (lib/resources.py ResourceLocator):
- Source: `<repo>/tools/lsmiotool/lsmiotool-worker` imports `lsmiotool.lib.*` from its own
  package directory and reads LMP assets from `<repo>/tools/bmtool/lmp-reaxff`. The package is
  mirrored to `<work>/tools/lsmiotool` and the assets to `<work>/tools/bmtool/lmp-reaxff`, so
  ResourceLocator.forSource() of the relocated worker resolves the same relative layout.
- Installed: `<prefix>/<libexec>/lsmio/lsmiotool-worker` reaches its python package, profile and
  assets through the REL_LIBEXEC_TO_* constants baked in at configure time. Each of those
  directories is mirrored below `<work>/tools/lsmiotool` at its path relative to their common
  root, preserving every relative link.
"""

import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from lsmiotool.lib.log import Console
from lsmiotool.lib.resources import (
    InstallRelativeLayout,
    LayoutConfigurationError,
    ResourceLocator,
)
from lsmiotool.lib.site import SiteResolutionError, resolveArcher2WorkRoot


class RelocationError(Exception):
    """Raised when the ARCHER2 worker relocation cannot be planned or performed."""

    pass


RELOCATION_SITE = "ARCHER2"

# bmtool `case "$BM_DIRNAME" in /home*|/home2*)`: a plain string-prefix match
DEFAULT_HOME_PREFIXES: Tuple[str, ...] = ("/home",)

# bmtool `rsync -a --delete "$_src_tools/" "$_work_tools/" --exclude="*.log" --exclude="*.err"`
RSYNC_OPTIONS: Tuple[str, ...] = ("-a", "--delete")
RSYNC_EXCLUDES: Tuple[str, ...] = ("--exclude=*.log", "--exclude=*.err")

WORKER_BASENAME = "lsmiotool-worker"

_INSTALLED_CONSTANT_PATTERN = re.compile(
    r'^(REL_LIBEXEC_TO_[A-Z]+)\s*=\s*"([^"\n]*)"\s*$', re.MULTILINE
)

RelocationRunner = Callable[[List[str]], Any]


def _checkPathToken(f_value: str, f_name: str) -> str:
    """Validate an absolute path without control characters; return it normalized."""
    if not isinstance(f_value, str) or not f_value.strip():
        raise RelocationError(f"{f_name} must be a non-empty string, got: {f_value!r}")
    if any(ord(f_c) < 32 or ord(f_c) == 127 for f_c in f_value):
        raise RelocationError(f"{f_name} contains control characters: {f_value!r}")
    f_stripped = f_value.strip()
    if not f_stripped.startswith("/"):
        raise RelocationError(f"{f_name} must be an absolute path: {f_value!r}")
    return os.path.normpath(f_stripped)


def homePrefixes(f_environ: Mapping[str, str]) -> Tuple[str, ...]:
    """Return /home plus the colon-separated BM_HOME_PREFIXES entries (empty entries skipped)."""
    f_prefixes: List[str] = list(DEFAULT_HOME_PREFIXES)
    for f_pref in (f_environ.get("BM_HOME_PREFIXES") or "").split(":"):
        if f_pref and f_pref not in f_prefixes:
            f_prefixes.append(f_pref)
    return tuple(f_prefixes)


def isUnderHomePrefix(f_path: str, f_environ: Mapping[str, str]) -> bool:
    """True when f_path starts with any home prefix (bmtool `case "$path" in "$prefix"*`)."""
    return any(f_path.startswith(f_pref) for f_pref in homePrefixes(f_environ))


def buildRsyncArgv(f_source_dir: str, f_dest_dir: str) -> List[str]:
    """Build the bmtool-equivalent mirror argv: rsync -a --delete <src>/ <dst>/ excludes."""
    f_src = _checkPathToken(f_source_dir, "rsync source")
    f_dst = _checkPathToken(f_dest_dir, "rsync destination")
    return ["rsync", *RSYNC_OPTIONS, *RSYNC_EXCLUDES, f_src + "/", f_dst + "/"]


def _siteName(f_profile: Any) -> str:
    if isinstance(f_profile, str):
        return f_profile.strip().upper()
    f_name = getattr(f_profile, "name", None)
    if isinstance(f_name, str):
        return f_name.strip().upper()
    f_value = getattr(f_name, "value", None)
    return f_value.strip().upper() if isinstance(f_value, str) else ""


def _readInstalledConstants(f_worker_path: str) -> Dict[str, str]:
    """Parse the configured REL_LIBEXEC_TO_* constants of an installed worker wrapper."""
    try:
        with open(f_worker_path, "r", encoding="utf-8") as f_f:
            f_text = f_f.read()
    except (OSError, UnicodeDecodeError) as f_err:
        raise RelocationError(
            f"Cannot read worker executable '{f_worker_path}': {f_err}"
        ) from f_err
    return {
        f_m.group(1): f_m.group(2)
        for f_m in _INSTALLED_CONSTANT_PATTERN.finditer(f_text)
        if "@" not in f_m.group(2)
    }


def planRelocation(
    f_worker_path: str, f_tools_root: str
) -> Tuple[List[Tuple[str, str]], str]:
    """
    Plan the directories to mirror for a worker and where the relocated worker will live.

    Args:
        f_worker_path: Real absolute path of the worker executable.
        f_tools_root: Destination tools root (<ARCHER2_WORK_ROOT>/tools).

    Returns:
        ([(source_dir, dest_dir), ...], relocated_worker_path). Required directories come
        first; optional asset/profile directories are included only when they exist.
    """
    f_worker = _checkPathToken(f_worker_path, "worker executable")
    f_tools = _checkPathToken(f_tools_root, "tools root")
    f_pkg_dest = os.path.join(f_tools, "lsmiotool")

    f_constants = _readInstalledConstants(f_worker)
    try:
        if "REL_LIBEXEC_TO_PYTHON" in f_constants:
            return _planInstalled(f_worker, f_constants, f_pkg_dest)
        return _planSource(f_worker, f_tools)
    except LayoutConfigurationError as f_err:
        raise RelocationError(
            f"Cannot derive the worker layout of '{f_worker}': {f_err}"
        ) from f_err


def _planSource(
    f_worker: str, f_tools: str
) -> Tuple[List[Tuple[str, str]], str]:
    f_layout = ResourceLocator.forSource(f_worker)
    f_package_root = f_layout.package_root
    if os.path.dirname(f_worker) != f_package_root:
        raise RelocationError(
            f"Source worker '{f_worker}' is not at its package root '{f_package_root}'"
        )
    if os.path.basename(f_package_root) != "lsmiotool":
        raise RelocationError(
            f"Source package directory must be named 'lsmiotool' to be importable: '{f_package_root}'"
        )
    f_pairs: List[Tuple[str, str]] = [
        (f_package_root, os.path.join(f_tools, "lsmiotool"))
    ]
    if os.path.isdir(f_layout.asset_root):
        f_pairs.append(
            (f_layout.asset_root, os.path.join(f_tools, "bmtool", "lmp-reaxff"))
        )
    return f_pairs, os.path.join(f_tools, "lsmiotool", os.path.basename(f_worker))


def _planInstalled(
    f_worker: str, f_constants: Mapping[str, str], f_pkg_dest: str
) -> Tuple[List[Tuple[str, str]], str]:
    f_python = f_constants["REL_LIBEXEC_TO_PYTHON"]
    f_rel_layout = InstallRelativeLayout(
        f_package_root=f_python,
        f_profile_file=f_constants.get(
            "REL_LIBEXEC_TO_PROFILE", f_python + "/lsmiotool/etc/environments.json"
        ),
        f_asset_root=f_constants.get("REL_LIBEXEC_TO_ASSETS", f_python),
        f_worker_executable=f_constants.get(
            "REL_LIBEXEC_TO_WORKER", os.path.basename(f_worker)
        ),
        f_version_file=f_constants.get(
            "REL_LIBEXEC_TO_VERSION", f_python + "/lsmiotool/VERSION"
        ),
    )
    f_layout = ResourceLocator.forInstalled(f_worker, f_rel_layout)

    f_required = [os.path.dirname(f_worker), f_layout.package_root]
    f_optional = [os.path.dirname(f_layout.profile_file), f_layout.asset_root]
    f_dirs: List[str] = list(f_required) + [
        f_d for f_d in f_optional if os.path.isdir(f_d)
    ]
    f_common = os.path.commonpath(f_dirs)
    if f_common == "/":
        raise RelocationError(
            f"Installed worker layout of '{f_worker}' has no common install root"
        )

    # Drop directories already covered by a mirrored ancestor
    f_unique: List[str] = []
    for f_d in sorted(set(f_dirs), key=len):
        if not any(
            f_d == f_u or f_d.startswith(f_u.rstrip("/") + "/") for f_u in f_unique
        ):
            f_unique.append(f_d)

    f_pairs = [
        (f_d, os.path.normpath(os.path.join(f_pkg_dest, os.path.relpath(f_d, f_common))))
        for f_d in f_unique
    ]
    f_new_worker = os.path.normpath(
        os.path.join(f_pkg_dest, os.path.relpath(f_worker, f_common))
    )
    return f_pairs, f_new_worker


def _defaultRunner(f_argv: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        f_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _checkRunnerResult(f_argv: Sequence[str], f_result: Any) -> None:
    f_code = f_result if isinstance(f_result, int) else getattr(f_result, "returncode", 0)
    if f_code:
        f_stderr = getattr(f_result, "stderr", "") or ""
        raise RelocationError(
            f"Command failed with exit code {f_code}: {' '.join(f_argv)}"
            + (f": {f_stderr.strip()}" if f_stderr.strip() else "")
        )


def relocateForSite(
    f_profile: Any,
    f_worker_executable: str,
    f_environ: Optional[Mapping[str, str]] = None,
    f_runner: Optional[RelocationRunner] = None,
) -> str:
    """
    Mirror the worker tree to the ARCHER2 work filesystem when it lives under /home.

    Args:
        f_profile: SiteProfile (or anything with a `name`, or a site name string).
        f_worker_executable: Absolute worker executable path the job script would exec.
        f_environ: Environment (ARCHER2_WORK_ROOT, BM_HOME_PREFIXES, USER); os.environ by default.
        f_runner: Callable taking an argv list and returning a CompletedProcess-like object or
            an int exit code; runs the rsync commands (subprocess.run by default).

    Returns:
        The relocated worker path, or f_worker_executable unchanged when the site is not
        ARCHER2 or the worker is not under a home prefix.

    Raises:
        RelocationError: If the work root is itself under a home prefix, the layout cannot be
            derived, an rsync fails, or the relocated worker is missing afterwards.
    """
    if _siteName(f_profile) != RELOCATION_SITE:
        return f_worker_executable

    f_env: Mapping[str, str] = os.environ if f_environ is None else f_environ
    f_worker_abs = _checkPathToken(f_worker_executable, "worker executable")
    f_worker_real = os.path.realpath(f_worker_abs)
    if not (
        isUnderHomePrefix(f_worker_real, f_env) or isUnderHomePrefix(f_worker_abs, f_env)
    ):
        return f_worker_executable

    try:
        f_work_root = resolveArcher2WorkRoot(f_env)
    except SiteResolutionError as f_err:
        raise RelocationError(str(f_err)) from f_err
    f_tools_root = os.path.join(f_work_root, "tools")
    if isUnderHomePrefix(f_tools_root, f_env) or isUnderHomePrefix(
        os.path.realpath(f_tools_root), f_env
    ):
        raise RelocationError(
            f"ARCHER2 relocation target '{f_tools_root}' is itself under a home prefix "
            f"{list(homePrefixes(f_env))}; set ARCHER2_WORK_ROOT to a /work path"
        )

    f_pairs, f_new_worker = planRelocation(f_worker_real, f_tools_root)
    f_run = f_runner if f_runner is not None else _defaultRunner

    Console.info(
        f"ARCHER2 notice: compute nodes cannot access /home; "
        f"auto-syncing lsmiotool to {os.path.join(f_tools_root, 'lsmiotool')}"
    )
    for f_src, f_dst in f_pairs:
        try:
            os.makedirs(f_dst, exist_ok=True)
        except OSError as f_err:
            raise RelocationError(
                f"Cannot create relocation directory '{f_dst}': {f_err}"
            ) from f_err
        f_argv = buildRsyncArgv(f_src, f_dst)
        try:
            f_result = f_run(f_argv)
        except OSError as f_err:
            raise RelocationError(
                f"Cannot run '{' '.join(f_argv)}': {f_err}"
            ) from f_err
        _checkRunnerResult(f_argv, f_result)

    if not os.path.isfile(f_new_worker) or not os.access(f_new_worker, os.X_OK):
        raise RelocationError(
            f"Relocated worker '{f_new_worker}' is missing or not executable after sync"
        )
    Console.info(f"Using relocated worker {f_new_worker}")
    return f_new_worker


relocate_for_site = relocateForSite
