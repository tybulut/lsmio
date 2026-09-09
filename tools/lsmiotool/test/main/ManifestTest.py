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
import unittest

from lsmiotool.lib.profile import ProfileLoader
from lsmiotool.lib.run import (
    Combination,
    ManifestDocument,
    ManifestSerializer,
    ManifestValidationError,
    RunPlan,
    RunPlanner,
    RunRequest,
    ScalePoint,
    ScheduledPointResources,
)
from lsmiotool.lib.site import EnvironmentResolver


class ManifestTest(unittest.TestCase):
    """Unit tests for ManifestDocument, canonical JSON formatting, and ManifestSerializer."""

    def setUp(self) -> None:
        self.m_default_profile_path = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "etc", "environments.json"
            )
        )
        self.m_profile_doc = ProfileLoader.load(self.m_default_profile_path)
        self.m_test_user = "alice"
        self.m_test_home = "/home/alice"
        self.m_registry = EnvironmentResolver.resolveRegistry(
            self.m_profile_doc, f_user=self.m_test_user, f_home=self.m_test_home
        )
        self.m_dev_profile = self.m_registry.getProfile("DEV")
        self.m_viking_profile = self.m_registry.getProfile("VIKING")
        self.m_viking2_profile = self.m_registry.getProfile("VIKING2")
        self.m_isambard_profile = self.m_registry.getProfile("ISAMBARD")
        self.m_archer2_profile = self.m_registry.getProfile("ARCHER2")

    def testCanonicalJsonFormattingAndRoundTrip(self) -> None:
        """Assert 2-space indentation, sorted keys, newline termination, and exact roundtrip."""
        # 1. Test across different targets, scales, storage classes, and profiles
        f_test_configs = [
            ("ior", "local", False, "BASE", self.m_viking_profile),
            ("lsmio", "bake", True, "NATIVE-M", self.m_viking2_profile),
            ("lmp", "small", False, "LSMIO", self.m_isambard_profile),
            ("ior", "large", True, "HDF5", self.m_archer2_profile),
            ("lsmio", "local", False, "ROCKSDB-M", self.m_dev_profile),
        ]

        for f_target, f_scale, f_ssd, f_setup, f_prof in f_test_configs:
            f_tokens = [
                f"lm-{f_i:024x}"
                for f_i in range(len(RunPlanner.SCALE_MATRICES[f_scale]))
            ]
            f_tok_idx = 0

            def token_gen() -> str:
                nonlocal f_tok_idx
                f_tok = f_tokens[f_tok_idx]
                f_tok_idx += 1
                return f_tok

            f_req = RunRequest(
                f_target=f_target, f_scale=f_scale, f_ssd=f_ssd, f_setup=f_setup
            )
            f_plan = RunPlanner.createPlan(
                f_request=f_req,
                f_profile=f_prof,
                f_run_id_source=lambda: f"run-test-{f_target}-{f_scale}",
                f_clock=lambda: "2026-08-20T12:00:00Z",
                f_token_source=token_gen,
            )

            # Serialization to canonical JSON
            f_json_str = ManifestSerializer.serialize(f_plan)

            # Assert string ends with trailing newline
            self.assertTrue(f_json_str.endswith("\n"))

            # Assert 2-space indentation
            self.assertTrue(f_json_str.startswith('{\n  "'))
            self.assertIn('\n  "combinations": [', f_json_str)
            self.assertIn('\n  "schema_version": 1,', f_json_str)

            # Assert top-level keys appear in sorted alphabetical order
            f_expected_top_order = [
                "combinations",
                "created_at_utc",
                "plan",
                "points",
                "request",
                "run_id",
                "scale_points",
                "schema_version",
                "site",
                "tokens",
            ]
            f_positions = [f_json_str.find(f'"{f_k}":') for f_k in f_expected_top_order]
            self.assertEqual(f_positions, sorted(f_positions))

            # Deserialization from JSON string
            f_doc = ManifestSerializer.deserialize(f_json_str)
            self.assertEqual(f_doc.schema_version, 1)
            self.assertEqual(f_doc.run_id, f_plan.run_id)
            self.assertEqual(f_doc.created_at_utc, f_plan.manifest_timestamp)
            self.assertEqual(f_doc.request, f_plan.request)
            self.assertEqual(f_doc.site.toDict(), f_plan.profile.toDict())
            self.assertEqual(f_doc.scale_points, f_plan.scale_points)
            self.assertEqual(f_doc.combinations, f_plan.combinations)
            self.assertEqual(f_doc.points, f_plan.scheduled_points)
            self.assertEqual(f_doc.tokens, f_plan.tokens)

            # Assert plan dict matches resolved properties
            self.assertEqual(f_doc.plan["target"], f_plan.request.target)
            self.assertEqual(f_doc.plan["scale"], f_plan.request.scale)
            self.assertEqual(f_doc.plan["storage"], f_plan.request.storage.value)
            self.assertEqual(f_doc.plan["setup"], f_plan.request.setup)
            self.assertEqual(f_doc.plan["lmp_task_tuning"], f_plan.lmp_task_tuning)

            # Roundtrip to RunPlan
            f_reconstructed_plan = f_doc.toRunPlan()
            self.assertEqual(f_reconstructed_plan, f_plan)

            # Re-serialization exact byte/string equality
            self.assertEqual(ManifestSerializer.serialize(f_doc), f_json_str)
            self.assertEqual(
                ManifestSerializer.serialize(f_reconstructed_plan), f_json_str
            )
            self.assertEqual(f_doc.toJson(), f_json_str)

            # Deserialization from UTF-8 bytes
            f_doc_from_bytes = ManifestSerializer.deserialize(
                f_json_str.encode("utf-8")
            )
            self.assertEqual(f_doc_from_bytes, f_doc)

            # Deserialization from dictionary
            f_dict = json.loads(f_json_str)
            f_doc_from_dict = ManifestSerializer.deserialize(f_dict)
            self.assertEqual(f_doc_from_dict, f_doc)

    def testSchemaVersionValidation(self) -> None:
        """Assert fail-closed rejection of missing, non-1, non-integer, or float schema_version."""
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-version-test",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-000000000000000000000001",
        )
        f_base_dict = json.loads(ManifestSerializer.serialize(f_plan))

        # 1. Missing schema_version
        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["schema_version"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("schema_version", str(f_ctx.exception))

        # 2. Version != 1
        for f_bad_ver in [0, 2, -1, 99]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["schema_version"] = f_bad_ver
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("schema_version", str(f_ctx.exception))

        # 3. String schema_version
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["schema_version"] = "1"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("schema_version", str(f_ctx.exception))

        # 4. Float schema_version
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["schema_version"] = 1.0
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("schema_version", str(f_ctx.exception))

        # 5. Boolean schema_version (True is int in Python, but disallowed)
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["schema_version"] = True
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("schema_version", str(f_ctx.exception))

        # 6. Null schema_version
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["schema_version"] = None
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("schema_version", str(f_ctx.exception))

    def testPointTokenCardinalityAndUniqueness(self) -> None:
        """Assert strict 1:1 cardinality between points and tokens, no duplicate tokens, and regex validation."""
        f_req = RunRequest("ior", "bake")  # bake has 4 points
        f_tokens = [f"lm-{f_i:024x}" for f_i in range(4)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-tokens-test",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )
        f_base_dict = json.loads(ManifestSerializer.serialize(f_plan))

        # 1. Cardinality mismatch: fewer tokens than points (3 tokens for 4 points)
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = f_tokens[:3]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("tokens count", str(f_ctx.exception))

        # 2. Cardinality mismatch: more tokens than points (5 tokens for 4 points)
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = f_tokens + ["lm-000000000000000000000005"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("tokens count", str(f_ctx.exception))

        # 3. Duplicate tokens
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = [f_tokens[0], f_tokens[0], f_tokens[2], f_tokens[3]]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("Duplicate", str(f_ctx.exception))

        # 4. Invalid token formats
        # Uppercase hex
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = ["lm-0123456789ABCDEF01234567"] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

        # Wrong prefix
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = ["xx-000000000000000000000000"] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

        # Too short / too long
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = ["lm-1234"] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = ["lm-0000000000000000000000000000"] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

        # Non-hex characters
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = ["lm-00000000000000000000000g"] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

        # Non-string token
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["tokens"] = [12345] + f_tokens[1:]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("invalid", str(f_ctx.exception))

    def testRejectsExtraOrMissingFields(self) -> None:
        """Assert fail-closed validation on extra or missing keys at every level of the manifest."""
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-fields-test",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-000000000000000000000001",
        )
        f_base_dict = json.loads(ManifestSerializer.serialize(f_plan))

        # 1. Extra top-level keys (e.g. prohibited mutable state / job IDs)
        for f_extra_key in [
            "job_id",
            "job_ids",
            "status",
            "state",
            "results",
            "extra_field",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict[f_extra_key] = "prohibited_value"
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn(f_extra_key, str(f_ctx.exception))

        # 2. Missing each top-level key one by one
        f_required_top = [
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
        ]
        for f_req_key in f_required_top:
            f_dict = copy.deepcopy(f_base_dict)
            del f_dict[f_req_key]
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn(f_req_key, str(f_ctx.exception))

        # 3. Request sub-fields
        # Extra key in request
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["request"]["unexpected_key"] = "bad"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("unexpected_key", str(f_ctx.exception))

        # Missing key in request
        for f_req_sub in ["target", "scale", "ssd", "setup"]:
            f_dict = copy.deepcopy(f_base_dict)
            del f_dict["request"][f_req_sub]
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn(f_req_sub, str(f_ctx.exception))

        # 4. Plan sub-fields
        # Extra key in plan
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["plan"]["extra_plan_prop"] = 123
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("extra_plan_prop", str(f_ctx.exception))

        # Missing key in plan
        for f_plan_sub in ["target", "scale", "storage", "setup", "lmp_task_tuning"]:
            f_dict = copy.deepcopy(f_base_dict)
            del f_dict["plan"][f_plan_sub]
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn(f_plan_sub, str(f_ctx.exception))

        # 5. Scale points sub-fields
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["scale_points"][0]["extra"] = 99
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("extra", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["scale_points"][0]["tasks"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("tasks", str(f_ctx.exception))

        # 6. Combinations sub-fields
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["combinations"][0]["extra_combo"] = True
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("extra_combo", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["combinations"][0]["block_bytes"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("block_bytes", str(f_ctx.exception))

        # 7. Points sub-fields
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["points"][0]["job_id"] = "12345"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("job_id", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["points"][0]["walltime"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("walltime", str(f_ctx.exception))

        # 8. Site sub-fields
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["site"]["extra_site_attr"] = "value"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("extra_site_attr", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["site"]["scheduler"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("scheduler", str(f_ctx.exception))

        # Site benchmark_roots missing or extra
        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["site"]["benchmark_roots"]["hdd"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("benchmark_roots", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        f_dict["site"]["benchmark_roots"]["nvme"] = "/mnt/nvme"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("benchmark_roots", str(f_ctx.exception))

        # Site resources missing shape or shape extra key
        f_dict = copy.deepcopy(f_base_dict)
        del f_dict["site"]["resources"]["large"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("resources", str(f_ctx.exception))

        f_dict = copy.deepcopy(f_base_dict)
        f_dict["site"]["resources"]["small"]["extra_res_field"] = "bad"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("extra_res_field", str(f_ctx.exception))

        # Site rank_identity missing or extra
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["site"]["rank_identity"]["extra_rank"] = "bad"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("rank_identity", str(f_ctx.exception))

        # Site cancellation missing or extra
        f_dict = copy.deepcopy(f_base_dict)
        f_dict["site"]["cancellation"]["extra_canc"] = 12
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_dict)
        self.assertIn("cancellation", str(f_ctx.exception))

    def testTimestampFormattingIsoUtc(self) -> None:
        """Assert strict ISO 8601 UTC timestamp format (%Y-%m-%dT%H:%M:%SZ) without float seconds."""
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-ts-test",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-000000000000000000000001",
        )
        f_base_dict = json.loads(ManifestSerializer.serialize(f_plan))

        # 1. Valid ISO 8601 UTC formats
        for f_valid_ts in [
            "2026-08-20T12:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-12-31T23:59:59Z",
            "2025-06-15T08:30:45Z",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_valid_ts
            f_doc = ManifestSerializer.deserialize(f_dict)
            self.assertEqual(f_doc.created_at_utc, f_valid_ts)

        # 2. Reject float / millisecond timestamps
        for f_float_ts in [
            "2026-08-20T12:00:00.000Z",
            "2026-08-20T12:00:00.123456Z",
            "2026-08-20T12:00:00.0Z",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_float_ts
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("created_at_utc", str(f_ctx.exception))

        # 3. Reject non-Z timezone offsets
        for f_tz_ts in [
            "2026-08-20T12:00:00+00:00",
            "2026-08-20T12:00:00-07:00",
            "2026-08-20T12:00:00+0100",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_tz_ts
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("created_at_utc", str(f_ctx.exception))

        # 4. Reject missing Z or space separator
        for f_bad_fmt in [
            "2026-08-20T12:00:00",
            "2026-08-20 12:00:00",
            "2026-08-20 12:00:00Z",
            "2026/08/20 12:00:00",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_bad_fmt
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("created_at_utc", str(f_ctx.exception))

        # 5. Reject invalid calendar date / time
        for f_invalid_date in [
            "2026-02-30T12:00:00Z",
            "2026-13-01T12:00:00Z",
            "2026-00-01T12:00:00Z",
            "2026-08-32T12:00:00Z",
            "2026-08-20T24:00:00Z",
            "2026-08-20T12:60:00Z",
        ]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_invalid_date
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("created_at_utc", str(f_ctx.exception))

        # 6. Reject non-string timestamps
        for f_non_str in [1724155200, 1724155200.5, None, True]:
            f_dict = copy.deepcopy(f_base_dict)
            f_dict["created_at_utc"] = f_non_str
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_dict)
            self.assertIn("created_at_utc", str(f_ctx.exception))

    def testImmutabilityAndSerializerEdgeCases(self) -> None:
        """Assert ManifestDocument immutability and serializer error boundaries."""
        f_req = RunRequest("ior", "local")
        f_plan = RunPlanner.createPlan(
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-edge-test",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-000000000000000000000001",
        )
        f_json = ManifestSerializer.serialize(f_plan)
        f_doc = ManifestSerializer.deserialize(f_json)

        # Immutability
        with self.assertRaises(AttributeError):
            f_doc.run_id = "other-run-id"  # type: ignore
        with self.assertRaises(AttributeError):
            del f_doc.run_id  # type: ignore

        # Serializing invalid object raises ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.serialize("not-a-plan")  # type: ignore
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.serialize(None)  # type: ignore

        # Deserializing invalid source
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize("{invalid json")
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize("")
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize("   ")
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize("[1, 2, 3]")
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize(12345)  # type: ignore
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.deserialize(b"\xff\xfe\xfd")  # invalid UTF-8

        # Plan with invalid timestamp raises during serialize
        f_bad_plan = RunPlan(
            f_run_id="run-bad-ts",
            f_request=f_req,
            f_profile=self.m_viking_profile,
            f_scale_points=f_plan.scale_points,
            f_combinations=f_plan.combinations,
            f_scheduled_points=f_plan.scheduled_points,
            f_tokens=f_plan.tokens,
            f_manifest_timestamp="invalid-timestamp",
        )
        with self.assertRaises(ManifestValidationError):
            ManifestSerializer.serialize(f_bad_plan)

    def testLmpTuningCanonicalRoundTripAndByteStability(self) -> None:
        """Assert LMP task tuning round-trips through canonical JSON serialization with byte stability."""
        f_expected_local = {
            "1": {"replication": 4, "buffer_size_mb": 32},
        }
        f_expected_bake = {
            "1": {"replication": 4, "buffer_size_mb": 32},
            "2": {"replication": 5, "buffer_size_mb": 32},
            "4": {"replication": 6, "buffer_size_mb": 64},
            "8": {"replication": 8, "buffer_size_mb": 128},
        }
        f_expected_small = {
            "1": {"replication": 4, "buffer_size_mb": 32},
            "2": {"replication": 5, "buffer_size_mb": 32},
            "4": {"replication": 6, "buffer_size_mb": 64},
            "8": {"replication": 8, "buffer_size_mb": 128},
            "16": {"replication": 10, "buffer_size_mb": 256},
            "24": {"replication": 12, "buffer_size_mb": 512},
            "32": {"replication": 14, "buffer_size_mb": 1024},
            "40": {"replication": 15, "buffer_size_mb": 1024},
            "48": {"replication": 16, "buffer_size_mb": 1024},
        }

        f_cases = [
            ("local", self.m_viking_profile, f_expected_local),
            ("bake", self.m_viking2_profile, f_expected_bake),
            ("small", self.m_isambard_profile, f_expected_small),
        ]

        for f_scale, f_profile, f_expected in f_cases:
            f_tokens = [
                f"lm-{f_i:024x}"
                for f_i in range(len(RunPlanner.SCALE_MATRICES[f_scale]))
            ]
            f_tok_idx = 0

            def token_gen() -> str:
                nonlocal f_tok_idx
                f_tok = f_tokens[f_tok_idx]
                f_tok_idx += 1
                return f_tok

            f_req = RunRequest(
                f_target="lmp", f_scale=f_scale, f_ssd=False, f_setup="LSMIO"
            )
            f_plan = RunPlanner.createPlan(
                f_request=f_req,
                f_profile=f_profile,
                f_run_id_source=lambda: f"run-lmp-{f_scale}",
                f_clock=lambda: "2026-08-20T12:00:00Z",
                f_token_source=token_gen,
            )

            # Plan contains exact literal expected tuning
            self.assertEqual(f_plan.lmp_task_tuning, f_expected)

            # Serialize to canonical JSON
            f_json_str = ManifestSerializer.serialize(f_plan)

            # Verify presence in serialized manifest
            f_parsed_raw = json.loads(f_json_str)
            self.assertEqual(f_parsed_raw["plan"]["lmp_task_tuning"], f_expected)

            # Deserialize to ManifestDocument
            f_doc = ManifestSerializer.deserialize(f_json_str)
            self.assertEqual(f_doc.plan["lmp_task_tuning"], f_expected)

            # Reconstruct to RunPlan
            f_reconstructed_plan = f_doc.toRunPlan()
            self.assertEqual(f_reconstructed_plan.lmp_task_tuning, f_expected)
            self.assertEqual(f_reconstructed_plan, f_plan)

            # Byte stability
            self.assertEqual(ManifestSerializer.serialize(f_doc), f_json_str)
            self.assertEqual(
                ManifestSerializer.serialize(f_reconstructed_plan), f_json_str
            )
            self.assertEqual(f_doc.toJson(), f_json_str)

    def testNonLmpTuningIsExactlyEmpty(self) -> None:
        """Assert non-LMP manifests (IOR, LSMIO) always have lmp_task_tuning as exactly {}."""
        f_cases = [
            ("ior", "local", self.m_viking_profile, "BASE"),
            ("ior", "bake", self.m_viking2_profile, "HDF5"),
            ("ior", "small", self.m_isambard_profile, "COLLECTIVE"),
            ("ior", "large", self.m_archer2_profile, "REVERSE"),
            ("lsmio", "local", self.m_dev_profile, "NATIVE-M"),
            ("lsmio", "bake", self.m_viking_profile, "ROCKSDB-M"),
            ("lsmio", "small", self.m_viking2_profile, "ADIOS-M"),
            ("lsmio", "large", self.m_archer2_profile, "LEVELDB-M"),
        ]

        for f_target, f_scale, f_profile, f_setup in f_cases:
            f_tokens = [
                f"lm-{f_i:024x}"
                for f_i in range(len(RunPlanner.SCALE_MATRICES[f_scale]))
            ]
            f_tok_idx = 0

            def token_gen() -> str:
                nonlocal f_tok_idx
                f_tok = f_tokens[f_tok_idx]
                f_tok_idx += 1
                return f_tok

            f_req = RunRequest(
                f_target=f_target, f_scale=f_scale, f_ssd=False, f_setup=f_setup
            )
            f_plan = RunPlanner.createPlan(
                f_request=f_req,
                f_profile=f_profile,
                f_run_id_source=lambda: f"run-{f_target}-{f_scale}",
                f_clock=lambda: "2026-08-20T12:00:00Z",
                f_token_source=token_gen,
            )

            self.assertEqual(f_plan.lmp_task_tuning, {})
            f_json_str = ManifestSerializer.serialize(f_plan)
            f_parsed_raw = json.loads(f_json_str)
            self.assertEqual(f_parsed_raw["plan"]["lmp_task_tuning"], {})

            f_doc = ManifestSerializer.deserialize(f_json_str)
            self.assertEqual(f_doc.plan["lmp_task_tuning"], {})

            f_reconstructed_plan = f_doc.toRunPlan()
            self.assertEqual(f_reconstructed_plan.lmp_task_tuning, {})
            self.assertEqual(f_reconstructed_plan, f_plan)

            self.assertEqual(ManifestSerializer.serialize(f_doc), f_json_str)
            self.assertEqual(
                ManifestSerializer.serialize(f_reconstructed_plan), f_json_str
            )

    def testMissingExtraMalformedNodeKeyedOrMismatchedTuningRejected(self) -> None:
        """Assert fail-closed rejection of missing, extra, malformed, node-keyed, or mismatched LMP tuning."""
        # 1. Base valid LMP small manifest dictionary
        f_tokens = [f"lm-{f_i:024x}" for f_i in range(9)]
        f_tok_idx = 0

        def token_gen() -> str:
            nonlocal f_tok_idx
            f_tok = f_tokens[f_tok_idx]
            f_tok_idx += 1
            return f_tok

        f_lmp_req = RunRequest(f_target="lmp", f_scale="small")
        f_lmp_plan = RunPlanner.createPlan(
            f_request=f_lmp_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-lmp-valid",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=token_gen,
        )
        f_lmp_base_dict = json.loads(ManifestSerializer.serialize(f_lmp_plan))

        # Base valid IOR local manifest dictionary
        f_ior_req = RunRequest(f_target="ior", f_scale="local")
        f_ior_plan = RunPlanner.createPlan(
            f_request=f_ior_req,
            f_profile=self.m_viking_profile,
            f_run_id_source=lambda: "run-ior-valid",
            f_clock=lambda: "2026-08-20T12:00:00Z",
            f_token_source=lambda: "lm-000000000000000000000001",
        )
        f_ior_base_dict = json.loads(ManifestSerializer.serialize(f_ior_plan))

        # A. Missing lmp_task_tuning key in plan
        f_d = copy.deepcopy(f_lmp_base_dict)
        del f_d["plan"]["lmp_task_tuning"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("lmp_task_tuning", str(f_ctx.exception))

        # B. Non-dict lmp_task_tuning
        for f_bad_val in ["not-a-dict", [1, 2, 4], 123, True, None]:
            f_d = copy.deepcopy(f_lmp_base_dict)
            f_d["plan"]["lmp_task_tuning"] = f_bad_val
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_d)
            self.assertIn("lmp_task_tuning", str(f_ctx.exception))

        # C. Non-LMP target with non-empty lmp_task_tuning
        f_d = copy.deepcopy(f_ior_base_dict)
        f_d["plan"]["lmp_task_tuning"] = {"1": {"replication": 4, "buffer_size_mb": 32}}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("empty", str(f_ctx.exception))

        # D. LMP missing a planned scale point's task count (missing task "48")
        f_d = copy.deepcopy(f_lmp_base_dict)
        del f_d["plan"]["lmp_task_tuning"]["48"]
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("match", str(f_ctx.exception))

        # E. LMP with extra task count not in scale points (adding "64" to small)
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["64"] = {
            "replication": 20,
            "buffer_size_mb": 2048,
        }
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertTrue(
            "undefined" in str(f_ctx.exception) or "match" in str(f_ctx.exception)
        )

        # F. Node-keyed substitutions instead of decimal tasks
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"] = {
            "node_1": {"replication": 4, "buffer_size_mb": 32},
        }
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("invalid", str(f_ctx.exception))

        # G. Non-decimal or malformed keys (e.g. "01", "-1", "1.0", "one", "")
        for f_bad_key in ["01", "-1", "1.0", "one", "", " 1 ", "1_0"]:
            f_d = copy.deepcopy(f_lmp_base_dict)
            f_d["plan"]["lmp_task_tuning"][f_bad_key] = {
                "replication": 4,
                "buffer_size_mb": 32,
            }
            with self.assertRaises(ManifestValidationError) as f_ctx:
                ManifestSerializer.deserialize(f_d)
            self.assertIn("invalid", str(f_ctx.exception))

        # H. Inner dictionary malformed
        # Missing replication
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"buffer_size_mb": 32}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("contain exactly", str(f_ctx.exception))

        # Missing buffer_size_mb
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"replication": 4}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("contain exactly", str(f_ctx.exception))

        # Extra key in inner dict
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {
            "replication": 4,
            "buffer_size_mb": 32,
            "extra_key": 99,
        }
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("contain exactly", str(f_ctx.exception))

        # Non-dict inner value
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = "replication=4"
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("dict", str(f_ctx.exception))

        # Boolean values in replication or buffer_size_mb
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {
            "replication": True,
            "buffer_size_mb": 32,
        }
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("positive integer", str(f_ctx.exception))

        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {
            "replication": 4,
            "buffer_size_mb": False,
        }
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("positive integer", str(f_ctx.exception))

        # Zero or negative values
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"replication": 0, "buffer_size_mb": 32}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("positive integer", str(f_ctx.exception))

        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"replication": 4, "buffer_size_mb": -32}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("positive integer", str(f_ctx.exception))

        # Float values
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"replication": 4.0, "buffer_size_mb": 32}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("positive integer", str(f_ctx.exception))

        # Mismatched tuning values (does not match approved LMP tuning authority)
        f_d = copy.deepcopy(f_lmp_base_dict)
        f_d["plan"]["lmp_task_tuning"]["1"] = {"replication": 99, "buffer_size_mb": 32}
        with self.assertRaises(ManifestValidationError) as f_ctx:
            ManifestSerializer.deserialize(f_d)
        self.assertIn("match", str(f_ctx.exception))
