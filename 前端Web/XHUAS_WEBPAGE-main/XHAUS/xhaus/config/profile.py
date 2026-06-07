"""Profile configuration facade — public entry for the config layer."""

from xhaus.config.errors import (
    ProfileConfigError,
    ProfileDirectoryError,
    ProfileNotFoundError,
)
from xhaus.config.loader import (
    available_presets,
    load_from_directory,
    load_preset,
    load_profile,
)
from xhaus.config.models import (
    PROFILE_DOCUMENT_ORDER,
    Profile,
    ProfileDocument,
    ProfileDocumentKind,
    ProfileLoadResult,
    ProfileSource,
)
from xhaus.config.paths import (
    default_custom_profiles_root,
    list_preset_names,
    presets_root,
    resolve_custom_path,
    resolve_preset_path,
)
from xhaus.config.validation import (
    collect_warnings,
    missing_document_message,
    validate_directory_structure,
    validate_profile,
)

__all__ = [
    "PROFILE_DOCUMENT_ORDER",
    "Profile",
    "ProfileConfigError",
    "ProfileDirectoryError",
    "ProfileDocument",
    "ProfileDocumentKind",
    "ProfileLoadResult",
    "ProfileNotFoundError",
    "ProfileSource",
    "available_presets",
    "collect_warnings",
    "default_custom_profiles_root",
    "list_preset_names",
    "load_from_directory",
    "load_preset",
    "load_profile",
    "missing_document_message",
    "presets_root",
    "resolve_custom_path",
    "resolve_preset_path",
    "validate_directory_structure",
    "validate_profile",
]
