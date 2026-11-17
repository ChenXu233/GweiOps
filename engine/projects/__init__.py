# engine/projects/__init__.py
"""项目这一级的值 —— 可见性、默认发布参数、项目级凭据。

放在 `engine/projects` 而不是某个路由里,是因为读它的有两处:控制台的仓库 /
项目列表(可见性)、发布解析(默认参数)。两边读同一份,判据只写一处。
"""

from engine.projects.settings import (
    CREDENTIAL_SCOPE_PREFIX,
    VISIBILITIES,
    ProjectSettings,
    project_of_repo,
    project_settings,
    reload_project_snapshot,
    settings_of_project,
)

__all__ = [
    "CREDENTIAL_SCOPE_PREFIX",
    "VISIBILITIES",
    "ProjectSettings",
    "project_of_repo",
    "project_settings",
    "reload_project_snapshot",
    "settings_of_project",
]
