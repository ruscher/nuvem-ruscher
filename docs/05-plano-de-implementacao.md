# 05 — Plano de implementação

Legenda: `[x]` feito e verificado · `[ ]` pendente · `[~]` parcial (ver nota).

## Fase 0 — Pesquisa e documentação
- [x] Pesquisa oficial do Immich registrada (`01`)
- [x] Visão, arquitetura, design, armazenamento, plano, testes, empacotamento
- [x] Hipóteses críticas validadas offline (aspas no systemd, `\x20`, merge do override,
      código de saída do `findmnt --verify`)

**Pronto quando:** os 8 documentos existem e as decisões de risco foram testadas.

## Fase 1 — Núcleo (`core/`) e testes
- [ ] `validation`, `escaping` (fstab, systemd)
- [ ] `storage` (findmnt/lsblk, avisos por FS, biblioteca existente)
- [ ] `fstab` (opções por FS, entradas existentes)
- [ ] `docker` (ps/inspect/stats/events, `sg docker`)
- [ ] `compose` (plano de download, progresso JSON)
- [ ] `system` (RAM, CPU, porta, internet, fuso, GPU, firewall, IP, Tailscale)
- [ ] `releases` (comparação, notas, mudanças incompatíveis)
- [ ] `immich_api`, `config`, `helper_protocol`

**Pronto quando:** `pytest` verde, `ruff check` sem avisos, tipagem nos módulos.

## Fase 2 — Helper privilegiado + polkit
- [ ] Todas as ações da tabela do `02`, com validação
- [ ] Modo simulado com raiz-sandbox e comandos falsos
- [ ] Geração de `.env`, override e unidade; `fstab-add/remove` com rollback
- [ ] `update` com snapshot e rollback; `uninstall` preservando dados
- [ ] Política polkit com `argv1`

**Pronto quando:** `shellcheck` limpo; testes do helper simulado verdes, incluindo
`docker compose config` e `systemd-analyze verify` nos arquivos gerados.

## Fase 3 — Interface: assistente
- [ ] Janela, CSS, ícone, ilustrações
- [ ] 8 telas com navegação, teclado e breakpoints
- [ ] Instalação com progresso real, cancelar e retomar
- [ ] Conta via API; celular com QR; celebração

**Pronto quando:** fluxo completo em `--simular` sem travar, em claro e escuro, largo e
estreito.

## Fase 4 — Interface: painel
- [ ] Visão geral ao vivo (`docker events`), métricas e disco
- [ ] Celular, Registros (filtro/copiar), Backups, Atualizações, Mais
- [ ] Desinstalar com texto explícito sobre as fotos

**Pronto quando:** todas as abas funcionam em `--simular` e cenários de erro exibem
mensagens humanas.

## Fase 5 — i18n, empacotamento, README
- [ ] `po/` (pot + pt_BR), `.desktop`, metainfo validada (`appstreamcli`)
- [ ] `Makefile` e `PKGBUILD`; instalar e remover com pacman
- [ ] `README.md` com screenshots

## Fase 6 — Validação real (com autorização)
- [ ] Instalação real; API em `http://localhost:2283`
- [ ] Arquivo enviado aparece em `/run/media/ruscher/Novo volume/immich-ruscher/`
- [ ] Banco em `/var/lib/nuvem-ruscher/immich/postgres`
- [ ] Reboot com disco: sobe; sem disco: não sobe
