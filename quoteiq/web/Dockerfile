# QuoteIQ Web — Next.js on port 3008.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --legacy-peer-deps --include=optional

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
RUN chmod -R u+rwx node_modules/.bin 2>/dev/null || true
COPY . .
RUN mkdir -p public
ENV NEXT_TELEMETRY_DISABLED=1
ARG QUOTEIQ_API_INTERNAL_URL=http://quoteiq-api:8008
ENV QUOTEIQ_API_INTERNAL_URL=$QUOTEIQ_API_INTERNAL_URL
RUN npx next build

FROM node:20-alpine AS runner
# The base image's Alpine packages trail the patched builds.
RUN apk upgrade --no-cache
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.js ./
EXPOSE 3008
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3008/ || exit 1
CMD ["npm", "start"]
