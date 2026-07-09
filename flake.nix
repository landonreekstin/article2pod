{
  description = "article2pod — read-it-later to podcast converter";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems
        (system: f nixpkgs.legacyPackages.${system});
    in {
      packages = forAllSystems (pkgs:
        let
          pythonEnv = pkgs.python3.withPackages (ps: with ps; [
            fastapi
            uvicorn
            trafilatura
            feedgen
            pydantic
          ]);
        in {
          default = pkgs.stdenv.mkDerivation {
            pname = "article2pod";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [ pkgs.makeWrapper ];
            installPhase = ''
              runHook preInstall
              mkdir -p $out/lib/article2pod
              cp app.py db.py extractor.py tts_client.py worker.py \
                $out/lib/article2pod/
              mkdir -p $out/bin
              makeWrapper ${pythonEnv}/bin/uvicorn $out/bin/article2pod-api \
                --set PYTHONPATH "$out/lib/article2pod" \
                --add-flags "app:app"
              makeWrapper ${pythonEnv}/bin/python $out/bin/article2pod-worker \
                --set PYTHONPATH "$out/lib/article2pod" \
                --prefix PATH : "${pkgs.ffmpeg}/bin" \
                --add-flags "$out/lib/article2pod/worker.py"
              runHook postInstall
            '';
            meta = with pkgs.lib; {
              description = "Read-it-later to podcast converter with TTS synthesis";
              license = licenses.gpl3;
              platforms = platforms.linux;
            };
          };
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [
              fastapi
              uvicorn
              trafilatura
              feedgen
              pydantic
            ]))
            pkgs.ffmpeg
          ];
        };
      });
    };
}
