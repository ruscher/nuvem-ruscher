# Nuvem Ruscher — instalação sem etapa de build Python (ADR-001).
#
#   make            compila as traduções (build/locale)
#   make test       pytest
#   make lint       ruff + shellcheck
#   make pot        regenera po/nuvem-ruscher.pot
#   make update-po  leva os textos novos do .pot para cada po/*.po
#   sudo make install PREFIX=/usr
#   sudo make uninstall PREFIX=/usr
#
# PREFIX é onde o app vai rodar (/usr no pacman, $out no Nix); DESTDIR é só a raiz
# temporária onde os arquivos são gravados (o $pkgdir do makepkg). Os caminhos gravados
# dentro dos arquivos (shebang, policy do polkit) usam PREFIX, nunca DESTDIR.
# PYTHON é o interpretador fixado no lançador instalado e usado para gerar os .pyc.

PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= /usr/bin/python3
APP_ID  := io.github.ruscher.NuvemRuscher
VERSION := $(shell sed -n 's/^VERSION = "\(.*\)"$$/\1/p' nuvem_ruscher/__init__.py)
BINDIR  := $(PREFIX)/bin
DATADIR := $(PREFIX)/share
APPDIR  := $(DATADIR)/nuvem-ruscher
LIBDIR  := $(PREFIX)/lib/nuvem-ruscher
LOCALEDIR := $(DATADIR)/locale

PY_FILES   := $(shell find nuvem_ruscher -type f \( -name '*.py' -o -name '*.css' \) | sort)
DATA_FILES := $(shell find data/illustrations data/icons -type f -name '*.svg' | sort)
PO_FILES   := $(wildcard po/*.po)
LANGS      := $(basename $(notdir $(PO_FILES)))
MO_FILES   := $(foreach l,$(LANGS),build/locale/$(l)/LC_MESSAGES/nuvem-ruscher.mo)

.PHONY: all test lint pot update-po install uninstall clean

all: $(MO_FILES)

build/locale/%/LC_MESSAGES/nuvem-ruscher.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

pot:
	xgettext --from-code=UTF-8 --language=Python --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
		--add-comments=TRANSLATORS --package-name=nuvem-ruscher --package-version=$(VERSION) \
		--msgid-bugs-address=https://github.com/ruscher/nuvem-ruscher/issues \
		-o po/nuvem-ruscher.pot $(filter %.py,$(PY_FILES))

update-po:
	@for po in $(PO_FILES); do msgmerge --quiet --update --backup=none --previous "$$po" po/nuvem-ruscher.pot; done

test:
	python3 -m pytest

lint:
	ruff check .
	ruff format --check .
	shellcheck -x helper/nuvem-ruscher-helper
	cd tests/sim-bin && shellcheck -x ./*
	shellcheck packaging/nuvem-ruscher.install
	bash -n packaging/PKGBUILD
	desktop-file-validate data/$(APP_ID).desktop
	appstreamcli validate --no-net data/$(APP_ID).metainfo.xml

install: all
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(DATADIR)/polkit-1/actions
	sed '1s|^#!.*|#!$(PYTHON)|' bin/nuvem-ruscher > $(DESTDIR)$(BINDIR)/nuvem-ruscher
	chmod 755 $(DESTDIR)$(BINDIR)/nuvem-ruscher
	@for f in $(PY_FILES); do install -Dm644 "$$f" "$(DESTDIR)$(APPDIR)/$$f"; done
	@for f in $(DATA_FILES); do install -Dm644 "$$f" "$(DESTDIR)$(APPDIR)/$$f"; done
	$(PYTHON) -m compileall -q -d $(APPDIR)/nuvem_ruscher $(DESTDIR)$(APPDIR)/nuvem_ruscher
	install -Dm755 helper/nuvem-ruscher-helper $(DESTDIR)$(LIBDIR)/nuvem-ruscher-helper
	sed 's|@HELPER_PATH@|$(LIBDIR)/nuvem-ruscher-helper|g' data/$(APP_ID).policy.in \
		> $(DESTDIR)$(DATADIR)/polkit-1/actions/$(APP_ID).policy
	chmod 644 $(DESTDIR)$(DATADIR)/polkit-1/actions/$(APP_ID).policy
	install -Dm644 data/$(APP_ID).desktop $(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop
	install -Dm644 data/$(APP_ID).metainfo.xml $(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml
	install -Dm644 data/icons/hicolor/scalable/apps/$(APP_ID).svg \
		$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	install -Dm644 data/icons/hicolor/symbolic/apps/$(APP_ID)-symbolic.svg \
		$(DESTDIR)$(DATADIR)/icons/hicolor/symbolic/apps/$(APP_ID)-symbolic.svg
	@for l in $(LANGS); do \
		install -Dm644 build/locale/$$l/LC_MESSAGES/nuvem-ruscher.mo \
			$(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/nuvem-ruscher.mo; done
	install -Dm644 LICENSE $(DESTDIR)$(DATADIR)/licenses/nuvem-ruscher/LICENSE

# Remove apenas o que o "install" colocou (lista explícita). Nunca toca no servidor,
# nas fotos ou no banco: para isso use o app (Painel → Mais → Desinstalar o servidor).
uninstall:
	rm -f $(DESTDIR)$(BINDIR)/nuvem-ruscher
	@for f in $(PY_FILES) $(DATA_FILES); do rm -f "$(DESTDIR)$(APPDIR)/$$f"; done
	find $(DESTDIR)$(APPDIR)/nuvem_ruscher -name '__pycache__' -type d -prune -exec rm -r -- {} +
	rm -f $(DESTDIR)$(LIBDIR)/nuvem-ruscher-helper
	rm -f $(DESTDIR)$(DATADIR)/polkit-1/actions/$(APP_ID).policy
	rm -f $(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop
	rm -f $(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml
	rm -f $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg
	rm -f $(DESTDIR)$(DATADIR)/icons/hicolor/symbolic/apps/$(APP_ID)-symbolic.svg
	rm -f $(DESTDIR)$(DATADIR)/licenses/nuvem-ruscher/LICENSE
	@for l in $(LANGS); do rm -f $(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/nuvem-ruscher.mo; done
	-find $(DESTDIR)$(APPDIR) $(DESTDIR)$(LIBDIR) -depth -type d -empty -delete

clean:
	rm -rf build/locale build/testes
