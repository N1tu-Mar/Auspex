FROM node:22-slim
RUN corepack enable && install -d -o node -g node /repo
USER node
WORKDIR /repo
COPY --chown=node:node package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY --chown=node:node packages/contracts/package.json packages/contracts/
COPY --chown=node:node apps/web/package.json apps/web/
RUN CI=true pnpm install --frozen-lockfile --filter web...
COPY --chown=node:node packages/contracts/generated packages/contracts/generated
COPY --chown=node:node apps/web apps/web
EXPOSE 5173
CMD ["pnpm", "--filter", "web", "exec", "vite", "--host", "0.0.0.0"]
