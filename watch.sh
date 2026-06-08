#!/bin/bash
# watch.sh — Auto-deploy khi có file thay đổi (dùng LOCAL, không cần GitHub)
# Yêu cầu: brew install fswatch (Mac) hoặc apt install inotify-tools (Linux)
#
# Dùng: ./watch.sh
# Ctrl+C để dừng

echo "Watching for file changes... (Ctrl+C to stop)"

if command -v fswatch &> /dev/null; then
    # macOS
    fswatch -o --exclude ".git" --exclude "__pycache__" . | while read; do
        echo "Change detected → rebuilding..."
        docker compose build --no-cache
        docker compose up -d --force-recreate
        echo "Done: $(date)"
    done
elif command -v inotifywait &> /dev/null; then
    # Linux
    while inotifywait -r -e modify,create,delete \
        --exclude ".git|__pycache__|.pyc" .; do
        echo "Change detected → rebuilding..."
        docker compose build --no-cache
        docker compose up -d --force-recreate
        echo "Done: $(date)"
    done
else
    echo "Can't find fswatch or inotifywait."
    echo "Mac:   brew install fswatch"
    echo "Linux: apt install inotify-tools"
fi
