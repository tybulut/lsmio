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

    _TWO_SEGMENT_PREFIXES: Tuple[str, ...] = (
        "native-m-",
        "rocksdb-m-",
        "leveldb-m-",
        "adios-m-",
        "plugin-m-",
    )

    _ONE_SEGMENT_PREFIXES: Tuple[str, ...] = (
        "native-",
        "rocksdb-",
        "leveldb-",
        "adios-",
        "plugin-",
        "manager-",
    )

    # Exhaustive mapping of all 37 non-empty variant keys to (tokens, engine_flags)
    _VARIANT_SPECS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
        "footer": ("footer", ("--lsmio-no-autotune", "--lsmio-footer-index")),
        "btree": ("btree", ("--lsmio-no-autotune", "--lsmio-memtable", "btree")),
        "footer-btree": (
            "footer-btree",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-memtable", "btree"),
        ),
        "map": ("map", ("--lsmio-no-autotune", "--lsmio-memtable", "map")),
        "vsort": ("vsort", ("--lsmio-no-autotune", "--lsmio-memtable", "vector-sort")),
        "prealloc": ("prealloc", ("--lsmio-no-autotune", "--lsmio-prealloc")),
        "footer-prealloc": (
            "footer-prealloc",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-prealloc"),
        ),
        "manoff": ("manoff", ("--lsmio-no-autotune", "--lsmio-manual-offset")),
        "footer-manoff": (
            "footer-manoff",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-manual-offset"),
        ),
        "wbuf-512m": ("wbuf-512m", ("--lsmio-no-autotune", "--lsmio-wbuffer", "536870912")),
        "wbuf-32m": ("wbuf-32m", ("--lsmio-no-autotune", "--lsmio-wbuffer", "33554432")),
        "footer-wbuf-512m": (
            "footer-wbuf-512m",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-wbuffer", "536870912"),
        ),
        "footer-btree-prealloc": (
            "footer-btree-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-prealloc",
            ),
        ),
        "bfilter": ("bfilter", ("--lsmio-no-autotune", "--lsmio-bfilter")),
        "wal": ("wal", ("--lsmio-no-autotune", "--lsmio-wal")),
        "mmap": ("mmap", ("--lsmio-no-autotune", "--lsmio-mmap", "--lsmio-no-pread")),
        "pread": ("pread", ("--lsmio-no-autotune", "--lsmio-pread")),
        "footer-mmap": (
            "footer-mmap",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-mmap", "--lsmio-no-pread"),
        ),
        "footer-pread": (
            "footer-pread",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-pread"),
        ),
        "compress": ("compress", ("--lsmio-no-autotune", "--lsmio-compress")),
        "sync": ("sync", ("--lsmio-no-autotune", "--sync")),
        "pool-8": ("pool-8", ("--lsmio-no-autotune", "--lsmio-pool", "8")),
        # INV-ARCH-4: exact CLI11 spelling --lsmio-always-flush
        "flush": ("flush", ("--lsmio-no-autotune", "--lsmio-always-flush")),
        "batch-2048": ("batch-2048", ("--lsmio-no-autotune", "--lsmio-batch-size", "2048")),
        "manoff-prealloc": (
            "manoff-prealloc",
            ("--lsmio-no-autotune", "--lsmio-manual-offset", "--lsmio-prealloc"),
        ),
        "wbuf-512m-manoff-prealloc": (
            "wbuf-512m-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-wbuffer",
                "536870912",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-wbuf-32m": (
            "footer-wbuf-32m",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-wbuffer", "33554432"),
        ),
        "footer-pool-8": (
            "footer-pool-8",
            ("--lsmio-no-autotune", "--lsmio-footer-index", "--lsmio-pool", "8"),
        ),
        "footer-wbuf-512m-manoff-prealloc": (
            "footer-wbuf-512m-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-wbuffer",
                "536870912",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-vsort-manoff-prealloc": (
            "footer-vsort-manoff-prealloc",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
                "--lsmio-prealloc",
            ),
        ),
        "footer-vsort-manoff-mmap": (
            "footer-vsort-manoff-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "footer-vsort-manoff": (
            "footer-vsort-manoff",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-manual-offset",
            ),
        ),
        "footer-pool-8-mmap": (
            "footer-pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "footer-manoff-pool-8-mmap": (
            "footer-manoff-pool-8-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "footer-btree-manoff-mmap": (
            "footer-btree-manoff-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-manual-offset",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "footer-manoff-pool-8": (
            "footer-manoff-pool-8",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
            ),
        ),
        "footer-pread-pool-8": (
            "footer-pread-pool-8",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-pread",
                "--lsmio-pool",
                "8",
            ),
        ),
        "footer-pread-manoff": (
            "footer-pread-manoff",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-pread",
                "--lsmio-manual-offset",
            ),
        ),
        "footer-pread-manoff-pool-8": (
            "footer-pread-manoff-pool-8",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-pread",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
            ),
        ),
        "footer-map-pread": (
            "footer-map-pread",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "map",
                "--lsmio-pread",
            ),
        ),
        "footer-btree-pread": (
            "footer-btree-pread",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-pread",
            ),
        ),
        "footer-vsort-pread": (
            "footer-vsort-pread",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "vector-sort",
                "--lsmio-pread",
            ),
        ),
        "footer-btree-manoff-pread": (
            "footer-btree-manoff-pread",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "btree",
                "--lsmio-manual-offset",
                "--lsmio-pread",
            ),
        ),
        "footer-map-manoff-pread": (
            "footer-map-manoff-pread",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "map",
                "--lsmio-manual-offset",
                "--lsmio-pread",
            ),
        ),
        "footer-map-manoff-mmap": (
            "footer-map-manoff-mmap",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "map",
                "--lsmio-manual-offset",
                "--lsmio-mmap",
                "--lsmio-no-pread",
            ),
        ),
        "footer-map": (
            "footer-map",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "map",
            ),
        ),
        "footer-map-manoff": (
            "footer-map-manoff",
            (
                "--lsmio-no-autotune",
                "--lsmio-footer-index",
                "--lsmio-memtable",
                "map",
                "--lsmio-manual-offset",
            ),
        ),
        "manoff-pool-8": (
            "manoff-pool-8",
            (
                "--lsmio-no-autotune",
                "--lsmio-manual-offset",
                "--lsmio-pool",
                "8",
            ),
        ),
        "vnosort": (
            "vnosort",
            ("--lsmio-no-autotune", "--lsmio-memtable", "vector-no-sort"),
        ),
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
        "autotune": (
            "autotune",
            ("--lsmio-autotune",),
        ),
    }

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

        Patterns handled:
        - Two segments: native-m-*, rocksdb-m-*, leveldb-m-*, adios-m-*, plugin-m-*
        - One segment: native-*, rocksdb-*, leveldb-*, adios-*, plugin-*, manager-*
        """
        if not isinstance(f_key, str):
            raise TypeError(f"f_key must be a string, got: {type(f_key).__name__}")
        k = f_key.strip().lower()
        for prefix in cls._TWO_SEGMENT_PREFIXES:
            if k.startswith(prefix):
                return k[len(prefix) :]
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
    def canonicalVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all 26 streamlined matrix variant keys in canonical order ('default' followed by 25 variants)."""
        return ("default",) + cls._CANONICAL_VARIANTS

    @classmethod
    def mostVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all 26 streamlined matrix variant keys in canonical order (alias for canonicalVariants)."""
        return cls.canonicalVariants()

    @classmethod
    def allVariants(cls) -> Tuple[str, ...]:
        """Returns tuple of all variants in exhaustive catalog ('default' followed by all supported non-empty variants)."""
        return ("default",) + cls.supportedVariants()

    @classmethod
    def resolve(cls, f_key: Optional[str] = None) -> VariantRecord:
        """Resolves variant key into a canonical VariantRecord.

        Handles:
        - None, "", "base", "default" -> empty variant (base run).
        - Strips backend prefix.
        - Canonical lookup against 37 discrete non-empty keys.
        - Raises UnknownVariantError on unrecognized keys.
        """
        if f_key is None:
            return VariantRecord("", "", ())

        if not isinstance(f_key, str):
            raise UnknownVariantError(str(f_key), cls.supportedVariants())

        stripped_raw = f_key.strip()
        if stripped_raw == "":
            return VariantRecord("", "", ())

        if stripped_raw.lower() in ("base", "default"):
            return VariantRecord("", "", ())

        stripped = cls.stripBackendPrefix(stripped_raw)
        if stripped in ("", "base", "default"):
            return VariantRecord("", "", ())

        if stripped in cls._VARIANT_SPECS:
            spec_tokens, spec_flags = cls._VARIANT_SPECS[stripped]
            return VariantRecord(stripped, spec_tokens, spec_flags)

        if stripped.startswith("version-"):
            payload = stripped[len("version-"):]
            for cand_var in sorted(cls.supportedVariants(), key=len, reverse=True):
                if payload.endswith(f"-{cand_var}"):
                    prefix = payload[:-len(cand_var) - 1]
                    if "-" in prefix:
                        spec = cls._VARIANT_SPECS[cand_var]
                        return VariantRecord(stripped, stripped, spec[1])
            return VariantRecord(stripped, stripped, ("--lsmio-no-autotune",))

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

        Backend tokens:
        - Setup ending in '-M': base setup without '-M' lowercased (e.g. 'NATIVE-M' -> 'native')
        - Setup == 'MANAGER': 'manager'
        - Other setups: setup lowercased with '-nompi' (e.g. 'ROCKSDB' -> 'rocksdb-nompi')

        Returns:
            f"{backend_token}-{variant_tokens}" if variant_tokens else backend_token.
        """
        setup_val = f_backend if f_backend is not None else f_setup
        variant_val = f_key if f_key is not None else f_variant

        if not isinstance(setup_val, str) or not setup_val.strip():
            setup_val = "NATIVE-M"

        setup_clean = setup_val.strip()
        setup_upper = setup_clean.upper()

        if setup_upper.endswith("-M"):
            backend_token = setup_upper[:-2].lower()
        elif setup_upper == "MANAGER":
            backend_token = "manager"
        else:
            backend_token = f"{setup_clean.lower()}-nompi"

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
            payload = f_variant[len("version-"):]
            sub_variant = None
            for cand_var in sorted(VariantCatalogue.supportedVariants(), key=len, reverse=True):
                if payload.endswith(f"-{cand_var}"):
                    prefix = payload[:-len(cand_var) - 1]
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
            if combined_candidate in VariantCatalogue.supportedVariants():
                variant = combined_candidate
                collision = None
            elif variant.startswith("version-"):
                sub_cand = combined_candidate[len("version-"):]
                for v in VariantCatalogue.supportedVariants():
                    if sub_cand.endswith(f"-{v}"):
                        prefix = sub_cand[:-len(v) - 1]
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
