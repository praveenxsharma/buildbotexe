import json
import logging
from pathlib import Path
from src import (
    utils,
    apkpure,
    session,
    uptodown,
    aptoide,
    apkmirror
)

def download_resource(url: str, name: str = None) -> Path:
    res = session.get(url, stream=True)
    res.raise_for_status()
    final_url = res.url

    if not name:
        name = utils.extract_filename(res, fallback_url=final_url)

    filepath = Path(name)
    total_size = int(res.headers.get('content-length', 0))
    downloaded_size = 0

    with filepath.open("wb") as file:
        for chunk in res.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)
                downloaded_size += len(chunk)

    logging.info(
        f"URL: {final_url} [{downloaded_size}/{total_size}] -> \"{filepath}\" [1]"
    )

    return filepath

def download_required(source: str) -> tuple[list[Path], str]:
    source_path = Path("sources") / f"{source}.json"
    with source_path.open() as json_file:
        repos_info = json.load(json_file)

    if isinstance(repos_info, dict) and "bundle_url" in repos_info:
        return download_from_bundle(repos_info)
    
    name = repos_info[0]["name"]
    downloaded_files = []

    for repo_info in repos_info[1:]:
        user = repo_info['user']
        repo = repo_info['repo']
        tag = repo_info['tag']

        release = utils.detect_github_release(user, repo, tag)
        
        for asset in release["assets"]:
            if asset["name"].endswith(".asc"):
                continue
            
            # Version-aware naming for CLI and Patches
            custom_name = None
            clean_tag = tag.replace('v', '') if tag not in ["latest", ""] else "latest"
            
            if "cli" in asset["name"].lower() and asset["name"].endswith(".jar"):
                custom_name = f"revanced-cli-{clean_tag}.jar"
            elif "patches" in asset["name"].lower() and asset["name"].endswith((".rvp", ".jar", ".mpp")):
                ext = Path(asset["name"]).suffix
                custom_name = f"patches-{clean_tag}{ext}"

            filepath = download_resource(asset["browser_download_url"], name=custom_name)
            downloaded_files.append(filepath)

    return downloaded_files, name

def download_from_bundle(bundle_info: dict) -> tuple[list[Path], str]:
    bundle_url = bundle_info["bundle_url"]
    name = bundle_info.get("name", "bundle-patches")
    
    logging.info(f"Downloading bundle from {bundle_url}")
    
    with session.get(bundle_url) as res:
        res.raise_for_status()
        bundle_data = res.json()
    
    downloaded_files = []
    
    if "patches" in bundle_data:
        for patch in bundle_data.get("patches", []):
            if "url" in patch:
                downloaded_files.append(download_resource(patch["url"]))
        
        for integration in bundle_data.get("integrations", []):
            if "url" in integration:
                downloaded_files.append(download_resource(integration["url"]))
    
    try:
        cli_release = utils.detect_github_release("revanced", "revanced-cli", "latest")
        for asset in cli_release["assets"]:
            if asset["name"].endswith(".jar") and "cli" in asset["name"].lower():
                downloaded_files.append(download_resource(asset["browser_download_url"], name="revanced-cli-latest.jar"))
                break
    except Exception as e:
        logging.warning(f"Could not download ReVanced CLI: {e}")
    
    return downloaded_files, name

def download_platform(app_name: str, platform: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    try:
        config_path = Path("apps") / platform / f"{app_name}.json"
        if not config_path.exists():
            return None, None

        with config_path.open() as json_file:
            config = json.load(json_file)
        
        if arch:
            config['arch'] = arch

        version = config.get("version") or utils.get_supported_version(config['package'], cli, patches)
        platform_module = globals()[platform]
        version = version or platform_module.get_latest_version(app_name, config)
        
        download_link = platform_module.get_download_link(version, app_name, config)
        filepath = download_resource(download_link)
        return filepath, version 

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None, None

def download_apkmirror(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "apkmirror", cli, patches, arch)

def download_apkpure(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "apkpure", cli, patches, arch)

def download_aptoide(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "aptoide", cli, patches, arch)

def download_uptodown(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "uptodown", cli, patches, arch)

def download_apkeditor() -> Path:
    release = utils.detect_github_release("REAndroid", "APKEditor", "latest")
    for asset in release["assets"]:
        if asset["name"].startswith("APKEditor") and asset["name"].endswith(".jar"):
            return download_resource(asset["browser_download_url"])
    raise RuntimeError("APKEditor .jar file not found")
