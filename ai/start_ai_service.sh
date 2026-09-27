#!/usr/bin/env bash
# ==============================================================================
# UCust AI: Master Production Contour Launcher (Full Stack Supervisor)
# ==============================================================================
# Запускает полный контур платформы:
#   1. ComfyUI Server (:8188) — движок генерации фото Qwen-Image 2512
#   2. Octopoda Server (:8741 / :7842) — мультиагентная память и дашборд
#   3. Celery Task Workers — асинхронные очереди (CPU/GPU)
#   4. FastAPI AI Service Gateway (:8000) — единый фасад и шлюз API
#
# Использование:
#   cd /opt/ucust && nohup bash start_ai_service.sh > ai_service.log 2>&1 &
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# 1. Определение директорий проекта
# ------------------------------------------------------------------------------
if [ -d "$SCRIPT_DIR/ai" ]; then
    ROOT_DIR="$SCRIPT_DIR"
    AI_DIR="$SCRIPT_DIR/ai"
else
    AI_DIR="$SCRIPT_DIR"
    ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

echo "===================================================================="
echo "🚀 UCUST AI: ЗАПУСК ПОЛНОГО КОММЕРЧЕСКОГО КОНТУРА (v2.7.0)"
echo "===================================================================="
echo "📁 Root Directory: $ROOT_DIR"
echo "📁 AI Directory:   $AI_DIR"

# ------------------------------------------------------------------------------
# 2. Загрузка переменных окружения (.env)
# ------------------------------------------------------------------------------
for env_candidate in "$ROOT_DIR/.env" "$AI_DIR/.env" "/opt/ucust/.env" "/opt/ucust/ai/.env"; do
    if [ -f "$env_candidate" ]; then
        echo "📄 Загрузка переменных окружения из: $env_candidate"
        # shellcheck disable=SC1090
        set -a
        source "$env_candidate"
        set +a
        break
    fi
done

# Стандартные дефолты
export PYTHONIOENCODING=utf-8
export AI_SERVICE_HOST="${AI_SERVICE_HOST:-0.0.0.0}"
export AI_SERVICE_PORT="${AI_SERVICE_PORT:-8000}"
export ENABLE_NEURAL_MODELS="${ENABLE_NEURAL_MODELS:-1}"
export INTERNAL_API_SECRET="${INTERNAL_API_SECRET:-ucust-super-secret-service-token-2026}"
export COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
export COMFYUI_PORT="${COMFYUI_PORT:-8188}"
export OCTOPODA_BASE_URL="${OCTOPODA_BASE_URL:-http://127.0.0.1:8741}"
export OCTOPODA_API_KEY="${OCTOPODA_API_KEY:-local-dev}"
export OCTOPODA_MODE="${OCTOPODA_MODE:-auto}"

# ------------------------------------------------------------------------------
# 3. Поиск и активация виртуального окружения (Python venv)
# ------------------------------------------------------------------------------
VENV_FOUND=""
for candidate in \
    "/opt/ucust/venv" \
    "/opt/ucust/ai/venv" \
    "$ROOT_DIR/venv" \
    "$ROOT_DIR/.venv" \
    "$AI_DIR/venv" \
    "$AI_DIR/.venv" \
    "$HOME/venv" \
    "$HOME/.venv"; do
    if [ -f "$candidate/bin/activate" ]; then
        VENV_FOUND="$candidate"
        break
    fi
done

if [ -n "$VENV_FOUND" ]; then
    echo "🔍 Найдено виртуальное окружение: $VENV_FOUND"
    # shellcheck disable=SC1090
    source "$VENV_FOUND/bin/activate"
    PYTHON_CMD="python3"
else
    echo "⚠️ Виртуальное окружение не найдено, используется системный python3."
    PYTHON_CMD="python3"
fi

echo "🐍 Python Interpreter: $($PYTHON_CMD -c 'import sys; print(sys.executable)') ($($PYTHON_CMD --version 2>&1))"

# ------------------------------------------------------------------------------
# 4. Обработка сигналов и корректное завершение (Graceful Shutdown)
# ------------------------------------------------------------------------------
declare -a CHILD_PIDS=()

cleanup() {
    echo ""
    echo "===================================================================="
    echo "🛑 Остановка всех процессов контура UCust AI..."
    echo "===================================================================="
    for pid in "${CHILD_PIDS[@]}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "   🔌 Завершение дочернего процесса PID: $pid"
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo "✅ Все сервисы контура успешно остановлены."
}

trap cleanup SIGINT SIGTERM SIGHUP EXIT

# Утилита освобождения порта
free_port() {
    local port="$1"
    local name="$2"
    local running_pid
    running_pid=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$running_pid" ]; then
        echo "   ⚠️ Порт $port ($name) занят PID: $running_pid. Освобождаем..."
        kill -9 $running_pid 2>/dev/null || true
        sleep 1
    fi
}

echo "🧹 Проверка и очистка сетевых портов..."
free_port "$AI_SERVICE_PORT" "AI Gateway"
free_port "$COMFYUI_PORT" "ComfyUI"
free_port 8741 "Octopoda API"
free_port 7842 "Octopoda Dashboard"
free_port 7843 "Octopoda Smart Proxy"

# ------------------------------------------------------------------------------
# 5. Подсистема 1: ComfyUI Server (Qwen-Image 2512 & Realism Engine)
# ------------------------------------------------------------------------------
COMFY_DIR=""
for candidate_comfy in \
    "${COMFYUI_DIR:-}" \
    "/opt/ucust/ComfyUI" \
    "/opt/ucust/ai/ComfyUI" \
    "$ROOT_DIR/ComfyUI" \
    "$AI_DIR/ComfyUI" \
    "$ROOT_DIR/../ComfyUI"; do
    if [ -n "$candidate_comfy" ] && [ -f "$candidate_comfy/main.py" ]; then
        COMFY_DIR="$candidate_comfy"
        break
    fi
done

if [ -n "$COMFY_DIR" ]; then
    echo "--------------------------------------------------------------------"
    echo "🎨 [1/4] Запуск ComfyUI Server ($COMFY_DIR) на порту $COMFYUI_PORT..."
    mkdir -p "$ROOT_DIR/output/photos" "$AI_DIR/output/photos" "$COMFY_DIR/output"
    
    COMFY_LOG="$AI_DIR/comfy.log"
    (
        cd "$COMFY_DIR"
        exec "$PYTHON_CMD" main.py --listen 0.0.0.0 --port "$COMFYUI_PORT" --fast > "$COMFY_LOG" 2>&1
    ) &
    COMFY_PID=$!
    CHILD_PIDS+=("$COMFY_PID")
    echo "   🟢 ComfyUI запущен в фоне (PID: $COMFY_PID, Log: $COMFY_LOG)"
else
    echo "⚠️ [1/4] Директория ComfyUI с main.py не найдена. AI Gateway будет использовать fast-fail / CPU rule-based fallback."
fi

# ------------------------------------------------------------------------------
# 6. Подсистема 2: Octopoda Multi-Agent Core & Dashboard
# ------------------------------------------------------------------------------
echo "--------------------------------------------------------------------"
echo "🐙 [2/4] Запуск Octopoda Multi-Agent Runtime & Dashboard..."

OCTOPODA_LOG="$AI_DIR/octopoda.log"

if $PYTHON_CMD -c "import synrix_runtime" 2>/dev/null; then
    (
        cd "$AI_DIR"
        exec "$PYTHON_CMD" -m synrix_runtime.start > "$OCTOPODA_LOG" 2>&1
    ) &
    OCTOPODA_PID=$!
    CHILD_PIDS+=("$OCTOPODA_PID")
    echo "   🟢 Octopoda Core запущена в фоне (PID: $OCTOPODA_PID, Log: $OCTOPODA_LOG)"
elif [ -f "$AI_DIR/integration/octopoda_dashboard.py" ]; then
    (
        cd "$AI_DIR"
        exec "$PYTHON_CMD" -m uvicorn integration.octopoda_dashboard:app --host 0.0.0.0 --port 7842 > "$OCTOPODA_LOG" 2>&1
    ) &
    OCTOPODA_PID=$!
    CHILD_PIDS+=("$OCTOPODA_PID")
    echo "   🟢 Octopoda Dashboard запущен в фоне (PID: $OCTOPODA_PID, Port: 7842)"
else
    echo "   ℹ️ Octopoda автономно работает через встроенный SQLite memory store: $AI_DIR/octopoda_memory.db"
fi

# ------------------------------------------------------------------------------
# 7. Подсистема 3: Celery Task Worker (Асинхронные очереди)
# ------------------------------------------------------------------------------
echo "--------------------------------------------------------------------"
echo "⚡ [3/4] Проверка Celery и распределенной очереди задач..."

if $PYTHON_CMD -c "import celery" 2>/dev/null && [ -f "$AI_DIR/celery_tasks.py" ]; then
    CELERY_LOG="$AI_DIR/celery.log"
    (
        cd "$AI_DIR"
        exec "$PYTHON_CMD" -m celery -A celery_tasks worker --loglevel=info -Q ucust_ai_queue,ucust_gpu_render --concurrency=2 > "$CELERY_LOG" 2>&1
    ) &
    CELERY_PID=$!
    CHILD_PIDS+=("$CELERY_PID")
    echo "   🟢 Celery Workers запущены в фоне (PID: $CELERY_PID, Log: $CELERY_LOG)"
else
    echo "   ℹ️ Фоновая очередь работает через встроенный In-Memory AsyncQueueManager."
fi

# ------------------------------------------------------------------------------
# 8. Подсистема 4: FastAPI AI Service Gateway (Главный процесс)
# ------------------------------------------------------------------------------
echo "--------------------------------------------------------------------"
echo "🌐 [4/4] Запуск FastAPI AI Service Gateway (:8000)..."
echo "===================================================================="
echo "✅ Контур успешно инициализирован:"
echo "   • AI Gateway:     http://$AI_SERVICE_HOST:$AI_SERVICE_PORT"
echo "   • Swagger UI:     http://$AI_SERVICE_HOST:$AI_SERVICE_PORT/docs"
echo "   • OpenAPI JSON:   http://$AI_SERVICE_HOST:$AI_SERVICE_PORT/openapi.json"
echo "   • Smart Ideas:    http://$AI_SERVICE_HOST:$AI_SERVICE_PORT/api/v1/ideas/placeholders"
echo "   • ComfyUI Server: http://$COMFYUI_HOST:$COMFYUI_PORT"
echo "   • Health Check:   http://$AI_SERVICE_HOST:$AI_SERVICE_PORT/api/v1/ai/health"
echo "===================================================================="

cd "$AI_DIR"

# Запуск основного API Gateway
exec "$PYTHON_CMD" api_gateway.py
