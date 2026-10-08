"""Generate an auditable draft control profile from a powder workspace."""

from __future__ import annotations

from typing import Any

from .control_profiles import normalize_target_profiles, normalize_target_rate_bands


def build_candidate_control_profile(workspace: dict[str, Any]) -> dict[str, Any]:
    """Build a draft; measured-data gaps become warnings, never hidden defaults."""
    powder_id = str(workspace.get("powder_id", "")).strip()
    powder_name = str(workspace.get("powder_name", "")).strip()
    if not powder_id or not powder_name:
        raise ValueError("workspace must contain powder_id and powder_name")
    profiles = normalize_target_profiles(workspace.get("recommended_profiles", {}))
    target_rate_bands = normalize_target_rate_bands(
        workspace.get("target_rate_bands", [])
    )
    controller = workspace.get("recommended_controller")
    if not isinstance(controller, dict):
        raise ValueError("workspace must contain recommended_controller")

    warnings: list[str] = []
    scan_grid = workspace.get("scan_grid", [])
    pending_count = sum(1 for point in scan_grid if point.get("status") == "pending")
    if pending_count:
        warnings.append(f"{pending_count} scan points are still pending")
    for region_name in ("safe_coarse_region", "safe_fine_region"):
        region = workspace.get(region_name, {})
        if region.get("confidence") in (None, "low"):
            warnings.append(f"{region_name} has low or unspecified confidence")
    if not workspace.get("path_dependency", {}).get("notes"):
        warnings.append("transition/path-dependency evidence is missing")
    tail = workspace.get("tail_behavior", {})
    if not isinstance(tail.get("mean_tail_mg"), (int, float)):
        warnings.append("measured stop-tail evidence is missing")

    return {
        "schema_version": 1,
        "powder_id": powder_id,
        "powder_name": powder_name,
        "status": "draft",
        "recommended_preset_id": workspace.get("recommended_preset_id", ""),
        "recommended_controller": dict(controller),
        "target_profiles": {str(mass): values for mass, values in profiles.items()},
        "target_rate_bands": target_rate_bands,
        "generation_warnings": warnings,
        "source_workspace_updated_at": workspace.get("updated_at"),
    }
