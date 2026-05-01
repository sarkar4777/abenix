#!/bin/sh
# Next.js standalone with npm workspaces preserves workspace path
# server.js is at /app/apps/web/server.js inside the standalone output
if [ -f /app/apps/web/server.js ]; then
  cd /app && node apps/web/server.js &
elif [ -f /app/server.js ]; then
  cd /app && node server.js &
else
  echo "ERROR: Cannot find server.js" && exit 1
fi
exec nginx -g "daemon off;"
