FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json .
RUN npm install --legacy-peer-deps --include=optional

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public
ENV NEXT_TELEMETRY_DISABLED=1

ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

ARG MIDEASTTOURISM_API_INTERNAL_URL=http://mideasttourism-api:8002
ENV MIDEASTTOURISM_API_INTERNAL_URL=$MIDEASTTOURISM_API_INTERNAL_URL

RUN npm run build

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

EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3002/ || exit 1

CMD ["npm", "start"]
