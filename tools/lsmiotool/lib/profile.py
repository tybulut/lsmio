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
import json
import os
import stat
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple


class ProfileSchemaError(Exception):
    """Exception raised when profile schema validation fails."""
    pass


class ProfileRecord:
    """Immutable representation of a single site profile."""

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
        f_scheduler: str,
        f_launcher: str,
        f_certification: str,
        f_test_only: bool,
        f_benchmark_roots: Dict[str, str],
        f_install_prefix: str,
        f_executables: Dict[str, str],
        f_modules: List[str],
        f_resources: Dict[str, Dict[str, Optional[str]]],
        f_rank_identity: Dict[str, Optional[str]],
        f_cancellation: Dict[str, int],
        f_lustre_pools: Dict[str, Optional[str]],
    ) -> None:
        super().__setattr__("m_name", f_name)
        super().__setattr__("m_scheduler", f_scheduler)
        super().__setattr__("m_launcher", f_launcher)
        super().__setattr__("m_certification", f_certification)
        super().__setattr__("m_test_only", f_test_only)
        super().__setattr__(
            "m_benchmark_roots", dict(copy.deepcopy(f_benchmark_roots))
        )
        super().__setattr__("m_install_prefix", f_install_prefix)
        super().__setattr__(
            "m_executables", dict(copy.deepcopy(f_executables))
        )
        super().__setattr__("m_modules", tuple(f_modules))
        super().__setattr__(
            "m_resources", dict(copy.deepcopy(f_resources))
        )
        super().__setattr__(
            "m_rank_identity", dict(copy.deepcopy(f_rank_identity))
        )
        super().__setattr__(
            "m_cancellation", dict(copy.deepcopy(f_cancellation))
        )
        super().__setattr__(
            "m_lustre_pools", dict(copy.deepcopy(f_lustre_pools))
        )
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
    def scheduler(self) -> str:
        return self.m_scheduler

    @property
    def launcher(self) -> str:
        return self.m_launcher

    @property
    def certification(self) -> str:
        return self.m_certification

    @property
    def test_only(self) -> bool:
        return self.m_test_only

    @property
    def benchmark_roots(self) -> Dict[str, str]:
        return copy.deepcopy(self.m_benchmark_roots)

    @property
    def install_prefix(self) -> str:
        return self.m_install_prefix

    @property
    def executables(self) -> Dict[str, str]:
        return copy.deepcopy(self.m_executables)

    @property
    def modules(self) -> Tuple[str, ...]:
        return self.m_modules

    @property
    def resources(self) -> Dict[str, Dict[str, Optional[str]]]:
        return copy.deepcopy(self.m_resources)

    @property
    def rank_identity(self) -> Dict[str, Optional[str]]:
        return copy.deepcopy(self.m_rank_identity)

    @property
    def cancellation(self) -> Dict[str, int]:
        return copy.deepcopy(self.m_cancellation)

    @property
    def lustre_pools(self) -> Dict[str, Optional[str]]:
        return copy.deepcopy(self.m_lustre_pools)

    def toDict(self) -> Dict[str, Any]:
        """Convert record to canonical dictionary structure."""
        return {
            "scheduler": self.m_scheduler,
            "launcher": self.m_launcher,
            "certification": self.m_certification,
            "test_only": self.m_test_only,
            "benchmark_roots": copy.deepcopy(self.m_benchmark_roots),
            "install_prefix": self.m_install_prefix,
            "executables": copy.deepcopy(self.m_executables),
            "modules": list(self.m_modules),
            "resources": copy.deepcopy(self.m_resources),
            "rank_identity": copy.deepcopy(self.m_rank_identity),
            "cancellation": copy.deepcopy(self.m_cancellation),
            "lustre_pools": copy.deepcopy(self.m_lustre_pools),
        }


class ProfileDocument:
    """Immutable representation of the RUN_PROFILES document."""

    __slots__ = ("m_schema_version", "m_profiles", "_frozen")

    def __init__(
        self,
        f_schema_version: int,
        f_profiles: Mapping[str, ProfileRecord],
    ) -> None:
        super().__setattr__("m_schema_version", f_schema_version)
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
    def schema_version(self) -> int:
        return self.m_schema_version

    @property
    def profiles(self) -> Dict[str, ProfileRecord]:
        return dict(self.m_profiles)

    def getProfile(self, f_name: str) -> ProfileRecord:
        """Get profile by site name or raise ProfileSchemaError if missing."""
        if f_name not in self.m_profiles:
            raise ProfileSchemaError(f"Profile '{f_name}' not found in profile document")
        return self.m_profiles[f_name]

    def toDict(self) -> Dict[str, Any]:
        """Convert document to canonical dictionary structure."""
        return {
            "schema_version": self.m_schema_version,
            "profiles": {
                f_name: f_rec.toDict()
                for f_name, f_rec in self.m_profiles.items()
            },
        }


class ProfileLoader:
    """Loader and validator for RUN_PROFILES schema-version-1 document."""

    _REQUIRED_DOCUMENT_KEYS: Set[str] = {"schema_version", "profiles"}
    _REQUIRED_SITES: Set[str] = {"DEV", "VIKING", "VIKING2", "ARCHER2", "ISAMBARD"}
    _REQUIRED_PROFILE_KEYS: Set[str] = {
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
    _REQUIRED_ROOT_KEYS: Set[str] = {"hdd", "ssd"}
    _REQUIRED_EXECUTABLE_KEYS: Set[str] = {
        "ior",
        "lmp",
        "bm_native",
        "bm_adios",
        "bm_rocksdb",
        "bm_leveldb",
        "bm_manager",
    }
    _REQUIRED_RESOURCE_SHAPES: Set[str] = {"small", "large"}
    _REQUIRED_SHAPE_FIELDS: Set[str] = {
        "walltime_policy",
        "queue",
        "partition",
        "qos",
        "memory",
        "mail_mode",
        "pmem",
        "pvmem",
    }
    _REQUIRED_RANK_KEYS: Set[str] = {"global", "node", "local"}
    _REQUIRED_CANCELLATION_KEYS: Set[str] = {
        "poll_interval_seconds",
        "grace_seconds",
    }
    _REQUIRED_POOL_KEYS: Set[str] = {"hdd", "ssd"}

    @classmethod
    def load(cls, f_path: str) -> ProfileDocument:
        """
        Load and strictly validate RUN_PROFILES document from f_path.

        Validates that f_path is a regular readable file (not a symlink),
        parses the JSON content, enforces schema_version == 1, checks all
        exact keys and types, and returns an immutable ProfileDocument.
        """
        if not isinstance(f_path, str) or not f_path:
            raise ProfileSchemaError(f"Profile path must be a non-empty string, got: {f_path!r}")

        try:
            f_stat = os.lstat(f_path)
        except (FileNotFoundError, OSError) as f_exc:
            raise ProfileSchemaError(
                f"Failed to stat profile path '{f_path}': {f_exc}"
            ) from f_exc

        if stat.S_ISLNK(f_stat.st_mode):
            raise ProfileSchemaError(
                f"Profile path '{f_path}' is a symlink, which is rejected"
            )

        if not stat.S_ISREG(f_stat.st_mode):
            raise ProfileSchemaError(
                f"Profile path '{f_path}' is not a regular file"
            )

        try:
            with open(f_path, "r", encoding="utf-8") as f_file:
                f_raw_json = json.load(f_file)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as f_exc:
            raise ProfileSchemaError(
                f"Failed to read or parse JSON from '{f_path}': {f_exc}"
            ) from f_exc

        return cls._validateAndBuildDocument(f_raw_json)

    @classmethod
    def _validateAndBuildDocument(cls, f_raw_json: Any) -> ProfileDocument:
        if not isinstance(f_raw_json, dict):
            raise ProfileSchemaError("Top-level JSON content must be a dictionary")

        if "RUN_PROFILES" not in f_raw_json:
            raise ProfileSchemaError("Missing top-level 'RUN_PROFILES' key in JSON")

        f_run_profiles = f_raw_json["RUN_PROFILES"]
        if not isinstance(f_run_profiles, dict):
            raise ProfileSchemaError("'RUN_PROFILES' section must be a dictionary")

        f_doc_keys = set(f_run_profiles.keys())
        if f_doc_keys != cls._REQUIRED_DOCUMENT_KEYS:
            f_missing = cls._REQUIRED_DOCUMENT_KEYS - f_doc_keys
            f_extra = f_doc_keys - cls._REQUIRED_DOCUMENT_KEYS
            raise ProfileSchemaError(
                f"RUN_PROFILES keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )

        f_schema_version = f_run_profiles["schema_version"]
        if isinstance(f_schema_version, bool) or not isinstance(f_schema_version, int):
            raise ProfileSchemaError(
                f"schema_version must be an integer, got {type(f_schema_version).__name__}"
            )
        if f_schema_version != 1:
            raise ProfileSchemaError(
                f"Unsupported schema_version: {f_schema_version} (expected 1)"
            )

        f_profiles_data = f_run_profiles["profiles"]
        if not isinstance(f_profiles_data, dict):
            raise ProfileSchemaError("'profiles' member must be a dictionary")

        f_site_keys = set(f_profiles_data.keys())
        if f_site_keys != cls._REQUIRED_SITES:
            f_missing = cls._REQUIRED_SITES - f_site_keys
            f_extra = f_site_keys - cls._REQUIRED_SITES
            raise ProfileSchemaError(
                f"Profiles site mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )

        f_parsed_profiles: Dict[str, ProfileRecord] = {}
        for f_site_name, f_site_dict in f_profiles_data.items():
            f_parsed_profiles[f_site_name] = cls._validateAndBuildProfileRecord(
                f_site_name, f_site_dict
            )

        return ProfileDocument(
            f_schema_version=f_schema_version,
            f_profiles=f_parsed_profiles,
        )

    @classmethod
    def _validateAndBuildProfileRecord(
        cls, f_site_name: str, f_site_dict: Any
    ) -> ProfileRecord:
        if not isinstance(f_site_dict, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}' must be a dictionary"
            )

        f_keys = set(f_site_dict.keys())
        if f_keys != cls._REQUIRED_PROFILE_KEYS:
            f_missing = cls._REQUIRED_PROFILE_KEYS - f_keys
            f_extra = f_keys - cls._REQUIRED_PROFILE_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}' keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )

        # scheduler
        f_scheduler = f_site_dict["scheduler"]
        if not isinstance(f_scheduler, str) or not f_scheduler:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.scheduler must be a non-empty string"
            )

        # launcher
        f_launcher = f_site_dict["launcher"]
        if not isinstance(f_launcher, str) or not f_launcher:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.launcher must be a non-empty string"
            )

        # certification
        f_certification = f_site_dict["certification"]
        if not isinstance(f_certification, str) or not f_certification:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.certification must be a non-empty string"
            )

        # test_only
        f_test_only = f_site_dict["test_only"]
        if not isinstance(f_test_only, bool):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.test_only must be a boolean"
            )

        # install_prefix
        f_install_prefix = f_site_dict["install_prefix"]
        if not isinstance(f_install_prefix, str) or not f_install_prefix:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.install_prefix must be a non-empty string"
            )

        # benchmark_roots
        f_benchmark_roots = f_site_dict["benchmark_roots"]
        if not isinstance(f_benchmark_roots, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.benchmark_roots must be a dictionary"
            )
        f_root_keys = set(f_benchmark_roots.keys())
        if f_root_keys != cls._REQUIRED_ROOT_KEYS:
            f_missing = cls._REQUIRED_ROOT_KEYS - f_root_keys
            f_extra = f_root_keys - cls._REQUIRED_ROOT_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.benchmark_roots keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        for f_rk, f_rv in f_benchmark_roots.items():
            if not isinstance(f_rv, str) or not f_rv:
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.benchmark_roots['{f_rk}'] must be a non-empty string"
                )

        # executables
        f_executables = f_site_dict["executables"]
        if not isinstance(f_executables, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.executables must be a dictionary"
            )
        f_exec_keys = set(f_executables.keys())
        if f_exec_keys != cls._REQUIRED_EXECUTABLE_KEYS:
            f_missing = cls._REQUIRED_EXECUTABLE_KEYS - f_exec_keys
            f_extra = f_exec_keys - cls._REQUIRED_EXECUTABLE_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.executables keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        for f_ek, f_ev in f_executables.items():
            if not isinstance(f_ev, str) or not f_ev:
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.executables['{f_ek}'] must be a non-empty string"
                )

        # modules
        f_modules = f_site_dict["modules"]
        if not isinstance(f_modules, list):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.modules must be a list of strings"
            )
        for f_mod in f_modules:
            if not isinstance(f_mod, str) or not f_mod:
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.modules entries must be non-empty strings"
                )

        # resources
        f_resources = f_site_dict["resources"]
        if not isinstance(f_resources, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.resources must be a dictionary"
            )
        f_res_shapes = set(f_resources.keys())
        if f_res_shapes != cls._REQUIRED_RESOURCE_SHAPES:
            f_missing = cls._REQUIRED_RESOURCE_SHAPES - f_res_shapes
            f_extra = f_res_shapes - cls._REQUIRED_RESOURCE_SHAPES
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.resources shapes mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        for f_shape_name, f_shape_dict in f_resources.items():
            if not isinstance(f_shape_dict, dict):
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.resources['{f_shape_name}'] must be a dictionary"
                )
            f_shape_fields = set(f_shape_dict.keys())
            if f_shape_fields != cls._REQUIRED_SHAPE_FIELDS:
                f_missing = cls._REQUIRED_SHAPE_FIELDS - f_shape_fields
                f_extra = f_shape_fields - cls._REQUIRED_SHAPE_FIELDS
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.resources['{f_shape_name}'] fields mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
                )
            for f_sfk, f_sfv in f_shape_dict.items():
                if f_sfv is not None and not isinstance(f_sfv, str):
                    raise ProfileSchemaError(
                        f"Profile '{f_site_name}'.resources['{f_shape_name}']['{f_sfk}'] must be a string or null"
                    )

        # rank_identity
        f_rank_identity = f_site_dict["rank_identity"]
        if not isinstance(f_rank_identity, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.rank_identity must be a dictionary"
            )
        f_rank_keys = set(f_rank_identity.keys())
        if f_rank_keys != cls._REQUIRED_RANK_KEYS:
            f_missing = cls._REQUIRED_RANK_KEYS - f_rank_keys
            f_extra = f_rank_keys - cls._REQUIRED_RANK_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.rank_identity keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        if not isinstance(f_rank_identity["global"], str) or not f_rank_identity["global"]:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.rank_identity['global'] must be a non-empty string"
            )
        if not isinstance(f_rank_identity["node"], str) or not f_rank_identity["node"]:
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.rank_identity['node'] must be a non-empty string"
            )
        if f_rank_identity["local"] is not None and not isinstance(f_rank_identity["local"], str):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.rank_identity['local'] must be a string or null"
            )

        # cancellation
        f_cancellation = f_site_dict["cancellation"]
        if not isinstance(f_cancellation, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.cancellation must be a dictionary"
            )
        f_cancel_keys = set(f_cancellation.keys())
        if f_cancel_keys != cls._REQUIRED_CANCELLATION_KEYS:
            f_missing = cls._REQUIRED_CANCELLATION_KEYS - f_cancel_keys
            f_extra = f_cancel_keys - cls._REQUIRED_CANCELLATION_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.cancellation keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        for f_ck, f_cv in f_cancellation.items():
            if isinstance(f_cv, bool) or not isinstance(f_cv, int) or f_cv <= 0:
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.cancellation['{f_ck}'] must be a positive integer"
                )

        # lustre_pools
        f_lustre_pools = f_site_dict["lustre_pools"]
        if not isinstance(f_lustre_pools, dict):
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.lustre_pools must be a dictionary"
            )
        f_pool_keys = set(f_lustre_pools.keys())
        if f_pool_keys != cls._REQUIRED_POOL_KEYS:
            f_missing = cls._REQUIRED_POOL_KEYS - f_pool_keys
            f_extra = f_pool_keys - cls._REQUIRED_POOL_KEYS
            raise ProfileSchemaError(
                f"Profile '{f_site_name}'.lustre_pools keys mismatch: missing={sorted(f_missing)}, extra={sorted(f_extra)}"
            )
        for f_pk, f_pv in f_lustre_pools.items():
            if f_pv is not None and not isinstance(f_pv, str):
                raise ProfileSchemaError(
                    f"Profile '{f_site_name}'.lustre_pools['{f_pk}'] must be a string or null"
                )

        return ProfileRecord(
            f_name=f_site_name,
            f_scheduler=f_scheduler,
            f_launcher=f_launcher,
            f_certification=f_certification,
            f_test_only=f_test_only,
            f_benchmark_roots=f_benchmark_roots,
            f_install_prefix=f_install_prefix,
            f_executables=f_executables,
            f_modules=f_modules,
            f_resources=f_resources,
            f_rank_identity=f_rank_identity,
            f_cancellation=f_cancellation,
            f_lustre_pools=f_lustre_pools,
        )
