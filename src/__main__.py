import json
import logging
import re
from sys import exit
from pathlib import Path
from os import getenv
import subprocess
from src import (
    utils,
    downloader
)

def run_build(app_name: str, source: str, arch: str = "universal") -> str:
    download_files, name = downloader.download_required(source)

    cli = utils.find_file(download_files, contains="morphe", suffix=".jar")
    if not cli: cli = utils.find_file(download_files, contains="cli", suffix=".jar")
    
    patches = utils.find_file(download_files, suffix=".mpp")
    if not patches:
        patches = utils.find_file(download_files, contains="patches", suffix=".rvp") or \
                  utils.find_file(download_files, contains="patches", suffix=".jar")

    if not cli or not patches:
        logging.error(f"❌ Missing tools for {source}")
        return None

    cli_str = cli.name.lower()
    is_morphe_cli = "morphe" in cli_str
    major_version = 0
    match = re.search(r'cli-v?(\d+)', cli_str)
    if match: major_version = int(match.group(1))
    
    logging.info(f"✅ Toolchain: {'Morphe' if is_morphe_cli else 'ReVanced'} CLI (v{major_version if major_version else '?'})")

    input_apk, version = None, None
    for method in [downloader.download_apkmirror, downloader.download_apkpure, downloader.download_uptodown]:
        input_apk, version = method(app_name, str(cli), str(patches))
        if input_apk: break
            
    if not input_apk: 
        logging.error(f"❌ Failed to download APK for {app_name}")
        return None

    # Architecture Slicing
    if arch != "universal":
        logging.info(f"Slicing APK for {arch}...")
        utils.run_process(["zip", "--delete", str(input_apk), "lib/x86/*", "lib/x86_64/*", 
                          "lib/armeabi-v7a/*" if arch == "arm64-v8a" else "lib/arm64-v8a/*"], 
                          silent=True, check=False)

    exclude_patches, include_patches = [], []
    patches_path = Path("patches") / f"{app_name}-{source}.txt"
    if patches_path.exists():
        with patches_path.open('r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('-'): exclude_patches.extend(["-d", line[1:].strip()])
                elif line.startswith('+'): include_patches.extend(["-e", line[1:].strip()])

    output_apk = Path(f"{app_name}-{arch}-patch-v{version}.apk")

    # Final Command Construction
    if is_morphe_cli:
        patch_cmd = ["java", "-jar", str(cli), "patch", "--patches", str(patches), "--out", str(output_apk), str(input_apk), *exclude_patches, *include_patches]
    elif major_version >= 6:
        patch_cmd = ["java", "-jar", str(cli), "patch", "-p", str(patches), *exclude_patches, *include_patches, "--out", str(output_apk), str(input_apk)]
    elif major_version == 4:
        # v4.6.0 compatibility
        flag = "-b" if patches.suffix in [".jar", ".rvp", ".mpp"] else "--patches"
        patch_cmd = ["java", "-jar", str(cli), "patch", flag, str(patches), "--out", str(output_apk), str(input_apk), *exclude_patches, *include_patches]
    else:
        patch_cmd = ["java", "-jar", str(cli), "patch", "--patches", str(patches), "--out", str(output_apk), str(input_apk), *exclude_patches, *include_patches]

    logging.info(f"🚀 Running: {' '.join(patch_cmd)}")
    utils.run_process(patch_cmd, stream=True)
    
    signed_apk = Path(f"{app_name}-{arch}-{name}-v{version}.apk")
    apksigner = utils.find_apksigner()
    if apksigner:
        utils.run_process([str(apksigner), "sign", "--ks", "keystore/public.jks", "--ks-pass", "pass:public", "--key-pass", "pass:public", "--ks-key-alias", "public", "--in", str(output_apk), "--out", str(signed_apk)])
    
    output_apk.unlink(missing_ok=True)
    return str(signed_apk)

def main():
    app_name, source = getenv("APP_NAME"), getenv("SOURCE")
    if not app_name or not source: exit(1)
    
    arches = ["universal"]
    arch_path = Path("arch-config.json")
    if arch_path.exists():
        with open(arch_path) as f:
            for cfg in json.load(f):
                if cfg["app_name"] == app_name and cfg["source"] == source:
                    arches = cfg["arches"]
                    break
    
    for arch in arches:
        logging.info(f"🔨 Building {app_name} ({arch})...")
        run_build(app_name, source, arch)

if __name__ == "__main__":
    main()
