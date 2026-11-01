#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${GH_PAT:?Set GH_PAT in the environment}"
npm run build -- --base=/sentinel-spatial/
mkdir -p .pages-work
export GIT_ASKPASS="$PWD/.pages-work/askpass.sh" GIT_TERMINAL_PROMPT=0
printf '#!/bin/sh\ncase "$1" in *Username*) echo x-access-token;; *) printf "%%s" "$GH_PAT";; esac\n' > "$GIT_ASKPASS"
chmod 700 "$GIT_ASKPASS"
remote=https://github.com/Zakee47/sentinel-spatial.git
if [ ! -d .pages-work/repo/.git ]; then
  git init .pages-work/repo
fi
git -C .pages-work/repo fetch "$remote" gh-pages 2>/dev/null && git -C .pages-work/repo checkout -B gh-pages FETCH_HEAD || git -C .pages-work/repo checkout --orphan gh-pages
find .pages-work/repo -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R dist/. .pages-work/repo/
touch .pages-work/repo/.nojekyll
git -C .pages-work/repo add .
git -C .pages-work/repo diff --cached --quiet || git -C .pages-work/repo commit -m "Deploy Sentinel dashboard"
git -C .pages-work/repo push "$remote" HEAD:gh-pages
status=$(curl -sS -o .pages-work/pages.json -w '%{http_code}' -H "Authorization: Bearer $GH_PAT" -H 'Accept: application/vnd.github+json' https://api.github.com/repos/Zakee47/sentinel-spatial/pages)
if [ "$status" = 404 ]; then
  curl --fail-with-body -sS -X POST -H "Authorization: Bearer $GH_PAT" -H 'Accept: application/vnd.github+json' https://api.github.com/repos/Zakee47/sentinel-spatial/pages -d '{"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}' >/dev/null
elif [ "$status" != 200 ]; then
  echo "Pages settings unavailable (HTTP $status)" >&2; exit 1
fi
echo 'https://zakee47.github.io/sentinel-spatial/?replay=demo.jsonl'
