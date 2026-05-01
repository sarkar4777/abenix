# ResolveAI Web — Next.js on port 3004.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --legacy-peer-deps

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public
ENV NEXT_TELEMETRY_DISABLED=1
ARG RESOLVEAI_API_INTERNAL_URL=http://resolveai-api:8004
ENV RESOLVEAI_API_INTERNAL_URL=$RESOLVEAI_API_INTERNAL_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.js ./
EXPOSE 3004
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3004/ || exit 1
CMD ["npm", "start"]
