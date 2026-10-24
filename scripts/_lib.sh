# Shared by run.sh and dev.sh. Sourced, not executed. Everything here must
# work on the bash 3.2 that ships with macOS: no `wait -n`, no `${var,,}`,
# no associative arrays, no `mapfile`.

say() { printf '%s\n' "$*" >&2; }

# read_env_var FILE NAME -> prints the last value of NAME in a .env file,
# quotes stripped. Prints nothing if unset. Enough for the KEY=value files
# this repo uses; it is not a full dotenv parser.
read_env_var() {
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$2[[:space:]]*=[[:space:]]*//p" "$1" \
    | tail -n 1 | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/' | tr -d '[:space:]'
}

# url_port URL -> the explicit port, or the scheme default.
url_port() {
  local rest="${1#*://}" hostport
  hostport="${rest%%/*}"
  case "$hostport" in
    *:*) printf '%s\n' "${hostport##*:}" ;;
    *) case "$1" in https://*) echo 443 ;; *) echo 80 ;; esac ;;
  esac
}

# port_in_use PORT -> succeeds if something answers (or hangs) on 127.0.0.1:PORT.
# curl exit 7 is "connection refused", the one outcome that means free.
port_in_use() {
  curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/" && return 0
  [ $? -ne 7 ]
}

# kill_tree PID -> TERM a process and every descendant, children first.
# pnpm does not forward signals to the `ng serve` it spawns, and uvicorn
# --reload has a worker under the reloader; killing only the top PID leaves
# the real server running and the port taken.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

# ensure_node_modules DIR -> pnpm install when node_modules is missing or
# older than the lockfile (pnpm rewrites .modules.yaml on every install).
ensure_node_modules() {
  if [ ! -d "$1/node_modules" ] || [ "$1/pnpm-lock.yaml" -nt "$1/node_modules/.modules.yaml" ]; then
    (cd "$1" && pnpm install --frozen-lockfile >&2)
  fi
}
