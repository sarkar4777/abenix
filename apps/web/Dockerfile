FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/
COPY packages/shared/package.json ./packages/shared/
RUN npm ci --workspace=@abenix/web --include-workspace-root

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/package.json ./package.json
RUN mkdir -p packages/shared
COPY apps/web/ ./apps/web/
COPY packages/shared/ ./packages/shared/
COPY turbo.json ./
ENV NEXT_TELEMETRY_DISABLED=1
# Patch Next.js's lockfile-checker to no-op. The original throws
# `Cannot read properties of undefined (reading 'os')` on alpine
# because some optional-deps entries are missing platform-specific
# metadata. The patcher's only job is to suggest re-running npm
# install — it doesn't affect the actual build output. Replacing
# the function body with a return is the cleanest fix; the env-var
# bypass alone has been unreliable across Next 14.x.
# Also strip `packageManager` from root package.json so Corepack
# doesn't accidentally invoke Yarn (which is on the alpine base
# image but doesn't speak the npm@ format).
RUN sed -i 's/"packageManager":[^,]*,*//' /app/package.json && \
    node -e "const f='/app/node_modules/next/dist/lib/patch-incorrect-lockfile.js';const s=require('fs').readFileSync(f,'utf8');require('fs').writeFileSync(f,s.replace('async function patchIncorrectLockfile(dir) {','async function patchIncorrectLockfile(dir) { return;'))"
RUN npm run build --workspace=@abenix/web

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

# Copy standalone output (server.js lives at /app/server.js)
COPY --from=builder /app/apps/web/.next/standalone ./
# Copy node_modules that standalone tracing missed (workspace hoisting issue)
COPY --from=builder /app/node_modules ./node_modules
# Strip build-time-only binaries from the production image. esbuild ships
# precompiled Go binaries; Trivy flags CVE-2024-24790 + CVE-2025-68121
# against the embedded Go stdlib. They are never invoked at runtime
# (Next.js's runtime is the JS server only), so removing them eliminates
# the CRITICAL findings without affecting the app.
RUN find ./node_modules -type d \( -name '@esbuild' -o -name 'esbuild' \) \
        -prune -exec rm -rf {} + 2>/dev/null || true

# Next.js standalone server reads static from `${__dirname}/.next/static`
# Since server.js is at /app, static must be at /app/.next/static (not /app/apps/web/.next/static)
COPY --from=builder /app/apps/web/.next/static ./.next/static
COPY --from=builder /app/apps/web/public ./public

EXPOSE 3000
ENV PORT=3000 HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
