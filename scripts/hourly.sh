#!/usr/bin/env bash
# Почасовая отметка прогресса — п. 5.4.8 и 5.9.2 Положения.
# Отсутствие подтверждённого результата по итогам ЛЮБОГО часа = дисквалификация.
#
# Использование:
#   ./scripts/hourly.sh "что сделали за этот час"
#
# Если делать нечего — всё равно коммитьте: обновите docs/PROGRESS.md,
# добавьте скриншот, схему, тест. Пустой час хуже кривого коммита.
set -euo pipefail

cd "$(dirname "$0")/.."

MSG="${1:-progress checkpoint}"
STAMP="$(date '+%Y-%m-%d %H:%M')"

mkdir -p docs
if [ ! -f docs/PROGRESS.md ]; then
  printf '# Журнал прогресса\n\n' > docs/PROGRESS.md
fi
printf -- '- **%s** — %s\n' "$STAMP" "$MSG" >> docs/PROGRESS.md

git add -A
if git diff --cached --quiet; then
  echo "Нечего коммитить — но отметка в docs/PROGRESS.md добавлена, повторяю."
  git add docs/PROGRESS.md
fi

git commit -m "checkpoint: ${MSG} (${STAMP})"
git push

echo "✓ Чекпойнт запушен: ${MSG}"
git log --oneline -1
