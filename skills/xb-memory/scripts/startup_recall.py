#!/usr/bin/env python3
"""Query startup memory without writing archives or bypassing retention rules."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import Any
from memory_ontology import (OntologyError, project_memory_root, query_memory, require,
                             pretty_json, assertion_relevance, load_store, validate_store,
                             validate_entity, validate_assertion, validate_source_ref, load_registry, load_json)
import topic_coordinates as topics


def check_memory(project_root: Path) -> dict[str, Any]:
    """Diagnose existing data before first use; never create or repair a store."""
    root = project_memory_root(project_root)
    require(root.is_relative_to(project_root.expanduser().resolve()), "E_PATH: memory root escapes project")
    if not root.exists():
        return {"status": "no_archive", "checked": True, "issues": []}
    require(root.is_dir(), 'E_PATH: memory root must be a directory')
    if not (root / 'ontology').exists():
        return {"status": "legacy_review_required", "checked": True, "issues": []}
    for name in ('entities.json', 'assertions.json', 'index.json', 'meta.json'):
        require((root / 'ontology' / name).resolve().is_relative_to(root),
                'E_PATH: ontology store escapes memory root')
    issues = []

    def inspect(location, action):
        try:
            action()
        except (OntologyError, OSError, KeyError, TypeError, ValueError) as exc:
            issues.append({"location": location, "error": str(exc)})

    inspect('ontology/index.json + meta.json', lambda: validate_store(root))
    try:
        entities, assertions = load_store(root)
        entity_map = {e['entity_id']: e for e in entities['entities']}
        registry = load_registry()
        seen_entities, seen_assertions, checked_sessions = set(), set(), set()
        for group, values in [('entities.json', entities['entities']), ('assertions.json', assertions['assertions'])]:
            for item in values:
                item_id = item.get('entity_id', item.get('assertion_id', '?'))
                location = f'ontology/{group}:{item_id}'
                refs = item.get('source_refs', [])
                first_session = refs[0].get('session_id', '') if refs else ''
                minimal = dict(item, source_refs=refs[:1])
                if group == 'entities.json':
                    inspect(location, lambda: validate_entity(minimal, first_session, seen_entities))
                else:
                    inspect(location, lambda: validate_assertion(item, first_session, {}, entity_map,
                                                                 seen_assertions, registry, True))
                for index, ref in enumerate(refs):
                    inspect(f'{location}.source_refs[{index}]',
                            lambda: validate_source_ref(ref, ref.get('session_id', ''), location))
                    session_id = ref.get('session_id')
                    if session_id and session_id not in checked_sessions:
                        checked_sessions.add(session_id)
                        path = (root / 'sessions' / session_id / 'session.md').resolve()
                        inspect(f'sessions/{session_id}/session.md',
                                lambda: require(path.is_relative_to(root) and path.is_file(),
                                                'E_SOURCE_MISSING: source session missing or outside memory root'))
    except (OntologyError, OSError, KeyError, TypeError, ValueError) as exc:
        issues.append({"location": "ontology", "error": str(exc)})
    return {"status": "healthy" if not issues else "repair_required", "checked": True,
            "issues": issues, "write_performed": False}

def recall_memory(project_root: Path, task: str) -> dict[str, Any]:
    """Read-only startup query; never turn a session summary into reusable facts."""
    require(bool(task.strip()), "E_QUERY_SCHEMA: task missing")
    memory_root = project_memory_root(project_root)
    require(memory_root.is_relative_to(project_root.expanduser().resolve()),
            "E_PATH: memory root escapes project")
    if not memory_root.exists():
        return {"status": "no_archive", "query_executed": True, "task": task,
                "assertions": [], "source_sessions": [], "open_items": [], "material_paths": []}
    require(memory_root.is_dir(), f"E_PATH: memory root is not a directory: {memory_root}")
    health = check_memory(project_root)
    require(health['status'] != 'repair_required',
            'E_MEMORY_HEALTH: existing archive needs repair; run startup_recall.py --check for file and field coordinates')
    if not (memory_root / "ontology").exists():
        # Filenames only: raw summaries/classification may contain session-only data.
        sessions = memory_root / "sessions"
        candidates = []
        if sessions.is_dir():
            require(sessions.resolve().is_relative_to(memory_root), "E_PATH: sessions escape memory root")
            candidates = [str(p.resolve()) for p in sorted(sessions.glob("*/session.md"))
                          if p.resolve().is_relative_to(memory_root)]
        return {"status": "legacy_review_required", "query_executed": True, "task": task,
                "assertions": [], "source_sessions": [], "open_items": [], "material_paths": [],
                "legacy_candidates": candidates,
                "notice": "No ontology store; review only task-related legacy sources under the existing sensitivity rules. Do not claim no_match or auto-migrate."}
    request = {"schema_version": 1, "request_id": "startup-recall", "task": task,
               "entity_ids": [], "entity_types": [], "predicates": [], "as_of": None,
               "max_assertions": 5, "include_candidates": True, "include_disputed": True,
               "include_restricted": False, "authorized_sensitive_read": False}
    packet = query_memory(memory_root, request)
    # Open work and material coordinates have their own budget, independent of progress.md.
    supplementary = query_memory(memory_root, dict(request, max_assertions=50))
    supplementary_entities = {e["entity_id"]: e for e in supplementary["entities"]}
    open_items = [a for a in supplementary["assertions"]
                  if a["predicate"] == "has_status"
                  and a.get("qualifiers", {}).get("memory_kind") == "open_item"
                  and assertion_relevance(a, supplementary_entities, request) > 0
                  and str(a["object"].get("value", "")).lower() in {"open", "pending", "待验证", "待反馈"}]
    path_packet = supplementary
    material_paths = []
    for assertion in path_packet["assertions"]:
        value = assertion.get("qualifiers", {}).get("material_path")
        if not value:
            continue
        require(isinstance(value, str), "E_MATERIAL_PATH: stored material_path must be a string")
        path = Path(value).expanduser()
        require(path.is_absolute(), "E_MATERIAL_PATH: stored material_path must be absolute")
        material_paths.append({"path": str(path), "exists": path.exists(),
                               "assertion_id": assertion["assertion_id"],
                               "observed_at": assertion["observed_at"],
                               "source_refs": assertion["source_refs"]})
    sources = []
    seen = set()
    for assertion in [*packet["assertions"], *open_items]:
        for ref in assertion["source_refs"]:
            session_id = ref["session_id"]
            if session_id in seen:
                continue
            seen.add(session_id)
            path = (memory_root / "sessions" / session_id / "session.md").resolve()
            require(path.is_relative_to(memory_root), "E_PATH: source session escapes memory root")
            require(path.is_file(), f"E_SOURCE_MISSING: source session missing: {path}")
            sources.append({"session_id": session_id, "date": session_id[:10], "path": str(path)})
    packet.update(query_executed=True, source_sessions=sources, open_items=open_items,
                  material_paths=material_paths, supplementary_omissions={
                      "open_items": supplementary["omissions"], "material_paths": path_packet["omissions"]})
    return packet


def locate_topic(project_root, task, navigation=None, workspace_root=None):
    """Resolve only evidenced coordinates, in local → navigation → index order."""
    project_root = topics.path_of(str(project_root))
    if workspace_root is not None:
        workspace_root = topics.path_of(str(workspace_root))
    local = recall_memory(project_root, task)
    trace = [{"step": "project_memory", "status": local["status"]}]
    root = project_memory_root(project_root)
    rows = []
    if local["status"] in {"matched", "no_match"}:
        entities, assertions = load_store(root)
        index = load_json(root / "ontology/index.json")
        rows = topics.ontology_rows(entities["entities"], assertions["assertions"], index["effective_assertion_ids"])
    vetoes = {topics.identity(row) for row in topics.latest(rows) if topics.excluded(row, task)}
    matches = topics.match(rows, task)
    if not matches and local["material_paths"]:
        # Older archives can also carry exact topic names and paths. Relevance
        # scores by themselves are insufficient to identify a project.
        entities = {e["entity_id"]: e for e in local.get("entities", [])}
        paths = {p["assertion_id"]: p for p in local["material_paths"]}
        legacy = []
        for assertion in local.get("assertions", []):
            entity = entities.get(assertion["subject_id"], {})
            path = paths.get(assertion["assertion_id"])
            if (path and entity.get("status") == "active" and entity.get("sensitivity") == "normal"
                    and assertion["lifecycle"] == "active" and assertion["retention"] == "long_term"
                    and assertion["qualifiers"].get("memory_kind") != "topic_coordinates"
                    and entity.get("entity_type") in {"project", "artifact", "work_item"}):
                legacy.append(dict(canonical_name=entity["canonical_name"], aliases=entity["aliases"],
                                   material_path=path["path"], status=None, exclusions=[],
                                   registered_on=path["observed_at"][:10],
                                   source_session=path["source_refs"][0]["session_id"]))
        matches = topics.match([row for row in legacy if topics.identity(row) not in vetoes], task)
    if matches and all(row["material_path"] is None for row in matches):
        # An incomplete local registration should not hide a later coordinate.
        incomplete, matches = matches, []
    else:
        incomplete = []
    anchor = workspace_root or project_root
    if not matches:
        if navigation is None:
            trace.append({"step": "navigation", "status": "not_configured"})
        else:
            navigation = topics.path_of(str(navigation))
            topics.require(navigation.suffix.lower() == ".md", "E_TOPIC_NAVIGATION: expected .md file")
            _, rows = topics.read_navigation(navigation)
            vetoes.update(topics.identity(row) for row in topics.latest(rows) if topics.excluded(row, task))
            matches = topics.match([row for row in rows if topics.identity(row) not in vetoes], task)
            trace.append({"step": "navigation", "status": "matched" if matches else "no_match",
                          "path": str(navigation)})
    if not matches:
        index = topics.configured_index(anchor)
        if index is None:
            trace.append({"step": "topic_index", "status": "not_configured"})
        else:
            matches = topics.match([row for row in topics.read_index(index) if topics.identity(row) not in vetoes], task)
            trace.append({"step": "topic_index", "status": "matched" if matches else "no_match",
                          "path": str(index)})
    matches = topics.describe(matches or incomplete)
    if len(matches) != 1:
        status = "ambiguous" if matches else "ask_location"
    elif not matches[0]["material_exists"]:
        status = "material_missing" if matches[0]["material_path"] else "material_unrecorded"
    else:
        status = "matched"
    return {"status": status, "query_executed": True, "project_root": str(project_root.resolve()),
            "task": task, "steps": trace, "topics": matches}


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--task')
    parser.add_argument('--check', action='store_true', help='Read-only first-use archive health check')
    parser.add_argument('--locate', action='store_true', help='Locate a topic before file exploration')
    parser.add_argument('--workspace-root', help='Authorized anchor holding the topic index setting')
    parser.add_argument('--navigation', help='Absolute path of an existing authorized Markdown navigation')
    args = parser.parse_args()
    try:
        require(args.check or bool(args.task), 'E_QUERY_SCHEMA: --task or --check required')
        require(not (args.check and args.locate), 'E_QUERY_SCHEMA: choose --check or --locate')
        require(args.locate or not (args.navigation or args.workspace_root),
                'E_QUERY_SCHEMA: topic locations require --locate')
        project = Path(args.project_root)
        if args.check:
            result = check_memory(project)
        elif args.locate:
            workspace = topics.path_of(args.workspace_root) if args.workspace_root else None
            result = locate_topic(project, args.task, args.navigation, workspace)
        else:
            result = recall_memory(project, args.task)
            result['project_root'] = str(project.resolve())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(pretty_json(result), end='')
    return 2 if result['status'] == 'repair_required' else 0

if __name__ == '__main__':
    raise SystemExit(main())
