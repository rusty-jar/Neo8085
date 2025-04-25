"""Version information for Neo8085."""

# Use semantic versioning (MAJOR.MINOR.PATCH)
# - MAJOR: incompatible API changes
# - MINOR: new functionality, backwards-compatible
# - PATCH: bug fixes, backwards-compatible
__version__ = "1.1.3"

# Release status: 'alpha', 'beta', 'rc', or 'final'
__release_status__ = "final"

# Build date in YYYYMMDD format
__build_date__ = "20250425"

# Build number for multiple releases on same day
__build_number__ = 1

# Complete build identifier
__build__ = f"{__build_date__}.{__build_number__}"

# String representation for display purposes
version_info = f"{__version__}"
if __release_status__ != "final":
    version_info += f"-{__release_status__}"

# Full version string including build metadata
version_string = f"{version_info} (build {__build__})"

# User-friendly display version (for About dialog)
display_version = version_info
