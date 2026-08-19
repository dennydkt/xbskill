#!/usr/bin/env python3
"""Fail-fast checks for the public xbskill repository."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "LICENSE",
    "LICENSES/AGPL-3.0-or-later.txt",
    "LICENSES/CC-BY-NC-SA-4.0.txt",
    "NOTICE.md",
    "ATTRIBUTION.md",
    "PROVENANCE.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "LICENSE-ENFORCEMENT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CITATION.cff",
    "README.md",
    "VERSION",
    "UPDATE.json",
    "BUILD-PROVENANCE.json",
    "RIGHTS-AUDIT.json",
    "skills/xbskill/VERSION",
    "skills/xbskill/manifest.json",
}
FORBIDDEN_PATH_PARTS = {"internal", "evaluation", "memory"}
FORBIDDEN_TEXT = re.compile(
    r"不是.*而是|不在于|不需要.*需要|不会.*会|真正的|与其说"
)
FORBIDDEN_RELEASE_CONTEXT = re.compile(
    r"C:\\Users|/home/|国药|sinopharm|数据中台|xb-iteration|"
    r"internal-skills|本轮对话|主会话|四家工具",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".json", ".cff"}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    missing = sorted(path for path in REQUIRED if not (ROOT / path).is_file())
    if missing:
        fail(f"missing required public files: {missing}")

    root_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    skill_version = (ROOT / "skills/xbskill/VERSION").read_text(
        encoding="utf-8"
    ).strip()
    manifest = json.loads(
        (ROOT / "skills/xbskill/manifest.json").read_text(encoding="utf-8")
    )
    update = json.loads((ROOT / "UPDATE.json").read_text(encoding="utf-8"))
    build = json.loads(
        (ROOT / "BUILD-PROVENANCE.json").read_text(encoding="utf-8")
    )
    rights = json.loads((ROOT / "RIGHTS-AUDIT.json").read_text(encoding="utf-8"))
    versions = {
        "root VERSION": root_version,
        "skill VERSION": skill_version,
        "manifest": str(manifest.get("version", "")),
        "UPDATE.json": str(update.get("version", "")),
    }
    if len(set(versions.values())) != 1:
        fail(f"version mismatch: {versions}")
    if build.get("version") != root_version:
        fail("BUILD-PROVENANCE.json version does not match VERSION")
    if not re.fullmatch(r"[0-9a-f]{40}", str(build.get("source_commit", ""))):
        fail("BUILD-PROVENANCE.json has no immutable source commit")
    if rights.get("record_type") != "ExactTextOverlapAudit":
        fail("RIGHTS-AUDIT.json has an unknown record type")
    if rights.get("overlap_count") != 0:
        fail("RIGHTS-AUDIT.json contains unresolved exact long-text overlap")
    if not re.fullmatch(
        r"[0-9a-f]{64}", str(rights.get("derived_tree_sha256", ""))
    ):
        fail("RIGHTS-AUDIT.json has no derived tree digest")

    skill_dirs = sorted(
        path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")
    )
    if len(skill_dirs) != 35:
        fail(f"expected 35 public skills, found {len(skill_dirs)}")

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if FORBIDDEN_PATH_PARTS.intersection(relative.parts):
            fail(f"private source path leaked into release: {relative}")
        if path.name == "LOCAL-LESSONS.md":
            fail(f"local-only file leaked into release: {relative}")
        if relative.parts and relative.parts[0] == "skills":
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != "LICENSE":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = FORBIDDEN_TEXT.search(text)
        if match:
            fail(f"forbidden writing pattern in {relative}: {match.group(0)!r}")
        context_match = FORBIDDEN_RELEASE_CONTEXT.search(text)
        if context_match:
            fail(
                f"private release context leaked into {relative}: "
                f"{context_match.group(0)!r}"
            )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = "npx -y skills add dennydkt/xbskill -g --all"
    if install not in readme:
        fail("README is missing the stable ordinary-user install command")

    license_map = (ROOT / "LICENSE").read_text(encoding="utf-8")
    for marker in ("AGPL-3.0-or-later", "CC BY-NC-SA 4.0", "TRADEMARKS.md"):
        if marker not in license_map:
            fail(f"LICENSE mapping is missing {marker}")

    print(
        f"VALID release governance: version={root_version} "
        f"skills={len(skill_dirs)} required_files={len(REQUIRED)}"
    )


if __name__ == "__main__":
    main()
