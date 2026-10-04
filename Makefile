# Nuvem Ruscher — instalação sem etapa de build Python (ADR-001).
#
#   make            compila as traduções (build/locale)
#   make test       pytest
#   make lint       ruff + shellcheck
#   make pot        regenera po/nuvem-ruscher.pot
#   sudo make install PREFIX=/usr
#   sudo make uninstall PREFIX=/usr

PREFIX  ?= /usr
DESTDIR ?=
APP_ID  := io.github.ruscher.NuvemRuscher
DATADIR := $(PREFIX)/share
APPDIR  := $(DATADIR)/nuvem-ruscher
LIBDIR  := $(PREFIX)/lib/nuvem-ruscher
LOCALEDIR := $(DATADIR)/locale

PY_FILES   := $(shell find nuvem_ruscher -type f \( -name '*.py' -o -name '*.css' \) | sort)
DATA_FILES := $(shell find data/illustrations data/icons -type f -name '*.svg' | sort)
PO_FILES   := $(wildcard po/*.po)
LANGS      := $(basename $(notdir $(PO_FILES)))
MO_FILES   := $(foreach l,$(LANGS),build/locale/$(l)/LC_MESSAGES/nuvem-ruscher.mo)

.PHONY: all test lint pot install uninstall clean

all: $(MO_FILES)

build/locale/%/LC_MESSAGES/nuvem-ruscher.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

pot:
	xgettext --from-code=UTF-8 --language=Python --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
		--add-comments=TRANSLATORS --package-name=nuvem-ruscher --package-version=1.0.0 \
		--msgid-bugs-address=https://github.com/ruscher/nuvem-ruscher/issues \
		-o po/nuvem-ruscher.pot $(filter %.py,$(PY_FILES))

test:
	python3 -m pytest

lint:
	ruff check .
	ruff format --check .
	shellcheck -x helper/nuvem-ruscher-helper
	cd tests/sim-bin && shellcheck -x ./*
	desktop-file-validate data/$(APP_ID).desktop
	appstreamcli validate --no-net data/$(APP_ID).metainfo.xml

install: all
	install -Dm755 bin/nuvem-ruscher $(DESTDIR)$(PREFIX)/bin/nuvem-ruscher
	@for f in $(PY_FILES); do install -Dm644 "$$f" "$(DESTDIR)$(APPDIR)/$$f"; done
	@for f in $(DATA_FILES); do install -Dm644 "$$f" "$(DESTDIR)$(APPDIR)/$$f"; done
	python3 -m compileall -q -d $(APPDIR)/nuvem_ruscher $(DESTDIR)$(APPDIR)/nuvem_ruscher
	install -Dm755 helper/nuvem-ruscher-helper $(DESTDIR)$(LIBDIR)/nuvem-ruscher-helper
	install -Dm644 data/$(APP_ID).policy $(DESTDIR)$(DATADIR)/polkit-1/actions/$(APP_ID).policy
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
	rm -f $(DESTDIR)$(PREFIX)/bin/nuvem-ruscher
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
