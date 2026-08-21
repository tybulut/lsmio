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

from datetime import datetime, timezone
from enum import Enum
import json
import os
import re
import secrets
import signal
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from lsmiotool.lib.site import (
    CancellationPolicy,
    CertificationState,
    ExecutableRegistry,
    LauncherPolicy,
    PbsMailMode,
    RankIdentityPolicy,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SiteResolutionError,
    SlurmMailMode,
    StorageClass,
)


class PlanValidationError(Exception):
    """Exception raised when a run plan request or configuration fails validation."""

    pass


class ManifestValidationError(Exception):
    """Exception raised when manifest validation, serialization, or deserialization fails."""

    pass


class LaunchMode(Enum):
    """Enumeration of execution launcher modes."""

    DIRECT = "direct"
    SLURM = "slurm"
    PBS = "pbs"
    FAKE = "fake"


class LaunchSpec:
    """Immutable benchmark launch specification."""

    __slots__ = ("m_mode", "m_executable_or_worker", "m_arguments", "m_expected_results", "_frozen")

    def __init__(
        self,
        f_mode: Union[LaunchMode, str],
        f_executable_or_worker: str,
        f_arguments: Sequence[str] = (),
        f_expected_results: Sequence[str] = (),
    ) -> None:
        if isinstance(f_mode, str):
            try:
                f_norm_mode = LaunchMode(f_mode.lower())
            except ValueError:
                raise PlanValidationError(f"Invalid LaunchMode string: {f_mode!r}")
        elif isinstance(f_mode, LaunchMode):
            f_norm_mode = f_mode
        else:
            raise PlanValidationError(f"LaunchMode must be LaunchMode or str, got: {f_mode!r}")

        if not isinstance(f_executable_or_worker, str) or not f_executable_or_worker:
            raise PlanValidationError(
                f"executable_or_worker must be a non-empty string, got: {f_executable_or_worker!r}"
            )

        super().__setattr__("m_mode", f_norm_mode)
        super().__setattr__("m_executable_or_worker", f_executable_or_worker)
        super().__setattr__("m_arguments", tuple(str(f_a) for f_a in f_arguments))
        super().__setattr__("m_expected_results", tuple(str(f_r) for f_r in f_expected_results))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def mode(self) -> LaunchMode:
        return self.m_mode

    @property
    def executable_or_worker(self) -> str:
        return self.m_executable_or_worker

    @property
    def arguments(self) -> Tuple[str, ...]:
        return self.m_arguments

    @property
    def expected_results(self) -> Tuple[str, ...]:
        return self.m_expected_results

    def toDict(self) -> Dict[str, Any]:
        return {
            "mode": self.m_mode.value,
            "executable_or_worker": self.m_executable_or_worker,
            "arguments": list(self.m_arguments),
            "expected_results": list(self.m_expected_results),
        }

    def __repr__(self) -> str:
        return (
            f"LaunchSpec(mode={self.m_mode!r}, "
            f"executable_or_worker={self.m_executable_or_worker!r}, "
            f"arguments={self.m_arguments!r}, "
            f"expected_results={self.m_expected_results!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, LaunchSpec):
            return (
                self.m_mode == f_other.m_mode
                and self.m_executable_or_worker == f_other.m_executable_or_worker
                and self.m_arguments == f_other.m_arguments
                and self.m_expected_results == f_other.m_expected_results
            )
        return False


class RankIdentity:
    """Immutable rank identity resolved by a launched task worker."""

    __slots__ = ("m_global_rank", "m_node_rank", "m_local_rank", "_frozen")

    def __init__(
        self,
        f_global_rank: int,
        f_node_rank: Union[str, int],
        f_local_rank: Optional[int] = None,
    ) -> None:
        if not isinstance(f_global_rank, int) or f_global_rank < 0:
            raise PlanValidationError(
                f"global_rank must be a non-negative integer, got: {f_global_rank!r}"
            )
        if not isinstance(f_node_rank, (str, int)) or (isinstance(f_node_rank, str) and not f_node_rank):
            raise PlanValidationError(
                f"node_rank must be a non-empty string or integer, got: {f_node_rank!r}"
            )
        if f_local_rank is not None:
            if not isinstance(f_local_rank, int) or f_local_rank < 0:
                raise PlanValidationError(
                    f"local_rank must be a non-negative integer or None, got: {f_local_rank!r}"
                )

        super().__setattr__("m_global_rank", f_global_rank)
        super().__setattr__("m_node_rank", f_node_rank)
        super().__setattr__("m_local_rank", f_local_rank)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def global_rank(self) -> int:
        return self.m_global_rank

    @property
    def node_rank(self) -> Union[str, int]:
        return self.m_node_rank

    @property
    def node(self) -> Union[str, int]:
        return self.m_node_rank

    @property
    def local_rank(self) -> Optional[int]:
        return self.m_local_rank

    def toDict(self) -> Dict[str, Any]:
        return {
            "global_rank": self.m_global_rank,
            "node_rank": self.m_node_rank,
            "local_rank": self.m_local_rank,
        }

    def __repr__(self) -> str:
        return (
            f"RankIdentity(global_rank={self.m_global_rank}, "
            f"node_rank={self.m_node_rank!r}, "
            f"local_rank={self.m_local_rank!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, RankIdentity):
            return (
                self.m_global_rank == f_other.m_global_rank
                and self.m_node_rank == f_other.m_node_rank
                and self.m_local_rank == f_other.m_local_rank
            )
        return False


class RunRequest:
    """Immutable parsed and validated run request."""

    __slots__ = ("m_target", "m_scale", "m_ssd", "m_setup", "_frozen")

    def __init__(
        self,
        f_target: str,
        f_scale: str,
        f_ssd: bool = False,
        f_setup: Optional[str] = None,
    ) -> None:
        if not isinstance(f_target, str) or not f_target.strip():
            raise PlanValidationError(f"target must be a non-empty string, got: {f_target!r}")
        if not isinstance(f_scale, str) or not f_scale.strip():
            raise PlanValidationError(f"scale must be a non-empty string, got: {f_scale!r}")
        if not isinstance(f_ssd, bool):
            raise PlanValidationError(f"ssd must be a boolean, got: {f_ssd!r}")
        if f_setup is not None and (not isinstance(f_setup, str) or not f_setup.strip()):
            raise PlanValidationError(f"setup must be a non-empty string or None, got: {f_setup!r}")

        super().__setattr__("m_target", f_target.strip().lower())
        super().__setattr__("m_scale", f_scale.strip().lower())
        super().__setattr__("m_ssd", f_ssd)
        super().__setattr__("m_setup", f_setup.strip().upper() if f_setup else None)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def target(self) -> str:
        return self.m_target

    @property
    def scale(self) -> str:
        return self.m_scale

    @property
    def ssd(self) -> bool:
        return self.m_ssd

    @property
    def is_ssd(self) -> bool:
        return self.m_ssd

    @property
    def setup(self) -> Optional[str]:
        return self.m_setup

    @property
    def storage(self) -> StorageClass:
        return StorageClass.SSD if self.m_ssd else StorageClass.HDD

    def toDict(self) -> Dict[str, Any]:
        return {
            "target": self.m_target,
            "scale": self.m_scale,
            "ssd": self.m_ssd,
            "setup": self.m_setup,
        }

    def __repr__(self) -> str:
        return (
            f"RunRequest(target={self.m_target!r}, "
            f"scale={self.m_scale!r}, "
            f"ssd={self.m_ssd!r}, "
            f"setup={self.m_setup!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, RunRequest):
            return (
                self.m_target == f_other.m_target
                and self.m_scale == f_other.m_scale
                and self.m_ssd == f_other.m_ssd
                and self.m_setup == f_other.m_setup
            )
        return False


class Combination:
    """Immutable combination of stripe count and block size in an execution point."""

    __slots__ = (
        "m_processes",
        "m_block_size",
        "m_stripe_count",
        "m_block_bytes",
        "m_key_count",
        "m_segment_count",
        "_frozen",
    )

    def __init__(
        self,
        f_processes: int,
        f_block_size: str,
        f_stripe_count: int,
        f_block_bytes: int,
        f_key_count: int,
        f_segment_count: int,
    ) -> None:
        if not isinstance(f_processes, int) or f_processes <= 0:
            raise PlanValidationError(f"processes must be a positive integer, got: {f_processes!r}")
        if not isinstance(f_block_size, str) or not f_block_size.strip():
            raise PlanValidationError(f"block_size must be a non-empty string, got: {f_block_size!r}")
        if not isinstance(f_stripe_count, int) or f_stripe_count <= 0:
            raise PlanValidationError(f"stripe_count must be a positive integer, got: {f_stripe_count!r}")
        if not isinstance(f_block_bytes, int) or f_block_bytes <= 0:
            raise PlanValidationError(f"block_bytes must be a positive integer, got: {f_block_bytes!r}")
        if not isinstance(f_key_count, int) or f_key_count <= 0:
            raise PlanValidationError(f"key_count must be a positive integer, got: {f_key_count!r}")
        if not isinstance(f_segment_count, int) or f_segment_count <= 0:
            raise PlanValidationError(f"segment_count must be a positive integer, got: {f_segment_count!r}")

        super().__setattr__("m_processes", f_processes)
        super().__setattr__("m_block_size", f_block_size.strip())
        super().__setattr__("m_stripe_count", f_stripe_count)
        super().__setattr__("m_block_bytes", f_block_bytes)
        super().__setattr__("m_key_count", f_key_count)
        super().__setattr__("m_segment_count", f_segment_count)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def processes(self) -> int:
        return self.m_processes

    @property
    def block_size(self) -> str:
        return self.m_block_size

    @property
    def stripe_count(self) -> int:
        return self.m_stripe_count

    @property
    def block_bytes(self) -> int:
        return self.m_block_bytes

    @property
    def key_count(self) -> int:
        return self.m_key_count

    @property
    def segment_count(self) -> int:
        return self.m_segment_count

    @property
    def name(self) -> str:
        return f"c{self.m_stripe_count}_b{self.m_block_size}"

    def toDict(self) -> Dict[str, Any]:
        return {
            "processes": self.m_processes,
            "block_size": self.m_block_size,
            "stripe_count": self.m_stripe_count,
            "block_bytes": self.m_block_bytes,
            "key_count": self.m_key_count,
            "segment_count": self.m_segment_count,
        }

    def __repr__(self) -> str:
        return (
            f"Combination(processes={self.m_processes}, "
            f"block_size={self.m_block_size!r}, "
            f"stripe_count={self.m_stripe_count}, "
            f"block_bytes={self.m_block_bytes}, "
            f"key_count={self.m_key_count}, "
            f"segment_count={self.m_segment_count})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, Combination):
            return (
                self.m_processes == f_other.m_processes
                and self.m_block_size == f_other.m_block_size
                and self.m_stripe_count == f_other.m_stripe_count
                and self.m_block_bytes == f_other.m_block_bytes
                and self.m_key_count == f_other.m_key_count
                and self.m_segment_count == f_other.m_segment_count
            )
        return False


class ScalePoint:
    """Immutable scale point representing tasks, processes-per-node, and node count."""

    __slots__ = ("m_tasks", "m_ppn", "m_nodes", "_frozen")

    def __init__(self, f_tasks: int, f_ppn: int, f_nodes: int) -> None:
        if not isinstance(f_tasks, int) or f_tasks <= 0:
            raise PlanValidationError(f"tasks must be a positive integer, got: {f_tasks!r}")
        if not isinstance(f_ppn, int) or f_ppn not in {1, 4}:
            raise PlanValidationError(f"ppn must be 1 or 4, got: {f_ppn!r}")
        if f_tasks % f_ppn != 0:
            raise PlanValidationError(
                f"tasks ({f_tasks}) must be evenly divisible by ppn ({f_ppn})"
            )
        if not isinstance(f_nodes, int) or f_nodes != f_tasks // f_ppn:
            raise PlanValidationError(
                f"nodes ({f_nodes}) must equal tasks ({f_tasks}) // ppn ({f_ppn}) = {f_tasks // f_ppn}"
            )

        super().__setattr__("m_tasks", f_tasks)
        super().__setattr__("m_ppn", f_ppn)
        super().__setattr__("m_nodes", f_nodes)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def tasks(self) -> int:
        return self.m_tasks

    @property
    def ppn(self) -> int:
        return self.m_ppn

    @property
    def nodes(self) -> int:
        return self.m_nodes

    @property
    def task_count(self) -> int:
        return self.m_tasks

    @property
    def tasks_per_node(self) -> int:
        return self.m_ppn

    @property
    def node_count(self) -> int:
        return self.m_nodes

    def toDict(self) -> Dict[str, int]:
        return {
            "tasks": self.m_tasks,
            "ppn": self.m_ppn,
            "nodes": self.m_nodes,
        }

    def __repr__(self) -> str:
        return f"ScalePoint(tasks={self.m_tasks}, ppn={self.m_ppn}, nodes={self.m_nodes})"

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ScalePoint):
            return (
                self.m_tasks == f_other.m_tasks
                and self.m_ppn == f_other.m_ppn
                and self.m_nodes == f_other.m_nodes
            )
        return False


class ScheduledPointResources:
    """Immutable resolved scheduler-specific resources for a scale point."""

    __slots__ = (
        "m_walltime",
        "m_select_chunks",
        "m_ncpus",
        "m_mpiprocs",
        "m_mem",
        "m_mail_mode",
        "m_queue",
        "m_partition",
        "m_qos",
        "m_pmem",
        "m_pvmem",
        "_frozen",
    )

    def __init__(
        self,
        f_walltime: str,
        f_select_chunks: Optional[int] = None,
        f_ncpus: Optional[int] = None,
        f_mpiprocs: Optional[int] = None,
        f_mem: Optional[str] = None,
        f_mail_mode: Optional[str] = None,
        f_queue: Optional[str] = None,
        f_partition: Optional[str] = None,
        f_qos: Optional[str] = None,
        f_pmem: Optional[str] = None,
        f_pvmem: Optional[str] = None,
    ) -> None:
        if not isinstance(f_walltime, str) or not f_walltime.strip():
            raise PlanValidationError(f"walltime must be a non-empty string, got: {f_walltime!r}")
        if f_select_chunks is not None and (not isinstance(f_select_chunks, int) or f_select_chunks <= 0):
            raise PlanValidationError(f"select_chunks must be a positive integer or None, got: {f_select_chunks!r}")
        if f_ncpus is not None and (not isinstance(f_ncpus, int) or f_ncpus <= 0):
            raise PlanValidationError(f"ncpus must be a positive integer or None, got: {f_ncpus!r}")
        if f_mpiprocs is not None and (not isinstance(f_mpiprocs, int) or f_mpiprocs <= 0):
            raise PlanValidationError(f"mpiprocs must be a positive integer or None, got: {f_mpiprocs!r}")

        super().__setattr__("m_walltime", f_walltime.strip())
        super().__setattr__("m_select_chunks", f_select_chunks)
        super().__setattr__("m_ncpus", f_ncpus)
        super().__setattr__("m_mpiprocs", f_mpiprocs)
        super().__setattr__("m_mem", f_mem)
        super().__setattr__("m_mail_mode", f_mail_mode)
        super().__setattr__("m_queue", f_queue)
        super().__setattr__("m_partition", f_partition)
        super().__setattr__("m_qos", f_qos)
        super().__setattr__("m_pmem", f_pmem)
        super().__setattr__("m_pvmem", f_pvmem)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def walltime(self) -> str:
        return self.m_walltime

    @property
    def select_chunks(self) -> Optional[int]:
        return self.m_select_chunks

    @property
    def ncpus(self) -> Optional[int]:
        return self.m_ncpus

    @property
    def mpiprocs(self) -> Optional[int]:
        return self.m_mpiprocs

    @property
    def mem(self) -> Optional[str]:
        return self.m_mem

    @property
    def mail_mode(self) -> Optional[str]:
        return self.m_mail_mode

    @property
    def queue(self) -> Optional[str]:
        return self.m_queue

    @property
    def partition(self) -> Optional[str]:
        return self.m_partition

    @property
    def qos(self) -> Optional[str]:
        return self.m_qos

    @property
    def pmem(self) -> Optional[str]:
        return self.m_pmem

    @property
    def pvmem(self) -> Optional[str]:
        return self.m_pvmem

    def toDict(self) -> Dict[str, Any]:
        return {
            "walltime": self.m_walltime,
            "select_chunks": self.m_select_chunks,
            "ncpus": self.m_ncpus,
            "mpiprocs": self.m_mpiprocs,
            "mem": self.m_mem,
            "mail_mode": self.m_mail_mode,
            "queue": self.m_queue,
            "partition": self.m_partition,
            "qos": self.m_qos,
            "pmem": self.m_pmem,
            "pvmem": self.m_pvmem,
        }

    def __repr__(self) -> str:
        return (
            f"ScheduledPointResources(walltime={self.m_walltime!r}, "
            f"select_chunks={self.m_select_chunks!r}, "
            f"ncpus={self.m_ncpus!r}, mpiprocs={self.m_mpiprocs!r}, "
            f"mem={self.m_mem!r}, mail_mode={self.m_mail_mode!r}, "
            f"queue={self.m_queue!r}, partition={self.m_partition!r}, "
            f"qos={self.m_qos!r}, pmem={self.m_pmem!r}, pvmem={self.m_pvmem!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ScheduledPointResources):
            return (
                self.m_walltime == f_other.m_walltime
                and self.m_select_chunks == f_other.m_select_chunks
                and self.m_ncpus == f_other.m_ncpus
                and self.m_mpiprocs == f_other.m_mpiprocs
                and self.m_mem == f_other.m_mem
                and self.m_mail_mode == f_other.m_mail_mode
                and self.m_queue == f_other.m_queue
                and self.m_partition == f_other.m_partition
                and self.m_qos == f_other.m_qos
                and self.m_pmem == f_other.m_pmem
                and self.m_pvmem == f_other.m_pvmem
            )
        return False


class RunPlan:
    """Immutable complete execution plan for a benchmark run."""

    __slots__ = (
        "m_run_id",
        "m_request",
        "m_profile",
        "m_scale_points",
        "m_combinations",
        "m_scheduled_points",
        "m_tokens",
        "m_manifest_timestamp",
        "_frozen",
    )

    def __init__(
        self,
        f_run_id: str,
        f_request: RunRequest,
        f_profile: SiteProfile,
        f_scale_points: Sequence[ScalePoint],
        f_combinations: Sequence[Combination],
        f_scheduled_points: Sequence[ScheduledPointResources],
        f_tokens: Sequence[str],
        f_manifest_timestamp: str,
    ) -> None:
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise PlanValidationError(f"run_id must be a non-empty string, got: {f_run_id!r}")
        if not isinstance(f_request, RunRequest):
            raise PlanValidationError(f"request must be a RunRequest, got: {f_request!r}")
        if not isinstance(f_profile, SiteProfile):
            raise PlanValidationError(f"profile must be a SiteProfile, got: {f_profile!r}")
        if not f_scale_points:
            raise PlanValidationError("scale_points must not be empty")
        if not f_combinations:
            raise PlanValidationError("combinations must not be empty")
        if len(f_scheduled_points) != len(f_scale_points):
            raise PlanValidationError(
                f"scheduled_points count ({len(f_scheduled_points)}) must equal scale_points count ({len(f_scale_points)})"
            )
        if len(f_tokens) != len(f_scale_points):
            raise PlanValidationError(
                f"tokens count ({len(f_tokens)}) must equal scale_points count ({len(f_scale_points)})"
            )
        if not isinstance(f_manifest_timestamp, str) or not f_manifest_timestamp.strip():
            raise PlanValidationError(
                f"manifest_timestamp must be a non-empty string, got: {f_manifest_timestamp!r}"
            )

        super().__setattr__("m_run_id", f_run_id.strip())
        super().__setattr__("m_request", f_request)
        super().__setattr__("m_profile", f_profile)
        super().__setattr__("m_scale_points", tuple(f_scale_points))
        super().__setattr__("m_combinations", tuple(f_combinations))
        super().__setattr__("m_scheduled_points", tuple(f_scheduled_points))
        super().__setattr__("m_tokens", tuple(f_tokens))
        super().__setattr__("m_manifest_timestamp", f_manifest_timestamp.strip())
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def run_id(self) -> str:
        return self.m_run_id

    @property
    def request(self) -> RunRequest:
        return self.m_request

    @property
    def profile(self) -> SiteProfile:
        return self.m_profile

    @property
    def scale_points(self) -> Tuple[ScalePoint, ...]:
        return self.m_scale_points

    @property
    def combinations(self) -> Tuple[Combination, ...]:
        return self.m_combinations

    @property
    def scheduled_points(self) -> Tuple[ScheduledPointResources, ...]:
        return self.m_scheduled_points

    @property
    def tokens(self) -> Tuple[str, ...]:
        return self.m_tokens

    @property
    def manifest_timestamp(self) -> str:
        return self.m_manifest_timestamp

    def toDict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.m_run_id,
            "manifest_timestamp": self.m_manifest_timestamp,
            "request": self.m_request.toDict(),
            "profile": self.m_profile.toDict(),
            "scale_points": [f_sp.toDict() for f_sp in self.m_scale_points],
            "combinations": [f_c.toDict() for f_c in self.m_combinations],
            "scheduled_points": [f_sp.toDict() for f_sp in self.m_scheduled_points],
            "tokens": list(self.m_tokens),
        }

    def __repr__(self) -> str:
        return (
            f"RunPlan(run_id={self.m_run_id!r}, "
            f"request={self.m_request!r}, "
            f"profile={self.m_profile!r}, "
            f"scale_points={self.m_scale_points!r}, "
            f"combinations={self.m_combinations!r}, "
            f"scheduled_points={self.m_scheduled_points!r}, "
            f"tokens={self.m_tokens!r}, "
            f"manifest_timestamp={self.m_manifest_timestamp!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, RunPlan):
            return (
                self.m_run_id == f_other.m_run_id
                and self.m_request == f_other.m_request
                and self.m_profile.toDict() == f_other.m_profile.toDict()
                and self.m_scale_points == f_other.m_scale_points
                and self.m_combinations == f_other.m_combinations
                and self.m_scheduled_points == f_other.m_scheduled_points
                and self.m_tokens == f_other.m_tokens
                and self.m_manifest_timestamp == f_other.m_manifest_timestamp
            )
        return False


class RunPlanner:
    """Pure planner that validates domain constraints and creates immutable RunPlan records."""

    TOKEN_PATTERN: re.Pattern = re.compile(r"^lm-[0-9a-f]{24}$")

    ORDERED_COMBINATIONS: Tuple[Combination, ...] = (
        Combination(
            f_processes=16,
            f_block_size="8M",
            f_stripe_count=16,
            f_block_bytes=8388608,
            f_key_count=1024,
            f_segment_count=128,
        ),
        Combination(
            f_processes=16,
            f_block_size="1M",
            f_stripe_count=16,
            f_block_bytes=1048576,
            f_key_count=4096,
            f_segment_count=1024,
        ),
        Combination(
            f_processes=16,
            f_block_size="64K",
            f_stripe_count=16,
            f_block_bytes=65536,
            f_key_count=65536,
            f_segment_count=16384,
        ),
        Combination(
            f_processes=4,
            f_block_size="8M",
            f_stripe_count=4,
            f_block_bytes=8388608,
            f_key_count=1024,
            f_segment_count=128,
        ),
        Combination(
            f_processes=4,
            f_block_size="1M",
            f_stripe_count=4,
            f_block_bytes=1048576,
            f_key_count=4096,
            f_segment_count=1024,
        ),
        Combination(
            f_processes=4,
            f_block_size="64K",
            f_stripe_count=4,
            f_block_bytes=65536,
            f_key_count=65536,
            f_segment_count=16384,
        ),
    )

    SCALE_MATRICES: Dict[str, Tuple[ScalePoint, ...]] = {
        "local": (ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1),),
        "bake": (
            ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1),
            ScalePoint(f_tasks=2, f_ppn=1, f_nodes=2),
            ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4),
            ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8),
        ),
        "small": (
            ScalePoint(f_tasks=1, f_ppn=1, f_nodes=1),
            ScalePoint(f_tasks=2, f_ppn=1, f_nodes=2),
            ScalePoint(f_tasks=4, f_ppn=1, f_nodes=4),
            ScalePoint(f_tasks=8, f_ppn=1, f_nodes=8),
            ScalePoint(f_tasks=16, f_ppn=1, f_nodes=16),
            ScalePoint(f_tasks=24, f_ppn=1, f_nodes=24),
            ScalePoint(f_tasks=32, f_ppn=1, f_nodes=32),
            ScalePoint(f_tasks=40, f_ppn=1, f_nodes=40),
            ScalePoint(f_tasks=48, f_ppn=1, f_nodes=48),
        ),
        "large": (
            ScalePoint(f_tasks=4, f_ppn=4, f_nodes=1),
            ScalePoint(f_tasks=8, f_ppn=4, f_nodes=2),
            ScalePoint(f_tasks=16, f_ppn=4, f_nodes=4),
            ScalePoint(f_tasks=32, f_ppn=4, f_nodes=8),
            ScalePoint(f_tasks=64, f_ppn=4, f_nodes=16),
            ScalePoint(f_tasks=128, f_ppn=4, f_nodes=32),
            ScalePoint(f_tasks=192, f_ppn=4, f_nodes=48),
            ScalePoint(f_tasks=256, f_ppn=4, f_nodes=64),
        ),
    }

    DEFAULT_SETUPS: Dict[str, str] = {
        "ior": "BASE",
        "lsmio": "NATIVE-M",
        "lmp": "LSMIO",
    }

    ALLOWED_SETUPS: Dict[str, Set[str]] = {
        "ior": {"BASE", "HDF5", "HDF5-C", "COLLECTIVE", "FSYNC", "REVERSE"},
        "lsmio": {
            "NATIVE-M",
            "ADIOS-M",
            "PLUGIN-M",
            "ROCKSDB-M",
            "LEVELDB-M",
            "ADIOS",
            "PLUGIN",
            "ROCKSDB",
            "LEVELDB",
            "MANAGER",
        },
        "lmp": {"LSMIO", "LSMIO-MMAP", "FS"},
    }

    LMP_TASK_TUNING: Dict[int, Tuple[int, int]] = {
        1: (4, 32),
        2: (5, 32),
        4: (6, 64),
        8: (8, 128),
        16: (10, 256),
        24: (12, 512),
        32: (14, 1024),
        40: (15, 1024),
        48: (16, 1024),
    }

    @classmethod
    def getLmpTuning(cls, f_tasks: int) -> Tuple[int, int]:
        """Return (REP, buffer_size_mb) tuple for the given LMP task count."""
        if f_tasks not in cls.LMP_TASK_TUNING:
            raise PlanValidationError(
                f"LMP tuning is not defined for task count {f_tasks}"
            )
        return cls.LMP_TASK_TUNING[f_tasks]

    @classmethod
    def createPlan(
        cls,
        f_request: RunRequest,
        f_profile: SiteProfile,
        f_run_id_source: Optional[Callable[[], str]] = None,
        f_clock: Optional[Callable[[], str]] = None,
        f_token_source: Optional[Callable[[], str]] = None,
    ) -> RunPlan:
        """Validate request and site profile constraints, then generate an immutable RunPlan."""
        # 1. Pure validation of request and profile types and vocabulary BEFORE invoking any sources
        if not isinstance(f_request, RunRequest):
            raise PlanValidationError(f"f_request must be RunRequest, got: {f_request!r}")
        if not isinstance(f_profile, SiteProfile):
            raise PlanValidationError(f"f_profile must be SiteProfile, got: {f_profile!r}")

        f_target = f_request.target.strip().lower()
        if f_target not in cls.DEFAULT_SETUPS:
            raise PlanValidationError(
                f"Unknown benchmark target '{f_request.target}'. Allowed: {sorted(cls.DEFAULT_SETUPS.keys())}"
            )

        f_scale = f_request.scale.strip().lower()
        if f_scale not in cls.SCALE_MATRICES:
            raise PlanValidationError(
                f"Unknown scale '{f_request.scale}'. Allowed: {sorted(cls.SCALE_MATRICES.keys())}"
            )

        # 2. Strict rejection of LMP large scale and verification of LMP task tuning BEFORE sources
        if f_target == "lmp" and f_scale == "large":
            raise PlanValidationError(
                "LMP large scale is unsupported: tuning beyond 48 tasks is undefined"
            )

        if f_target == "lmp":
            for f_sp in cls.SCALE_MATRICES[f_scale]:
                if f_sp.tasks not in cls.LMP_TASK_TUNING:
                    raise PlanValidationError(
                        f"LMP tuning is undefined for task count {f_sp.tasks}"
                    )

        # 3. Setup validation and default resolution BEFORE sources
        if f_request.setup is None or not f_request.setup.strip():
            f_norm_setup = cls.DEFAULT_SETUPS[f_target]
        else:
            f_norm_setup = f_request.setup.strip().upper()

        if f_target == "lsmio" and f_norm_setup == "ENV":
            raise PlanValidationError(
                "LSMIO setup 'ENV' is a diagnostic mode and cannot be used as a run benchmark setup"
            )

        if f_norm_setup not in cls.ALLOWED_SETUPS[f_target]:
            raise PlanValidationError(
                f"Setup '{f_request.setup}' is not valid for target '{f_target}'. "
                f"Allowed setups: {sorted(cls.ALLOWED_SETUPS[f_target])}"
            )

        # 4. Resource policy lookup
        f_shape = "large" if f_scale == "large" else "small"
        f_resource_policy = f_profile.getResourcePolicy(f_shape)
        f_scale_points = cls.SCALE_MATRICES[f_scale]

        # 5. ScheduledPointResources calculation
        f_scheduled_points: List[ScheduledPointResources] = []
        for f_sp in f_scale_points:
            # Walltime calculation
            if f_resource_policy.walltime_policy == "slurm_nodes":
                f_wallhour = 2 + (f_sp.nodes // 3)
                f_walltime = f"{f_wallhour:02d}:00:00"
            elif f_resource_policy.walltime_policy == "fixed_06:00:00":
                f_walltime = "06:00:00"
            elif (
                isinstance(f_resource_policy.walltime_policy, str)
                and f_resource_policy.walltime_policy.startswith("fixed_")
            ):
                f_walltime = f_resource_policy.walltime_policy[len("fixed_"):]
            else:
                f_walltime = "00:00:00"

            # Backend-specific resource mapping
            if f_profile.scheduler == SchedulerKind.PBS:
                f_res = ScheduledPointResources(
                    f_walltime=f_walltime,
                    f_select_chunks=f_sp.nodes,
                    f_ncpus=f_sp.ppn,
                    f_mpiprocs=f_sp.ppn,
                    f_mem=f_resource_policy.memory,
                    f_mail_mode=f_resource_policy.mail_mode.value if f_resource_policy.mail_mode else None,
                    f_queue=f_resource_policy.queue,
                    f_partition=f_resource_policy.partition,
                    f_qos=f_resource_policy.qos,
                    f_pmem=f_resource_policy.pmem,
                    f_pvmem=f_resource_policy.pvmem,
                )
            elif f_profile.scheduler == SchedulerKind.SLURM:
                f_res = ScheduledPointResources(
                    f_walltime=f_walltime,
                    f_select_chunks=None,
                    f_ncpus=None,
                    f_mpiprocs=None,
                    f_mem=f_resource_policy.memory,
                    f_mail_mode=f_resource_policy.mail_mode.value if f_resource_policy.mail_mode else None,
                    f_queue=f_resource_policy.queue,
                    f_partition=f_resource_policy.partition,
                    f_qos=f_resource_policy.qos,
                    f_pmem=f_resource_policy.pmem,
                    f_pvmem=f_resource_policy.pvmem,
                )
            else:
                # FAKE or unmanaged
                f_res = ScheduledPointResources(
                    f_walltime=f_walltime,
                    f_select_chunks=None,
                    f_ncpus=None,
                    f_mpiprocs=None,
                    f_mem=None,
                    f_mail_mode=None,
                    f_queue=None,
                    f_partition=None,
                    f_qos=None,
                    f_pmem=None,
                    f_pvmem=None,
                )
            f_scheduled_points.append(f_res)

        # 6. Now generate correlation tokens, run ID, and manifest timestamp
        if f_token_source is None:
            f_eff_token_source: Callable[[], str] = lambda: f"lm-{secrets.token_hex(12)}"
        else:
            f_eff_token_source = f_token_source

        f_tokens: List[str] = []
        f_seen_tokens: Set[str] = set()
        for _ in f_scale_points:
            f_token = f_eff_token_source()
            if not isinstance(f_token, str) or not cls.TOKEN_PATTERN.match(f_token):
                raise PlanValidationError(
                    f"Generated correlation token '{f_token}' is invalid; must match '^lm-[0-9a-f]{{24}}$'"
                )
            if f_token in f_seen_tokens:
                raise PlanValidationError(
                    f"Duplicate correlation token generated: '{f_token}'"
                )
            f_seen_tokens.add(f_token)
            f_tokens.append(f_token)

        if f_run_id_source is None:
            f_eff_run_id_source: Callable[[], str] = (
                lambda: f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
            )
        else:
            f_eff_run_id_source = f_run_id_source

        f_run_id = f_eff_run_id_source()
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise PlanValidationError(f"run_id must be a non-empty string, got: {f_run_id!r}")

        if f_clock is None:
            f_eff_clock: Callable[[], str] = (
                lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        else:
            f_eff_clock = f_clock

        f_manifest_timestamp = f_eff_clock()
        if not isinstance(f_manifest_timestamp, str) or not f_manifest_timestamp.strip():
            raise PlanValidationError(
                f"manifest_timestamp must be a non-empty string, got: {f_manifest_timestamp!r}"
            )

        f_normalized_request = RunRequest(
            f_target=f_target,
            f_scale=f_scale,
            f_ssd=f_request.ssd,
            f_setup=f_norm_setup,
        )

        return RunPlan(
            f_run_id=f_run_id,
            f_request=f_normalized_request,
            f_profile=f_profile,
            f_scale_points=f_scale_points,
            f_combinations=cls.ORDERED_COMBINATIONS,
            f_scheduled_points=tuple(f_scheduled_points),
            f_tokens=tuple(f_tokens),
            f_manifest_timestamp=f_manifest_timestamp,
        )


class ManifestDocument:
    """Immutable representation of a validated schema-version-1 run manifest document."""

    __slots__ = (
        "m_schema_version",
        "m_run_id",
        "m_created_at_utc",
        "m_request",
        "m_site",
        "m_plan",
        "m_scale_points",
        "m_combinations",
        "m_points",
        "m_tokens",
        "_frozen",
    )

    def __init__(
        self,
        f_schema_version: int,
        f_run_id: str,
        f_created_at_utc: str,
        f_request: RunRequest,
        f_site: SiteProfile,
        f_plan: Mapping[str, Any],
        f_scale_points: Sequence[ScalePoint],
        f_combinations: Sequence[Combination],
        f_points: Sequence[ScheduledPointResources],
        f_tokens: Sequence[str],
    ) -> None:
        if not isinstance(f_schema_version, int) or isinstance(f_schema_version, bool) or f_schema_version != 1:
            raise ManifestValidationError(
                f"schema_version must be integer 1, got: {f_schema_version!r}"
            )
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise ManifestValidationError(
                f"run_id must be a non-empty string, got: {f_run_id!r}"
            )
        if not isinstance(f_created_at_utc, str) or not f_created_at_utc.strip():
            raise ManifestValidationError(
                f"created_at_utc must be a non-empty string, got: {f_created_at_utc!r}"
            )
        if not ManifestSerializer.ISO_UTC_PATTERN.match(f_created_at_utc):
            raise ManifestValidationError(
                f"created_at_utc '{f_created_at_utc}' must match exact ISO 8601 UTC format YYYY-MM-DDTHH:MM:SSZ"
            )
        try:
            datetime.strptime(f_created_at_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as f_err:
            raise ManifestValidationError(
                f"created_at_utc '{f_created_at_utc}' is not a valid UTC date/time: {f_err}"
            )

        if not isinstance(f_request, RunRequest):
            raise ManifestValidationError(
                f"request must be a RunRequest, got: {f_request!r}"
            )
        if not isinstance(f_site, SiteProfile):
            raise ManifestValidationError(
                f"site must be a SiteProfile, got: {f_site!r}"
            )
        if not isinstance(f_plan, Mapping):
            raise ManifestValidationError(
                f"plan must be a mapping, got: {f_plan!r}"
            )
        if not f_scale_points:
            raise ManifestValidationError("scale_points must not be empty")
        if not f_combinations:
            raise ManifestValidationError("combinations must not be empty")
        if len(f_points) != len(f_scale_points):
            raise ManifestValidationError(
                f"points count ({len(f_points)}) must equal scale_points count ({len(f_scale_points)})"
            )
        if len(f_tokens) != len(f_points):
            raise ManifestValidationError(
                f"tokens count ({len(f_tokens)}) must equal points count ({len(f_points)})"
            )

        f_seen_tokens: Set[str] = set()
        for f_tok in f_tokens:
            if not isinstance(f_tok, str) or not RunPlanner.TOKEN_PATTERN.match(f_tok):
                raise ManifestValidationError(
                    f"Token '{f_tok}' is invalid; must match '^lm-[0-9a-f]{{24}}$'"
                )
            if f_tok in f_seen_tokens:
                raise ManifestValidationError(f"Duplicate correlation token: '{f_tok}'")
            f_seen_tokens.add(f_tok)

        super().__setattr__("m_schema_version", f_schema_version)
        super().__setattr__("m_run_id", f_run_id.strip())
        super().__setattr__("m_created_at_utc", f_created_at_utc.strip())
        super().__setattr__("m_request", f_request)
        super().__setattr__("m_site", f_site)
        super().__setattr__("m_plan", dict(f_plan))
        super().__setattr__("m_scale_points", tuple(f_scale_points))
        super().__setattr__("m_combinations", tuple(f_combinations))
        super().__setattr__("m_points", tuple(f_points))
        super().__setattr__("m_tokens", tuple(f_tokens))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def schema_version(self) -> int:
        return self.m_schema_version

    @property
    def run_id(self) -> str:
        return self.m_run_id

    @property
    def created_at_utc(self) -> str:
        return self.m_created_at_utc

    @property
    def request(self) -> RunRequest:
        return self.m_request

    @property
    def site(self) -> SiteProfile:
        return self.m_site

    @property
    def plan(self) -> Dict[str, Any]:
        return dict(self.m_plan)

    @property
    def scale_points(self) -> Tuple[ScalePoint, ...]:
        return self.m_scale_points

    @property
    def combinations(self) -> Tuple[Combination, ...]:
        return self.m_combinations

    @property
    def points(self) -> Tuple[ScheduledPointResources, ...]:
        return self.m_points

    @property
    def tokens(self) -> Tuple[str, ...]:
        return self.m_tokens

    def toDict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.m_schema_version,
            "run_id": self.m_run_id,
            "created_at_utc": self.m_created_at_utc,
            "request": self.m_request.toDict(),
            "site": self.m_site.toDict(),
            "plan": dict(self.m_plan),
            "scale_points": [f_sp.toDict() for f_sp in self.m_scale_points],
            "combinations": [f_c.toDict() for f_c in self.m_combinations],
            "points": [f_p.toDict() for f_p in self.m_points],
            "tokens": list(self.m_tokens),
        }

    def toJson(self) -> str:
        return ManifestSerializer.serializeDocument(self)

    def toRunPlan(self) -> RunPlan:
        return RunPlan(
            f_run_id=self.m_run_id,
            f_request=self.m_request,
            f_profile=self.m_site,
            f_scale_points=self.m_scale_points,
            f_combinations=self.m_combinations,
            f_scheduled_points=self.m_points,
            f_tokens=self.m_tokens,
            f_manifest_timestamp=self.m_created_at_utc,
        )

    def __repr__(self) -> str:
        return (
            f"ManifestDocument(schema_version={self.m_schema_version}, "
            f"run_id={self.m_run_id!r}, "
            f"created_at_utc={self.m_created_at_utc!r}, "
            f"request={self.m_request!r}, "
            f"site={self.m_site!r}, "
            f"plan={self.m_plan!r}, "
            f"scale_points={self.m_scale_points!r}, "
            f"combinations={self.m_combinations!r}, "
            f"points={self.m_points!r}, "
            f"tokens={self.m_tokens!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ManifestDocument):
            return (
                self.m_schema_version == f_other.m_schema_version
                and self.m_run_id == f_other.m_run_id
                and self.m_created_at_utc == f_other.m_created_at_utc
                and self.m_request == f_other.m_request
                and self.m_site.toDict() == f_other.m_site.toDict()
                and self.m_plan == f_other.m_plan
                and self.m_scale_points == f_other.m_scale_points
                and self.m_combinations == f_other.m_combinations
                and self.m_points == f_other.m_points
                and self.m_tokens == f_other.m_tokens
            )
        return False


class ManifestSerializer:
    """Canonical schema-version-1 serializer and fail-closed validator for run manifest documents."""

    ISO_UTC_PATTERN: re.Pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    REQUIRED_TOP_LEVEL_KEYS: Set[str] = {
        "schema_version",
        "run_id",
        "created_at_utc",
        "request",
        "site",
        "plan",
        "scale_points",
        "combinations",
        "points",
        "tokens",
    }

    REQUIRED_REQUEST_KEYS: Set[str] = {"target", "scale", "ssd", "setup"}
    REQUIRED_PLAN_KEYS: Set[str] = {"target", "scale", "storage", "setup"}
    REQUIRED_SCALE_POINT_KEYS: Set[str] = {"tasks", "ppn", "nodes"}
    REQUIRED_COMBINATION_KEYS: Set[str] = {
        "processes",
        "block_size",
        "stripe_count",
        "block_bytes",
        "key_count",
        "segment_count",
    }
    REQUIRED_POINT_KEYS: Set[str] = {
        "walltime",
        "select_chunks",
        "ncpus",
        "mpiprocs",
        "mem",
        "mail_mode",
        "queue",
        "partition",
        "qos",
        "pmem",
        "pvmem",
    }
    REQUIRED_SITE_KEYS: Set[str] = {
        "name",
        "scheduler",
        "launcher",
        "certification",
        "test_only",
        "benchmark_roots",
        "install_prefix",
        "executables",
        "modules",
        "resources",
        "rank_identity",
        "cancellation",
        "lustre_pools",
    }
    REQUIRED_BENCHMARK_ROOT_KEYS: Set[str] = {"hdd", "ssd"}
    REQUIRED_LUSTRE_POOL_KEYS: Set[str] = {"hdd", "ssd"}
    REQUIRED_RESOURCE_SHAPES: Set[str] = {"small", "large"}
    REQUIRED_RESOURCE_SHAPE_KEYS: Set[str] = {
        "walltime_policy",
        "queue",
        "partition",
        "qos",
        "memory",
        "mail_mode",
        "pmem",
        "pvmem",
    }
    REQUIRED_RANK_IDENTITY_KEYS: Set[str] = {"global", "node", "local"}
    REQUIRED_CANCELLATION_KEYS: Set[str] = {"poll_interval_seconds", "grace_seconds"}

    @classmethod
    def serialize(cls, f_plan: Union[RunPlan, ManifestDocument]) -> str:
        """Serialize a RunPlan or ManifestDocument into canonical schema-version-1 JSON."""
        if isinstance(f_plan, RunPlan):
            if not isinstance(f_plan.manifest_timestamp, str) or not f_plan.manifest_timestamp.strip():
                raise ManifestValidationError("manifest_timestamp must be a non-empty string")
            if not cls.ISO_UTC_PATTERN.match(f_plan.manifest_timestamp):
                raise ManifestValidationError(
                    f"created_at_utc '{f_plan.manifest_timestamp}' must match exact ISO 8601 UTC format YYYY-MM-DDTHH:MM:SSZ"
                )
            try:
                datetime.strptime(f_plan.manifest_timestamp, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as f_err:
                raise ManifestValidationError(
                    f"created_at_utc '{f_plan.manifest_timestamp}' is not a valid UTC date/time: {f_err}"
                )

            f_dict: Dict[str, Any] = {
                "schema_version": 1,
                "run_id": f_plan.run_id,
                "created_at_utc": f_plan.manifest_timestamp,
                "request": f_plan.request.toDict(),
                "site": f_plan.profile.toDict(),
                "plan": {
                    "target": f_plan.request.target,
                    "scale": f_plan.request.scale,
                    "storage": f_plan.request.storage.value,
                    "setup": f_plan.request.setup,
                },
                "scale_points": [f_sp.toDict() for f_sp in f_plan.scale_points],
                "combinations": [f_c.toDict() for f_c in f_plan.combinations],
                "points": [f_pt.toDict() for f_pt in f_plan.scheduled_points],
                "tokens": list(f_plan.tokens),
            }
        elif isinstance(f_plan, ManifestDocument):
            f_dict = f_plan.toDict()
        else:
            raise ManifestValidationError(
                f"Expected RunPlan or ManifestDocument, got: {type(f_plan).__name__}"
            )

        return json.dumps(f_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def serializeDocument(cls, f_doc: ManifestDocument) -> str:
        """Serialize a ManifestDocument into canonical schema-version-1 JSON."""
        return cls.serialize(f_doc)

    @classmethod
    def deserialize(cls, f_source: Union[str, bytes, Dict[str, Any]]) -> ManifestDocument:
        """Deserialize and fail-closed validate JSON string, bytes, or dict into a ManifestDocument."""
        if isinstance(f_source, bytes):
            try:
                f_source = f_source.decode("utf-8")
            except UnicodeDecodeError as f_err:
                raise ManifestValidationError(f"Invalid UTF-8 source: {f_err}")

        if isinstance(f_source, str):
            if not f_source.strip():
                raise ManifestValidationError("Manifest JSON source is empty")
            try:
                f_raw = json.loads(f_source)
            except json.JSONDecodeError as f_err:
                raise ManifestValidationError(f"Invalid JSON syntax: {f_err}")
        elif isinstance(f_source, dict):
            f_raw = f_source
        else:
            raise ManifestValidationError(
                f"f_source must be str, bytes, or dict, got: {type(f_source).__name__}"
            )

        if not isinstance(f_raw, dict):
            raise ManifestValidationError(
                f"Manifest root must be a JSON object (dict), got: {type(f_raw).__name__}"
            )

        # 1. Strict top-level key check
        f_top_keys = set(f_raw.keys())
        f_missing_top = cls.REQUIRED_TOP_LEVEL_KEYS - f_top_keys
        if f_missing_top:
            raise ManifestValidationError(
                f"Missing required top-level manifest keys: {sorted(f_missing_top)}"
            )
        f_extra_top = f_top_keys - cls.REQUIRED_TOP_LEVEL_KEYS
        if f_extra_top:
            raise ManifestValidationError(
                f"Unexpected extra top-level manifest keys: {sorted(f_extra_top)}"
            )

        # 2. Validate schema_version
        f_ver = f_raw["schema_version"]
        if not isinstance(f_ver, int) or isinstance(f_ver, bool) or f_ver != 1:
            raise ManifestValidationError(
                f"schema_version must be integer 1, got: {f_ver!r}"
            )

        # 3. Validate run_id
        f_run_id = f_raw["run_id"]
        if not isinstance(f_run_id, str) or not f_run_id.strip():
            raise ManifestValidationError(
                f"run_id must be a non-empty string, got: {f_run_id!r}"
            )

        # 4. Validate created_at_utc
        f_created_at_utc = f_raw["created_at_utc"]
        if not isinstance(f_created_at_utc, str) or not f_created_at_utc.strip():
            raise ManifestValidationError(
                f"created_at_utc must be a non-empty string, got: {f_created_at_utc!r}"
            )
        if not cls.ISO_UTC_PATTERN.match(f_created_at_utc):
            raise ManifestValidationError(
                f"created_at_utc '{f_created_at_utc}' must match exact ISO 8601 UTC format YYYY-MM-DDTHH:MM:SSZ"
            )
        try:
            datetime.strptime(f_created_at_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as f_err:
            raise ManifestValidationError(
                f"created_at_utc '{f_created_at_utc}' is not a valid UTC date/time: {f_err}"
            )

        # 5. Validate request
        f_req_raw = f_raw["request"]
        if not isinstance(f_req_raw, dict):
            raise ManifestValidationError(
                f"request must be a dict, got: {type(f_req_raw).__name__}"
            )
        f_req_keys = set(f_req_raw.keys())
        f_missing_req = cls.REQUIRED_REQUEST_KEYS - f_req_keys
        if f_missing_req:
            raise ManifestValidationError(
                f"Missing keys in request: {sorted(f_missing_req)}"
            )
        f_extra_req = f_req_keys - cls.REQUIRED_REQUEST_KEYS
        if f_extra_req:
            raise ManifestValidationError(
                f"Unexpected extra keys in request: {sorted(f_extra_req)}"
            )
        if not isinstance(f_req_raw["target"], str) or not f_req_raw["target"].strip():
            raise ManifestValidationError("request.target must be a non-empty string")
        if not isinstance(f_req_raw["scale"], str) or not f_req_raw["scale"].strip():
            raise ManifestValidationError("request.scale must be a non-empty string")
        if not isinstance(f_req_raw["ssd"], bool):
            raise ManifestValidationError("request.ssd must be a boolean")
        if f_req_raw["setup"] is not None and not isinstance(f_req_raw["setup"], str):
            raise ManifestValidationError("request.setup must be a string or null")

        try:
            f_request = RunRequest(
                f_target=f_req_raw["target"],
                f_scale=f_req_raw["scale"],
                f_ssd=f_req_raw["ssd"],
                f_setup=f_req_raw["setup"],
            )
        except Exception as f_err:
            raise ManifestValidationError(f"Invalid request record: {f_err}")

        # 6. Validate plan
        f_plan_raw = f_raw["plan"]
        if not isinstance(f_plan_raw, dict):
            raise ManifestValidationError(
                f"plan must be a dict, got: {type(f_plan_raw).__name__}"
            )
        f_plan_keys = set(f_plan_raw.keys())
        f_missing_plan = cls.REQUIRED_PLAN_KEYS - f_plan_keys
        if f_missing_plan:
            raise ManifestValidationError(
                f"Missing keys in plan: {sorted(f_missing_plan)}"
            )
        f_extra_plan = f_plan_keys - cls.REQUIRED_PLAN_KEYS
        if f_extra_plan:
            raise ManifestValidationError(
                f"Unexpected extra keys in plan: {sorted(f_extra_plan)}"
            )
        if not isinstance(f_plan_raw["target"], str) or not f_plan_raw["target"].strip():
            raise ManifestValidationError("plan.target must be a non-empty string")
        if not isinstance(f_plan_raw["scale"], str) or not f_plan_raw["scale"].strip():
            raise ManifestValidationError("plan.scale must be a non-empty string")
        if not isinstance(f_plan_raw["storage"], str) or f_plan_raw["storage"] not in {"hdd", "ssd"}:
            raise ManifestValidationError("plan.storage must be 'hdd' or 'ssd'")
        if not isinstance(f_plan_raw["setup"], str) or not f_plan_raw["setup"].strip():
            raise ManifestValidationError("plan.setup must be a non-empty string")

        # 7. Validate scale_points
        f_sp_raw = f_raw["scale_points"]
        if not isinstance(f_sp_raw, list) or not f_sp_raw:
            raise ManifestValidationError("scale_points must be a non-empty list")
        f_scale_points: List[ScalePoint] = []
        for f_idx, f_sp_item in enumerate(f_sp_raw):
            if not isinstance(f_sp_item, dict):
                raise ManifestValidationError(
                    f"scale_points[{f_idx}] must be a dict, got: {type(f_sp_item).__name__}"
                )
            f_item_keys = set(f_sp_item.keys())
            f_missing_sp = cls.REQUIRED_SCALE_POINT_KEYS - f_item_keys
            if f_missing_sp:
                raise ManifestValidationError(
                    f"Missing keys in scale_points[{f_idx}]: {sorted(f_missing_sp)}"
                )
            f_extra_sp = f_item_keys - cls.REQUIRED_SCALE_POINT_KEYS
            if f_extra_sp:
                raise ManifestValidationError(
                    f"Unexpected extra keys in scale_points[{f_idx}]: {sorted(f_extra_sp)}"
                )
            if isinstance(f_sp_item["tasks"], bool) or isinstance(f_sp_item["ppn"], bool) or isinstance(f_sp_item["nodes"], bool):
                raise ManifestValidationError(f"scale_points[{f_idx}] values must be integers, not booleans")
            try:
                f_scale_points.append(
                    ScalePoint(
                        f_tasks=f_sp_item["tasks"],
                        f_ppn=f_sp_item["ppn"],
                        f_nodes=f_sp_item["nodes"],
                    )
                )
            except Exception as f_err:
                raise ManifestValidationError(
                    f"Invalid scale point at index {f_idx}: {f_err}"
                )

        # 8. Validate combinations
        f_combo_raw = f_raw["combinations"]
        if not isinstance(f_combo_raw, list) or not f_combo_raw:
            raise ManifestValidationError("combinations must be a non-empty list")
        f_combinations: List[Combination] = []
        for f_idx, f_c_item in enumerate(f_combo_raw):
            if not isinstance(f_c_item, dict):
                raise ManifestValidationError(
                    f"combinations[{f_idx}] must be a dict, got: {type(f_c_item).__name__}"
                )
            f_item_keys = set(f_c_item.keys())
            f_missing_c = cls.REQUIRED_COMBINATION_KEYS - f_item_keys
            if f_missing_c:
                raise ManifestValidationError(
                    f"Missing keys in combinations[{f_idx}]: {sorted(f_missing_c)}"
                )
            f_extra_c = f_item_keys - cls.REQUIRED_COMBINATION_KEYS
            if f_extra_c:
                raise ManifestValidationError(
                    f"Unexpected extra keys in combinations[{f_idx}]: {sorted(f_extra_c)}"
                )
            for f_int_key in ("processes", "stripe_count", "block_bytes", "key_count", "segment_count"):
                if isinstance(f_c_item[f_int_key], bool):
                    raise ManifestValidationError(
                        f"combinations[{f_idx}].{f_int_key} must be integer, not boolean"
                    )
            try:
                f_combinations.append(
                    Combination(
                        f_processes=f_c_item["processes"],
                        f_block_size=f_c_item["block_size"],
                        f_stripe_count=f_c_item["stripe_count"],
                        f_block_bytes=f_c_item["block_bytes"],
                        f_key_count=f_c_item["key_count"],
                        f_segment_count=f_c_item["segment_count"],
                    )
                )
            except Exception as f_err:
                raise ManifestValidationError(
                    f"Invalid combination at index {f_idx}: {f_err}"
                )

        # 9. Validate points
        f_pts_raw = f_raw["points"]
        if not isinstance(f_pts_raw, list) or not f_pts_raw:
            raise ManifestValidationError("points must be a non-empty list")
        if len(f_pts_raw) != len(f_scale_points):
            raise ManifestValidationError(
                f"points count ({len(f_pts_raw)}) must match scale_points count ({len(f_scale_points)})"
            )
        f_points: List[ScheduledPointResources] = []
        for f_idx, f_pt_item in enumerate(f_pts_raw):
            if not isinstance(f_pt_item, dict):
                raise ManifestValidationError(
                    f"points[{f_idx}] must be a dict, got: {type(f_pt_item).__name__}"
                )
            f_item_keys = set(f_pt_item.keys())
            f_missing_pt = cls.REQUIRED_POINT_KEYS - f_item_keys
            if f_missing_pt:
                raise ManifestValidationError(
                    f"Missing keys in points[{f_idx}]: {sorted(f_missing_pt)}"
                )
            f_extra_pt = f_item_keys - cls.REQUIRED_POINT_KEYS
            if f_extra_pt:
                raise ManifestValidationError(
                    f"Unexpected extra keys in points[{f_idx}]: {sorted(f_extra_pt)}"
                )
            for f_opt_int_key in ("select_chunks", "ncpus", "mpiprocs"):
                if isinstance(f_pt_item[f_opt_int_key], bool):
                    raise ManifestValidationError(
                        f"points[{f_idx}].{f_opt_int_key} must be int or null, not boolean"
                    )
            try:
                f_points.append(
                    ScheduledPointResources(
                        f_walltime=f_pt_item["walltime"],
                        f_select_chunks=f_pt_item["select_chunks"],
                        f_ncpus=f_pt_item["ncpus"],
                        f_mpiprocs=f_pt_item["mpiprocs"],
                        f_mem=f_pt_item["mem"],
                        f_mail_mode=f_pt_item["mail_mode"],
                        f_queue=f_pt_item["queue"],
                        f_partition=f_pt_item["partition"],
                        f_qos=f_pt_item["qos"],
                        f_pmem=f_pt_item["pmem"],
                        f_pvmem=f_pt_item["pvmem"],
                    )
                )
            except Exception as f_err:
                raise ManifestValidationError(
                    f"Invalid scheduled point at index {f_idx}: {f_err}"
                )

        # 10. Validate tokens
        f_tokens_raw = f_raw["tokens"]
        if not isinstance(f_tokens_raw, list) or not f_tokens_raw:
            raise ManifestValidationError("tokens must be a non-empty list")
        if len(f_tokens_raw) != len(f_points):
            raise ManifestValidationError(
                f"tokens count ({len(f_tokens_raw)}) must match points count ({len(f_points)})"
            )
        f_seen_tokens: Set[str] = set()
        f_tokens: List[str] = []
        for f_idx, f_tok in enumerate(f_tokens_raw):
            if not isinstance(f_tok, str) or not RunPlanner.TOKEN_PATTERN.match(f_tok):
                raise ManifestValidationError(
                    f"tokens[{f_idx}] '{f_tok}' is invalid; must match '^lm-[0-9a-f]{{24}}$'"
                )
            if f_tok in f_seen_tokens:
                raise ManifestValidationError(
                    f"Duplicate token '{f_tok}' in tokens list at index {f_idx}"
                )
            f_seen_tokens.add(f_tok)
            f_tokens.append(f_tok)

        # 11. Validate site
        f_site_raw = f_raw["site"]
        if not isinstance(f_site_raw, dict):
            raise ManifestValidationError(
                f"site must be a dict, got: {type(f_site_raw).__name__}"
            )
        f_site_keys = set(f_site_raw.keys())
        f_missing_site = cls.REQUIRED_SITE_KEYS - f_site_keys
        if f_missing_site:
            raise ManifestValidationError(
                f"Missing keys in site: {sorted(f_missing_site)}"
            )
        f_extra_site = f_site_keys - cls.REQUIRED_SITE_KEYS
        if f_extra_site:
            raise ManifestValidationError(
                f"Unexpected extra keys in site: {sorted(f_extra_site)}"
            )

        if not isinstance(f_site_raw["name"], str) or not f_site_raw["name"].strip():
            raise ManifestValidationError("site.name must be a non-empty string")
        if not isinstance(f_site_raw["scheduler"], str) or f_site_raw["scheduler"] not in {"slurm", "pbs", "fake"}:
            raise ManifestValidationError(f"Invalid site.scheduler: {f_site_raw.get('scheduler')!r}")
        if not isinstance(f_site_raw["launcher"], str) or not f_site_raw["launcher"].strip():
            raise ManifestValidationError("site.launcher must be a non-empty string")
        if not isinstance(f_site_raw["certification"], str) or f_site_raw["certification"] not in {"configured", "certified"}:
            raise ManifestValidationError(f"Invalid site.certification: {f_site_raw.get('certification')!r}")
        if not isinstance(f_site_raw["test_only"], bool):
            raise ManifestValidationError("site.test_only must be a boolean")
        if not isinstance(f_site_raw["install_prefix"], str) or not f_site_raw["install_prefix"].startswith("/"):
            raise ManifestValidationError("site.install_prefix must be an absolute path")

        # Validate benchmark_roots
        f_bm_roots = f_site_raw["benchmark_roots"]
        if not isinstance(f_bm_roots, dict):
            raise ManifestValidationError("site.benchmark_roots must be a dict")
        f_bm_keys = set(f_bm_roots.keys())
        f_missing_bm = cls.REQUIRED_BENCHMARK_ROOT_KEYS - f_bm_keys
        if f_missing_bm:
            raise ManifestValidationError(f"Missing keys in site.benchmark_roots: {sorted(f_missing_bm)}")
        f_extra_bm = f_bm_keys - cls.REQUIRED_BENCHMARK_ROOT_KEYS
        if f_extra_bm:
            raise ManifestValidationError(f"Unexpected extra keys in site.benchmark_roots: {sorted(f_extra_bm)}")
        for f_sc_name, f_sc_path in f_bm_roots.items():
            if not isinstance(f_sc_path, str) or not f_sc_path.startswith("/"):
                raise ManifestValidationError(
                    f"site.benchmark_roots.{f_sc_name} must be an absolute path, got: {f_sc_path!r}"
                )

        # Validate lustre_pools
        f_l_pools = f_site_raw["lustre_pools"]
        if not isinstance(f_l_pools, dict):
            raise ManifestValidationError("site.lustre_pools must be a dict")
        f_lp_keys = set(f_l_pools.keys())
        f_missing_lp = cls.REQUIRED_LUSTRE_POOL_KEYS - f_lp_keys
        if f_missing_lp:
            raise ManifestValidationError(f"Missing keys in site.lustre_pools: {sorted(f_missing_lp)}")
        f_extra_lp = f_lp_keys - cls.REQUIRED_LUSTRE_POOL_KEYS
        if f_extra_lp:
            raise ManifestValidationError(f"Unexpected extra keys in site.lustre_pools: {sorted(f_extra_lp)}")
        for f_lp_name, f_lp_val in f_l_pools.items():
            if f_lp_val is not None and not isinstance(f_lp_val, str):
                raise ManifestValidationError(
                    f"site.lustre_pools.{f_lp_name} must be string or null, got: {f_lp_val!r}"
                )

        # Validate executables
        f_ex_raw = f_site_raw["executables"]
        if not isinstance(f_ex_raw, dict):
            raise ManifestValidationError("site.executables must be a dict")
        f_ex_keys = set(f_ex_raw.keys())
        f_missing_ex = ExecutableRegistry.REQUIRED_EXECUTABLES - f_ex_keys
        if f_missing_ex:
            raise ManifestValidationError(f"Missing keys in site.executables: {sorted(f_missing_ex)}")
        f_extra_ex = f_ex_keys - ExecutableRegistry.REQUIRED_EXECUTABLES
        if f_extra_ex:
            raise ManifestValidationError(f"Unexpected extra keys in site.executables: {sorted(f_extra_ex)}")
        for f_ex_name, f_ex_path in f_ex_raw.items():
            if not isinstance(f_ex_path, str) or not f_ex_path.startswith("/"):
                raise ManifestValidationError(
                    f"site.executables.{f_ex_name} must be an absolute path, got: {f_ex_path!r}"
                )

        # Validate modules
        f_mods = f_site_raw["modules"]
        if not isinstance(f_mods, list):
            raise ManifestValidationError("site.modules must be a list of strings")
        for f_idx, f_m in enumerate(f_mods):
            if not isinstance(f_m, str):
                raise ManifestValidationError(f"site.modules[{f_idx}] must be a string")

        # Validate resources
        f_res_raw = f_site_raw["resources"]
        if not isinstance(f_res_raw, dict):
            raise ManifestValidationError("site.resources must be a dict")
        f_res_keys = set(f_res_raw.keys())
        f_missing_res = cls.REQUIRED_RESOURCE_SHAPES - f_res_keys
        if f_missing_res:
            raise ManifestValidationError(f"Missing keys in site.resources: {sorted(f_missing_res)}")
        f_extra_res = f_res_keys - cls.REQUIRED_RESOURCE_SHAPES
        if f_extra_res:
            raise ManifestValidationError(f"Unexpected extra keys in site.resources: {sorted(f_extra_res)}")
        f_resources_dict: Dict[str, ResourcePolicy] = {}
        for f_shp, f_shp_raw in f_res_raw.items():
            if not isinstance(f_shp_raw, dict):
                raise ManifestValidationError(f"site.resources.{f_shp} must be a dict")
            f_shp_keys = set(f_shp_raw.keys())
            f_missing_shp = cls.REQUIRED_RESOURCE_SHAPE_KEYS - f_shp_keys
            if f_missing_shp:
                raise ManifestValidationError(
                    f"Missing keys in site.resources.{f_shp}: {sorted(f_missing_shp)}"
                )
            f_extra_shp = f_shp_keys - cls.REQUIRED_RESOURCE_SHAPE_KEYS
            if f_extra_shp:
                raise ManifestValidationError(
                    f"Unexpected extra keys in site.resources.{f_shp}: {sorted(f_extra_shp)}"
                )
            f_sched_enum = SchedulerKind(f_site_raw["scheduler"])
            f_mail_mode_obj = None
            if f_shp_raw["mail_mode"] is not None:
                if f_sched_enum == SchedulerKind.SLURM:
                    try:
                        f_mail_mode_obj = SlurmMailMode(f_shp_raw["mail_mode"])
                    except ValueError:
                        raise ManifestValidationError(
                            f"Invalid Slurm mail_mode: {f_shp_raw['mail_mode']!r}"
                        )
                elif f_sched_enum == SchedulerKind.PBS:
                    try:
                        f_mail_mode_obj = PbsMailMode(f_shp_raw["mail_mode"])
                    except ValueError:
                        raise ManifestValidationError(
                            f"Invalid PBS mail_mode: {f_shp_raw['mail_mode']!r}"
                        )
                else:
                    raise ManifestValidationError(
                        f"Fake scheduler cannot accept mail_mode: {f_shp_raw['mail_mode']!r}"
                    )
            try:
                f_resources_dict[f_shp] = ResourcePolicy(
                    f_scheduler=f_sched_enum,
                    f_walltime_policy=f_shp_raw["walltime_policy"],
                    f_queue=f_shp_raw["queue"],
                    f_partition=f_shp_raw["partition"],
                    f_qos=f_shp_raw["qos"],
                    f_memory=f_shp_raw["memory"],
                    f_mail_mode=f_mail_mode_obj,
                    f_pmem=f_shp_raw["pmem"],
                    f_pvmem=f_shp_raw["pvmem"],
                )
            except Exception as f_err:
                raise ManifestValidationError(f"Invalid resource policy for shape '{f_shp}': {f_err}")

        # Validate rank_identity
        f_ri_raw = f_site_raw["rank_identity"]
        if not isinstance(f_ri_raw, dict):
            raise ManifestValidationError("site.rank_identity must be a dict")
        f_ri_keys = set(f_ri_raw.keys())
        f_missing_ri = cls.REQUIRED_RANK_IDENTITY_KEYS - f_ri_keys
        if f_missing_ri:
            raise ManifestValidationError(f"Missing keys in site.rank_identity: {sorted(f_missing_ri)}")
        f_extra_ri = f_ri_keys - cls.REQUIRED_RANK_IDENTITY_KEYS
        if f_extra_ri:
            raise ManifestValidationError(f"Unexpected extra keys in site.rank_identity: {sorted(f_extra_ri)}")
        try:
            f_rank_identity = RankIdentityPolicy(
                f_global_rank=f_ri_raw["global"],
                f_node_name=f_ri_raw["node"],
                f_local_rank=f_ri_raw["local"],
            )
        except Exception as f_err:
            raise ManifestValidationError(f"Invalid site.rank_identity: {f_err}")

        # Validate cancellation
        f_canc_raw = f_site_raw["cancellation"]
        if not isinstance(f_canc_raw, dict):
            raise ManifestValidationError("site.cancellation must be a dict")
        f_canc_keys = set(f_canc_raw.keys())
        f_missing_canc = cls.REQUIRED_CANCELLATION_KEYS - f_canc_keys
        if f_missing_canc:
            raise ManifestValidationError(f"Missing keys in site.cancellation: {sorted(f_missing_canc)}")
        f_extra_canc = f_canc_keys - cls.REQUIRED_CANCELLATION_KEYS
        if f_extra_canc:
            raise ManifestValidationError(f"Unexpected extra keys in site.cancellation: {sorted(f_extra_canc)}")
        if isinstance(f_canc_raw["poll_interval_seconds"], bool) or isinstance(f_canc_raw["grace_seconds"], bool):
            raise ManifestValidationError("site.cancellation values must be integers, not booleans")
        try:
            f_cancellation = CancellationPolicy(
                f_poll_interval_seconds=f_canc_raw["poll_interval_seconds"],
                f_grace_seconds=f_canc_raw["grace_seconds"],
            )
        except Exception as f_err:
            raise ManifestValidationError(f"Invalid site.cancellation: {f_err}")

        # Construct SiteProfile
        try:
            f_site = SiteProfile(
                f_name=f_site_raw["name"],
                f_scheduler=SchedulerKind(f_site_raw["scheduler"]),
                f_launcher=LauncherPolicy(f_site_raw["launcher"]),
                f_certification=CertificationState(f_site_raw["certification"]),
                f_test_only=f_site_raw["test_only"],
                f_benchmark_roots=f_bm_roots,
                f_install_prefix=f_site_raw["install_prefix"],
                f_executables=ExecutableRegistry(f_ex_raw),
                f_modules=f_mods,
                f_resources=f_resources_dict,
                f_rank_identity=f_rank_identity,
                f_cancellation=f_cancellation,
                f_lustre_pools=f_l_pools,
            )
        except Exception as f_err:
            raise ManifestValidationError(f"Invalid site profile: {f_err}")

        return ManifestDocument(
            f_schema_version=f_ver,
            f_run_id=f_run_id,
            f_created_at_utc=f_created_at_utc,
            f_request=f_request,
            f_site=f_site,
            f_plan=f_plan_raw,
            f_scale_points=f_scale_points,
            f_combinations=f_combinations,
            f_points=f_points,
            f_tokens=f_tokens,
        )


class SignalCoordinator:
    """Coordinates signal handling for SIGINT and SIGTERM with latching lifecycle."""

    __slots__ = (
        "m_interrupted_signal",
        "m_exit_code",
        "m_old_handlers",
        "m_installed",
        "_frozen",
    )

    def __init__(self) -> None:
        self.m_interrupted_signal: Optional[int] = None
        self.m_exit_code: Optional[int] = None
        self.m_old_handlers: Dict[int, Any] = {}
        self.m_installed: bool = False
        self._frozen: bool = False

    @property
    def isInterrupted(self) -> bool:
        return self.m_interrupted_signal is not None

    @property
    def is_interrupted(self) -> bool:
        return self.isInterrupted

    @property
    def interruptedSignal(self) -> Optional[int]:
        return self.m_interrupted_signal

    @property
    def interrupted_signal(self) -> Optional[int]:
        return self.interruptedSignal

    @property
    def exitCode(self) -> Optional[int]:
        return self.m_exit_code

    @property
    def exit_code(self) -> Optional[int]:
        return self.exitCode

    @property
    def signalName(self) -> Optional[str]:
        if self.m_interrupted_signal is None:
            return None
        if self.m_interrupted_signal == signal.SIGINT:
            return "SIGINT"
        if self.m_interrupted_signal == signal.SIGTERM:
            return "SIGTERM"
        return f"SIG{self.m_interrupted_signal}"

    @property
    def signal_name(self) -> Optional[str]:
        return self.signalName

    def trigger(self, f_signum: int) -> None:
        """Latch the first received signal and ignore subsequent mixed or duplicate signals."""
        if self.m_interrupted_signal is not None:
            return
        self.m_interrupted_signal = f_signum
        if f_signum == signal.SIGINT:
            self.m_exit_code = 130
        elif f_signum == signal.SIGTERM:
            self.m_exit_code = 143
        else:
            self.m_exit_code = 128 + f_signum

    def _handleSignal(self, f_signum: int, f_frame: Any) -> None:
        self.trigger(f_signum)

    def install(self) -> "SignalCoordinator":
        """Register signal handlers for SIGINT and SIGTERM."""
        if self.m_installed:
            return self
        try:
            for f_sig in (signal.SIGINT, signal.SIGTERM):
                self.m_old_handlers[f_sig] = signal.signal(f_sig, self._handleSignal)
            self.m_installed = True
        except (ValueError, AttributeError):
            pass
        return self

    def uninstall(self) -> None:
        """Restore previous signal handlers."""
        if not self.m_installed:
            return
        for f_sig, f_old in list(self.m_old_handlers.items()):
            try:
                signal.signal(f_sig, f_old)
            except (ValueError, AttributeError):
                pass
        self.m_old_handlers.clear()
        self.m_installed = False

    def reset(self) -> None:
        """Reset interrupted state (useful for test reuse)."""
        self.m_interrupted_signal = None
        self.m_exit_code = None

    def __enter__(self) -> "SignalCoordinator":
        return self.install()

    def __exit__(self, f_exc_type: Any, f_exc_val: Any, f_exc_tb: Any) -> None:
        self.uninstall()


class OrchestrationError(Exception):
    """Base exception for run orchestration errors."""

    pass


class PreflightError(OrchestrationError):
    """Raised when preflight validation fails before allocating resources or mutating state."""

    pass


class RunOrchestrator:
    """Foreground orchestrator managing preflight, allocation, sequential submission, polling, recovery, interruption, and finalization."""

    __slots__ = (
        "m_profile_resolver",
        "m_planner",
        "m_artifact_store_factory",
        "m_scheduler_adapter_factory",
        "m_reconciler",
        "m_worker_validator",
        "m_command_runner",
        "m_clock",
        "m_run_id_source",
        "m_token_source",
        "m_poll_interval",
        "m_sleep",
        "m_signal_coordinator",
        "m_clock_float",
        "m_last_plan",
        "m_last_artifact_store",
        "m_last_evidence_store",
        "m_last_view",
        "_frozen",
    )

    def __init__(
        self,
        f_profile_resolver: Optional[Any] = None,
        f_planner: Optional[Any] = None,
        f_artifact_store_factory: Optional[Callable[..., Any]] = None,
        f_scheduler_adapter_factory: Optional[Callable[..., Any]] = None,
        f_reconciler: Optional[Any] = None,
        f_worker_validator: Optional[Union[Any, Callable[[str], str]]] = None,
        f_command_runner: Optional[Any] = None,
        f_clock: Optional[Callable[[], str]] = None,
        f_run_id_source: Optional[Callable[[], str]] = None,
        f_token_source: Optional[Callable[[], str]] = None,
        f_poll_interval: Optional[float] = None,
        f_sleep: Optional[Callable[[float], None]] = None,
        f_profile_store: Optional[Any] = None,
        f_artifact_store: Optional[Any] = None,
        f_scheduler_adapter: Optional[Any] = None,
        f_time_source: Optional[Callable[[], str]] = None,
        f_signal_coordinator: Optional[Any] = None,
        f_clock_float: Optional[Callable[[], float]] = None,
    ) -> None:
        f_eff_profile_resolver = f_profile_resolver if f_profile_resolver is not None else f_profile_store
        f_eff_artifact_store_factory = f_artifact_store_factory
        if f_eff_artifact_store_factory is None and f_artifact_store is not None:
            if callable(f_artifact_store):
                f_eff_artifact_store_factory = f_artifact_store
            else:
                f_eff_artifact_store_factory = lambda f_root, f_rid: f_artifact_store

        f_eff_scheduler_adapter_factory = f_scheduler_adapter_factory
        if f_eff_scheduler_adapter_factory is None and f_scheduler_adapter is not None:
            if callable(f_scheduler_adapter):
                f_eff_scheduler_adapter_factory = f_scheduler_adapter
            else:
                f_eff_scheduler_adapter_factory = lambda f_prof, f_ev, f_val, f_cmd: f_scheduler_adapter

        f_eff_clock = f_clock if f_clock is not None else f_time_source

        object.__setattr__(self, "m_profile_resolver", f_eff_profile_resolver)
        object.__setattr__(self, "m_planner", f_planner or RunPlanner)
        object.__setattr__(self, "m_artifact_store_factory", f_eff_artifact_store_factory)
        object.__setattr__(self, "m_scheduler_adapter_factory", f_eff_scheduler_adapter_factory)
        object.__setattr__(self, "m_reconciler", f_reconciler)
        object.__setattr__(self, "m_worker_validator", f_worker_validator)
        object.__setattr__(self, "m_command_runner", f_command_runner)
        object.__setattr__(self, "m_clock", f_eff_clock)
        object.__setattr__(self, "m_run_id_source", f_run_id_source)
        object.__setattr__(self, "m_token_source", f_token_source)
        object.__setattr__(self, "m_poll_interval", f_poll_interval)
        object.__setattr__(self, "m_sleep", f_sleep)
        object.__setattr__(self, "m_signal_coordinator", f_signal_coordinator)
        object.__setattr__(self, "m_clock_float", f_clock_float)
        object.__setattr__(self, "m_last_plan", None)
        object.__setattr__(self, "m_last_artifact_store", None)
        object.__setattr__(self, "m_last_evidence_store", None)
        object.__setattr__(self, "m_last_view", None)
        object.__setattr__(self, "_frozen", False)

    @property
    def profileResolver(self) -> Optional[Any]:
        return self.m_profile_resolver

    @property
    def profile_resolver(self) -> Optional[Any]:
        return self.m_profile_resolver

    @property
    def planner(self) -> Any:
        return self.m_planner

    @property
    def reconciler(self) -> Optional[Any]:
        return self.m_reconciler

    @property
    def workerValidator(self) -> Optional[Any]:
        return self.m_worker_validator

    @property
    def worker_validator(self) -> Optional[Any]:
        return self.m_worker_validator

    @property
    def commandRunner(self) -> Optional[Any]:
        return self.m_command_runner

    @property
    def command_runner(self) -> Optional[Any]:
        return self.m_command_runner

    @property
    def clock(self) -> Optional[Callable[[], str]]:
        return self.m_clock

    @property
    def runIdSource(self) -> Optional[Callable[[], str]]:
        return self.m_run_id_source

    @property
    def run_id_source(self) -> Optional[Callable[[], str]]:
        return self.m_run_id_source

    @property
    def tokenSource(self) -> Optional[Callable[[], str]]:
        return self.m_token_source

    @property
    def token_source(self) -> Optional[Callable[[], str]]:
        return self.m_token_source

    @property
    def pollInterval(self) -> Optional[float]:
        return self.m_poll_interval

    @property
    def poll_interval(self) -> Optional[float]:
        return self.m_poll_interval

    @property
    def signalCoordinator(self) -> Optional[Any]:
        return self.m_signal_coordinator

    @property
    def signal_coordinator(self) -> Optional[Any]:
        return self.m_signal_coordinator

    @property
    def isInterrupted(self) -> bool:
        if self.m_signal_coordinator is not None:
            return self.m_signal_coordinator.is_interrupted
        return False

    @property
    def is_interrupted(self) -> bool:
        return self.isInterrupted

    @property
    def interruptedSignal(self) -> Optional[int]:
        if self.m_signal_coordinator is not None:
            return self.m_signal_coordinator.interrupted_signal
        return None

    @property
    def interrupted_signal(self) -> Optional[int]:
        return self.interruptedSignal

    @property
    def exitCode(self) -> int:
        if self.m_signal_coordinator is not None and self.m_signal_coordinator.is_interrupted:
            return self.m_signal_coordinator.exit_code or 130
        if self.m_last_view is not None:
            from lsmiotool.lib.state import OverallRunState
            if self.m_last_view.state == OverallRunState.SUCCEEDED:
                return 0
            if self.m_last_view.state == OverallRunState.INTERRUPTED:
                if self.m_signal_coordinator is not None and self.m_signal_coordinator.exit_code is not None:
                    return self.m_signal_coordinator.exit_code
                return 130
            return 1
        return 1

    @property
    def exit_code(self) -> int:
        return self.exitCode

    @property
    def lastPlan(self) -> Optional[RunPlan]:
        return self.m_last_plan

    @property
    def last_plan(self) -> Optional[RunPlan]:
        return self.m_last_plan

    @property
    def lastArtifactStore(self) -> Optional[Any]:
        return self.m_last_artifact_store

    @property
    def last_artifact_store(self) -> Optional[Any]:
        return self.m_last_artifact_store

    @property
    def lastRunRoot(self) -> Optional[str]:
        if self.m_last_artifact_store is not None:
            return self.m_last_artifact_store.layout.runRoot
        return None

    @property
    def last_run_root(self) -> Optional[str]:
        return self.lastRunRoot

    @property
    def lastEvidenceStore(self) -> Optional[Any]:
        return self.m_last_evidence_store

    @property
    def last_evidence_store(self) -> Optional[Any]:
        return self.m_last_evidence_store

    @property
    def lastView(self) -> Optional[Any]:
        return self.m_last_view

    @property
    def last_view(self) -> Optional[Any]:
        return self.m_last_view

    def _recordInterruptionControlEvent(
        self,
        f_evidence_store: Any,
        f_sig_coord: SignalCoordinator,
    ) -> None:
        """Record an INTERRUPTED control event in EvidenceStore if not already recorded."""
        from lsmiotool.lib.evidence import EvidenceKind
        f_ctrl_events = f_evidence_store.readControlEvents("control")
        for f_ev in f_ctrl_events:
            if f_ev.evidence_kind == EvidenceKind.INTERRUPTED:
                return
        f_ctrl_seq = len(f_ctrl_events) + 1
        f_payload = {
            "signal": f_sig_coord.interrupted_signal,
            "signal_name": f_sig_coord.signal_name,
            "exit_code": f_sig_coord.exit_code,
        }
        try:
            f_evidence_store.recordInterruption(
                f_writer_id="control",
                f_sequence=f_ctrl_seq,
                f_payload=f_payload,
            )
        except Exception:
            pass

    def _queryJobState(
        self,
        f_adapter: Any,
        f_handle: Any,
        f_profile: SiteProfile,
    ) -> Tuple[Any, Optional[int]]:
        """Query scheduler for fresh job status using exact-job queries."""
        from lsmiotool.lib.scheduler import (
            PbsSchedulerAdapter,
            SlurmSchedulerAdapter,
        )
        from lsmiotool.lib.site import SchedulerKind
        from lsmiotool.lib.state import SchedulerJobState

        if f_profile.scheduler == SchedulerKind.SLURM:
            f_norm_id = SlurmSchedulerAdapter.validateJobId(f_handle.job_id)
            # 1. Active query
            f_act_argv = SlurmSchedulerAdapter.activeQueryCommand(f_norm_id)
            f_act_res = f_adapter.command_runner.run(f_act_argv)
            if f_act_res.is_success and f_act_res.stdout.strip():
                try:
                    f_act_state = SlurmSchedulerAdapter.parseActiveQuery(
                        f_act_res.stdout, f_job_id=f_norm_id
                    )
                    if f_act_state is not None:
                        if f_act_state in (
                            SchedulerJobState.QUEUED,
                            SchedulerJobState.ACTIVE,
                        ):
                            return (f_act_state, None)
                        elif f_act_state.is_terminal:
                            return (f_act_state, None)
                except Exception:
                    pass

            # 2. Accounting query
            f_acct_argv = SlurmSchedulerAdapter.accountingQueryCommand(f_norm_id)
            f_acct_res = f_adapter.command_runner.run(f_acct_argv)
            if f_acct_res.is_success and f_acct_res.stdout.strip():
                try:
                    f_acct_state, f_exit_code = (
                        SlurmSchedulerAdapter.parseAccountingQuery(
                            f_acct_res.stdout, f_job_id=f_norm_id
                        )
                    )
                    return (f_acct_state, f_exit_code)
                except Exception:
                    return (SchedulerJobState.UNKNOWN, None)
            else:
                return (SchedulerJobState.UNKNOWN, None)

        elif f_profile.scheduler == SchedulerKind.PBS:
            f_norm_id = PbsSchedulerAdapter.validateJobId(f_handle.job_id)
            # 1. Active query
            f_act_argv = PbsSchedulerAdapter.activeQueryCommand(f_norm_id)
            f_act_res = f_adapter.command_runner.run(f_act_argv)
            if f_act_res.is_success and f_act_res.stdout.strip():
                try:
                    f_act_state = PbsSchedulerAdapter.parseActiveQuery(
                        f_act_res.stdout, f_job_id=f_norm_id
                    )
                    if f_act_state is not None:
                        if f_act_state in (
                            SchedulerJobState.QUEUED,
                            SchedulerJobState.ACTIVE,
                        ):
                            return (f_act_state, None)
                        elif f_act_state.is_terminal:
                            return (f_act_state, None)
                except Exception:
                    pass

            # 2. Accounting query
            f_acct_argv = PbsSchedulerAdapter.accountingQueryCommand(f_norm_id)
            f_acct_res = f_adapter.command_runner.run(f_acct_argv)
            if f_acct_res.is_success and f_acct_res.stdout.strip():
                try:
                    f_acct_state, f_exit_code = (
                        PbsSchedulerAdapter.parseAccountingQuery(
                            f_acct_res.stdout, f_job_id=f_norm_id
                        )
                    )
                    return (f_acct_state, f_exit_code)
                except Exception:
                    return (SchedulerJobState.UNKNOWN, None)
            else:
                return (SchedulerJobState.UNKNOWN, None)

        else:
            if hasattr(f_adapter, "queryJob"):
                return f_adapter.queryJob(f_handle)
            return (SchedulerJobState.SUCCEEDED, 0)

    def execute(
        self,
        f_request: RunRequest,
        f_site: Optional[Union[str, SiteProfile]] = None,
        f_runtime_layout: Optional[Any] = None,
        f_worker_executable: Optional[str] = None,
        f_user: Optional[str] = None,
        f_home: Optional[str] = None,
        f_signal_coordinator: Optional[Any] = None,
    ) -> Any:
        """Execute full foreground orchestration of a benchmark run request."""
        f_sig_coord = f_signal_coordinator or self.m_signal_coordinator or SignalCoordinator()
        object.__setattr__(self, "m_signal_coordinator", f_sig_coord)

        with f_sig_coord:
            # -----------------------------------------------------------------
            # 1. Preflight Validation
            # -----------------------------------------------------------------
            if not isinstance(f_request, RunRequest):
                raise PreflightError(f"f_request must be RunRequest, got: {type(f_request).__name__}")

            # Strict LMP large check before anything else
            if f_request.target.lower() == "lmp" and f_request.scale.lower() == "large":
                raise PreflightError(
                    "LMP large scale is unsupported: tuning beyond 48 tasks is undefined"
                )

            # Resolve SiteProfile
            f_profile: Optional[SiteProfile] = None
            if isinstance(f_site, SiteProfile):
                f_profile = f_site
            elif isinstance(f_site, str):
                if self.m_profile_resolver is not None:
                    try:
                        if hasattr(self.m_profile_resolver, "getProfile"):
                            f_profile = self.m_profile_resolver.getProfile(f_site)
                        elif hasattr(self.m_profile_resolver, "resolveProfile"):
                            f_profile = self.m_profile_resolver.resolveProfile(
                                f_site, f_user=f_user, f_home=f_home
                            )
                        elif callable(self.m_profile_resolver):
                            f_profile = self.m_profile_resolver(f_site)
                        else:
                            raise PreflightError(f"Unsupported profile resolver: {self.m_profile_resolver!r}")
                    except Exception as f_err:
                        raise PreflightError(f"Failed to resolve site profile '{f_site}': {f_err}") from f_err
                else:
                    try:
                        from lsmiotool.lib.site import EnvironmentResolver
                        f_reg = EnvironmentResolver.resolveRegistry(f_user=f_user, f_home=f_home)
                        f_profile = f_reg.getProfile(f_site)
                    except Exception as f_err:
                        raise PreflightError(f"Failed to resolve site profile '{f_site}': {f_err}") from f_err
            elif f_site is None:
                if self.m_profile_resolver is not None:
                    try:
                        if hasattr(self.m_profile_resolver, "detect"):
                            f_profile = self.m_profile_resolver.detect(f_user=f_user, f_home=f_home)
                        elif hasattr(self.m_profile_resolver, "resolveProfile"):
                            f_profile = self.m_profile_resolver.resolveProfile(
                                None, f_user=f_user, f_home=f_home
                            )
                        elif callable(self.m_profile_resolver):
                            f_profile = self.m_profile_resolver(None)
                        else:
                            raise PreflightError(f"Unsupported profile resolver: {self.m_profile_resolver!r}")
                    except Exception as f_err:
                        raise PreflightError(f"Failed to detect site profile: {f_err}") from f_err
                else:
                    try:
                        from lsmiotool.lib.site import EnvironmentResolver
                        f_profile = EnvironmentResolver.detect(f_user=f_user, f_home=f_home)
                    except Exception as f_err:
                        raise PreflightError(f"Failed to detect site profile: {f_err}") from f_err
            else:
                raise PreflightError(f"Invalid f_site argument: {f_site!r}")

            if not isinstance(f_profile, SiteProfile):
                raise PreflightError(f"Resolved profile is not a SiteProfile, got: {type(f_profile).__name__}")

            # Create RunPlan
            f_planner_obj = self.m_planner or RunPlanner
            try:
                f_plan = f_planner_obj.createPlan(
                    f_request=f_request,
                    f_profile=f_profile,
                    f_run_id_source=self.m_run_id_source,
                    f_clock=self.m_clock,
                    f_token_source=self.m_token_source,
                )
            except PlanValidationError as f_err:
                raise PreflightError(str(f_err)) from f_err
            except Exception as f_err:
                raise PreflightError(f"Plan creation failed: {f_err}") from f_err

            # Validate worker executable
            f_raw_worker: str
            if f_worker_executable is not None:
                f_raw_worker = str(f_worker_executable).strip()
            elif f_runtime_layout is not None:
                f_raw_worker = f_runtime_layout.worker_executable
            else:
                f_raw_worker = os.path.join(f_profile.install_prefix, "bin", "lsmiotool-worker")

            f_validated_worker: str = f_raw_worker
            if self.m_worker_validator is not None:
                try:
                    if hasattr(self.m_worker_validator, "validate"):
                        f_validated_worker = self.m_worker_validator.validate(f_raw_worker)
                    elif callable(self.m_worker_validator):
                        f_validated_worker = self.m_worker_validator(f_raw_worker)
                    else:
                        raise PreflightError(f"Unsupported worker validator: {self.m_worker_validator!r}")
                except Exception as f_err:
                    raise PreflightError(
                        f"Worker executable validation failed for '{f_raw_worker}': {f_err}"
                    ) from f_err

            # -----------------------------------------------------------------
            # 2. Lock & Allocate
            # -----------------------------------------------------------------
            f_storage = f_plan.request.storage
            f_benchmark_root = f_profile.getBenchmarkRoot(f_storage)
            if not f_benchmark_root:
                raise PreflightError(f"Benchmark root for storage '{f_storage.value}' is not configured")

            from lsmiotool.lib.artifacts import (
                ArtifactError,
                ArtifactStore,
                LockContentionError,
            )

            if self.m_artifact_store_factory is not None:
                f_artifact_store = self.m_artifact_store_factory(f_benchmark_root, f_plan.run_id)
            else:
                f_artifact_store = ArtifactStore(f_benchmark_root, f_plan.run_id)

            object.__setattr__(self, "m_last_plan", f_plan)
            object.__setattr__(self, "m_last_artifact_store", f_artifact_store)

            if not os.path.exists(f_artifact_store.layout.runRoot):
                try:
                    f_artifact_store.allocateRun(f_plan)
                except ArtifactError as f_err:
                    raise OrchestrationError(f"Failed to allocate run: {f_err}") from f_err

            f_control_lock = f_artifact_store.getControlLock()
            try:
                f_control_lock.acquire(f_blocking=False)
            except LockContentionError as f_err:
                raise OrchestrationError(
                    f"Control lock contention on run '{f_plan.run_id}': {f_err}"
                ) from f_err
            except ArtifactError as f_err:
                raise OrchestrationError(
                    f"Failed to acquire control lock on run '{f_plan.run_id}': {f_err}"
                ) from f_err

            try:
                from lsmiotool.lib.evidence import EvidenceKind, EvidenceRecord, EvidenceStore, WriterKind
                f_evidence_store = EvidenceStore(f_artifact_store.layout, f_plan)
                object.__setattr__(self, "m_last_evidence_store", f_evidence_store)

                from lsmiotool.lib.scheduler import (
                    JobSpec,
                    PbsScriptRenderer,
                    PbsSchedulerAdapter,
                    SchedulerAdapter,
                    SlurmScriptRenderer,
                    SlurmSchedulerAdapter,
                )
                from lsmiotool.lib.site import PbsMailMode, SchedulerKind, SlurmMailMode
                from lsmiotool.lib.state import (
                    OverallRunState,
                    PointRunState,
                    RunStateView,
                    SchedulerJobState,
                    StateReconciler,
                )

                if self.m_scheduler_adapter_factory is not None:
                    f_adapter = self.m_scheduler_adapter_factory(
                        f_profile, f_evidence_store, self.m_worker_validator, self.m_command_runner
                    )
                else:
                    if f_profile.scheduler == SchedulerKind.SLURM:
                        f_adapter = SlurmSchedulerAdapter(
                            f_evidence_store=f_evidence_store,
                            f_worker_validator=self.m_worker_validator,
                            f_command_runner=self.m_command_runner,
                        )
                    elif f_profile.scheduler == SchedulerKind.PBS:
                        f_adapter = PbsSchedulerAdapter(
                            f_evidence_store=f_evidence_store,
                            f_worker_validator=self.m_worker_validator,
                            f_command_runner=self.m_command_runner,
                        )
                    else:
                        f_adapter = SchedulerAdapter(
                            f_backend=f_profile.scheduler,
                            f_evidence_store=f_evidence_store,
                            f_worker_validator=self.m_worker_validator,
                            f_command_runner=self.m_command_runner,
                        )

                f_reconciler_obj = self.m_reconciler or StateReconciler
                f_all_points_succeeded = True
                f_current_view: Optional[RunStateView] = None

                # Check if interrupted before loop
                if f_sig_coord.is_interrupted:
                    self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                    f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                    f_all_points_succeeded = False
                    object.__setattr__(self, "m_last_view", f_current_view)
                    return f_current_view

                # -----------------------------------------------------------------
                # 3. Sequential Point Submission & Monitoring
                # -----------------------------------------------------------------
                for f_idx, f_scale_point in enumerate(f_plan.scale_points):
                    if f_sig_coord.is_interrupted:
                        self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                        f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                        f_all_points_succeeded = False
                        break

                    f_point_name = f_artifact_store.layout.pointDirName(f_scale_point, f_idx)

                    # Prepare point directory structure
                    f_artifact_store.preparePoint(f_scale_point, f_plan.combinations, f_ordinal=f_idx)

                    # Render script
                    f_point_sched_dir = f_artifact_store.layout.pointSchedulerDir(f_scale_point, f_idx)
                    f_script_path = os.path.join(f_point_sched_dir, "job.sh")
                    f_logs_dir = f_artifact_store.layout.pointLogsDir(f_scale_point, f_idx)
                    f_output_path = os.path.join(f_logs_dir, "job.out")
                    f_error_path = os.path.join(f_logs_dir, "job.err")

                    f_point_res = f_plan.scheduled_points[f_idx]
                    f_token = f_plan.tokens[f_idx]

                    if f_profile.scheduler == SchedulerKind.SLURM:
                        f_mail_mode_val = SlurmMailMode.END_FAIL if f_point_res.mail_mode else None
                        f_directives = SlurmScriptRenderer.renderDirectives(
                            f_point=f_scale_point,
                            f_profile=f_profile,
                            f_job_name=f_token,
                            f_output_path=f_output_path,
                            f_error_path=f_error_path,
                            f_account=None,
                            f_mail_user=None,
                            f_mail_mode=f_mail_mode_val,
                            f_walltime=f_point_res.walltime,
                        )
                    elif f_profile.scheduler == SchedulerKind.PBS:
                        f_mail_mode_val = PbsMailMode.ABE if f_point_res.mail_mode else None
                        f_directives = PbsScriptRenderer.renderDirectives(
                            f_point=f_scale_point,
                            f_profile=f_profile,
                            f_job_name=f_token,
                            f_output_path=f_output_path,
                            f_error_path=f_error_path,
                            f_mail_mode=f_mail_mode_val,
                            f_walltime=f_point_res.walltime,
                            f_resources=f_point_res,
                        )
                    else:
                        f_directives = [
                            f"#FAKE --job-name={f_token}",
                            f"#FAKE --output={f_output_path}",
                            f"#FAKE --error={f_error_path}",
                        ]

                    f_script_body = f_adapter.renderScript(
                        f_directives=f_directives,
                        f_profile=f_profile,
                        f_worker_executable=f_validated_worker,
                        f_manifest_path=f_artifact_store.layout.manifestPath,
                        f_point_id=f_point_name,
                    )

                    with open(f_script_path, "w", encoding="utf-8") as f_f:
                        f_f.write(f_script_body)
                    os.chmod(f_script_path, 0o755)

                    f_spec = JobSpec(
                        f_point_id=f_scale_point,
                        f_script_path=f_script_path,
                        f_working_dir=f_artifact_store.layout.pointDir(f_scale_point, f_idx),
                        f_resources=f_point_res,
                        f_output_path=f_output_path,
                        f_error_path=f_error_path,
                        f_job_name=f_token,
                    )

                    if f_sig_coord.is_interrupted:
                        self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                        f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                        f_all_points_succeeded = False
                        break

                    try:
                        f_job_result = f_adapter.dispatchSubmission(
                            f_point=f_scale_point,
                            f_spec=f_spec,
                            f_writer_id="control",
                            f_ordinal=f_idx,
                        )
                    except Exception:
                        if f_sig_coord.is_interrupted:
                            self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                        f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                        f_all_points_succeeded = False
                        break

                    f_handle = f_job_result.job_handle

                    f_poll_interval = (
                        self.m_poll_interval
                        if self.m_poll_interval is not None
                        else (
                            f_profile.cancellation.poll_interval_seconds
                            if f_profile.cancellation
                            else 1.0
                        )
                    )
                    f_sleep_fn = self.m_sleep or (lambda f_s: None)

                    f_obs_seq = 1
                    f_obs_dir = f_artifact_store.layout.pointSchedulerObservationsDir(
                        f_scale_point, f_writer="control", f_ordinal=f_idx
                    )
                    if os.path.exists(f_obs_dir):
                        f_existing_obs = [
                            f_x for f_x in os.listdir(f_obs_dir) if f_x.endswith(".json")
                        ]
                        f_obs_seq = len(f_existing_obs) + 1

                    f_point_terminal = False
                    f_consecutive_unknown = 0
                    f_max_consecutive_unknown = 3
                    while not f_point_terminal:
                        if f_sig_coord.is_interrupted:
                            # 1. Record CANCEL_REQUESTED
                            f_evidence_store.recordCancelRequested(
                                f_point=f_scale_point,
                                f_writer_id="control",
                                f_handle=f_handle,
                                f_payload={
                                    "reason": f"Interrupted by {f_sig_coord.signal_name}",
                                    "signal": f_sig_coord.interrupted_signal,
                                    "exit_code": f_sig_coord.exit_code,
                                },
                                f_ordinal=f_idx,
                            )

                            # 2. Cancel exact active JobHandle via scheduler adapter
                            f_cancel_poll_interval = 1.0
                            f_cancel_grace_seconds = 120.0
                            if f_profile.cancellation:
                                f_cancel_poll_interval = float(f_profile.cancellation.poll_interval_seconds)
                                f_cancel_grace_seconds = float(f_profile.cancellation.grace_seconds)
                            if self.m_poll_interval is not None:
                                f_cancel_poll_interval = self.m_poll_interval

                            f_cancel_state = SchedulerJobState.UNKNOWN
                            if hasattr(f_adapter, "cancelAndConfirm"):
                                f_cancel_state = f_adapter.cancelAndConfirm(
                                    f_job_id=f_handle.job_id,
                                    f_poll_interval=f_cancel_poll_interval,
                                    f_grace_seconds=f_cancel_grace_seconds,
                                    f_clock=self.m_clock_float,
                                    f_sleep=self.m_sleep,
                                )
                            elif hasattr(f_adapter, "cancel_and_confirm"):
                                f_cancel_state = f_adapter.cancel_and_confirm(
                                    f_job_id=f_handle.job_id,
                                    f_poll_interval=f_cancel_poll_interval,
                                    f_grace_seconds=f_cancel_grace_seconds,
                                    f_clock=self.m_clock_float,
                                    f_sleep=self.m_sleep,
                                )
                            elif hasattr(f_adapter, "cancelJob"):
                                f_cancel_state = f_adapter.cancelJob(f_handle)
                            elif hasattr(f_adapter, "cancel_job"):
                                f_cancel_state = f_adapter.cancel_job(f_handle)
                            else:
                                f_cancel_state = SchedulerJobState.CANCELLED

                            # 3. Record cancel outcome
                            if f_cancel_state == SchedulerJobState.UNKNOWN:
                                f_unconf_path = os.path.join(
                                    f_artifact_store.layout.pointSchedulerDir(f_scale_point, f_idx),
                                    "cancel_unconfirmed.json",
                                )
                                f_unconf_rec = EvidenceRecord(
                                    f_writer_kind=WriterKind.CONTROL,
                                    f_writer_id="control",
                                    f_sequence_number=2,
                                    f_evidence_kind=EvidenceKind.CANCEL_UNCONFIRMED,
                                    f_point_id=f_artifact_store.layout.pointDirName(f_scale_point, f_idx),
                                    f_payload={
                                        "outcome": "unconfirmed",
                                        "handle": f_handle.toDict(),
                                    },
                                    f_run_id=f_artifact_store.layout.runId,
                                )
                                f_evidence_store.recordRecord(f_unconf_path, f_unconf_rec)
                            else:
                                f_outcome = "confirmed" if f_cancel_state == SchedulerJobState.CANCELLED else "already_terminal"
                                f_evidence_store.recordCancelRecorded(
                                    f_point=f_scale_point,
                                    f_writer_id="control",
                                    f_handle=f_handle,
                                    f_payload={
                                        "outcome": f_outcome,
                                        "terminal_state": f_cancel_state.value,
                                    },
                                    f_ordinal=f_idx,
                                )
                                f_evidence_store.recordSchedulerObservation(
                                    f_point=f_scale_point,
                                    f_writer_id="control",
                                    f_sequence=f_obs_seq,
                                    f_payload={
                                        "handle": f_handle.toDict(),
                                        "state": f_cancel_state.value,
                                        "status": f_cancel_state.value,
                                    },
                                    f_ordinal=f_idx,
                                )
                                f_obs_seq += 1

                            # 4. Record INTERRUPTED control event
                            self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                            f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                            f_all_points_succeeded = False
                            f_point_terminal = True
                            break

                        f_job_state, f_exit_code = self._queryJobState(
                            f_adapter=f_adapter,
                            f_handle=f_handle,
                            f_profile=f_profile,
                        )

                        f_evidence_store.recordSchedulerObservation(
                            f_point=f_scale_point,
                            f_writer_id="control",
                            f_sequence=f_obs_seq,
                            f_payload={
                                "handle": f_handle.toDict(),
                                "state": f_job_state.value,
                                "status": f_job_state.value,
                                "exit_code": f_exit_code,
                            },
                            f_ordinal=f_idx,
                        )
                        f_obs_seq += 1

                        if f_job_state.is_terminal:
                            f_point_terminal = True
                        elif f_job_state == SchedulerJobState.UNKNOWN:
                            f_consecutive_unknown += 1
                            if f_consecutive_unknown >= f_max_consecutive_unknown:
                                f_point_terminal = True
                            else:
                                f_sleep_fn(f_poll_interval)
                        else:
                            f_consecutive_unknown = 0
                            f_sleep_fn(f_poll_interval)

                    f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                    f_pt_view = f_current_view.point_states[f_idx]

                    if f_sig_coord.is_interrupted or f_pt_view.state != PointRunState.SUCCEEDED:
                        if f_sig_coord.is_interrupted:
                            self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                            f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                        f_all_points_succeeded = False
                        break

                # -----------------------------------------------------------------
                # 4. Finalization
                # -----------------------------------------------------------------
                if f_sig_coord.is_interrupted:
                    self._recordInterruptionControlEvent(f_evidence_store, f_sig_coord)
                    f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                elif f_all_points_succeeded and f_current_view is not None:
                    f_all_pts_ok = all(
                        f_pv.state == PointRunState.SUCCEEDED
                        for f_pv in f_current_view.point_states
                    )
                    if f_all_pts_ok and not f_current_view.has_interruption and not f_sig_coord.is_interrupted:
                        f_ctrl_seq = len(f_evidence_store.readControlEvents("control")) + 1
                        try:
                            f_evidence_store.recordWholeRunSucceeded(
                                f_writer_id="control",
                                f_sequence=f_ctrl_seq,
                                f_payload={"run_id": f_plan.run_id},
                            )
                            f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)
                        except Exception:
                            f_current_view = f_reconciler_obj.reconcile(f_plan, f_evidence_store)

                object.__setattr__(self, "m_last_view", f_current_view)
                return f_current_view
            finally:
                f_control_lock.release()

    run = execute


