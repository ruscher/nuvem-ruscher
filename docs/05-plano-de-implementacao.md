# 05 — Plano de implementação

Legenda: `[x]` feito e verificado · `[ ]` pendente · `[~]` parcial (ver nota).

## Fase 0 — Pesquisa e documentação
- [x] Pesquisa oficial do Immich registrada (`01`)
- [x] Visão, arquitetura, design, armazenamento, plano, testes, empacotamento
- [x] Hipóteses críticas validadas offline (aspas no systemd, `\x20`, merge do override,
      código de saída do `findmnt --verify`)

**Pronto quando:** os 8 documentos existem e as decisões de risco foram testadas.

## Fase 1 — Núcleo (`core/`) e testes
- [x] `validation`, `escaping` (fstab, systemd)
- [x] `storage` (findmnt/lsblk, avisos por FS, biblioteca existente)
- [x] `fstab` (opções por FS, entradas existentes)
- [x] `docker` (ps/inspect/stats/events, `sg docker`)
- [x] `compose` (plano de download, progresso JSON)
- [x] `system` (RAM, CPU, porta, internet, fuso, GPU, firewall, IP, Tailscale)
- [x] `releases` (comparação, notas, mudanças incompatíveis)
- [x] `immich_api`, `config`, `helper_protocol`

**Pronto quando:** `pytest` verde, `ruff check` sem avisos, tipagem nos módulos.

## Fase 2 — Helper privilegiado + polkit
- [x] Todas as ações da tabela do `02`, com validação
- [x] Modo simulado com raiz-sandbox e comandos falsos
- [x] Geração de `.env`, override e unidade; `fstab-add/remove` com rollback
- [x] `update` com snapshot e rollback; `uninstall` preservando dados
- [x] Política polkit com `argv1`

**Pronto quando:** `shellcheck` limpo; testes do helper simulado verdes, incluindo
`docker compose config` e `systemd-analyze verify` nos arquivos gerados.

## Fase 3 — Interface: assistente
- [x] Janela, CSS, ícone, ilustrações
- [x] 8 telas com navegação, teclado e breakpoints
- [x] Instalação com progresso real, cancelar e retomar
- [x] Conta via API; celular com QR; celebração

**Pronto quando:** fluxo completo em `--simular` sem travar, em claro e escuro, largo e
estreito.

## Fase 4 — Interface: painel
- [x] Visão geral ao vivo (`docker events`), métricas e disco
- [x] Celular, Registros (filtro/copiar), Backups, Atualizações, Mais
- [x] Desinstalar com texto explícito sobre as fotos

**Pronto quando:** todas as abas funcionam em `--simular` e cenários de erro exibem
mensagens humanas.

## Fase 5 — i18n, empacotamento, README
- [x] `po/nuvem-ruscher.pot` (textos-fonte em pt-BR, ADR-009), `.desktop`, metainfo validada
- [x] `Makefile` e `PKGBUILD`; pacote gerado com `makepkg`
- [x] Instalar, remover e reinstalar com pacman (102 arquivos saem; o servidor segue no ar)
- [x] `README.md` com screenshots

## Fase 6 — Validação real (com autorização, 04/10/2026)
- [x] Instalação real (Immich v3.2.4); API em `http://localhost:2283` → `{"res":"pong"}`
- [x] O Immich criou `library/`, `upload/`, `thumbs/`, `encoded-video/`, `profile/`, `backups/`
      (com `.immich`) em `/run/media/ruscher/Novo volume/immich-ruscher/`; o container vê `/data`
      como FUSE (o NTFS). Envio de foto pelo celular: depende da conta, que fica com o usuário.
- [x] Banco em `/var/lib/nuvem-ruscher/immich/postgres` (314 MB, NVMe interno, btrfs)
- [x] Download das imagens pelo código do app: 1,1 GB em 36 s, sem erros
- [x] Interface real retomou a instalação e chegou à tela de Conta; painel real com métricas
- [x] Montagem no boot: linha no fstab (backup `/etc/fstab.nuvem-ruscher-20261004-013247.bak`),
      `findmnt --verify` sem erros, unidade gerada com `SourcePath=/etc/fstab`, serviço habilitado
- [x] Backup real do banco: 18,6 MB, `gzip -t` ok, gravado no disco das fotos
- [ ] Reboot com disco: sobe — **a fazer pelo usuário** (roteiro abaixo)
- [ ] Reboot sem disco: não sobe e não cria pasta — **a fazer pelo usuário**

### Problemas encontrados na instalação real (e corrigidos)

| Problema | Correção |
|---|---|
| Primeira subida caiu: o Postgres reinicia ao fim do `initdb` e o `immich_server` encerrava com `ECONNREFUSED`, derrubando o conjunto | override com `depends_on: database: condition: service_healthy`; limite de reinícios 10/15 min |
| Desligar deixava a unidade “failed” (o compose sai com 143 no SIGTERM) | `SuccessExitStatus=143` |
| Ao retomar, a etapa já feita aparecia cinza | marcada como “Já feito” |
| Cartão de fotos dizia “Disponível com o servidor ligado” com o servidor ligado (falta a conta) | “Conecte sua conta para ver” |
| Com o disco no fstab, conectá-lo **depois** do boot não montaria (o udisks montaria como usuário e falharia) | `x-systemd.wanted-by=<dispositivo>`: o systemd monta ao aparecer; linha substituída no sistema real |

### Roteiro de reinicialização (para o usuário)

1. **Com o disco conectado:** reinicie; antes de entrar na sessão (ou logo depois), rode
   `systemctl status nuvem-ruscher-immich` → `active (running)`; `curl localhost:2283/api/server/ping`.
2. **Sem o disco:** desligue, desconecte o “Novo volume”, ligue. O boot não trava (`nofail`, 15 s).
   `systemctl status nuvem-ruscher-immich` → não iniciado por dependência; `ls /run/media/ruscher/`
   não deve ter `Novo volume/immich-ruscher`. Conecte o disco: o serviço liga sozinho.

## Registro de execução

- **Testes:** 175 testes `pytest` (núcleo, helper em sandbox com espaço no caminho, modo simulado
  sem processos, importação da interface). `ruff`, `shellcheck`, `desktop-file-validate` e
  `appstreamcli` sem erros (`make lint`).
- **Interface:** percorrida inteira em `--simular` por `tools/tour.py` em tema claro, escuro e
  janela estreita; cenários de erro capturados (sem Docker, porta ocupada, disco ausente, FAT32,
  atualização com mudanças incompatíveis).
- **Pacote:** `makepkg` gera `nuvem-ruscher-1.0.0-1-any.pkg.tar` (o `namcap` só acusa falsos
  positivos de módulos Python privados em `/usr/share/nuvem-ruscher`).

### Descobertas que mudaram o código

| Descoberta | Correção |
|---|---|
| `RequiresMountsFor=` sem aspas parte o caminho no espaço (“volume/immich-ruscher” ignorado) | aspas + teste com `systemd-analyze verify` |
| Com `LC_ALL=C`, o `findmnt` escreve “ç” como `\xc3\xa7` | helper usa `LC_ALL=C.UTF-8` |
| O `/tmp` do BigLinux é `noexec`: comandos falsos da sandbox não rodavam e o bash caía nos reais | helper simulado **recusa rodar** se qualquer comando perigoso não for o falso; sandbox em `build/` |
| A saída YAML do `docker compose config` quebra linhas longas nos espaços | testes usam `--format json` |
| `IMMICH_MACHINE_LEARNING_ENABLED` não existe na v3 | ML desligado via `profiles` + `/api/system-config` |
| O SVG com `<filter>` vira um retângulo cinza no renderizador do GTK | sombras desenhadas como formas |
| `AdwStatusPage` dentro de outra rolagem esconde título e botões | `StatusBlock` próprio |
| O total de bytes do pull só é conhecido quando cada camada começa (porcentagem “mentia” para cima) | progresso por camada |
