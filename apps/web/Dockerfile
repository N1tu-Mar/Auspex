FROM node:22-slim
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/contracts/package.json packages/contracts/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter web...
COPY packages/contracts/generated packages/contracts/generated
COPY apps/web apps/web
USER node
EXPOSE 5173
CMD ["pnpm", "--filter", "web", "exec", "vite", "--host", "0.0.0.0"]
