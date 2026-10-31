#!/usr/bin/env python3
"""Deterministic xb-lucky contract, CLI, and optional real-dataset checks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
LUCKY = ROOT / "xb-lucky"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_dataset_module():
    path = LUCKY / "scripts" / "dataset.py"
    spec = importlib.util.spec_from_file_location("xb_lucky_dataset", path)
    require(spec is not None and spec.loader is not None, "cannot load dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def static_checks() -> None:
    skill = (LUCKY / "SKILL.md").read_text(encoding="utf-8")
    interpretation = (LUCKY / "references" / "interpretation.md").read_text(encoding="utf-8")
    ledger = (LUCKY / "references" / "source-ledger.md").read_text(encoding="utf-8")
    notices = (LUCKY / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    shell = (ROOT / "xbskill" / "SKILL.md").read_text(encoding="utf-8")
    routing = (ROOT / "xbskill" / "references" / "routing.md").read_text(encoding="utf-8")
    guide = (ROOT / "xbskill" / "references" / "user-guide.md").read_text(encoding="utf-8")
    for phrase in (
        "无论由 `xbskill` 路由、用户直接输入 `$xb-lucky`", "任何高自动档",
        "同意本次 / 同意并本次会话内不再询问 / 不用了", "禁止劝用",
        "断语温度", "判断让渡", "防依赖", "危机转介", "股票", "九宫姓名学",
        "E_DST_CONFIRMATION_REQUIRED", "E_DATASET_DOWNLOAD", "iztro` **2.6.3**",
    ):
        require(phrase in skill, f"xb-lucky contract misses {phrase}")
    for phrase in ("不是成功率", "双方自愿", "医疗", "现实硬约束优先", "同一事项已解读"):
        require(phrase in interpretation, f"interpretation contract misses {phrase}")
    for phrase in ("ff9a1470ebe652e57b9d690f5d01db9a04f47aae", "CC BY 4.0", "不批量复制", "2.6.3"):
        require(phrase in ledger, f"source ledger misses {phrase}")
    require("MIT License" in notices and "Copyright (c) 2026 紫微研究" in notices, "MIT attribution missing")
    require("`xb-lucky`" in routing and "调起声明卡" in shell, "root route or consent gate missing")
    require("40 个专科" in guide and "41 个公开 Skill" in guide, "public skill count stale")

    dataset = load_dataset_module()
    require("health" not in dataset.ALLOWED_TOPICS, "dataset health topic is exposed")
    with tempfile.TemporaryDirectory(prefix="xb-lucky-static-") as raw:
        temp = Path(raw)
        chart = {
            "command": "chart",
            "input": {"datasetLookup": {"key": "2026-11-04-5-male", "sameChartBasis": True}},
            "chart": {"lifePalaceFirstMajorStar": "巨门"},
        }
        chart_path = temp / "chart.json"
        chart_path.write_text(json.dumps(chart, ensure_ascii=False), encoding="utf-8")
        data_path = temp / "year-2026.jsonl"
        data_path.write_text(json.dumps({"k": "2026-11-04-5-male", "ms": "巨门", "c": {"overview": "fixture"}}, ensure_ascii=False) + "\n", encoding="utf-8")
        dataset.PINNED["files"][data_path.name] = hashlib.sha256(data_path.read_bytes()).hexdigest()
        result = dataset.lookup(data_path, chart_path, ["overview"])
        require(result["comparison"] == "life_palace_first_major_star_match", "matching dataset fixture failed")
        require(result["officialReadings"]["overview"] == "fixture", "official reading extraction failed")
        chart["input"]["datasetLookup"]["sameChartBasis"] = False
        chart_path.write_text(json.dumps(chart, ensure_ascii=False), encoding="utf-8")
        result = dataset.lookup(data_path, chart_path, ["overview"])
        require(result["comparison"] == "not_comparable_input_basis", "corrected chart was falsely treated as dataset-equivalent")
        try:
            dataset.lookup(data_path, chart_path, ["health"])
        except dataset.DatasetError as exc:
            require(exc.code == "E_DATASET_TOPIC", "health topic did not fail with the expected code")
        else:
            raise AssertionError("health topic was accepted")
        data_path.write_text('tampered', encoding='utf-8')
        try:
            dataset.lookup(data_path, chart_path, ['overview'])
        except dataset.DatasetError as exc:
            require(exc.code == 'E_DATASET_HASH', 'tampered file must fail integrity check')
        else:
            raise AssertionError('tampered official asset accepted')
        try:
            dataset.download(2026, temp, False)
        except dataset.DatasetError as exc:
            require(exc.code == "E_CONFIRMATION", "download consent bypassed")
        else:
            raise AssertionError("download without confirmation was accepted")
    print("PASS xb-lucky consent, safety, source, routing, dataset fixtures, and health/download blocks")


def run_node(node_path: str, args: list[str], expect: int = 0) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["NODE_PATH"] = node_path
    executable = shutil.which("node") or shutil.which("node.exe") or shutil.which("node.cmd")
    require(executable is not None, "Node.js 22.20+ is required for full xb-lucky checks")
    completed = subprocess.run(
        [executable, str(LUCKY / "scripts" / "ziwei.cjs"), *args],
        text=True, encoding="utf-8", errors="replace", capture_output=True, env=env, check=False,
    )
    require(completed.returncode == expect, f"node {' '.join(args)} returned {completed.returncode}: {completed.stderr}")
    return completed


def full_checks(node_path: str, dataset_path: Path | None) -> None:
    result = json.loads(run_node(node_path, ["self-test"]).stdout)
    require(result["passed"] and result["sampleLifePalaceFirstMajorStar"] == "巨门", "engine self-test failed")
    pick = json.loads(run_node(node_path, [
        "pick-day", "--start", "2026-11-02", "--end", "2026-11-08",
        "--time", "10:00", "--gender", "male", "--topic", "project",
    ]).stdout)
    require(pick["preferred"] == ["2026-11-04", "2026-11-05"], "documented pick-day sample changed")
    require(pick["candidates"][0]["supportCount"] == 3, "pick-day support scoring changed")
    blocked = json.loads(run_node(node_path, [
        "chart", "--date", "1990-05-01", "--time", "08:00", "--gender", "male", "--time-basis", "clock", "--region", "china-mainland",
    ], expect=2).stderr)
    require(blocked["error"] == "E_DST_CONFIRMATION_REQUIRED", "China DST was silently adjusted")
    overseas = json.loads(run_node(node_path, ['chart','--date','1990-05-01','--time','12:00','--gender','male','--time-basis','clock','--region','other','--standard-minus-clock-minutes','0','--longitude','-74','--utc-offset','-300']).stdout)
    require(not overseas['input']['clockAdjustment']['chinaDSTDate'], 'overseas input used China DST table')
    shifted = json.loads(run_node(node_path, ['chart','--date','2026-11-04','--time','23:00','--gender','male','--longitude','180','--utc-offset','-720']).stdout)
    require(shifted['input']['chartDate'] == '2026-11-06', 'positive cross-day late Zi hour lost next-day rule')
    unknown = run_node(node_path, ['chart','--date','2026-11-04','--time','10:00','--gender','male','--longtitude','121'], expect=2)
    require(json.loads(unknown.stderr)['error'] == 'E_ARGUMENT', 'misspelled correction option silently ignored')
    with tempfile.TemporaryDirectory(prefix="xb-lucky-full-") as raw:
        chart_path = Path(raw) / "chart.json"
        chart = run_node(node_path, ["chart", "--date", "2026-11-04", "--time", "10:00", "--gender", "male"])
        chart_path.write_text(chart.stdout, encoding="utf-8")
        chart_json = json.loads(chart.stdout)
        require(chart_json["input"]["datasetLookup"]["key"] == "2026-11-04-5-male", "dataset key changed")
        if dataset_path:
            dataset = load_dataset_module()
            comparison = dataset.lookup(dataset_path, chart_path, ["overview", "career", "wealth"])
            require(comparison["comparison"] == "life_palace_first_major_star_match", "real dataset comparison failed")
            require(comparison["datasetLifePalaceFirstMajorStar"] == "巨门", "real dataset star changed")
            print("PASS real v4.0 yearly dataset exact-key and life-palace comparison")
    print("PASS iztro engine, true-solar/DST gates, and documented 2026-11-02..08 pick-day sample")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-path", help="external node_modules directory containing iztro 2.6.3")
    parser.add_argument("--dataset", type=Path, help="optional real year-YYYY.jsonl[.zst]")
    args = parser.parse_args()
    static_checks()
    if args.node_path:
        full_checks(args.node_path, args.dataset)
    print("SUMMARY xb-lucky deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
