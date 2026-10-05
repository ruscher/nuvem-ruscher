{
  description = "Nuvem Ruscher: instala, configura e cuida do Immich no BigLinux";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    # Só Linux: o app gerencia systemd, Docker, polkit e /etc/fstab.
    flake-utils.lib.eachSystem [ "x86_64-linux" "aarch64-linux" ] (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        nuvem-ruscher = pkgs.callPackage ./nix/package.nix { };
      in
      {
        packages = {
          inherit nuvem-ruscher;
          default = nuvem-ruscher;
        };

        # "nix flake check" constrói o pacote, o que roda a suíte de testes (checkPhase).
        checks = {
          inherit nuvem-ruscher;
        };

        devShells.default = pkgs.mkShell {
          nativeBuildInputs = with pkgs; [
            gettext
            gobject-introspection
            (python3.withPackages (ps: [
              ps.pygobject3
              ps.qrcode
              ps.pytest
            ]))
            ruff
            shellcheck
            desktop-file-utils
            appstream
          ];
          buildInputs = with pkgs; [
            gtk4
            libadwaita
          ];
          # Para "./bin/nuvem-ruscher --simular" achar os schemas do GTK (diálogos de pasta).
          shellHook = ''
            export XDG_DATA_DIRS="$GSETTINGS_SCHEMAS_PATH''${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"
          '';
        };
      }
    );
}
