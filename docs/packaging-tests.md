# Empacotamento: testes realizados (04/10/2026, BigLinux, Python 3.14, GTK 4.22, libadwaita 1.9, polkit 127)

## Automatizados

| Comando | Resultado |
|---|---|
| `make test` | 195 passed (eram 176; +17 de `tests/test_packaging.py`, +2 de link simbólico no helper) |
| `make lint` | ruff, ruff format, shellcheck (helper, sim-bin, `.install`), `bash -n PKGBUILD`, desktop-file-validate e appstreamcli: OK |
| pytest sem `DISPLAY`/`WAYLAND_DISPLAY`/D-Bus, sem `test_helper.py` (o que o `checkPhase` do Nix roda) | passa |
| os 2 testes novos de link simbólico contra o helper anterior | falham (confirmam a correção) |

`tests/test_packaging.py` instala de verdade com o Makefile: como o PKGBUILD
(`DESTDIR`+`PREFIX=/usr`: só `usr/`, arquivos esperados, permissões, `.pyc`, nada de
desenvolvimento, shebang fixo, policy com o helper certo, `uninstall` só remove o que
instalou) e como o Nix (`PREFIX` qualquer: o lançador carrega a própria cópia, tradução
`.po → .mo → <prefixo>/share/locale` funciona e cai no pt-BR, helper e policy seguem o
prefixo). Também confere versão (pyproject, `__init__`, helper, AppStream, PKGBUILD), IDs
(desktop, AppStream, policy) e cada `po/*.po`: compila com `msgfmt --check`, sem "fuzzy",
todas as mensagens traduzidas e com os mesmos `{marcadores}`, quebras de linha e `<b>`.

## Pacote Arch

| Verificação | Resultado |
|---|---|
| `bash -n` (PKGBUILD e `.install`), `makepkg --printsrcinfo` | OK; fora do repositório: `git+…#tag=v1.0.0` e `git` em makedepends |
| `makepkg -f` | gera `nuvem-ruscher-1.0.0-1-any.pkg.tar`; `check()`: 195 passed + validações |
| `pacman -Qlp` | 61 arquivos (com `locale/en/…/nuvem-ruscher.mo`) + 42 `.pyc`, todos em `/usr` |
| `namcap` (PATH padrão) | só falsos positivos (ver packaging-arch.md) |
| `sudo pacman -U` | instalou; hooks de ícones e `.desktop` rodaram; "O servidor de fotos não foi reiniciado" |
| `nuvem-ruscher --version`, `--help`, `--cenario ajuda` | OK; com `LANGUAGE=en`, em inglês |
| `tools/tour.py` com `LANGUAGE=en` | 14 telas em inglês, sem texto cortado nem trecho em português |
| `tools/tour.py` apontado para `/usr/share/nuvem-ruscher` | 14 telas em `--simular` com CSS, ilustrações, ícones simbólicos e QR Code |
| `kioclient ls applications:/Graphics/` | "Nuvem Ruscher" no menu do Plasma |
| `gio launch` do `.desktop` instalado | o app real abriu (nome D-Bus registrado), sem traceback; fechado pela ação `app.quit` |
| `pkaction` | 4 ações, `exec.path` = `/usr/lib/nuvem-ruscher/nuvem-ruscher-helper` |
| `pkexec /usr/lib/nuvem-ruscher/nuvem-ruscher-helper version` (janela de senha do KDE) | rc=0, `1.0.0` |
| `pkcheck` na sessão ativa | `start`/`stop`/`restart` autorizados sem senha; `manage` e a ação genérica pedem senha |

Avisos no terminal ao abrir (`lsfg-vk`, `radv`, `gtk-application-prefer-dark-theme`) vêm
de uma camada Vulkan instalada no sistema e do `~/.config/gtk-4.0/settings.ini` gravado
pelo KDE, não do app.

## Remoção sem perda de dados

Com o Immich real rodando (24 mil fotos), comparando um retrato antes e depois de
`sudo pacman -R nuvem-ruscher`:

- serviço `nuvem-ruscher-immich` ativo desde o mesmo instante; `/api/server/ping` = pong;
  os 4 containers de pé;
- sha256 idênticos de `/etc/fstab`, `/etc/nuvem-ruscher/nuvem-ruscher.conf`, da unidade
  systemd, de `.env`, `docker-compose.yml` e `docker-compose.override.yml`;
- banco: mesma quantidade de arquivos; fotos originais (`upload/` + `library/`): mesmos
  52.370 arquivos e bytes;
- `/usr/share/nuvem-ruscher` e `/usr/lib/nuvem-ruscher` sumiram; `/etc/nuvem-ruscher` e
  `/var/lib/nuvem-ruscher` ficaram.

Depois, `pacman -U` de novo: `pacman -Qkk` sem arquivos alterados, serviço ativo. O
pacote final (com a tradução) foi reinstalado do mesmo jeito: serviço com o mesmo
horário de início, `ping` respondendo.

## Nix

Não testado: sem Nix nesta máquina (ver packaging-nix.md).

## v2.0.0 (05/10/2026)

| Verificação | Resultado |
|---|---|
| `make test` | 395 passed (helper em sandbox, migração, RAID, discos, SMART, contas, simulador, fumaça da interface, i18n) |
| `make lint` | limpo (ruff, shellcheck, desktop-file-validate, appstreamcli) |
| `make pot` + `make update-po` | 969 mensagens em pt_BR, nenhuma pendente ou aproximada |
| `makepkg -f` | gera `nuvem-ruscher-2.0.0-1-any.pkg.tar`; `check()`: 395 passed |
| `namcap` | sem erros; só os avisos esperados de dependências chamadas em tempo de execução (`docker`, `rsync`, `systemd`…) |
| Instalação do pacote v2 nesta máquina | **não feita** (aguarda autorização; o Immich real não foi tocado) |
