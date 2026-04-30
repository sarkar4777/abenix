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
RUN npm run build --workspace=@abenix/web

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

# Copy standalone output (server.js lives at /app/server.js)
COPY --from=builder /app/apps/web/.next/standalone ./
# Copy node_modules that standalone tracing missed (workspace hoisting issue)
COPY --from=builder /app/node_modules ./node_modules
# Next.js standalone server reads static from `${__dirname}/.next/static`
# Since server.js is at /app, static must be at /app/.next/static (not /app/apps/web/.next/static)
COPY --from=builder /app/apps/web/.next/static ./.next/static
COPY --from=builder /app/apps/web/public ./public

EXPOSE 3000
ENV PORT=3000 HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
