#!/usr/bin/env python3
"""Emit a small, read-only environment discovery report as JSON.

Usage:
    python -B probe_environment.py
    python -B probe_environment.py --scope user-device --confirmed-local

The default scope is the execution host, which may be a remote host or sandbox.
Only use --confirmed-local after independently confirming that execution takes
place on the user's device. This flag does not verify a target application.

Discovery uses a fixed list of top-level module names and executable names.
Module specs are located without importing those modules. Executable discovery
uses shutil.which (the normal PATH lookup); paths and environment variables are
never included in output. There is no recursive directory search, network call,
package installation, subprocess launch, Office probe, or permission test.

An available module spec or PATH entry is discovery evidence only. Imports,
native dependencies, graphical display, executable launch, and application
compatibility remain untested. Missing PATH entries do not establish that an
application is absent from the device. Errors use fixed codes without paths.
"""

import argparse
import importlib.util
import json
import platform
import shutil
import struct
import sys


SCOPES = ("execution-host", "user-device")
MODULE_NAMES = ("tkinter", "_tkinter", "pandas", "openpyxl", "PIL", "pytest", "PyInstaller")
PROGRAM_NAMES = {
    "python": ("python", "python3", "py"),
    "node": ("node", "nodejs"),
    "browser": ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser", "firefox", "brave", "safari"),
}


class ScopeError(ValueError):
    """The execution scope cannot be asserted from the provided arguments."""


def _module_status(name):
    try:
        found = importlib.util.find_spec(name) is not None
    except Exception:
        return {"availability": "unknown", "method": "module_spec", "reason": "discovery_error", "runtime_test": "unknown"}
    return {
        "availability": "available" if found else "unavailable",
        "method": "module_spec",
        "runtime_test": "unknown",
    }


def _program_status(names):
    discovered = []
    failed = False
    for name in names:
        try:
            if shutil.which(name) is not None:
                discovered.append(name)
        except Exception:
            failed = True
    # Names are fixed public command names; resolved paths are never retained.
    result = {
        "availability": "available" if discovered else ("unknown" if failed else "unavailable"),
        "method": "path_lookup_only",
        "commands": discovered,
        "runtime_test": "unknown",
        "installed_on_device": "unknown",
    }
    if failed:
        result["reason"] = "discovery_error"
    return result


def _platform_status():
    system = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(sys.platform, "unknown")
    try:
        machine = platform.machine().lower()
    except Exception:
        machine = ""
    architecture = {
        "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "aarch64": "arm64", "arm64": "arm64",
        "x86": "x86", "i386": "x86", "i486": "x86", "i586": "x86", "i686": "x86",
        "armv7l": "armv7", "armv6l": "armv6", "riscv64": "riscv64",
    }.get(machine, "unknown")
    return {
        "system": system,
        "reported_architecture": architecture,
        "interpreter_pointer_bits": struct.calcsize("P") * 8,
        "native_hardware_verified": "unknown",
        "os_product_version": "unknown",
    }


def collect_environment(scope="execution-host", confirmed_local=False):
    """Collect discovery facts; validate scope before any discovery takes place."""
    if scope not in SCOPES:
        raise ScopeError("scope must be execution-host or user-device")
    if scope == "user-device" and not confirmed_local:
        raise ScopeError("user-device scope requires --confirmed-local")
    if scope != "user-device" and confirmed_local:
        raise ScopeError("--confirmed-local requires --scope user-device")

    implementation = {"cpython": "CPython", "pypy": "PyPy"}.get(sys.implementation.name, "unknown")
    return {
        "schema_version": 1,
        "scope": scope,
        "scope_basis": "explicit_local_confirmation" if confirmed_local else "execution_context_only",
        "platform": _platform_status(),
        "python": {
            "version": ".".join(str(v) for v in sys.version_info[:3]),
            "implementation": implementation,
            "current_interpreter": "running_this_probe",
            "modules": {name: _module_status(name) for name in MODULE_NAMES},
        },
        "programs": {name: _program_status(commands) for name, commands in PROGRAM_NAMES.items()},
        "unverified": {
            "network_access": "unknown",
            "installation_permission": "unknown",
            "office_availability": "unknown",
            "graphical_display": "unknown",
            "target_application_tested": "unknown",
            "target_device_compatibility": "unknown",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scope", choices=SCOPES, default="execution-host")
    parser.add_argument("--confirmed-local", action="store_true", help="Confirm this execution is on the user's device; does not verify an application.")
    args = parser.parse_args(argv)
    try:
        result = collect_environment(args.scope, args.confirmed_local)
    except ScopeError as exc:
        print(json.dumps({"ok": False, "error": "invalid_scope_confirmation", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
