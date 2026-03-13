#!/usr/bin/env bash
#
# Remote sweep controller: run sweeps on a Kubernetes pod.
#
# Usage:
#   scripts/sweep_remote.sh start --sweep NAME [--model-dir DIR] [--benchmark BENCH] [--runs N] [--goal GOAL] [--force]
#   scripts/sweep_remote.sh sync  [--sweep NAME]
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

    # Copy .env files for API keys
    for envfile in "$PROJECT_DIR/.env" "$PROJECT_DIR/../.env"; do
        if [ -f "$envfile" ]; then
            info "Copying $(basename "$envfile") from $(dirname "$envfile")..."
            if [ "$envfile" = "$PROJECT_DIR/.env" ]; then
                kubectl cp "$envfile" "$CONTROLLER_POD:$REMOTE_DIR/.env" --no-preserve=true
            else
                kubectl cp "$envfile" "$CONTROLLER_POD:/workspace/.env" --no-preserve=true
            fi
        fi
    done

    # Inject API keys from local environment (they may not be in .env files)
    local env_append=""
    [ -n "${ANTHROPIC_API_KEY:-}" ] && env_append+="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"$'\n'
    [ -n "${OPENAI_API_KEY:-}" ]    && env_append+="OPENAI_API_KEY=${OPENAI_API_KEY}"$'\n'
    [ -n "${EXA_API_KEY:-}" ]       && env_append+="EXA_API_KEY=${EXA_API_KEY}"$'\n'
    if [ -n "$env_append" ]; then
        info "Injecting API keys from local environment..."
        kubectl exec -i "$CONTROLLER_POD" -- tee -a "$REMOTE_DIR/.env" > /dev/null <<< "$env_append"
    fi

    info "Code synced"
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
    local pid_file="/workspace/sweep-${sweep}.pid"

    # Write the sweep script to the pod (avoids shell escaping issues with nohup)
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
make full-sweep SWEEP=${sweep} MODEL_DIR=${model_dir} BENCHMARK=${benchmark} RUNS=${runs}"
    [ -n "$goal" ]  && script_body+=" GOAL=\"${goal}\""
    [ -n "$force" ] && script_body+=" FORCE=1"
    script_body+=$'\n'

    kubectl exec -i "$CONTROLLER_POD" -- tee "$script_file" > /dev/null <<< "$script_body"
    kubectl exec "$CONTROLLER_POD" -- chmod +x "$script_file"

    info "Starting sweep '${sweep}' on controller pod (${runs} runs, ${benchmark} benchmark)..."
    info "Logs: kubectl exec $CONTROLLER_POD -- tail -f $log_file"
    info ""

    # Run in background inside the pod so it survives if we disconnect
    kubectl exec "$CONTROLLER_POD" -- bash -c \
        "nohup $script_file > $log_file 2>&1 & echo \$! > $pid_file; echo \"Sweep PID: \$(cat $pid_file)\""

    info ""
    info "Sweep started in background on '$CONTROLLER_POD'"
    info ""
    info "Useful commands:"
    info "  make sweep-logs                           # tail live output"
    info "  make sweep-status                         # check if sweep is running"
    info "  make sync-results SWEEP=${sweep}          # copy results to local machine"
    info "  make sweep-remote-teardown                # delete controller pod"
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
        local remote_path="$REMOTE_DIR/results/sweep-${sweep}"
        local local_path="$local_results/sweep-${sweep}"
        info "Syncing sweep-${sweep} results from controller..."
        mkdir -p "$local_path"
        kubectl exec "$CONTROLLER_POD" -- tar czf - -C "$REMOTE_DIR/results" "sweep-${sweep}" 2>/dev/null \
            | tar xzf - -C "$local_results"
    else
        info "Syncing ALL results from controller..."
        kubectl exec "$CONTROLLER_POD" -- tar czf - -C "$REMOTE_DIR" results 2>/dev/null \
            | tar xzf - -C "$PROJECT_DIR"
    fi

    info "Results synced to $local_results"
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

    # Check for running sweeps
    local pids
    pids=$(kubectl exec "$CONTROLLER_POD" -- bash -c \
        'for f in /workspace/sweep-*.pid; do
            [ -f "$f" ] || continue
            pid=$(cat "$f")
            sweep=$(basename "$f" .pid | sed "s/^sweep-//")
            if kill -0 "$pid" 2>/dev/null; then
                echo "  RUNNING: $sweep (PID $pid)"
            else
                echo "  DONE:    $sweep (PID $pid)"
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

[ $# -ge 1 ] || die "Usage: $0 {start|sync|logs|status|teardown} [args...]"
ACTION="$1"; shift

case "$ACTION" in
    start)    action_start "$@" ;;
    sync)     action_sync "$@" ;;
    logs)     action_logs "$@" ;;
    status)   action_status "$@" ;;
    teardown) action_teardown "$@" ;;
    *)        die "Unknown action: $ACTION. Use: start, sync, logs, status, teardown" ;;
esac
