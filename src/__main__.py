import json
import logging
import re
from sys import exit
from pathlib import Path
from os import getenv
import subprocess
from src import (
    r2,
    utils,
    release,
    downloader
)

def run_build(app_name: str, source: str, arch: str = "universal") -> str:
    download_files, name = downloader.download_required(source)

    logging.info(f"📦 Downloaded {len(download_files)} files for {source}:")
    for file in download_files:
        logging.info(f"  - {file.name} ({file.stat().st_size} bytes)")

    is_morphe = False
    is_revanced = False

    for file in download_files:
        if "morphe-cli" in file.name.lower():
            is_morphe = True
            break
        elif "revanced-cli" in file.name.lower():
            is_revanced = True
            break

    if not is_morphe and not is_revanced:
        for file in download_files:
            if file.suffix == ".mpp":
                is_morphe = True
                break
            elif file.suffix in [".rvp", ".jar"] and "patches" in file.name.lower():
                is_revanced = True
                break

    if not is_morphe and not is_revanced:
        is_morphe = "morphe" in source.lower() or "custom" in source.lower()
        is_revanced = not is_morphe

    logging.info(f"🔍 Detected: {'Morphe' if is_morphe else 'ReVanced'} source type")

    if is_morphe:
        cli = utils.find_file(download_files, contains="morphe-cli", suffix=".jar", exclude=["dev"])
        if not cli:
            cli = utils.find_file(download_files, contains="morphe", suffix=".jar")
        
        patches = utils.find_file(download_files, contains="patches", suffix=".mpp")
        if not patches:
            patches = utils.find_file(download_files, suffix=".mpp")
    else:
        cli = utils.find_file(download_files, contains="revanced-cli", suffix=".jar")
        patches = utils.find_file(download_files, contains="patches", suffix=".rvp")
        if not patches:
            patches = utils.find_file(download_files, contains="patches", suffix=".jar")

    if not cli:
        logging.error(f"❌ CLI not found for source: {source}")
        return None
    if not patches:
        logging.error(f"❌ Patches not found for source: {source}")
        return None

    logging.info(f"✅ Using CLI: {cli.name}")
    logging.info(f"✅ Using patches: {patches.name}")

    download_methods = [
        downloader.download_apkmirror,
        downloader.download_apkpure,
        downloader.download_uptodown,
        downloader.download_aptoide
    ]

    input_apk = None
    version = None
    for method in download_methods:
        input_apk, version = method(app_name, str(cli), str(patches))
        if input_apk:
            break
            
    if input_apk is None:
        logging.error(f"❌ Failed to download APK for {app_name}")
        return None

    if input_apk.suffix != ".apk":
        logging.warning("Input file is not .apk, using APKEditor to merge")
        apk_editor = downloader.download_apkeditor()
        merged_apk = input_apk.with_suffix(".apk")

        utils.run_process([
            "java", "-jar", apk_editor, "m",
            "-i", str(input_apk),
            "-o", str(merged_apk)
        ], silent=True)

        input_apk.unlink(missing_ok=True)

        if not merged_apk.exists():
            logging.error("Merged APK file not found")
            exit(1)

        clean_name = re.sub(r'\(\d+\)', '', merged_apk.name)
        clean_name = re.sub(r'-\d+_', '_', clean_name)
        if clean_name != merged_apk.name:
            clean_apk = merged_apk.with_name(clean_name)
            merged_apk.rename(clean_apk)
            merged_apk = clean_apk

        input_apk = merged_apk
        logging.info(f"Merged APK file generated: {input_apk}")

    if arch != "universal":
        logging.info(f"Processing APK for {arch} architecture...")
        if arch == "arm64-v8a":
            utils.run_process(["zip", "--delete", str(input_apk), "lib/x86/*", "lib/x86_64/*", "lib/armeabi-v7a/*"], silent=True, check=False)
        elif arch == "armeabi-v7a":
            utils.run_process(["zip", "--delete", str(input_apk), "lib/x86/*", "lib/x86_64/*", "lib/arm64-v8a/*"], silent=True, check=False)
    else:
        utils.run_process(["zip", "--delete", str(input_apk), "lib/x86/*", "lib/x86_64/*"], silent=True, check=False)

    exclude_patches = []
    include_patches = []

    patches_path = Path("patches") / f"{app_name}-{source}.txt"
    if patches_path.exists():
        with patches_path.open('r') as patches_file:
            for line in patches_file:
                line = line.strip()
                if line.startswith('-'):
                    exclude_patches.extend(["-d", line[1:].strip()])
                elif line.startswith('+'):
                    include_patches.extend(["-e", line[1:].strip()])

    try:
        fixed_apk = Path(f"{app_name}-fixed-v{version}.apk")
        subprocess.run(["zip", "-FF", str(input_apk), "--out", str(fixed_apk)], check=False, capture_output=True)
        if fixed_apk.exists() and fixed_apk.stat().st_size > 0:
            input_apk.unlink(missing_ok=True)
            fixed_apk.rename(input_apk)
    except Exception as e:
        logging.warning(f"Could not fix APK: {e}")

    output_apk = Path(f"{app_name}-{arch}-patch-v{version}.apk")

    if is_morphe:
        logging.info("🔧 Using Morphe patching system...")
        patch_cmd = [
            "java", "-jar", str(cli),
            "patch", "--patches", str(patches),
            "--out", str(output_apk), str(input_apk),
            *exclude_patches, *include_patches
        ]
    else:
        logging.info("🔧 Using ReVanced patching system...")
        cli_str = str(cli).lower()
        
        # Regex to safely check the exact major version number
        is_v6_plus = False
        match = re.search(r'cli-(\d+)', cli_str)
        if match and int(match.group(1)) >= 6:
            is_v6_plus = True
                
        if is_v6_plus:
            # v6.0.0+ Documentation Syntax
            patch_cmd = [
                "java", "-jar", str(cli),
                "patch",
                "-b", "-p", str(patches),
                *exclude_patches, *include_patches,
                "--out", str(output_apk),
                str(input_apk)
            ]
        else:
            # Legacy Syntax
            patch_cmd = [
                "java", "-jar", str(cli),
                "patch", 
                "--patches", str(patches),
                "--out", str(output_apk), 
                str(input_apk),
                *exclude_patches, *include_patches
            ]

    logging.info(f"🚀 Running patch command: {' '.join(patch_cmd)}")
    utils.run_process(patch_cmd, stream=True)

    input_apk.unlink(missing_ok=True)
    signed_apk = Path(f"{app_name}-{arch}-{name}-v{version}.apk")

    apksigner = utils.find_apksigner()
    if not apksigner:
        exit(1)

    try:
        utils.run_process([
            str(apksigner), "sign", "--verbose",
            "--ks", "keystore/public.jks",
            "--ks-pass", "pass:public",
            "--key-pass", "pass:public",
            "--ks-key-alias", "public",
            "--in", str(output_apk), "--out", str(signed_apk)
        ], stream=True)
    except Exception as e:
        logging.warning(f"Standard signing failed: {e}")
        utils.run_process([
            str(apksigner), "sign", "--verbose",
            "--min-sdk-version", "21",
            "--ks", "keystore/public.jks",
            "--ks-pass", "pass:public",
            "--key-pass", "pass:public",
            "--ks-key-alias", "public",
            "--in", str(output_apk), "--out", str(signed_apk)
        ], stream=True)

    output_apk.unlink(missing_ok=True)
    print(f"✅ APK built: {signed_apk.name}")
    
    return str(signed_apk)

def main():
    app_name = getenv("APP_NAME")
    source = getenv("SOURCE")

    if not app_name or not source:
        logging.error("APP_NAME and SOURCE environment variables must be set")
        exit(1)

    arch_config_path = Path("arch-config.json")
    arches = ["universal"]
    if arch_config_path.exists():
        with open(arch_config_path) as f:
            arch_config = json.load(f)
        for config in arch_config:
            if config["app_name"] == app_name and config["source"] == source:
                arches = config["arches"]
                break
        
    built_apks = []
    for arch in arches:
        logging.info(f"🔨 Building {app_name} for {arch} architecture...")
        apk_path = run_build(app_name, source, arch)
        if apk_path:
            built_apks.append(apk_path)
            print(f"✅ Built {arch} version: {Path(apk_path).name}")
        
    print(f"\n🎯 Built {len(built_apks)} APK(s) for {app_name}:")
    for apk in built_apks:
        print(f"  📱 {Path(apk).name}")

if __name__ == "__main__":
    main()
