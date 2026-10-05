# 13 — Inglês como idioma-fonte (v2)

Documento de trabalho; o app não lê este arquivo.

## Antes e depois

| | v1.0.0 | v2 |
|---|---|---|
| Texto no código (`_()`, `N_()`) | pt-BR | inglês |
| Catálogos | `po/en.po` | `po/pt_BR.po` |
| Idioma sem catálogo (ex.: alemão) | pt-BR | inglês |
| Mensagens técnicas (helper, erros internos, logs do simulador) | pt-BR | inglês |
| `.desktop`, AppStream, policy do polkit | inglês + `[pt_BR]`/`xml:lang` | sem mudança |
| Flags da linha de comando | `--simular`, `--cenario`, `ajuda` | `--simulate`, `--scenario`, `help` (as antigas continuam aceitas) |
| Cenários do simulador | `feliz`, `sem-docker`… | `fresh`, `no-docker`… (os nomes antigos continuam aceitos) |

## Como foi feito

1. `po/en.po` (458 mensagens, pt→en) virou o mapa da troca. Um script de uso único
   percorreu a AST de cada arquivo e trocou **só** os literais dentro de `_()`, `N_()` e
   `ngettext()`; ele parava se faltasse alguma mensagem. Única colisão: "Concluído" e
   "Pronto" viravam "Done" — o título da página final passou a ser "Ready".
2. `make pot` regenerou o `.pot` em inglês; `po/pt_BR.po` foi gerado invertendo o mapa
   (`Plural-Forms: nplurals=2; plural=(n > 1);`).
3. Duas concatenações que impediam a tradução viraram frases com marcador: a porta ocupada
   ("It is used by “{name}”. …") e a versão "{version} (simulation)".
4. Achado do teste novo: o tooltip "Menu" do assistente não passava pelo gettext.

## O que ficou de propósito

- `# Nuvem Ruscher: disco de fotos do Immich`, o marcador das linhas do app no `/etc/fstab`:
  é como o app reconhece a linha que criou (inclusive nas instalações existentes).
- O perfil `desativado` do override do Compose (identificador, conferido por teste).
- Comentários e docstrings do código e os documentos em `docs/` continuam em pt-BR.

## Garantias (testes)

- `tests/test_i18n.py::test_no_hardcoded_visible_strings`: nenhum literal com palavras é
  passado a `set_title`, `set_subtitle`, `set_tooltip_text`, `title=`, `label=` etc. fora
  do gettext (exceções: nomes próprios).
- `test_source_language_is_english`: o `.pot` não tem letras/palavras típicas do português.
- `test_portuguese_catalog_and_english_fallback`: pt_BR traduz, inglês é o padrão.
- `tests/test_packaging.py::test_catalog_complete_and_consistent`: todo `po/*.po` completo,
  sem "fuzzy", com os mesmos `{marcadores}`, quebras de linha e `<b>`.

## Fluxo para textos novos

```bash
make pot && make update-po        # extrai e mescla (remove obsoletos)
msgfmt --check --statistics -o /dev/null po/pt_BR.po
```
