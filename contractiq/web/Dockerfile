# ContractIQ Web — standalone Next.js app
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --legacy-peer-deps --include=optional

FROM node:20-alpine AS builder
WORKDIR /app
RUN rm -f /usr/local/bin/yarn /usr/local/bin/yarnpkg && rm -rf /opt/yarn-* 2>/dev/null || true
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Create empty public dir if missing (Next.js expects it)
RUN mkdir -p public
ENV NEXT_TELEMETRY_DISABLED=1
# Build-time API URL for client-side bundles.
# Default is empty — the browser uses relative URLs like /api/contractiq/auth/login
# and Next.js server-side proxies them to CONTRACTIQ_API_INTERNAL_URL at runtime.
# This works identically for local dev (CIQ_API_INTERNAL_URL=http://localhost:8001)
# and in k8s (CIQ_API_INTERNAL_URL=http://contractiq-api:8001).
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# The rewrite destination in next.config.js is resolved at BUILD time in
# standalone mode. Set it here so the built server.js knows where to proxy
# /api/contractiq/* requests. For k8s this is the cluster-internal DNS;
# for local dev the default fallback in next.config.js handles it.
ARG CONTRACTIQ_API_INTERNAL_URL=http://contractiq-api:8001
ENV CONTRACTIQ_API_INTERNAL_URL=$CONTRACTIQ_API_INTERNAL_URL
ENV NODE_OPTIONS=--max-old-space-size=6144
RUN npm run build

FROM node:20-alpine AS runner
# The base image's Alpine packages trail the patched builds.
RUN apk upgrade --no-cache
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Copy built app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.js ./

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3001/ || exit 1

CMD ["npm", "start"]
