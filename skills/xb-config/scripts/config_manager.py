"""Project-scoped XB preferences and a deterministic reference invocation gate."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


class ConfigError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def empty_config():
    return {"schema_version": 1, "call_intensity": None, "save_prompt": None}


def validate_config(data, require_complete=False):
    if not isinstance(data, dict):
        raise ConfigError("E_CONFIG_TYPE", "Configuration must be an object")
    unknown = set(data) - {"schema_version", "call_intensity", "save_prompt"}
    if unknown:
        raise ConfigError("E_CONFIG_FIELDS", "Unknown fields: " + ", ".join(sorted(map(str, unknown))))
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ConfigError("E_CONFIG_VERSION", "schema_version must be integer 1")
    result = empty_config()
    for key, choices in (("call_intensity", ("high", "medium", "low")), ("save_prompt", ("high", "low"))):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or value not in choices):
            raise ConfigError("E_CONFIG_VALUE", "Invalid " + key)
        if require_complete and value is None:
            raise ConfigError("E_CONFIG_INCOMPLETE", "User must select " + key)
        result[key] = value
    return result


def _config_path(project):
    if project is None or not str(project).strip():
        raise ConfigError("E_CONFIG_PROJECT", "An explicit project directory is required")
    supplied = Path(project).expanduser()
    if not supplied.is_absolute():
        raise ConfigError("E_CONFIG_PROJECT", "Project path must be absolute")
    try:
        root = supplied.resolve(strict=True)
        if not root.is_dir():
            raise ConfigError("E_CONFIG_PROJECT", "Project is not a directory: " + str(root))
        folder = root / ".xbskill"
        path = folder / "config.json"
        if folder.is_symlink() or path.is_symlink():
            raise ConfigError("E_CONFIG_PATH", "Configuration symlinks are unsupported: " + str(path))
        # resolve() catches Windows junctions as well as ordinary symlinks.
        if folder.resolve() != folder or path.resolve() != path:
            raise ConfigError("E_CONFIG_PATH", "Configuration must remain in its project: " + str(path))
        if folder.exists() and not folder.is_dir():
            raise ConfigError("E_CONFIG_PATH", "Configuration parent is not a directory: " + str(folder))
        if path.exists() and not path.is_file():
            raise ConfigError("E_CONFIG_PATH", "Configuration is not a file: " + str(path))
        return path
    except OSError as exc:
        raise ConfigError("E_CONFIG_PATH", str(exc)) from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("E_CONFIG_FIELDS", "Duplicate field: " + key)
        result[key] = value
    return result


def load_config(project):
    path = _config_path(project)
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return empty_config()
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ConfigError("E_CONFIG_JSON", str(path) + ": " + str(exc)) from exc
    except OSError as exc:
        raise ConfigError("E_CONFIG_READ", str(path) + ": " + str(exc)) from exc
    return validate_config(data)


def write_config(project, data, *, user_confirmed=False):
    if user_confirmed is not True:
        raise ConfigError("E_CONFIG_AUTH", "Both preferences require explicit user selection")
    checked = validate_config(data, require_complete=True)
    path = _config_path(project)
    # Refuse to silently replace corrupt or unsupported existing configuration.
    load_config(project)
    temporary = None
    try:
        path.parent.mkdir(exist_ok=True)
        _config_path(project)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=".config-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(checked, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _config_path(project)
        os.replace(temporary, path)
        temporary = None
        if load_config(project) != checked:
            raise ConfigError("E_CONFIG_VERIFY", "Configuration changed during verification: " + str(path))
        return str(path)
    except OSError as exc:
        raise ConfigError("E_CONFIG_WRITE", str(path) + ": " + str(exc)) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def decide_gate(config, *, task_id, specialist, explicit_xb=False, explicit_external=False,
                refused_xb=False, natural_match=False, authorized_task=None, authorized_specialist=None,
                save_requested=False):
    for flag in (explicit_xb, explicit_external, refused_xb, natural_match, save_requested):
        if type(flag) is not bool:
            raise ConfigError("E_GATE_TYPE", "Gate signals must be booleans")
    if refused_xb:
        return {"decision": "deny", "reason": "user_refusal"}
    if save_requested:
        if specialist != "xb-save":
            raise ConfigError("E_GATE_SCOPE", "A save request may dispatch only xb-save")
        return {"decision": "allow", "reason": "save_request"}
    if explicit_external and not explicit_xb:
        return {"decision": "deny", "reason": "external_choice"}
    checked = validate_config(config)
    if checked["call_intensity"] is None or checked["save_prompt"] is None:
        return {"decision": "configure" if explicit_xb else "deny", "reason": "unconfigured"}
    if not isinstance(task_id, str) or not task_id.strip() or not isinstance(specialist, str) or not specialist.strip():
        raise ConfigError("E_GATE_SCOPE", "Task and specialist identifiers are required")
    if explicit_xb:
        return {"decision": "allow", "reason": "joint_request" if explicit_external else "explicit_xb"}
    if authorized_task == task_id and authorized_specialist == specialist:
        return {"decision": "allow", "reason": "authorized_continuation"}
    if not natural_match:
        return {"decision": "deny", "reason": "no_match"}
    intensity = checked["call_intensity"]
    return {"decision": {"high": "allow", "medium": "confirm", "low": "deny"}[intensity],
            "reason": {"high": "high_natural_match", "medium": "task_confirmation_required", "low": "explicit_only"}[intensity]}


def should_prompt_save(config, *, final_response=True, xb_active=True):
    if type(final_response) is not bool or type(xb_active) is not bool:
        raise ConfigError("E_GATE_TYPE", "Reply signals must be booleans")
    if not final_response or not xb_active:
        return False
    checked = validate_config(config)
    return checked["call_intensity"] is not None and checked["save_prompt"] == "high"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("read", "set", "gate", "prompt"):
        command = commands.add_parser(name)
        command.add_argument("--project", required=True)
        if name == "set":
            command.add_argument("--call-intensity", choices=("high", "medium", "low"), required=True)
            command.add_argument("--save-prompt", choices=("high", "low"), required=True)
            command.add_argument("--user-confirmed", action="store_true")
        if name == "gate":
            command.add_argument("--task-id", required=True)
            command.add_argument("--specialist", required=True)
            for flag in ("explicit-xb", "explicit-external", "refused-xb", "natural-match", "save-requested"):
                command.add_argument("--" + flag, action="store_true")
            command.add_argument("--authorized-task")
            command.add_argument("--authorized-specialist")
        if name == "prompt":
            command.add_argument("--intermediate", action="store_true")
            command.add_argument("--inactive", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "set":
            path = write_config(args.project, {"schema_version": 1, "call_intensity": args.call_intensity,
                                "save_prompt": args.save_prompt}, user_confirmed=args.user_confirmed)
            result = {"status": "configured", "path": path, "config": load_config(args.project)}
        elif args.command == "read":
            config = load_config(args.project)
            result = {"status": "unconfigured" if None in config.values() else "configured",
                      "path": str(_config_path(args.project)), "config": config}
        elif args.command == "gate":
            # An explicit external choice must succeed even if XB configuration is broken.
            bypass_config = args.refused_xb or args.save_requested or (args.explicit_external and not args.explicit_xb)
            config = empty_config() if bypass_config else load_config(args.project)
            result = decide_gate(config, task_id=args.task_id, specialist=args.specialist,
                                 explicit_xb=args.explicit_xb, explicit_external=args.explicit_external,
                                 refused_xb=args.refused_xb, natural_match=args.natural_match,
                                 authorized_task=args.authorized_task, authorized_specialist=args.authorized_specialist,
                                 save_requested=args.save_requested)
        else:
            result = {"prompt_save": should_prompt_save(load_config(args.project),
                       final_response=not args.intermediate, xb_active=not args.inactive), "save_authorized": False}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ConfigError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
