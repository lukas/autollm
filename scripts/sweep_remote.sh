#!/usr/bin/env bash
#
# Remote sweep controller: run sweeps on a Kubernetes pod.
#
# Usage:
#   scripts/sweep_remote.sh start    --sweep NAME [--model-dir DIR] [--benchmark BENCH] [--runs N] [--goal GOAL] [--force]
#   scripts/sweep_remote.sh improve  --sweep NAME [--runs N] [--allow-model-change]
#   scripts/sweep_remote.sh set-runs --sweep NAME --runs N
#   scripts/sweep_remote.sh sync     [--sweep NAME]
#   scripts/sweep_remote.sh logs
#   scripts/sweep_remote.sh status
#   scripts/sweep_remote.sh teardown
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTROLLER_POD="${CONTROLLER_POD:-autollm-controller}"
REMOTE_DIR="/workspace/autollm"

# ── helpers ──────────────────────────────────────────────────────────────────

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

pod_exists() { kubectl get pod "$CONTROLLER_POD" &>/dev/null; }
pod_ready()  { kubectl exec "$CONTROLLER_POD" -- test -f /tmp/ready &>/dev/null; }

sync_tar_entries() {
    local remote_base="$1"
    local local_dest="$2"
    shift 2
    [ "$#" -gt 0 ] || return 0

    # Results may be actively written during a live sweep; tolerate file changes while archiving.
    kubectl exec "$CONTROLLER_POD" -- tar --ignore-failed-read --warning=no-file-changed -czf - -C "$remote_base" "$@" 2>/dev/null \
        | tar xzf - -C "$local_dest"
}

append_unique() {
    local item="$1"
    shift
    local existing=""
    for existing in "$@"; do
        [ "$existing" = "$item" ] && return 0
    done
    return 1
}

sync_single_sweep_incremental() {
    local sweep="$1"
    local remote_root="$REMOTE_DIR/results"
    local remote_sweep="$remote_root/sweep-${sweep}"
    local local_results="$PROJECT_DIR/results"
    local local_sweep="$local_results/sweep-${sweep}"

    kubectl exec "$CONTROLLER_POD" -- test -d "$remote_sweep" \
        || die "Remote sweep not found on controller: sweep-${sweep}"

    mkdir -p "$local_sweep"
    info "Syncing sweep-${sweep} results from controller..."

    local -a entries=(
        "sweep-${sweep}/sweep_metadata.json"
        "sweep-${sweep}/OVERVIEW.md"
        "sweep-${sweep}/leaderboard.txt"
        "sweep-${sweep}/FULL_RETRO.txt"
        "sweep-${sweep}/RESEARCH_LOG.md"
        "sweep-${sweep}/RESEARCH_MEMORY.md"
        "sweep-${sweep}/results.txt"
        "sweep-${sweep}/agent.log"
        "sweep-${sweep}/meta-feedback.txt"
        "sweep-${sweep}/baseline"
        "sweep-${sweep}/best-runllm"
    )

    local -a remote_runs=()
    local remote_runs_text=""
    remote_runs_text=$(
        kubectl exec "$CONTROLLER_POD" -- bash -lc \
            "cd '$remote_sweep' && ls -1d 20[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | sort"
    )
    if [ -n "$remote_runs_text" ]; then
        while IFS= read -r run; do
            [ -n "$run" ] && remote_runs+=("$run")
        done <<EOF
$remote_runs_text
EOF
    fi

    local -a selected_runs=()
    local run=""
    for run in "${remote_runs[@]}"; do
        [ -z "$run" ] && continue
        if [ ! -d "$local_sweep/$run" ]; then
            selected_runs+=("$run")
        fi
    done

    local total_runs="${#remote_runs[@]}"
    local newest_count=2
    local start_idx=0
    if [ "$total_runs" -gt "$newest_count" ]; then
        start_idx=$((total_runs - newest_count))
    fi
    local idx=0
    for ((idx=start_idx; idx<total_runs; idx++)); do
        run="${remote_runs[$idx]}"
        [ -z "$run" ] && continue
        if [ "${#selected_runs[@]}" -eq 0 ]; then
            selected_runs+=("$run")
        elif ! append_unique "$run" "${selected_runs[@]}"; then
            selected_runs+=("$run")
        fi
    done

    if [ "${#selected_runs[@]}" -gt 0 ]; then
        for run in "${selected_runs[@]}"; do
            entries+=("sweep-${sweep}/${run}")
        done
    fi

    sync_tar_entries "$remote_root" "$local_results" "${entries[@]}"
    info "Results synced to $local_results (top-level files + ${#selected_runs[@]} run dirs)"
}

ensure_controller() {
    if pod_exists; then
        info "Controller pod '$CONTROLLER_POD' already exists"
        if pod_ready; then
            return 0
        fi
    else
        info "Applying RBAC..."
        kubectl apply -f "$PROJECT_DIR/sweep-controller-rbac.yaml"

        info "Creating controller pod..."
        kubectl apply -f "$PROJECT_DIR/sweep-controller.yaml"
    fi

    info "Waiting for controller pod to be Running..."
    kubectl wait --for=condition=Ready "pod/$CONTROLLER_POD" --timeout=300s 2>/dev/null || true

    info "Waiting for controller setup (kubectl + uv install)..."
    local tries=0
    while ! pod_ready; do
        tries=$((tries + 1))
        if [ "$tries" -gt 120 ]; then
            die "Controller setup timed out after 10 minutes"
        fi
        sleep 5
    done
    info "Controller ready"
}

sync_code() {
    info "Syncing code to controller pod..."
    kubectl exec "$CONTROLLER_POD" -- mkdir -p "$REMOTE_DIR"

    tar czf - \
        --exclude='./results' \
        --exclude='./.git' \
        --exclude='./runllm/.git' \
        --exclude='./__pycache__' \
        --exclude='./scripts/__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.log' \
        --exclude='./sweep.log' \
        --exclude='./sweep-*.log' \
        --exclude='./.venv' \
        -C "$PROJECT_DIR" . \
        | kubectl exec -i "$CONTROLLER_POD" -- tar xzf - -C "$REMOTE_DIR"

    # Copy .env for API keys
    if [ -f "$PROJECT_DIR/.env" ]; then
        info "Copying .env..."
        kubectl cp "$PROJECT_DIR/.env" "$CONTROLLER_POD:$REMOTE_DIR/.env" --no-preserve=true
    fi

    # Inject API keys from local environment (they may not be in .env files)
    local env_append=""
    [ -n "${ANTHROPIC_API_KEY:-}" ] && env_append+="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"$'\n'
    [ -n "${OPENAI_API_KEY:-}" ]    && env_append+="OPENAI_API_KEY=${OPENAI_API_KEY}"$'\n'
    [ -n "${EXA_API_KEY:-}" ]       && env_append+="EXA_API_KEY=${EXA_API_KEY}"$'\n'
    [ -n "${AI_PROVIDER:-}" ]       && env_append+="AI_PROVIDER=${AI_PROVIDER}"$'\n'
    [ -n "${AI_MODEL:-}" ]          && env_append+="AI_MODEL=${AI_MODEL}"$'\n'
    if [ -n "$env_append" ]; then
        info "Injecting environment overrides from local environment..."
        kubectl exec -i "$CONTROLLER_POD" -- tee -a "$REMOTE_DIR/.env" > /dev/null <<< "$env_append"
    fi

    info "Code synced"
}

sync_sweep_results() {
    local sweep="$1"
    local local_sweep="$PROJECT_DIR/results/sweep-${sweep}"

    [ -d "$local_sweep" ] || die "Local sweep results not found: $local_sweep"

    info "Syncing local results for sweep-${sweep} to controller pod..."
    kubectl exec "$CONTROLLER_POD" -- mkdir -p "$REMOTE_DIR/results"
    tar czf - -C "$PROJECT_DIR/results" "sweep-${sweep}" \
        | kubectl exec -i "$CONTROLLER_POD" -- tar xzf - -C "$REMOTE_DIR/results"
    info "Sweep results synced to pod"
}

sweep_is_running() {
    local sweep="$1"
    local pid_file="/workspace/sweep-${sweep}.pid"
    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "if [ ! -f '$pid_file' ]; then exit 1; fi; pid=\$(cat '$pid_file'); stat=\$(ps -o stat= -p \"\$pid\" 2>/dev/null | tr -d ' '); [ -n \"\$stat\" ] && [[ \"\$stat\" != Z* ]]" &>/dev/null
}

save_start_count() {
    local sweep="$1"
    local start_file="/workspace/sweep-${sweep}.start_count"
    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "ls -d $REMOTE_DIR/results/sweep-${sweep}/20[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | wc -l | tr -d ' ' > $start_file"
}

write_remote_launcher() {
    local sweep="$1"
    local script_file="$2"
    local launcher_file="$3"
    local pid_file="$4"
    local exit_file="$5"

    local launcher_body="#!/usr/bin/env bash
set -uo pipefail
trap 'rm -f \"$pid_file\"' EXIT
set +e
\"$script_file\"
rc=\$?
echo \"\$rc\" > \"$exit_file\"
exit \"\$rc\"
"

    kubectl exec -i "$CONTROLLER_POD" -- tee "$launcher_file" > /dev/null <<< "$launcher_body"
    kubectl exec "$CONTROLLER_POD" -- chmod +x "$launcher_file"
}

# ── actions ──────────────────────────────────────────────────────────────────

action_start() {
    local sweep="" model_dir="qwen2.5-1.5b" benchmark="quick" runs="1" goal="" force=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --sweep)      sweep="$2";     shift 2 ;;
            --model-dir)  model_dir="$2"; shift 2 ;;
            --benchmark)  benchmark="$2"; shift 2 ;;
            --runs)       runs="$2";      shift 2 ;;
            --goal)       goal="$2";      shift 2 ;;
            --force)      force="1";      shift   ;;
            *) die "Unknown arg: $1" ;;
        esac
    done
    [ -n "$sweep" ] || die "--sweep NAME is required"

    ensure_controller
    sync_code

    local log_file="/workspace/sweep-${sweep}.log"
    local script_file="/workspace/sweep-${sweep}.sh"
    local launcher_file="/workspace/sweep-${sweep}.launcher.sh"
    local pid_file="/workspace/sweep-${sweep}.pid"
    local exit_file="/workspace/sweep-${sweep}.exit_code"

    local target_file="/workspace/sweep-${sweep}.target_runs"

    # Write the sweep script with a target-file loop (so RUNS can be bumped live)
    local sweep_cmd="make sweep SWEEP=${sweep} MODEL_DIR=${model_dir} BENCHMARK=${benchmark}"
    [ -n "$goal" ]  && sweep_cmd+=" GOAL=\"${goal}\""
    [ -n "$force" ] && sweep_cmd+=" FORCE=1"

    local improve_flags=""
    local script_body="#!/usr/bin/env bash
set -euo pipefail
export PATH=/root/.local/bin:\$PATH
cd $REMOTE_DIR

# Source .env files and export all variables (API keys, etc.)
set -a
[ -f /workspace/.env ] && source /workspace/.env
[ -f .env ] && source .env
set +a

env -u VIRTUAL_ENV uv sync --extra guidellm --extra ai_optimizer
${sweep_cmd}

# Improve loop: reads target from file each iteration so it can be bumped live
i=0
while true; do
    target=\$(cat $target_file 2>/dev/null || echo 0)
    [ \"\$i\" -ge \"\$target\" ] && break
    i=\$((i + 1))
    echo \"\"
    echo \"══════════════════════════════════════════\"
    echo \"  Improvement run \$i/\$target\"
    echo \"══════════════════════════════════════════\"
    rc=0
    env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --sweep \"${sweep}\" ${improve_flags} || rc=\$?
    if [ \"\$rc\" -eq 40 ]; then
        echo \"Sweep stop policy triggered; stopping remote improve loop.\"
        break
    fi
done
"

    kubectl exec -i "$CONTROLLER_POD" -- tee "$script_file" > /dev/null <<< "$script_body"
    kubectl exec "$CONTROLLER_POD" -- chmod +x "$script_file"
    write_remote_launcher "$sweep" "$script_file" "$launcher_file" "$pid_file" "$exit_file"
    kubectl exec "$CONTROLLER_POD" -- bash -c "echo ${runs} > $target_file"
    kubectl exec "$CONTROLLER_POD" -- rm -f "$pid_file" "$exit_file"

    save_start_count "$sweep"

    info "Starting sweep '${sweep}' on controller pod (${runs} runs, ${benchmark} benchmark)..."
    info "Logs: kubectl exec $CONTROLLER_POD -- tail -f $log_file"
    info ""

    # Run in background inside the pod so it survives if we disconnect
    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "nohup $launcher_file > $log_file 2>&1 < /dev/null & echo \$! > $pid_file; echo \"Sweep PID: \$(cat $pid_file)\""

    info ""
    info "Sweep started in background on '$CONTROLLER_POD'"
    info ""
    info "Useful commands:"
    info "  make sweep-logs                           # tail live output"
    info "  make sweep-status                         # check if sweep is running"
    info "  make sync-results SWEEP=${sweep}          # copy results to local machine"
    info "  make sweep-remote-teardown                # delete controller pod"
}

action_improve() {
    local sweep="" runs="1" allow_model_change=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --sweep)              sweep="$2";            shift 2 ;;
            --runs)               runs="$2";             shift 2 ;;
            --allow-model-change) allow_model_change="1"; shift   ;;
            *) die "Unknown arg: $1" ;;
        esac
    done
    [ -n "$sweep" ] || die "--sweep NAME is required"

    ensure_controller

    local target_file="/workspace/sweep-${sweep}.target_runs"

    if sweep_is_running "$sweep"; then
        # Bump the target so the running loop picks it up on the next iteration
        kubectl exec "$CONTROLLER_POD" -- bash -c "echo ${runs} > $target_file"
        info "Sweep '${sweep}' is already running — updated target to ${runs} runs."
        info ""
        info "Useful commands:"
        info "  make sweep-logs                           # tail live output"
        info "  make sweep-status                         # check running sweeps"
        info "  make sync-results SWEEP=${sweep}          # copy results to local machine"
        return 0
    fi

    sync_code
    sync_sweep_results "$sweep"

    local log_file="/workspace/sweep-${sweep}.log"
    local script_file="/workspace/sweep-${sweep}.sh"
    local launcher_file="/workspace/sweep-${sweep}.launcher.sh"
    local pid_file="/workspace/sweep-${sweep}.pid"
    local exit_file="/workspace/sweep-${sweep}.exit_code"

    local improve_flags=""
    [ -n "$allow_model_change" ] && improve_flags+="--allow-model-change "

    local script_body="#!/usr/bin/env bash
set -euo pipefail
export PATH=/root/.local/bin:\$PATH
cd $REMOTE_DIR

set -a
[ -f /workspace/.env ] && source /workspace/.env
[ -f .env ] && source .env
set +a

env -u VIRTUAL_ENV uv sync --extra guidellm --extra ai_optimizer

# Improve loop: reads target from file each iteration so it can be bumped live
i=0
while true; do
    target=\$(cat $target_file 2>/dev/null || echo 0)
    [ \"\$i\" -ge \"\$target\" ] && break
    i=\$((i + 1))
    echo \"\"
    echo \"══════════════════════════════════════════\"
    echo \"  Improvement run \$i/\$target\"
    echo \"══════════════════════════════════════════\"
    rc=0
    env -u VIRTUAL_ENV uv run python scripts/ai_experiment.py --sweep \"${sweep}\" ${improve_flags} || rc=\$?
    if [ \"\$rc\" -eq 40 ]; then
        echo \"Sweep stop policy triggered; stopping remote improve loop.\"
        break
    fi
done
"

    kubectl exec -i "$CONTROLLER_POD" -- tee "$script_file" > /dev/null <<< "$script_body"
    kubectl exec "$CONTROLLER_POD" -- chmod +x "$script_file"
    write_remote_launcher "$sweep" "$script_file" "$launcher_file" "$pid_file" "$exit_file"
    kubectl exec "$CONTROLLER_POD" -- bash -c "echo ${runs} > $target_file"
    kubectl exec "$CONTROLLER_POD" -- rm -f "$pid_file" "$exit_file"

    save_start_count "$sweep"

    info "Starting improve for sweep '${sweep}' on controller pod (${runs} runs)..."
    info "Logs: kubectl exec $CONTROLLER_POD -- tail -f $log_file"
    info ""

    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "nohup $launcher_file > $log_file 2>&1 < /dev/null & echo \$! > $pid_file; echo \"Sweep PID: \$(cat $pid_file)\""

    info ""
    info "Improve started in background on '$CONTROLLER_POD'"
    info ""
    info "Useful commands:"
    info "  make sweep-logs                           # tail live output"
    info "  make sweep-status                         # check if sweep is running"
    info "  make sync-results SWEEP=${sweep}          # copy results to local machine"
    info "  make sweep-remote-teardown                # delete controller pod"
}

action_set_runs() {
    local sweep="" runs=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --sweep) sweep="$2"; shift 2 ;;
            --runs)  runs="$2";  shift 2 ;;
            *) die "Unknown arg: $1" ;;
        esac
    done
    [ -n "$sweep" ] || die "--sweep NAME is required"
    [ -n "$runs" ]  || die "--runs N is required"

    pod_exists || die "Controller pod '$CONTROLLER_POD' not found."

    local target_file="/workspace/sweep-${sweep}.target_runs"
    kubectl exec "$CONTROLLER_POD" -- bash -c "echo ${runs} > $target_file"

    if sweep_is_running "$sweep"; then
        info "Set target to ${runs} runs for '${sweep}' — will take effect on next iteration."
    else
        info "Set target to ${runs} runs for '${sweep}' (sweep is not currently running)."
    fi
}

action_sync() {
    local sweep=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --sweep) sweep="$2"; shift 2 ;;
            *) die "Unknown arg: $1" ;;
        esac
    done

    pod_exists || die "Controller pod '$CONTROLLER_POD' not found. Nothing to sync."

    local local_results="$PROJECT_DIR/results"
    mkdir -p "$local_results"

    if [ -n "$sweep" ]; then
        sync_single_sweep_incremental "$sweep"
    else
        info "Syncing ALL sweeps from controller..."
        local -a sweeps=()
        local sweeps_text=""
        sweeps_text=$(
            kubectl exec "$CONTROLLER_POD" -- bash -lc \
                "cd '$REMOTE_DIR/results' && ls -1d sweep-* 2>/dev/null | sed 's/^sweep-//' | sort"
        )
        if [ -n "$sweeps_text" ]; then
            while IFS= read -r sweep_name; do
                [ -n "$sweep_name" ] && sweeps+=("$sweep_name")
            done <<EOF
$sweeps_text
EOF
        fi
        local sweep_name=""
        for sweep_name in "${sweeps[@]}"; do
            [ -z "$sweep_name" ] && continue
            sync_single_sweep_incremental "$sweep_name"
        done
    fi
}

action_logs() {
    pod_exists || die "Controller pod '$CONTROLLER_POD' not found."

    # Find the most recent sweep log
    local log_file
    log_file=$(kubectl exec "$CONTROLLER_POD" -- bash -c \
        'ls -t /workspace/sweep-*.log 2>/dev/null | head -1' 2>/dev/null || true)

    if [ -z "$log_file" ]; then
        die "No sweep log files found on controller"
    fi

    info "Tailing $log_file (Ctrl+C to stop)..."
    kubectl exec "$CONTROLLER_POD" -- tail -f "$log_file"
}

action_status() {
    if ! pod_exists; then
        echo "Controller pod '$CONTROLLER_POD' does not exist."
        return 0
    fi

    echo "Controller pod: $CONTROLLER_POD"
    kubectl get pod "$CONTROLLER_POD" -o wide --no-headers 2>/dev/null || true
    echo ""

    # Check for running sweeps, with progress info
    local pids
    pids=$(kubectl exec "$CONTROLLER_POD" -- bash -c '
        for f in /workspace/sweep-*.pid; do
            [ -f "$f" ] || continue
            pid=$(cat "$f")
            sweep=$(basename "$f" .pid | sed "s/^sweep-//")

            # Read target from the live target file, fall back to parsing the script
            target_file="/workspace/sweep-${sweep}.target_runs"
            target_runs=""
            if [ -f "$target_file" ]; then
                target_runs=$(cat "$target_file" | tr -d " \n")
            else
                script="/workspace/sweep-${sweep}.sh"
                if [ -f "$script" ]; then
                    target_runs=$(grep -oP "RUNS=\K[0-9]+" "$script" 2>/dev/null || true)
                fi
            fi

            # Count completed run directories (timestamped dirs like 20260313_120000)
            results_dir="'"$REMOTE_DIR"'/results/sweep-${sweep}"
            total_runs=0
            if [ -d "$results_dir" ]; then
                total_runs=$(ls -d "$results_dir"/20[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | wc -l)
            fi

            # Subtract pre-existing runs to get runs completed in this session
            start_file="/workspace/sweep-${sweep}.start_count"
            start_count=0
            if [ -f "$start_file" ]; then
                start_count=$(cat "$start_file" | tr -d " \n")
            fi
            new_runs=$((total_runs - start_count))
            [ "$new_runs" -lt 0 ] && new_runs=0

            progress=""
            if [ -n "$target_runs" ] && [ "$new_runs" -le "$target_runs" ]; then
                progress=" — run ${new_runs}/${target_runs} (${total_runs} total)"
            elif [ -n "$target_runs" ]; then
                progress=" — ${total_runs} total, target ${target_runs}"
            elif [ "$total_runs" -gt 0 ]; then
                progress=" — ${total_runs} runs total"
            fi

            proc_state=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d " ")
            if [ -n "$proc_state" ] && [[ "$proc_state" != Z* ]]; then
                echo "  RUNNING: $sweep (PID $pid)${progress}"
            else
                rm -f "$f"
                if [ -n "$proc_state" ] && [[ "$proc_state" == Z* ]]; then
                    echo "  DONE:    $sweep (stale zombie PID $pid cleaned)${progress}"
                else
                    echo "  DONE:    $sweep (PID $pid cleaned)${progress}"
                fi
            fi
        done' 2>/dev/null || true)

    if [ -n "$pids" ]; then
        echo "Sweeps:"
        echo "$pids"
    else
        echo "No sweep processes found."
    fi

    echo ""
    # List result directories
    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "ls -d $REMOTE_DIR/results/sweep-*/ 2>/dev/null | sed 's|.*/||' || echo '(no results yet)'" 2>/dev/null || true
}

action_teardown() {
    if pod_exists; then
        info "Deleting controller pod '$CONTROLLER_POD'..."
        kubectl delete pod "$CONTROLLER_POD" --ignore-not-found=true
        info "Controller pod deleted"
    else
        info "Controller pod '$CONTROLLER_POD' does not exist"
    fi
}

# ── main ─────────────────────────────────────────────────────────────────────

[ $# -ge 1 ] || die "Usage: $0 {start|improve|set-runs|sync|logs|status|teardown} [args...]"
ACTION="$1"; shift

case "$ACTION" in
    start)    action_start "$@" ;;
    improve)  action_improve "$@" ;;
    set-runs) action_set_runs "$@" ;;
    sync)     action_sync "$@" ;;
    logs)     action_logs "$@" ;;
    status)   action_status "$@" ;;
    teardown) action_teardown "$@" ;;
    *)        die "Unknown action: $ACTION. Use: start, improve, set-runs, sync, logs, status, teardown" ;;
esac
