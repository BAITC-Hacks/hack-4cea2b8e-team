#!/usr/bin/env bash
# Настройка git для участника. Каждый запускает ОДИН раз после клонирования.
#
#   ./scripts/setup-git.sh "Имя Фамилия" почта@example.com
#
# Настраивает: авторство, шаблон сообщения, хук против утечки ключей,
# rebase при pull.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${1:-}"
EMAIL="${2:-}"

if [ -z "$NAME" ] || [ -z "$EMAIL" ]; then
  CUR_NAME=$(git config user.name || true)
  CUR_EMAIL=$(git config user.email || true)
  if [ -z "$CUR_NAME" ] || [ -z "$CUR_EMAIL" ]; then
    echo "Укажите имя и почту:"
    echo "  ./scripts/setup-git.sh \"Имя Фамилия\" почта@example.com"
    echo ""
    echo "Почта должна совпадать с той, что привязана к вашему GitHub —"
    echo "иначе коммиты не свяжутся с вашим аккаунтом, и вклад будет не виден."
    exit 1
  fi
  echo "Авторство уже настроено: $CUR_NAME <$CUR_EMAIL>"
else
  git config user.name "$NAME"
  git config user.email "$EMAIL"
  echo "Авторство: $NAME <$EMAIL>"
fi

git config commit.template .gitmessage
git config core.hooksPath .githooks
git config pull.rebase true
chmod +x .githooks/* 2>/dev/null || true

echo "Шаблон сообщения:  .gitmessage"
echo "Хуки:              .githooks/"
echo "pull:              всегда --rebase"
echo ""
echo "Готово. Проверьте, что вас видно в истории:  git shortlog -sn"
