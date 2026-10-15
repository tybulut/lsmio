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

"""Arms: the benchmark configurations that share one allocation per scale point.

Mirrors the branches of bmtool's jobs/batch.in.sh:
- backends mode: one arm per backend (INV-BACKEND-1)
- ior scaling runs: one arm per IOR setup, archived like backends to lsmio-archive/ior
- versioned variants: the bm_native:main reference baseline (role base), then the current
  binary per variant (role run) with a version-<branch>-<hash>[-<variant>] arm ID
- paired variants: the unconfigured baseline (role base), then each variant (role run)
- anything else: a single arm
"""

import os
import re
import subprocess
from typing import Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

DEFAULT_VARIANT_TOKENS = (None, "", "default", "base")

# Backend token -> (setup, arm ID), as in batch.in.sh's backends loop
BACKEND_ARMS: Dict[str, Tuple[str, str]] = {
    "adios2": ("ADIOS", "adios"),
    "adios": ("ADIOS", "adios"),
    "native": ("NATIVE", "native"),
    "plugin": ("PLUGIN", "plugin"),
    "rocksdb": ("ROCKSDB", "rocksdb"),
    "leveldb": ("LEVELDB", "leveldb"),
}

# IOR setup token -> (setup, arm ID); bmtool's ior-benchmark.sh ran one hard-coded setup
IOR_ARMS: Dict[str, Tuple[str, str]] = {
    "base": ("BASE", "ior"),
    "ior": ("BASE", "ior"),
    "collective": ("COLLECTIVE", "ior-collective"),
    "hdf5": ("HDF5", "ior-hdf5"),
    "hdf5-c": ("HDF5-C", "ior-hdf5-collective"),
    "hdf5-collective": ("HDF5-C", "ior-hdf5-collective"),
    "fsync": ("FSYNC", "ior-fsync"),
    "reverse": ("REVERSE", "ior-reverse"),
}
DEFAULT_IOR_SETUPS: Tuple[str, ...] = ("base", "collective", "hdf5", "hdf5-collective")
DEFAULT_LSMIO_BACKENDS: Tuple[str, ...] = ("adios2", "native", "plugin", "rocksdb")

# Reference baseline binary installed by `./build.sh install:main`
REFERENCE_NATIVE_EXECUTABLE = "bm_native:main"


class ArmError(Exception):
    """Raised when a request cannot be resolved into arms."""


class RunArm(NamedTuple):
    """One benchmark configuration run inside a shared allocation."""

    label: str
    setup: str
    variant: Optional[str]
    # Archive arm ID (outputs-<arm_id>[:role]); None for a paired baseline, which is
    # archived as the :base twin of every run arm instead
    arm_id: Optional[str]
    role: Optional[str]
    executable_overrides: Mapping[str, str] = {}


class ArmGroup(NamedTuple):
    """Arms of one request and how they run and archive."""

    kind: str  # "single", "paired" or "backends"
    arms: Tuple[RunArm, ...]
    archive: bool

    @property
    def is_paired(self) -> bool:
        return self.kind == "paired"

    @property
    def baseline(self) -> Optional[RunArm]:
        return self.arms[0] if self.is_paired else None

    @property
    def run_arms(self) -> Tuple[RunArm, ...]:
        return self.arms[1:] if self.is_paired else self.arms


def iorArmToken(f_setup: str) -> str:
    """The IOR arm token of an IOR setup name or token (BASE -> base, HDF5-C and
    hdf5-c -> hdf5-collective, ior -> base)."""
    f_low = str(f_setup).strip().lower()
    f_norm = IOR_ARMS[f_low][0] if f_low in IOR_ARMS else f_low.upper()
    for f_token in DEFAULT_IOR_SETUPS + tuple(IOR_ARMS):
        if IOR_ARMS[f_token][0] == f_norm:
            return f_token
    raise ArmError(f"Unsupported IOR setup: [{f_setup}]")


def isIorArmId(f_arm_id: Optional[str]) -> bool:
    """True for the arm ID of an IOR arm (outputs-ior, outputs-ior-<setup>)."""
    return f_arm_id is not None and (f_arm_id == "ior" or f_arm_id.startswith("ior-"))


def isDefaultVariant(f_variant: Optional[str]) -> bool:
    return f_variant in DEFAULT_VARIANT_TOKENS


def sanitizeBranch(f_branch: str) -> str:
    """Same as bmtool: sed -E 's/[^a-zA-Z0-9_-]/-/g'."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", f_branch)


def resolveVersionTag(f_repo_dir: Optional[str] = None) -> str:
    """Returns '<sanitized-branch>-<short-hash>' of the git checkout, like bmtool's versioned
    branch; each part falls back to 'unknown'."""
    f_dir = f_repo_dir or os.path.dirname(os.path.abspath(__file__))

    def _git(f_args: List[str]) -> str:
        try:
            f_res = subprocess.run(
                ["git", "-C", f_dir] + f_args,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        f_out = f_res.stdout.strip()
        return f_out if f_res.returncode == 0 and f_out else "unknown"

    f_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    f_hash = _git(["rev-parse", "--short", "HEAD"])
    return f"{sanitizeBranch(f_branch)}-{f_hash}"


def resolveArmGroup(
    f_request: object,
    f_setup: str,
    f_install_prefix: str,
    f_version_tag: Optional[str] = None,
) -> ArmGroup:
    """Resolve a RunRequest into the arms bmtool would run in one allocation."""
    from lsmiotool.lib.archive import ArchiveEngine

    from lsmiotool.lib.benchmarks import LsmioAdapter

    f_target = getattr(f_request, "target", "").lower()
    f_scale = getattr(f_request, "scale", "").lower()
    f_mode = getattr(f_request, "mode", "standard")
    f_archive_flag = getattr(f_request, "archive", None)

    if f_target == "lsmio" and str(f_setup).strip().upper() not in LsmioAdapter.ALLOWED_SETUPS:
        raise ArmError(
            f"Invalid setup: {f_setup!r}. Must be one of: {list(LsmioAdapter.ALLOWED_SETUPS)}"
        )

    if f_target == "ior" and f_mode == "backends":
        f_ior_arms: List[RunArm] = []
        f_seen: Set[str] = set()
        for f_raw in getattr(f_request, "backends", None) or DEFAULT_IOR_SETUPS:
            f_token = str(f_raw).strip().lower()
            if f_token not in IOR_ARMS:
                raise ArmError(
                    f"Unsupported IOR setup: [{f_token}]. Must be one of: {sorted(IOR_ARMS)}"
                )
            f_i_setup, f_i_arm = IOR_ARMS[f_token]
            if f_i_arm in f_seen:
                raise ArmError(f"IOR setup listed twice: [{f_token}]")
            f_seen.add(f_i_arm)
            f_ior_arms.append(RunArm(f_token, f_i_setup, None, f_i_arm, None))
        return ArmGroup("backends", tuple(f_ior_arms), f_archive_flag is not False)

    if f_target == "lsmio" and f_mode == "backends":
        f_arms: List[RunArm] = []
        for f_backend in getattr(f_request, "backends", None) or ():
            if f_backend not in BACKEND_ARMS:
                raise ArmError(
                    f"Unsupported backend for backends scaling: [{f_backend}]"
                )
            f_b_setup, f_b_arm = BACKEND_ARMS[f_backend]
            f_arms.append(RunArm(f_backend, f_b_setup, None, f_b_arm, None))
        if not f_arms:
            raise ArmError("Backends mode requires at least one backend")
        # batch.in.sh archives every backend run that completed
        return ArmGroup("backends", tuple(f_arms), f_archive_flag is not False)

    f_variants = tuple(getattr(f_request, "variants", (None,)) or (None,))
    f_real = [f_v for f_v in f_variants if not isDefaultVariant(f_v)]

    if f_target == "lsmio" and f_scale in ("variants", "baseline"):
        if getattr(f_request, "versioned", False):
            f_tag = f_version_tag or resolveVersionTag()
            f_ref = RunArm(
                "reference",
                f_setup,
                None,
                None,
                "base",
                {
                    "bm_native": os.path.join(
                        f_install_prefix, "bin", REFERENCE_NATIVE_EXECUTABLE
                    )
                },
            )
            if f_real:
                f_runs = [
                    RunArm(
                        f_v,
                        f_setup,
                        f_v,
                        ArchiveEngine.resolveArmId(f_setup, f"version-{f_tag}-{f_v}"),
                        "run",
                    )
                    for f_v in f_real
                ]
            else:
                f_runs = [
                    RunArm(
                        "version",
                        f_setup,
                        None,
                        ArchiveEngine.resolveArmId(f_setup, f"version-{f_tag}"),
                        "run",
                    )
                ]
            # bmtool rejects --no-archive with --versioned
            return ArmGroup("paired", tuple([f_ref] + f_runs), True)

        if f_real:
            f_base = RunArm("baseline", f_setup, None, None, "base")
            f_runs = [
                RunArm(
                    f_v, f_setup, f_v, ArchiveEngine.resolveArmId(f_setup, f_v), "run"
                )
                for f_v in f_real
            ]
            return ArmGroup(
                "paired", tuple([f_base] + f_runs), f_archive_flag is not False
            )

        # Standalone baseline: archived only on request
        return ArmGroup(
            "single",
            (
                RunArm(
                    "default",
                    f_setup,
                    None,
                    ArchiveEngine.resolveArmId(f_setup, None),
                    None,
                ),
            ),
            f_archive_flag is True,
        )

    f_variant = f_real[0] if f_real else None
    f_arm_id = (
        ArchiveEngine.resolveArmId(f_setup, f_variant) if f_target == "lsmio" else None
    )
    # bmtool never archives ior/lmp or plain lsmio scaling runs (ior scaling runs are
    # backends-mode groups above)
    return ArmGroup(
        "single",
        (RunArm(f_variant or "default", f_setup, f_variant, f_arm_id, None),),
        f_target == "lsmio" and f_archive_flag is True,
    )
