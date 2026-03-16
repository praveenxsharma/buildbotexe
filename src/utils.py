import re
import logging
from typing import List, Optional
from src import gh
from sys import exit
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

def _parseparam(s):
    while s[:1] == ";":
        s = s[1:]
        end = s.find(";")
        while end > 0 and (s.count('"', 0, end) - s.count('\\"', 0, end)) % 2:
            end = s.find(";", end + 1)
        if end < 0:
            end = len(s)
        f = s[:end]
        yield f.strip()
        s = s[end:]


def parse_header(line):
    """Parse a Content-type like header.
    Return the main content-type and a dictionary of options.
    """
    parts = _parseparam(";" + line)
    key = parts.__next__()
    pdict = {}
    for p in parts:
        i = p.find("=")
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i + 1 :].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
                value = value.replace("\\\\", "\\").replace('\\"', '"')
            pdict[name] = value
    return key, pdict

def find_file(files: list[Path], prefix: str = None, suffix: str = None, contains: str = None, exclude: list = None) -> Path | None:
    """Find a file with various matching criteria"""
    if exclude is None:
        exclude = []
    
    for file in files:
        # Skip excluded patterns
        if any(excl.lower() in file.name.lower() for excl in exclude):
            continue
            
        # Check all criteria
        matches = True
        
        if prefix and not file.name.startswith(prefix):
            matches = False
            
        if suffix and not file.name.endswith(suffix):
            matches = False
            
        if contains and contains.lower() not in file.name.lower():
            matches = False
            
        if matches:
            return file
    
    # If not found with exclude, try without exclude (for fallback)
    if exclude:
        for file in files:
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
        logging.error(f"No build-tools found at: {build_tools_dir}")
        return None

    versions = sorted(build_tools_dir.iterdir(), reverse=True)
    for version_dir in versions:
        apksigner_path = version_dir / "apksigner"
        if apksigner_path.exists() and apksigner_path.is_file():
            return str(apksigner_path)

    logging.error("No apksigner found in build-tools")
    return None

def run_process(
    command: List[str],
    cwd: Optional[Path] = None,
    capture: bool = False,
    stream: bool = False,
    silent: bool = False,
    check: bool = True,
    shell: bool = False
) -> Optional[str]:
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
                if not silent:
                    print(line.rstrip(), flush=True)
                if capture:
                    output_lines.append(line)
        process.stdout.close()
        return_code = process.wait()

        if check and return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)

        return ''.join(output_lines).strip() if capture else None

    except FileNotFoundError:
        print(f"Command not found: {command[0]}", flush=True)
        exit(1)
    except Exception as e:
        print(f"Error while running command: {e}", flush=True)
        exit(1)

def normalize_version(version: str) -> list[int]:
    parts = version.split('.')
    normalized = []
    for part in parts:
        match = re.match(r'(\d+)', part)
        if match:
            normalized.append(int(match.group(1)))
        else:
            normalized.append(0)
    
    # Include build number in comparison for versions like "6.6 build 002"
    build_match = re.search(r'build\s+(\d+)', version, re.IGNORECASE)
    if build_match:
        normalized.append(int(build_match.group(1)))
    
    # Also check for parentheses format like "32.30.0(1575420)"
    paren_match = re.search(r'\((\d+)\)$', version)
    if paren_match:
        normalized.append(int(paren_match.group(1)))
    
    return normalized

def get_highest_version(versions: list[str]) -> str | None:
    if not versions:
        return None
    highest_version = versions[0]
    for v in versions[1:]:
        if normalize_version(v) > normalize_version(highest_version):
            highest_version = v
    return highest_version

def get_supported_version(package_name: str, cli: str, patches: str) -> Optional[str]:
    # Detect CLI version
    is_v6 = "6." in cli and "revanced" in cli.lower()

    if is_v6:
        # v6.0.0+ Syntax: requires -p (patches) and -b (bypass-verification)
        cmd = [
            'java', '-jar', cli,
            'list-versions',
            '-f', package_name,
            '-p', patches,
            '-b'
        ]
    else:
        # Legacy Syntax
        cmd = [
            'java', '-jar', cli,
            'list-versions',
            '-f', package_name,
            patches
        ]

    output = run_process(cmd, capture=True, silent=True)

    if not output:
        logging.warning(f"No output returned from list-versions for {package_name}")
        return None

    lines = output.splitlines()
    versions = []
    # Regex to catch version patterns like 10.1.2 or 32.30.0(12345)
    version_pattern = re.compile(r'\d+(\.\d+)+(\(\d+\))?(\sbuild\s\d+)?')

    for line in lines:
        line = line.strip()
        if line and 'Any' not in line and 'Package' not in line:
            match = version_pattern.search(line)
            if match:
                # Extract only the version part if build info is separate
                versions.append(match.group())

    if not versions:
        logging.warning(f"No compatible versions found in CLI output for {package_name}")
        return None

    logging.info(f"CLI parsed compatible versions: {versions}")
    return get_highest_version(versions)

def extract_filename(response, fallback_url=None) -> str:
    cd = response.headers.get('content-disposition')
    if cd:
        _, params = parse_header(cd)
        filename = params.get('filename') or params.get('filename*')
        if filename:
            return unquote(filename)

    parsed = urlparse(response.url)
    query_params = parse_qs(parsed.query)
    rcd = query_params.get('response-content-disposition')
    if rcd:
        _, params = parse_header(unquote(rcd[0]))
        filename = params.get('filename') or params.get('filename*')
        if filename:
            return unquote(filename)

    path = urlparse(fallback_url or response.url).path
    return unquote(Path(path).name)

def detect_github_release(user: str, repo: str, tag: str) -> dict:
    repo_obj = gh.get_repo(f"{user}/{repo}")

    if tag == "latest":
        release = repo_obj.get_latest_release()
        logging.info(f"Fetched latest release: {release.tag_name}")
        return release.raw_data

    if tag in ["", "dev", "prerelease"]:
        releases = list(repo_obj.get_releases())
        if not releases:
            raise ValueError(f"No releases found for {user}/{repo}")

        if tag == "":
            release = max(releases, key=lambda x: x.created_at)
        elif tag == "dev":
            devs = [r for r in releases if 'dev' in r.tag_name.lower()]
            if not devs:
                raise ValueError(f"No dev release found for {user}/{repo}")
            release = max(devs, key=lambda x: x.created_at)
        else:
            pres = [r for r in releases if r.prerelease]
            if not pres:
                raise ValueError(f"No prerelease found for {user}/{repo}")
            release = max(pres, key=lambda x: x.created_at)

        logging.info(f"Fetched release: {release.tag_name}")
        return release.raw_data

    try:
        release = repo_obj.get_release(tag)
        logging.info(f"Fetched release: {release.tag_name}")
        return release.raw_data
    except Exception as e:
        logging.error(f"Error fetching release {tag} for {user}/{repo}: {e}")
        raise

def detect_source_type(cli_file: Path, patches_file: Path) -> str:
    """Detect if we're using Morphe or ReVanced based on downloaded files"""
    if cli_file and "morphe" in cli_file.name.lower() and patches_file and patches_file.suffix == ".mpp":
        return "morphe"
    elif cli_file and "revanced" in cli_file.name.lower() and patches_file and patches_file.suffix in [".jar", ".rvp"]:
        return "revanced"
    return "unknown"
