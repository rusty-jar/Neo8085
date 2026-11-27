"""Version information for Neo8085."""

# Semantic versioning: MAJOR.MINOR.PATCH
__version__ = "2.0.1"

# 'alpha', 'beta', 'rc' or 'final'
__release_status__ = "final"

# YYYYMMDD
__build_date__ = "20261127"

# Distinguishes builds made on the same day
__build_number__ = 1

__build__ = f"{__build_date__}.{__build_number__}"

version_info = f"{__version__}"
if __release_status__ != "final":
    version_info += f"-{__release_status__}"

version_string = f"{version_info} (build {__build__})"

# Shown in the About dialog
display_version = version_info
