import re
import logging
from typing import List, Optional
from src import gh
from sys import exit
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

# ... (parse_header and parse_param functions remain unchanged) ...

def find_file(files: list[Path], prefix: str = None, suffix: str = None, contains: str = None, exclude: list = None) -> Path | None:
    if exclude is None:
        exclude = []
    
    for file in files:
        if any(excl.lower() in file.name.lower() for excl in exclude):
            continue
            
        matches = True
        if prefix and not file.name.startswith(prefix):
            matches = False
        if suffix and not file.name.endswith(suffix):
            matches = False
        if contains and contains.lower() not in file.name.lower():
            matches = False
            
        if matches:
            return file
    return None

def find_apksigner() -> str | None:
    sdk_root = Path("/usr/local/lib/android/sdk")
    build_tools_dir = sdk_root / "build-tools"
    if not build_tools_dir.exists():
        return None
    versions = sorted(build_tools_dir.iterdir(), reverse=True)
    for version_dir in versions:
        apksigner_path = version_dir / "apksigner"
        if apksigner_path.exists():
            return str(apksigner_path)
    return None

def run_process(command, cwd=None, capture=False, stream=False, silent=False, check=True, shell=False):
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=shell
    )
    output_lines = []
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                if not silent: print(line.rstrip(), flush=True)
                if capture: output_lines.append(line)
        process.stdout.close()
        rc = process.wait()
        if check and rc != 0: raise subprocess.CalledProcessError(rc, command)
        return ''.join(output_lines).strip() if capture else None
    except Exception as e:
        print(f"Error: {e}")
        exit(1)

def get_highest_version(versions: list[str]) -> str | None:
    if not versions: return None
    def ver_key(v): return [int(x) if x.isdigit() else 0 for x in re.split(r'\D+', v)]
    return max(versions, key=ver_key)

def get_supported_version(package_name: str, cli: str, patches: str) -> Optional[str]:
    cli_str = str(cli).lower()
    major_version = 0
    # Updated Regex to handle v4.6.0 or 4.6.0
    match = re.search(r'cli-v?(\d+)', cli_str)
    if match:
        major_version = int(match.group(1))
    elif "6." in cli_str:
        major_version = 6

    if major_version >= 6:
        cmd = ['java', '-jar', str(cli), 'list-versions', '-f', package_name, '-p', str(patches)]
    elif major_version == 4:
        cmd = ['java', '-jar', str(cli), 'list-versions', '-f', package_name, '-b', str(patches)]
    else:
        cmd = ['java', '-jar', str(cli), 'list-versions', '-f', package_name, str(patches)]

    output = run_process(cmd, capture=True, silent=True)
    if not output: return None

    versions = re.findall(r'\d+(?:\.\d+)+', output)
    return get_highest_version(versions) if versions else None

def extract_filename(response, fallback_url=None) -> str:
    cd = response.headers.get('content-disposition')
    if cd:
        filename = re.findall('filename=(.+)', cd)
        if filename: return unquote(filename[0].strip('"'))
    path = urlparse(fallback_url or response.url).path
    return unquote(Path(path).name)

def detect_github_release(user: str, repo: str, tag: str) -> dict:
    repo_obj = gh.get_repo(f"{user}/{repo}")
    if tag == "latest" or tag == "":
        release = repo_obj.get_latest_release()
    else:
        release = repo_obj.get_release(tag)
    return release.raw_data
