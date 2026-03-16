def get_supported_version(package_name: str, cli: str, patches: str) -> Optional[str]:
    cli_str = str(cli).lower()
    
    # Extract the FIRST number after "cli-" to get the exact major version safely
    major_version = 0
    if "revanced" in cli_str:
        match = re.search(r'cli-(\d+)', cli_str)
        if match:
            major_version = int(match.group(1))
        elif "6." in cli_str:
            major_version = 6

    if major_version >= 6:
        # v6.0.0+ Syntax: -f <pkg> -b (bypass) -p <patches.rvp>
        cmd = [
            'java', '-jar', str(cli),
            'list-versions',
            '-f', package_name,
            '-b', '-p', str(patches)
        ]
    elif major_version == 4:
        # v4.x Syntax: patches use -b or --patch-bundle (NOT bypass)
        cmd = [
            'java', '-jar', str(cli),
            'list-versions',
            '-f', package_name,
            '-b', str(patches)
        ]
    else:
        # v5.x and Morphe Syntax: patches are positional
        cmd = [
            'java', '-jar', str(cli),
            'list-versions',
            '-f', package_name,
            str(patches)
        ]

    logging.info(f"🚀 Running version check (CLI v{major_version}): {' '.join(cmd)}")
    output = run_process(cmd, capture=True, silent=True)

    if not output:
        logging.warning(f"No output returned from list-versions for {package_name}")
        return None

    lines = output.splitlines()
    versions = []
    version_pattern = re.compile(r'\d+(\.\d+)+')

    for line in lines:
        line = line.strip()
        if not line or any(x in line for x in ['Package name', 'Most common', 'Compatible versions']):
            continue
            
        match = version_pattern.search(line)
        if match:
            versions.append(match.group())

    if not versions:
        logging.warning(f"No compatible versions found in output for {package_name}")
        return None

    return get_highest_version(versions)
