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

import copy
from enum import Enum
import os
import platform
import re
from typing import Any, Dict, Generic, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar, Union

from lsmiotool.lib.profile import ProfileDocument, ProfileLoader, ProfileRecord, ProfileSchemaError


class SchedulerKind(Enum):
    """Enumeration of supported job scheduler backends."""

    SLURM = "slurm"
    PBS = "pbs"
    FAKE = "fake"


class StorageClass(Enum):
    """Enumeration of benchmark storage tiers."""

    HDD = "hdd"
    SSD = "ssd"


class CertificationState(Enum):
    """Enumeration of site profile certification states."""

    CONFIGURED = "configured"
    CERTIFIED = "certified"


class SlurmMailMode(Enum):
    """Backend-typed Slurm mail notification modes."""

    END_FAIL = "END,FAIL"


class PbsMailMode(Enum):
    """Backend-typed PBS mail notification modes."""

    ABE = "abe"


MailModeT = TypeVar("MailModeT", SlurmMailMode, PbsMailMode, None)


class SiteResolutionError(Exception):
    """Exception raised when site or environment resolution fails."""

    pass


class LauncherPolicy:
    """Immutable policy defining the MPI/job launcher configuration."""

    __slots__ = ("m_kind", "_frozen")

    def __init__(self, f_kind: str) -> None:
        if not isinstance(f_kind, str) or not f_kind:
            raise SiteResolutionError(
                f"Launcher kind must be a non-empty string, got: {f_kind!r}"
            )
        super().__setattr__("m_kind", f_kind)
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
    def kind(self) -> str:
        return self.m_kind

    def toDict(self) -> Dict[str, Any]:
        return {"kind": self.m_kind}

    def __repr__(self) -> str:
        return f"LauncherPolicy(kind={self.m_kind!r})"

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, LauncherPolicy):
            return self.m_kind == f_other.m_kind
        return False


class RankIdentityPolicy:
    """Immutable policy specifying environment variable names for rank identity."""

    __slots__ = ("m_global_rank", "m_node_name", "m_local_rank", "_frozen")

    def __init__(
        self,
        f_global_rank: str,
        f_node_name: str,
        f_local_rank: Optional[str] = None,
    ) -> None:
        if not isinstance(f_global_rank, str) or not f_global_rank:
            raise SiteResolutionError(
                f"global_rank must be a non-empty string, got: {f_global_rank!r}"
            )
        if not isinstance(f_node_name, str) or not f_node_name:
            raise SiteResolutionError(
                f"node_name must be a non-empty string, got: {f_node_name!r}"
            )
        if f_local_rank is not None and not isinstance(f_local_rank, str):
            raise SiteResolutionError(
                f"local_rank must be str or None, got: {f_local_rank!r}"
            )

        super().__setattr__("m_global_rank", f_global_rank)
        super().__setattr__("m_node_name", f_node_name)
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
    def global_rank(self) -> str:
        return self.m_global_rank

    @property
    def node_name(self) -> str:
        return self.m_node_name

    @property
    def node(self) -> str:
        return self.m_node_name

    @property
    def local_rank(self) -> Optional[str]:
        return self.m_local_rank

    def toDict(self) -> Dict[str, Optional[str]]:
        return {
            "global": self.m_global_rank,
            "node": self.m_node_name,
            "local": self.m_local_rank,
        }

    def __repr__(self) -> str:
        return (
            f"RankIdentityPolicy(global_rank={self.m_global_rank!r}, "
            f"node_name={self.m_node_name!r}, "
            f"local_rank={self.m_local_rank!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, RankIdentityPolicy):
            return (
                self.m_global_rank == f_other.m_global_rank
                and self.m_node_name == f_other.m_node_name
                and self.m_local_rank == f_other.m_local_rank
            )
        return False


class CancellationPolicy:
    """Immutable policy defining cancellation polling and grace period parameters."""

    __slots__ = ("m_poll_interval_seconds", "m_grace_seconds", "_frozen")

    def __init__(
        self,
        f_poll_interval_seconds: int,
        f_grace_seconds: int,
    ) -> None:
        if not isinstance(f_poll_interval_seconds, int) or f_poll_interval_seconds <= 0:
            raise SiteResolutionError(
                f"poll_interval_seconds must be a positive integer, got: {f_poll_interval_seconds!r}"
            )
        if not isinstance(f_grace_seconds, int) or f_grace_seconds <= 0:
            raise SiteResolutionError(
                f"grace_seconds must be a positive integer, got: {f_grace_seconds!r}"
            )
        super().__setattr__("m_poll_interval_seconds", f_poll_interval_seconds)
        super().__setattr__("m_grace_seconds", f_grace_seconds)
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
    def poll_interval_seconds(self) -> int:
        return self.m_poll_interval_seconds

    @property
    def grace_seconds(self) -> int:
        return self.m_grace_seconds

    def toDict(self) -> Dict[str, int]:
        return {
            "poll_interval_seconds": self.m_poll_interval_seconds,
            "grace_seconds": self.m_grace_seconds,
        }

    def __repr__(self) -> str:
        return (
            f"CancellationPolicy(poll_interval_seconds={self.m_poll_interval_seconds}, "
            f"grace_seconds={self.m_grace_seconds})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, CancellationPolicy):
            return (
                self.m_poll_interval_seconds == f_other.m_poll_interval_seconds
                and self.m_grace_seconds == f_other.m_grace_seconds
            )
        return False


class ResourcePolicy(Generic[MailModeT]):
    """Immutable resource policy defining scheduler directives and shape limits."""

    __slots__ = (
        "m_scheduler",
        "m_walltime_policy",
        "m_queue",
        "m_partition",
        "m_qos",
        "m_memory",
        "m_mail_mode",
        "m_pmem",
        "m_pvmem",
        "_frozen",
    )

    def __init__(
        self,
        f_scheduler: Optional[SchedulerKind] = None,
        f_walltime_policy: Optional[str] = None,
        f_queue: Optional[str] = None,
        f_partition: Optional[str] = None,
        f_qos: Optional[str] = None,
        f_memory: Optional[str] = None,
        f_mail_mode: Optional[Union[SlurmMailMode, PbsMailMode]] = None,
        f_pmem: Optional[str] = None,
        f_pvmem: Optional[str] = None,
    ) -> None:
        if f_mail_mode is not None:
            if isinstance(f_mail_mode, str):
                raise TypeError(
                    f"Raw mail string {f_mail_mode!r} is prohibited; must use backend-typed enum SlurmMailMode or PbsMailMode"
                )
            if not isinstance(f_mail_mode, (SlurmMailMode, PbsMailMode)):
                raise TypeError(
                    f"mail_mode must be SlurmMailMode, PbsMailMode, or None, got: {type(f_mail_mode).__name__}"
                )

        if f_scheduler is not None:
            if not isinstance(f_scheduler, SchedulerKind):
                raise TypeError(
                    f"scheduler must be a SchedulerKind enum, got: {type(f_scheduler).__name__}"
                )
            if f_scheduler == SchedulerKind.SLURM:
                if f_mail_mode is not None and not isinstance(f_mail_mode, SlurmMailMode):
                    raise SiteResolutionError(
                        f"Slurm scheduler cannot accept {type(f_mail_mode).__name__} ({f_mail_mode})"
                    )
            elif f_scheduler == SchedulerKind.PBS:
                if f_mail_mode is not None and not isinstance(f_mail_mode, PbsMailMode):
                    raise SiteResolutionError(
                        f"PBS scheduler cannot accept {type(f_mail_mode).__name__} ({f_mail_mode})"
                    )
            elif f_scheduler == SchedulerKind.FAKE:
                if f_mail_mode is not None:
                    raise SiteResolutionError(
                        f"Fake scheduler cannot accept mail_mode: {f_mail_mode}"
                    )

        super().__setattr__("m_scheduler", f_scheduler)
        super().__setattr__("m_walltime_policy", f_walltime_policy)
        super().__setattr__("m_queue", f_queue)
        super().__setattr__("m_partition", f_partition)
        super().__setattr__("m_qos", f_qos)
        super().__setattr__("m_memory", f_memory)
        super().__setattr__("m_mail_mode", f_mail_mode)
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
    def scheduler(self) -> Optional[SchedulerKind]:
        return self.m_scheduler

    @property
    def walltime_policy(self) -> Optional[str]:
        return self.m_walltime_policy

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
    def memory(self) -> Optional[str]:
        return self.m_memory

    @property
    def mail_mode(self) -> Optional[Union[SlurmMailMode, PbsMailMode]]:
        return self.m_mail_mode

    @property
    def pmem(self) -> Optional[str]:
        return self.m_pmem

    @property
    def pvmem(self) -> Optional[str]:
        return self.m_pvmem

    @property
    def requires_credentials(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    @property
    def requires_account(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    @property
    def requires_email(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    def validateCredentials(
        self,
        f_account: Optional[str] = None,
        f_email: Optional[str] = None,
    ) -> None:
        if self.requires_credentials:
            if not f_account or not str(f_account).strip():
                raise SiteResolutionError(
                    "Slurm scheduler policy requires a non-empty account (SB_ACCOUNT)"
                )
            if not f_email or not str(f_email).strip():
                raise SiteResolutionError(
                    "Slurm scheduler policy requires a non-empty email (SB_EMAIL)"
                )

    def toDict(self) -> Dict[str, Optional[str]]:
        return {
            "walltime_policy": self.m_walltime_policy,
            "queue": self.m_queue,
            "partition": self.m_partition,
            "qos": self.m_qos,
            "memory": self.m_memory,
            "mail_mode": self.m_mail_mode.value if self.m_mail_mode is not None else None,
            "pmem": self.m_pmem,
            "pvmem": self.m_pvmem,
        }

    def __repr__(self) -> str:
        return (
            f"ResourcePolicy(scheduler={self.m_scheduler!r}, "
            f"walltime_policy={self.m_walltime_policy!r}, "
            f"queue={self.m_queue!r}, partition={self.m_partition!r}, "
            f"qos={self.m_qos!r}, memory={self.m_memory!r}, "
            f"mail_mode={self.m_mail_mode!r}, "
            f"pmem={self.m_pmem!r}, pvmem={self.m_pvmem!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ResourcePolicy):
            return (
                self.m_scheduler == f_other.m_scheduler
                and self.m_walltime_policy == f_other.m_walltime_policy
                and self.m_queue == f_other.m_queue
                and self.m_partition == f_other.m_partition
                and self.m_qos == f_other.m_qos
                and self.m_memory == f_other.m_memory
                and self.m_mail_mode == f_other.m_mail_mode
                and self.m_pmem == f_other.m_pmem
                and self.m_pvmem == f_other.m_pvmem
            )
        return False


class ExecutableRegistry:
    """Immutable registry of benchmark executable paths resolved below install_prefix/bin."""

    __slots__ = ("m_executables", "_frozen")

    REQUIRED_EXECUTABLES: Set[str] = {
        "ior",
        "lmp",
        "bm_native",
        "bm_adios",
        "bm_rocksdb",
        "bm_leveldb",
        "bm_manager",
    }

    def __init__(self, f_executables: Mapping[str, str]) -> None:
        f_missing = self.REQUIRED_EXECUTABLES - set(f_executables.keys())
        if f_missing:
            raise SiteResolutionError(
                f"Missing required executables in registry: {sorted(f_missing)}"
            )
        f_extra = set(f_executables.keys()) - self.REQUIRED_EXECUTABLES
        if f_extra:
            raise SiteResolutionError(
                f"Unexpected extra executables in registry: {sorted(f_extra)}"
            )
        for f_name, f_path in f_executables.items():
            if not isinstance(f_path, str) or not f_path.startswith("/"):
                raise SiteResolutionError(
                    f"Executable '{f_name}' path must be an absolute path, got: {f_path!r}"
                )

        super().__setattr__("m_executables", dict(f_executables))
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    def getExecutable(self, f_name: str) -> str:
        if f_name not in self.m_executables:
            raise SiteResolutionError(f"Executable '{f_name}' not found in registry")
        return self.m_executables[f_name]

    def __getitem__(self, f_name: str) -> str:
        return self.getExecutable(f_name)

    @property
    def ior(self) -> str:
        return self.m_executables["ior"]

    @property
    def lmp(self) -> str:
        return self.m_executables["lmp"]

    @property
    def bm_native(self) -> str:
        return self.m_executables["bm_native"]

    @property
    def bm_adios(self) -> str:
        return self.m_executables["bm_adios"]

    @property
    def bm_rocksdb(self) -> str:
        return self.m_executables["bm_rocksdb"]

    @property
    def bm_leveldb(self) -> str:
        return self.m_executables["bm_leveldb"]

    @property
    def bm_manager(self) -> str:
        return self.m_executables["bm_manager"]

    @property
    def executables(self) -> Dict[str, str]:
        return dict(self.m_executables)

    def toDict(self) -> Dict[str, str]:
        return dict(self.m_executables)

    def __repr__(self) -> str:
        return f"ExecutableRegistry({self.m_executables!r})"

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, ExecutableRegistry):
            return self.m_executables == f_other.m_executables
        return False


class SiteProfile:
    """Immutable fully-resolved site profile with typed policies and expanded paths."""

    __slots__ = (
        "m_name",
        "m_scheduler",
        "m_launcher",
        "m_certification",
        "m_test_only",
        "m_benchmark_roots",
        "m_install_prefix",
        "m_executables",
        "m_modules",
        "m_resources",
        "m_rank_identity",
        "m_cancellation",
        "m_lustre_pools",
        "_frozen",
    )

    def __init__(
        self,
        f_name: str,
        f_scheduler: SchedulerKind,
        f_launcher: LauncherPolicy,
        f_certification: CertificationState,
        f_test_only: bool,
        f_benchmark_roots: Mapping[Union[StorageClass, str], str],
        f_install_prefix: str,
        f_executables: ExecutableRegistry,
        f_modules: Sequence[str],
        f_resources: Mapping[str, ResourcePolicy],
        f_rank_identity: RankIdentityPolicy,
        f_cancellation: CancellationPolicy,
        f_lustre_pools: Mapping[Union[StorageClass, str], Optional[str]],
    ) -> None:
        if not isinstance(f_name, str) or not f_name:
            raise SiteResolutionError(
                f"Site name must be a non-empty string, got: {f_name!r}"
            )
        if not isinstance(f_scheduler, SchedulerKind):
            raise SiteResolutionError(
                f"Scheduler must be a SchedulerKind enum, got: {f_scheduler!r}"
            )
        if not isinstance(f_launcher, LauncherPolicy):
            raise SiteResolutionError(
                f"Launcher must be a LauncherPolicy, got: {f_launcher!r}"
            )
        if not isinstance(f_certification, CertificationState):
            raise SiteResolutionError(
                f"Certification must be a CertificationState enum, got: {f_certification!r}"
            )
        if not isinstance(f_test_only, bool):
            raise SiteResolutionError(
                f"test_only must be a boolean, got: {f_test_only!r}"
            )
        if not isinstance(f_install_prefix, str) or not f_install_prefix.startswith("/"):
            raise SiteResolutionError(
                f"install_prefix must be an absolute path, got: {f_install_prefix!r}"
            )
        if not isinstance(f_executables, ExecutableRegistry):
            raise SiteResolutionError(
                f"executables must be an ExecutableRegistry, got: {f_executables!r}"
            )
        if not isinstance(f_rank_identity, RankIdentityPolicy):
            raise SiteResolutionError(
                f"rank_identity must be a RankIdentityPolicy, got: {f_rank_identity!r}"
            )
        if not isinstance(f_cancellation, CancellationPolicy):
            raise SiteResolutionError(
                f"cancellation must be a CancellationPolicy, got: {f_cancellation!r}"
            )

        f_norm_roots: Dict[StorageClass, str] = {}
        for f_st_key, f_st_val in f_benchmark_roots.items():
            f_sc = f_st_key if isinstance(f_st_key, StorageClass) else StorageClass(f_st_key)
            if not isinstance(f_st_val, str) or not f_st_val.startswith("/"):
                raise SiteResolutionError(
                    f"Benchmark root for {f_sc} must be an absolute path, got: {f_st_val!r}"
                )
            f_norm_roots[f_sc] = f_st_val

        for f_req_sc in (StorageClass.HDD, StorageClass.SSD):
            if f_req_sc not in f_norm_roots:
                raise SiteResolutionError(
                    f"Missing benchmark root for storage class: {f_req_sc}"
                )

        f_norm_pools: Dict[StorageClass, Optional[str]] = {}
        for f_pl_key, f_pl_val in f_lustre_pools.items():
            f_sc = f_pl_key if isinstance(f_pl_key, StorageClass) else StorageClass(f_pl_key)
            f_norm_pools[f_sc] = f_pl_val

        for f_req_sc in (StorageClass.HDD, StorageClass.SSD):
            if f_req_sc not in f_norm_pools:
                raise SiteResolutionError(
                    f"Missing lustre pool for storage class: {f_req_sc}"
                )

        if set(f_resources.keys()) != {"small", "large"}:
            raise SiteResolutionError(
                f"resources must contain exactly 'small' and 'large' shapes, got: {set(f_resources.keys())}"
            )
        for f_shp, f_pol in f_resources.items():
            if not isinstance(f_pol, ResourcePolicy):
                raise SiteResolutionError(
                    f"Resource policy for '{f_shp}' must be ResourcePolicy, got: {f_pol!r}"
                )

        super().__setattr__("m_name", f_name)
        super().__setattr__("m_scheduler", f_scheduler)
        super().__setattr__("m_launcher", f_launcher)
        super().__setattr__("m_certification", f_certification)
        super().__setattr__("m_test_only", f_test_only)
        super().__setattr__("m_benchmark_roots", f_norm_roots)
        super().__setattr__("m_install_prefix", f_install_prefix)
        super().__setattr__("m_executables", f_executables)
        super().__setattr__("m_modules", tuple(f_modules))
        super().__setattr__("m_resources", dict(f_resources))
        super().__setattr__("m_rank_identity", f_rank_identity)
        super().__setattr__("m_cancellation", f_cancellation)
        super().__setattr__("m_lustre_pools", f_norm_pools)
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
    def name(self) -> str:
        return self.m_name

    @property
    def scheduler(self) -> SchedulerKind:
        return self.m_scheduler

    @property
    def launcher(self) -> LauncherPolicy:
        return self.m_launcher

    @property
    def certification(self) -> CertificationState:
        return self.m_certification

    @property
    def test_only(self) -> bool:
        return self.m_test_only

    @property
    def benchmark_roots(self) -> Dict[str, str]:
        return {f_k.value: f_v for f_k, f_v in self.m_benchmark_roots.items()}

    def getBenchmarkRoot(self, f_storage: Union[StorageClass, str]) -> str:
        f_sc = f_storage if isinstance(f_storage, StorageClass) else StorageClass(f_storage)
        if f_sc not in self.m_benchmark_roots:
            raise SiteResolutionError(f"Unknown storage class: {f_storage}")
        return self.m_benchmark_roots[f_sc]

    @property
    def install_prefix(self) -> str:
        return self.m_install_prefix

    @property
    def executables(self) -> ExecutableRegistry:
        return self.m_executables

    @property
    def modules(self) -> Tuple[str, ...]:
        return self.m_modules

    @property
    def resources(self) -> Dict[str, ResourcePolicy]:
        return dict(self.m_resources)

    def getResourcePolicy(self, f_shape: str) -> ResourcePolicy:
        if f_shape not in self.m_resources:
            raise SiteResolutionError(
                f"Resource shape '{f_shape}' not found in profile '{self.m_name}'"
            )
        return self.m_resources[f_shape]

    @property
    def rank_identity(self) -> RankIdentityPolicy:
        return self.m_rank_identity

    @property
    def cancellation(self) -> CancellationPolicy:
        return self.m_cancellation

    @property
    def lustre_pools(self) -> Dict[str, Optional[str]]:
        return {f_k.value: f_v for f_k, f_v in self.m_lustre_pools.items()}

    def getLustrePool(self, f_storage: Union[StorageClass, str]) -> Optional[str]:
        f_sc = f_storage if isinstance(f_storage, StorageClass) else StorageClass(f_storage)
        if f_sc not in self.m_lustre_pools:
            raise SiteResolutionError(f"Unknown storage class: {f_storage}")
        return self.m_lustre_pools[f_sc]

    @property
    def requires_credentials(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    @property
    def requires_account(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    @property
    def requires_email(self) -> bool:
        return self.m_scheduler == SchedulerKind.SLURM

    def validateCredentials(
        self,
        f_account: Optional[str] = None,
        f_email: Optional[str] = None,
    ) -> None:
        if self.requires_credentials:
            if not f_account or not str(f_account).strip():
                raise SiteResolutionError(
                    f"Site '{self.m_name}' with Slurm scheduler requires a non-empty account (SB_ACCOUNT)"
                )
            if not f_email or not str(f_email).strip():
                raise SiteResolutionError(
                    f"Site '{self.m_name}' with Slurm scheduler requires a non-empty email (SB_EMAIL)"
                )

    def toDict(self) -> Dict[str, Any]:
        return {
            "name": self.m_name,
            "scheduler": self.m_scheduler.value,
            "launcher": self.m_launcher.kind,
            "certification": self.m_certification.value,
            "test_only": self.m_test_only,
            "benchmark_roots": {f_k.value: f_v for f_k, f_v in self.m_benchmark_roots.items()},
            "install_prefix": self.m_install_prefix,
            "executables": self.m_executables.toDict(),
            "modules": list(self.m_modules),
            "resources": {f_k: f_v.toDict() for f_k, f_v in self.m_resources.items()},
            "rank_identity": self.m_rank_identity.toDict(),
            "cancellation": self.m_cancellation.toDict(),
            "lustre_pools": {f_k.value: f_v for f_k, f_v in self.m_lustre_pools.items()},
        }


class SiteProfileRegistry:
    """Immutable registry of resolved site profiles."""

    __slots__ = ("m_profiles", "_frozen")

    def __init__(self, f_profiles: Mapping[str, SiteProfile]) -> None:
        for f_name, f_prof in f_profiles.items():
            if not isinstance(f_prof, SiteProfile):
                raise SiteResolutionError(
                    f"Profile '{f_name}' must be a SiteProfile instance, got: {f_prof!r}"
                )
        super().__setattr__("m_profiles", dict(f_profiles))
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
    def profiles(self) -> Dict[str, SiteProfile]:
        return dict(self.m_profiles)

    def getProfile(self, f_name: str) -> SiteProfile:
        f_key = f_name.upper() if isinstance(f_name, str) else str(f_name)
        if f_key not in self.m_profiles:
            raise SiteResolutionError(f"Profile '{f_name}' not found in registry")
        return self.m_profiles[f_key]

    def hasProfile(self, f_name: str) -> bool:
        f_key = f_name.upper() if isinstance(f_name, str) else str(f_name)
        return f_key in self.m_profiles

    def __getitem__(self, f_name: str) -> SiteProfile:
        return self.getProfile(f_name)

    def toDict(self) -> Dict[str, Any]:
        return {f_k: f_v.toDict() for f_k, f_v in self.m_profiles.items()}


class EnvironmentResolver:
    """Resolver for detecting sites, expanding paths, and producing immutable SiteProfiles."""

    @classmethod
    def getDefaultProfilePath(cls) -> str:
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "etc", "environments.json")
        )

    @classmethod
    def _getSystemGroups(cls) -> List[str]:
        try:
            import grp
            f_gids = os.getgroups()
            return [grp.getgrgid(f_gid).gr_name for f_gid in f_gids]
        except Exception:
            return []

    @classmethod
    def detect(
        cls,
        f_hostname: Optional[str] = None,
        f_groups: Optional[Iterable[str]] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_test_mode: bool = False,
    ) -> str:
        """
        Detect target HPC environment name.

        Site detection order and rules:
        - If LSMIO_ENV is set:
          - "DEV" requires explicit f_test_mode=True.
          - Known production sites: "VIKING", "VIKING2", "ARCHER2", "ISAMBARD".
          - Unknown values raise SiteResolutionError.
        - If LSMIO_ENV is not set:
          - Hostname & group inspection:
            - Viking2: "viking2" in hostname
            - Viking: "viking" in hostname and not "viking2" in hostname
            - Isambard: hostname starts with "xci" or "nid"
            - Archer2: "archer2" in hostname or "archer2" in groups
          - Ambiguous sightings (multiple matches) fail closed.
          - Unknown production sightings fail closed unless f_test_mode is True (yielding "DEV").
        """
        f_environ = os.environ if f_env is None else f_env

        f_lsmio_env = f_environ.get("LSMIO_ENV")
        if f_lsmio_env is not None and f_lsmio_env.strip():
            f_site = f_lsmio_env.strip().upper()
            if f_site == "DEV":
                if not f_test_mode:
                    raise SiteResolutionError(
                        "DEV environment requires explicit test_mode=True"
                    )
                return "DEV"
            if f_site in {"VIKING", "VIKING2", "ARCHER2", "ISAMBARD"}:
                return f_site
            raise SiteResolutionError(f"Unknown LSMIO_ENV value: {f_lsmio_env!r}")

        f_hn = (f_hostname if f_hostname is not None else platform.node()).strip().lower()
        f_raw_groups = cls._getSystemGroups() if f_groups is None else list(f_groups)
        f_grps = [str(g).strip().lower() for g in f_raw_groups]

        f_is_isambard = f_hn.startswith("xci") or f_hn.startswith("nid")
        f_is_viking2 = "viking2" in f_hn
        f_is_viking = "viking" in f_hn and not f_is_viking2
        f_is_archer2 = "archer2" in f_hn or "archer2" in f_grps

        f_matches: List[str] = []
        if f_is_isambard:
            f_matches.append("ISAMBARD")
        if f_is_viking2:
            f_matches.append("VIKING2")
        if f_is_viking:
            f_matches.append("VIKING")
        if f_is_archer2:
            f_matches.append("ARCHER2")

        if len(f_matches) > 1:
            raise SiteResolutionError(
                f"Ambiguous site detection: matched {f_matches} for hostname={f_hn!r}, groups={f_grps!r}"
            )
        if len(f_matches) == 1:
            return f_matches[0]

        if f_test_mode:
            return "DEV"

        raise SiteResolutionError(
            f"Unknown HPC environment for hostname={f_hn!r}, groups={f_grps!r}. Production detection failed."
        )

    @classmethod
    def _expandTemplate(cls, f_template: str, f_user: str, f_home: str) -> str:
        """
        Expand {user} and {home} placeholders in f_template.

        Rejects unexpanded placeholders, malformed braces, path escaping (..),
        and non-absolute resulting paths.
        """
        if not isinstance(f_template, str) or not f_template:
            raise SiteResolutionError(
                f"Template path must be a non-empty string, got: {f_template!r}"
            )
        if not isinstance(f_user, str) or not f_user:
            raise SiteResolutionError(
                f"User must be a non-empty string, got: {f_user!r}"
            )
        if not isinstance(f_home, str) or not f_home.startswith("/"):
            raise SiteResolutionError(
                f"Home must be an absolute path, got: {f_home!r}"
            )

        if "/" in f_user or ".." in f_user or "\0" in f_user:
            raise SiteResolutionError(
                f"Invalid user name '{f_user}' contains illegal characters or path traversal"
            )

        if ".." in f_home.split("/") or "\0" in f_home:
            raise SiteResolutionError(
                f"Invalid home directory '{f_home}' contains path traversal"
            )

        f_placeholders = re.findall(r"\{([^{}]+)\}", f_template)
        for f_p in f_placeholders:
            if f_p not in ("user", "home"):
                raise SiteResolutionError(
                    f"Unresolved template placeholder '{{{f_p}}}' in '{f_template}'"
                )

        f_expanded = f_template.replace("{user}", f_user).replace("{home}", f_home)
        if "{" in f_expanded or "}" in f_expanded:
            raise SiteResolutionError(
                f"Malformed or unresolved braces in '{f_expanded}'"
            )

        if ".." in f_template.split("/") or ".." in f_expanded.split("/"):
            raise SiteResolutionError(
                f"Escaping path traversal prohibited in template '{f_template}'"
            )

        f_norm = os.path.normpath(f_expanded)
        if ".." in f_norm.split("/") or not f_norm.startswith("/"):
            raise SiteResolutionError(
                f"Resolved path must be absolute and non-escaping: '{f_norm}'"
            )

        return f_norm

    @classmethod
    def resolveProfile(
        cls,
        f_profile_or_name: Union[ProfileRecord, str],
        f_user: Optional[str] = None,
        f_home: Optional[str] = None,
        f_document: Optional[ProfileDocument] = None,
        f_env_file: Optional[str] = None,
    ) -> SiteProfile:
        """
        Resolve a ProfileRecord or named site profile into an immutable SiteProfile.

        Performs typed decoding of mail modes through the selected scheduler enum,
        expands benchmark roots and install prefix templates, resolves executables
        below install_prefix/bin, and validates all resource policies and rank mappings.
        """
        if isinstance(f_profile_or_name, str):
            f_doc = f_document
            if f_doc is None:
                f_path = f_env_file or cls.getDefaultProfilePath()
                f_doc = ProfileLoader.load(f_path)
            f_record = f_doc.getProfile(f_profile_or_name.upper())
        elif isinstance(f_profile_or_name, ProfileRecord):
            f_record = f_profile_or_name
        else:
            raise SiteResolutionError(
                f"Expected ProfileRecord or site name string, got: {type(f_profile_or_name).__name__}"
            )

        f_resolved_user = f_user
        if f_resolved_user is None:
            f_resolved_user = os.environ.get("USER")
            if not f_resolved_user:
                raise SiteResolutionError(
                    "USER environment variable or explicit f_user argument is required for profile resolution"
                )

        f_resolved_home = f_home
        if f_resolved_home is None:
            f_resolved_home = os.environ.get("HOME")
            if not f_resolved_home:
                raise SiteResolutionError(
                    "HOME environment variable or explicit f_home argument is required for profile resolution"
                )

        # Scheduler kind
        f_raw_sched = f_record.scheduler.lower()
        if f_raw_sched == "slurm":
            f_scheduler = SchedulerKind.SLURM
        elif f_raw_sched == "pbs":
            f_scheduler = SchedulerKind.PBS
        elif f_raw_sched == "fake":
            f_scheduler = SchedulerKind.FAKE
        else:
            raise SiteResolutionError(f"Unknown scheduler kind: {f_record.scheduler!r}")

        # Launcher policy
        f_launcher = LauncherPolicy(f_record.launcher)

        # Certification state
        f_raw_cert = f_record.certification.lower()
        if f_raw_cert == "configured":
            f_cert = CertificationState.CONFIGURED
        elif f_raw_cert == "certified":
            f_cert = CertificationState.CERTIFIED
        else:
            raise SiteResolutionError(
                f"Unknown certification state: {f_record.certification!r}"
            )

        f_test_only = bool(f_record.test_only)

        # Benchmark roots
        f_roots: Dict[StorageClass, str] = {}
        for f_st_name, f_tmpl in f_record.benchmark_roots.items():
            f_sc = StorageClass(f_st_name)
            f_roots[f_sc] = cls._expandTemplate(f_tmpl, f_resolved_user, f_resolved_home)

        # Install prefix
        f_prefix = cls._expandTemplate(
            f_record.install_prefix, f_resolved_user, f_resolved_home
        )

        # Executables
        f_exec_dict: Dict[str, str] = {}
        for f_ex_name, f_ex_basename in f_record.executables.items():
            f_exec_dict[f_ex_name] = os.path.join(f_prefix, "bin", f_ex_basename)
        f_exec_registry = ExecutableRegistry(f_exec_dict)

        # Modules
        f_modules = tuple(f_record.modules)

        # Resources with backend-typed mail modes
        f_res_dict: Dict[str, ResourcePolicy] = {}
        for f_shape in ("small", "large"):
            f_shape_data = f_record.resources[f_shape]
            f_raw_mail = f_shape_data.get("mail_mode")
            f_mail_mode: Optional[Union[SlurmMailMode, PbsMailMode]] = None

            if f_raw_mail is not None:
                if not isinstance(f_raw_mail, str):
                    raise SiteResolutionError(
                        f"mail_mode in JSON must be string or None, got: {type(f_raw_mail).__name__}"
                    )
                if f_scheduler == SchedulerKind.SLURM:
                    if f_raw_mail == SlurmMailMode.END_FAIL.value:
                        f_mail_mode = SlurmMailMode.END_FAIL
                    else:
                        raise SiteResolutionError(
                            f"Invalid Slurm mail_mode '{f_raw_mail}'; only '{SlurmMailMode.END_FAIL.value}' is supported"
                        )
                elif f_scheduler == SchedulerKind.PBS:
                    if f_raw_mail == PbsMailMode.ABE.value:
                        f_mail_mode = PbsMailMode.ABE
                    else:
                        raise SiteResolutionError(
                            f"Invalid PBS mail_mode '{f_raw_mail}'; only '{PbsMailMode.ABE.value}' is supported"
                        )
                else:  # FAKE
                    raise SiteResolutionError(
                        f"Fake scheduler does not support mail_mode: '{f_raw_mail}'"
                    )

            f_res_dict[f_shape] = ResourcePolicy(
                f_scheduler=f_scheduler,
                f_walltime_policy=f_shape_data.get("walltime_policy"),
                f_queue=f_shape_data.get("queue"),
                f_partition=f_shape_data.get("partition"),
                f_qos=f_shape_data.get("qos"),
                f_memory=f_shape_data.get("memory"),
                f_mail_mode=f_mail_mode,
                f_pmem=f_shape_data.get("pmem"),
                f_pvmem=f_shape_data.get("pvmem"),
            )

        # Rank identity
        f_rank_dict = f_record.rank_identity
        f_rank_identity = RankIdentityPolicy(
            f_global_rank=f_rank_dict["global"],
            f_node_name=f_rank_dict["node"],
            f_local_rank=f_rank_dict.get("local"),
        )

        # Cancellation
        f_canc_dict = f_record.cancellation
        f_cancellation = CancellationPolicy(
            f_poll_interval_seconds=f_canc_dict["poll_interval_seconds"],
            f_grace_seconds=f_canc_dict["grace_seconds"],
        )

        # Lustre pools
        f_pools: Dict[StorageClass, Optional[str]] = {}
        for f_st_name, f_pool_val in f_record.lustre_pools.items():
            f_sc = StorageClass(f_st_name)
            f_pools[f_sc] = f_pool_val

        return SiteProfile(
            f_name=f_record.name,
            f_scheduler=f_scheduler,
            f_launcher=f_launcher,
            f_certification=f_cert,
            f_test_only=f_test_only,
            f_benchmark_roots=f_roots,
            f_install_prefix=f_prefix,
            f_executables=f_exec_registry,
            f_modules=f_modules,
            f_resources=f_res_dict,
            f_rank_identity=f_rank_identity,
            f_cancellation=f_cancellation,
            f_lustre_pools=f_pools,
        )

    @classmethod
    def resolveRegistry(
        cls,
        f_document_or_path: Optional[Union[ProfileDocument, str]] = None,
        f_user: Optional[str] = None,
        f_home: Optional[str] = None,
    ) -> SiteProfileRegistry:
        """
        Resolve all profiles within a ProfileDocument or from the default path into a SiteProfileRegistry.
        """
        if isinstance(f_document_or_path, ProfileDocument):
            f_doc = f_document_or_path
        else:
            f_path = f_document_or_path or cls.getDefaultProfilePath()
            f_doc = ProfileLoader.load(f_path)

        f_resolved_profiles: Dict[str, SiteProfile] = {}
        for f_name, f_rec in f_doc.profiles.items():
            f_prof = cls.resolveProfile(f_rec, f_user=f_user, f_home=f_home)
            f_resolved_profiles[f_name] = f_prof

        return SiteProfileRegistry(f_resolved_profiles)
