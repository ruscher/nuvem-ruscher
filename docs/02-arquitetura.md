# 02 — Arquitetura

## Visão em camadas

```
┌──────────────────────── usuário comum (ruscher) ─────────────────────────┐
│  Interface GTK4 + libadwaita (Python)                                    │
│   ui/  ── telas do assistente e do painel                                │
│    │                                                                     │
│    ▼                                                                     │
│  backend/  ── fachada única: RealBackend  |  SimulatedBackend (--simular)│
│    │            │                │                  │                    │
│    │      core/ (lógica pura,    │ docker CLI       │ HTTP (urllib)      │
│    │      tipada, sem Gtk)       │ (grupo docker)   │ localhost:2283     │
│    │                             │ ps/logs/stats/   │ GitHub API         │
│    ▼                             │ events/pull      │                    │
│  pkexec /usr/lib/nuvem-ruscher/nuvem-ruscher-helper <ação> <args>        │
└────┼─────────────────────────────────────────────────────────────────────┘
     │ polkit (io.github.ruscher.NuvemRuscher.*)
┌────▼──────────────────────────── root ───────────────────────────────────┐
│  Helper Bash (lista fechada de ações, argumentos validados)              │
│   ├─ pacman / systemctl / gpasswd / ufw|firewall-cmd                     │
│   ├─ /etc/fstab (backup → edição → findmnt --verify → rollback)          │
│   ├─ /var/lib/nuvem-ruscher/immich/{docker-compose*.yml,.env,postgres}   │
│   ├─ /etc/nuvem-ruscher/nuvem-ruscher.conf (configuração pública)        │
│   └─ /etc/systemd/system/nuvem-ruscher-immich.service                    │
└──────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
   systemd ──► docker compose up (primeiro plano) ──► 4 containers
               (BindsTo= disco de fotos, sem restart do Docker)
```

## Estrutura de pastas

```
nuvem-ruscher/
├── bin/nuvem-ruscher                 lançador (funciona do código-fonte e instalado)
├── nuvem_ruscher/
│   ├── __init__.py                   versão e APP_ID
│   ├── __main__.py                   python3 -m nuvem_ruscher
│   ├── main.py                       argumentos (--simular, --cenario), i18n, inicia o app
│   ├── i18n.py                       gettext (domínio "nuvem-ruscher")
│   ├── constants.py                  caminhos fixos, nomes de containers, URLs
│   ├── async_utils.py                threads + GLib.idle_add, processo com streaming
│   ├── core/                         ── lógica pura, 100% testável, tipada ──
│   │   ├── validation.py             caminhos, versões, e-mail, senha, UUID
│   │   ├── escaping.py               fstab (\040), aspas systemd, nomes de unidade
│   │   ├── storage.py                findmnt/lsblk → Volume; avisos por FS; biblioteca existente
│   │   ├── fstab.py                  opções por FS; leitura de entradas existentes
│   │   ├── compose.py                plano de download (cópia legível), progresso JSON
│   │   ├── docker.py                 parse de ps/inspect/stats/events; prefixo `sg docker`
│   │   ├── system.py                 RAM, CPU, porta, internet, fuso, GPU, firewall, IP, Tailscale
│   │   ├── releases.py               releases do GitHub, comparação, mudanças incompatíveis
│   │   ├── immich_api.py             ping, versão, config, admin-sign-up, login, api-keys, stats
│   │   ├── config.py                 leitura de /etc/nuvem-ruscher/*.conf e estado do usuário
│   │   └── helper_protocol.py        protocolo de linhas @@ do helper; erros → texto humano
│   ├── backend/
│   │   ├── base.py                   interface `Backend` (Protocol)
│   │   ├── real.py                   execução real
│   │   └── simulated.py              tudo fingido, com cenários
│   └── ui/
│       ├── application.py            Adw.Application, ações, CSS
│       ├── window.py                 janela, toasts, troca assistente ↔ painel
│       ├── style.css
│       ├── widgets/                  CheckRow, QrCode, Confetti, StepHeader…
│       ├── wizard/                   8 telas do assistente
│       └── dashboard/                painel (6 abas)
├── helper/nuvem-ruscher-helper       Bash, shellcheck limpo
├── data/                             .desktop, metainfo, polkit, ícones, ilustrações
├── po/                               nuvem-ruscher.pot, pt_BR.po, LINGUAS, POTFILES
├── tests/                            pytest (core + helper simulado)
├── packaging/                        PKGBUILD, nuvem-ruscher.install
├── Makefile                          install/uninstall/test/lint/pot
└── docs/
```

## Arquivos em tempo de execução

| Caminho | Dono / modo | Conteúdo |
|---|---|---|
| `/var/lib/nuvem-ruscher/immich/` | root 755 | diretório do projeto Compose |
| `…/docker-compose.yml` | root 644 | **oficial, intocado**, da release fixada |
| `…/docker-compose.override.yml` | root 644 | personalizações (restart, binds seguros, GPU) |
| `…/.env` | root **600** | inclui `DB_PASSWORD` |
| `…/postgres/` | uid 999 700 | banco (disco interno) |
| `…/postgres.anterior/` | uid 999 | snapshot da última atualização (rollback) |
| `…/rollback/` | root | compose/.env da versão anterior |
| `/etc/nuvem-ruscher/nuvem-ruscher.conf` | root 644 | configuração **sem segredos**, lida pela interface |
| `/etc/systemd/system/nuvem-ruscher-immich.service` | root 644 | unidade do stack |
| `/etc/systemd/system/<unidade-de-montagem>.wants/` | root | inicia o serviço quando o disco monta |
| `~/.config/nuvem-ruscher/state.json` | usuário 600 | progresso do assistente, preferências |
| `~/.config/nuvem-ruscher/api-key` | usuário 600 | chave **só de estatísticas** do Immich |
| `~/.cache/nuvem-ruscher/` | usuário | cache de releases, plano de download |
| `UPLOAD_LOCATION/backups/nuvem-ruscher/` | — | backups manuais do banco (outro disco) |

## Módulos e fluxo de dados

- **`core/`** não importa Gtk. Funções recebem texto/estruturas e devolvem
  dataclasses. É o que os testes cobrem.
- **`backend/`** é a única camada que executa coisas. A interface nunca chama
  `subprocess` diretamente. `--simular` troca `RealBackend` por `SimulatedBackend`
  — mesma interface, mesmas telas.
- **`async_utils.run_async(fn, on_done, on_error)`**: executa `fn` numa thread e
  entrega o resultado na thread da interface via `GLib.idle_add`.
  **`StreamingProcess`**: `Popen` + thread leitora; cada linha vira um callback na
  thread da interface; `cancel()` envia SIGTERM ao processo (só a processos do próprio
  usuário — ver ADR-006).
- **Status ao vivo**: um processo `docker events --filter label=com.docker.compose.project=immich`
  fica aberto; cada evento dispara um `docker ps`/`inspect`. CPU/RAM vêm de
  `docker stats --no-stream` a cada 5 s **só enquanto a aba está visível e a janela
  ativa**. Sem polling quando nada muda.

## Helper privilegiado

`/usr/lib/nuvem-ruscher/nuvem-ruscher-helper <ação> [args…]`

| Ação | Argumentos | O que faz | Polkit |
|---|---|---|---|
| `install-docker` | — | `pacman -S --needed --noconfirm docker docker-compose` + habilita | admin |
| `enable-docker` | — | `systemctl enable --now docker.service` | admin |
| `add-docker-group` | — | `gpasswd -a <usuário do PKEXEC_UID> docker` | admin |
| `firewall-allow` | — | libera `2283/tcp` no ufw ou firewalld | admin |
| `fstab-add` | `<uuid> <ponto-de-montagem>` | backup, linha por UUID, verify, rollback | admin |
| `fstab-remove` | `<uuid>` | remove **só** a linha marcada pelo app | admin |
| `setup` | `<versão> <pasta-fotos> <fuso> <transcode> <ml>` | baixa compose oficial, escreve `.env`/override/conf/unidade, habilita | admin |
| `start` / `stop` / `restart` | — | `systemctl … nuvem-ruscher-immich.service` | ativo local: sim |
| `backup-db` | — | `pg_dump` oficial → `UPLOAD_LOCATION/backups/nuvem-ruscher/` | admin |
| `update` | `<versão>` | backup → snapshot → troca → saúde → rollback se falhar | admin |
| `uninstall` | `[--remove-images]` | para, remove unidade/containers/compose; **mantém fotos, banco e .env** | admin |

Regras do helper:

- `set -Eeuo pipefail`, `umask 077`, `PATH` fixo, `LC_ALL=C`.
- O usuário-alvo vem **somente** de `PKEXEC_UID` (nunca de argumento).
- Cada argumento passa por validação com regex/listas fechadas antes de qualquer uso.
- Toda saída para a interface segue um protocolo de linhas:
  `@@STEP <id>`, `@@INFO <texto>`, `@@PROGRESS <0-100>`, `@@RESULT <chave>=<valor>`,
  `@@ERROR <código> <texto técnico>`. Linhas sem `@@` são log técnico.
- Arquivos são escritos em temporário no mesmo diretório e movidos (`mv`) — atômico.
- Modo simulado (`NUVEM_RUSCHER_SIM_ROOT`) só é aceito quando **não** está rodando como
  root nem via pkexec (o pkexec limpa o ambiente de qualquer forma).

## Unidade systemd (gerada pelo helper)

```ini
[Unit]
Description=Nuvem Ruscher: servidor de fotos Immich
Documentation=https://docs.immich.app
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
BindsTo=run-media-ruscher-Novo\x20volume.mount
After=run-media-ruscher-Novo\x20volume.mount
RequiresMountsFor="/run/media/ruscher/Novo volume/immich-ruscher" /var/lib/nuvem-ruscher/immich
StartLimitIntervalSec=15min
StartLimitBurst=10

[Service]
Type=exec
WorkingDirectory=/var/lib/nuvem-ruscher/immich
ExecStartPre=/usr/bin/mountpoint -q "/run/media/ruscher/Novo volume"
ExecStartPre=/usr/bin/test -d "/run/media/ruscher/Novo volume/immich-ruscher"
ExecStart=/usr/bin/docker compose up --pull never --abort-on-container-exit --remove-orphans
ExecStop=/usr/bin/docker compose stop
SuccessExitStatus=143
Restart=always
RestartSec=10s
TimeoutStopSec=3min

[Install]
WantedBy=multi-user.target
```

- `BindsTo=` + `After=` na unidade de montagem: sem disco, o serviço não sobe; se o
  disco for desmontado, o serviço para **antes** (libera o disco).
- `RequiresMountsFor=` com **aspas** (validado: sem aspas o systemd parte o caminho
  no espaço e ignora “volume/immich-ruscher”).
- `ExecStartPre` com `mountpoint` e `test -d`: barreira extra, sem depender do app.
- `--pull never`: o boot nunca depende de internet.
- `--abort-on-container-exit` + `Restart=always`: se qualquer container morrer, o
  systemd reinicia o conjunto todo (com limite de 10 tentativas em 15 min).
- O override faz o `immich-server` esperar o banco **saudável** (`depends_on` com
  `condition: service_healthy`). Descoberto na instalação real: sem isso, na primeira subida
  o Postgres reinicia ao terminar o `initdb`, o servidor recebe “connection refused” e cai
  (no compose oficial o Docker o reiniciaria; aqui quem reinicia é o systemd).
- A unidade não chama o helper: o servidor continua funcionando mesmo se o app for
  removido.
- Quando a pasta de fotos está no disco do sistema, as linhas `BindsTo`/`mountpoint`
  são omitidas.

## Registro de decisões (ADR)

**ADR-001 — Python + GTK4/libadwaita sem etapa de build.** Pacotes oficiais
(`python-gobject`, `libadwaita`, `python-qrcode`, `python-yaml`). O código é instalado
em `/usr/share/nuvem-ruscher` e executado diretamente; só as traduções (`.mo`) são
compiladas no `PKGBUILD`. Sem Blueprint/Meson para reduzir dependências.

**ADR-002 — Um único helper Bash via pkexec com `argv1`.** O polkit escolhe a ação
pelo primeiro argumento (`org.freedesktop.policykit.exec.argv1`). Isso permite que
`start`/`stop`/`restart` não peçam senha a quem já está na sessão ativa local (quem
está no grupo `docker` já pode parar containers; não há ganho de privilégio), enquanto
fstab, pacotes e configuração exigem senha de administrador (`auth_admin_keep`).

**ADR-003 — systemd controla o stack, Docker não reinicia nada.** O override troca
`restart: always` por `restart: "no"`. Senão, o Docker sobe os containers no boot
antes do disco existir e grava fotos numa pasta vazia no disco do sistema.
`docker compose up` em primeiro plano dá supervisão real ao systemd.

**ADR-004 — Três barreiras contra “pasta vazia no lugar errado”.**
(1) `BindsTo`/`RequiresMountsFor`; (2) `ExecStartPre=mountpoint`; (3) bind de `/data`
com `create_host_path: false` no override — o Docker falha em vez de criar a pasta.
Além disso, `UPLOAD_LOCATION` aponta para uma **subpasta** (`immich-ruscher`), que não
existe quando o disco não está montado.

**ADR-005 — Banco sempre no disco interno.** `/var/lib/nuvem-ruscher/immich/postgres`.
A documentação oficial diz que o banco não funciona em NTFS/exFAT/FAT e não deve ficar
em rede. Também separa fisicamente banco e backups do banco (que vão para o disco de
fotos).

**ADR-006 — Download das imagens como usuário.** O `.env` é 600 (root). Para ter
progresso real **e cancelamento**, a interface copia `docker-compose.yml` e o override
(legíveis) para `~/.cache/nuvem-ruscher/plano/`, cria um `.env` **sem segredos** com os
mesmos valores públicos e roda `docker compose --progress json pull` como usuário (grupo
`docker`). As imagens resultantes são idênticas. Cancelar = SIGTERM no próprio processo.

**ADR-007 — Versão fixada.** `IMMICH_VERSION=vX.Y.Z` exato. Atualizar é uma ação
explícita com backup, snapshot e rollback.

**ADR-008 — Rollback por snapshot do diretório do banco.** Antes de atualizar:
`pg_dump` (seguro) **e** `cp -a --reflink=auto postgres postgres.anterior` com o serviço
parado (instantâneo em btrfs). Se a nova versão não ficar saudável em 15 min, o helper
para, move o banco novo para `postgres.falhou-<data>` (nunca apaga), restaura o snapshot
e a versão anterior. A remoção do snapshot antigo é a **única** remoção recursiva do
projeto: caminho montado só de constantes, com verificações (não é link, não é ponto de
montagem, está dentro de `/var/lib/nuvem-ruscher/immich`) e `--one-file-system`.

**ADR-009 — Textos-fonte em pt-BR.** O produto nasce em português; os `msgid` são em
pt-BR e o `.pot` é gerado para outras línguas. Evita a interface cair em inglês caso o
`.mo` falte.

**ADR-010 — Chave de API mínima para estatísticas.** Após criar o administrador, o app
cria uma chave com permissões apenas de leitura do servidor e guarda em arquivo 600 no
perfil do usuário (KWallet/Secret Service evitados para não abrir diálogos inesperados
no KDE). A senha do administrador nunca é armazenada.

**ADR-011 — `ntfs-3g` no fstab para NTFS.** É o mesmo driver que o udisks2 usa hoje
nesta máquina (`fuseblk`), então o comportamento após o boot é idêntico ao atual.
`findmnt --verify` emite 2 avisos conhecidos para `ntfs-3g` (não é módulo do kernel);
o helper reprova apenas por **código de saída** ≠ 0 (erros), não por avisos.
