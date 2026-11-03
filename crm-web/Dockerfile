FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY client/package.json client/package-lock.json ./client/
RUN npm --prefix client ci
COPY client ./client
RUN npm run build
COPY server ./server

FROM node:24-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/server ./server
COPY --from=build /app/client/dist ./client/dist
USER 10001:10001
EXPOSE 8787
CMD ["node","server/index.js"]
