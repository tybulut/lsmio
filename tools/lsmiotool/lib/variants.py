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

"""Declarative variant catalogue, engine CLI flag mappings, and token resolution for LSMIO."""

import re
from typing import Any, Dict, NamedTuple, Optional, Sequence, Tuple

from lsmiotool.lib.cli import CliParseError


class UnknownSetupError(CliParseError):
    """Raised when a setup is not one of the LSMIO setups (e.g. a removed '-M' name)."""

    def __init__(self, f_setup: str, f_supported: Sequence[str]) -> None:
        super().__init__(
            f"Invalid setup: {f_setup!r}. Supported setups are: {list(f_supported)}"
        )
        self.m_setup = f_setup


class UnknownVariantError(CliParseError):
    """Raised when an unknown variant token is encountered at CLI or configuration boundaries."""

    def __init__(self, f_variant: str, f_supported: Sequence[str]) -> None:
        super().__init__(
            f"Invalid variant: {f_variant!r}. Supported variants are: {list(f_supported)}"
        )
        self.m_variant = f_variant
        self.m_supported = tuple(f_supported)

    @property
    def variant(self) -> str:
        return self.m_variant

    @property
    def supported(self) -> Tuple[str, ...]:
        return self.m_supported


class VariantRecord:
    """Immutable record specifying variant tokens and associated engine CLI flags."""

    __slots__ = ("m_key", "m_tokens", "m_flags", "_frozen")

    def __init__(
        self,
        f_key: str,
        f_tokens: str,
        f_flags: Sequence[str],
    ) -> None:
        if not isinstance(f_key, str):
            raise TypeError(f"key must be a string, got: {type(f_key).__name__}")
        if not isinstance(f_tokens, str):
            raise TypeError(f"tokens must be a string, got: {type(f_tokens).__name__}")
        if not isinstance(f_flags, (tuple, list)):
            raise TypeError(
                f"flags must be a sequence of strings, got: {type(f_flags).__name__}"
            )

        flags_tuple = tuple(f_flags)
        for flag in flags_tuple:
            if not isinstance(flag, str):
                raise TypeError(
                    f"flag item must be a string, got: {type(flag).__name__}"
                )

        super().__setattr__("m_key", f_key)
        super().__setattr__("m_tokens", f_tokens)
        super().__setattr__("m_flags", flags_tuple)
        super().__setattr__("_frozen", True)

    def __setattr__(self, f_key: str, f_value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Cannot modify immutable {self.__class__.__name__}")
        super().__setattr__(f_key, f_value)

    def __delattr__(self, f_key: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"Cannot delete attribute from immutable {self.__class__.__name__}"
            )
        super().__delattr__(f_key)

    @property
    def key(self) -> str:
        return self.m_key

    @property
    def tokens(self) -> str:
        return self.m_tokens

    @property
    def flags(self) -> Tuple[str, ...]:
        return self.m_flags

    @property
    def flagsString(self) -> str:
        """Space-separated flags suitable for shell rendering."""
        return " ".join(self.m_flags)

    def __repr__(self) -> str:
        return (
            f"VariantRecord(key={self.m_key!r}, tokens={self.m_tokens!r}, "
            f"flags={self.m_flags!r})"
        )

    def __eq__(self, f_other: Any) -> bool:
        if not isinstance(f_other, VariantRecord):
            return False
        return (
            self.m_key == f_other.m_key
            and self.m_tokens == f_other.m_tokens
            and self.m_flags == f_other.m_flags
        )

    def __hash__(self) -> int:
        return hash((self.m_key, self.m_tokens, self.m_flags))


class VariantCatalogue:
    """Pure declarative catalogue mapping variant keys to tokens and engine CLI flags."""

    # Flags of the default (baseline) variant; every other variant except 'autotune'
    # starts with the same flag, as bmtool's resolve_variant does
    _DEFAULT_FLAGS: Tuple[str, ...] = ("--lsmio-no-autotune",)

    _ONE_SEGMENT_PREFIXES: Tuple[str, ...] = (
        "native-",
        "rocksdb-",
        "leveldb-",
        "adios-",
        "plugin-",
        "manager-",
    )

    # Every non-empty variant key mapped to (tokens, engine_flags), in canonical order.
    # Each one changes the engine from its defaults in a different way.
    _VARIANT_SPECS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
        "vsort": ("vsort", ("--lsmio-no-autotune", "--lsmio-memtable", "vector-sort")),
        "btree": ("btree", ("--lsmio-no-autotune", "--lsmio-memtable", "btree")),
        "vnosort": (
            "vnosort",
            ("--lsmio-no-autotune", "--lsmio-memtable", "vector-no-sort"),
        ),
        "mmap": ("mmap", ("--lsmio-no-autotune", "--lsmio-mmap", "--lsmio-no-pread")),
        "no-pread": (
            "no-pread",
            ("--lsmio-no-autotune", "--lsmio-no-pread"),
        ),
        "no-footer": (
            "no-footer",
            ("--lsmio-no-autotune", "--lsmio-no-footer-index"),
        ),
        "no-manoff": (
            "no-manoff",
            ("--lsmio-no-autotune", "--lsmio-no-manual-offset"),
        ),
        "legacy": (
            "legacy",
            (
                "--lsmio-no-autotune",
                "--lsmio-no-footer-index",
                "--lsmio-no-manual-offset",
                "--lsmio-no-pread",
                "--lsmio-memtable",
                "vector-no-sort",
            ),
        ),
        "prealloc": ("prealloc", ("--lsmio-no-autotune", "--lsmio-prealloc")),
        "wbuf-512m": (
            "wbuf-512m",
            ("--lsmio-no-autotune", "--lsmio-wbuffer", "536870912"),
        ),
        "wbuf-32m": (
            "wbuf-32m",
            ("--lsmio-no-autotune", "--lsmio-wbuffer", "33554432"),
        ),
        "pool-8": ("pool-8", ("--lsmio-no-autotune", "--lsmio-pool", "8")),
        "prealloc-vsort": (
            "prealloc-vsort",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-prealloc",
            ),
        ),
        "prealloc-btree": (
            "prealloc-btree",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "btree",
                "--lsmio-prealloc",
            ),
        ),
        "prealloc-wbuf-512m": (
            "prealloc-wbuf-512m",
            (
                "--lsmio-no-autotune",
                "--lsmio-wbuffer",
                "536870912",
                "--lsmio-prealloc",
            ),
        ),
        "mmap-vsort": (
            "mmap-vsort",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "mmap-btree": (
            "mmap-btree",
            (
                "--lsmio-no-autotune",
                "--lsmio-memtable",
                "btree",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "pool-8-mmap": (
            "pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        # INV-ARCH-4: exact CLI11 spelling --lsmio-always-flush
        "flush": ("flush", ("--lsmio-no-autotune", "--lsmio-always-flush")),
        "batch-2048": (
            "batch-2048",
            ("--lsmio-no-autotune", "--lsmio-batch-size", "2048"),
        ),
        "bfilter": ("bfilter", ("--lsmio-no-autotune", "--lsmio-bfilter")),
        "wal": ("wal", ("--lsmio-no-autotune", "--lsmio-wal")),
        "compress": ("compress", ("--lsmio-no-autotune", "--lsmio-compress")),
        "sync": ("sync", ("--lsmio-no-autotune", "--sync")),
        "autotune": (
            "autotune",
            ("--lsmio-autotune",),
        ),
    }

    # Variant keys dropped because they re-enable engine defaults (footer index, manual
    # offset, pread, map memtable) and so duplicate another variant. They cannot be run;
    # they are kept only so that archive directories named after them still resolve.
    _RETIRED_VARIANTS: Tuple[str, ...] = (
        "footer",
        "footer-btree",
        "map",
        "footer-prealloc",
        "manoff",
        "footer-manoff",
        "footer-wbuf-512m",
        "footer-btree-prealloc",
        "pread",
        "footer-mmap",
        "footer-pread",
        "manoff-prealloc",
        "wbuf-512m-manoff-prealloc",
        "footer-wbuf-32m",
        "footer-pool-8",
        "footer-wbuf-512m-manoff-prealloc",
        "footer-vsort-manoff-prealloc",
        "footer-vsort-manoff-mmap",
        "footer-vsort-manoff",
        "footer-pool-8-mmap",
        "footer-manoff-pool-8-mmap",
        "footer-btree-manoff-mmap",
        "footer-manoff-pool-8",
        "footer-pread-pool-8",
        "footer-pread-manoff",
        "footer-pread-manoff-pool-8",
        "footer-map-pread",
        "footer-btree-pread",
        "footer-vsort-pread",
        "footer-btree-manoff-pread",
        "footer-map-manoff-pread",
        "footer-map-manoff-mmap",
        "footer-map",
        "footer-map-manoff",
        "manoff-pool-8",
    )

    _CANONICAL_VARIANTS: Tuple[str, ...] = (
        "vsort",
        "btree",
        "vnosort",
        "mmap",
        "no-pread",
        "no-footer",
        "no-manoff",
        "legacy",
        "prealloc",
        "wbuf-512m",
        "wbuf-32m",
        "pool-8",
        "prealloc-vsort",
        "prealloc-btree",
        "prealloc-wbuf-512m",
        "mmap-vsort",
        "mmap-btree",
        "pool-8-mmap",
        "flush",
        "batch-2048",
        "bfilter",
        "wal",
        "compress",
        "sync",
        "autotune",
    )

    @classmethod
    def stripBackendPrefix(cls, f_key: str) -> str:
        """Strips composite backend setup prefixes from a variant key string.

        Patterns handled: native-*, rocksdb-*, leveldb-*, adios-*, plugin-*, manager-*
        """
        if not isinstance(f_key, str):
            raise TypeError(f"f_key must be a string, got: {type(f_key).__name__}")
        k = f_key.strip().lower()
        for prefix in cls._ONE_SEGMENT_PREFIXES:
            if k.startswith(prefix):
                return k[len(prefix) :]
        return k

    @classmethod
    def supportedVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all supported non-empty variant keys in canonical order."""
        return tuple(cls._VARIANT_SPECS.keys())

    @classmethod
    def getAllVariantKeys(cls) -> Tuple[str, ...]:
        """Returns tuple of all valid non-empty variant keys in canonical order."""
        return cls.supportedVariants()

    @classmethod
    def archivedVariantNames(cls) -> Tuple[str, ...]:
        """Returns every variant key an archive directory may be named after.

        That is the supported keys plus the retired ones, which can no longer be run.
        """
        return cls.supportedVariants() + cls._RETIRED_VARIANTS

    @classmethod
    def canonicalVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all 26 streamlined matrix variant keys in canonical order ('default' followed by 25 variants)."""
        return ("default",) + cls._CANONICAL_VARIANTS

    @classmethod
    def mostVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all 26 streamlined matrix variant keys in canonical order (alias for canonicalVariants)."""
        return cls.canonicalVariants()

    @classmethod
    def allVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all variants ('default' followed by every supported variant); the same as mostVariants()."""
        return cls.canonicalVariants()

    @classmethod
    def resolve(cls, f_key: Optional[str] = None) -> VariantRecord:
        """Resolves variant key into a canonical VariantRecord.

        Handles:
        - None, "", "base", "default" -> the default variant (base run), flags
          --lsmio-no-autotune.
        - Strips backend prefix.
        - Canonical lookup against 25 discrete non-empty keys; retired keys are rejected.
        - Raises UnknownVariantError on unrecognized keys.
        """
        if f_key is None:
            return VariantRecord("", "", cls._DEFAULT_FLAGS)

        if not isinstance(f_key, str):
            raise UnknownVariantError(str(f_key), cls.supportedVariants())

        stripped_raw = f_key.strip()
        if stripped_raw == "":
            return VariantRecord("", "", cls._DEFAULT_FLAGS)

        if stripped_raw.lower() in ("base", "default"):
            return VariantRecord("", "", cls._DEFAULT_FLAGS)

        stripped = cls.stripBackendPrefix(stripped_raw)
        if stripped in ("", "base", "default"):
            return VariantRecord("", "", cls._DEFAULT_FLAGS)

        if stripped in cls._VARIANT_SPECS:
            spec_tokens, spec_flags = cls._VARIANT_SPECS[stripped]
            return VariantRecord(stripped, spec_tokens, spec_flags)

        if stripped.startswith("version-"):
            payload = stripped[len("version-") :]
            # The longest variant name the key ends with decides, as in bmtool:
            # version-<branch>-<hash>-<retired variant> is rejected like the bare key
            # (footer-btree is not read as btree), no-pread is not read as pread
            for cand_var in sorted(
                cls.archivedVariantNames(), key=len, reverse=True
            ):
                if payload.endswith(f"-{cand_var}"):
                    prefix = payload[: -len(cand_var) - 1]
                    if "-" in prefix:
                        if cand_var not in cls._VARIANT_SPECS:
                            raise UnknownVariantError(f_key, cls.supportedVariants())
                        spec = cls._VARIANT_SPECS[cand_var]
                        return VariantRecord(stripped, stripped, spec[1])
            return VariantRecord(stripped, stripped, cls._DEFAULT_FLAGS)

        raise UnknownVariantError(f_key, cls.supportedVariants())

    @classmethod
    def isValid(cls, f_key: Optional[str]) -> bool:
        """Returns True if the variant key is known and valid, False otherwise."""
        try:
            cls.resolve(f_key)
            return True
        except UnknownVariantError:
            return False

    @classmethod
    def getInfix(
        cls,
        f_setup: str = "",
        f_variant: Optional[str] = None,
        *,
        f_backend: Optional[str] = None,
        f_key: Optional[str] = None,
    ) -> str:
        """Derives mechanical backend-variant infix token for log and DB naming.

        Backend token: the setup lowercased (e.g. 'NATIVE' -> 'native', 'MANAGER' -> 'manager').

        Raises:
            UnknownSetupError: For a setup that is not an LSMIO setup (e.g. 'NATIVE-M').

        Returns:
            f"{backend_token}-{variant_tokens}" if variant_tokens else backend_token.
        """
        setup_val = f_backend if f_backend is not None else f_setup
        variant_val = f_key if f_key is not None else f_variant

        if not isinstance(setup_val, str) or not setup_val.strip():
            setup_val = "NATIVE"

        from lsmiotool.lib.benchmarks import LsmioAdapter

        if setup_val.strip().upper() not in LsmioAdapter.ALLOWED_SETUPS:
            raise UnknownSetupError(setup_val, LsmioAdapter.ALLOWED_SETUPS)
        backend_token = setup_val.strip().lower()

        rec = cls.resolve(variant_val)
        if rec.tokens:
            return f"{backend_token}-{rec.tokens}"
        return backend_token


class VariantResolutionResult(NamedTuple):
    """Encapsulates the deterministic decomposition of an archive folder name."""

    raw_directory: str  # e.g. "outputs-native-footer:run-1"
    backend: str  # e.g. "native"
    variant: str  # e.g. "footer"
    collision: Optional[str]  # e.g. "1" or None
    display_label: str  # e.g. "footer" or "footer-1"
    role: Optional[str] = None  # "run" | "base" | None


class VariantReverseResolver:
    """Deterministic reverse-resolution engine mapping archive directories to clean variant labels."""

    PATTERN = re.compile(
        r"^outputs-(?P<backend>[a-zA-Z0-9]+)"
        r"(?:-(?P<variant>[a-zA-Z0-9_-]+?))?"
        r"(?::(?P<role>run|base))?"
        r"(?:-(?P<collision>\d+))?$"
    )

    @classmethod
    def formatLabel(
        cls,
        f_backend: str,
        f_variant: str,
        f_collision: Optional[str] = None,
    ) -> str:
        """Formats canonical display label based on backend, variant, and collision suffix."""
        if f_variant.startswith("version-"):
            payload = f_variant[len("version-") :]
            sub_variant = None
            for cand_var in sorted(
                VariantCatalogue.archivedVariantNames(), key=len, reverse=True
            ):
                if payload.endswith(f"-{cand_var}"):
                    prefix = payload[: -len(cand_var) - 1]
                    if "-" in prefix:
                        sub_variant = cand_var
                        payload = prefix
                        break

            if "-" in payload:
                branch, commit_hash = payload.rsplit("-", 1)
                lbl = f"{branch} ({commit_hash})"
            else:
                lbl = payload

            if sub_variant is not None:
                lbl = f"{lbl} [{sub_variant}]"

            if f_backend != "native":
                lbl = f"{f_backend}-{lbl}"

            if f_collision is not None:
                return f"{lbl}-{f_collision}"
            return lbl

        if f_backend == "native":
            if f_collision is not None:
                return f"{f_variant}-{f_collision}"
            return f_variant

        if f_variant == "default":
            if f_collision is not None:
                return f"{f_backend}-{f_collision}"
            return f_backend

        if f_collision is not None:
            return f"{f_backend}-{f_variant}-{f_collision}"
        return f"{f_backend}-{f_variant}"

    @classmethod
    def resolve(cls, f_dir_name: str) -> Optional[VariantResolutionResult]:
        """Decomposes 'outputs-<backend>-<variant>[:<role>][-<collision>]' and 'outputs-<backend>[-<collision>]'."""
        if not f_dir_name.startswith("outputs-"):
            return None

        match = cls.PATTERN.match(f_dir_name)
        if not match:
            return None

        backend = match.group("backend")
        variant_raw = match.group("variant")
        role = match.group("role")
        collision = match.group("collision")

        # Step 3: Normalize variant and standalone baseline collision
        if variant_raw is None or variant_raw == "":
            variant = "default"
        elif variant_raw.isdigit() and role is None and collision is None:
            variant = "default"
            collision = variant_raw
        else:
            variant = variant_raw

        # Step 4: Disambiguate hyphenated variants ending in digits (e.g. footer-pool-8)
        if role is None and collision is not None and variant != "default":
            combined_candidate = f"{variant}-{collision}"
            if combined_candidate in VariantCatalogue.archivedVariantNames():
                variant = combined_candidate
                collision = None
            elif variant.startswith("version-"):
                sub_cand = combined_candidate[len("version-") :]
                for v in VariantCatalogue.archivedVariantNames():
                    if sub_cand.endswith(f"-{v}"):
                        prefix = sub_cand[: -len(v) - 1]
                        if "-" in prefix:
                            variant = combined_candidate
                            collision = None
                            break

        # Step 5: Canonicalize baseline alias
        if variant in ("", "default", "native"):
            variant = "default"

        # Step 6: Derive display label
        display_label = cls.formatLabel(backend, variant, collision)

        return VariantResolutionResult(
            raw_directory=f_dir_name,
            backend=backend,
            variant=variant,
            collision=collision,
            display_label=display_label,
            role=role,
        )
