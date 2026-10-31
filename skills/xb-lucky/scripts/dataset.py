#!/usr/bin/env python3
"""Explicit-download and offline lookup for ziwei-doushu v4.0 yearly data."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


RELEASE_API = "https://api.github.com/repos/Renhuai123/ziwei-doushu/releases/tags/v4.0-13d"
ATTRIBUTION = "紫微斗数开源解读数据集 v4.0；来源：https://github.com/Renhuai123/ziwei-doushu；作者：王多鱼AI"
ALLOWED_TOPICS = {
    "overview", "personality", "love", "career", "wealth", "family",
    "children", "move", "friends", "home", "spirit", "parents",
}


PINNED = json.loads((Path(__file__).resolve().parents[1] / 'references' / 'dataset-sha256.json').read_text(encoding='utf-8'))

def verify_dataset(path: Path) -> None:
    expected = PINNED['files'].get(path.name)
    if not expected or sha256(path) != expected:
        fail('E_DATASET_HASH', 'Local file is not a verified pinned yearly asset; use the original year-YYYY.jsonl.zst. No official reading is returned.')


class DatasetError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> None:
    raise DatasetError(code, message)


def fetch_bytes(url: str, accept: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "xbskill-xb-lucky/1.0",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail("E_DATASET_DOWNLOAD", f"下载失败：{url}；{exc}。核心 AI 解读仍可继续，本次没有官方成稿对照")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(year: int, destination: Path, confirmed: bool) -> dict:
    if not confirmed:
        fail("E_CONFIRMATION", "年度下载必须另加 --yes；排盘授权不自动包含联网下载")
    if not 1950 <= year <= 2026:
        fail("E_DATASET_YEAR", "v4.0 只提供 1950–2026 年文件")
    if not destination.is_absolute():
        fail("E_DATASET_PATH", "--dest 必须是用户确认的绝对目录")
    filename = f"year-{year}.jsonl.zst"
    target = destination / filename
    if target.exists():
        fail("E_DATASET_EXISTS", f"目标已存在，未覆盖：{target}")
    destination.mkdir(parents=True, exist_ok=True)

    try:
        release = json.loads(fetch_bytes(RELEASE_API, "application/vnd.github+json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("E_DATASET_METADATA", f"Release 元数据无效：{exc}")
    assets = {item.get("name"): item for item in release.get("assets", []) if isinstance(item, dict)}
    for required in (filename, "SHA256SUMS.txt"):
        if required not in assets or not assets[required].get("url"):
            fail("E_DATASET_METADATA", f"Release 缺少资产：{required}")

    checksums_text = fetch_bytes(assets["SHA256SUMS.txt"]["url"], "application/octet-stream").decode("utf-8")
    expected = None
    for line in checksums_text.splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == filename:
            expected = fields[0].lower()
            break
    if not expected or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        fail("E_DATASET_HASH", f"SHA256SUMS.txt 中没有 {filename} 的有效哈希")

    if expected != PINNED['files'].get(filename):
        fail('E_DATASET_HASH', 'Release checksum differs from the pinned release; refusing changed asset')

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=filename + ".", suffix=".part", dir=destination, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(fetch_bytes(assets[filename]["url"], "application/octet-stream"))
            handle.flush()
            os.fsync(handle.fileno())
        actual = sha256(temporary)
        if actual != expected:
            fail("E_DATASET_HASH", f"年度文件哈希不符：期望 {expected}，实际 {actual}；已拒绝落盘")
        temporary.replace(target)
        temporary = None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return {
        "status": "downloaded",
        "file": str(target),
        "sha256": expected,
        "release": "v4.0-13d",
        "attribution": ATTRIBUTION,
        "notice": "数据集未做真太阳时校正；倪师原话不适用 CC BY，禁止批量商用",
    }


def read_chart(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("E_CHART_JSON", f"无法读取排盘 JSON：{path}；{exc}")
    if value.get("command") != "chart" or "datasetLookup" not in value.get("input", {}):
        fail("E_CHART_JSON", "排盘 JSON 缺少 command=chart 或 input.datasetLookup")
    return value


def iter_records(path: Path):
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            yield from handle
        return
    if path.suffix != ".zst":
        fail("E_DATASET_FORMAT", "只接受 year-YYYY.jsonl 或 year-YYYY.jsonl.zst")
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        zstandard = None
    if zstandard is not None:
        try:
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    with io.TextIOWrapper(reader, encoding="utf-8") as text:
                        yield from text
            return
        except Exception as exc:
            fail("E_ZSTD_READ", f"Python zstandard 解压失败：{exc}。核心 AI 解读仍可继续")
    executable = shutil.which("zstd")
    if not executable:
        fail("E_ZSTD_MISSING", "读取 .zst 需要现有 Python zstandard 或用户安装 zstd 并放入 PATH；未自动安装。核心 AI 解读仍可继续")
    process = subprocess.Popen(
        [executable, "-d", "--long=27", "-c", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    exhausted = False
    try:
        for line in process.stdout:
            yield line
        exhausted = True
    finally:
        process.stdout.close()
        if not exhausted and process.poll() is None:
            process.terminate()
        stderr = process.stderr.read() if process.stderr else ""
        code = process.wait()
    if exhausted and code != 0:
        fail("E_ZSTD_READ", f"zstd 解压失败（退出码 {code}）：{stderr.strip()}")


def lookup(file: Path, chart_path: Path, topics: list[str]) -> dict:
    chart = read_chart(chart_path)
    lookup_info = chart["input"]["datasetLookup"]
    key = lookup_info["key"]
    if not topics or any(topic not in ALLOWED_TOPICS for topic in topics):
        fail("E_DATASET_TOPIC", "主题无效；health 永远不接受，其他可用主题见 --help")
    if not file.is_file():
        fail("E_DATASET_MISSING", f"年度文件不存在：{file}。核心 AI 解读仍可继续，本次没有官方成稿对照")

    verify_dataset(file)
    record = None
    try:
        for line in iter_records(file):
            if not line.strip():
                continue
            candidate = json.loads(line)
            if candidate.get("k") == key:
                record = candidate
                break
    except json.JSONDecodeError as exc:
        fail("E_DATASET_JSON", f"年度文件包含无效 JSONL：{exc}")
    if record is None:
        fail("E_DATASET_NO_MATCH", f"年度文件未找到 {key}；不附其他日期或时辰的文本")

    same_basis = bool(lookup_info.get("sameChartBasis"))
    dataset_star = record.get("ms")
    chart_star = chart.get("chart", {}).get("lifePalaceFirstMajorStar")
    if not same_basis:
        comparison = "not_comparable_input_basis"
        comparison_note = "当前盘经过时钟或真太阳时校正；数据集只作原始时钟参考，不能校对当前盘"
    elif dataset_star == chart_star:
        comparison = "life_palace_first_major_star_match"
        comparison_note = "仅命宫第一颗主星一致，不代表完整盘面、亮度或解读口径一致"
    else:
        comparison = "life_palace_first_major_star_mismatch"
        comparison_note = f"命宫第一颗主星不一致：数据集={dataset_star!r}，当前盘={chart_star!r}；请核对版本与口径，不得隐藏差异"
    return {
        "status": "matched",
        "key": key,
        "release": "v4.0-13d",
        "contentVersion": "ca268829f7a9",
        "comparison": comparison,
        "comparisonNote": comparison_note,
        "datasetLifePalaceFirstMajorStar": dataset_star,
        "chartLifePalaceFirstMajorStar": chart_star,
        "officialReadings": {topic: record.get("c", {}).get(topic) for topic in topics},
        "attribution": ATTRIBUTION,
        "notice": "传统文本演绎，仅供文化参考；不是预测或建议。倪师原话不在 CC BY 授权内",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="explicitly download one verified yearly asset")
    dl.add_argument("--year", type=int, required=True)
    dl.add_argument("--dest", type=Path, required=True)
    dl.add_argument("--yes", action="store_true")
    lk = sub.add_parser("lookup", help="offline exact-key lookup")
    lk.add_argument("--file", type=Path, required=True)
    lk.add_argument("--chart-json", type=Path, required=True)
    lk.add_argument("--topics", default="overview,career,wealth", help="comma-separated; health is prohibited")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "download":
            result = download(args.year, args.dest.resolve(), args.yes)
        else:
            topics = [item.strip() for item in args.topics.split(",") if item.strip()]
            result = lookup(args.file.resolve(), args.chart_json.resolve(), topics)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"error": "E_DATASET_IO", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except DatasetError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
