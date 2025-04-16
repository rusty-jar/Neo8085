"""Version information for Neo8085."""

# Use semantic versioning (MAJOR.MINOR.PATCH)
# - MAJOR: incompatible API changes
# - MINOR: new functionality, backwards-compatible
# - PATCH: bug fixes, backwards-compatible
__version__ = '1.0.0'

# Release status: 'alpha', 'beta', 'rc', or 'final'
__release_status__ = 'final'

# Build metadata (optional, usually date and/or commit hash)
__build__ = '20250416'  # YYYYMMDD format

# String representation for display purposes
version_info = f"{__version__}"
if __release_status__ != 'final':
    version_info += f"-{__release_status__}"

# Full version string including build metadata
version_string = f"{version_info} (build {__build__})"

# User-friendly display version (for About dialog)
display_version = version_info