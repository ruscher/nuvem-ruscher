# Empacotamento: BigLinux / Manjaro / Arch

## Uso

```bash
cd packaging
makepkg -si          # gera e instala
makepkg -f           # só gera nuvem-ruscher-1.0.0-1-any.pkg.tar (o BigLinux usa PKGEXT sem compressão)
```

## Como o PKGBUILD funciona

- **Árvore local ou upstream.** Se o PKGBUILD está em `packaging/` de um checkout (há
  `../Makefile`, `../nuvem_ruscher/__init__.py` e `../packaging/PKGBUILD`), o `prepare()`
  copia para `$srcdir` só o que o build usa (`Makefile LICENSE pyproject.toml bin
  nuvem_ruscher helper data po tests`), sem caches. Alterações ainda não commitadas
  entram no pacote — é o modo de desenvolvimento. Copiado para fora (AUR, repositório
  do BigLinux), o mesmo arquivo usa `source=("nuvem-ruscher::git+…#tag=v$pkgver")` e
  acrescenta `git` a `makedepends`.
- **Uma única receita de instalação.** `package()` é só
  `make DESTDIR="$pkgdir" PREFIX=/usr PYTHON=/usr/bin/python3 install`. O Nix usa o mesmo
  alvo com `PREFIX=$out`.
- **`build()`** compila `po/*.po` em `build/locale/*/LC_MESSAGES/nuvem-ruscher.mo`.
- **`check()`** roda toda a suíte (pytest, inclusive o helper em sandbox) e valida o
  `.desktop` e o AppStream.

## Dependências

| Tipo | Pacotes | Por quê |
|---|---|---|
| depends | `python python-gobject python-qrcode gtk4 libadwaita glib2 graphene pango hicolor-icon-theme` | interface; GLib/Gio/GObject, Graphene e Pango são importados direto |
| depends | `polkit` | `pkexec` e a policy |
| depends | `docker docker-compose` | o servidor Immich roda no Docker Compose |
| depends | `bash curl gzip util-linux systemd shadow iproute2` | helper (download, backup, `flock`/`findmnt`, `systemctl`, `gpasswd`) e interface (`sg`, `ip`) |
| makedepends | `gettext` (+ `git` fora da árvore) | `msgfmt` |
| checkdepends | `python-pytest desktop-file-utils appstream` | `check()` |
| optdepends | `ntfs-3g exfatprogs tailscale ufw` | discos NTFS/exFAT, acesso fora de casa, firewall |

Não há pip nem download no build. `namcap` (com o PATH padrão) só aponta "Dependency
included, but may not be needed" para os comandos chamados por subprocesso — falso positivo
— e `File referenced in $startdir` no PKGBUILD, que é a detecção intencional da árvore local
(mesmo padrão do big-hardware-info).

## Conteúdo do pacote

Tudo em `/usr`, nada em `/etc` nem `/var` (verificado por teste):

```
/usr/bin/nuvem-ruscher                                    #!/usr/bin/python3
/usr/lib/nuvem-ruscher/nuvem-ruscher-helper               755, #!/usr/bin/bash
/usr/share/nuvem-ruscher/{nuvem_ruscher,data}             código (+ __pycache__), CSS, ilustrações, ícones de status
/usr/share/polkit-1/actions/io.github.ruscher.NuvemRuscher.policy
/usr/share/applications/io.github.ruscher.NuvemRuscher.desktop
/usr/share/metainfo/io.github.ruscher.NuvemRuscher.metainfo.xml
/usr/share/icons/hicolor/{scalable,symbolic}/apps/io.github.ruscher.NuvemRuscher*.svg
/usr/share/locale/pt_BR/LC_MESSAGES/nuvem-ruscher.mo      português (o texto-fonte é inglês)
/usr/share/licenses/nuvem-ruscher/LICENSE
```

## Instalação, atualização e remoção

- O `nuvem-ruscher.install` só imprime mensagens. Caches de ícones e de `.desktop` são
  atualizados pelos hooks do pacman (`gtk-update-icon-cache.hook`,
  `update-desktop-database.hook`); o polkitd percebe a policy nova sozinho.
- Atualizar o pacote **não** reinicia o servidor.
- `pacman -R`/`-Rns` remove só os arquivos acima. Servidor, unidade systemd, `/etc/fstab`,
  `/etc/nuvem-ruscher`, `/var/lib/nuvem-ruscher` (banco, `.env`, compose) e as fotos não
  pertencem ao pacote e ficam. Para remover o servidor: *Painel → Mais → Desinstalar o
  servidor* (que também preserva fotos e banco).

## Para publicar

1. Numa versão nova, mudar juntos `pkgver`, `VERSION` (`nuvem_ruscher/__init__.py`),
   `pyproject.toml`, `HELPER_VERSION` e o `<release>` do AppStream (um teste confere), e
   criar a tag anotada `v$pkgver` no GitHub.
2. Copiar `PKGBUILD` e `nuvem-ruscher.install` para o repositório de pacotes e gerar o
   `.SRCINFO` com `makepkg --printsrcinfo` **lá** (dentro deste repositório ele mostra
   `source=()` porque está no modo local).
3. Fontes git usam `SKIP`; para fixar o conteúdo, troque `#tag=` por `#commit=<hash>` ou
   assine as tags e use `validpgpkeys`.
