# ============================================================================
# NovelScript Frontend — multi-stage Docker build (Node 24 + pnpm)
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — dependencies (pnpm store cache mount)
# ---------------------------------------------------------------------------
FROM node:24-alpine AS deps
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app

# Copy only manifests first → cached unless they change
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# --mount=type=cache keeps pnpm's global store across rebuilds
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# ---------------------------------------------------------------------------
# Stage 2 — build
# ---------------------------------------------------------------------------
FROM node:24-alpine AS builder
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app

COPY . .
COPY --from=deps /app/node_modules ./node_modules

RUN pnpm run build

# ---------------------------------------------------------------------------
# Stage 3 — production runtime
# ---------------------------------------------------------------------------
FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY --from=builder /app/build ./build

RUN corepack enable && corepack prepare pnpm@latest --activate
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --prod

EXPOSE 3000
CMD ["pnpm", "run", "start"]
