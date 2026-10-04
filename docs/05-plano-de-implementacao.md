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
- [x] `po/` (pot + pt_BR), `.desktop`, metainfo validada (`appstreamcli`)
- [x] `Makefile` e `PKGBUILD`; instalar e remover com pacman
- [x] `README.md` com screenshots

## Fase 6 — Validação real (com autorização)
- [ ] Instalação real; API em `http://localhost:2283`
- [ ] Arquivo enviado aparece em `/run/media/ruscher/Novo volume/immich-ruscher/`
- [ ] Banco em `/var/lib/nuvem-ruscher/immich/postgres`
- [ ] Reboot com disco: sobe; sem disco: não sobe

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
