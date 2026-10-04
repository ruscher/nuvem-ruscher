# 06 — Testes e QA

## Estratégia

| Camada | Ferramenta | O que cobre |
|---|---|---|
| Núcleo Python | `pytest` | validações, escapes, parsers (findmnt, lsblk, docker, progresso, releases, conf, protocolo do helper) |
| Helper | `pytest` + Bash em modo simulado | cada ação numa raiz-sandbox com comandos falsos; arquivos gerados conferidos com `docker compose config` e `systemd-analyze verify` |
| Estilo | `ruff check`, `ruff format --check`, `shellcheck -x` | zero avisos |
| Interface | `--simular` + cenários + screenshots | fluxo completo, estados de erro, claro/escuro, estreito |
| Integração real | instalação na máquina (com autorização) | API, caminho das fotos, banco, reboot |

Comandos:

```bash
make test        # pytest
make lint        # ruff + shellcheck
./bin/nuvem-ruscher --simular                 # tudo fingido, cenário "feliz"
./bin/nuvem-ruscher --simular --cenario ntfs  # ver lista com --cenario ajuda
```

## Testes específicos do caminho com espaço

- `escape_fstab("/run/media/ruscher/Novo volume")` → `…/Novo\040volume`; ida e volta.
- `findmnt --tab-file` lendo a linha gerada devolve exatamente o caminho com espaço.
- Unidade gerada passa no `systemd-analyze verify` **sem** “path is not absolute” e sem
  “Failed to add dependency”.
- `.env` gerado + override → `docker compose config` mostra
  `source: /run/media/ruscher/Novo volume/immich-ruscher` e `create_host_path: false`.
- Helper com pasta de fotos com espaço em todas as ações.
- Caminhos maliciosos (`"`, `$()`, `` ` ``, `\n`, `%`, `..`) são recusados em Python e no Bash.

## Matriz de cenários

| # | Cenário | Esperado | Como testar |
|---|---|---|---|
| 1 | Docker ausente | item vermelho + [Instalar] → `install-docker` | `--cenario sem-docker`; teste do helper |
| 2 | Docker instalado mas parado | [Ligar e manter ligado] → `enable-docker` | `--cenario docker-parado` |
| 3 | Usuário fora do grupo docker | [Permitir] → `add-docker-group`; depois usa `sg docker` | `--cenario sem-grupo`; `test_docker.py` |
| 4 | Acabou de entrar no grupo (sessão antiga) | detecta via `/etc/group` × `os.getgroups()`, usa `sg docker -c`, sugere relogar | `test_docker.py` |
| 5 | Disco desmontado | Armazenamento: “disco não conectado”; serviço não sobe | `--cenario disco-ausente`; reboot real sem disco |
| 6 | NTFS | aviso amigável + fstab `ntfs-3g` | `--cenario ntfs` (padrão desta máquina) |
| 7 | FAT32 | aviso forte de 4 GB | `--cenario fat32`; `test_storage.py` |
| 8 | Porta 2283 ocupada | item bloqueante com nome do processo | `--cenario porta-ocupada`; `test_system.py` |
| 9 | Sem internet | bloqueia só a instalação; mensagem clara | `--cenario sem-internet` |
| 10 | Pouca RAM (< 6 GB) | aviso, sugere ML desligado; < 4 GB bloqueia | `--cenario pouca-ram` |
| 11 | Reinstalação com biblioteca existente | detecta `.immich`, reaproveita, preserva senha do banco | `--cenario biblioteca-existente`; teste do helper `setup` 2× |
| 12 | Falha no meio da instalação | etapa ✗, mensagem humana, [Tentar novamente] retoma | `--cenario falha-download` |
| 13 | Cancelar o download | processo encerrado; “pausada”; [Continuar] retoma | simulado + real |
| 14 | API demora a ficar saudável | espera até 10 min com mensagem tranquilizadora | `--cenario lento` |
| 15 | Atualização falha | rollback automático para a versão anterior | teste do helper `update` com saúde falsa |
| 16 | fstab inválido após edição | restaura backup | teste do helper com `findmnt` falso retornando 1 |
| 17 | Entrada já existe no fstab | recusa sem alterar nada | teste do helper |
| 18 | Firewall ativo | item informativo + [Liberar porta] | `--cenario firewall` |
| 19 | Pouco espaço para imagens | bloqueia com quanto falta | `test_system.py` |
| 20 | CPU sem x86-64-v2 | avisa e desliga ML | `test_system.py` |
| 21 | Desinstalar | remove serviço/containers; fotos, banco e `.env` intactos | teste do helper |
| 22 | Argumentos maliciosos ao helper | recusados com `@@ERROR invalid-argument` | teste do helper |
| 23 | Reboot com disco | serviço sobe após a montagem | real |
| 24 | Reboot sem disco | serviço não sobe; nenhuma pasta criada | real |

## Checklist de QA visual
- [ ] Todas as telas em claro e escuro
- [ ] Janela 360 px de largura (breakpoint)
- [ ] Navegação só com teclado do início ao fim
- [ ] Nenhum texto cortado; nenhuma tela “crua”
- [ ] Cor de destaque do sistema refletida
