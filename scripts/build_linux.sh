#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python}"

"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" -m pip install pyinstaller
"$PYTHON" -m PyInstaller --clean --noconfirm Fluoddity.spec

if [[ -d dist/Fluoddity/_internal/shaders ]]; then
  rm -rf dist/Fluoddity/shaders
  mv dist/Fluoddity/_internal/shaders dist/Fluoddity/shaders
fi

cp -f default_keyboard_controls.json dist/Fluoddity/default_keyboard_controls.json
cp -f default_imgui.ini dist/Fluoddity/default_imgui.ini
rm -rf dist/Fluoddity/physics_configs
mkdir -p dist/Fluoddity/physics_configs
cp -R physics_configs/Core dist/Fluoddity/physics_configs/Core
cp -R physics_configs/Advanced dist/Fluoddity/physics_configs/Advanced
rm -rf dist/Fluoddity/steam_input
mkdir -p dist/Fluoddity/steam_input
cp -R steam_input/* dist/Fluoddity/steam_input/
"$PYTHON" scripts/write_steam_input_handoff.py --output dist/Fluoddity/steam_input/steam_input_handoff.md

cat > dist/Fluoddity/run_steam_deck.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export FLUODDITY_STEAM_DECK=1
exec ./Fluoddity --steam-deck --game "$@"
EOF
chmod +x dist/Fluoddity/run_steam_deck.sh

echo "Linux build complete: dist/Fluoddity"
echo "Steam Deck launch target: dist/Fluoddity/run_steam_deck.sh"
