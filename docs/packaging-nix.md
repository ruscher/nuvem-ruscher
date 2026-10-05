# Empacotamento: Nix

> **Situação (04/10/2026): escrito, mas NÃO testado.** Esta máquina não tem Nix, e a
> instalação dele foi adiada. Nada aqui foi construído com `nix build`; o `flake.lock`
> ainda não existe (é criado no primeiro `nix build`). Antes de anunciar o suporte, rode o
> roteiro de validação do fim deste documento.

## Arquivos

- `flake.nix`: `packages.<sistema>.{nuvem-ruscher,default}`, `checks` (constrói o pacote,
  o que roda os testes) e `devShells.default`. Só `x86_64-linux` e `aarch64-linux`: o app
  gerencia systemd, Docker, polkit e fstab, e com `eachDefaultSystem` o `nix flake check`
  falharia ao avaliar o pacote (Linux-only) no Darwin.
- `nix/package.nix`: a derivação. Escolhido em vez do `default.nix` do big-hardware-info
  porque lá o `default.nix` é uma função para `callPackage` que não funciona com
  `nix-build` puro; o nome `package.nix` segue a convenção atual do nixpkgs.

Não há `apps`: `nix run` usa `packages.default` e `meta.mainProgram`.

## Derivação

`stdenv.mkDerivation` + o `make install` do projeto (não há pacote Python para o
`buildPythonApplication`, ADR-001):

- `makeFlags = [ "PREFIX=$out" "PYTHON=<python com pygobject3 e qrcode>" ]` — o lançador
  instalado aponta para esse Python, que já enxerga PyGObject e qrcode sem `PYTHONPATH`.
- `nativeBuildInputs`: `gettext` (msgfmt), `gobject-introspection` e `wrapGAppsHook4`
  (montam `GI_TYPELIB_PATH`, `XDG_DATA_DIRS` com os schemas do GTK etc. no wrapper de
  `bin/nuvem-ruscher`), e o Python (para o `compileall`).
- `buildInputs`: `gtk4`, `libadwaita` e `bash` (o fixup troca `#!/usr/bin/bash` do helper
  pelo bash do Nix Store).
- `src` filtrado com `lib.fileset` (sem capturas, docs, `packaging/`).
- `checkPhase`: pytest, menos `tests/test_helper.py` (o helper usa as ferramentas de
  `/usr/bin`, que não existem no sandbox; ele roda no `make test` e no `check()` do
  PKGBUILD). Esse subconjunto foi rodado aqui sem display e sem sessão D-Bus: passa.
- `postInstall`: `Exec=$out/bin/nuvem-ruscher` no `.desktop`.
- O wrapper acrescenta ao `PATH` só `util-linux` e `iproute2` do Nix (consultas de discos e
  rede). `docker`, `systemctl`, `sg`, `pkexec` e `tailscale` vêm do sistema **de propósito**:
  conversam com daemons do sistema e `sg`/`pkexec` precisam de setuid, que o Nix Store não tem.

### Caminhos

O app calcula tudo a partir do próprio arquivo (`nuvem_ruscher/paths.py`):
`$out/share/nuvem-ruscher` → prefixo `$out` → helper em `$out/lib/nuvem-ruscher/` e
traduções em `$out/share/locale`. O lançador (`.nuvem-ruscher-wrapped` depois do wrapper)
faz o mesmo cálculo. A policy instalada em `$out/share/polkit-1/actions/` traz o caminho
do helper no `$out`. Isso é coberto por `tests/test_packaging.py::TestRelocatedPrefix`
(instala num prefixo qualquer e roda o lançador de lá).

## Polkit com Nix — limitação real

- O polkitd do sistema só lê policies de `/usr/share/polkit-1/actions`,
  `/usr/local/share/polkit-1/actions`, `/etc/polkit-1/actions` e `/run/polkit-1/actions`
  (verificado no polkitd 127 do BigLinux). Um `nix profile install` não escreve em nenhum
  deles, então **a policy do Nuvem Ruscher não é registrada**.
- Sem ela, o `pkexec $out/lib/nuvem-ruscher/nuvem-ruscher-helper …` cai na ação genérica
  `org.freedesktop.policykit.exec` (`auth_admin`): **funciona**, mas pede a senha de
  administrador em **toda** ação, inclusive ligar/desligar/reiniciar, e a janela mostra o
  caminho do Nix Store em vez da frase do app.
- Não registramos a policy automaticamente, nem oferecemos copiar para `/etc/polkit-1/actions`:
  1. o pkexec compara o caminho **resolvido** (`realpath`), então um link estável como
     `~/.nix-profile/lib/...` não serviria; teria de ser o caminho do Nix Store, que muda a
     cada atualização;
  2. a policy concede `start`/`stop`/`restart` **sem senha** ao caminho anotado. Isso só é
     seguro se o arquivo for imutável e de root. Num Nix multiusuário o Store é de root,
     mas numa instalação monousuário o Store pertence ao usuário, que poderia trocar o
     helper e ganhar root sem senha.
- O helper roda com o `PATH` do sistema e administra o sistema (pacman, `/etc/fstab`,
  `/usr/bin/docker` na unidade systemd). Por isso o pacote Nix serve para usar o app num
  BigLinux/Manjaro/Arch que tenha Nix; **NixOS não é suportado** para gerenciar o servidor.

Modalidade recomendada: pacote do pacman. O Nix é útil para desenvolvimento
(`nix develop`) e para experimentar a interface (`--simular`).

## Remoção e coleta de lixo

O pacote Nix só contém o app. `nix profile remove` e `nix-collect-garbage` apagam caminhos
do Nix Store e nunca tocam em `/etc`, `/var/lib/nuvem-ruscher` nem nas fotos.

## Roteiro de validação (pendente)

```bash
nix flake check                       # avalia e constrói (roda os testes)
nix build && readlink -f result
find result/ -maxdepth 5 -type f | sort
head -1 result/lib/nuvem-ruscher/nuvem-ruscher-helper           # bash do Nix Store
grep exec.path result/share/polkit-1/actions/*.policy           # caminho do $out
grep ^Exec result/share/applications/*.desktop
nix-store -q --references ./result     # Python env, gtk4, libadwaita, bash, util-linux, iproute2…
nix-store -q --requisites ./result | grep -v /nix/store && echo "algo fora do Store"
./result/bin/nuvem-ruscher --version
./result/bin/nuvem-ruscher --simular
nix run . -- --simular
env -i HOME=$HOME DISPLAY=$DISPLAY WAYLAND_DISPLAY=$WAYLAND_DISPLAY XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
    PATH=/usr/bin ./result/bin/nuvem-ruscher --simular            # sem o ambiente do desenvolvedor
nix develop -c make test lint
pkexec "$(readlink -f result)/lib/nuvem-ruscher/nuvem-ruscher-helper" version   # ação genérica, pede senha
```
