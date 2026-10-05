# Nuvem Ruscher para Nix. Não há build Python (ADR-001): o "make install" do projeto
# instala tudo em $out, como faz o PKGBUILD em /usr. Veja docs/packaging-nix.md.
{
  lib,
  stdenv,
  bash,
  python3,
  gtk4,
  libadwaita,
  gettext,
  gobject-introspection,
  wrapGAppsHook4,
  iproute2,
  util-linux,
}:

let
  python = python3.withPackages (ps: [
    ps.pygobject3
    ps.qrcode
  ]);
  pythonForTests = python3.withPackages (ps: [
    ps.pygobject3
    ps.qrcode
    ps.pytest
  ]);
in
stdenv.mkDerivation {
  pname = "nuvem-ruscher";
  version = (lib.importTOML ../pyproject.toml).project.version;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../Makefile
      ../LICENSE
      ../pyproject.toml
      ../bin
      ../nuvem_ruscher
      ../helper
      ../data
      ../po
      ../tests
    ];
  };

  strictDeps = true;

  nativeBuildInputs = [
    gettext
    gobject-introspection
    python
    wrapGAppsHook4
  ];

  # bash: interpretador do helper (o fixup troca o "#!/usr/bin/bash" pelo do Nix Store).
  buildInputs = [
    bash
    gtk4
    libadwaita
  ];

  makeFlags = [
    "PREFIX=${placeholder "out"}"
    "PYTHON=${python.interpreter}"
  ];

  # Os testes do helper ficam de fora: ele usa as ferramentas do sistema (/usr/bin), que
  # não existem no sandbox do Nix. Rodam no "make test" e no check() do PKGBUILD.
  # (Os de interface pulam sozinhos sem tela.)
  doCheck = true;
  nativeCheckInputs = [
    pythonForTests
    util-linux
  ];
  checkPhase = ''
    runHook preCheck
    ${pythonForTests.interpreter} -m pytest -p no:cacheprovider \
      --ignore=tests/test_helper.py --ignore=tests/test_helper_storage.py
    runHook postCheck
  '';

  postInstall = ''
    substituteInPlace $out/share/applications/io.github.ruscher.NuvemRuscher.desktop \
      --replace-fail "Exec=nuvem-ruscher" "Exec=$out/bin/nuvem-ruscher"
  '';

  # Só leitura do sistema (discos, rede) vem do Nix. docker, systemctl, sg, pkexec e
  # tailscale vêm do sistema de propósito: falam com daemons do sistema e alguns
  # precisam de setuid. O helper usa só o PATH do sistema (/usr/bin), definido nele.
  preFixup = ''
    gappsWrapperArgs+=(--prefix PATH : ${
      lib.makeBinPath [
        iproute2
        util-linux
      ]
    })
  '';

  meta = {
    description = "Instala, configura e cuida do Immich (alternativa livre ao Google Fotos) no BigLinux";
    homepage = "https://github.com/ruscher/nuvem-ruscher";
    license = lib.licenses.gpl3Plus;
    mainProgram = "nuvem-ruscher";
    platforms = lib.platforms.linux;
  };
}
