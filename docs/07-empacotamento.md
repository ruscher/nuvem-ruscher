# 07 — Empacotamento

## Layout instalado

| Origem | Destino |
|---|---|
| `bin/nuvem-ruscher` | `/usr/bin/nuvem-ruscher` |
| `nuvem_ruscher/` | `/usr/share/nuvem-ruscher/nuvem_ruscher/` |
| `data/illustrations/*.svg`, `style.css` | `/usr/share/nuvem-ruscher/…` |
| `helper/nuvem-ruscher-helper` | `/usr/lib/nuvem-ruscher/nuvem-ruscher-helper` (755) |
| `data/io.github.ruscher.NuvemRuscher.policy` | `/usr/share/polkit-1/actions/` |
| `data/io.github.ruscher.NuvemRuscher.desktop` | `/usr/share/applications/` |
| `data/io.github.ruscher.NuvemRuscher.metainfo.xml` | `/usr/share/metainfo/` |
| ícones | `/usr/share/icons/hicolor/{scalable,symbolic}/apps/` |
| `po/*.po` → `.mo` | `/usr/share/locale/<lang>/LC_MESSAGES/nuvem-ruscher.mo` |

O lançador descobre se está rodando do código-fonte (pasta `nuvem_ruscher` ao lado)
ou instalado (`/usr/share/nuvem-ruscher`) e ajusta `sys.path`. Do código-fonte, ele
usa o helper do repositório **apenas** em `--simular`; para operações reais exige o
helper instalado em `/usr/lib` (o polkit só confia no caminho instalado).

## PKGBUILD (resumo)

```bash
pkgname=nuvem-ruscher
pkgver=1.0.0
pkgrel=1
arch=('any')
depends=(python python-gobject gtk4 libadwaita python-qrcode python-yaml
         polkit docker docker-compose util-linux systemd curl gzip)
optdepends=('ntfs-3g: discos NTFS' 'exfatprogs: discos exFAT'
            'tailscale: acesso fora de casa' 'ufw: firewall')
makedepends=(gettext)
install=nuvem-ruscher.install
package() { make -C "$srcdir/.." DESTDIR="$pkgdir" PREFIX=/usr install; }
```

`docker`/`docker-compose` são dependências: o assistente ainda oferece instalá-los
quando o app é usado a partir do código-fonte.

## `.desktop`

`Categories=GTK;GNOME;Graphics;Photography;System;` · `Keywords` em pt-BR e inglês
(fotos, backup, google fotos, immich, nuvem) · `StartupNotify=true` ·
`DBusActivatable=false` · `Icon=io.github.ruscher.NuvemRuscher`.

## Metainfo AppStream

ID `io.github.ruscher.NuvemRuscher`, licença do metadado `CC0-1.0`, do projeto
`GPL-3.0-or-later`, `content_rating oars-1.1`, `releases`, `branding` com as cores do
céu, `requires`/`recommends` de memória (6 GB) e tela. Validação:
`appstreamcli validate --no-net`.

## Instalação

```bash
cd packaging && makepkg -si      # gera e instala
# ou, para desenvolvimento:
sudo make install PREFIX=/usr
```

## Desinstalação

`sudo pacman -R nuvem-ruscher` remove **o app**. O servidor de fotos continua
funcionando (a unidade systemd não depende do app). Para remover o servidor, use antes
*Painel → Mais → Desinstalar o servidor*. O `nuvem-ruscher.install` imprime esse aviso
no `pre_remove` quando o serviço existe. **Fotos, banco e `.env` nunca são removidos
pelo pacote.**
