"""Versioned runtime contracts for evidence-bearing pipeline artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _required(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    missing = fields - set(value)
    if missing:
        raise ValueError(f"{label} is missing required fields: {sorted(missing)}")


@dataclass(frozen=True)
class SyncReport:
    verdict: str
    bindings: Mapping[str, Any]

    @classmethod
    def parse(cls, raw: Any) -> "SyncReport":
        value = _mapping(raw, "sync report")
        _required(value, {"schema_version", "verdict", "bindings"}, "sync report")
        if value["schema_version"] != 1 or value["verdict"] not in {"PASS", "NOT_REQUIRED"}:
            raise ValueError("invalid sync report version or verdict")
        return cls(str(value["verdict"]), _mapping(value["bindings"], "sync bindings"))


@dataclass(frozen=True)
class EditorialAnalysis:
    source_transcript_sha256: str
    candidates: tuple[Mapping[str, Any], ...]

    @classmethod
    def parse(cls, raw: Any) -> "EditorialAnalysis":
        value = _mapping(raw, "editorial analysis")
        fields = {
            "schema_version", "kind", "worker_version", "source_transcript_sha256",
            "thresholds", "verdict", "pause_candidates", "repetition_candidates",
            "take_candidates", "candidates",
        }
        _required(value, fields, "editorial analysis")
        if value["schema_version"] != 1 or value["kind"] != "editorial-analysis":
            raise ValueError("invalid editorial analysis version or kind")
        if not str(value["worker_version"]).strip() or not str(value["source_transcript_sha256"]).startswith("sha256:"):
            raise ValueError("editorial analysis has invalid bindings")
        thresholds = _mapping(value["thresholds"], "editorial thresholds")
        pause = float(thresholds.get("pause_s", float("nan")))
        similarity = float(thresholds.get("repetition_similarity", float("nan")))
        if not math.isfinite(pause) or pause < 0 or not math.isfinite(similarity) or not 0 <= similarity <= 1:
            raise ValueError("editorial analysis has invalid thresholds")
        detail_specs = {
            "pause": ("pause_candidates", {"id", "after_utterance_id", "before_utterance_id", "start_s", "end_s", "duration_s", "reason"}),
            "repetition": ("repetition_candidates", {"id", "utterance_ids", "similarity", "reason"}),
            "take": ("take_candidates", {"id", "take_group", "utterance_ids", "recommended_keep", "recommended_cut", "reason"}),
        }
        detail_keys: set[tuple[str, str]] = set()
        for kind, (field, required) in detail_specs.items():
            collection = value[field]
            if not isinstance(collection, list):
                raise ValueError(f"{field} must be a list")
            for raw_detail in collection:
                detail = _mapping(raw_detail, field)
                _required(detail, required, field)
                detail_id = str(detail["id"]); key = (detail_id, kind)
                if not detail_id or key in detail_keys:
                    raise ValueError("duplicate or empty editorial detail id")
                detail_keys.add(key)
                if kind == "pause":
                    numbers = [float(detail[name]) for name in ("start_s", "end_s", "duration_s")]
                    if any(not math.isfinite(number) for number in numbers) or numbers[0] < 0 or numbers[1] <= numbers[0] or abs((numbers[1] - numbers[0]) - numbers[2]) > 1e-4:
                        raise ValueError("invalid pause candidate")
                elif kind == "repetition":
                    utterance_ids = detail["utterance_ids"]; similarity_value = float(detail["similarity"])
                    if not isinstance(utterance_ids, list) or len(utterance_ids) != 2 or len(set(utterance_ids)) != 2 or not math.isfinite(similarity_value) or not 0 <= similarity_value <= 1:
                        raise ValueError("invalid repetition candidate")
                else:
                    utterance_ids = detail["utterance_ids"]; cuts = detail["recommended_cut"]
                    if not isinstance(utterance_ids, list) or len(utterance_ids) < 2 or not isinstance(cuts, list) or detail["recommended_keep"] not in utterance_ids or not set(cuts).issubset(utterance_ids) or detail["recommended_keep"] in cuts:
                        raise ValueError("invalid take candidate")
        candidates = value["candidates"]
        if not isinstance(candidates, list):
            raise ValueError("editorial candidates must be a list")
        ids: set[str] = set(); flat_keys: set[tuple[str, str]] = set(); parsed = []
        for raw_candidate in candidates:
            candidate = _mapping(raw_candidate, "editorial candidate")
            _required(candidate, {"id", "kind", "decision"}, "editorial candidate")
            candidate_id = str(candidate["id"]); kind = str(candidate["kind"]); key = (candidate_id, kind)
            if not candidate_id or candidate_id in ids or kind not in detail_specs or candidate["decision"] != "REVIEW":
                raise ValueError("invalid editorial candidate")
            ids.add(candidate_id); flat_keys.add(key); parsed.append(candidate)
        if flat_keys != detail_keys:
            raise ValueError("editorial candidate collections are inconsistent")
        expected = "CANDIDATES_PROPOSED" if parsed else "NO_CANDIDATES"
        if value["verdict"] != expected:
            raise ValueError("editorial verdict does not match candidates")
        return cls(str(value["source_transcript_sha256"]), tuple(parsed))


@dataclass(frozen=True)
class CrossSegmentTakeAnalysis:
    input_bindings: tuple[Mapping[str, Any], ...]
    groups: tuple[Mapping[str, Any], ...]

    @classmethod
    def parse(cls, raw: Any) -> "CrossSegmentTakeAnalysis":
        value = _mapping(raw, "cross-segment take analysis")
        _required(value, {
            "schema_version", "kind", "worker_version", "input_bindings", "thresholds",
            "verdict", "groups", "uncertain_matches", "candidates", "auto_apply",
        }, "cross-segment take analysis")
        if value["schema_version"] != 1 or value["kind"] != "cross-segment-take-analysis" or value["auto_apply"] is not False:
            raise ValueError("invalid cross-segment take analysis version, kind, or auto-apply policy")
        thresholds = _mapping(value["thresholds"], "cross-segment thresholds")
        similarity = float(thresholds.get("similarity", float("nan")))
        recommendation = float(thresholds.get("recommendation", float("nan")))
        min_tokens = thresholds.get("min_tokens")
        if (
            not math.isfinite(similarity) or not math.isfinite(recommendation)
            or not 0 <= similarity <= recommendation <= 1
            or isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens < 1
        ):
            raise ValueError("invalid cross-segment take thresholds")
        raw_bindings = value["input_bindings"]
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise ValueError("cross-segment analysis requires source bindings")
        bindings: list[Mapping[str, Any]] = []
        bound_segments: set[str] = set()
        for raw_binding in raw_bindings:
            binding = _mapping(raw_binding, "cross-segment source binding")
            _required(binding, {"segment_id", "source_transcript_sha256", "utterance_ids"}, "cross-segment source binding")
            segment_id = str(binding["segment_id"])
            utterance_ids = binding["utterance_ids"]
            if (
                not segment_id or segment_id in bound_segments
                or not str(binding["source_transcript_sha256"]).startswith("sha256:")
                or not isinstance(utterance_ids, list) or len(set(utterance_ids)) != len(utterance_ids)
                or any(not isinstance(item, str) or not item for item in utterance_ids)
            ):
                raise ValueError("invalid or duplicate cross-segment source binding")
            bound_segments.add(segment_id); bindings.append(binding)
        allowed_refs = {
            (str(binding["segment_id"]), utterance_id)
            for binding in bindings for utterance_id in binding["utterance_ids"]
        }
        raw_groups = value["groups"]
        raw_candidates = value["candidates"]
        if not isinstance(raw_groups, list) or not isinstance(raw_candidates, list) or not isinstance(value["uncertain_matches"], list):
            raise ValueError("cross-segment candidate collections must be lists")
        groups: list[Mapping[str, Any]] = []
        group_ids: set[str] = set()
        for raw_group in raw_groups:
            group = _mapping(raw_group, "cross-segment take group")
            _required(group, {
                "id", "members", "minimum_similarity", "recommended_keep", "recommended_cut",
                "recommendation_policy", "decision",
            }, "cross-segment take group")
            group_id = str(group["id"])
            members = group["members"]
            cuts = group["recommended_cut"]
            keep = group["recommended_keep"]
            confidence = float(group["minimum_similarity"])
            if (
                not group_id or group_id in group_ids or group["decision"] != "REVIEW"
                or not math.isfinite(confidence) or not recommendation <= confidence <= 1
                or group["recommendation_policy"] != "latest-complete-take-high-confidence"
            ):
                raise ValueError("invalid cross-segment take recommendation")
            if not isinstance(members, list) or len(members) < 2 or not isinstance(cuts, list) or not isinstance(keep, dict):
                raise ValueError("invalid cross-segment take members")
            member_keys = {(str(item.get("segment_id")), str(item.get("utterance_id"))) for item in members if isinstance(item, dict)}
            keep_key = (str(keep.get("segment_id")), str(keep.get("utterance_id")))
            cut_keys = {(str(item.get("segment_id")), str(item.get("utterance_id"))) for item in cuts if isinstance(item, dict)}
            if (
                len(member_keys) != len(members) or len({item[0] for item in member_keys}) != len(members)
                or not member_keys.issubset(allowed_refs)
                or keep_key not in member_keys or keep_key != (str(members[-1].get("segment_id")), str(members[-1].get("utterance_id")))
                or cut_keys != member_keys - {keep_key}
            ):
                raise ValueError("cross-segment keep/cut recommendation is inconsistent")
            group_ids.add(group_id); groups.append(group)
        uncertain_ids: set[str] = set()
        for raw_uncertain in value["uncertain_matches"]:
            uncertain = _mapping(raw_uncertain, "uncertain cross-segment match")
            _required(uncertain, {"id", "members", "minimum_similarity", "decision"}, "uncertain cross-segment match")
            uncertain_id = str(uncertain["id"]); uncertain_members = uncertain["members"]
            uncertain_score = float(uncertain["minimum_similarity"]); prohibited = {"recommended_keep", "recommended_cut"} & set(uncertain)
            if (
                not uncertain_id or uncertain_id in uncertain_ids or uncertain["decision"] != "REVIEW" or prohibited
                or not similarity <= uncertain_score < recommendation or not isinstance(uncertain_members, list)
            ):
                raise ValueError("invalid uncertain cross-segment match")
            uncertain_refs = {(str(item.get("segment_id")), str(item.get("utterance_id"))) for item in uncertain_members if isinstance(item, dict)}
            if len(uncertain_refs) != len(uncertain_members) or len({item[0] for item in uncertain_refs}) < 2 or not uncertain_refs.issubset(allowed_refs):
                raise ValueError("invalid uncertain cross-segment members")
            uncertain_ids.add(uncertain_id)
        if uncertain_ids & group_ids:
            raise ValueError("cross-segment group ids must be unique")
        candidate_ids = set()
        for raw_candidate in raw_candidates:
            candidate = _mapping(raw_candidate, "cross-segment candidate")
            _required(candidate, {"id", "kind", "decision"}, "cross-segment candidate")
            if candidate["kind"] != "cross-segment-take" or candidate["decision"] != "REVIEW":
                raise ValueError("cross-segment candidates may only request review")
            candidate_ids.add(str(candidate["id"]))
        if len(candidate_ids) != len(raw_candidates) or candidate_ids != group_ids or value["verdict"] != ("CANDIDATES_PROPOSED" if groups else "NO_CANDIDATES"):
            raise ValueError("cross-segment verdict or candidate index is inconsistent")
        return cls(tuple(bindings), tuple(groups))


@dataclass(frozen=True)
class TranscriptVerification:
    verdict: str
    provider: str
    provider_version: str
    thresholds: Mapping[str, Any]
    metrics: Mapping[str, Any]
    bindings: Mapping[str, Any]

    @classmethod
    def parse(cls, raw: Any) -> "TranscriptVerification":
        value = _mapping(raw, "transcript verification")
        fields = {"schema_version", "verdict", "provider", "provider_version", "thresholds", "metrics", "bindings"}
        _required(value, fields, "transcript verification")
        if value["schema_version"] != 1 or value["verdict"] != "PASS":
            raise ValueError("transcript verification did not pass")
        if value["provider"] in {"synthetic", "synthetic-render-asr", "sidecar"}:
            raise ValueError("test/sidecar providers cannot produce production verification evidence")
        return cls(str(value["verdict"]), str(value["provider"]), str(value["provider_version"]), _mapping(value["thresholds"], "verification thresholds"), _mapping(value["metrics"], "verification metrics"), _mapping(value["bindings"], "verification bindings"))


@dataclass(frozen=True)
class QcReport:
    verdict: str
    bindings: Mapping[str, Any]
    technical: Mapping[str, Any]
    frame_integrity: Mapping[str, Any]
    layout_policy: Mapping[str, Any]
    visual_render_policy: Mapping[str, Any] | None = None
    visual_audit: Mapping[str, Any] | None = None

    @classmethod
    def parse(cls, raw: Any) -> "QcReport":
        value = _mapping(raw, "QC report")
        fields = {"schema_version", "verdict", "bindings", "technical", "frame_integrity", "layout_policy"}
        _required(value, fields, "QC report")
        schema = value["schema_version"]
        if schema not in {2, 3, 4} or value["verdict"] != "PASS":
            raise ValueError("QC report or one of its components did not pass")
        components = [value["technical"], value["frame_integrity"], value["layout_policy"]]
        if "audio_policy" in value:
            components.append(value["audio_policy"])
        visual = value.get("visual_render_policy")
        audit = value.get("visual_audit")
        if schema >= 3:
            if visual is None:
                raise ValueError("schema 3+ QC requires visual_render_policy")
            components.append(visual)
        elif visual is not None:
            components.append(visual)
        if schema >= 4:
            if audit is None:
                raise ValueError("schema 4 QC requires visual_audit (random + per-MOTION probes)")
            components.append(audit)
        elif audit is not None:
            components.append(audit)
        if any(_mapping(item, "QC component").get("verdict") != "PASS" for item in components):
            raise ValueError("QC report or one of its components did not pass")
        return cls(
            str(value["verdict"]),
            _mapping(value["bindings"], "QC bindings"),
            _mapping(value["technical"], "QC component"),
            _mapping(value["frame_integrity"], "QC component"),
            _mapping(value["layout_policy"], "QC component"),
            _mapping(visual, "QC component") if visual is not None else None,
            _mapping(audit, "QC component") if audit is not None else None,
        )


PARSERS: dict[str, Callable[[Any], Any]] = {
    "editorial-analysis": EditorialAnalysis.parse,
    "cross-segment-take-analysis": CrossSegmentTakeAnalysis.parse,
    "sync-report": SyncReport.parse,
    "transcript-verification": TranscriptVerification.parse,
    "segment-qc": QcReport.parse,
    "final-qc": QcReport.parse,
}


def parse_contract(kind: str, raw: Any) -> Any:
    try:
        parser = PARSERS[kind]
    except KeyError as exc:
        raise ValueError(f"no runtime contract registered for {kind}") from exc
    return parser(raw)

