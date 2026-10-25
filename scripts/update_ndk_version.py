#!/usr/bin/env python3
"""Pin the newest stable Linux NDK published in Google's SDK repository."""

import argparse
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


REPOSITORY_URL = "https://dl.google.com/android/repository/repository2-3.xml"
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def children(node, name):
    return [item for item in node if item.tag.rsplit("}", 1)[-1] == name]


def child(node, name):
    return next(iter(children(node, name)), None)


def content(node, name, default=""):
    item = child(node, name)
    return default if item is None else (item.text or "").strip()


def latest_stable_ndk(xml_data):
    root = ET.fromstring(xml_data)
    candidates = []
    for package in root.iter():
        if package.tag.rsplit("}", 1)[-1] != "remotePackage":
            continue
        package_path = package.get("path", "")
        if not package_path.startswith("ndk;"):
            continue
        version = package_path.removeprefix("ndk;")
        if not VERSION_PATTERN.fullmatch(version):
            continue
        if package.get("obsolete", "false").lower() == "true":
            continue
        obsolete = child(package, "obsolete")
        if obsolete is not None and (obsolete.text or "true").strip().lower() not in {"false", "0"}:
            continue
        channel = child(package, "channelRef")
        if channel is not None and channel.get("ref") != "channel-0":
            continue
        revision = child(package, "revision")
        if revision is None:
            continue
        # Preview packages can also appear in channel-0; check the revision too.
        try:
            if int(content(revision, "preview", "0")) != 0:
                continue
            numbers = tuple(int(content(revision, key, "0")) for key in ("major", "minor", "micro"))
        except ValueError:
            continue
        if numbers != tuple(map(int, version.split("."))):
            continue
        archives = child(package, "archives")
        if archives is None:
            continue
        linux_available = False
        for archive in children(archives, "archive"):
            complete = child(archive, "complete")
            if content(archive, "host-os") == "linux" and complete is not None and content(complete, "url"):
                linux_available = True
                break
        if linux_available:
            candidates.append((numbers, version))
    if not candidates:
        raise ValueError("Google SDK metadata contains no stable Linux NDK package")
    return max(candidates)[1]


def update_properties(path, latest):
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"^NDK_VERSION=(.*)$", text, re.M)
    if len(matches) != 1 or not VERSION_PATTERN.fullmatch(matches[0].strip()):
        raise ValueError("Expected exactly one numeric NDK_VERSION property")
    current = matches[0].strip()
    changed = tuple(map(int, latest.split("."))) > tuple(map(int, current.split(".")))
    selected = latest if changed else current
    if changed:
        text = re.sub(r"^NDK_VERSION=.*$", f"NDK_VERSION={selected}", text, flags=re.M)
        path.write_text(text, encoding="utf-8")
    return current, selected, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--properties", type=Path, default=Path("version.properties"))
    parser.add_argument("--repository-xml", type=Path, help="Read saved SDK metadata instead of downloading it")
    args = parser.parse_args()
    try:
        if args.repository_xml is not None:
            xml_data = args.repository_xml.read_bytes()
        else:
            with urllib.request.urlopen(REPOSITORY_URL, timeout=30) as response:
                xml_data = response.read()
        latest = latest_stable_ndk(xml_data)
        current, selected, changed = update_properties(args.properties, latest)
        if output_path := os.environ.get("GITHUB_OUTPUT"):
            with open(output_path, "a", encoding="utf-8") as output:
                output.write(f"changed={str(changed).lower()}\nversion={selected}\nlatest={latest}\n")
        print(f"NDK: {current} -> {selected}; newest stable Linux package: {latest}; changed: {changed}")
        return 0
    except (OSError, ValueError, ET.ParseError, urllib.error.URLError) as error:
        print(f"NDK update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
