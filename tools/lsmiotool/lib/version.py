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

import os
import re
import stat
from pathlib import Path
from typing import Optional, Union


class VersionError(Exception):
    """Exception raised when version file is missing, invalid, or cannot be read."""
    pass


_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def getVersion(f_version_file_path: Optional[Union[str, Path]] = None) -> str:
    """Retrieve and validate the package version from the authoritative VERSION file.

    Parameters:
        f_version_file_path: Optional explicit path to the VERSION file.
            If None, uses the package-relative path Path(__file__).parent.parent / "VERSION".

    Returns:
        The validated semantic version string.

    Raises:
        VersionError: If the version file is missing, a symlink, not a regular file,
            unreadable, empty, multiline, or does not match semver format.
    """
    if f_version_file_path is None:
        f_path = Path(__file__).parent.parent / "VERSION"
    elif isinstance(f_version_file_path, (str, Path)):
        f_path = Path(f_version_file_path)
    else:
        raise VersionError(
            f"Invalid version file path type: {type(f_version_file_path).__name__}"
        )

    f_path_str = str(f_path)

    try:
        f_st = os.lstat(f_path_str)
    except (FileNotFoundError, OSError) as f_e:
        raise VersionError(
            f"Version file does not exist or cannot be accessed: {f_path_str}"
        ) from f_e

    if stat.S_ISLNK(f_st.st_mode) or os.path.islink(f_path_str):
        raise VersionError(f"Version file must not be a symlink: {f_path_str}")

    if not stat.S_ISREG(f_st.st_mode):
        raise VersionError(f"Version file must be a regular file: {f_path_str}")

    if not os.access(f_path_str, os.R_OK):
        raise VersionError(f"Version file is not readable: {f_path_str}")

    try:
        with open(f_path_str, "r", encoding="utf-8") as f_file:
            f_content = f_file.read()
    except (PermissionError, OSError) as f_e:
        raise VersionError(f"Failed to read version file: {f_path_str}") from f_e

    f_lines = f_content.splitlines()
    if len(f_lines) != 1:
        raise VersionError(
            f"Version file must contain exactly one line, got {len(f_lines)} lines: {f_path_str}"
        )

    f_version = f_lines[0].strip()
    if not f_version:
        raise VersionError(
            f"Version file contains empty version string: {f_path_str}"
        )

    if not _SEMVER_PATTERN.match(f_version):
        raise VersionError(
            f"Version string {f_version!r} does not match semantic version format: {f_path_str}"
        )

    return f_version
