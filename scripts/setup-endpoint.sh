#!/usr/bin/env bash
# Set up a local NeMo-Speech.cpp endpoint for live-transcribe-translate.
#
# Downloads the NeMo-Speech.cpp release binary, the Nemotron ASR and
# diarization models, converts Riva-Translate to GGUF, writes an env file and
# prints the `nemo-speech serve` command. Each step skips work that is already
# present and verified, so you can run the script again safely.
#
# See docs/endpoint.md.

set -euo pipefail

readonly NEMO_VERSION="0.2.0"
readonly NEMO_REPO="https://github.com/NVIDIA/NeMo-Speech.cpp"
readonly HF="https://huggingface.co"

readonly ASR_REPO="nvidia/nemotron-3.5-asr-streaming-0.6b"
readonly ASR_FILE="nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
readonly DIAR_REPO="nvidia/Nemotron-3-Diarization"
readonly DIAR_FILE="Nemotron-3-Diarization.q8_0.gguf"
readonly NMT_REPO="nvidia/Riva-Translate-4B-Instruct-v2"
readonly NMT_FILE="riva-translate-4b-instruct-v2.q8_0.gguf"

# Free space (GiB) that the translation model conversion needs under the
# prefix: about 9 GB checkpoint, about 2 GB venv, 4.4 GB output.
readonly CONVERT_FREE_GIB=17

backend=""
prefix="${XDG_DATA_HOME:-$HOME/.local/share}/live-transcribe-translate/endpoint"
translation=1
host="127.0.0.1"
port=8080
threads=4

usage() {
	cat <<EOF
Usage: $(basename "$0") --backend vulkan|cuda|cpu [options]

Set up a local NeMo-Speech.cpp ${NEMO_VERSION} endpoint (ASR, diarization and
translation) for live-transcribe-translate. Run it again at any time: it skips
the steps that are already done and verified.

Options:
  --backend B       vulkan, cuda or cpu. Required. Without it, the script
                    shows a suggestion for this machine and stops.
  --prefix DIR      Install directory.
                    Default: \${XDG_DATA_HOME:-~/.local/share}/live-transcribe-translate/endpoint
                    (now: ${prefix})
  --no-translation  Do not convert the Riva-Translate model (saves 4.4 GB and
                    the conversion).
  --host ADDR       Bind address for the printed serve command (default: ${host}).
                    The endpoint has no login: use a non-loopback address only
                    on a network that you trust.
  --port N          Port for the printed serve command (default: ${port}).
  --threads N       Endpoint worker count (default: ${threads}). Use at least the
                    number of Sources that you capture at the same time.
  -h, --help        Show this help.

The script needs curl, tar, sha256sum, git and uv. It stores all files under
the prefix (temporary files too), never in /tmp.
EOF
}

info() { printf '==> %s\n' "$*"; }
skip() { printf '    skip: %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

need_value() {
	[[ $# -ge 2 && -n $2 ]] || die "option $1 needs a value. See --help."
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--backend)
		need_value "$@"
		backend=$2
		shift 2
		;;
	--backend=*)
		backend=${1#*=}
		shift
		;;
	--prefix)
		need_value "$@"
		prefix=$2
		shift 2
		;;
	--prefix=*)
		prefix=${1#*=}
		shift
		;;
	--no-translation)
		translation=0
		shift
		;;
	--host)
		need_value "$@"
		host=$2
		shift 2
		;;
	--host=*)
		host=${1#*=}
		shift
		;;
	--port)
		need_value "$@"
		port=$2
		shift 2
		;;
	--port=*)
		port=${1#*=}
		shift
		;;
	--threads)
		need_value "$@"
		threads=$2
		shift 2
		;;
	--threads=*)
		threads=${1#*=}
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		die "unknown option: $1. See --help."
		;;
	esac
done

# ---------------------------------------------------------------------------
# Checks

suggest_backend() {
	local cap
	if command -v nvidia-smi >/dev/null 2>&1; then
		cap=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1 || true)
		if [[ -n $cap ]]; then
			if cuda_cap_ok "$cap"; then
				echo "cuda"
			else
				echo "vulkan"
			fi
			return
		fi
	fi
	if command -v vulkaninfo >/dev/null 2>&1 && vulkaninfo --summary 2>/dev/null | grep -q 'PHYSICAL_DEVICE_TYPE_\(DISCRETE\|INTEGRATED\)_GPU'; then
		echo "vulkan"
		return
	fi
	echo "cpu"
}

# True when compute capability $1 (for example "8.6") is 7.5 or higher.
cuda_cap_ok() {
	local major=${1%%.*} minor=${1#*.}
	[[ $major =~ ^[0-9]+$ && $minor =~ ^[0-9]+$ ]] || return 1
	((major * 10 + minor >= 75))
}

if [[ -z $backend ]]; then
	cat >&2 <<EOF
error: give --backend vulkan, cuda or cpu.
Suggestion for this machine: --backend $(suggest_backend)
  cuda    NVIDIA GPU with compute capability 7.5 or higher (Turing or newer)
  vulkan  any GPU with a Vulkan driver (Intel, AMD, older NVIDIA)
  cpu     no GPU (slow; real time is not guaranteed)
EOF
	exit 2
fi
case $backend in
vulkan | cuda | cpu) ;;
*) die "unknown backend '$backend'. Use vulkan, cuda or cpu." ;;
esac
if ! [[ $port =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
	die "--port must be a number from 1 to 65535."
fi
if ! [[ $threads =~ ^[0-9]+$ ]] || ((threads < 1)); then
	die "--threads must be a positive number."
fi
[[ $prefix != *[[:space:]]* ]] || die "the prefix must not contain spaces: '$prefix'."
[[ $prefix == /* ]] || prefix="$PWD/$prefix"

[[ $(uname -s) == Linux ]] || die "this script supports Linux only."
[[ $(uname -m) == x86_64 ]] || die "this script supports x86_64 only. On $(uname -m), build NeMo-Speech.cpp from source (see docs/endpoint.md)."

missing=()
for tool in curl tar sha256sum git uv; do
	command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
((${#missing[@]} == 0)) || die "install these tools first: ${missing[*]}."

if [[ $backend == cuda ]]; then
	if command -v nvidia-smi >/dev/null 2>&1; then
		while read -r cap; do
			[[ -n $cap ]] || continue
			cuda_cap_ok "$cap" || die "a GPU on this machine has CUDA compute capability $cap. The prebuilt CUDA archive supports 7.5 or higher only. Use --backend vulkan, or build NeMo-Speech.cpp from source for this GPU (see docs/endpoint.md)."
		done < <(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null || true)
	else
		warn "nvidia-smi not found: cannot check the CUDA compute capability (7.5 or higher is necessary)."
	fi
fi

if [[ $host != 127.* && $host != localhost && $host != ::1 ]]; then
	warn "the endpoint will listen on $host. It has no login: anyone who can reach this port can use it."
fi

readonly archive_name="nemo-speech-${NEMO_VERSION}-linux-x86_64-${backend}"
readonly downloads="$prefix/downloads"
readonly models="$prefix/models"
readonly install_dir="$prefix/$archive_name"
readonly bin_link="$prefix/bin/nemo-speech"
readonly env_file="$prefix/endpoint.env"

mkdir -p "$downloads" "$models" "$prefix/bin"

# ---------------------------------------------------------------------------
# Helpers

# Download URL $1 to file $2 with resume. Write to $2.part and move it into
# place only when the download completes.
fetch() {
	local url=$1 out=$2
	curl -fL --retry 3 --retry-delay 5 -C - --progress-bar -o "$out.part" "$url" ||
		die "download failed: $url"
	mv -f "$out.part" "$out"
}

# True when "$dir/$file.sha256" exists and the file matches it.
sidecar_ok() {
	local dir=$1 file=$2
	[[ -f $dir/$file && -f $dir/$file.sha256 ]] || return 1
	(cd "$dir" && sha256sum --status -c "$file.sha256")
}

# ---------------------------------------------------------------------------
# Step 1: NeMo-Speech.cpp release binary

step_binary() {
	local tarball="$archive_name.tar.gz"
	local url="$NEMO_REPO/releases/download/v$NEMO_VERSION/$tarball"
	info "1/4 NeMo-Speech.cpp $NEMO_VERSION ($backend)"

	if [[ -x $install_dir/bin/nemo-speech ]] && sidecar_ok "$downloads" "$tarball"; then
		skip "$install_dir is present and the archive checksum is correct."
	else
		if sidecar_ok "$downloads" "$tarball"; then
			skip "archive is present and its checksum is correct."
		else
			fetch "$url.sha256" "$downloads/$tarball.sha256"
			fetch "$url" "$downloads/$tarball"
			(cd "$downloads" && sha256sum -c "$tarball.sha256") ||
				die "checksum of $tarball is not correct. Remove $downloads/$tarball and try again."
		fi
		local staging="$prefix/.extract"
		rm -rf "$staging" "$install_dir"
		mkdir -p "$staging"
		tar -xzf "$downloads/$tarball" -C "$staging"
		[[ -x $staging/$archive_name/bin/nemo-speech ]] ||
			die "the archive does not contain $archive_name/bin/nemo-speech."
		mv "$staging/$archive_name" "$install_dir"
		rmdir "$staging"
		echo "    installed $install_dir"
	fi

	local target="../$archive_name/bin/nemo-speech"
	if [[ $(readlink "$bin_link" 2>/dev/null || true) != "$target" ]]; then
		ln -sfn "$target" "$bin_link"
		echo "    linked $bin_link -> $target"
	fi
	"$bin_link" --version >/dev/null 2>&1 ||
		die "$bin_link does not run. Check the $backend driver and libraries (run '$bin_link --version' to see the error)."
}

# ---------------------------------------------------------------------------
# Step 2: ASR and diarization models from Hugging Face

# Print "<sha256> <size>" for file $2 in repo $1 from the Hugging Face tree
# API. The sha256 is "-" when the API gives no LFS oid. Print nothing on
# failure.
hf_file_info() {
	local repo=$1 file=$2 json piece oid size
	json=$(curl -fsSL "$HF/api/models/$repo/tree/main" 2>/dev/null) || return 0
	# Each "{" starts a new line. The "lfs" object then is on the same line
	# as the "path" of its file: "oid":"...","size":N,...},"path":"FILE"}
	piece=$(printf '%s' "$json" | tr '{' '\n' | grep -F "\"path\":\"$file\"" || true)
	if [[ $piece =~ \"oid\":\"([0-9a-f]{64})\" ]]; then
		oid=${BASH_REMATCH[1]}
		[[ $piece =~ \"size\":([0-9]+) ]] && size=${BASH_REMATCH[1]}
		[[ -n ${size:-} ]] && printf '%s %s\n' "$oid" "$size"
		return 0
	fi
	# No LFS oid: use the size from the download headers.
	size=$(curl -fsSIL "$HF/$repo/resolve/main/$file" 2>/dev/null |
		tr -d '\r' | sed -n 's/^x-linked-size: *//Ip' | tail -n 1 || true)
	[[ -n $size ]] && printf -- '- %s\n' "$size"
	return 0
}

fetch_model() {
	local repo=$1 file=$2 info_line sha size actual
	if sidecar_ok "$models" "$file"; then
		skip "$file is present and verified."
		return
	fi
	info_line=$(hf_file_info "$repo" "$file")
	[[ -n $info_line ]] || die "cannot get the size of $repo/$file from Hugging Face."
	read -r sha size <<<"$info_line"
	echo "    download $repo/$file ($((size / 1024 / 1024)) MiB)"
	fetch "$HF/$repo/resolve/main/$file" "$models/$file"
	actual=$(stat -c %s "$models/$file")
	[[ $actual == "$size" ]] || {
		rm -f "$models/$file"
		die "$file has $actual bytes, expected $size. Run the script again."
	}
	if [[ $sha == - ]]; then
		warn "Hugging Face gives no sha256 for $file: only its size is verified."
		sha=$(sha256sum "$models/$file" | cut -d' ' -f1)
	fi
	printf '%s  %s\n' "$sha" "$file" >"$models/$file.sha256"
	(cd "$models" && sha256sum -c "$file.sha256") || {
		rm -f "$models/$file" "$models/$file.sha256"
		die "checksum of $file is not correct. Run the script again."
	}
}

step_models() {
	info "2/4 ASR and diarization models"
	fetch_model "$ASR_REPO" "$ASR_FILE"
	fetch_model "$DIAR_REPO" "$DIAR_FILE"
}

# ---------------------------------------------------------------------------
# Step 3: convert Riva-Translate to GGUF

step_translation() {
	info "3/4 translation model ($NMT_REPO)"
	if ((!translation)); then
		skip "--no-translation is set."
		return
	fi
	if sidecar_ok "$models" "$NMT_FILE"; then
		skip "$NMT_FILE is present and verified."
		return
	fi

	local work="$prefix/work/riva-convert"
	local src="$work/src" venv="$work/venv" part="$models/${NMT_FILE%.gguf}.part.gguf"
	mkdir -p "$work/tmp"

	local free_gib
	free_gib=$(($(df -Pk "$work" | awk 'NR == 2 { print $4 }') / 1024 / 1024))
	((free_gib >= CONVERT_FREE_GIB)) ||
		die "the conversion needs about $CONVERT_FREE_GIB GiB free under $prefix, but only $free_gib GiB is free. Free some space, or use --no-translation."

	# Keep all temporary and cache files in the work directory, so that the
	# cleanup removes them. Read an existing Hugging Face token before HF_HOME
	# changes.
	local token_file="${HF_HOME:-$HOME/.cache/huggingface}/token"
	if [[ -z ${HF_TOKEN:-} && -r $token_file ]]; then
		HF_TOKEN=$(<"$token_file")
		export HF_TOKEN
	fi
	export HF_HOME="$work/hf" TMPDIR="$work/tmp" UV_CACHE_DIR="$work/uv-cache"

	if [[ ! -f $src/convert_model.py ]]; then
		echo "    clone NeMo-Speech.cpp v$NEMO_VERSION source"
		rm -rf "$src"
		git -c advice.detachedHead=false clone --quiet --depth 1 --branch "v$NEMO_VERSION" "$NEMO_REPO.git" "$src"
	fi
	if [[ ! -f $src/llama.cpp/convert_hf_to_gguf.py ]]; then
		echo "    fetch the pinned llama.cpp submodule"
		git -C "$src" submodule update --init --depth 1 llama.cpp
	fi

	if [[ ! -f $venv/.ltt-ready ]]; then
		echo "    create the conversion venv (CPU PyTorch)"
		rm -rf "$venv"
		uv venv --quiet -p 3.12 "$venv"
		uv pip install --quiet --python "$venv/bin/python" \
			-r "$src/requirements.txt" --index-strategy unsafe-best-match
		touch "$venv/.ltt-ready"
	fi

	echo "    convert (downloads about 9 GB the first time)"
	rm -f "$part"
	"$venv/bin/python" "$src/convert_model.py" "$NMT_REPO" \
		--outfile "$part" --outtype q8_0 --cache-dir "$HF_HOME/hub" ||
		die "the conversion failed. The work files stay in $work, so a new run continues the download. Remove that directory to start again."
	[[ $(head -c 4 "$part") == GGUF ]] || die "$part is not a GGUF file."

	mv -f "$part" "$models/$NMT_FILE"
	(cd "$models" && sha256sum "$NMT_FILE" >"$NMT_FILE.sha256")
	echo "    wrote $models/$NMT_FILE"

	echo "    remove the work files ($work)"
	rm -rf "$work"
	rmdir "$prefix/work" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Step 4: env file and serve command

step_env() {
	info "4/4 env file and serve command"
	local nmt_model="" nmt_args=""
	if ((translation)); then
		nmt_model="$models/$NMT_FILE"
		nmt_args="--nmt.model.path $nmt_model"
	elif [[ -f $models/$NMT_FILE ]]; then
		warn "--no-translation is set: the endpoint will not load $models/$NMT_FILE."
	fi

	local new
	new=$(
		cat <<EOF
# Written by scripts/setup-endpoint.sh. Run the script again to change it.
# Read by scripts/systemd/ltt-endpoint.service (EnvironmentFile=) and by sh.
NEMO_SPEECH_BIN="$bin_link"
LTT_ENDPOINT_ASR_MODEL="$models/$ASR_FILE"
LTT_ENDPOINT_DIAR_MODEL="$models/$DIAR_FILE"
LTT_ENDPOINT_NMT_MODEL="$nmt_model"
LTT_ENDPOINT_NMT_ARGS="$nmt_args"
LTT_ENDPOINT_DEVICE="$backend"
LTT_ENDPOINT_HOST="$host"
LTT_ENDPOINT_PORT="$port"
LTT_ENDPOINT_THREADS="$threads"
EOF
	)
	if [[ -f $env_file && $(<"$env_file") == "$new" ]]; then
		skip "$env_file is up to date."
	else
		printf '%s\n' "$new" >"$env_file"
		echo "    wrote $env_file"
	fi

	local cmd=("$bin_link" serve
		--asr-model "$models/$ASR_FILE"
		--diar-model "$models/$DIAR_FILE")
	((translation)) && cmd+=(--nmt.model.path "$models/$NMT_FILE")
	cmd+=(--device "$backend" --host "$host" --port "$port" --no-ui
		--threads "$threads"
		--asr.endpointing.enable=true --asr.batching.enabled=false)

	local url_host=$host
	[[ $host == 0.0.0.0 || $host == :: ]] && url_host="<this machine's address>"
	[[ $url_host == *:* && $url_host != \<* ]] && url_host="[$url_host]"

	cat <<EOF

Done. Start the endpoint with:

  $(printf '%q ' "${cmd[@]}" | sed 's/ $//; s/ --/ \\\n    --/g')

Or copy scripts/systemd/ltt-endpoint.service to ~/.config/systemd/user/ and
run (see docs/endpoint.md):

  systemctl --user enable --now ltt-endpoint.service

Point the app at the endpoint:

  export LTT_ASR_ENDPOINT_URL=ws://$url_host:$port

or in ~/.config/live-transcribe-translate/config.toml:

  asr_endpoint_url = "ws://$url_host:$port"

Check it with: curl http://$url_host:$port/ready
EOF
}

info "prefix: $prefix"
step_binary
step_models
step_translation
step_env
