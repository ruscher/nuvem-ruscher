"""Caminhos e nomes fixos. Precisam bater com o helper (helper/nuvem-ruscher-helper)."""

from __future__ import annotations

from typing import Final

IMMICH_PORT: Final = 2283
STACK_DIR: Final = "/var/lib/nuvem-ruscher/immich"
DB_DIR: Final = f"{STACK_DIR}/postgres"
CONF_FILE: Final = "/etc/nuvem-ruscher/nuvem-ruscher.conf"
SERVICE_NAME: Final = "nuvem-ruscher-immich.service"
HELPER_PATH: Final = "/usr/lib/nuvem-ruscher/nuvem-ruscher-helper"
COMPOSE_PROJECT: Final = "immich"

# Containers do docker-compose.yml oficial, na ordem em que aparecem no painel.
CONTAINER_SERVER: Final = "immich_server"
CONTAINER_ML: Final = "immich_machine_learning"
CONTAINER_DB: Final = "immich_postgres"
CONTAINER_REDIS: Final = "immich_redis"
CONTAINERS: Final = (CONTAINER_SERVER, CONTAINER_ML, CONTAINER_DB, CONTAINER_REDIS)

GITHUB_RELEASES_API: Final = "https://api.github.com/repos/immich-app/immich/releases?per_page=40"
RELEASE_DOWNLOAD: Final = "https://github.com/immich-app/immich/releases/download/{tag}/{name}"
RELEASES_PAGE: Final = "https://github.com/immich-app/immich/releases/tag/{tag}"
CONNECTIVITY_URL: Final = "https://api.github.com/zen"

PLAY_STORE_URL: Final = "https://play.google.com/store/apps/details?id=app.alextran.immich"
FDROID_URL: Final = "https://f-droid.org/packages/app.alextran.immich/"
IMMICH_DOCS_URL: Final = "https://docs.immich.app"
TAILSCALE_DOWNLOAD_URL: Final = "https://tailscale.com/download/linux"
PROJECT_URL: Final = "https://github.com/ruscher/nuvem-ruscher"

# Requisitos oficiais (docs.immich.app/install/requirements, consulta de 04/10/2026).
MIN_RAM_GIB: Final = 6
RECOMMENDED_RAM_GIB: Final = 8
ML_OFF_RAM_GIB: Final = 4
MIN_CORES: Final = 2
# Espaço para as imagens Docker (servidor + ML + banco + valkey ≈ 4–5 GB, com folga).
MIN_DOCKER_FREE_GIB: Final = 10

HEALTH_TIMEOUT_S: Final = 600
API_KEY_PERMISSIONS: Final = (
    "server.statistics",
    "server.storage",
    "server.about",
    "server.versionCheck",
)
