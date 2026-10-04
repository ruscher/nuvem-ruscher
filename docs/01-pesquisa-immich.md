# 01 — Pesquisa oficial do Immich

> Consulta feita em **04/10/2026**. Versão estável consultada: **Immich v3.2.4**
> (publicada em 28/09/2026). Pré-releases existentes no momento: v3.3.0-rc.0 a rc.2
> (ignoradas pelo app).
>
> Nada aqui veio de memória: todos os itens foram conferidos nos arquivos da release,
> na documentação oficial ou na especificação OpenAPI da tag `v3.2.4`.

## Fontes

| Fonte | Link |
|---|---|
| Release v3.2.4 | <https://github.com/immich-app/immich/releases/tag/v3.2.4> |
| API de releases (usada pelo app) | <https://api.github.com/repos/immich-app/immich/releases> |
| `docker-compose.yml` da release | <https://github.com/immich-app/immich/releases/download/v3.2.4/docker-compose.yml> |
| `example.env` da release | <https://github.com/immich-app/immich/releases/download/v3.2.4/example.env> |
| `hwaccel.ml.yml` / `hwaccel.transcoding.yml` | mesmos links, mesma pasta de download |
| Instalação com Docker Compose | <https://docs.immich.app/install/docker-compose> |
| Requisitos | <https://docs.immich.app/install/requirements> |
| Backup e restauração | <https://docs.immich.app/administration/backup-and-restore> |
| Especificação OpenAPI (tag v3.2.4) | <https://raw.githubusercontent.com/immich-app/immich/v3.2.4/open-api/immich-openapi-specs.json> |
| Aceleração de ML | <https://docs.immich.app/features/ml-hardware-acceleration> |
| Transcodificação por hardware | <https://docs.immich.app/features/hardware-transcoding> |
| App Android (Play Store) | <https://play.google.com/store/apps/details?id=app.alextran.immich> |
| App Android (F-Droid) | <https://f-droid.org/packages/app.alextran.immich/> (F-Droid já tem a 3.2.4) |

## Arquivos que a release publica

`docker-compose.yml`, `docker-compose.rootless.yml`, `example.env`, `hwaccel.ml.yml`,
`hwaccel.transcoding.yml`, `prometheus.yml` e os APKs Android.

O app baixa sempre o arquivo da **release fixada** (`releases/download/<tag>/...`),
nunca o do branch `main` (o próprio arquivo avisa que o `main` pode ser incompatível).

## `docker-compose.yml` (v3.2.4, na íntegra, sem os comentários do topo)

```yaml
name: immich

services:
  immich-server:
    container_name: immich_server
    image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION:-release}
    # extends:
    #   file: hwaccel.transcoding.yml
    #   service: cpu # set to one of [nvenc, quicksync, rkmpp, vaapi, vaapi-wsl] for accelerated transcoding
    volumes:
      # Do not edit the next line. If you want to change the media storage location on your system, edit the value of UPLOAD_LOCATION in the .env file
      - ${UPLOAD_LOCATION}:/data
      - /etc/localtime:/etc/localtime:ro
    env_file:
      - .env
    ports:
      - '2283:2283'
    depends_on:
      - redis
      - database
    restart: always
    healthcheck:
      disable: false

  immich-machine-learning:
    container_name: immich_machine_learning
    # For hardware acceleration, add one of -[armnn, cuda, rocm, openvino, rknn] to the image tag.
    # Example tag: ${IMMICH_VERSION:-release}-cuda
    image: ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION:-release}
    # extends: # uncomment this section for hardware acceleration - see https://docs.immich.app/features/ml-hardware-acceleration
    #   file: hwaccel.ml.yml
    #   service: cpu # set to one of [armnn, cuda, rocm, openvino, openvino-wsl, rknn] for accelerated inference - use the `-wsl` version for WSL2 where applicable
    volumes:
      - model-cache:/cache
    env_file:
      - .env
    restart: always
    healthcheck:
      disable: false

  redis:
    container_name: immich_redis
    image: docker.io/valkey/valkey:9@sha256:70739f85ad2ee01a726a965584a0f94895f01b0c60b3cc8b0aeef11eaa6888cf
    healthcheck:
      test: redis-cli ping | grep -q PONG || exit 1
    restart: always

  database:
    container_name: immich_postgres
    image: ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_USER: ${DB_USERNAME}
      POSTGRES_DB: ${DB_DATABASE_NAME}
      POSTGRES_INITDB_ARGS: '--data-checksums'
      # Uncomment the DB_STORAGE_TYPE: 'HDD' var if your database isn't stored on SSDs
      # DB_STORAGE_TYPE: 'HDD'
    volumes:
      # Do not edit the next line. If you want to change the database storage location on your system, edit the value of DB_DATA_LOCATION in the .env file
      - ${DB_DATA_LOCATION}:/var/lib/postgresql/data
    shm_size: 128mb
    restart: always
    healthcheck:
      disable: false

volumes:
  model-cache:
```

Observações que viraram decisões do app:

- **Nome do projeto Compose:** `immich`. Os containers têm nomes fixos:
  `immich_server`, `immich_machine_learning`, `immich_redis`, `immich_postgres`.
- **Todos os serviços usam `restart: always`.** O app neutraliza isso no
  `docker-compose.override.yml` (`restart: "no"`), porque quem manda é o systemd
  (veja ADR-003 em `02-arquitetura.md`).
- O servidor lê o `.env` inteiro como `env_file`, então `TZ` vai pelo `.env`.
- Valkey e Postgres são fixados por digest `sha256` — reprodutível.

## `example.env` (v3.2.4, na íntegra)

```ini
# You can find documentation for all the supported env variables at https://docs.immich.app/install/environment-variables

# The location where your uploaded files are stored
UPLOAD_LOCATION=./library

# The location where your database files are stored. Network shares are not supported for the database
DB_DATA_LOCATION=./postgres

# To set a timezone, uncomment the next line and change Etc/UTC to a TZ identifier from this list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List
# TZ=Etc/UTC

# The Immich version to use. You can pin this to a specific version like "v2.1.0"
IMMICH_VERSION=v3

# Connection secret for postgres. You should change it to a random password
# Please use only the characters `A-Za-z0-9`, without special characters or spaces
DB_PASSWORD=postgres

# The values below this line do not need to be changed
###################################################################################
DB_USERNAME=postgres
DB_DATABASE_NAME=immich
```

Decisões:

- `IMMICH_VERSION` é **fixado na tag exata** (ex.: `v3.2.4`), não em `v3`, para que
  atualizações só aconteçam quando o usuário pedir (e com backup + rollback).
- `DB_PASSWORD`: 32 caracteres de `[A-Za-z0-9]`, gerados com `/dev/urandom`.
- Valores com espaço vão **entre aspas duplas**. Verificado com
  `docker compose config`: `UPLOAD_LOCATION="/run/media/ruscher/Novo volume/immich-ruscher"`
  chega intacto ao container.

## Caminho interno do volume de upload

`${UPLOAD_LOCATION}:/data` → dentro do container, a biblioteca fica em **`/data`**.
Subpastas criadas pelo Immich: `library`, `upload`, `thumbs`, `encoded-video`,
`profile`, `backups`. Cada uma recebe um arquivo `.immich`, que o servidor usa para
verificar a integridade da montagem — se estiver faltando, o servidor se recusa a
subir. O app usa esses arquivos para **detectar uma biblioteca existente**.

O banco fica em `/var/lib/postgresql/data` dentro do container.

## Porta padrão

`2283` (publicada como `'2283:2283'`). Interface web e API em
`http://<ip>:2283`, API sob o prefixo `/api`.

## Requisitos mínimos de hardware (docs/install/requirements, versão de 28/09/2026)

| Item | Mínimo | Recomendado |
|---|---|---|
| RAM | 6 GB | 8 GB |
| CPU | 2 núcleos | 4 núcleos |
| Arquitetura | amd64 ou arm64 | — |

- Com **4 GB** dá para rodar **com machine learning desativado**.
- Desde a v3, o ML em amd64 exige microarquitetura **x86-64-v2** (CPUs de ~2012 em
  diante). O app verifica a flag `sse4_2`/`popcnt` em `/proc/cpuinfo`.
- Miniaturas e vídeos convertidos somam **10–20 %** do tamanho da biblioteca.
- Banco: tipicamente **1–3 GB**, em **SSD local**, **nunca** em compartilhamento de rede.
- Sistemas de arquivos recomendados: Unix (ext4, ZFS, APFS…) com dono/grupo.
  A documentação diz explicitamente que o **banco** “não funciona em NTFS ou
  exFAT/FAT32”. Isso fundamenta a regra de nunca colocar o Postgres no disco NTFS.
- Requer `docker compose` (plugin). O antigo `docker-compose` não é suportado.

## Endpoints da API usados pelo app (OpenAPI v3.2.4)

| Uso | Método e caminho | Autenticação | Resposta |
|---|---|---|---|
| Saúde / ping | `GET /api/server/ping` | nenhuma | `{"res":"pong"}` |
| Versão do servidor | `GET /api/server/version` | nenhuma | `{"major","minor","patch","prerelease"}` |
| Estado de inicialização | `GET /api/server/config` | nenhuma | `isInitialized` (já existe admin?), `isOnboarded` |
| **Criar o primeiro administrador** | `POST /api/auth/admin-sign-up` | nenhuma | corpo `{"email","name","password"}` → `UserAdminResponseDto` |
| Login | `POST /api/auth/login` | nenhuma | `{"accessToken",...}` |
| Criar chave de API | `POST /api/api-keys` | bearer | corpo `{"name","permissions":[...]}` → `{"secret",...}` |
| Estatísticas (fotos/vídeos/uso) | `GET /api/server/statistics` | admin, permissão `server.statistics` | `{"photos","videos","usage",...}` |
| Armazenamento | `GET /api/server/storage` | permissão `server.storage` | `diskAvailableRaw`, `diskSizeRaw`… |

A criação do administrador **é possível direto pelo app** (`admin-sign-up` não exige
autenticação e só funciona enquanto `isInitialized` for `false`). Depois do cadastro,
o app faz login uma única vez e cria uma chave de API **só de leitura de estatísticas**
(`server.statistics`, `server.storage`, `server.about`, `server.versionCheck`) para
mostrar contagem de fotos no painel. A senha nunca é guardada.

## Backup e restauração oficiais

**Backups automáticos** (feitos pelo próprio Immich): ficam em
`UPLOAD_LOCATION/backups`, diariamente às 2h, mantendo os **14** mais recentes.
Configurável em *Administração → Configurações → Backup*. Nomes no formato
`immich-db-backup-<data>-v<versão>-pg<versão>.sql.gz`.

**Backup manual (Linux), comando oficial:**

```bash
docker exec -t immich_postgres pg_dump --clean --if-exists \
  --dbname=<DB_DATABASE_NAME> --username=<DB_USERNAME> | \
  gzip > "/path/to/backup/dump.sql.gz"
```

O app usa exatamente este comando (sem `-t`, já que não há terminal) e grava em
`UPLOAD_LOCATION/backups/nuvem-ruscher/` — no disco de fotos, ou seja, **em outro
disco físico** que não o do banco.

**Restauração oficial (linha de comando):**

```bash
docker compose down -v
docker compose pull
docker compose create
docker start immich_postgres
sleep 10
gunzip --stdout "/path/to/backup/dump.sql.gz" | \
  sed "s/SELECT pg_catalog.set_config('search_path', '', false);/SELECT pg_catalog.set_config('search_path', 'public, pg_catalog', true);/g" | \
  docker exec -i immich_postgres psql --dbname=<DB_DATABASE_NAME> \
  --username=<DB_USERNAME> --single-transaction --set ON_ERROR_STOP=on
docker compose up -d
```

**Restauração pela interface web** (v3): *Administração → Manutenção → Restaurar
backup do banco*; numa instalação nova, a tela de boas-vindas oferece
**“Restore from backup”** depois de mover as pastas `backups`, `encoded-video`,
`library`, `profile`, `thumbs` e `upload` para o novo `UPLOAD_LOCATION`.
O app aponta para esse fluxo quando detecta biblioteca existente com banco vazio.

**Pastas críticas do disco:** `library`, `upload`, `profile`. Regeneráveis:
`thumbs`, `encoded-video`, `backups`. O backup do banco **não contém fotos**.
A ordem recomendada é banco primeiro, arquivos depois, com o servidor parado.

## Aceleração por hardware

**Transcodificação de vídeo** (`hwaccel.transcoding.yml`): serviços `cpu`, `nvenc`
(reserva de GPU NVIDIA com `gpu, compute, video`), `quicksync` (`/dev/dri`),
`rkmpp`, `vaapi` (`/dev/dri`), `vaapi-wsl`. Além de expor o dispositivo, é preciso
ativar em *Administração → Configurações → Transcodificação de vídeo*.

**Machine learning** (`hwaccel.ml.yml`): `cpu`, `cuda` (NVIDIA), `rocm` (AMD,
`/dev/dri` + `/dev/kfd`, grupo `video`), `openvino` (Intel, `/dev/dri`, regra de
cgroup `c 189:* rmw`, `/dev/bus/usb`), `armnn`, `rknn`, `openvino-wsl`. Requer
trocar a imagem para a tag com sufixo (`-cuda`, `-rocm`, `-openvino`…).

**Como o app usa:** em vez de `extends:` (que exigiria editar o compose oficial),
o app escreve os mesmos `devices`/`group_add`/`image` diretamente no
`docker-compose.override.yml`. Padrão conservador: transcodificação VAAPI ligada se
houver `/dev/dri/renderD*` com GPU Intel/AMD; ML acelerado **desligado** por
padrão (imagens grandes e suporte por GPU variável), disponível em “Opções avançadas”.

## App Android

- ID do pacote: `app.alextran.immich` (Play Store e F-Droid, ambos com 3.2.4).
- Login no app: digitar o endereço do servidor, ex.: `http://192.168.0.10:2283`.
- **O app não tem leitor de QR para o endereço** (pedido aberto na discussão
  [#14763](https://github.com/immich-app/immich/discussions/14763)). Por isso o QR
  do Nuvem Ruscher abre o endereço no navegador do celular (de onde é fácil copiar),
  e um segundo QR leva à loja.

## Marcação de mudanças incompatíveis nas releases

As notas usam o título `### 🚨 Breaking Changes` (vistas em v3.0.0, v3.0.0-rc.0 e
v3.1.0). Algumas versões são puladas (v3.2.3 não existe). O app junta as notas de
todas as releases estáveis entre a versão instalada e a nova e procura títulos com
“breaking”/🚨; mudança de versão principal (v3 → v4) sempre recebe aviso reforçado.
