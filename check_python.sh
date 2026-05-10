#!/bin/bash
# Скрипт проверки Python для Git Bash

echo "===================================="
echo "Проверка Python"
echo "===================================="
echo ""

# Проверка через PATH
echo "1. Поиск Python в PATH..."
if command -v python &> /dev/null; then
    echo "[OK] python найден:"
    python --version
    PYTHON_CMD="python"
elif command -v py &> /dev/null; then
    echo "[OK] py launcher найден:"
    py --version
    PYTHON_CMD="py"
elif command -v python3 &> /dev/null; then
    echo "[OK] python3 найден:"
    python3 --version
    PYTHON_CMD="python3"
else
    echo "[ОШИБКА] Python не найден в PATH"
    PYTHON_CMD=""
fi

echo ""

# Поиск установок Python
echo "2. Поиск установок Python на диске..."
PYTHON_PATHS=(
    "/c/Python313/python.exe"
    "/c/Python312/python.exe"
    "/c/Python311/python.exe"
    "/c/Python310/python.exe"
    "/c/Users/$USER/AppData/Local/Programs/Python/Python313/python.exe"
    "/c/Users/$USER/AppData/Local/Programs/Python/Python312/python.exe"
    "/c/Users/$USER/AppData/Local/Programs/Python/Python311/python.exe"
    "/c/Program Files/Python313/python.exe"
    "/c/Program Files/Python312/python.exe"
    "/c/Program Files/Python311/python.exe"
)

FOUND_PYTHON=""
for path in "${PYTHON_PATHS[@]}"; do
    if [ -f "$path" ]; then
        echo "[OK] Найден: $path"
        "$path" --version 2>&1
        FOUND_PYTHON="$path"
        break
    fi
done

if [ -z "$FOUND_PYTHON" ]; then
    echo "[ПРЕДУПРЕЖДЕНИЕ] python.exe не найден в стандартных местах"
fi

echo ""
echo "===================================="
echo "Результат проверки"
echo "===================================="
echo ""

if [ -n "$PYTHON_CMD" ]; then
    echo "[OK] Python доступен через команду: $PYTHON_CMD"
    echo ""
    echo "Проверка pip..."
    $PYTHON_CMD -m pip --version 2>&1
    echo ""
    echo "[OK] Всё готово! Можете запускать install.bat"
elif [ -n "$FOUND_PYTHON" ]; then
    echo "[ПРЕДУПРЕЖДЕНИЕ] Python найден, но не в PATH"
    echo "Расположение: $FOUND_PYTHON"
    echo ""
    echo "Нужно добавить Python в PATH или использовать полный путь"
else
    echo "[ОШИБКА] Python не найден!"
    echo ""
    echo "Установите Python:"
    echo "1. Откройте: https://www.python.org/downloads/"
    echo "2. Скачайте последнюю версию"
    echo "3. При установке отметьте 'Add Python to PATH'"
fi

echo ""
read -p "Нажмите Enter для выхода..."
