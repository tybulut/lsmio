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
import getpass
import json
import math
import os
import re
import shlex
import sys
import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
    runtime_checkable,
)

from lsmiotool.lib.evidence import (
    EvidenceError,
    EvidenceKind,
    EvidenceRecord,
    EvidenceStore,
    JobHandle,
    WriterKind,
)
from lsmiotool.lib.run import (
    Combination,
    RunPlan,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.site import (
    PbsMailMode,
    ResourcePolicy,
    SchedulerKind,
    SiteProfile,
    SlurmMailMode,
)
from lsmiotool.lib.state import SchedulerJobState
from lsmiotool.lib.worker import (
    ModuleSetup,
    ProcessExecutionError,
    ProcessLoggingError,
    ProcessResult,
    ProcessRunner,
    ProcessSpawnError,
)


class SchedulerError(Exception):
    """Base exception for all scheduler and script rendering operations."""

    pass


class SchedulerScriptError(SchedulerError):
    """Raised when script rendering, directive validation, or token validation fails."""

    pass


class SubmissionDispatchError(SchedulerError):
    """Raised when submission dispatch orchestration, command execution, or recovery fails."""

    pass


# -------------------------------------------------------------------------
# Token Validation Patterns
# -------------------------------------------------------------------------

JOB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CORRELATION_TOKEN_PATTERN = re.compile(r"^lm-[0-9a-f]{24}$")
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
QUEUE_PARTITION_QOS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+$")
PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./%+-]+$")
MODULE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./+:@-]*$")


def _checkNoControlChars(f_val: str, f_field_name: str) -> None:
    """Validate that string contains no NUL bytes, newlines, carriage returns, or unprintable characters."""
    if "\0" in f_val:
        raise SchedulerScriptError(f"{f_field_name} contains NUL byte: {f_val!r}")
    if "\n" in f_val:
        raise SchedulerScriptError(f"{f_field_name} contains newline (\\n): {f_val!r}")
    if "\r" in f_val:
        raise SchedulerScriptError(f"{f_field_name} contains carriage return (\\r): {f_val!r}")
    if any(ord(f_c) < 32 or ord(f_c) == 127 for f_c in f_val):
        raise SchedulerScriptError(f"{f_field_name} contains control/unprintable characters: {f_val!r}")


def _checkNoDirectiveInjection(f_val: str, f_field_name: str) -> None:
    """Validate that string does not contain embedded directive injection patterns."""
    if "#SBATCH" in f_val or "#PBS" in f_val:
        raise SchedulerScriptError(
            f"{f_field_name} contains directive injection pattern: {f_val!r}"
        )


def validateTimeout(f_timeout: Any, f_param_name: str = "timeout") -> float:
    """Validate that a timeout value is a positive finite number (not bool, nan, inf, zero, or negative)."""
    if isinstance(f_timeout, bool) or not isinstance(f_timeout, (int, float)):
        raise SchedulerError(
            f"{f_param_name} must be a positive finite number, got {type(f_timeout).__name__}: {f_timeout!r}"
        )
    f_num = float(f_timeout)
    if math.isnan(f_num) or math.isinf(f_num) or f_num <= 0.0:
        raise SchedulerError(
            f"{f_param_name} must be a positive finite number, got: {f_timeout!r}"
        )
    return f_num


validate_timeout = validateTimeout


@runtime_checkable
class WorkerExecutableValidator(Protocol):
    """Protocol for injected worker executable path validators."""

    def validate(self, f_worker_path: str) -> str:
        """Validate and return approved worker path, or raise an exception."""
        ...


class JobSpec:
    """Immutable record specifying job submission parameters and script metadata."""

    __slots__ = (
        "m_point_id",
        "m_script_path",
        "m_working_dir",
        "m_resources",
        "m_mail_user",
        "m_mail_mode",
        "m_account",
        "m_output_path",
        "m_error_path",
        "m_job_name",
        "_frozen",
    )

    def __init__(
        self,
        f_point_id: Union[ScalePoint, str, int],
        f_script_path: str,
        f_working_dir: str,
        f_resources: Optional[Any] = None,
        f_mail_user: Optional[str] = None,
        f_mail_mode: Optional[Union[SlurmMailMode, PbsMailMode]] = None,
        f_account: Optional[str] = None,
        f_output_path: Optional[str] = None,
        f_error_path: Optional[str] = None,
        f_job_name: Optional[str] = None,
    ) -> None:
        if f_point_id is None:
            raise SchedulerScriptError("point_id cannot be None")
        f_norm_point_id = str(f_point_id).strip()
        if not f_norm_point_id:
            raise SchedulerScriptError("point_id cannot be empty")
        _checkNoControlChars(f_norm_point_id, "point_id")

        if not isinstance(f_script_path, str) or not f_script_path.strip():
            raise SchedulerScriptError(f"script_path must be a non-empty string, got: {f_script_path!r}")
        _checkNoControlChars(f_script_path, "script_path")

        if not isinstance(f_working_dir, str) or not f_working_dir.strip():
            raise SchedulerScriptError(f"working_dir must be a non-empty string, got: {f_working_dir!r}")
        _checkNoControlChars(f_working_dir, "working_dir")

        if f_mail_user is not None:
            if not isinstance(f_mail_user, str) or not f_mail_user.strip():
                raise SchedulerScriptError(f"mail_user must be a non-empty string or None, got: {f_mail_user!r}")
            _checkNoControlChars(f_mail_user, "mail_user")
            _checkNoDirectiveInjection(f_mail_user, "mail_user")

        if f_account is not None:
            if not isinstance(f_account, str) or not f_account.strip():
                raise SchedulerScriptError(f"account must be a non-empty string or None, got: {f_account!r}")
            _checkNoControlChars(f_account, "account")
            _checkNoDirectiveInjection(f_account, "account")

        if f_output_path is not None:
            if not isinstance(f_output_path, str) or not f_output_path.strip():
                raise SchedulerScriptError(f"output_path must be a non-empty string or None, got: {f_output_path!r}")
            _checkNoControlChars(f_output_path, "output_path")
            _checkNoDirectiveInjection(f_output_path, "output_path")

        if f_error_path is not None:
            if not isinstance(f_error_path, str) or not f_error_path.strip():
                raise SchedulerScriptError(f"error_path must be a non-empty string or None, got: {f_error_path!r}")
            _checkNoControlChars(f_error_path, "error_path")
            _checkNoDirectiveInjection(f_error_path, "error_path")

        if f_job_name is not None:
            if not isinstance(f_job_name, str) or not f_job_name.strip():
                raise SchedulerScriptError(f"job_name must be a non-empty string or None, got: {f_job_name!r}")
            _checkNoControlChars(f_job_name, "job_name")
            _checkNoDirectiveInjection(f_job_name, "job_name")

        object.__setattr__(self, "m_point_id", f_norm_point_id)
        object.__setattr__(self, "m_script_path", f_script_path.strip())
        object.__setattr__(self, "m_working_dir", f_working_dir.strip())
        object.__setattr__(self, "m_resources", f_resources)
        object.__setattr__(self, "m_mail_user", f_mail_user.strip() if f_mail_user else None)
        object.__setattr__(self, "m_mail_mode", f_mail_mode)
        object.__setattr__(self, "m_account", f_account.strip() if f_account else None)
        object.__setattr__(self, "m_output_path", f_output_path.strip() if f_output_path else None)
        object.__setattr__(self, "m_error_path", f_error_path.strip() if f_error_path else None)
        object.__setattr__(self, "m_job_name", f_job_name.strip() if f_job_name else None)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def pointId(self) -> str:
        return self.m_point_id

    @property
    def point_id(self) -> str:
        return self.m_point_id

    @property
    def scriptPath(self) -> str:
        return self.m_script_path

    @property
    def script_path(self) -> str:
        return self.m_script_path

    @property
    def workingDir(self) -> str:
        return self.m_working_dir

    @property
    def working_dir(self) -> str:
        return self.m_working_dir

    @property
    def resources(self) -> Optional[Any]:
        return self.m_resources

    @property
    def mailUser(self) -> Optional[str]:
        return self.m_mail_user

    @property
    def mail_user(self) -> Optional[str]:
        return self.m_mail_user

    @property
    def mailMode(self) -> Optional[Union[SlurmMailMode, PbsMailMode]]:
        return self.m_mail_mode

    @property
    def mail_mode(self) -> Optional[Union[SlurmMailMode, PbsMailMode]]:
        return self.m_mail_mode

    @property
    def account(self) -> Optional[str]:
        return self.m_account

    @property
    def outputPath(self) -> Optional[str]:
        return self.m_output_path

    @property
    def output_path(self) -> Optional[str]:
        return self.m_output_path

    @property
    def errorPath(self) -> Optional[str]:
        return self.m_error_path

    @property
    def error_path(self) -> Optional[str]:
        return self.m_error_path

    @property
    def jobName(self) -> Optional[str]:
        return self.m_job_name

    @property
    def job_name(self) -> Optional[str]:
        return self.m_job_name

    def toDict(self) -> Dict[str, Any]:
        return {
            "point_id": self.m_point_id,
            "script_path": self.m_script_path,
            "working_dir": self.m_working_dir,
            "resources": (
                self.m_resources.toDict()
                if hasattr(self.m_resources, "toDict")
                else self.m_resources
            ),
            "mail_user": self.m_mail_user,
            "mail_mode": self.m_mail_mode.value if self.m_mail_mode is not None else None,
            "account": self.m_account,
            "output_path": self.m_output_path,
            "error_path": self.m_error_path,
            "job_name": self.m_job_name,
        }

    def __repr__(self) -> str:
        return (
            f"JobSpec(point_id={self.m_point_id!r}, "
            f"script_path={self.m_script_path!r}, "
            f"job_name={self.m_job_name!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, JobSpec):
            return (
                self.m_point_id == f_other.m_point_id
                and self.m_script_path == f_other.m_script_path
                and self.m_working_dir == f_other.m_working_dir
                and self.m_resources == f_other.m_resources
                and self.m_mail_user == f_other.m_mail_user
                and self.m_mail_mode == f_other.m_mail_mode
                and self.m_account == f_other.m_account
                and self.m_output_path == f_other.m_output_path
                and self.m_error_path == f_other.m_error_path
                and self.m_job_name == f_other.m_job_name
            )
        return False

    def __hash__(self) -> int:
        return hash((self.m_point_id, self.m_script_path, self.m_job_name))


class JobResult:
    """Immutable result of a scheduler execution or dispatch operation."""

    __slots__ = (
        "m_job_handle",
        "m_raw_output",
        "m_exit_code",
        "m_status",
        "m_diagnostics",
        "_frozen",
    )

    def __init__(
        self,
        f_job_handle: JobHandle,
        f_raw_output: str = "",
        f_exit_code: int = 0,
        f_status: Union[SchedulerJobState, str] = SchedulerJobState.QUEUED,
        f_diagnostics: Optional[Sequence[str]] = None,
    ) -> None:
        if not isinstance(f_job_handle, JobHandle):
            raise SchedulerError(f"job_handle must be JobHandle, got: {type(f_job_handle).__name__}")

        if isinstance(f_status, str):
            try:
                f_norm_status = SchedulerJobState(f_status.lower().strip())
            except ValueError:
                f_norm_status = f_status.strip()
        else:
            f_norm_status = f_status

        f_diag_tuple = tuple(str(f_d) for f_d in (f_diagnostics or ()))

        object.__setattr__(self, "m_job_handle", f_job_handle)
        object.__setattr__(self, "m_raw_output", str(f_raw_output) if f_raw_output is not None else "")
        object.__setattr__(self, "m_exit_code", int(f_exit_code))
        object.__setattr__(self, "m_status", f_norm_status)
        object.__setattr__(self, "m_diagnostics", f_diag_tuple)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot delete attribute from immutable {self.__class__.__name__}")
        super().__delattr__(f_key)

    @property
    def jobHandle(self) -> JobHandle:
        return self.m_job_handle

    @property
    def job_handle(self) -> JobHandle:
        return self.m_job_handle

    @property
    def rawOutput(self) -> str:
        return self.m_raw_output

    @property
    def raw_output(self) -> str:
        return self.m_raw_output

    @property
    def exitCode(self) -> int:
        return self.m_exit_code

    @property
    def exit_code(self) -> int:
        return self.m_exit_code

    @property
    def status(self) -> Union[SchedulerJobState, str]:
        return self.m_status

    @property
    def diagnostics(self) -> Tuple[str, ...]:
        return self.m_diagnostics

    @property
    def isSuccess(self) -> bool:
        return self.m_exit_code == 0 and (
            self.m_status in (SchedulerJobState.SUCCEEDED, SchedulerJobState.QUEUED, SchedulerJobState.ACTIVE)
            or str(self.m_status).lower() in ("succeeded", "queued", "active")
        )

    @property
    def is_success(self) -> bool:
        return self.isSuccess

    def toDict(self) -> Dict[str, Any]:
        return {
            "job_handle": self.m_job_handle.toDict(),
            "raw_output": self.m_raw_output,
            "exit_code": self.m_exit_code,
            "status": self.m_status.value if isinstance(self.m_status, SchedulerJobState) else str(self.m_status),
            "diagnostics": list(self.m_diagnostics),
            "is_success": self.is_success,
        }

    def __repr__(self) -> str:
        return (
            f"JobResult(job_handle={self.m_job_handle!r}, "
            f"exit_code={self.m_exit_code}, "
            f"status={self.m_status!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if isinstance(f_other, JobResult):
            return (
                self.m_job_handle == f_other.m_job_handle
                and self.m_raw_output == f_other.m_raw_output
                and self.m_exit_code == f_other.m_exit_code
                and self.m_status == f_other.m_status
                and self.m_diagnostics == f_other.m_diagnostics
            )
        return False


# -------------------------------------------------------------------------
# Scheduler Script Renderer
# -------------------------------------------------------------------------

class SchedulerScriptRenderer:
    """Scheduler-neutral job script renderer and directive validator.

    Invariants:
    - Renders structured backend directives (#SBATCH or #PBS) contiguous after '#!/bin/bash'.
    - Emits fail-fast 'set -euo pipefail' immediately following directives.
    - Emits one-time module setup preamble via ModuleSetup.render(profile).
    - Emits POSIX-quoted worker execution tail:
        exec <shlex.quote(worker)> allocation <shlex.quote(manifest)> <shlex.quote(point_id)>
    - Dispatches ONLY typed SlurmMailMode (END_FAIL='END,FAIL') or PbsMailMode (ABE='abe').
    - Rejects raw strings, cross-backend enums, injected values, newlines, CR, NUL, and foreign directives.
    - Performs NO filesystem inspection itself, delegating worker validation to injected protocol.
    """

    __slots__ = ()

    def __init__(self) -> None:
        pass

    @classmethod
    def validateJobName(cls, f_name: Any, f_strict_token: bool = False) -> str:
        """Validate scheduler job name / correlation token string."""
        if not isinstance(f_name, str):
            raise SchedulerScriptError(f"Job name must be a string, got: {type(f_name).__name__}")
        f_norm = f_name.strip()
        if not f_norm:
            raise SchedulerScriptError("Job name cannot be empty")
        _checkNoControlChars(f_name, "job_name")
        _checkNoDirectiveInjection(f_name, "job_name")

        if f_strict_token:
            if not CORRELATION_TOKEN_PATTERN.match(f_norm):
                raise SchedulerScriptError(
                    f"Job name does not match correlation token format '^lm-[0-9a-f]{{24}}$': {f_name!r}"
                )
        else:
            if not JOB_NAME_PATTERN.match(f_norm):
                raise SchedulerScriptError(
                    f"Job name does not match pattern '^[A-Za-z0-9][A-Za-z0-9_.-]*$': {f_name!r}"
                )
        return f_norm

    validate_job_name = validateJobName

    @classmethod
    def validateAccount(cls, f_account: Any) -> str:
        """Validate scheduler account token string."""
        if not isinstance(f_account, str):
            raise SchedulerScriptError(f"Account must be a string, got: {type(f_account).__name__}")
        f_norm = f_account.strip()
        if not f_norm:
            raise SchedulerScriptError("Account cannot be empty")
        _checkNoControlChars(f_account, "account")
        _checkNoDirectiveInjection(f_account, "account")

        if not ACCOUNT_PATTERN.match(f_norm):
            raise SchedulerScriptError(
                f"Account does not match pattern '^[A-Za-z0-9][A-Za-z0-9_.-]*$': {f_account!r}"
            )
        return f_norm

    validate_account = validateAccount

    @classmethod
    def validateQueueOrPartition(cls, f_token: Any, f_field_name: str = "queue/partition") -> str:
        """Validate queue, partition, or QoS token string."""
        if not isinstance(f_token, str):
            raise SchedulerScriptError(f"{f_field_name} must be a string, got: {type(f_token).__name__}")
        f_norm = f_token.strip()
        if not f_norm:
            raise SchedulerScriptError(f"{f_field_name} cannot be empty")
        _checkNoControlChars(f_token, f_field_name)
        _checkNoDirectiveInjection(f_token, f_field_name)

        if not QUEUE_PARTITION_QOS_PATTERN.match(f_norm):
            raise SchedulerScriptError(
                f"{f_field_name} does not match pattern '^[A-Za-z0-9][A-Za-z0-9_.-]*$': {f_token!r}"
            )
        return f_norm

    validate_queue_or_partition = validateQueueOrPartition

    @classmethod
    def validateMailUser(cls, f_email: Any) -> str:
        """Validate email address string for scheduler notifications."""
        if not isinstance(f_email, str):
            raise SchedulerScriptError(f"Email must be a string, got: {type(f_email).__name__}")
        f_norm = f_email.strip()
        if not f_norm:
            raise SchedulerScriptError("Email cannot be empty")
        _checkNoControlChars(f_email, "mail_user")
        _checkNoDirectiveInjection(f_email, "mail_user")

        if not EMAIL_PATTERN.match(f_norm):
            raise SchedulerScriptError(
                f"Email does not match pattern '^[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+$': {f_email!r}"
            )
        return f_norm

    validate_mail_user = validateMailUser

    @classmethod
    def validateMailMode(cls, f_backend: SchedulerKind, f_mail_mode: Any) -> str:
        """Validate backend-typed mail mode enum.

        Accepts ONLY SlurmMailMode.END_FAIL for Slurm and PbsMailMode.ABE for PBS.
        Rejects raw strings, cross-backend enums, reordered, case-changed, and injected values.
        """
        if not isinstance(f_backend, SchedulerKind):
            raise SchedulerScriptError(f"Backend must be SchedulerKind, got: {type(f_backend).__name__}")

        if isinstance(f_mail_mode, str):
            raise SchedulerScriptError(
                f"Raw mail mode string {f_mail_mode!r} is rejected; must use typed backend enum"
            )

        if f_backend == SchedulerKind.SLURM:
            if not isinstance(f_mail_mode, SlurmMailMode):
                raise SchedulerScriptError(
                    f"Slurm backend requires SlurmMailMode enum, got: {type(f_mail_mode).__name__} ({f_mail_mode!r})"
                )
            if f_mail_mode != SlurmMailMode.END_FAIL or f_mail_mode.value != "END,FAIL":
                raise SchedulerScriptError(
                    f"Slurm backend requires exact SlurmMailMode.END_FAIL ('END,FAIL'), got: {f_mail_mode!r}"
                )
            return "END,FAIL"

        elif f_backend == SchedulerKind.PBS:
            if not isinstance(f_mail_mode, PbsMailMode):
                raise SchedulerScriptError(
                    f"PBS backend requires PbsMailMode enum, got: {type(f_mail_mode).__name__} ({f_mail_mode!r})"
                )
            if f_mail_mode != PbsMailMode.ABE or f_mail_mode.value != "abe":
                raise SchedulerScriptError(
                    f"PBS backend requires exact PbsMailMode.ABE ('abe'), got: {f_mail_mode!r}"
                )
            return "abe"

        elif f_backend == SchedulerKind.FAKE:
            if f_mail_mode is not None:
                raise SchedulerScriptError(
                    f"Fake scheduler does not accept mail mode, got: {f_mail_mode!r}"
                )
            return ""

        else:
            raise SchedulerScriptError(f"Unsupported scheduler backend for mail mode: {f_backend}")

    validate_mail_mode = validateMailMode

    @classmethod
    def validatePath(cls, f_path: Any, f_field_name: str = "path") -> str:
        """Validate absolute path token without filesystem calls."""
        if not isinstance(f_path, str):
            raise SchedulerScriptError(f"{f_field_name} must be a string, got: {type(f_path).__name__}")
        f_norm = f_path.strip()
        if not f_norm:
            raise SchedulerScriptError(f"{f_field_name} cannot be empty")
        _checkNoControlChars(f_path, f_field_name)
        _checkNoDirectiveInjection(f_path, f_field_name)

        if not f_norm.startswith("/"):
            raise SchedulerScriptError(f"{f_field_name} must be an absolute path: {f_path!r}")

        if not PATH_PATTERN.match(f_norm):
            raise SchedulerScriptError(
                f"{f_field_name} contains disallowed characters (expected '^[A-Za-z0-9_./%+-]+$'): {f_path!r}"
            )
        return f_norm

    validate_path = validatePath

    @classmethod
    def validateWorkerPath(
        cls,
        f_worker_executable: Any,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
    ) -> str:
        """Validate worker executable path using injected validator without making filesystem calls."""
        if not isinstance(f_worker_executable, str):
            raise SchedulerScriptError(
                f"Worker executable must be a string, got: {type(f_worker_executable).__name__}"
            )
        f_worker_str = f_worker_executable.strip()
        if not f_worker_str:
            raise SchedulerScriptError("Worker executable path cannot be empty")
        _checkNoControlChars(f_worker_executable, "worker_executable")
        _checkNoDirectiveInjection(f_worker_executable, "worker_executable")

        if not f_worker_str.startswith("/"):
            raise SchedulerScriptError(
                f"Worker executable path must be an absolute path, got: {f_worker_executable!r}"
            )

        if f_worker_validator is not None:
            try:
                if isinstance(f_worker_validator, type) and hasattr(f_worker_validator, "validate"):
                    f_validated = f_worker_validator.validate(f_worker_str)
                elif callable(f_worker_validator):
                    f_validated = f_worker_validator(f_worker_str)
                elif hasattr(f_worker_validator, "validate") and callable(getattr(f_worker_validator, "validate")):
                    f_validated = f_worker_validator.validate(f_worker_str)
                else:
                    raise SchedulerScriptError(
                        f"Injected worker validator is invalid: {type(f_worker_validator).__name__}"
                    )
            except Exception as f_val_err:
                raise SchedulerScriptError(
                    f"Worker executable validation failed for '{f_worker_str}': {f_val_err}"
                ) from f_val_err

            if not isinstance(f_validated, str) or not f_validated.strip():
                raise SchedulerScriptError(
                    f"Worker validator rejected worker executable '{f_worker_str}'"
                )
            return f_validated.strip()

        return f_worker_str

    validate_worker_path = validateWorkerPath

    @classmethod
    def renderExecutionTail(
        cls,
        f_worker_executable: str,
        f_manifest_path: str,
        f_point_id: Any,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
    ) -> str:
        """Construct POSIX-quoted worker execution tail: exec <worker> allocation <manifest> <point>."""
        f_valid_worker = cls.validateWorkerPath(f_worker_executable, f_worker_validator)

        if not isinstance(f_manifest_path, str) or not f_manifest_path.strip():
            raise SchedulerScriptError(f"Manifest path must be a non-empty string, got: {f_manifest_path!r}")
        _checkNoControlChars(f_manifest_path, "manifest_path")
        _checkNoDirectiveInjection(f_manifest_path, "manifest_path")
        if not f_manifest_path.strip().startswith("/"):
            raise SchedulerScriptError(f"Manifest path must be an absolute path: {f_manifest_path!r}")

        if f_point_id is None:
            raise SchedulerScriptError("Point ID cannot be None")
        f_point_str = str(f_point_id).strip()
        if not f_point_str:
            raise SchedulerScriptError("Point ID cannot be empty")
        _checkNoControlChars(f_point_str, "point_id")
        _checkNoDirectiveInjection(f_point_str, "point_id")

        f_quoted_worker = shlex.quote(f_valid_worker)
        f_quoted_manifest = shlex.quote(f_manifest_path.strip())
        f_quoted_point = shlex.quote(f_point_str)

        return f"exec {f_quoted_worker} allocation {f_quoted_manifest} {f_quoted_point}"

    render_execution_tail = renderExecutionTail

    @classmethod
    def renderModulePreamble(cls, f_profile: Any) -> str:
        """Render one-time module setup preamble via ModuleSetup."""
        if f_profile is None:
            return ""
        return ModuleSetup.render(f_profile)

    render_module_preamble = renderModulePreamble

    @classmethod
    def renderScript(
        cls,
        f_backend: SchedulerKind,
        f_directives: Sequence[str],
        f_profile: Any,
        f_worker_executable: str,
        f_manifest_path: str,
        f_point_id: Any,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
    ) -> str:
        """Render complete structured scheduler job script with strict section order and validation."""
        if not isinstance(f_backend, SchedulerKind):
            raise SchedulerScriptError(f"Backend must be SchedulerKind, got: {type(f_backend).__name__}")

        f_validated_directives: List[str] = []
        f_expected_prefix = (
            "#SBATCH" if f_backend == SchedulerKind.SLURM else "#PBS" if f_backend == SchedulerKind.PBS else ""
        )
        f_foreign_prefix = (
            "#PBS" if f_backend == SchedulerKind.SLURM else "#SBATCH" if f_backend == SchedulerKind.PBS else ""
        )

        for f_idx, f_dir_line in enumerate(f_directives):
            if not isinstance(f_dir_line, str) or not f_dir_line.strip():
                raise SchedulerScriptError(f"Directive at index {f_idx} must be a non-empty string")
            _checkNoControlChars(f_dir_line, f"directive[{f_idx}]")

            f_dir_stripped = f_dir_line.strip()
            if f_expected_prefix and not f_dir_stripped.startswith(f_expected_prefix):
                raise SchedulerScriptError(
                    f"Directive '{f_dir_stripped}' does not start with expected prefix '{f_expected_prefix}'"
                )
            if f_foreign_prefix and f_foreign_prefix in f_dir_stripped:
                raise SchedulerScriptError(
                    f"Foreign directive '{f_foreign_prefix}' detected in {f_backend.value} script: '{f_dir_stripped}'"
                )

            f_validated_directives.append(f_dir_stripped)

        # 1. Shebang
        f_sections: List[str] = ["#!/bin/bash"]

        # 2. Contiguous Directives
        if f_validated_directives:
            f_sections.extend(f_validated_directives)

        # 3. Fail-fast shell option
        f_sections.append("set -euo pipefail")

        # 4. One-time module preamble
        f_preamble = cls.renderModulePreamble(f_profile)
        if f_preamble:
            f_sections.append(f_preamble)

        # 5. Worker execution tail
        f_tail = cls.renderExecutionTail(
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_point_id,
            f_worker_validator=f_worker_validator,
        )
        f_sections.append(f_tail)

        f_full_script = "\n".join(f_sections) + "\n"

        # Validate script structure
        cls.validateScript(f_full_script, f_backend=f_backend)

        return f_full_script

    render_script = renderScript

    @classmethod
    def validateScript(cls, f_script: str, f_backend: Optional[SchedulerKind] = None) -> None:
        """Validate completed script sections, directive ordering, and absence of foreign/late directives."""
        if not isinstance(f_script, str) or not f_script.strip():
            raise SchedulerScriptError("Job script content cannot be empty")
        if "\0" in f_script:
            raise SchedulerScriptError("Job script content contains NUL byte")

        f_lines = [f_line.strip() for f_line in f_script.strip().splitlines() if f_line.strip()]
        if not f_lines:
            raise SchedulerScriptError("Job script contains no executable lines")

        # Line 0 must be '#!/bin/bash'
        if f_lines[0] != "#!/bin/bash":
            raise SchedulerScriptError(f"Script must start with '#!/bin/bash', got: {f_lines[0]!r}")

        # Determine backend if not explicitly provided
        f_has_sbatch = any(f_line.startswith("#SBATCH") for f_line in f_lines)
        f_has_pbs = any(f_line.startswith("#PBS") for f_line in f_lines)

        if f_has_sbatch and f_has_pbs:
            raise SchedulerScriptError("Script contains conflicting #SBATCH and #PBS directives")

        f_detected_backend = f_backend
        if f_detected_backend is None:
            if f_has_sbatch:
                f_detected_backend = SchedulerKind.SLURM
            elif f_has_pbs:
                f_detected_backend = SchedulerKind.PBS
            else:
                f_detected_backend = SchedulerKind.FAKE

        if f_detected_backend == SchedulerKind.SLURM and f_has_pbs:
            raise SchedulerScriptError("Foreign #PBS directive detected in Slurm script")
        if f_detected_backend == SchedulerKind.PBS and f_has_sbatch:
            raise SchedulerScriptError("Foreign #SBATCH directive detected in PBS script")

        # Check section boundaries
        f_seen_set_e = False
        f_seen_exec = False
        f_exec_line: Optional[str] = None

        for f_idx, f_line in enumerate(f_lines[1:], start=1):
            if f_line.startswith("#SBATCH") or f_line.startswith("#PBS"):
                if f_seen_set_e:
                    raise SchedulerScriptError(
                        f"Late directive '{f_line}' detected after fail-fast option at line {f_idx + 1}"
                    )
                if f_seen_exec:
                    raise SchedulerScriptError(
                        f"Late directive '{f_line}' detected after exec tail at line {f_idx + 1}"
                    )
            elif f_line in ("set -euo pipefail", "set -e"):
                f_seen_set_e = True
            elif f_line.startswith("exec "):
                if not f_seen_set_e:
                    raise SchedulerScriptError(
                        f"Exec tail encountered before fail-fast option at line {f_idx + 1}"
                    )
                f_seen_exec = True
                f_exec_line = f_line

        if not f_seen_set_e:
            raise SchedulerScriptError("Script is missing fail-fast 'set -euo pipefail' or 'set -e'")

        if not f_seen_exec or not f_exec_line:
            raise SchedulerScriptError("Script is missing 'exec <worker> allocation <manifest> <point>' tail")

        # Validate final exec line structure
        if not re.match(r"^exec\s+\S+\s+allocation\s+\S+\s+\S+$", f_exec_line):
            raise SchedulerScriptError(
                f"Exec tail does not match 'exec <worker> allocation <manifest> <point>': {f_exec_line!r}"
            )

    validate_script = validateScript


# -------------------------------------------------------------------------
# Scheduler Command Runner
# -------------------------------------------------------------------------

class SchedulerCommandRunner:
    """Command runner for external scheduler CLI operations (submit, query, cancel, recovery)."""

    __slots__ = ("m_process_runner",)

    def __init__(self, f_process_runner: Optional[ProcessRunner] = None) -> None:
        self.m_process_runner = f_process_runner or ProcessRunner()

    @property
    def processRunner(self) -> ProcessRunner:
        return self.m_process_runner

    @property
    def process_runner(self) -> ProcessRunner:
        return self.m_process_runner

    def run(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_timeout: Optional[float] = None,
    ) -> ProcessResult:
        """Execute scheduler CLI command directly via ProcessRunner."""
        return self.m_process_runner.run(
            f_argv,
            f_cwd=f_cwd,
            f_env=f_env,
            f_timeout=f_timeout,
        )


# -------------------------------------------------------------------------
# Scheduler Adapter Base
# -------------------------------------------------------------------------

class SchedulerAdapter:
    """Abstract base class for scheduler adapters managing submission, recovery, and evidence dispatch.

    Invariants:
    - Order of evidence records when dispatching a point:
      1. SUBMISSION_REQUESTED: recorded before building submit argv.
      2. Build exact argv.
      3. SUBMISSION_DISPATCHED: recorded immediately BEFORE process spawn with argv, correlation token, and script/point correlation (no invented post-return result).
      4. Execute submit command via SchedulerCommandRunner.
      5. Validate process status and output.
      6. SUBMISSION_RECORDED: recorded once exact job_id is extracted and verified into JobHandle.
    - If submission_dispatched exists without submission_recorded: recovers by token/job name.
    - Indeterminate recovery (0 or >1 candidates) fails closed without re-submitting.
    - A request without submission_dispatched may submit once.
    """

    __slots__ = (
        "m_backend",
        "m_command_runner",
        "m_evidence_store",
        "m_worker_validator",
        "m_command_timeout",
    )

    def __init__(
        self,
        f_backend: SchedulerKind,
        f_command_runner: Optional[SchedulerCommandRunner] = None,
        f_evidence_store: Optional[EvidenceStore] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_timeout: Optional[float] = None,
        f_command_timeout: Optional[float] = None,
        f_profile: Optional[SiteProfile] = None,
    ) -> None:
        if not isinstance(f_backend, SchedulerKind):
            raise SchedulerError(f"Backend must be SchedulerKind, got: {type(f_backend).__name__}")
        self.m_backend = f_backend
        self.m_command_runner = f_command_runner or SchedulerCommandRunner()
        self.m_evidence_store = f_evidence_store
        self.m_worker_validator = f_worker_validator

        # Derive positive finite command timeout
        f_raw_timeout: Any = None
        if f_timeout is not None:
            f_raw_timeout = f_timeout
        elif f_command_timeout is not None:
            f_raw_timeout = f_command_timeout
        elif f_profile is not None:
            f_raw_timeout = f_profile.cancellation.grace_seconds
        else:
            f_raw_timeout = 120.0

        self.m_command_timeout = self.validateTimeout(f_raw_timeout, "timeout")

    @classmethod
    def validateTimeout(cls, f_timeout: Any, f_param_name: str = "timeout") -> float:
        """Validate timeout value as positive finite float."""
        return validateTimeout(f_timeout, f_param_name)

    validate_timeout = validateTimeout

    @property
    def backend(self) -> SchedulerKind:
        return self.m_backend

    @property
    def commandRunner(self) -> SchedulerCommandRunner:
        return self.m_command_runner

    @property
    def command_runner(self) -> SchedulerCommandRunner:
        return self.m_command_runner

    @property
    def commandTimeout(self) -> float:
        return self.m_command_timeout

    @property
    def command_timeout(self) -> float:
        return self.m_command_timeout

    @property
    def timeout(self) -> float:
        return self.m_command_timeout

    @property
    def evidenceStore(self) -> Optional[EvidenceStore]:
        return self.m_evidence_store

    @property
    def evidence_store(self) -> Optional[EvidenceStore]:
        return self.m_evidence_store

    @property
    def workerValidator(self) -> Optional[Union[WorkerExecutableValidator, Callable[[str], str]]]:
        return self.m_worker_validator

    @property
    def worker_validator(self) -> Optional[Union[WorkerExecutableValidator, Callable[[str], str]]]:
        return self.m_worker_validator

    def _runCommand(
        self,
        f_argv: Sequence[str],
        f_cwd: Optional[str] = None,
        f_env: Optional[Mapping[str, str]] = None,
        f_timeout: Optional[float] = None,
    ) -> ProcessResult:
        """Helper to invoke command runner with timeout and fallback for legacy test mocks."""
        f_eff_timeout = f_timeout if f_timeout is not None else self.m_command_timeout
        try:
            return self.m_command_runner.run(
                f_argv,
                f_cwd=f_cwd,
                f_env=f_env,
                f_timeout=f_eff_timeout,
            )
        except TypeError as f_type_err:
            if "f_timeout" in str(f_type_err) or "unexpected keyword argument" in str(f_type_err):
                try:
                    return self.m_command_runner.run(f_argv, f_cwd=f_cwd)
                except TypeError:
                    return self.m_command_runner.run(f_argv)
            raise

    def buildSubmitArgv(self, f_spec: JobSpec) -> List[str]:
        """Build command argv for job script submission."""
        if self.m_backend == SchedulerKind.SLURM:
            return ["sbatch", "--parsable", f_spec.script_path]
        elif self.m_backend == SchedulerKind.PBS:
            return ["qsub", f_spec.script_path]
        elif self.m_backend == SchedulerKind.FAKE:
            return [f_spec.script_path]
        else:
            raise SchedulerError(f"Unsupported scheduler backend: {self.m_backend}")

    build_submit_argv = buildSubmitArgv

    def parseSubmitOutput(self, f_stdout: str) -> str:
        """Extract exact job ID string from submission command standard output."""
        if not isinstance(f_stdout, str) or not f_stdout.strip():
            raise SubmissionDispatchError(f"Submission output is empty or invalid: {f_stdout!r}")

        f_clean = f_stdout.strip()

        if self.m_backend == SchedulerKind.SLURM:
            # Strip only terminal line ending (\r\n or \n or \r)
            f_clean = f_stdout
            if f_clean.endswith("\r\n"):
                f_clean = f_clean[:-2]
            elif f_clean.endswith("\n") or f_clean.endswith("\r"):
                f_clean = f_clean[:-1]
            if not f_clean or not re.fullmatch(r"[0-9]+", f_clean):
                raise SubmissionDispatchError(
                    f"Slurm submission output does not match exact decimal ID '^[0-9]+$': {f_stdout!r}"
                )
            return f_clean

        elif self.m_backend == SchedulerKind.PBS:
            # Strip only terminal line ending (\r\n or \n or \r)
            f_clean = f_stdout
            if f_clean.endswith("\r\n"):
                f_clean = f_clean[:-2]
            elif f_clean.endswith("\n") or f_clean.endswith("\r"):
                f_clean = f_clean[:-1]
            if not f_clean:
                raise SubmissionDispatchError(
                    f"PBS submission output is empty: {f_stdout!r}"
                )
            m = re.fullmatch(r"([0-9]+)(?:\.[A-Za-z0-9._-]+)?", f_clean)
            if not m:
                raise SubmissionDispatchError(
                    f"PBS submission output does not match valid PBS ID pattern: {f_stdout!r}"
                )
            return m.group(1)

        elif self.m_backend == SchedulerKind.FAKE:
            return f_clean

        else:
            return f_clean

    parse_submit_output = parseSubmitOutput

    def recoverCandidateJobIds(self, f_job_name: str, f_user: Optional[str] = None) -> List[str]:
        """Query scheduler by exact job name / correlation token to discover candidate job IDs."""
        # Base adapter returns empty list; concrete Slurm/PBS adapters implement real query
        return []

    recover_candidate_job_ids = recoverCandidateJobIds

    def recoverJobHandle(self, f_job_name: str, f_user: Optional[str] = None) -> Optional[JobHandle]:
        """Recover JobHandle by exact correlation token / job name.

        Returns:
            JobHandle if exactly 1 distinct candidate is found.
            None if 0 candidates are found.

        Raises:
            SubmissionDispatchError: If multiple distinct candidate jobs are found (indeterminate).
        """
        if not f_job_name or not str(f_job_name).strip():
            return None

        f_candidates = self.recoverCandidateJobIds(f_job_name.strip(), f_user=f_user)
        f_unique_ids = sorted(list(set(f_candidates)))

        if len(f_unique_ids) == 0:
            return None
        elif len(f_unique_ids) == 1:
            return JobHandle(self.m_backend.value, f_unique_ids[0])
        else:
            raise SubmissionDispatchError(
                f"Indeterminate recovery: found multiple distinct candidate jobs for token '{f_job_name}': {f_unique_ids}"
            )

    recover_job_handle = recoverJobHandle

    def renderScript(
        self,
        f_directives: Sequence[str],
        f_profile: Any,
        f_worker_executable: str,
        f_manifest_path: str,
        f_point_id: Any,
    ) -> str:
        """Render structured scheduler script using this adapter's backend and worker validator."""
        return SchedulerScriptRenderer.renderScript(
            f_backend=self.m_backend,
            f_directives=f_directives,
            f_profile=f_profile,
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_point_id,
            f_worker_validator=self.m_worker_validator,
        )

    render_script = renderScript

    def dispatchSubmission(
        self,
        f_point: Union[ScalePoint, str, int],
        f_spec: JobSpec,
        f_writer_id: str = "control",
        f_ordinal: Optional[int] = None,
    ) -> JobResult:
        """Execute submission dispatch orchestration adhering to exact pre-spawn evidence protocol.

        Order of evidence records:
        1. Check existing records on crash recovery:
           - submission_recorded exists -> return recorded JobResult.
           - submission_dispatched exists without recorded handle -> recover by token; if single candidate persist and return; if 0 or >1 candidates fail closed (INDETERMINATE, never blindly resubmits).
           - submission_requested exists without dispatched -> proceed to submit once.
        2. SUBMISSION_REQUESTED: record before building argv/dispatching if not already recorded.
        3. Build exact submit argv.
        4. SUBMISSION_DISPATCHED: create-only record immediately BEFORE process spawn containing argv, correlation token, and script/point metadata (no invented post-return result).
        5. Execute submit command via SchedulerCommandRunner.
        6. Validate process status and output.
        7. SUBMISSION_RECORDED: record once job ID is extracted into JobHandle.
        """
        # Step 1: Check existing evidence records for recovery
        if self.m_evidence_store is not None:
            f_sub_records = self.m_evidence_store.readSubmissionRecords(f_point, f_ordinal=f_ordinal)
            f_rec_recorded = f_sub_records.get("submission_recorded")
            f_rec_dispatched = f_sub_records.get("submission_dispatched")
            f_rec_requested = f_sub_records.get("submission_requested")

            # Case A: Already recorded
            if f_rec_recorded is not None:
                f_payload = f_rec_recorded.payload
                f_handle_dict = f_payload.get("handle")
                if isinstance(f_handle_dict, dict):
                    f_handle = JobHandle.fromDict(f_handle_dict)
                    return JobResult(
                        f_job_handle=f_handle,
                        f_raw_output=str(f_payload.get("raw_output", "")),
                        f_exit_code=int(f_payload.get("exit_code", 0)),
                        f_status=SchedulerJobState.QUEUED,
                    )

            # Case B: Dispatched exists without recorded handle (Crash Window)
            if f_rec_dispatched is not None:
                if f_spec.job_name:
                    f_recovered_handle = self.recoverJobHandle(f_spec.job_name)
                    if f_recovered_handle is not None:
                        # Exactly 1 candidate found: persist and return
                        self.m_evidence_store.recordSubmissionRecorded(
                            f_point=f_point,
                            f_writer_id=f_writer_id,
                            f_handle=f_recovered_handle,
                            f_payload={"recovered": True, "job_name": f_spec.job_name},
                            f_ordinal=f_ordinal,
                        )
                        return JobResult(
                            f_job_handle=f_recovered_handle,
                            f_raw_output="recovered",
                            f_exit_code=0,
                            f_status=SchedulerJobState.QUEUED,
                        )
                    else:
                        raise SubmissionDispatchError(
                            f"Dispatched submission exists for point '{f_point}' but recovery found 0 candidate jobs for token '{f_spec.job_name}'"
                        )
                else:
                    raise SubmissionDispatchError(
                        f"Dispatched submission exists for point '{f_point}' without recorded handle and no job_name for recovery"
                    )

            # Case C: Requested exists without dispatched -> proceed to submit once

        # Step 2: Record SUBMISSION_REQUESTED if not already recorded
        if self.m_evidence_store is not None:
            f_existing_req = self.m_evidence_store.readSubmissionRecords(f_point, f_ordinal=f_ordinal).get("submission_requested")
            if f_existing_req is None:
                self.m_evidence_store.recordSubmissionRequested(
                    f_point=f_point,
                    f_writer_id=f_writer_id,
                    f_payload={
                        "script_path": f_spec.script_path,
                        "working_dir": f_spec.working_dir,
                        "job_name": f_spec.job_name,
                        "account": f_spec.account,
                        "mail_user": f_spec.mail_user,
                    },
                    f_ordinal=f_ordinal,
                )

        # Step 3: Build exact argv
        f_submit_argv = self.buildSubmitArgv(f_spec)

        # Step 4: Record SUBMISSION_DISPATCHED immediately BEFORE process spawn
        if self.m_evidence_store is not None:
            self.m_evidence_store.recordSubmissionDispatched(
                f_point=f_point,
                f_writer_id=f_writer_id,
                f_payload={
                    "argv": f_submit_argv,
                    "job_name": f_spec.job_name,
                    "correlation_token": f_spec.job_name,
                    "script_path": f_spec.script_path,
                    "working_dir": f_spec.working_dir,
                    "point_id": str(f_spec.point_id),
                },
                f_ordinal=f_ordinal,
            )

        # Step 5: Execute submit command via SchedulerCommandRunner
        f_proc_res = self._runCommand(
            f_submit_argv,
            f_cwd=f_spec.working_dir,
            f_timeout=self.m_command_timeout,
        )

        # Step 6: Validate process return code and timeout
        if f_proc_res.timed_out or not f_proc_res.is_success:
            f_err_msg = (
                "command timed out"
                if f_proc_res.timed_out
                else (
                    f_proc_res.stderr.strip()
                    or f_proc_res.stdout.strip()
                    or f"submit command exited with code {f_proc_res.returncode}"
                )
            )
            raise SubmissionDispatchError(
                f"Scheduler submission failed with return code {f_proc_res.returncode}: {f_err_msg}"
            )

        # Step 7: Extract Job ID and build JobHandle
        f_job_id = self.parseSubmitOutput(f_proc_res.stdout)
        f_handle = JobHandle(self.m_backend.value, f_job_id)

        # Step 8: Record SUBMISSION_RECORDED
        if self.m_evidence_store is not None:
            self.m_evidence_store.recordSubmissionRecorded(
                f_point=f_point,
                f_writer_id=f_writer_id,
                f_handle=f_handle,
                f_payload={
                    "raw_output": f_proc_res.stdout.strip(),
                    "exit_code": f_proc_res.returncode,
                    "job_name": f_spec.job_name,
                },
                f_ordinal=f_ordinal,
            )

        return JobResult(
            f_job_handle=f_handle,
            f_raw_output=f_proc_res.stdout,
            f_exit_code=f_proc_res.returncode,
            f_status=SchedulerJobState.QUEUED,
        )

    dispatch_submission = dispatchSubmission

    def submit(
        self,
        f_spec: JobSpec,
        f_point: Optional[Union[ScalePoint, str, int]] = None,
        f_writer_id: str = "control",
        f_ordinal: Optional[int] = None,
    ) -> JobResult:
        """Submit job specification for execution."""
        f_target_point = f_point if f_point is not None else f_spec.point_id
        return self.dispatchSubmission(
            f_point=f_target_point,
            f_spec=f_spec,
            f_writer_id=f_writer_id,
            f_ordinal=f_ordinal,
        )


# -------------------------------------------------------------------------
# Slurm Script Renderer
# -------------------------------------------------------------------------

class SlurmScriptRenderer(SchedulerScriptRenderer):
    """Slurm-specific job script renderer adhering to exact directive order and site policies.

    Directive Order:
    1. #SBATCH --job-name=<job_name>
    2. #SBATCH --ntasks=<tasks>
    3. #SBATCH --nodes=<nodes>
    4. #SBATCH --ntasks-per-node=<ppn>
    5. Shape fields:
       - small (ppn=1): #SBATCH --ntasks-per-socket=1, #SBATCH --cpus-per-task=1
       - large (ppn=4): #SBATCH --ntasks-per-socket=2, #SBATCH --ntasks-per-core=1
    6. #SBATCH --distribution=cyclic:cyclic
    7. #SBATCH --time=<walltime> (e.g. 2 + nodes//3 hours formatted HH:MM:SS)
    8. #SBATCH --account=<account> (if configured / passed)
    9. #SBATCH --mail-user=<mail_user> (if configured / passed)
    10. #SBATCH --mail-type=END,FAIL (enforcing SlurmMailMode.END_FAIL)
    11. Site resource:
        - Viking / Viking2: #SBATCH --mem=8gb
        - Archer2: #SBATCH --partition=standard, #SBATCH --qos=standard (NO mem directive)
    12. #SBATCH --output=<output_path>
    13. #SBATCH --error=<error_path>
    Followed immediately by 'set -euo pipefail', one-time ModuleSetup.render(profile), and POSIX-quoted worker execution tail.
    """

    __slots__ = ()

    @classmethod
    def computeWalltime(cls, f_nodes: int) -> str:
        """Compute walltime string HH:MM:SS based on Slurm node formula: 2 + nodes // 3 hours."""
        if not isinstance(f_nodes, int) or f_nodes <= 0:
            raise SchedulerScriptError(f"Nodes must be a positive integer, got: {f_nodes!r}")
        f_hours = 2 + (f_nodes // 3)
        return f"{f_hours:02d}:00:00"

    compute_walltime = computeWalltime

    @classmethod
    def renderDirectives(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_job_name: str,
        f_output_path: str,
        f_error_path: str,
        f_account: Optional[str] = None,
        f_mail_user: Optional[str] = None,
        f_mail_mode: Optional[Union[SlurmMailMode, Any]] = SlurmMailMode.END_FAIL,
        f_walltime: Optional[str] = None,
    ) -> List[str]:
        """Render Slurm #SBATCH directives in exact prescribed order."""
        if f_point is None:
            raise SchedulerScriptError("Scale point cannot be None")
        if not hasattr(f_point, "tasks") or not hasattr(f_point, "nodes") or not hasattr(f_point, "ppn"):
            raise SchedulerScriptError(f"Scale point must have tasks, nodes, ppn, got: {f_point!r}")

        f_tasks = int(f_point.tasks)
        f_nodes = int(f_point.nodes)
        f_ppn = int(f_point.ppn)

        if f_tasks <= 0:
            raise SchedulerScriptError(f"Tasks must be positive, got: {f_tasks}")
        if f_nodes <= 0:
            raise SchedulerScriptError(f"Nodes must be positive, got: {f_nodes}")
        if f_ppn not in (1, 4):
            raise SchedulerScriptError(f"Slurm ppn must be 1 or 4, got: {f_ppn}")
        if f_tasks != f_nodes * f_ppn:
            raise SchedulerScriptError(
                f"Tasks ({f_tasks}) must equal nodes ({f_nodes}) * ppn ({f_ppn})"
            )

        # Validate tokens
        f_valid_job_name = cls.validateJobName(f_job_name)
        f_valid_out_path = cls.validatePath(f_output_path, "output_path")
        f_valid_err_path = cls.validatePath(f_error_path, "error_path")

        # Validate mail mode
        f_valid_mail_mode = cls.validateMailMode(SchedulerKind.SLURM, f_mail_mode)

        # Validate walltime
        if f_walltime is not None:
            if not isinstance(f_walltime, str) or not f_walltime.strip():
                raise SchedulerScriptError(f"walltime must be a non-empty string, got: {f_walltime!r}")
            _checkNoControlChars(f_walltime, "walltime")
            _checkNoDirectiveInjection(f_walltime, "walltime")
            f_norm_walltime = f_walltime.strip()
            if not re.match(r"^\d+:\d{2}:\d{2}$", f_norm_walltime):
                raise SchedulerScriptError(
                    f"Walltime must match HH:MM:SS format (e.g. '04:00:00'), got: {f_walltime!r}"
                )
            f_time_str = f_norm_walltime
        else:
            f_time_str = cls.computeWalltime(f_nodes)

        # Directives list in exact sequence:
        f_directives: List[str] = []

        # 1. job-name
        f_directives.append(f"#SBATCH --job-name={f_valid_job_name}")

        # 2. ntasks
        f_directives.append(f"#SBATCH --ntasks={f_tasks}")

        # 3. nodes
        f_directives.append(f"#SBATCH --nodes={f_nodes}")

        # 4. ntasks-per-node
        f_directives.append(f"#SBATCH --ntasks-per-node={f_ppn}")

        # 5. Shape fields
        if f_ppn == 1:
            f_directives.append("#SBATCH --ntasks-per-socket=1")
            f_directives.append("#SBATCH --cpus-per-task=1")
        elif f_ppn == 4:
            f_directives.append("#SBATCH --ntasks-per-socket=2")
            f_directives.append("#SBATCH --ntasks-per-core=1")

        # 6. distribution
        f_directives.append("#SBATCH --distribution=cyclic:cyclic")

        # 7. time
        f_directives.append(f"#SBATCH --time={f_time_str}")

        # 8. account (if configured / passed)
        if f_account is not None and str(f_account).strip():
            f_valid_acc = cls.validateAccount(f_account)
            f_directives.append(f"#SBATCH --account={f_valid_acc}")

        # 9. mail-user (if configured / passed)
        if f_mail_user is not None and str(f_mail_user).strip():
            f_valid_mail = cls.validateMailUser(f_mail_user)
            f_directives.append(f"#SBATCH --mail-user={f_valid_mail}")

        # 10. mail-type
        f_directives.append(f"#SBATCH --mail-type={f_valid_mail_mode}")

        # 11. Site resource
        f_shape_name = "small" if f_ppn == 1 else "large"
        f_res_policy = None
        if hasattr(f_profile, "resources"):
            if isinstance(f_profile.resources, dict):
                f_res_policy = f_profile.resources.get(f_shape_name)
            elif hasattr(f_profile.resources, f_shape_name):
                f_res_policy = getattr(f_profile.resources, f_shape_name)

        if f_res_policy is not None:
            if getattr(f_res_policy, "partition", None) is not None:
                f_part = cls.validateQueueOrPartition(f_res_policy.partition, "partition")
                f_directives.append(f"#SBATCH --partition={f_part}")
            if getattr(f_res_policy, "qos", None) is not None:
                f_qos = cls.validateQueueOrPartition(f_res_policy.qos, "qos")
                f_directives.append(f"#SBATCH --qos={f_qos}")
            if getattr(f_res_policy, "memory", None) is not None:
                _checkNoControlChars(f_res_policy.memory, "memory")
                _checkNoDirectiveInjection(f_res_policy.memory, "memory")
                f_directives.append(f"#SBATCH --mem={f_res_policy.memory}")

        # 12. output
        f_directives.append(f"#SBATCH --output={f_valid_out_path}")

        # 13. error
        f_directives.append(f"#SBATCH --error={f_valid_err_path}")

        return f_directives

    render_directives = renderDirectives

    @classmethod
    def render(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_worker_executable: str,
        f_manifest_path: str,
        f_job_name: str,
        f_output_path: str,
        f_error_path: str,
        f_account: Optional[str] = None,
        f_mail_user: Optional[str] = None,
        f_mail_mode: Optional[Union[SlurmMailMode, Any]] = SlurmMailMode.END_FAIL,
        f_walltime: Optional[str] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_point_id: Optional[Any] = None,
    ) -> str:
        """Render complete structured Slurm script from discrete parameters."""
        f_dirs = cls.renderDirectives(
            f_point=f_point,
            f_profile=f_profile,
            f_job_name=f_job_name,
            f_output_path=f_output_path,
            f_error_path=f_error_path,
            f_account=f_account,
            f_mail_user=f_mail_user,
            f_mail_mode=f_mail_mode,
            f_walltime=f_walltime,
        )
        f_resolved_point_id = (
            f_point_id
            if f_point_id is not None
            else f"0-tasks-{f_point.tasks}"
            if hasattr(f_point, "tasks")
            else "0-tasks-1"
        )
        return cls.renderScript(
            f_backend=SchedulerKind.SLURM,
            f_directives=f_dirs,
            f_profile=f_profile,
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_resolved_point_id,
            f_worker_validator=f_worker_validator,
        )

    @classmethod
    def renderJobScript(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_spec: JobSpec,
        f_worker_executable: str,
        f_manifest_path: str,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
    ) -> str:
        """Render complete structured Slurm script from JobSpec."""
        f_dirs = cls.renderDirectives(
            f_point=f_point,
            f_profile=f_profile,
            f_job_name=f_spec.job_name or "lm-000000000000000000000000",
            f_output_path=f_spec.output_path or "/tmp/out.log",
            f_error_path=f_spec.error_path or "/tmp/err.log",
            f_account=f_spec.account,
            f_mail_user=f_spec.mail_user,
            f_mail_mode=f_spec.mail_mode or SlurmMailMode.END_FAIL,
            f_walltime=getattr(f_spec.resources, "walltime", None) if f_spec.resources else None,
        )
        return cls.renderScript(
            f_backend=SchedulerKind.SLURM,
            f_directives=f_dirs,
            f_profile=f_profile,
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_spec.point_id,
            f_worker_validator=f_worker_validator,
        )

    render_job_script = renderJobScript


# -------------------------------------------------------------------------
# PBS Script Renderer
# -------------------------------------------------------------------------

class PbsScriptRenderer(SchedulerScriptRenderer):
    """PBS-specific job script renderer adhering to exact Isambard directive order and resource policies.

    Directive Order:
    1. #PBS -q arm
    2. #PBS -m abe (enforcing PbsMailMode.ABE)
    3. #PBS -N <job_name>
    4. #PBS -l select=<nodes>:ncpus=<ppn>:mpiprocs=<ppn>:mem=32GB
    5. If small scale (ppn == 1):
       #PBS -l pmem=8G
       #PBS -l pvmem=8G
       (If large scale ppn == 4, omits pmem and pvmem)
    6. #PBS -l walltime=06:00:00 (fixed 6 hours; NEVER computed)
    7. #PBS -o <output_path>
    8. #PBS -e <error_path>
    Followed immediately by 'set -euo pipefail', one-time ModuleSetup.render(profile), and POSIX-quoted worker execution tail.

    Prohibitions & Invariants:
    - NEVER render #SBATCH directives, Slurm account, email, or variable walltime.
    - Reject SlurmMailMode (SlurmMailMode.END_FAIL), raw strings, or injected mail values with SchedulerScriptError.
    - Strict token validation on job_name, output_path, and error_path rejecting newlines, NUL bytes, and #PBS/#SBATCH directive injections.
    """

    __slots__ = ()

    FIXED_WALLTIME = "06:00:00"

    @classmethod
    def renderDirectives(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_job_name: str,
        f_output_path: str,
        f_error_path: str,
        f_mail_mode: Optional[Union[PbsMailMode, Any]] = PbsMailMode.ABE,
        f_walltime: Optional[str] = None,
    ) -> List[str]:
        """Render PBS #PBS directives in exact prescribed order."""
        if f_point is None:
            raise SchedulerScriptError("Scale point cannot be None")
        if not hasattr(f_point, "tasks") or not hasattr(f_point, "nodes") or not hasattr(f_point, "ppn"):
            raise SchedulerScriptError(f"Scale point must have tasks, nodes, ppn, got: {f_point!r}")

        f_tasks = int(f_point.tasks)
        f_nodes = int(f_point.nodes)
        f_ppn = int(f_point.ppn)

        if f_tasks <= 0:
            raise SchedulerScriptError(f"Tasks must be positive, got: {f_tasks}")
        if f_nodes <= 0:
            raise SchedulerScriptError(f"Nodes must be positive, got: {f_nodes}")
        if f_ppn not in (1, 4):
            raise SchedulerScriptError(f"PBS ppn must be 1 or 4, got: {f_ppn}")
        if f_tasks != f_nodes * f_ppn:
            raise SchedulerScriptError(
                f"Tasks ({f_tasks}) must equal nodes ({f_nodes}) * ppn ({f_ppn})"
            )

        # Validate tokens
        f_valid_job_name = cls.validateJobName(f_job_name)
        f_valid_out_path = cls.validatePath(f_output_path, "output_path")
        f_valid_err_path = cls.validatePath(f_error_path, "error_path")

        # Validate mail mode (strict PbsMailMode.ABE enforcement)
        f_valid_mail_mode = cls.validateMailMode(SchedulerKind.PBS, f_mail_mode)

        # Validate walltime: fixed 06:00:00; reject any variable or different walltime
        if f_walltime is not None:
            if not isinstance(f_walltime, str) or not f_walltime.strip():
                raise SchedulerScriptError(f"walltime must be a non-empty string, got: {f_walltime!r}")
            _checkNoControlChars(f_walltime, "walltime")
            _checkNoDirectiveInjection(f_walltime, "walltime")
            f_norm_walltime = f_walltime.strip()
            if f_norm_walltime != cls.FIXED_WALLTIME:
                raise SchedulerScriptError(
                    f"PBS walltime must be fixed '{cls.FIXED_WALLTIME}' (computed/variable walltime is rejected), got: {f_walltime!r}"
                )

        # Extract profile resource configuration if available
        f_shape_name = "small" if f_ppn == 1 else "large"
        f_res_policy = None
        if hasattr(f_profile, "resources"):
            if isinstance(f_profile.resources, dict):
                f_res_policy = f_profile.resources.get(f_shape_name)
            elif hasattr(f_profile.resources, f_shape_name):
                f_res_policy = getattr(f_profile.resources, f_shape_name)

        # 1. Queue: default 'arm'
        f_queue = "arm"
        if f_res_policy is not None and getattr(f_res_policy, "queue", None) is not None:
            f_queue = cls.validateQueueOrPartition(f_res_policy.queue, "queue")

        # 4. Memory per select chunk: default '32GB'
        f_mem = "32GB"
        if f_res_policy is not None and getattr(f_res_policy, "memory", None) is not None:
            _checkNoControlChars(f_res_policy.memory, "memory")
            _checkNoDirectiveInjection(f_res_policy.memory, "memory")
            f_mem = str(f_res_policy.memory).strip()

        # 5. pmem and pvmem for small scale (ppn == 1)
        f_pmem = "8G"
        f_pvmem = "8G"
        if f_res_policy is not None:
            if getattr(f_res_policy, "pmem", None) is not None:
                _checkNoControlChars(f_res_policy.pmem, "pmem")
                _checkNoDirectiveInjection(f_res_policy.pmem, "pmem")
                f_pmem = str(f_res_policy.pmem).strip()
            if getattr(f_res_policy, "pvmem", None) is not None:
                _checkNoControlChars(f_res_policy.pvmem, "pvmem")
                _checkNoDirectiveInjection(f_res_policy.pvmem, "pvmem")
                f_pvmem = str(f_res_policy.pvmem).strip()

        # Directives list in exact sequence:
        f_directives: List[str] = []

        # 1. Queue
        f_directives.append(f"#PBS -q {f_queue}")

        # 2. Mail mode
        f_directives.append(f"#PBS -m {f_valid_mail_mode}")

        # 3. Job name
        f_directives.append(f"#PBS -N {f_valid_job_name}")

        # 4. Select chunk
        f_directives.append(f"#PBS -l select={f_nodes}:ncpus={f_ppn}:mpiprocs={f_ppn}:mem={f_mem}")

        # 5. Small scale pmem / pvmem
        if f_ppn == 1:
            f_directives.append(f"#PBS -l pmem={f_pmem}")
            f_directives.append(f"#PBS -l pvmem={f_pvmem}")

        # 6. Fixed walltime
        f_directives.append(f"#PBS -l walltime={cls.FIXED_WALLTIME}")

        # 7. Output path
        f_directives.append(f"#PBS -o {f_valid_out_path}")

        # 8. Error path
        f_directives.append(f"#PBS -e {f_valid_err_path}")

        return f_directives

    render_directives = renderDirectives

    @classmethod
    def render(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_worker_executable: str,
        f_manifest_path: str,
        f_job_name: str,
        f_output_path: str,
        f_error_path: str,
        f_mail_mode: Optional[Union[PbsMailMode, Any]] = PbsMailMode.ABE,
        f_walltime: Optional[str] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_point_id: Optional[Any] = None,
    ) -> str:
        """Render complete structured PBS script from discrete parameters."""
        f_dirs = cls.renderDirectives(
            f_point=f_point,
            f_profile=f_profile,
            f_job_name=f_job_name,
            f_output_path=f_output_path,
            f_error_path=f_error_path,
            f_mail_mode=f_mail_mode,
            f_walltime=f_walltime,
        )
        f_resolved_point_id = (
            f_point_id
            if f_point_id is not None
            else f"0-tasks-{f_point.tasks}"
            if hasattr(f_point, "tasks")
            else "0-tasks-1"
        )
        return cls.renderScript(
            f_backend=SchedulerKind.PBS,
            f_directives=f_dirs,
            f_profile=f_profile,
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_resolved_point_id,
            f_worker_validator=f_worker_validator,
        )

    @classmethod
    def renderJobScript(
        cls,
        f_point: Union[ScalePoint, Any],
        f_profile: SiteProfile,
        f_spec: JobSpec,
        f_worker_executable: str,
        f_manifest_path: str,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
    ) -> str:
        """Render complete structured PBS script from JobSpec."""
        f_dirs = cls.renderDirectives(
            f_point=f_point,
            f_profile=f_profile,
            f_job_name=f_spec.job_name or "lm-000000000000000000000000",
            f_output_path=f_spec.output_path or "/tmp/out.log",
            f_error_path=f_spec.error_path or "/tmp/err.log",
            f_mail_mode=f_spec.mail_mode or PbsMailMode.ABE,
            f_walltime=getattr(f_spec.resources, "walltime", None) if f_spec.resources else None,
        )
        return cls.renderScript(
            f_backend=SchedulerKind.PBS,
            f_directives=f_dirs,
            f_profile=f_profile,
            f_worker_executable=f_worker_executable,
            f_manifest_path=f_manifest_path,
            f_point_id=f_spec.point_id,
            f_worker_validator=f_worker_validator,
        )

    render_job_script = renderJobScript


# -------------------------------------------------------------------------
# Slurm Scheduler Adapter
# -------------------------------------------------------------------------

class SlurmSchedulerAdapter(SchedulerAdapter):
    """Concrete Slurm scheduler adapter implementing exact commands, parsers, and recovery.

    Command Specifications:
    - submit: ['sbatch', '--parsable', <script_path>]
    - active query: ['squeue', '-j', <job_id>, '-h', '-o', '%T']
    - accounting query: ['sacct', '-j', <job_id>, '-P', '-n', '-o', 'JobIDRaw,State,ExitCode']
    - cancel: ['scancel', <job_id>]
    - recovery active: ['squeue', '--noheader', '--name=<job_name>', '--format=%i|%j|%T']
    - recovery terminal: ['sacct', '--noheader', '--parsable2', '--name=<job_name>', '--format=JobIDRaw,JobName,State,ExitCode']
    """

    __slots__ = ()

    def __init__(
        self,
        f_command_runner: Optional[SchedulerCommandRunner] = None,
        f_evidence_store: Optional[EvidenceStore] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_timeout: Optional[float] = None,
        f_command_timeout: Optional[float] = None,
        f_profile: Optional[SiteProfile] = None,
    ) -> None:
        super().__init__(
            f_backend=SchedulerKind.SLURM,
            f_command_runner=f_command_runner,
            f_evidence_store=f_evidence_store,
            f_worker_validator=f_worker_validator,
            f_timeout=f_timeout,
            f_command_timeout=f_command_timeout,
            f_profile=f_profile,
        )

    @classmethod
    def validateJobId(cls, f_job_id: Any) -> str:
        """Validate that Job ID is a non-empty exact decimal string '^[0-9]+$'."""
        if not isinstance(f_job_id, str):
            raise SchedulerError(f"Job ID must be a string, got: {type(f_job_id).__name__}")
        if not f_job_id:
            raise SchedulerError("Job ID cannot be empty")
        _checkNoControlChars(f_job_id, "job_id")
        if not re.fullmatch(r"[0-9]+", f_job_id):
            raise SchedulerError(
                f"Slurm Job ID must match exact decimal string '^[0-9]+$', got: {f_job_id!r}"
            )
        return f_job_id

    validate_job_id = validateJobId

    @classmethod
    def submitCommand(cls, f_script_path: str) -> List[str]:
        """Build exact sbatch submission argv: ['sbatch', '--parsable', <script_path>]."""
        if not isinstance(f_script_path, str) or not f_script_path.strip():
            raise SchedulerError(f"Script path must be a non-empty string, got: {f_script_path!r}")
        _checkNoControlChars(f_script_path, "script_path")
        return ["sbatch", "--parsable", f_script_path.strip()]

    submit_command = submitCommand

    def buildSubmitArgv(self, f_spec: JobSpec) -> List[str]:
        return self.submitCommand(f_spec.script_path)

    @classmethod
    def activeQueryCommand(cls, f_job_id: str) -> List[str]:
        """Build exact squeue active query argv: ['squeue', '--noheader', f'--jobs={job_id}', '--format=%i|%T']."""
        f_norm_id = cls.validateJobId(f_job_id)
        return ["squeue", "--noheader", f"--jobs={f_norm_id}", "--format=%i|%T"]

    active_query_command = activeQueryCommand
    buildActiveQueryArgv = activeQueryCommand
    build_active_query_argv = activeQueryCommand

    @classmethod
    def accountingQueryCommand(cls, f_job_id: str) -> List[str]:
        """Build exact sacct accounting query argv: ['sacct', '--noheader', '--parsable2', f'--jobs={job_id}', '--format=JobIDRaw,JobName,State,ExitCode']."""
        f_norm_id = cls.validateJobId(f_job_id)
        return [
            "sacct",
            "--noheader",
            "--parsable2",
            f"--jobs={f_norm_id}",
            "--format=JobIDRaw,JobName,State,ExitCode",
        ]

    accounting_query_command = accountingQueryCommand
    buildAccountingQueryArgv = accountingQueryCommand
    build_accounting_query_argv = accountingQueryCommand

    @classmethod
    def cancelCommand(cls, f_job_id: str) -> List[str]:
        """Build exact scancel cancel argv: ['scancel', <job_id>]."""
        f_norm_id = cls.validateJobId(f_job_id)
        return ["scancel", f_norm_id]

    cancel_command = cancelCommand
    buildCancelArgv = cancelCommand
    build_cancel_argv = cancelCommand

    @classmethod
    def recoveryActiveCommand(cls, f_job_name: str) -> List[str]:
        """Build exact squeue recovery query argv: ['squeue', '--noheader', f'--name={job_name}', '--format=%i|%j|%T']."""
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        return ["squeue", "--noheader", f"--name={f_valid_name}", "--format=%i|%j|%T"]

    recovery_active_command = recoveryActiveCommand

    @classmethod
    def recoveryTerminalCommand(cls, f_job_name: str, f_start_time: Optional[str] = None) -> List[str]:
        """Build exact sacct recovery query argv: ['sacct', '--noheader', '--parsable2', f'--name={job_name}', '--format=JobIDRaw,JobName,State,ExitCode']."""
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        f_argv = [
            "sacct",
            "--noheader",
            "--parsable2",
            f"--name={f_valid_name}",
            "--format=JobIDRaw,JobName,State,ExitCode",
        ]
        if f_start_time is not None:
            f_argv.append(f"--starttime={f_start_time}")
        return f_argv

    recovery_terminal_command = recoveryTerminalCommand

    @classmethod
    def mapSlurmState(cls, f_state_str: str, f_exit_code_str: Optional[str] = None) -> SchedulerJobState:
        """Map raw Slurm state string and optional exit code to normalized SchedulerJobState."""
        if not isinstance(f_state_str, str) or not f_state_str.strip():
            return SchedulerJobState.UNKNOWN

        f_clean = f_state_str.strip()
        f_token = f_clean.split()[0].rstrip("+").upper()

        if f_token in ("PENDING", "CONFIGURING", "PD", "CF"):
            return SchedulerJobState.QUEUED
        elif f_token in ("RUNNING", "COMPLETING", "SUSPENDED", "R", "CG", "S"):
            return SchedulerJobState.ACTIVE
        elif f_token in ("COMPLETED", "CD"):
            if f_exit_code_str is not None:
                f_exit_code_clean = f_exit_code_str.strip()
                if f_exit_code_clean in ("0:0", "0"):
                    return SchedulerJobState.SUCCEEDED
                else:
                    return SchedulerJobState.FAILED
            return SchedulerJobState.SUCCEEDED
        elif f_clean.upper().startswith("CANCELLED") or f_token in ("CANCELLED", "CA"):
            return SchedulerJobState.CANCELLED
        elif f_token in ("TIMEOUT", "TO"):
            return SchedulerJobState.TIMEOUT
        elif f_token in (
            "BOOT_FAIL",
            "DEADLINE",
            "FAILED",
            "NODE_FAIL",
            "OUT_OF_MEMORY",
            "PREEMPTED",
            "REVOKED",
            "SPECIAL_EXIT",
            "BF",
            "DL",
            "F",
            "NF",
            "OOM",
            "PR",
            "RV",
            "SE",
        ):
            return SchedulerJobState.FAILED
        else:
            return SchedulerJobState.UNKNOWN

    map_slurm_state = mapSlurmState

    @classmethod
    def parseActiveQuery(cls, f_output: str, f_job_id: Optional[str] = None) -> Optional[SchedulerJobState]:
        """Parse squeue output into normalized SchedulerJobState.

        Returns:
            SchedulerJobState if an active record is found.
            None if output is empty/blank (job is not in active queue).
        """
        if not isinstance(f_output, str):
            raise SchedulerError(f"squeue output must be a string, got: {type(f_output).__name__}")

        f_lines = [f_l.strip() for f_l in f_output.splitlines() if f_l.strip()]
        if not f_lines:
            return None

        # Filter header line if present
        f_data_lines = [
            f_l for f_l in f_lines
            if not f_l.startswith("JOBID") and not f_l.startswith("STATE") and not f_l.startswith("ST")
        ]
        if not f_data_lines:
            return None

        f_candidate_states: List[SchedulerJobState] = []
        f_expected_id = cls.validateJobId(f_job_id) if f_job_id is not None else None

        for f_line in f_data_lines:
            f_parts = [f_p.strip() for f_p in f_line.split("|")]
            if len(f_parts) == 2:
                # Format %i|%T
                f_raw_id, f_state_str = f_parts[0], f_parts[1]
            elif len(f_parts) == 3:
                # Format %i|%j|%T
                f_raw_id, _, f_state_str = f_parts[0], f_parts[1], f_parts[2]
            elif len(f_parts) == 7:
                # Format %i|%T|%M|%l|%j|%u|%b
                f_raw_id, f_state_str = f_parts[0], f_parts[1]
            else:
                raise SchedulerError(
                    f"Malformed squeue row: expected pipe-delimited fields, got: {f_line!r}"
                )

            # Validate f_raw_id: exact numeric or root array handle (e.g. 123456 or 123456_0)
            if not re.fullmatch(r"[0-9]+(_[0-9]+)?", f_raw_id):
                raise SchedulerError(f"Malformed Job ID in squeue output: {f_raw_id!r}")

            if f_expected_id is not None:
                f_base_id = f_raw_id.split("_", 1)[0]
                if f_raw_id != f_expected_id and f_base_id != f_expected_id:
                    continue

            f_norm_state = cls.mapSlurmState(f_state_str)
            f_candidate_states.append(f_norm_state)

        if not f_candidate_states:
            return None

        f_unique_states = list(set(f_candidate_states))
        if len(f_unique_states) == 1:
            return f_unique_states[0]
        else:
            raise SchedulerError(f"Conflicting active job states in squeue output: {f_candidate_states}")

    parse_active_query = parseActiveQuery
    parseActiveOutput = parseActiveQuery
    parse_active_output = parseActiveQuery

    @classmethod
    def parseAccountingQuery(
        cls,
        f_output: str,
        f_job_id: Optional[str] = None,
    ) -> Tuple[SchedulerJobState, Optional[int]]:
        """Parse sacct output, extracting root row and ignoring well-formed step rows.

        Returns:
            Tuple[SchedulerJobState, Optional[int]]: (normalized_state, returncode)
        """
        if not isinstance(f_output, str):
            raise SchedulerError(f"sacct output must be a string, got: {type(f_output).__name__}")

        f_lines = [f_l.strip() for f_l in f_output.splitlines() if f_l.strip()]
        if not f_lines:
            return (SchedulerJobState.UNKNOWN, None)

        f_root_candidates: List[Tuple[SchedulerJobState, int]] = []
        f_expected_id = cls.validateJobId(f_job_id) if f_job_id is not None else None

        for f_idx, f_line in enumerate(f_lines):
            if f_line.startswith("JobIDRaw|") or f_line.startswith("JobID|"):
                continue

            f_parts = [f_p.strip() for f_p in f_line.split("|")]
            if len(f_parts) == 3:
                # JobIDRaw, State, ExitCode
                f_raw_id, f_state_str, f_exit_str = f_parts[0], f_parts[1], f_parts[2]
            elif len(f_parts) == 4:
                # JobIDRaw, JobName, State, ExitCode
                f_raw_id, _, f_state_str, f_exit_str = f_parts[0], f_parts[1], f_parts[2], f_parts[3]
            elif len(f_parts) == 5:
                # JobIDRaw, JobName, State, ExitCode, Submit
                f_raw_id, _, f_state_str, f_exit_str = f_parts[0], f_parts[1], f_parts[2], f_parts[3]
            elif len(f_parts) == 10:
                # JobIDRaw, State, ExitCode, Elapsed, AllocCPUs, AllocNodes, NodeList, Submit, Start, End
                f_raw_id, f_state_str, f_exit_str = f_parts[0], f_parts[1], f_parts[2]
            else:
                raise SchedulerError(
                    f"Malformed sacct row at line {f_idx + 1}: expected pipe-delimited fields, got: {f_line!r}"
                )

            # Check step row
            if "." in f_raw_id:
                f_prefix, f_step = f_raw_id.split(".", 1)
                if not re.fullmatch(r"[0-9]+", f_prefix) or not f_step:
                    raise SchedulerError(f"Malformed step row ID in sacct output: {f_raw_id!r}")
                if ":" in f_exit_str:
                    f_ret_s, f_sig_s = f_exit_str.split(":", 1)
                    if not (f_ret_s.strip().lstrip("-").isdigit() and f_sig_s.strip().lstrip("-").isdigit()):
                        raise SchedulerError(f"Malformed exit code in sacct output: {f_exit_str!r}")
                elif not f_exit_str.strip().lstrip("-").isdigit():
                    raise SchedulerError(f"Malformed exit code in sacct output: {f_exit_str!r}")
                if f_expected_id is not None and f_prefix != f_expected_id:
                    continue
                continue

            if not re.fullmatch(r"[0-9]+", f_raw_id):
                raise SchedulerError(f"Malformed root JobIDRaw in sacct output: {f_raw_id!r}")

            if f_expected_id is not None and f_raw_id != f_expected_id:
                continue

            f_exit_code = 0
            if ":" in f_exit_str:
                f_ret_s, f_sig_s = f_exit_str.split(":", 1)
                try:
                    f_ret = int(f_ret_s.strip())
                    f_sig = int(f_sig_s.strip())
                    f_exit_code = f_ret if f_ret != 0 else (128 + f_sig if f_sig != 0 else 0)
                except ValueError:
                    raise SchedulerError(f"Malformed exit code in sacct output: {f_exit_str!r}")
            else:
                try:
                    f_exit_code = int(f_exit_str.strip())
                except ValueError:
                    raise SchedulerError(f"Malformed exit code in sacct output: {f_exit_str!r}")

            f_norm_state = cls.mapSlurmState(f_state_str, f_exit_code_str=f_exit_str)
            f_root_candidates.append((f_norm_state, f_exit_code))

        if not f_root_candidates:
            return (SchedulerJobState.UNKNOWN, None)

        f_unique = list(set(f_root_candidates))
        if len(f_unique) == 1:
            return f_unique[0]
        else:
            raise SchedulerError(
                f"Conflicting root records found in sacct output: {f_root_candidates}"
            )

    parse_accounting_query = parseAccountingQuery
    parseAccountingOutput = parseAccountingQuery
    parse_accounting_output = parseAccountingQuery

    def queryJobState(
        self,
        f_job_id: str,
        f_timeout: Optional[float] = None,
    ) -> Tuple[SchedulerJobState, Optional[int]]:
        """Query Slurm job state: check squeue first; if missing/terminal or error, query sacct.

        Non-zero exit on query is non-fatal if other query succeeds, else returns (UNKNOWN, None).
        """
        f_norm_id = self.validateJobId(f_job_id)
        f_effective_timeout = (
            self.validateTimeout(f_timeout, "timeout")
            if f_timeout is not None
            else self.m_command_timeout
        )

        f_act_state: Optional[SchedulerJobState] = None

        # 1. Check squeue first
        f_act_argv = self.activeQueryCommand(f_norm_id)
        try:
            f_act_res = self._runCommand(f_act_argv, f_timeout=f_effective_timeout)
            if f_act_res.is_success and f_act_res.stdout.strip():
                f_act_state = self.parseActiveQuery(f_act_res.stdout, f_job_id=f_norm_id)
                if f_act_state in (SchedulerJobState.QUEUED, SchedulerJobState.ACTIVE):
                    return (f_act_state, None)
        except Exception:
            f_act_state = None

        # 2. Check sacct (if missing from squeue, or squeue reported terminal, or squeue failed)
        f_acct_argv = self.accountingQueryCommand(f_norm_id)
        try:
            f_acct_res = self._runCommand(f_acct_argv, f_timeout=f_effective_timeout)
            if f_acct_res.is_success and f_acct_res.stdout.strip():
                f_acct_state, f_exit_code = self.parseAccountingQuery(
                    f_acct_res.stdout, f_job_id=f_norm_id
                )
                if f_acct_state != SchedulerJobState.UNKNOWN:
                    return (f_acct_state, f_exit_code)
        except Exception:
            pass

        # 3. Fallback: if squeue had parsed a valid terminal state earlier
        if f_act_state is not None and f_act_state.is_terminal:
            return (f_act_state, None)

        return (SchedulerJobState.UNKNOWN, None)

    query_job_state = queryJobState

    def recoverCandidateJobIds(
        self,
        f_job_name: str,
        f_user: Optional[str] = None,
        f_start_time: Optional[str] = None,
    ) -> List[str]:
        """Query Slurm via squeue and sacct by exact correlation token / job name to discover candidate job IDs."""
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        f_found_ids: Set[str] = set()

        # 1. squeue by job name
        f_sq_argv = self.recoveryActiveCommand(f_valid_name)
        try:
            f_sq_res = self._runCommand(f_sq_argv, f_timeout=self.m_command_timeout)
            if f_sq_res.is_success and f_sq_res.stdout.strip():
                for f_line in f_sq_res.stdout.splitlines():
                    f_clean_l = f_line.strip()
                    if not f_clean_l:
                        continue
                    f_parts = [f_p.strip() for f_p in f_clean_l.split("|")]
                    if len(f_parts) >= 2:
                        f_cand_id, f_cand_name = f_parts[0], f_parts[1]
                        if f_cand_name == f_valid_name and re.fullmatch(r"[0-9]+", f_cand_id):
                            f_found_ids.add(f_cand_id)
        except Exception:
            pass

        # 2. sacct by job name
        f_sa_argv = self.recoveryTerminalCommand(f_valid_name, f_start_time=f_start_time)
        try:
            f_sa_res = self._runCommand(f_sa_argv, f_timeout=self.m_command_timeout)
            if f_sa_res.is_success and f_sa_res.stdout.strip():
                for f_line in f_sa_res.stdout.splitlines():
                    f_clean_l = f_line.strip()
                    if not f_clean_l or f_clean_l.startswith("JobIDRaw|") or f_clean_l.startswith("JobID|"):
                        continue
                    f_parts = [f_p.strip() for f_p in f_clean_l.split("|")]
                    if len(f_parts) >= 2:
                        f_cand_id, f_cand_name = f_parts[0], f_parts[1]
                        if "." not in f_cand_id and f_cand_name == f_valid_name and re.fullmatch(r"[0-9]+", f_cand_id):
                            f_found_ids.add(f_cand_id)
        except Exception:
            pass

        return sorted(list(f_found_ids))

    recover_candidate_job_ids = recoverCandidateJobIds

    def recoverDispatchedSubmission(
        self,
        f_job_name: str,
        f_runner: Optional[SchedulerCommandRunner] = None,
        f_start_time: Optional[str] = None,
    ) -> Optional[JobHandle]:
        """Recover JobHandle by exact correlation token / job name.

        Returns:
            JobHandle if exactly 1 candidate job found.
            None if 0 candidate jobs found.

        Raises:
            SubmissionDispatchError: if >1 distinct candidate jobs found (indeterminate).
        """
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        f_active_runner = f_runner or self.m_command_runner
        f_old_runner = self.m_command_runner
        try:
            self.m_command_runner = f_active_runner
            f_candidate_ids = self.recoverCandidateJobIds(f_valid_name, f_start_time=f_start_time)
        finally:
            self.m_command_runner = f_old_runner

        f_unique = sorted(list(set(f_candidate_ids)))

        if len(f_unique) == 0:
            return None
        elif len(f_unique) == 1:
            return JobHandle(SchedulerKind.SLURM.value, f_unique[0])
        else:
            raise SubmissionDispatchError(
                f"Indeterminate recovery: found multiple distinct candidate jobs for token '{f_job_name}': {f_unique}"
            )

    recover_dispatched_submission = recoverDispatchedSubmission

    def cancelAndConfirm(
        self,
        f_job_id: str,
        f_poll_interval: float = 1.0,
        f_grace_seconds: Optional[float] = None,
        f_clock: Optional[Callable[[], float]] = None,
        f_sleep: Optional[Callable[[float], None]] = None,
        f_timeout: Optional[float] = None,
        f_command_timeout: Optional[float] = None,
    ) -> SchedulerJobState:
        """Cancel exact Slurm job and poll with bounded confirmation until terminal state or grace period expires.

        Invariants:
        - Starts one monotonic deadline before cancel command.
        - Each command receives min(command_timeout, remaining_grace).
        - Sleep duration is truncated to at most remaining grace.
        - The deadline is never reset per loop.
        - Returns UNKNOWN immediately on timeout or when deadline expires.
        """
        f_norm_id = self.validateJobId(f_job_id)
        f_valid_poll = self.validateTimeout(f_poll_interval, "poll_interval")
        f_grace = (
            self.validateTimeout(f_grace_seconds, "grace_seconds")
            if f_grace_seconds is not None
            else self.m_command_timeout
        )
        if f_command_timeout is not None:
            f_cmd_timeout = self.validateTimeout(f_command_timeout, "command_timeout")
        elif f_timeout is not None:
            f_cmd_timeout = self.validateTimeout(f_timeout, "timeout")
        else:
            f_cmd_timeout = self.m_command_timeout

        f_now_fn = f_clock or time.monotonic
        f_sleep_fn = f_sleep or time.sleep

        # Start one monotonic deadline BEFORE executing cancel
        f_start_time = f_now_fn()
        f_deadline = f_start_time + f_grace

        def _run_with_remaining(f_argv: Sequence[str]) -> Optional[ProcessResult]:
            f_now = f_now_fn()
            f_rem = f_deadline - f_now
            if f_rem <= 0.0:
                return None
            f_effective_timeout = min(f_cmd_timeout, f_rem)
            if f_effective_timeout <= 0.0:
                return None
            try:
                return self._runCommand(f_argv, f_timeout=f_effective_timeout)
            except Exception:
                return None

        # 1. Execute cancel command
        f_cancel_argv = self.cancelCommand(f_norm_id)
        f_cancel_res = _run_with_remaining(f_cancel_argv)
        if f_cancel_res is None or (f_deadline - f_now_fn() <= 0.0):
            return SchedulerJobState.UNKNOWN

        # 2. Bounded confirmation polling loop
        while True:
            f_now = f_now_fn()
            f_rem = f_deadline - f_now
            if f_rem <= 0.0:
                return SchedulerJobState.UNKNOWN

            # Active query
            f_act_argv = self.activeQueryCommand(f_norm_id)
            f_act_res = _run_with_remaining(f_act_argv)
            if f_act_res is not None and f_act_res.is_success and f_act_res.stdout.strip():
                try:
                    f_act_state = self.parseActiveQuery(f_act_res.stdout, f_job_id=f_norm_id)
                except Exception:
                    f_act_state = None

                if f_act_state in (
                    SchedulerJobState.CANCELLED,
                    SchedulerJobState.FAILED,
                    SchedulerJobState.SUCCEEDED,
                    SchedulerJobState.TIMEOUT,
                ):
                    return f_act_state

                # If still QUEUED or ACTIVE in squeue, sleep and retry
                f_now_after = f_now_fn()
                f_rem_after = f_deadline - f_now_after
                if f_rem_after <= 0.0:
                    return SchedulerJobState.UNKNOWN
                f_sleep_dur = min(f_valid_poll, f_rem_after)
                if f_sleep_dur > 0.0:
                    f_sleep_fn(f_sleep_dur)
                if f_deadline - f_now_fn() <= 0.0:
                    return SchedulerJobState.UNKNOWN
                continue

            # Accounting query (when job has completed or left active queue)
            f_acct_argv = self.accountingQueryCommand(f_norm_id)
            f_acct_res = _run_with_remaining(f_acct_argv)
            if f_acct_res is not None and f_acct_res.is_success and f_acct_res.stdout.strip():
                try:
                    f_acct_state, _ = self.parseAccountingQuery(f_acct_res.stdout, f_job_id=f_norm_id)
                except Exception:
                    f_acct_state = None

                if f_acct_state in (
                    SchedulerJobState.CANCELLED,
                    SchedulerJobState.FAILED,
                    SchedulerJobState.SUCCEEDED,
                    SchedulerJobState.TIMEOUT,
                ):
                    return f_acct_state

            f_now_after_acct = f_now_fn()
            f_rem_after_acct = f_deadline - f_now_after_acct
            if f_rem_after_acct <= 0.0:
                return SchedulerJobState.UNKNOWN

            f_sleep_dur = min(f_valid_poll, f_rem_after_acct)
            if f_sleep_dur > 0.0:
                f_sleep_fn(f_sleep_dur)

            if f_deadline - f_now_fn() <= 0.0:
                return SchedulerJobState.UNKNOWN

    cancel_and_confirm = cancelAndConfirm


# -------------------------------------------------------------------------
# PBS Scheduler Adapter
# -------------------------------------------------------------------------

class PbsSchedulerAdapter(SchedulerAdapter):
    """Concrete PBS scheduler adapter implementing exact commands, JSON parsing, and recovery.

    Command Specifications:
    - submit: ['qsub', <script_path>]
    - active query: ['qstat', '-f', '-F', 'json', <job_id>]
    - accounting query: ['qstat', '-x', '-f', '-F', 'json', <job_id>]
    - cancel: ['qdel', <job_id>]
    - recovery: ['qstat', '-x', '-f', '-F', 'json', '-u', <user>]

    Invariants:
    - Stores exact qualified or unqualified PBS job ID in JobHandle('pbs', job_id) verbatim without stripping server suffix (e.g. '123456.isambard-pbs').
    - Status polling and cancellation query ONLY exact job ID, never whole-user qstat.
    - Whole-user query is permitted strictly during dispatch-crash correlation token recovery.
    - Missing/corrupted Exit_status on finished jobs fails closed to SchedulerJobState.UNKNOWN.
    - Negative signal exit statuses map to standard POSIX 128 + abs(sig).
    - Zero or multiple recovery matches fail closed without re-submitting.
    """

    __slots__ = ()

    def __init__(
        self,
        f_command_runner: Optional[SchedulerCommandRunner] = None,
        f_evidence_store: Optional[EvidenceStore] = None,
        f_worker_validator: Optional[Union[WorkerExecutableValidator, Callable[[str], str]]] = None,
        f_timeout: Optional[float] = None,
        f_command_timeout: Optional[float] = None,
        f_profile: Optional[SiteProfile] = None,
    ) -> None:
        super().__init__(
            f_backend=SchedulerKind.PBS,
            f_command_runner=f_command_runner,
            f_evidence_store=f_evidence_store,
            f_worker_validator=f_worker_validator,
            f_timeout=f_timeout,
            f_command_timeout=f_command_timeout,
            f_profile=f_profile,
        )

    @classmethod
    def validateJobId(cls, f_job_id: Any) -> str:
        """Validate that Job ID is a non-empty string matching '^[0-9]+(?:\\.[A-Za-z0-9._-]+)?$'."""
        if not isinstance(f_job_id, str):
            raise SchedulerError(f"Job ID must be a string, got: {type(f_job_id).__name__}")
        if not f_job_id:
            raise SchedulerError("Job ID cannot be empty")
        _checkNoControlChars(f_job_id, "job_id")
        if not re.fullmatch(r"^[0-9]+(?:\.[A-Za-z0-9._-]+)?$", f_job_id):
            raise SchedulerError(
                f"PBS Job ID must match format '^[0-9]+(?:\\.[A-Za-z0-9._-]+)?$', got: {f_job_id!r}"
            )
        return f_job_id

    validate_job_id = validateJobId

    @classmethod
    def submitCommand(cls, f_script_path: str) -> List[str]:
        """Build exact qsub submission argv: ['qsub', <script_path>]."""
        if not isinstance(f_script_path, str) or not f_script_path.strip():
            raise SchedulerError(f"Script path must be a non-empty string, got: {f_script_path!r}")
        _checkNoControlChars(f_script_path, "script_path")
        return ["qsub", f_script_path.strip()]

    submit_command = submitCommand

    def buildSubmitArgv(self, f_spec: JobSpec) -> List[str]:
        return self.submitCommand(f_spec.script_path)

    build_submit_argv = buildSubmitArgv

    def parseSubmitOutput(self, f_stdout: str) -> str:
        """Extract exact qualified or unqualified PBS job ID string from PBS submission output.

        Accepts <job_id>[.<server_suffix>] (e.g. '123456.isambard-pbs' or '123456'),
        extracts and returns the exact full job ID verbatim without stripping server suffix.
        Rejects invalid formats, whitespace, or multiline outputs.
        """
        if not isinstance(f_stdout, str) or not f_stdout:
            raise SubmissionDispatchError(f"PBS submission output is empty or invalid: {f_stdout!r}")

        f_clean = f_stdout
        if f_clean.endswith("\r\n"):
            f_clean = f_clean[:-2]
        elif f_clean.endswith("\n") or f_clean.endswith("\r"):
            f_clean = f_clean[:-1]

        if not f_clean:
            raise SubmissionDispatchError(f"PBS submission output is empty: {f_stdout!r}")

        m = re.fullmatch(r"^[0-9]+(?:\.[A-Za-z0-9._-]+)?$", f_clean)
        if not m:
            raise SubmissionDispatchError(
                f"PBS submission output does not match valid PBS ID pattern: {f_stdout!r}"
            )
        return f_clean

    parse_submit_output = parseSubmitOutput

    @classmethod
    def activeQueryCommand(cls, f_job_id: str) -> List[str]:
        """Build exact qstat active query argv: ['qstat', '-f', '-F', 'json', <job_id>]."""
        f_norm_id = cls.validateJobId(f_job_id)
        return ["qstat", "-f", "-F", "json", f_norm_id]

    active_query_command = activeQueryCommand
    buildActiveQueryArgv = activeQueryCommand
    build_active_query_argv = activeQueryCommand

    @classmethod
    def accountingQueryCommand(cls, f_job_id: str) -> List[str]:
        """Build exact qstat accounting query argv: ['qstat', '-x', '-f', '-F', 'json', <job_id>]."""
        f_norm_id = cls.validateJobId(f_job_id)
        return ["qstat", "-x", "-f", "-F", "json", f_norm_id]

    accounting_query_command = accountingQueryCommand
    buildAccountingQueryArgv = accountingQueryCommand
    build_accounting_query_argv = accountingQueryCommand

    @classmethod
    def recoveryCommand(cls, f_user: Optional[str] = None) -> List[str]:
        """Build exact qstat user recovery argv: ['qstat', '-x', '-f', '-F', 'json', '-u', <user>]."""
        if f_user is not None and f_user.strip():
            _checkNoControlChars(f_user, "user")
            return ["qstat", "-x", "-f", "-F", "json", "-u", f_user.strip()]
        return ["qstat", "-x", "-f", "-F", "json"]

    recovery_command = recoveryCommand
    buildRecoveryArgv = recoveryCommand
    build_recovery_argv = recoveryCommand

    @classmethod
    def cancelCommand(cls, f_job_id: str) -> List[str]:
        """Build exact qdel cancel argv: ['qdel', <job_id>]."""
        f_norm_id = cls.validateJobId(f_job_id)
        return ["qdel", f_norm_id]

    cancel_command = cancelCommand
    buildCancelArgv = cancelCommand
    build_cancel_argv = cancelCommand

    @classmethod
    def mapPbsState(
        cls,
        f_state_str: str,
        f_exit_status: Optional[Union[int, str]] = None,
    ) -> SchedulerJobState:
        """Map raw PBS state string and optional Exit_status to normalized SchedulerJobState."""
        if not isinstance(f_state_str, str) or not f_state_str.strip():
            return SchedulerJobState.UNKNOWN

        f_token = f_state_str.strip().split()[0].upper()

        if f_token in ("Q", "QUEUED", "W", "WAITING", "H", "HELD", "T", "TRANSIT", "TRANSITING"):
            return SchedulerJobState.QUEUED
        elif f_token in ("R", "RUNNING", "E", "EXITING", "B", "BEGUN", "S", "SUSPENDED"):
            return SchedulerJobState.ACTIVE
        elif f_token in ("F", "FINISHED", "C", "COMPLETED"):
            if f_exit_status is None:
                return SchedulerJobState.UNKNOWN
            try:
                f_exit_int = int(str(f_exit_status).strip())
            except (ValueError, TypeError):
                return SchedulerJobState.UNKNOWN
            if f_exit_int == 0:
                return SchedulerJobState.SUCCEEDED
            else:
                return SchedulerJobState.FAILED
        elif f_token.startswith("CANCELLED") or f_token in ("CA", "CANCEL", "CANCELLED"):
            return SchedulerJobState.CANCELLED
        elif f_token in ("TIMEOUT", "TO"):
            return SchedulerJobState.TIMEOUT
        else:
            return SchedulerJobState.UNKNOWN

    map_pbs_state = mapPbsState

    @classmethod
    def parseActiveQuery(
        cls,
        f_output: str,
        f_job_id: Optional[str] = None,
    ) -> Optional[SchedulerJobState]:
        """Parse qstat active JSON output into normalized SchedulerJobState.

        Returns:
            SchedulerJobState if a matching job record is found.
            None if output is empty/blank or contains no matching job in active queue.
        """
        if not isinstance(f_output, str):
            raise SchedulerError(f"qstat output must be a string, got: {type(f_output).__name__}")

        f_trimmed = f_output.strip()
        if not f_trimmed:
            return None

        try:
            f_data = json.loads(f_trimmed)
        except Exception as f_err:
            raise SchedulerError(f"Malformed PBS JSON output: {f_err}") from f_err

        if not isinstance(f_data, dict):
            raise SchedulerError(f"Expected PBS JSON root to be an object, got: {type(f_data).__name__}")

        f_jobs = f_data.get("Jobs")
        if f_jobs is None or (isinstance(f_jobs, dict) and len(f_jobs) == 0):
            return None

        if not isinstance(f_jobs, dict):
            raise SchedulerError(f"Expected 'Jobs' field in PBS JSON to be an object, got: {type(f_jobs).__name__}")

        f_expected_id = str(f_job_id).strip() if f_job_id is not None else None
        f_matched_entries: List[Tuple[str, Dict[str, Any]]] = []

        for f_key, f_val in f_jobs.items():
            if not isinstance(f_key, str):
                continue
            f_key_clean = f_key.strip()
            if f_expected_id is not None:
                if f_key_clean == f_expected_id:
                    if not isinstance(f_val, dict):
                        raise SchedulerError(f"Job entry '{f_key}' in PBS JSON is not an object")
                    f_matched_entries.append((f_key_clean, f_val))
            else:
                if not isinstance(f_val, dict):
                    raise SchedulerError(f"Job entry '{f_key}' in PBS JSON is not an object")
                f_matched_entries.append((f_key_clean, f_val))

        if not f_matched_entries:
            return None

        if len(f_matched_entries) > 1:
            raise SchedulerError(
                f"Expected exact single job entry matching '{f_expected_id}', found {len(f_matched_entries)}"
            )

        _, f_job_dict = f_matched_entries[0]
        f_state_raw = f_job_dict.get("job_state")
        if not isinstance(f_state_raw, str) or not f_state_raw.strip():
            return SchedulerJobState.UNKNOWN

        f_exit_raw = f_job_dict.get("Exit_status")
        return cls.mapPbsState(f_state_raw, f_exit_raw)

    parse_active_query = parseActiveQuery
    parseActiveOutput = parseActiveQuery
    parse_active_output = parseActiveQuery

    @classmethod
    def parseAccountingQuery(
        cls,
        f_output: str,
        f_job_id: Optional[str] = None,
    ) -> Tuple[SchedulerJobState, Optional[int]]:
        """Parse qstat -x historical JSON output, extracting terminal state and return code.

        Returns:
            Tuple[SchedulerJobState, Optional[int]]: (normalized_state, exit_status)
        """
        if not isinstance(f_output, str):
            raise SchedulerError(f"qstat output must be a string, got: {type(f_output).__name__}")

        f_trimmed = f_output.strip()
        if not f_trimmed:
            return (SchedulerJobState.UNKNOWN, None)

        try:
            f_data = json.loads(f_trimmed)
        except Exception as f_err:
            raise SchedulerError(f"Malformed PBS JSON output: {f_err}") from f_err

        if not isinstance(f_data, dict):
            raise SchedulerError(f"Expected PBS JSON root to be an object, got: {type(f_data).__name__}")

        f_jobs = f_data.get("Jobs")
        if f_jobs is None or (isinstance(f_jobs, dict) and len(f_jobs) == 0):
            return (SchedulerJobState.UNKNOWN, None)

        if not isinstance(f_jobs, dict):
            raise SchedulerError(f"Expected 'Jobs' field in PBS JSON to be an object, got: {type(f_jobs).__name__}")

        f_expected_id = str(f_job_id).strip() if f_job_id is not None else None
        f_matched_entries: List[Tuple[str, Dict[str, Any]]] = []

        for f_key, f_val in f_jobs.items():
            if not isinstance(f_key, str):
                continue
            f_key_clean = f_key.strip()
            if f_expected_id is not None:
                if f_key_clean == f_expected_id:
                    if not isinstance(f_val, dict):
                        raise SchedulerError(f"Job entry '{f_key}' in PBS JSON is not an object")
                    f_matched_entries.append((f_key_clean, f_val))
            else:
                if not isinstance(f_val, dict):
                    raise SchedulerError(f"Job entry '{f_key}' in PBS JSON is not an object")
                f_matched_entries.append((f_key_clean, f_val))

        if not f_matched_entries:
            return (SchedulerJobState.UNKNOWN, None)

        if len(f_matched_entries) > 1:
            raise SchedulerError(
                f"Expected exact single job entry matching '{f_expected_id}', found {len(f_matched_entries)}"
            )

        _, f_job_dict = f_matched_entries[0]
        f_state_raw = f_job_dict.get("job_state")
        if not isinstance(f_state_raw, str) or not f_state_raw.strip():
            return (SchedulerJobState.UNKNOWN, None)

        f_exit_raw = f_job_dict.get("Exit_status")
        f_exit_int: Optional[int] = None
        if f_exit_raw is not None:
            try:
                f_raw_int = int(str(f_exit_raw).strip())
                if f_raw_int < 0:
                    f_exit_int = 128 + abs(f_raw_int)
                else:
                    f_exit_int = f_raw_int
            except (ValueError, TypeError):
                f_exit_int = None

        f_state = cls.mapPbsState(f_state_raw, f_exit_raw)
        return (f_state, f_exit_int)

    parse_accounting_query = parseAccountingQuery
    parseAccountingOutput = parseAccountingQuery
    parse_accounting_output = parseAccountingQuery

    def queryJobState(
        self,
        f_job_id: str,
        f_timeout: Optional[float] = None,
    ) -> Tuple[SchedulerJobState, Optional[int]]:
        """Query PBS job state: check active qstat first; if missing/terminal or error, query historical qstat -x.

        Non-zero exit on query is non-fatal if other query succeeds, else returns (UNKNOWN, None).
        """
        f_norm_id = self.validateJobId(f_job_id)
        f_effective_timeout = (
            self.validateTimeout(f_timeout, "timeout")
            if f_timeout is not None
            else self.m_command_timeout
        )

        f_act_state: Optional[SchedulerJobState] = None

        # 1. Check active queue first (qstat -f -F json <job_id>)
        f_act_argv = self.activeQueryCommand(f_norm_id)
        try:
            f_act_res = self._runCommand(f_act_argv, f_timeout=f_effective_timeout)
            if f_act_res.is_success and f_act_res.stdout.strip():
                f_act_state = self.parseActiveQuery(f_act_res.stdout, f_job_id=f_norm_id)
                if f_act_state in (SchedulerJobState.QUEUED, SchedulerJobState.ACTIVE):
                    return (f_act_state, None)
        except Exception:
            f_act_state = None

        # 2. Check accounting / historical query (qstat -x -f -F json <job_id>)
        f_acct_argv = self.accountingQueryCommand(f_norm_id)
        try:
            f_acct_res = self._runCommand(f_acct_argv, f_timeout=f_effective_timeout)
            if f_acct_res.is_success and f_acct_res.stdout.strip():
                f_acct_state, f_exit_code = self.parseAccountingQuery(
                    f_acct_res.stdout, f_job_id=f_norm_id
                )
                if f_acct_state != SchedulerJobState.UNKNOWN:
                    return (f_acct_state, f_exit_code)
        except Exception:
            pass

        # 3. Fallback: if active query parsed a terminal state earlier
        if f_act_state is not None and f_act_state.is_terminal:
            return (f_act_state, None)

        return (SchedulerJobState.UNKNOWN, None)

    query_job_state = queryJobState

    def recoverCandidateJobIds(
        self,
        f_job_name: str,
        f_user: Optional[str] = None,
    ) -> List[str]:
        """Query PBS via qstat -x -f -F json -u <user> and filter Jobs by exact Job_Name."""
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        f_resolved_user = f_user or getpass.getuser()
        if not isinstance(f_resolved_user, str) or not f_resolved_user.strip():
            raise SchedulerError("Cannot recover PBS jobs without a valid username")
        f_clean_user = f_resolved_user.strip()
        _checkNoControlChars(f_clean_user, "user")

        f_qstat_argv = self.recoveryCommand(f_clean_user)
        f_res = self._runCommand(f_qstat_argv, f_timeout=self.m_command_timeout)

        if not f_res.is_success or not f_res.stdout.strip():
            return []

        try:
            f_data = json.loads(f_res.stdout)
        except Exception as f_err:
            raise SchedulerError(f"Malformed PBS JSON output during recovery: {f_err}") from f_err

        if not isinstance(f_data, dict):
            raise SchedulerError(f"Expected PBS JSON root to be an object, got: {type(f_data).__name__}")

        f_jobs = f_data.get("Jobs")
        if not f_jobs or not isinstance(f_jobs, dict):
            return []

        f_found_ids: Set[str] = set()
        for f_key, f_job_dict in f_jobs.items():
            if not isinstance(f_key, str) or not isinstance(f_job_dict, dict):
                continue
            f_cand_name = f_job_dict.get("Job_Name")
            if f_cand_name == f_valid_name:
                f_key_clean = f_key.strip()
                if re.fullmatch(r"^[0-9]+(?:\.[A-Za-z0-9._-]+)?$", f_key_clean):
                    f_found_ids.add(f_key_clean)

        return sorted(list(f_found_ids))

    recover_candidate_job_ids = recoverCandidateJobIds

    def recoverDispatchedSubmission(
        self,
        f_job_name: str,
        f_runner: Optional[SchedulerCommandRunner] = None,
        f_user: Optional[str] = None,
    ) -> Optional[JobHandle]:
        """Recover JobHandle by exact correlation token / job name during crash recovery.

        Returns:
            JobHandle if exactly 1 candidate job found.
            None if 0 candidate jobs found.

        Raises:
            SubmissionDispatchError: if >1 distinct candidate jobs found (indeterminate).
        """
        f_valid_name = SchedulerScriptRenderer.validateJobName(f_job_name)
        f_active_runner = f_runner or self.m_command_runner
        f_old_runner = self.m_command_runner
        try:
            self.m_command_runner = f_active_runner
            f_candidate_ids = self.recoverCandidateJobIds(f_valid_name, f_user=f_user)
        finally:
            self.m_command_runner = f_old_runner

        f_unique = sorted(list(set(f_candidate_ids)))

        if len(f_unique) == 0:
            return None
        elif len(f_unique) == 1:
            return JobHandle(SchedulerKind.PBS.value, f_unique[0])
        else:
            raise SubmissionDispatchError(
                f"Indeterminate recovery: found multiple distinct candidate jobs for token '{f_job_name}': {f_unique}"
            )

    recover_dispatched_submission = recoverDispatchedSubmission

    def cancelAndConfirm(
        self,
        f_job_id: str,
        f_poll_interval: float = 1.0,
        f_grace_seconds: Optional[float] = None,
        f_clock: Optional[Callable[[], float]] = None,
        f_sleep: Optional[Callable[[float], None]] = None,
        f_timeout: Optional[float] = None,
        f_command_timeout: Optional[float] = None,
    ) -> SchedulerJobState:
        """Cancel exact PBS job and poll with bounded confirmation until terminal state or grace period expires.

        Invariants:
        - Starts one monotonic deadline before cancel command.
        - Each command receives min(command_timeout, remaining_grace).
        - Sleep duration is truncated to at most remaining grace.
        - The deadline is never reset per loop.
        - Returns UNKNOWN immediately on timeout or when deadline expires.
        - Queries ONLY exact job ID using qstat -f -F json <job_id> (or qstat -x -f -F json <job_id>).
        - NEVER invokes whole-user qstat during cancellation polling.
        """
        f_norm_id = self.validateJobId(f_job_id)
        f_valid_poll = self.validateTimeout(f_poll_interval, "poll_interval")
        f_grace = (
            self.validateTimeout(f_grace_seconds, "grace_seconds")
            if f_grace_seconds is not None
            else self.m_command_timeout
        )
        if f_command_timeout is not None:
            f_cmd_timeout = self.validateTimeout(f_command_timeout, "command_timeout")
        elif f_timeout is not None:
            f_cmd_timeout = self.validateTimeout(f_timeout, "timeout")
        else:
            f_cmd_timeout = self.m_command_timeout

        f_now_fn = f_clock or time.monotonic
        f_sleep_fn = f_sleep or time.sleep

        # Start one monotonic deadline BEFORE executing cancel
        f_start_time = f_now_fn()
        f_deadline = f_start_time + f_grace

        def _run_with_remaining(f_argv: Sequence[str]) -> Optional[ProcessResult]:
            f_now = f_now_fn()
            f_rem = f_deadline - f_now
            if f_rem <= 0.0:
                return None
            f_effective_timeout = min(f_cmd_timeout, f_rem)
            if f_effective_timeout <= 0.0:
                return None
            try:
                return self._runCommand(f_argv, f_timeout=f_effective_timeout)
            except Exception:
                return None

        # 1. Execute cancel command
        f_cancel_argv = self.cancelCommand(f_norm_id)
        f_cancel_res = _run_with_remaining(f_cancel_argv)
        if f_cancel_res is None or (f_deadline - f_now_fn() <= 0.0):
            return SchedulerJobState.UNKNOWN

        # 2. Bounded confirmation polling loop
        while True:
            f_now = f_now_fn()
            f_rem = f_deadline - f_now
            if f_rem <= 0.0:
                return SchedulerJobState.UNKNOWN

            # Active query
            f_act_argv = self.activeQueryCommand(f_norm_id)
            f_act_res = _run_with_remaining(f_act_argv)
            if f_act_res is not None and f_act_res.is_success and f_act_res.stdout.strip():
                try:
                    f_act_state = self.parseActiveQuery(f_act_res.stdout, f_job_id=f_norm_id)
                except Exception:
                    f_act_state = None

                if f_act_state in (
                    SchedulerJobState.CANCELLED,
                    SchedulerJobState.FAILED,
                    SchedulerJobState.SUCCEEDED,
                    SchedulerJobState.TIMEOUT,
                ):
                    return f_act_state

                if f_act_state in (SchedulerJobState.QUEUED, SchedulerJobState.ACTIVE):
                    # If still QUEUED or ACTIVE in qstat, check elapsed and sleep
                    f_now_after = f_now_fn()
                    f_rem_after = f_deadline - f_now_after
                    if f_rem_after <= 0.0:
                        return SchedulerJobState.UNKNOWN
                    f_sleep_dur = min(f_valid_poll, f_rem_after)
                    if f_sleep_dur > 0.0:
                        f_sleep_fn(f_sleep_dur)
                    if f_deadline - f_now_fn() <= 0.0:
                        return SchedulerJobState.UNKNOWN
                    continue

            # Historical / accounting query
            f_acct_argv = self.accountingQueryCommand(f_norm_id)
            f_acct_res = _run_with_remaining(f_acct_argv)
            if f_acct_res is not None and f_acct_res.is_success and f_acct_res.stdout.strip():
                try:
                    f_acct_state, _ = self.parseAccountingQuery(f_acct_res.stdout, f_job_id=f_norm_id)
                except Exception:
                    f_acct_state = None

                if f_acct_state in (
                    SchedulerJobState.CANCELLED,
                    SchedulerJobState.FAILED,
                    SchedulerJobState.SUCCEEDED,
                    SchedulerJobState.TIMEOUT,
                ):
                    return f_acct_state

            f_now_after_acct = f_now_fn()
            f_rem_after_acct = f_deadline - f_now_after_acct
            if f_rem_after_acct <= 0.0:
                return SchedulerJobState.UNKNOWN

            f_sleep_dur = min(f_valid_poll, f_rem_after_acct)
            if f_sleep_dur > 0.0:
                f_sleep_fn(f_sleep_dur)

            if f_deadline - f_now_fn() <= 0.0:
                return SchedulerJobState.UNKNOWN

    cancel_and_confirm = cancelAndConfirm
