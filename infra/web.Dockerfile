# ClipMind 前端（Next.js）镜像
FROM node:24-alpine

WORKDIR /web

# 先装依赖（利用层缓存）。有 lock 用 npm ci，否则回退 npm install
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci || npm install

# 复制源码并构建
COPY apps/web ./
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000

# next start 绑定 0.0.0.0:3000（容器内）；对外仅由 compose 绑定 127.0.0.1
CMD ["npm", "run", "start"]
