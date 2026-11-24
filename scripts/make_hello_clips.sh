#!/usr/bin/env bash
# Make the landing page's greeting clips (tap the speech bubble to hear the companion).
# Same voice as the calls: Deepgram Flux TTS, model flux-ludvig-sv, expressivity 1
# (server/open_tutor/deepgram_tts.py). Needs DEEPGRAM_API_KEY in the environment
# (for example via `infisical run`), curl and ffmpeg. The spoken lines are kept in
# sync with web/src/locales/sv.ts (landing.hello*).
#
#   infisical run --projectId <open-tutor project> --env prod -- scripts/make_hello_clips.sh OUT_DIR
set -euo pipefail
set +x  # never trace: the API key is handled below
out=${1:?output directory}
mkdir -p "$out"
: "${DEEPGRAM_API_KEY:?DEEPGRAM_API_KEY is not set}"
declare -A LINES=(
  [primary]='Hej! Räven här. Tryck på knappen, så pratar vi om läxan!'
  [middle]='Hej! Lodjuret här. Tryck på knappen, så tar vi läxan tillsammans.'
  [upper]='Hej! Björnen här. Tryck på knappen, så kör vi.'
)
for band in primary middle upper; do
  text=${LINES[$band]}
  body=$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$text")
  # The key goes to curl as a config file on stdin (printf is a shell builtin),
  # so it never appears in any process's argv.
  printf 'header = "Authorization: Token %s"\n' "$DEEPGRAM_API_KEY" | curl -sS --fail-with-body -K - -X POST \
    "https://api.deepgram.com/v2/speak?model=flux-ludvig-sv&expressivity=1&encoding=linear16&container=wav" \
    -H 'Content-Type: application/json' \
    --data "$body" -o "$out/hello-$band.wav"
  ffmpeg -loglevel error -y -i "$out/hello-$band.wav" \
    -af "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-18:TP=-1.5" \
    -ac 1 -ar 44100 -b:a 64k "$out/hello-$band.mp3"
  rm "$out/hello-$band.wav"
  echo "$band: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out/hello-$band.mp3") s"
done
