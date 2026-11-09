"""Opt-in local topic coordinates for save and startup."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import html
import importlib.util
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

FIELDS = ("canonical_name", "aliases", "material_path", "status", "exclusions")
MARKER = "<!-- xbskill-topic "
LIMIT = 2_000_000


class TopicError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise TopicError(message)


def path_of(value, protected=True):
    require(isinstance(value, str) and Path(value).is_absolute()
            and not value.replace("\\", "/").startswith("//"), "E_TOPIC_PATH: local absolute path required")
    path = Path(value)
    if protected:
        require(path == path.resolve() and not path.is_symlink(),
                f"E_TOPIC_PATH: linked or noncanonical path: {path}")
        require(not any(p.casefold() in {".codex", ".claude", ".kimi", ".kimi_openclaw", ".zcode", "doubao"}
                        for p in path.parts),
                f"E_TOPIC_PATH: private tool path: {path}")
    return path


def read_text(path, *, keep_bom=False):
    try:
        with path.open("rb") as stream:
            data = stream.read(LIMIT + 1)
        require(len(data) <= LIMIT, f"E_TOPIC_READ: file exceeds {LIMIT} bytes: {path}")
        return data.decode("utf-8" if keep_bom else "utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise TopicError(f"E_TOPIC_READ: {path}: {exc}") from exc


def text(value, field):
    require(isinstance(value, str) and value == value.strip() and 0 < len(value) <= 400
            and all(ord(c) >= 32 for c in value), f"E_TOPIC_FIELD: invalid {field}")
    require(not re.search(r"-----BEGIN .*PRIVATE KEY-----|\b(?:sk|ghp|github_pat)_[\w-]{20,}\b", value),
            f"E_TOPIC_SECRET: credential pattern in {field}")
    return value


def coordinates(raw):
    require(isinstance(raw, dict) and set(raw) == set(FIELDS), "E_TOPIC_FIELD: invalid coordinates")
    result = {"canonical_name": text(raw["canonical_name"], "canonical_name")}
    for field in ("status", "material_path"):
        result[field] = None if raw[field] is None else text(raw[field], field)
    if result["material_path"]:
        path_of(result["material_path"], protected=False)
    for field in ("aliases", "exclusions"):
        require(isinstance(raw[field], list) and len(raw[field]) <= 20, f"E_TOPIC_FIELD: invalid {field}")
        result[field] = list(dict.fromkeys(text(value, field) for value in raw[field]))
    return result


def normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def identity(row):
    return normalized(row["canonical_name"]), os.path.normcase(row["material_path"] or "")


def topic_key(row):
    return hashlib.sha256(repr(identity(row)).encode()).hexdigest()[:16]


def has_evidence(body, value, is_path):
    if not is_path:
        return value in body
    # A substring of a longer filename or a parent of the quoted path is not evidence.
    escaped = re.escape(value)
    quoted = r"([\"'\x60])" + escaped + r"\1"
    complete_line = r"(?<![a-zA-Z0-9_./\\])" + escaped + r"[^\S\r\n]*$"
    return re.search(quoted + "|" + complete_line, body, re.MULTILINE) is not None


def confirmation(messages, turn, prompt_label, preview_fields, accepted):
    preview, response = messages.get(turn - 1, {}), messages.get(turn, {})
    require(preview.get("role") == "assistant" and prompt_label in preview["content"]
            and all(has_evidence(preview["content"], value, Path(value).is_absolute())
                    for value in preview_fields),
            f"E_TOPIC_AUTH: review turn must name the approved {prompt_label}")
    answer = response.get("content", "").strip().strip("。.!！")
    require(response.get("role") == "user" and answer in accepted,
            f"E_TOPIC_AUTH: explicit response missing for {prompt_label}")


def register(bundle):
    raw = bundle["topic_registration"]
    require(bundle["schema_version"] == 2 and isinstance(raw, dict), "E_TOPIC_SCHEMA: schema 2 required")
    row = coordinates(raw.get("coordinates"))
    require(raw.get("confirmed_fields") == sorted(FIELDS) and raw.get("normal_coordinates_confirmed") is True,
            "E_TOPIC_AUTH: confirm each field and non-sensitive coordinate storage")
    turn = raw.get("confirmation_turn")
    messages = {m["turn"]: m for m in bundle["transcript"]}
    user_messages = {n: m["content"] for n, m in messages.items() if m["role"] == "user"}
    require(type(turn) is int and turn in user_messages, "E_TOPIC_AUTH: current user confirmation required")
    sources = raw.get("sources", [])
    require(isinstance(sources, list) and len(sources) <= 20, "E_TOPIC_SOURCE: too many selected files")
    require(raw.get("mode") in {"import", "save"}, "E_TOPIC_SCHEMA: mode must be import or save")
    require(sources or raw["mode"] != "import", "E_TOPIC_SOURCE: select external source files")
    docs = []
    for source in sources:
        require(isinstance(source, dict) and set(source) == {"root", "file"},
                "E_TOPIC_SOURCE: selected root and file required")
        root, path = (path_of(source[k]) for k in ("root", "file"))
        require(path == root or (root.is_dir() and path.is_relative_to(root)),
                f"E_TOPIC_SOURCE: file outside selected input: {path}")
        require(path.is_file(), f"E_TOPIC_SOURCE: selected source file missing or unreadable: {path}")
        docs.append((path, read_text(path).splitlines()))

    values = list(filter(None, [row["canonical_name"], *row["aliases"], row["material_path"],
                                row["status"], *row["exclusions"]]))
    confirmation(messages, turn, "专题坐标", values, {"确认", "同意", "确认专题坐标"})
    evidence = {}
    for value in values:
        found = next(({"turn": n} for n, body in user_messages.items()
                      if n <= turn and has_evidence(body, value, value == row["material_path"])), None)
        if found is None:
            found = next(({"file": str(path), "line": n} for path, lines in docs
                          for n, body in enumerate(lines, 1)
                          if has_evidence(body, value, value == row["material_path"])), None)
        require(found is not None, f"E_TOPIC_EVIDENCE: missing verbatim evidence for {value!r}")
        evidence[value] = found

    confirmations = set()
    for kind, decisions in (("index", {"write", "skip"}), ("navigation", {"write", "offer", "decline"})):
        action = raw.get(kind)
        if action is None:
            continue
        require(isinstance(action, dict) and action.get("decision") in decisions,
                f"E_TOPIC_EFFECT: invalid {kind} decision")
        if action["decision"] == "skip":
            continue
        destination = path_of(action.get("path"))
        if action["decision"] in {"write", "decline"}:
            authorization = action.get("confirmation_turn")
            require(action.get("user_confirmed") is True and type(authorization) is int
                    and authorization in user_messages and authorization > turn and authorization not in confirmations,
                    f"E_TOPIC_AUTH: {kind} requires separate user confirmation")
            confirmations.add(authorization)
            label = "专题索引" if kind == "index" else "专题导航"
            accepted = ({"同意", "确认写入", f"同意写入{label}"} if action["decision"] == "write"
                        else {"拒绝", "不同意", "不写", "不用了", f"不写{label}", f"不同意写入{label}"})
            confirmation(messages, authorization, label, [str(destination)], accepted)
        if kind == "navigation":
            require(destination.suffix.lower() == ".md", "E_TOPIC_NAVIGATION: expected .md file")
        elif action["decision"] == "write":
            anchor = path_of(action.get("config_root"))
            require(configured_index(anchor) == destination,
                    f"E_TOPIC_AUTH: approved index differs from configured path: {destination}")
    return row, evidence, {"session_id": bundle["session_id"], "turn": turn, "role": "user",
                           "excerpt": user_messages[turn].strip()[:280]}


def attach(bundle):
    row, evidence, ref = register(bundle)
    sid = bundle["session_id"]
    delta = bundle["ontology_delta"]
    key = topic_key(row)
    session_key = hashlib.sha256(sid.encode()).hexdigest()[:16]
    entity_id = f"project:topic-{session_key}-{key}"
    scope = "project:topic-coordinates"
    qualifiers = {"memory_kind": "topic_coordinates",
                  "exclusions": json.dumps(row["exclusions"], ensure_ascii=False),
                  "coordinate_sources": json.dumps(evidence, ensure_ascii=False)}
    if row["material_path"]:
        qualifiers["material_path"] = row["material_path"]
    nav = bundle["topic_registration"].get("navigation")
    if nav:
        qualifiers.update(navigation_path=nav["path"], navigation_decision=nav["decision"])
    assertion_key = hashlib.sha256(json.dumps([row, qualifiers, ref, delta["generated_at"]],
                                              sort_keys=True).encode()).hexdigest()[:12]
    delta["entities"].append({"entity_id": entity_id, "entity_type": "project",
                              "canonical_name": row["canonical_name"], "aliases": row["aliases"],
                              "scope": scope, "sensitivity": "normal", "status": "active", "source_refs": [ref]})
    delta["assertions"].append({
        "assertion_id": f"a:topic-{sid}-{key}-{assertion_key}", "subject_id": entity_id, "predicate": "has_status",
        "object": {"kind": "literal", "value": row["status"] or "状态待补充", "value_type": "string"},
        "epistemic_status": "user_decision", "confidence": "high", "lifecycle": "active",
        "retention": "long_term", "sensitivity": "normal", "scope": scope,
        "observed_at": delta["generated_at"], "valid_from": None, "valid_until": None,
        "source_refs": [ref], "reversal": "用户更正专题身份、材料位置或状态。",
        "supersedes": [], "qualifiers": qualifiers})
    return row


def topic_row(entity, assertion):
    fields = assertion["qualifiers"]
    try:
        row = coordinates(dict(canonical_name=entity["canonical_name"], aliases=entity["aliases"],
                               material_path=fields.get("material_path"), status=assertion["object"]["value"],
                               exclusions=json.loads(fields["exclusions"])))
    except (ValueError, KeyError, TypeError) as exc:
        raise TopicError(f"E_TOPIC_ONTOLOGY: {assertion['assertion_id']}: {exc}") from exc
    return dict(row, registered_on=assertion["observed_at"][:10],
                source_session=assertion["source_refs"][0]["session_id"])


def ontology_rows(entities, assertions, effective_ids):
    effective = set(effective_ids)
    by_id = {e["entity_id"]: e for e in entities}
    now = datetime.now(timezone.utc)
    rows = []
    for assertion in sorted(assertions, key=lambda a: (a["observed_at"], a["assertion_id"]), reverse=True):
        if (assertion["assertion_id"] not in effective
                or assertion["qualifiers"].get("memory_kind") != "topic_coordinates"
                or assertion["sensitivity"] != "normal" or assertion["retention"] != "long_term"
                or assertion["lifecycle"] != "active"):
            continue
        entity = by_id[assertion["subject_id"]]
        if entity["sensitivity"] != "normal" or entity["status"] != "active":
            continue
        start, end = (assertion[field] for field in ("valid_from", "valid_until"))
        if ((start and datetime.fromisoformat(start.replace("Z", "+00:00")) > now)
                or (end and datetime.fromisoformat(end.replace("Z", "+00:00")) < now)):
            continue
        rows.append(topic_row(entity, assertion))
    return rows


def card(row, progress, startup_recorded):
    progress = re.sub(r"^## 冷启动提示卡\r?\n\r?\n"
                      r"- 最近登记专题：[^\r\n]*\r?\n- 别名：[^\r\n]*\r?\n"
                      r"- 材料位置：[^\r\n]*\r?\n- 开场查询：[^\r\n]*(?:\r?\n){0,2}", "",
                      progress, count=1, flags=re.MULTILINE)
    heading, _, body = progress.lstrip().partition("\n")
    if not heading.startswith("# "):
        heading, body = "# 工作近况", progress
    return (f"{heading}\n\n## 冷启动提示卡\n\n"
            f"- 最近登记专题：{row['canonical_name']}\n"
            f"- 别名：{'、'.join(row['aliases']) or '待补充'}\n"
            f"- 材料位置：{row['material_path'] or '待补充'}\n"
            f"- 开场查询：{'已记录' if startup_recorded else '本次未提交回执'}\n\n{body.lstrip()}")


def configured_index(anchor):
    path = Path(__file__).resolve().parents[2] / "xb-config/scripts/config_manager.py"
    require(path.is_file(), f"E_TOPIC_CONFIG: missing dependency: {path}")
    spec = importlib.util.spec_from_file_location("xb_topic_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.load_config(anchor).get("topic_index")
    if value is None:
        return None
    require(Path(value["anchor"]) == anchor.resolve(),
            f"E_TOPIC_CONFIG: configuration anchor changed: {anchor}; confirm the index position again")
    return path_of(value["path"])


def entry(raw):
    require(isinstance(raw, dict) and set(raw) == {*FIELDS, "registered_on", "source_session"},
            "invalid topic index entry fields")
    registered_on = text(raw["registered_on"], "registered_on")
    source_session = text(raw["source_session"], "source_session")
    require(date.fromisoformat(registered_on).isoformat() == registered_on, "invalid registration date")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9][a-z0-9-]{0,63}", source_session),
            "invalid source session ID")
    row = coordinates({key: raw[key] for key in FIELDS})
    require(row["material_path"], "indexed coordinates require a complete material path")
    return dict(row, registered_on=registered_on, source_session=source_session)


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate field: {key}")
        result[key] = value
    return result


def read_index(path):
    try:
        raw = json.loads(read_text(path), object_pairs_hook=unique_fields)
        require(type(raw) is dict and set(raw) == {"schema_version", "topics"}
                and type(raw["schema_version"]) is int and raw["schema_version"] == 1
                and type(raw["topics"]) is list,
                "invalid topic index")
        return [entry(row) for row in raw["topics"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise TopicError(f"E_TOPIC_INDEX: {path}: {exc}") from exc


def navigation_lines(body, path):
    """Return visible Markdown lines with offsets into the original document."""
    visible = []
    offset = 0
    fence = None
    for raw in body.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if offset == 0:
            line = line.lstrip("\ufeff")
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if opening and opening[1][0] == fence[0] and len(opening[1]) >= len(fence) and not opening[2].strip():
                fence = None
        elif opening:
            fence = opening[1]
        else:
            visible.append((offset, line))
        offset += len(raw)
    require(fence is None, f"E_TOPIC_NAVIGATION: unclosed code fence: {path}")
    return visible


def read_navigation(path):
    body = read_text(path, keep_bom=True)
    lines = [line for _, line in navigation_lines(body, path)]
    require(any(re.match(r"^#{1,6}\s+\S", row) for row in lines),
            f"E_TOPIC_NAVIGATION: expected existing Markdown headings: {path}")
    rows = []
    for line in lines:
        if line.startswith(MARKER):
            require(line.endswith(" -->"), f"E_TOPIC_NAVIGATION: invalid marker: {path}")
            try:
                rows.append(entry(json.loads(line[len(MARKER):-4], object_pairs_hook=unique_fields)))
            except (ValueError, KeyError, TypeError) as exc:
                raise TopicError(f"E_TOPIC_NAVIGATION: {path}: {exc}") from exc
        elif line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            name = cells[0].strip("* ")
            location = re.search(r"\x60([^\x60]+)\x60", cells[1])
            if name and location and Path(location[1]).is_absolute():
                rows.append(dict(canonical_name=name, aliases=[], material_path=location[1], status=None,
                                 exclusions=[], registered_on=None, source_session=None))
    return body, rows


@contextmanager
def update_lock(path):
    lock = path.with_name(path.name + ".xbskill-lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise TopicError(f"E_TOPIC_LOCK: pending update: {lock}") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def replace_text(path, body, *, expected_navigation=None):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".topic-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        require(len(body.encode("utf-8")) <= LIMIT, f"E_TOPIC_WRITE: file would exceed limit: {path}")
        if expected_navigation is not None:
            require(read_text(path, keep_bom=True) == expected_navigation,
                    f"E_TOPIC_NAVIGATION: file changed during update: {path}")
        os.replace(temporary, path)
        require(read_text(path, keep_bom=True) == body, f"E_TOPIC_VERIFY: {path}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_index(path, row, initialize):
    with update_lock(path):
        rows = [] if initialize and not path.exists() else read_index(path)
        previous = [old for old in rows if identity(old) == identity(row)]
        if any((old["registered_on"], old["source_session"]) >
               (row["registered_on"], row["source_session"]) for old in previous):
            return "newer_registration"
        rows = [old for old in rows if identity(old) != identity(row)] + [row]
        replace_text(path, json.dumps({"schema_version": 1, "topics": rows}, ensure_ascii=False, indent=2) + "\n")
        return "written"


def write_navigation(path, row):
    with update_lock(path):
        body, rows = read_navigation(path)
        if any(identity(old) == identity(row) for old in rows):
            return "already_registered"
        metadata = json.dumps(row, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        name, location, status = map(html.escape, (row["canonical_name"], row["material_path"], row["status"] or "状态待补充"))
        exclusions = html.escape("、".join(row["exclusions"]))
        note = f"。排除相近入口 {exclusions}" if exclusions else ""
        heading = "## xbskill 专题入口"
        block = f"\n\n- **{name}** · {location} · {status}{note}\n{MARKER}{metadata} -->\n"
        newline = "\r\n" if "\r\n" in body else "\n"
        block = block.replace("\n", newline)
        visible = navigation_lines(body, path)
        header = next((offset for offset, line in visible if line.rstrip() == heading), None)
        if header is not None:
            end = next((offset for offset, line in visible if offset > header and re.match(r"^#{1,2}\s+\S", line)),
                       len(body))
            updated = body[:end] + block + (newline + body[end:] if end < len(body) else "")
        else:
            updated = body + newline + newline + heading + block
        replace_text(path, updated, expected_navigation=body)
        return "written"


def apply_effects(raw, row, sid, observed_at, assertions, memory_root):
    result = {}
    saved = dict(row, registered_on=observed_at[:10], source_session=sid)
    for kind in ("index", "navigation"):
        action = raw.get(kind)
        if not action or action["decision"] == "skip":
            continue
        decision = action["decision"]
        try:
            require(row["material_path"], f"E_TOPIC_PATH: {kind} requires an evidenced path")
            if kind == "index":
                path = configured_index(path_of(action.get("config_root")))
                require(path == path_of(action.get("path")), "E_TOPIC_AUTH: configured index changed after approval")
                require(not path.is_relative_to(memory_root) and path.name != "config.json",
                        f"E_TOPIC_PATH: index overlaps project storage: {path}")
                require(all(Path(source["file"]) != path for source in raw.get("sources", [])),
                        f"E_TOPIC_SOURCE: source files are read-only: {path}")
                status = write_index(path, saved, action.get("initialize") is True)
            else:
                path = path_of(action["path"])
                require(not path.is_relative_to(memory_root), f"E_TOPIC_PATH: navigation overlaps project storage: {path}")
                require(all(Path(source["file"]) != path for source in raw.get("sources", [])),
                        f"E_TOPIC_SOURCE: source files are read-only: {path}")
                _, rows = read_navigation(path)
                if any(identity(old) == identity(row) for old in rows):
                    status = "already_registered"
                elif decision == "write":
                    status = write_navigation(path, saved)
                elif decision == "decline":
                    status = "declined"
                else:
                    history = [a for a in assertions if a["subject_id"].endswith(topic_key(row))
                               and a["qualifiers"].get("navigation_path") == str(path)]
                    declines = {a["source_refs"][0]["session_id"] for a in history
                                if a["qualifiers"].get("navigation_decision") == "decline"}
                    retried = any(a["qualifiers"].get("navigation_decision") == "offer"
                                  and min(declines) < a["source_refs"][0]["session_id"] < sid
                                  for a in history) if declines else False
                    status = "suppressed" if sid in declines or len(declines) >= 2 or retried else "offer"
            result[kind] = {"status": status, "path": str(path)}
            if status == "offer":
                result[kind]["coordinates"] = saved
        except (OSError, ValueError) as exc:
            result[kind] = {"status": "error", "error": str(exc)}
    return result


def latest(rows):
    entries = {}
    for row in rows:
        key = identity(row)
        previous = entries.get(key)
        revision = (row.get("registered_on") or "", row.get("source_session") or "")
        if previous is None or revision > (previous.get("registered_on") or "", previous.get("source_session") or ""):
            entries[key] = row
    return list(entries.values())


def excluded(row, task):
    return any(normalized(word) in normalized(task) for word in row["exclusions"])


def match(rows, task):
    task = normalized(task)
    candidates = []
    for row in latest(rows):
        if excluded(row, task):
            continue
        hits = [len(label) for label in map(normalized, [row["canonical_name"], *row["aliases"]])
                if re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", task)]
        if hits:
            candidates.append((max(hits), row))
    if not candidates:
        return []
    best = max(score for score, _ in candidates)
    return [row for score, row in candidates if score == best]


def describe(rows):
    described = []
    for row in rows:
        exists = None
        if row["material_path"]:
            path = path_of(row["material_path"], protected=False)
            try:
                path.stat()
                exists = True
            except FileNotFoundError:
                exists = False
            except OSError as exc:
                raise TopicError(f"E_TOPIC_MATERIAL: {path}: {exc}") from exc
        described.append(dict(row, material_exists=exists))
    return described
