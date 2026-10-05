# Empacotamento: auditoria (04/10/2026)

Registro do que foi encontrado antes de preparar o pacote Arch e o suporte Nix. O app
não lê nenhum destes `.md`.

## Como o app se encontra

| Peça | Antes | Problema | Agora |
|---|---|---|---|
| Lançador `bin/nuvem-ruscher` | procurava `bin/..` e, senão, `/usr/share/nuvem-ruscher` fixo | fora de `/usr` (Nix) cairia na cópia do pacman, se houvesse, misturando versões | procura `<prefixo>/share/nuvem-ruscher` relativo a si mesmo; sem fallback para outro prefixo |
| Shebang do lançador instalado | `#!/usr/bin/env python3` | um `python3` do conda/pyenv no PATH abriria o app sem PyGObject | `make install` grava `#!$(PYTHON)` (`/usr/bin/python3` no Arch, o Python do Nix Store no Nix) |
| CSS, ícones, ilustrações (`paths.py`) | relativos ao pacote | — | sem mudança |
| Traduções (`paths.locale_dir`) | `None` quando instalado = pasta padrão **do Python** | no Nix, a pasta padrão é a do Python no Nix Store: traduções nunca achadas | `<prefixo>/share/locale` (igual a `/usr/share/locale` no Arch) |
| Helper (`constants.HELPER_PATH`) | `/usr/lib/nuvem-ruscher/nuvem-ruscher-helper` fixo | no Nix o helper fica em `$out/lib/...` | `paths.helper_path()`: `<prefixo>/lib/nuvem-ruscher/…`; do código-fonte continua o de `/usr/lib` (o único que o polkit conhece) |
| Policy polkit | `exec.path` fixo em `/usr/lib/...` | errado para qualquer outro `PREFIX` | `data/*.policy.in` com `@HELPER_PATH@`, preenchido no `make install` |
| `.desktop` | `Exec=nuvem-ruscher` | no Nix depende do PATH da sessão | Arch: mantém; Nix: `Exec=$out/bin/nuvem-ruscher` |

## Caminhos absolutos que continuam fixos (de propósito)

- `/etc/nuvem-ruscher`, `/var/lib/nuvem-ruscher`, `/etc/systemd/system`, `/etc/fstab`,
  `/run/nuvem-ruscher-helper.lock`: estado do **sistema** gerenciado pelo helper. Não
  pertencem ao pacote, por isso `pacman -R` e o Nix nunca os removem.
- `PATH="/usr/bin:/usr/sbin:/bin:/sbin"` no helper e `/usr/bin/docker` na unidade systemd:
  o helper administra o sistema hospedeiro (systemd, Docker, pacman, fstab) e precisa dos
  comandos dele, num PATH que o usuário não controla.
- `/usr/lib/docker/cli-plugins/docker-compose` (detecção do Compose) e `/usr/share/zoneinfo`.

## Comandos externos

| Comando | Quem chama | Pacote Arch | No Nix |
|---|---|---|---|
| `docker`, `docker compose` | interface e helper | `docker`, `docker-compose` | do sistema (fala com o daemon do sistema) |
| `sg` | interface (grupo docker recém-adicionado) | `shadow` | do sistema (setuid) |
| `pkexec` | interface | `polkit` | do sistema (setuid) |
| `systemctl`, `systemd-escape` | interface e helper | `systemd` | do sistema |
| `findmnt`, `lsblk` | interface e helper | `util-linux` | `util-linux` do Nix na interface; do sistema no helper |
| `flock`, `mountpoint`, `blkid` | helper | `util-linux` | do sistema (helper) |
| `ip` | interface (fallback do IP local) | `iproute2` | `iproute2` do Nix |
| `curl`, `gzip` | helper | `curl`, `gzip` | do sistema (helper) |
| `pacman`, `gpasswd`, `groupadd` | helper | base | do sistema (helper) |
| `tailscale`, `ufw`, `firewall-cmd`, `nvidia-ctk` | opcionais | optdepends | do sistema, se houver |

Nenhum subprocesso usa `shell=True`; o único `sh -c` é o `sg docker -c` com `shlex.join`.

## Problemas encontrados

1. **Traduções quebrariam fora de `/usr`** (ver tabela). Não havia nenhum `po/*.po`, então
   o efeito ainda não aparecia. Na v1.0.0 houve um `po/en.po`; desde a v2 o texto-fonte é
   inglês e a tradução é `po/pt_BR.po` (ver 13-i18n-migration.md); o inglês é o que
   aparece para idiomas sem catálogo.
2. **Lançador podia carregar outra cópia do app** (fallback `/usr/share/nuvem-ruscher`).
3. **Policy e helper presos a `/usr`**, impedindo qualquer outro prefixo.
4. **PKGBUILD compilava dentro do repositório** (`make -C ..`), escrevendo em `build/` da
   árvore de trabalho, e o `check()` pulava os testes em silêncio se o pytest faltasse.
5. **`post_install` mandava "configurar o servidor" mesmo numa reinstalação** com o servidor
   já funcionando.
6. **Segurança (defesa em profundidade)**: como root, o helper criava a pasta das fotos e
   dava `chown` ao usuário, e gravava backups em `<fotos>/backups/` — pastas do usuário.
   Um link simbólico no caminho levaria essas operações para outro lugar (ex.:
   `/etc/systemd/system`). As duas ações exigem senha de administrador, então não é escalada
   de privilégio a partir de um usuário comum, mas agora o helper recusa links nesses
   caminhos (testes `test_rejects_symlink_inside_photo_path` e
   `test_backup_does_not_follow_symlink_in_photo_folder`).
7. **Shebang do helper** era `/usr/bin/env bash`; agora `/usr/bin/bash` (interpretador
   absoluto para um script que roda como root; o namcap reconhece a dependência).

Sem problemas: ações sem senha (`start`/`stop`/`restart`) não recebem argumentos e só leem a
configuração de root; o pkexec limpa o ambiente e o helper redefine `PATH` e `LC_ALL`;
arquivos temporários nascem com `mktemp` (600) na pasta de destino e são trocados com `mv`;
`/etc/fstab` tem backup, verificação e volta automática; não há `eval`, `rm -rf`,
`down -v` nem `--volumes` (verificado por teste).

## Diferenças em relação às referências

| | big-hardware-info | big-video-converter | Nuvem Ruscher |
|---|---|---|---|
| Build Python | wheel (`uv-build`, `python -m installer`) | nenhum (`cp -a usr`) | nenhum: `make install` (ADR-001) |
| `pkgver` | data (`%y.%m.%d`) | data | semântico (`1.0.0`), igual ao AppStream e ao helper |
| Fonte local/remota | detecta árvore local via `$startdir` | sempre git | detecta árvore local; fora dela, `git+…#tag=v$pkgver` |
| `check()` | — | `desktop-file-validate` + `appstreamcli` | pytest + `desktop-file-validate` + `appstreamcli` |
| Nix | `buildPythonApplication` + `default.nix` | — | `stdenv.mkDerivation` + `make install` em `nix/package.nix` |

O modelo de wheel do big-hardware-info não foi adotado: o projeto não tem pacote Python
instalável, e o Makefile já é a fonte única da instalação.
