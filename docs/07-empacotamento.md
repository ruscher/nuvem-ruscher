# 07 — Empacotamento

Detalhes e decisões: [auditoria](packaging-audit.md), [Arch](packaging-arch.md),
[Nix](packaging-nix.md), [testes](packaging-tests.md).

## Layout instalado

| Origem | Destino |
|---|---|
| `bin/nuvem-ruscher` | `/usr/bin/nuvem-ruscher` |
| `nuvem_ruscher/` | `/usr/share/nuvem-ruscher/nuvem_ruscher/` |
| `data/illustrations/*.svg`, `style.css` | `/usr/share/nuvem-ruscher/…` |
| `helper/nuvem-ruscher-helper` | `/usr/lib/nuvem-ruscher/nuvem-ruscher-helper` (755) |
| `data/io.github.ruscher.NuvemRuscher.policy.in` | `/usr/share/polkit-1/actions/` (com o caminho do helper) |
| `data/io.github.ruscher.NuvemRuscher.desktop` | `/usr/share/applications/` |
| `data/io.github.ruscher.NuvemRuscher.metainfo.xml` | `/usr/share/metainfo/` |
| ícones | `/usr/share/icons/hicolor/{scalable,symbolic}/apps/` |
| `po/*.po` → `.mo` | `/usr/share/locale/<lang>/LC_MESSAGES/nuvem-ruscher.mo` |

A tabela usa `PREFIX=/usr`. Tudo é relativo ao prefixo: o lançador procura
`<prefixo>/share/nuvem-ruscher` ao lado de si mesmo (ou `nuvem_ruscher/` no repositório) e
o app acha helper e traduções a partir daí (`nuvem_ruscher/paths.py`). Do código-fonte, o
backend real usa o helper instalado em `/usr/lib` (o polkit só confia no caminho
instalado); o `--simular` não chama helper.

## PKGBUILD (resumo)

`packaging/PKGBUILD` empacota a árvore local quando está dentro do repositório e a tag
`v$pkgver` do GitHub quando copiado para fora; `package()` é só
`make DESTDIR="$pkgdir" PREFIX=/usr PYTHON=/usr/bin/python3 install`. Dependências e
justificativas em [packaging-arch.md](packaging-arch.md).

## `.desktop`

`Categories=GTK;GNOME;Graphics;Photography;` · `Keywords` em pt-BR e inglês
(fotos, backup, google fotos, immich, nuvem) · `StartupNotify=true` ·
`StartupWMClass=io.github.ruscher.NuvemRuscher` · `Icon=io.github.ruscher.NuvemRuscher`.
No pacote Nix, `Exec` vira o caminho absoluto em `$out/bin`.

## Metainfo AppStream

ID `io.github.ruscher.NuvemRuscher`, licença do metadado `CC0-1.0`, do projeto
`GPL-3.0-or-later`, `content_rating oars-1.1`, `releases`, `branding` com as cores do
céu, `requires`/`recommends` de memória (6 GB) e tela. Validação:
`appstreamcli validate --no-net`.

> Observação: o BigLinux configura `PKGEXT='.pkg.tar'` (sem compressão) em `/etc/makepkg.conf`,
> então o arquivo gerado é `nuvem-ruscher-2.0.0-1-any.pkg.tar`.

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
